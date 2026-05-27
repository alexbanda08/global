"""Score microprice panel — Tasks 2-5, v2 with proper lockbox.

Improvements over v1:
  - Use OOS files (which have direction+pnl_legacy_usd+gate cols) directly for
    lockbox sleeve definitions instead of fragile ret_2m proxies.
  - Use prefix_fires.parquet (Apr 24 -> May 1) for early-period data so we span
    full Apr 24 -> May 25.
  - Sleeves now defined by ACTUAL gate combos that match real production sleeves
    (from R3 catalog + FULL_WINDOW_ALL_SLEEVES).
"""
from __future__ import annotations
import sys, os, time, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
WORK = ROOT / "strategy_lab" / "microprice_2026_05_26"
WORK.mkdir(exist_ok=True)

MP_PANEL = OUT_DIR / "microprice_panel.parquet"

# Window edges (UTC) — STRICT 3-way split
TRAIN_END_S = int(pd.Timestamp("2026-05-15T00:00:00Z").value // 1_000_000_000)
VAL_END_S   = int(pd.Timestamp("2026-05-22T00:00:00Z").value // 1_000_000_000)
# train: ... -> May 15 (~20d if start = Apr 24)
# val:   May 15 -> May 22 (7d)
# lockbox: May 22 -> May 25 (5d) but cleaner: use last full lockbox window from OOS files


def load_unified_fire_table():
    """Load full unified fire table from prefix + hybrid + OOS.

    Returns DataFrame with columns:
      asset, slug, tf, fire_us, fire_offset_s, outcome, ws_s,
      direction (UP/DOWN), pnl_up, pnl_dn (legacy 2%-on-profit),
      up_fill_ok, dn_fill_ok,
      gate columns (g_rf_with, g_ribbon_agrees, etc.)
    """
    parts = []

    # PREFIX (Apr 24 -> May 1) — same schema as OOS
    pref = OUT_DIR / "_full_window_2026_05_26" / "prefix_fires.parquet"
    if pref.exists():
        d = pd.read_parquet(pref)
        d["src"] = "prefix"
        parts.append(d)
        print(f"prefix fires: {len(d)} ({pd.to_datetime(d.fire_us.min()/1e6, unit='s')} -> {pd.to_datetime(d.fire_us.max()/1e6, unit='s')})")

    # HYBRID (Apr 30 -> May 23)
    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    hyb = pd.concat([fr5, fr15], ignore_index=True)
    hyb["src"] = "hybrid"
    # hybrid doesn't have direction/won — we'll synthesize by joining ret_2m
    parts.append(hyb)
    print(f"hybrid fires: {len(hyb)} ({pd.to_datetime(hyb.fire_us.min()/1e6, unit='s')} -> {pd.to_datetime(hyb.fire_us.max()/1e6, unit='s')})")

    # OOS (May 22 -> May 25)
    oos_parts = []
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            p = OUT_DIR / "_full_window_2026_05_26" / f"oos_fires_{asset}_{tf}.parquet"
            if p.exists():
                d = pd.read_parquet(p)
                d["src"] = "oos"
                oos_parts.append(d)
    if oos_parts:
        oos = pd.concat(oos_parts, ignore_index=True)
        parts.append(oos)
        print(f"oos fires: {len(oos)} ({pd.to_datetime(oos.fire_us.min()/1e6, unit='s')} -> {pd.to_datetime(oos.fire_us.max()/1e6, unit='s')})")

    fires = pd.concat(parts, ignore_index=True)

    # Dedup boundary overlap by (slug, fire_us, fire_offset_s, outcome, direction)
    # When duplicate, keep the OOS row (richest schema)
    src_priority = {"oos": 3, "prefix": 2, "hybrid": 1}
    fires["_pri"] = fires.src.map(src_priority)
    fires = fires.sort_values(["asset", "slug", "fire_us", "fire_offset_s", "outcome", "_pri"], ascending=[True]*5 + [False])
    fires = fires.drop_duplicates(["asset", "slug", "fire_us", "fire_offset_s", "outcome"], keep="first")
    fires = fires.drop(columns=["_pri"])
    print(f"unified fires after dedup: {len(fires)}")

    # Compute legacy pnl for hybrid rows (which don't have pnl_legacy_usd)
    # Use up_shares, up_usd, dn_shares, dn_usd from hybrid; for OOS/prefix use pnl_legacy_usd
    if "pnl_legacy_usd" not in fires.columns:
        fires["pnl_legacy_usd"] = np.nan
    if "direction" not in fires.columns:
        fires["direction"] = np.nan
    if "won" not in fires.columns:
        fires["won"] = np.nan

    # For hybrid rows, compute UP and DN PnL legs and store as two columns
    # (We'll bet UP for direction=='UP' and bet DN for direction=='DOWN' downstream)
    # For OOS/prefix, only one direction-leg available per row (with pnl_legacy_usd).
    # Build pnl_up, pnl_dn arrays.
    pnl_up = np.full(len(fires), np.nan)
    pnl_dn = np.full(len(fires), np.nan)
    # OOS/prefix: pnl_legacy_usd attached to chosen direction
    is_oosp = fires.src.isin(("oos", "prefix")).values
    dir_arr = fires.direction.values.astype(str)
    pnl_leg = fires.pnl_legacy_usd.values
    pnl_up = np.where(is_oosp & (dir_arr == "UP"), pnl_leg, pnl_up)
    pnl_dn = np.where(is_oosp & (dir_arr == "DOWN"), pnl_leg, pnl_dn)

    # Hybrid: compute legacy PnL on each leg from up_shares/up_usd/dn_shares/dn_usd
    is_hyb = (fires.src == "hybrid").values
    if "up_shares" in fires.columns:
        u_sh = fires.up_shares.values
        u_us = fires.up_usd.values
        u_ok = fires.up_fill_ok.values == True if "up_fill_ok" in fires.columns else np.full(len(fires), False)
        won_up = (fires.outcome.values == "Up")
        gross = u_sh - u_us
        pnl_u_won = gross - np.where(gross > 0, gross * 0.02, 0.0)
        pnl_u_lost = -u_us
        pnl_u_hyb = np.where(won_up, pnl_u_won, pnl_u_lost)
        pnl_u_hyb = np.where(u_ok, pnl_u_hyb, np.nan)
        pnl_up = np.where(is_hyb, pnl_u_hyb, pnl_up)
    if "dn_shares" in fires.columns:
        d_sh = fires.dn_shares.values
        d_us = fires.dn_usd.values
        d_ok = fires.dn_fill_ok.values == True if "dn_fill_ok" in fires.columns else np.full(len(fires), False)
        won_dn = (fires.outcome.values == "Down")
        gross = d_sh - d_us
        pnl_d_won = gross - np.where(gross > 0, gross * 0.02, 0.0)
        pnl_d_lost = -d_us
        pnl_d_hyb = np.where(won_dn, pnl_d_won, pnl_d_lost)
        pnl_d_hyb = np.where(d_ok, pnl_d_hyb, np.nan)
        pnl_dn = np.where(is_hyb, pnl_d_hyb, pnl_dn)
    fires["pnl_up"] = pnl_up
    fires["pnl_dn"] = pnl_dn
    print(f"pnl_up not null: {np.isfinite(pnl_up).sum()}; pnl_dn not null: {np.isfinite(pnl_dn).sum()}")
    return fires


def merge_with_microprice(fires, mp):
    """Inner-join on canonical fire key."""
    cols_mp = [c for c in mp.columns if c not in ("asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome", "ws_s")]
    keep_mp_cols = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome"] + cols_mp
    out = fires.merge(mp[keep_mp_cols], on=["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome"], how="left")
    print(f"merged: {len(out)} rows, mp_skew not null: {out.mp_skew.notna().sum()}")
    return out


# -----------------------------------------------------------------
# Define top sleeves using REAL gate combos from R3 catalog + production
# -----------------------------------------------------------------
def define_sleeves(p):
    """Return dict[sleeve_name] -> (mask_bool_series, direction_array_str).

    Sleeves are direction-aware. For OOS/prefix rows, direction comes from the
    'direction' column. For hybrid rows, we need to choose direction — for
    proxy sleeves we'll use ret_2m_at_ws sign. Note: hybrid rows can have
    EITHER UP or DOWN bet legitimately so for "production sleeve replication"
    we mostly want OOS/prefix logic.

    Strategy: define sleeve_mask THAT requires OOS/prefix rows (so direction is
    set by production) PLUS hybrid rows where ret_2m_at_ws is defined.
    For hybrid rows, only bet WITH ret_2m direction.
    """
    sleeves = {}

    # Set up direction array: from 'direction' col (oos/prefix) or from ret_2m_at_ws sign (hybrid)
    dir_arr = np.where(p.src.values == "hybrid",
                       np.where(p.ret_2m_at_ws.values > 0, "UP", "DOWN"),
                       p.direction.values.astype(str))

    # --- Sleeve 1: BTC S6 5m off=60-150 hybrid_v1 ---
    # Gate stack: cci ∧ stoch ∧ rf ∧ tr_above_ema50 ∧ ribbon
    g_btc_s6 = ((p.asset == "BTC") & (p.tf == "5m") & (p.fire_offset_s.isin([60, 90, 120, 150])) &
                (p.g_cci_with == True) & (p.g_stoch_with == True) & (p.g_rf_with == True) &
                (p.g_tr_above_ema50 == True) & (p.g_ribbon_agrees == True))
    sleeves["btc_5m_s6_hybrid_v1"] = (g_btc_s6, dir_arr)

    # --- Sleeve 2: ETH S6 5m off=60-150 hybrid_v1 ---
    # Gate stack: cci ∧ bb_pos ∧ ribbon
    g_eth_s6 = ((p.asset == "ETH") & (p.tf == "5m") & (p.fire_offset_s.isin([60, 90, 120, 150])) &
                (p.g_cci_with == True) & (p.g_bb_pos_with == True) & (p.g_ribbon_agrees == True))
    sleeves["eth_5m_s6_hybrid_v1"] = (g_eth_s6, dir_arr)

    # --- Sleeve 3: BTC S15 5m off=60-150 hybrid_v1 (different gate stack) ---
    g_btc_s15 = ((p.asset == "BTC") & (p.tf == "5m") & (p.fire_offset_s.isin([60, 90, 120, 150])) &
                 (p.g_rf_with == True) & (p.g_ribbon_agrees == True) & (p.g_tr_above_ema50 == True) &
                 (p.g_stoch_with == True))
    sleeves["btc_5m_s15_hybrid_v1"] = (g_btc_s15, dir_arr)

    # --- Sleeve 4: ETH 15m off=60-120 momo ---
    g_eth_15m_off = ((p.asset == "ETH") & (p.tf == "15m") & (p.fire_offset_s.isin([60, 120])) &
                     (p.g_ribbon_agrees == True) & (p.g_rf_with == True))
    sleeves["eth_15m_off60_120"] = (g_eth_15m_off, dir_arr)

    # --- Sleeve 5: BTC S7 15m off=480-840 — trend stack ---
    g_btc_s7 = ((p.asset == "BTC") & (p.tf == "15m") & (p.fire_offset_s.isin([480, 600, 720, 840])) &
                (p.g_tr_stack_with == True) & (p.g_tr_above_ema800 == True) & (p.g_ribbon_agrees == True))
    sleeves["btc_15m_s7_off_late"] = (g_btc_s7, dir_arr)

    # --- Sleeve 6: ETH S1.5 5m off=150-240 ---
    g_eth_s15 = ((p.asset == "ETH") & (p.tf == "5m") & (p.fire_offset_s.isin([150, 180, 210, 240])) &
                 (p.g_ribbon_agrees == True) & (p.g_tr_above_ema200 == True) & (p.g_stoch_with == True))
    sleeves["eth_5m_s15_off_mid"] = (g_eth_s15, dir_arr)

    # --- Sleeve 7: BTC S1.5 5m off=150-240 ---
    g_btc_s15_mid = ((p.asset == "BTC") & (p.tf == "5m") & (p.fire_offset_s.isin([150, 180, 210, 240])) &
                     (p.g_tr_above_pp == True) & (p.g_ribbon_agrees == True) & (p.g_stoch_with == True))
    sleeves["btc_5m_s15_off_mid"] = (g_btc_s15_mid, dir_arr)

    # --- Sleeve 8: SOL S6 5m off=60-150 (with caveats - SOL micro is noisy) ---
    g_sol_s6 = ((p.asset == "SOL") & (p.tf == "5m") & (p.fire_offset_s.isin([60, 90, 120, 150])) &
                (p.g_mfi_with == True) & (p.g_within_dev == True) & (p.g_bb_pos_with == True) &
                (p.g_ribbon_agrees == True))
    sleeves["sol_5m_s6"] = (g_sol_s6, dir_arr)

    # --- Sleeve 9: BTC momo broad (V7-like) — RF + PVSRA + MFI ---
    g_btc_v7 = ((p.asset == "BTC") & (p.tf == "5m") &
                (p.g_rf_with == True) & (p.g_mfi_with == True))
    sleeves["btc_5m_v7"] = (g_btc_v7, dir_arr)

    # --- Sleeve 10: ETH momo broad (V7-like) ---
    g_eth_v7 = ((p.asset == "ETH") & (p.tf == "5m") &
                (p.g_rf_with == True) & (p.g_mfi_with == True))
    sleeves["eth_5m_v7"] = (g_eth_v7, dir_arr)

    # --- Sleeve 11: ETH 15m S7 -- 480-840 trend ---
    g_eth_s7 = ((p.asset == "ETH") & (p.tf == "15m") & (p.fire_offset_s.isin([480, 600, 720, 840])) &
                (p.g_dev_extreme == True) & (p.g_tr_above_pp == True))
    sleeves["eth_15m_s7_late"] = (g_eth_s7, dir_arr)

    # --- Sleeve 12: BTC 15m sniper-style (mid-window) ---
    g_btc_15m_snip = ((p.asset == "BTC") & (p.tf == "15m") & (p.fire_offset_s.isin([120, 240, 360, 480])) &
                      (p.g_ribbon_agrees == True))
    sleeves["btc_15m_sniper"] = (g_btc_15m_snip, dir_arr)

    # --- Sleeve 13: SOL S7 15m off=480-840 ---
    g_sol_s7 = ((p.asset == "SOL") & (p.tf == "15m") & (p.fire_offset_s.isin([480, 600, 720, 840])) &
                (p.g_rf_aged == True) & (p.g_tr_within_adr == True) & (p.g_tr_above_pp == True))
    sleeves["sol_15m_s7_late"] = (g_sol_s7, dir_arr)

    # --- Sleeve 14: Universal RF+ribbon momo (5m, all assets) ---
    g_univ = ((p.tf == "5m") & (p.g_rf_with == True) & (p.g_ribbon_agrees == True))
    sleeves["univ_5m_rf_ribbon"] = (g_univ, dir_arr)

    # --- Sleeve 15: All UP bets ---
    sleeves["all_bet_up"] = (p.src.isin(("oos", "prefix")).values | (p.src == "hybrid").values, dir_arr)
    sleeves["all_bet_dn"] = sleeves["all_bet_up"]  # same mask, used for both UP/DOWN

    return sleeves


# -----------------------------------------------------------------
# Gate evaluator
# -----------------------------------------------------------------
def gate_eval(panel_view, direction_arr, gname):
    """Returns bool array indicating gate passes per (fire, direction)."""
    s = panel_view
    d_up = (direction_arr == "UP")
    d_dn = (direction_arr == "DOWN")
    if gname == "ALL":
        return np.full(len(s), True)
    if gname == "g_mp_skew_with":
        return ((d_up & (s.mp_skew.values > 0)) | (d_dn & (s.mp_skew.values < 0)))
    if gname == "g_mp_skew_strong_with":
        return ((d_up & (s.mp_skew.values > 20)) | (d_dn & (s.mp_skew.values < -20)))
    if gname == "g_mp_change_with":
        return ((d_up & (s.mp_skew_change_500ms.values > 0)) | (d_dn & (s.mp_skew_change_500ms.values < 0)))
    if gname == "g_mp_both_favor_bet":
        return ((d_up & (s.mp_up_dev_bps.values > 0) & (s.mp_dn_dev_bps.values < 0)) |
                (d_dn & (s.mp_up_dev_bps.values < 0) & (s.mp_dn_dev_bps.values > 0)))
    if gname == "g_mp_skew_extreme_against":
        return ((d_up & (s.mp_skew.values < -50)) | (d_dn & (s.mp_skew.values > 50)))
    if gname == "g_mp_no_extreme":
        return (np.abs(s.mp_skew.values) < 50)
    if gname == "g_mp_weighted_skew_with":
        return ((d_up & (s.mp_weighted_skew.values > 0)) | (d_dn & (s.mp_weighted_skew.values < 0)))
    if gname == "g_mp_weighted_strong_with":
        return ((d_up & (s.mp_weighted_skew.values > 20)) | (d_dn & (s.mp_weighted_skew.values < -20)))
    if gname == "g_mp_imbalance_with":
        return ((d_up & (s.mp_imbalance.values > 0.2)) | (d_dn & (s.mp_imbalance.values < -0.2)))
    if gname == "g_mp_imbalance_extreme":
        return ((d_up & (s.mp_imbalance.values > 0.5)) | (d_dn & (s.mp_imbalance.values < -0.5)))
    raise ValueError(f"unknown gate {gname}")


GATES = ["g_mp_skew_with", "g_mp_skew_strong_with", "g_mp_change_with",
         "g_mp_both_favor_bet", "g_mp_skew_extreme_against", "g_mp_no_extreme",
         "g_mp_weighted_skew_with", "g_mp_weighted_strong_with",
         "g_mp_imbalance_with", "g_mp_imbalance_extreme"]


# -----------------------------------------------------------------
# TASK 2 — Standalone direction rules
# -----------------------------------------------------------------
def task2_standalone(p):
    """5 candidate rules — using OOS+prefix fires (where direction is real production)
    PLUS hybrid (where direction = ret_2m sign as fallback) for max sample."""
    rows = []
    # For standalone, we IGNORE existing direction and synthesize bet direction from the rule
    p = p.copy()
    rule_dirs = {}
    rule_dirs["MP-A"] = np.where(p.mp_skew > 0, "UP", np.where(p.mp_skew < 0, "DOWN", "Skip"))
    rule_dirs["MP-B"] = np.where(p.mp_imbalance > 0.3, "UP",
                                  np.where(p.mp_imbalance < -0.3, "DOWN", "Skip"))
    cond_up = (p.mp_up_dev_bps > 10) & (p.mp_dn_dev_bps < -10)
    cond_dn = (p.mp_up_dev_bps < -10) & (p.mp_dn_dev_bps > 10)
    rule_dirs["MP-C"] = np.where(cond_up, "UP", np.where(cond_dn, "DOWN", "Skip"))
    rule_dirs["MP-D"] = np.where(p.mp_skew_change_500ms > 5, "UP",
                                  np.where(p.mp_skew_change_500ms < -5, "DOWN", "Skip"))
    cond_up_e = (p.mp_skew < -50)
    cond_dn_e = (p.mp_skew > 50)
    rule_dirs["MP-E"] = np.where(cond_up_e, "UP", np.where(cond_dn_e, "DOWN", "Skip"))

    # Compute pnl_up, pnl_dn for fires where we have BOTH legs OR the chosen leg
    # For hybrid rows, both legs computable; for OOS/prefix, only the chosen direction has pnl
    pnl_up = p.pnl_up.values
    pnl_dn = p.pnl_dn.values
    outcomes = p.outcome.values

    for rule, rd in rule_dirs.items():
        for asset in ("BTC", "ETH", "SOL", "ALL"):
            for tf in ("5m", "15m", "ALL"):
                base_mask = np.full(len(p), True)
                if asset != "ALL":
                    base_mask &= (p.asset.values == asset)
                if tf != "ALL":
                    base_mask &= (p.tf.values == tf)
                up_take = base_mask & (rd == "UP") & np.isfinite(pnl_up)
                dn_take = base_mask & (rd == "DOWN") & np.isfinite(pnl_dn)
                p_up = pnl_up[up_take]
                p_dn = pnl_dn[dn_take]
                if len(p_up) + len(p_dn) < 30:
                    continue
                pnl = np.concatenate([p_up, p_dn])
                won_up = ((outcomes[up_take] == "Up"))
                won_dn = ((outcomes[dn_take] == "Down"))
                wins = won_up.sum() + won_dn.sum()
                n = len(pnl)
                wr = wins / n
                rows.append({
                    "rule": rule, "asset": asset, "tf": tf,
                    "n": int(n), "wr": float(wr),
                    "dpt": float(pnl.mean()), "sum_pnl": float(pnl.sum()),
                })
    return pd.DataFrame(rows).sort_values("dpt", ascending=False)


# -----------------------------------------------------------------
# TASK 3 — Gate overlay on sleeves
# -----------------------------------------------------------------
def task3_gate_overlay(p):
    """For each sleeve × gate × split (full/train/lockbox), compute lift."""
    sleeves = define_sleeves(p)
    pnl_up = p.pnl_up.values
    pnl_dn = p.pnl_dn.values
    outcomes = p.outcome.values
    fire_s = (p.fire_us.values // 1_000_000)

    train_mask = fire_s < TRAIN_END_S
    val_mask = (fire_s >= TRAIN_END_S) & (fire_s < VAL_END_S)
    lock_mask = fire_s >= VAL_END_S

    def split_stats(idx_mask, pnl_array, won_array):
        v = idx_mask & np.isfinite(pnl_array)
        if v.sum() == 0:
            return (0, np.nan, np.nan, 0.0)
        return (int(v.sum()), float(won_array[v].mean()), float(pnl_array[v].mean()), float(pnl_array[v].sum()))

    rows = []
    for sleeve, (mask, dir_arr) in sleeves.items():
        # mask might be a Series or array
        mask_v = np.asarray(mask).astype(bool)
        dir_v = np.asarray(dir_arr).astype(str)

        # For each fire in sleeve, the bet direction is dir_v[i]
        # PnL: if dir==UP, use pnl_up; if dir==DOWN, use pnl_dn
        bet_up = (dir_v == "UP")
        bet_dn = (dir_v == "DOWN")
        pnl_taken = np.where(bet_up, pnl_up, np.where(bet_dn, pnl_dn, np.nan))
        won = np.where(bet_up, outcomes == "Up", np.where(bet_dn, outcomes == "Down", False))

        # Baseline (no microprice gate)
        full_base = mask_v & np.isfinite(pnl_taken)
        if full_base.sum() < 30:
            continue
        n_b, wr_b, dpt_b, sum_b = split_stats(mask_v, pnl_taken, won)
        n_b_tr, wr_b_tr, dpt_b_tr, sum_b_tr = split_stats(mask_v & train_mask, pnl_taken, won)
        n_b_vl, wr_b_vl, dpt_b_vl, sum_b_vl = split_stats(mask_v & val_mask, pnl_taken, won)
        n_b_lk, wr_b_lk, dpt_b_lk, sum_b_lk = split_stats(mask_v & lock_mask, pnl_taken, won)

        # Each gate
        for g in GATES:
            gpass = gate_eval(p, dir_v, g)
            # require mp_skew non-null (otherwise gate is undefined)
            mp_ok = p.mp_skew.notna().values
            gate_mask = mask_v & mp_ok & gpass
            if (gate_mask & np.isfinite(pnl_taken)).sum() < 20:
                continue
            n_g, wr_g, dpt_g, sum_g = split_stats(gate_mask, pnl_taken, won)
            n_g_tr, wr_g_tr, dpt_g_tr, sum_g_tr = split_stats(gate_mask & train_mask, pnl_taken, won)
            n_g_vl, wr_g_vl, dpt_g_vl, sum_g_vl = split_stats(gate_mask & val_mask, pnl_taken, won)
            n_g_lk, wr_g_lk, dpt_g_lk, sum_g_lk = split_stats(gate_mask & lock_mask, pnl_taken, won)
            rows.append({
                "sleeve": sleeve, "gate": g,
                "n_base": n_b, "wr_base": wr_b, "dpt_base": dpt_b, "sum_base": sum_b,
                "n_gate": n_g, "wr_gate": wr_g, "dpt_gate": dpt_g, "sum_gate": sum_g,
                "dpt_lift": dpt_g - dpt_b,
                "wr_lift": wr_g - wr_b,
                "keep_pct": n_g / max(1, n_b),
                "n_train": n_g_tr, "wr_train": wr_g_tr, "dpt_train": dpt_g_tr, "sum_train": sum_g_tr,
                "n_val": n_g_vl, "wr_val": wr_g_vl, "dpt_val": dpt_g_vl, "sum_val": sum_g_vl,
                "n_lockbox": n_g_lk, "wr_lockbox": wr_g_lk, "dpt_lockbox": dpt_g_lk, "sum_lockbox": sum_g_lk,
                # Base in same splits for comparison
                "n_base_lockbox": n_b_lk, "wr_base_lockbox": wr_b_lk,
                "dpt_base_lockbox": dpt_b_lk, "sum_base_lockbox": sum_b_lk,
            })
    return pd.DataFrame(rows)


# -----------------------------------------------------------------
# TASK 4 — Strict 3-way validation + bootstrap
# -----------------------------------------------------------------
def task4_validation(t3df, p):
    """For top combos by train dpt_train, verify with 200-shuffle bootstrap on lockbox."""
    rng = np.random.default_rng(42)
    # Select top combos: those with dpt_train > 0 AND n_train >= 30 AND wr_train >= 0.55
    cand = t3df[(t3df.dpt_train > 0) & (t3df.n_train >= 30) & (t3df.wr_train >= 0.55)].copy()
    cand = cand.sort_values("dpt_train", ascending=False).head(30)
    print(f"Task 4: {len(cand)} candidate combos to validate")

    sleeves = define_sleeves(p)
    pnl_up = p.pnl_up.values
    pnl_dn = p.pnl_dn.values
    outcomes = p.outcome.values
    fire_s = (p.fire_us.values // 1_000_000)
    train_mask = fire_s < TRAIN_END_S
    val_mask = (fire_s >= TRAIN_END_S) & (fire_s < VAL_END_S)
    lock_mask = fire_s >= VAL_END_S

    rows = []
    for _, c in cand.iterrows():
        sleeve = c.sleeve; gname = c.gate
        if sleeve not in sleeves:
            continue
        mask, dir_arr = sleeves[sleeve]
        mask_v = np.asarray(mask).astype(bool)
        dir_v = np.asarray(dir_arr).astype(str)
        bet_up = (dir_v == "UP")
        bet_dn = (dir_v == "DOWN")
        pnl_taken = np.where(bet_up, pnl_up, np.where(bet_dn, pnl_dn, np.nan))
        won = np.where(bet_up, outcomes == "Up", np.where(bet_dn, outcomes == "Down", False))
        gpass = gate_eval(p, dir_v, gname)
        mp_ok = p.mp_skew.notna().values
        full = mask_v & mp_ok & gpass & np.isfinite(pnl_taken)
        if full.sum() < 30:
            continue
        lk = full & lock_mask
        if lk.sum() < 10:
            continue
        lk_pnl = pnl_taken[lk]
        lk_won = won[lk]

        full_pnl = pnl_taken[full]
        # Bootstrap: under null (random pnl ordering), draw n_lk samples and compute mean
        n_lk = lk.sum()
        null_dpts = np.empty(200)
        for i in range(200):
            sample = rng.choice(full_pnl, size=n_lk, replace=True)
            null_dpts[i] = sample.mean()
        actual_dpt = lk_pnl.mean()
        boot_p = float(np.mean(null_dpts >= actual_dpt))
        boot_ci5 = float(np.percentile(null_dpts, 5))
        boot_ci95 = float(np.percentile(null_dpts, 95))

        deployable = bool(lk_pnl.sum() > 0 and lk_won.mean() >= 0.65 and boot_p <= 0.05 and n_lk >= 20)
        rows.append({
            "sleeve": sleeve, "gate": gname,
            "n_train": c.n_train, "wr_train": c.wr_train, "dpt_train": c.dpt_train, "sum_train": c.sum_train,
            "n_val": c.n_val, "wr_val": c.wr_val, "dpt_val": c.dpt_val, "sum_val": c.sum_val,
            "n_lockbox": int(n_lk), "wr_lockbox": float(lk_won.mean()),
            "dpt_lockbox": float(actual_dpt), "sum_lockbox": float(lk_pnl.sum()),
            "boot_p": boot_p, "boot_ci5_dpt": boot_ci5, "boot_ci95_dpt": boot_ci95,
            "deployable": deployable,
        })
    return pd.DataFrame(rows).sort_values("dpt_lockbox", ascending=False)


# -----------------------------------------------------------------
# TASK 5 — MP vs L1 imbalance comparison
# -----------------------------------------------------------------
def task5_mp_vs_l1(p):
    """Compare microprice signals to L1 book imbalance from existing microstructure panel."""
    ms = pd.read_parquet(OUT_DIR / "microstructure_panel.parquet")
    keep_l1 = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome",
               "up_imb1", "up_imb5", "up_imb25", "imb5_diff", "imb1_diff",
               "up_micro_dev_bps", "dn_micro_dev_bps", "micro_dev_diff"]
    keep_l1 = [c for c in keep_l1 if c in ms.columns]
    m = p.merge(ms[keep_l1], on=["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome"],
                how="inner", suffixes=("", "_l1ms"))
    print(f"task5 merge: {len(m)} rows")

    # Correlations
    out = {}
    both_ok = m.mp_skew.notna() & m.imb5_diff.notna()
    if both_ok.sum() > 100:
        out["corr_mp_skew_vs_imb5_diff"] = float(m.loc[both_ok, "mp_skew"].corr(m.loc[both_ok, "imb5_diff"]))
        out["corr_mp_skew_vs_imb1_diff"] = float(m.loc[both_ok, "mp_skew"].corr(m.loc[both_ok, "imb1_diff"]))
    both_micro = m.mp_skew.notna() & m.micro_dev_diff.notna()
    if both_micro.sum() > 100:
        out["corr_mp_skew_vs_micro_dev_diff_L1"] = float(m.loc[both_micro, "mp_skew"].corr(m.loc[both_micro, "micro_dev_diff"]))
    both_w = m.mp_skew.notna() & m.mp_weighted_skew.notna()
    if both_w.sum() > 100:
        out["corr_mp_skew_simple_vs_weighted"] = float(m.loc[both_w, "mp_skew"].corr(m.loc[both_w, "mp_weighted_skew"]))

    # Head-to-head: L1 imb5_with vs MP skew_with vs MP weighted_skew_with vs MP change_with
    # All applied to FULL universe in a directional bet
    rule_rows = []
    rules = {
        "L1_imb5_with":         np.where(m.imb5_diff > 0, "UP", np.where(m.imb5_diff < 0, "DOWN", "Skip")),
        "MP_skew_with":         np.where(m.mp_skew > 0, "UP", np.where(m.mp_skew < 0, "DOWN", "Skip")),
        "MP_weighted_skew_with":np.where(m.mp_weighted_skew > 0, "UP", np.where(m.mp_weighted_skew < 0, "DOWN", "Skip")),
        "MP_change_with":       np.where(m.mp_skew_change_500ms > 0, "UP", np.where(m.mp_skew_change_500ms < 0, "DOWN", "Skip")),
        "L1_micro_dev_with":    np.where(m.micro_dev_diff > 0, "UP", np.where(m.micro_dev_diff < 0, "DOWN", "Skip")),
    }
    pnl_up_a = m.pnl_up.values
    pnl_dn_a = m.pnl_dn.values
    out_arr = m.outcome.values
    for rname, rd in rules.items():
        for asset in ("BTC", "ETH", "SOL", "ALL"):
            for tf in ("5m", "15m", "ALL"):
                base = np.full(len(m), True)
                if asset != "ALL":
                    base &= (m.asset.values == asset)
                if tf != "ALL":
                    base &= (m.tf.values == tf)
                up_take = base & (rd == "UP") & np.isfinite(pnl_up_a)
                dn_take = base & (rd == "DOWN") & np.isfinite(pnl_dn_a)
                p_u = pnl_up_a[up_take]
                p_d = pnl_dn_a[dn_take]
                pnl = np.concatenate([p_u, p_d])
                n = len(pnl)
                if n < 100:
                    continue
                wins = (out_arr[up_take] == "Up").sum() + (out_arr[dn_take] == "Down").sum()
                rule_rows.append({
                    "rule": rname, "asset": asset, "tf": tf,
                    "n": int(n), "wr": float(wins/n),
                    "dpt": float(pnl.mean()), "sum_pnl": float(pnl.sum()),
                })
    rules_df = pd.DataFrame(rule_rows)

    # Joint regime: are L1 and MP independent signals?
    joint_rows = []
    # When BOTH say UP, only L1, only MP, neither — for UP bets
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            sub = m[(m.asset == asset) & (m.tf == tf) & np.isfinite(pnl_up_a) & m.mp_skew.notna() & m.imb5_diff.notna()]
            if len(sub) < 200:
                continue
            pnl_s = sub.pnl_up.values
            won_s = (sub.outcome.values == "Up")
            l1_p = sub.imb5_diff.values > 0
            mp_p = sub.mp_skew.values > 0
            for name, msk in [("both_pos", l1_p & mp_p),
                              ("only_L1", l1_p & ~mp_p),
                              ("only_MP", ~l1_p & mp_p),
                              ("neither", ~l1_p & ~mp_p)]:
                if msk.sum() < 30:
                    continue
                joint_rows.append({
                    "asset": asset, "tf": tf, "bet": "UP", "regime": name,
                    "n": int(msk.sum()), "wr": float(won_s[msk].mean()),
                    "dpt": float(pnl_s[msk].mean()),
                })
    joint_df = pd.DataFrame(joint_rows)
    return out, rules_df, joint_df


# -----------------------------------------------------------------
# Main
# -----------------------------------------------------------------
def main():
    import builtins
    _print = builtins.print
    def fp(*a, **k):
        k.setdefault('flush', True)
        _print(*a, **k)
    builtins.print = fp

    print("=== Load + merge ===")
    fires = load_unified_fire_table()
    mp = pd.read_parquet(MP_PANEL)
    p = merge_with_microprice(fires, mp)

    print("\n=== TASK 2: standalone direction rules ===")
    df2 = task2_standalone(p)
    df2.to_csv(WORK / "task2_standalone_rules_v2.csv", index=False)
    print(f"Saved task2 ({len(df2)} rows)")
    print("Top 15 by dpt (n>=300):")
    print(df2[df2.n >= 300].head(15).to_string(index=False))

    print("\n=== TASK 3: gate overlays with split metrics ===")
    df3 = task3_gate_overlay(p)
    df3.to_csv(WORK / "task3_gate_overlay_v2.csv", index=False)
    print(f"Saved task3 ({len(df3)} rows)")
    print("Top 20 by dpt_lift (n_train>=30):")
    cols_print = ["sleeve","gate","n_base","wr_base","dpt_base","sum_base",
                  "n_gate","wr_gate","dpt_gate","sum_gate","dpt_lift","wr_lift",
                  "n_train","wr_train","dpt_train",
                  "n_lockbox","wr_lockbox","dpt_lockbox","sum_lockbox"]
    show = df3[(df3.n_train >= 30) & (df3.n_lockbox >= 10)].sort_values("dpt_lift", ascending=False).head(20)
    print(show[cols_print].to_string(index=False))

    print("\n=== TASK 4: 3-way validation w/ bootstrap ===")
    df4 = task4_validation(df3, p)
    df4.to_csv(WORK / "task4_three_way_validation_v2.csv", index=False)
    print(f"Saved task4 ({len(df4)} rows)")
    print(f"Deployable (lockbox sum>0, WR>=65%, p<=0.05, n>=20): {df4.deployable.sum()}/{len(df4)}")
    print("\nTop 15 by dpt_lockbox:")
    print(df4.head(15).to_string(index=False))
    if df4.deployable.sum() > 0:
        print("\nDEPLOYABLE:")
        print(df4[df4.deployable].to_string(index=False))

    print("\n=== TASK 5: MP vs L1 imbalance ===")
    corrs, rdf, jdf = task5_mp_vs_l1(p)
    print("Correlations:")
    for k, v in corrs.items():
        print(f"  {k}: {v:.4f}")
    rdf.to_csv(WORK / "task5_rules_v2.csv", index=False)
    jdf.to_csv(WORK / "task5_joint_v2.csv", index=False)
    with open(WORK / "task5_correlations_v2.json", "w") as f:
        json.dump(corrs, f, indent=2)
    print("\nHead-to-head rules:")
    print(rdf.sort_values(["asset", "tf", "rule"]).to_string(index=False))
    print("\nJoint regime test (UP bets):")
    print(jdf.to_string(index=False))

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
