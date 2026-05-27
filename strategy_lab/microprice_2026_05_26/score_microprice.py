"""Score microprice panel — Tasks 2, 3, 4, 5.

Loads microprice_panel.parquet + merges with hybrid_fire_universe to get fill data.
Computes pnl per fire under LegacyConfig (2% on profit, winning leg only).

Then:
  TASK 2 — Standalone direction rules (A-E)
  TASK 3 — Microprice gates overlaid on top sleeves (and basic UP/DN universes)
  TASK 4 — Strict 3-way split (train/val/lockbox) with bootstrap on top combos
  TASK 5 — Microprice vs L1 imbalance comparison
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

PANEL = OUT_DIR / "microprice_panel.parquet"


# -----------------------------------------------------------------
# Load + merge w/ fire universe for fill/outcome data
# -----------------------------------------------------------------
def load_panel_with_pnl():
    """Load microprice panel + merge fill/outcome data + add pnl_up/pnl_dn."""
    mp = pd.read_parquet(PANEL)
    print(f"microprice panel: {len(mp)} rows")

    # Hybrid fire universe = Apr 30 -> May 23
    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fr5, fr15], ignore_index=True)

    # OOS fires (May 22-25) — column scheme is different
    oos_parts = []
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            p = OUT_DIR / "_full_window_2026_05_26" / f"oos_fires_{asset}_{tf}.parquet"
            if p.exists():
                d = pd.read_parquet(p)
                oos_parts.append(d)
    oos = pd.concat(oos_parts, ignore_index=True) if oos_parts else pd.DataFrame()
    print(f"oos fires: {len(oos)}")
    # OOS has pnl_legacy_usd, direction, won, entry_vwap already
    # Need to convert to up_/dn_ filll columns for compatibility with hybrid universe
    # OOS represents *one* direction per row; mark up_fill_ok or dn_fill_ok per direction
    if len(oos):
        oos["up_fill_ok"] = oos.direction.str.upper() == "UP"
        oos["dn_fill_ok"] = oos.direction.str.upper() == "DOWN"
        # PnL fields: when UP-direction-row, set pnl_up = pnl_legacy_usd; pnl_dn missing
        oos["pnl_up_legacy"] = np.where(oos.direction.str.upper() == "UP", oos.pnl_legacy_usd, np.nan)
        oos["pnl_dn_legacy"] = np.where(oos.direction.str.upper() == "DOWN", oos.pnl_legacy_usd, np.nan)
        # Approximate fill notional: if entry_vwap known, usd = $25 by convention
        oos["up_usd"] = np.where(oos.up_fill_ok, 25.0, np.nan)
        oos["dn_usd"] = np.where(oos.dn_fill_ok, 25.0, np.nan)
        oos["up_vwap"] = np.where(oos.up_fill_ok, oos.entry_vwap, np.nan)
        oos["dn_vwap"] = np.where(oos.dn_fill_ok, oos.entry_vwap, np.nan)
        # shares = usd / vwap
        with np.errstate(divide="ignore", invalid="ignore"):
            oos["up_shares"] = np.where((oos.up_fill_ok) & (oos.up_vwap > 0), oos.up_usd / oos.up_vwap, np.nan)
            oos["dn_shares"] = np.where((oos.dn_fill_ok) & (oos.dn_vwap > 0), oos.dn_usd / oos.dn_vwap, np.nan)

    # Concat the two universes; hybrid has BOTH legs, OOS has the chosen direction
    # For merging, use (asset, slug, tf, fire_us, fire_offset_s, outcome) as key.
    # In hybrid universe each row is unique on key; in OOS, can be 1-2 rows per fire (one per direction).
    # We need ONE row per (asset, slug, tf, fire_us, fire_offset_s, outcome) — collapse OOS direction-rows
    if len(oos):
        # Aggregate OOS to one row per key: max up/dn flags, take first non-null vwap/shares/usd
        keep_cols = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome",
                     "up_fill_ok", "dn_fill_ok",
                     "up_usd", "up_vwap", "up_shares",
                     "dn_usd", "dn_vwap", "dn_shares",
                     "pnl_up_legacy", "pnl_dn_legacy"]
        oos_agg = oos.groupby(["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome"]).agg({
            "up_fill_ok": "max", "dn_fill_ok": "max",
            "up_usd": "max", "up_vwap": "max", "up_shares": "max",
            "dn_usd": "max", "dn_vwap": "max", "dn_shares": "max",
            "pnl_up_legacy": "max", "pnl_dn_legacy": "max",
        }).reset_index()
        # Mark source
        fires["src"] = "hybrid"
        oos_agg["src"] = "oos"
        # Filter OOS not already in hybrid (some boundary overlap may exist)
        hyb_keys = set(zip(fires.asset, fires.slug, fires.tf, fires.fire_us, fires.fire_offset_s, fires.outcome))
        new_mask = ~oos_agg.apply(lambda r: (r.asset, r.slug, r.tf, int(r.fire_us), int(r.fire_offset_s), r.outcome) in hyb_keys, axis=1)
        oos_agg = oos_agg[new_mask]
        # Get the missing columns to align with hybrid
        for c in fires.columns:
            if c not in oos_agg.columns:
                oos_agg[c] = np.nan
        oos_agg = oos_agg[fires.columns]
        all_fires = pd.concat([fires, oos_agg], ignore_index=True)
    else:
        all_fires = fires
        all_fires["src"] = "hybrid"
        all_fires["pnl_up_legacy"] = np.nan
        all_fires["pnl_dn_legacy"] = np.nan
    print(f"total fires (hybrid + oos new): {len(all_fires)}")

    # Merge microprice with fires on (asset, slug, tf, fire_us, fire_offset_s, outcome)
    fire_cols = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome",
                 "up_fill_ok", "dn_fill_ok",
                 "up_vwap", "up_shares", "up_usd",
                 "dn_vwap", "dn_shares", "dn_usd",
                 "src", "pnl_up_legacy", "pnl_dn_legacy"]
    fire_cols = [c for c in fire_cols if c in all_fires.columns]
    m = mp.merge(all_fires[fire_cols], on=["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome"], how="left")
    print(f"after merge: {len(m)} rows")
    print(f"  with up_fill_ok: {(m.up_fill_ok == True).sum()}")
    print(f"  with dn_fill_ok: {(m.dn_fill_ok == True).sum()}")

    # Compute legacy pnl_up, pnl_dn vectorized
    # For OOS, use pnl_*_legacy if present, else compute
    shares_up = m.up_shares.values
    usd_up = m.up_usd.values
    won_up = (m.outcome.values == "Up")
    gross_up = shares_up - usd_up
    pnl_up_won = gross_up - np.where(gross_up > 0, gross_up * 0.02, 0.0)
    pnl_up_lost = -usd_up
    pnl_up = np.where(won_up, pnl_up_won, pnl_up_lost)
    pnl_up = np.where(m.up_fill_ok == True, pnl_up, np.nan)
    # Override with OOS pre-computed if available
    if "pnl_up_legacy" in m.columns:
        oos_up = m.pnl_up_legacy.notna()
        pnl_up = np.where(oos_up, m.pnl_up_legacy.values, pnl_up)
    m["pnl_up"] = pnl_up

    shares_dn = m.dn_shares.values
    usd_dn = m.dn_usd.values
    won_dn = (m.outcome.values == "Down")
    gross_dn = shares_dn - usd_dn
    pnl_dn_won = gross_dn - np.where(gross_dn > 0, gross_dn * 0.02, 0.0)
    pnl_dn_lost = -usd_dn
    pnl_dn = np.where(won_dn, pnl_dn_won, pnl_dn_lost)
    pnl_dn = np.where(m.dn_fill_ok == True, pnl_dn, np.nan)
    if "pnl_dn_legacy" in m.columns:
        oos_dn = m.pnl_dn_legacy.notna()
        pnl_dn = np.where(oos_dn, m.pnl_dn_legacy.values, pnl_dn)
    m["pnl_dn"] = pnl_dn
    print(f"pnl_up not null: {m.pnl_up.notna().sum()}; pnl_dn not null: {m.pnl_dn.notna().sum()}")
    return m


# -----------------------------------------------------------------
# TASK 2 — Standalone direction rules
# -----------------------------------------------------------------
def task2_standalone(p):
    """Five candidate rules from the spec:
       MP-A: bet UP when mp_skew > 0
       MP-B: bet WITH mp_imbalance sign when |mp_imbalance| > 0.3
       MP-C: bet UP when mp_up_dev_bps > 10 AND mp_dn_dev_bps < -10
       MP-D: bet WITH mp_skew_change_500ms sign
       MP-E: bet AGAINST extreme mp_skew (>50bps OR <-50bps) — mean revert
    """
    rows = []

    # Helper to evaluate one rule
    def eval_rule(rule_name, dir_col):
        for asset in ("BTC", "ETH", "SOL", "ALL"):
            for tf in ("5m", "15m", "ALL"):
                for off in (("ALL",) + tuple(sorted(p.fire_offset_s.dropna().unique()))):
                    sub = p
                    if asset != "ALL":
                        sub = sub[sub.asset == asset]
                    if tf != "ALL":
                        sub = sub[sub.tf == tf]
                    if off != "ALL":
                        sub = sub[sub.fire_offset_s == off]
                    if len(sub) < 30:
                        continue
                    # Fires where rule fired
                    up_mask = (sub[dir_col] == "Up") & (sub.up_fill_ok == True)
                    dn_mask = (sub[dir_col] == "Down") & (sub.dn_fill_ok == True)
                    up_pnl = sub.loc[up_mask, "pnl_up"].dropna()
                    dn_pnl = sub.loc[dn_mask, "pnl_dn"].dropna()
                    pnl = pd.concat([up_pnl, dn_pnl], ignore_index=True)
                    n_total = len(pnl)
                    if n_total < 30:
                        continue
                    wins_up = ((sub[dir_col] == "Up") & (sub.outcome == "Up") & (sub.up_fill_ok == True)).sum()
                    wins_dn = ((sub[dir_col] == "Down") & (sub.outcome == "Down") & (sub.dn_fill_ok == True)).sum()
                    wr = (wins_up + wins_dn) / (up_mask.sum() + dn_mask.sum())
                    rows.append({
                        "rule": rule_name, "asset": asset, "tf": tf, "fire_offset_s": str(off),
                        "n": int(n_total),
                        "wr": float(wr),
                        "dpt": float(pnl.mean()),
                        "sum_pnl": float(pnl.sum()),
                    })

    p = p.copy()
    # MP-A
    p["A_dir"] = np.where(p.mp_skew > 0, "Up", np.where(p.mp_skew < 0, "Down", "Skip"))
    eval_rule("MP-A", "A_dir")
    # MP-B
    p["B_dir"] = np.where((p.mp_imbalance > 0.3), "Up",
                  np.where((p.mp_imbalance < -0.3), "Down", "Skip"))
    eval_rule("MP-B", "B_dir")
    # MP-C
    cond_up = (p.mp_up_dev_bps > 10) & (p.mp_dn_dev_bps < -10)
    cond_dn = (p.mp_up_dev_bps < -10) & (p.mp_dn_dev_bps > 10)
    p["C_dir"] = np.where(cond_up, "Up", np.where(cond_dn, "Down", "Skip"))
    eval_rule("MP-C", "C_dir")
    # MP-D
    p["D_dir"] = np.where(p.mp_skew_change_500ms > 5, "Up",
                  np.where(p.mp_skew_change_500ms < -5, "Down", "Skip"))
    eval_rule("MP-D", "D_dir")
    # MP-E (mean revert from extreme)
    cond_up_e = (p.mp_skew < -50)   # extreme negative skew -> bet UP (revert)
    cond_dn_e = (p.mp_skew > 50)
    p["E_dir"] = np.where(cond_up_e, "Up", np.where(cond_dn_e, "Down", "Skip"))
    eval_rule("MP-E", "E_dir")

    df = pd.DataFrame(rows).sort_values("dpt", ascending=False)
    return df


# -----------------------------------------------------------------
# TASK 3 — Microprice gates as overlays on top sleeves
# -----------------------------------------------------------------
# Top sleeves from FINAL_CONSOLIDATED_REPORT + Round3 winners (15 sleeves).
# Each sleeve = (name, mask_function, direction_function) given a panel p.
def define_top_sleeves(p):
    """Return dict[sleeve_name] -> (mask: bool Series, direction: 'Up'/'Down' Series).

    Sleeves derived from fire_universe data already merged into the panel
    (ret_2m_at_ws, mag_ratio, vwap_since_open_bps, prod_q90) — note these
    come from hybrid_fire_universe ONLY (NOT OOS — OOS doesn't have ret_2m).
    For sleeves needing those cols, restrict to src=='hybrid'.
    """
    sleeves = {}
    # Pull in ret_2m and mag_ratio from hybrid_fire_universe
    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fr5, fr15], ignore_index=True)
    keep = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome",
            "ret_2m_at_ws", "mag_ratio", "vwap_since_open_bps", "prod_q90"]
    sup = p.merge(fires[keep], on=["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome"], how="left")

    # 1. BTC S6 5m hybrid_v1 (off=60-150): high-mag momo + RF + ribbon — fallback: |ret_2m|>=0.0005 mag>=2 BTC 5m 60-150
    btc_s6 = (sup.asset == "BTC") & (sup.tf == "5m") & (sup.fire_offset_s.isin([60, 90, 120, 150])) & \
             (sup.ret_2m_at_ws.abs() >= 0.0005) & (sup.mag_ratio >= 2.0)
    sleeves["btc_5m_s6_hybrid_v1_proxy"] = (btc_s6, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 2. ETH S6 5m hybrid_v1 (off=60-150): same shape on ETH
    eth_s6 = (sup.asset == "ETH") & (sup.tf == "5m") & (sup.fire_offset_s.isin([60, 90, 120, 150])) & \
             (sup.ret_2m_at_ws.abs() >= 0.0005) & (sup.mag_ratio >= 2.0)
    sleeves["eth_5m_s6_hybrid_v1_proxy"] = (eth_s6, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 3. BTC S15 5m hybrid_v1 (off=60-150): momo "v1"
    btc_s15 = (sup.asset == "BTC") & (sup.tf == "5m") & (sup.fire_offset_s.isin([60, 90, 120, 150])) & \
              (sup.ret_2m_at_ws.abs() >= 0.0003) & (sup.mag_ratio >= 1.5)
    sleeves["btc_5m_s15_hybrid_v1_proxy"] = (btc_s15, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 4. ETH 15m off=60-120: momo on 15m
    eth_15m_off = (sup.asset == "ETH") & (sup.tf == "15m") & (sup.fire_offset_s.isin([60, 120])) & \
                  (sup.ret_2m_at_ws.abs() >= 0.0005) & (sup.mag_ratio >= 1.5)
    sleeves["eth_15m_off60_120_proxy"] = (eth_15m_off, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 5. BTC S7 15m off=480-840: trend-stack momo
    btc_s7 = (sup.asset == "BTC") & (sup.tf == "15m") & (sup.fire_offset_s.isin([480, 600, 720, 840])) & \
             (sup.ret_2m_at_ws.abs() >= 0.0005)
    sleeves["btc_15m_s7_off_late_proxy"] = (btc_s7, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 6. ETH momo_v2_anywhere 15m — broad
    eth_15m_momo = (sup.asset == "ETH") & (sup.tf == "15m") & \
                   (sup.ret_2m_at_ws.abs() >= 0.0005) & (sup.mag_ratio >= 1.5)
    sleeves["eth_15m_momo_v2_anywhere_proxy"] = (eth_15m_momo, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 7. SOL S6 5m 60-150: high WR (92.9%) Cyclops-style
    sol_s6 = (sup.asset == "SOL") & (sup.tf == "5m") & (sup.fire_offset_s.isin([60, 90, 120, 150])) & \
             (sup.ret_2m_at_ws.abs() >= 0.0008) & (sup.mag_ratio >= 2.0)
    sleeves["sol_5m_s6_proxy"] = (sol_s6, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 8. ETH momo_extreme 15m (high mag, |ret|>=0.0015, mag>=3)
    eth_extreme = (sup.asset == "ETH") & (sup.tf == "15m") & \
                  (sup.ret_2m_at_ws.abs() >= 0.0015) & (sup.mag_ratio >= 3.0)
    sleeves["eth_15m_momo_extreme_proxy"] = (eth_extreme, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 9. BTC 5m momo broad (V7 standalone proxy)
    btc_5m_momo = (sup.asset == "BTC") & (sup.tf == "5m") & \
                  (sup.ret_2m_at_ws.abs() >= 0.0005)
    sleeves["btc_5m_momo_v7_proxy"] = (btc_5m_momo, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 10. ETH 5m momo broad
    eth_5m_momo = (sup.asset == "ETH") & (sup.tf == "5m") & \
                  (sup.ret_2m_at_ws.abs() >= 0.0005)
    sleeves["eth_5m_momo_v7_proxy"] = (eth_5m_momo, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 11. SOL 5m momo broad
    sol_5m_momo = (sup.asset == "SOL") & (sup.tf == "5m") & \
                  (sup.ret_2m_at_ws.abs() >= 0.0005)
    sleeves["sol_5m_momo_v7_proxy"] = (sol_5m_momo, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 12. BTC 15m sniper-style: mid-window offsets 120-480 with momo
    btc_15m_sniper = (sup.asset == "BTC") & (sup.tf == "15m") & \
                     (sup.fire_offset_s.isin([120, 240, 360, 480])) & \
                     (sup.ret_2m_at_ws.abs() >= 0.0003)
    sleeves["btc_15m_sniper_proxy"] = (btc_15m_sniper, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 13. All 5m momo (cross-asset)
    all_5m = (sup.tf == "5m") & (sup.ret_2m_at_ws.abs() >= 0.0005) & (sup.mag_ratio >= 2.0)
    sleeves["all_5m_momo_proxy"] = (all_5m, np.where(sup.ret_2m_at_ws > 0, "Up", "Down"))

    # 14. ALL UP universe (broad UP bets, anywhere)
    sleeves["all_bet_up"] = (sup.up_fill_ok == True, np.array(["Up"] * len(sup)))

    # 15. ALL DOWN universe
    sleeves["all_bet_dn"] = (sup.dn_fill_ok == True, np.array(["Down"] * len(sup)))

    return sleeves, sup


def task3_gate_overlay(panel):
    """For each top sleeve × each microprice gate, compute baseline vs gate stats."""
    sleeves, sup = define_top_sleeves(panel)

    def gate_pass(direction, sup_row_view, gname):
        """Returns boolean Series: gate g passes for (sup, direction)."""
        d_up = (direction == "Up")
        d_dn = (direction == "Down")
        s = sup_row_view
        # mp_skew sign
        if gname == "g_mp_skew_with":
            return ((d_up & (s.mp_skew > 0)) | (d_dn & (s.mp_skew < 0)))
        if gname == "g_mp_skew_strong_with":
            return ((d_up & (s.mp_skew > 20)) | (d_dn & (s.mp_skew < -20)))
        if gname == "g_mp_change_with":
            return ((d_up & (s.mp_skew_change_500ms > 0)) | (d_dn & (s.mp_skew_change_500ms < 0)))
        if gname == "g_mp_both_favor_bet":
            return ((d_up & (s.mp_up_dev_bps > 0) & (s.mp_dn_dev_bps < 0)) |
                    (d_dn & (s.mp_up_dev_bps < 0) & (s.mp_dn_dev_bps > 0)))
        if gname == "g_mp_skew_extreme_against":
            # Mean revert: bet AGAINST extreme skew (UP when skew very neg, DN when skew very pos)
            return ((d_up & (s.mp_skew < -50)) | (d_dn & (s.mp_skew > 50)))
        if gname == "g_mp_no_extreme":
            return (s.mp_skew.abs() < 50)
        if gname == "g_mp_weighted_skew_with":
            return ((d_up & (s.mp_weighted_skew > 0)) | (d_dn & (s.mp_weighted_skew < 0)))
        if gname == "g_mp_weighted_strong_with":
            return ((d_up & (s.mp_weighted_skew > 20)) | (d_dn & (s.mp_weighted_skew < -20)))
        if gname == "g_mp_imbalance_with":
            return ((d_up & (s.mp_imbalance > 0.2)) | (d_dn & (s.mp_imbalance < -0.2)))
        if gname == "g_mp_imbalance_extreme":
            return ((d_up & (s.mp_imbalance > 0.5)) | (d_dn & (s.mp_imbalance < -0.5)))
        raise ValueError(f"unknown gate {gname}")

    gates = [
        "g_mp_skew_with", "g_mp_skew_strong_with", "g_mp_change_with",
        "g_mp_both_favor_bet", "g_mp_skew_extreme_against", "g_mp_no_extreme",
        "g_mp_weighted_skew_with", "g_mp_weighted_strong_with",
        "g_mp_imbalance_with", "g_mp_imbalance_extreme",
    ]

    rows = []
    for sleeve_name, (mask, direction) in sleeves.items():
        # Restrict to fires that have a fill on the chosen side
        # And require microprice features non-null
        direction_arr = np.asarray(direction)
        sub_mask = mask & sup.mp_skew.notna()
        if sub_mask.sum() < 30:
            continue
        sub = sup[sub_mask].copy()
        # direction aligned
        dir_arr = np.asarray(direction)[sub_mask.values]
        d_up = (dir_arr == "Up")
        d_dn = (dir_arr == "Down")
        # PnL: for UP-bet use pnl_up; DN use pnl_dn
        pnl = np.where(d_up, sub.pnl_up.values, sub.pnl_dn.values)
        # winning indicator
        won = np.where(d_up, (sub.outcome.values == "Up"), (sub.outcome.values == "Down"))
        # baseline: drop NaN pnl
        bvalid = ~np.isnan(pnl)
        if bvalid.sum() < 30:
            continue
        b_pnl = pnl[bvalid]
        b_won = won[bvalid]
        n_b = len(b_pnl); wr_b = b_won.mean(); dpt_b = b_pnl.mean(); sum_b = b_pnl.sum()

        for g in gates:
            gpass = gate_pass(pd.Series(dir_arr, index=sub.index), sub, g).values
            ok = bvalid & gpass
            if ok.sum() < 20:
                continue
            g_pnl = pnl[ok]
            g_won = won[ok]
            rows.append({
                "sleeve": sleeve_name, "gate": g,
                "n_base": int(n_b), "wr_base": float(wr_b),
                "dpt_base": float(dpt_b), "sum_base": float(sum_b),
                "n_gate": int(ok.sum()), "wr_gate": float(g_won.mean()),
                "dpt_gate": float(g_pnl.mean()), "sum_gate": float(g_pnl.sum()),
                "dpt_lift": float(g_pnl.mean() - b_pnl.mean()),
                "wr_lift": float(g_won.mean() - b_won.mean()),
                "gate_keep_pct": float(ok.sum() / max(1, n_b)),
            })

    df = pd.DataFrame(rows).sort_values("dpt_lift", ascending=False)
    return df


# -----------------------------------------------------------------
# TASK 4 — Strict 3-way split (train/val/lockbox) + bootstrap
# -----------------------------------------------------------------
def task4_three_way_validation(panel, top_combos):
    """For each candidate (sleeve, gate) combo:
       Train = first 20 days (Apr 30 -> May 20)
       Val   = next 7 days (May 20 -> May 23 inclusive)  (window ~7d but we have ~3d hybrid)
       Lockbox = last 5 days (May 22 -> May 25)

       Deployable: lockbox_sum > 0 AND lockbox_wr >= 0.65 AND boot_p <= 0.05.

    top_combos: list of (sleeve_name, gate_name) tuples
    Returns DataFrame with per-combo split metrics + bootstrap.
    """
    sleeves, sup = define_top_sleeves(panel)

    # Window edges
    apr30_us = pd.Timestamp("2026-04-30 00:00:00", tz="UTC").value // 1000
    may20_us = pd.Timestamp("2026-05-20 00:00:00", tz="UTC").value // 1000  # train ends
    may22_us = pd.Timestamp("2026-05-22 00:00:00", tz="UTC").value // 1000  # lockbox starts
    print(f"Splits: train [<{may20_us}], val [{may20_us}..{may22_us}], lockbox [>={may22_us}]")

    def gate_pass(direction, sup_row_view, gname):
        s = sup_row_view
        d_up = (direction == "Up")
        d_dn = (direction == "Down")
        if gname == "ALL":
            return pd.Series([True] * len(sup_row_view), index=sup_row_view.index)
        if gname == "g_mp_skew_with":
            return ((d_up & (s.mp_skew > 0)) | (d_dn & (s.mp_skew < 0)))
        if gname == "g_mp_skew_strong_with":
            return ((d_up & (s.mp_skew > 20)) | (d_dn & (s.mp_skew < -20)))
        if gname == "g_mp_change_with":
            return ((d_up & (s.mp_skew_change_500ms > 0)) | (d_dn & (s.mp_skew_change_500ms < 0)))
        if gname == "g_mp_both_favor_bet":
            return ((d_up & (s.mp_up_dev_bps > 0) & (s.mp_dn_dev_bps < 0)) |
                    (d_dn & (s.mp_up_dev_bps < 0) & (s.mp_dn_dev_bps > 0)))
        if gname == "g_mp_skew_extreme_against":
            return ((d_up & (s.mp_skew < -50)) | (d_dn & (s.mp_skew > 50)))
        if gname == "g_mp_no_extreme":
            return (s.mp_skew.abs() < 50)
        if gname == "g_mp_weighted_skew_with":
            return ((d_up & (s.mp_weighted_skew > 0)) | (d_dn & (s.mp_weighted_skew < 0)))
        if gname == "g_mp_weighted_strong_with":
            return ((d_up & (s.mp_weighted_skew > 20)) | (d_dn & (s.mp_weighted_skew < -20)))
        if gname == "g_mp_imbalance_with":
            return ((d_up & (s.mp_imbalance > 0.2)) | (d_dn & (s.mp_imbalance < -0.2)))
        if gname == "g_mp_imbalance_extreme":
            return ((d_up & (s.mp_imbalance > 0.5)) | (d_dn & (s.mp_imbalance < -0.5)))
        raise ValueError(f"unknown gate {gname}")

    rng = np.random.default_rng(42)
    rows = []
    for sleeve_name, gate_name in top_combos:
        if sleeve_name not in sleeves:
            continue
        mask, direction = sleeves[sleeve_name]
        dir_arr = np.asarray(direction)
        sub_mask = mask & sup.mp_skew.notna()
        if sub_mask.sum() < 30:
            continue
        sub_idx = sub_mask[sub_mask].index
        sub = sup.loc[sub_idx]
        d_arr = dir_arr[sub_mask.values]
        gpass = gate_pass(pd.Series(d_arr, index=sub.index), sub, gate_name).values
        sub = sub[gpass]
        d_arr = d_arr[gpass]
        d_up = (d_arr == "Up")
        pnl = np.where(d_up, sub.pnl_up.values, sub.pnl_dn.values)
        won = np.where(d_up, (sub.outcome.values == "Up"), (sub.outcome.values == "Down"))
        fire_s = (sub.fire_us.values // 1_000_000)

        train_mask = fire_s < may20_us
        val_mask = (fire_s >= may20_us) & (fire_s < may22_us)
        lock_mask = fire_s >= may22_us

        def stats(m):
            p = pnl[m]
            w = won[m]
            p = p[~np.isnan(p)]
            w = w[:len(p)]
            if len(p) == 0:
                return (0, np.nan, np.nan, 0.0)
            return (int(len(p)), float(w.mean()), float(p.mean()), float(p.sum()))

        n_tr, wr_tr, dpt_tr, sum_tr = stats(train_mask)
        n_vl, wr_vl, dpt_vl, sum_vl = stats(val_mask)
        n_lk, wr_lk, dpt_lk, sum_lk = stats(lock_mask)

        # bootstrap: shuffle outcomes across the FULL combined sample (proper null)
        # 200 reshuffles; compare actual lockbox sum to null distribution
        lk_pnl = pnl[lock_mask]
        lk_pnl = lk_pnl[~np.isnan(lk_pnl)]
        n_lk_valid = len(lk_pnl)
        if n_lk_valid >= 20:
            null_sums = np.empty(200)
            full_pnl_valid = pnl[~np.isnan(pnl)]
            for i in range(200):
                resample = rng.choice(full_pnl_valid, size=n_lk_valid, replace=True)
                null_sums[i] = resample.sum()
            boot_p = float(np.mean(null_sums >= sum_lk))
            boot_ci5 = float(np.percentile(null_sums, 5))
            boot_ci95 = float(np.percentile(null_sums, 95))
        else:
            boot_p = np.nan; boot_ci5 = np.nan; boot_ci95 = np.nan

        # Deployable test
        deployable = bool(sum_lk > 0 and wr_lk >= 0.65 and (boot_p is not None and boot_p <= 0.05) and n_lk >= 20)
        rows.append({
            "sleeve": sleeve_name, "gate": gate_name,
            "n_train": n_tr, "wr_train": wr_tr, "dpt_train": dpt_tr, "sum_train": sum_tr,
            "n_val": n_vl, "wr_val": wr_vl, "dpt_val": dpt_vl, "sum_val": sum_vl,
            "n_lockbox": n_lk, "wr_lockbox": wr_lk, "dpt_lockbox": dpt_lk, "sum_lockbox": sum_lk,
            "boot_p_lockbox": boot_p, "boot_ci5_lockbox": boot_ci5, "boot_ci95_lockbox": boot_ci95,
            "deployable": deployable,
        })
    return pd.DataFrame(rows).sort_values("dpt_lockbox", ascending=False)


# -----------------------------------------------------------------
# TASK 5 — Microprice vs L1 imbalance comparison
# -----------------------------------------------------------------
def task5_mp_vs_l1(panel):
    """Compare microprice signals to L1 book imbalance from the existing microstructure panel."""
    # Load existing microstructure panel
    mp_panel = pd.read_parquet(OUT_DIR / "microstructure_panel.parquet")
    print(f"microstructure panel: {len(mp_panel)} rows")

    # Merge: match on (asset, slug, tf, fire_us, fire_offset_s, outcome)
    keep_l1 = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome",
               "up_imb1", "up_imb5", "up_imb25", "imb5_diff", "imb1_diff",
               "up_micro_dev_bps", "dn_micro_dev_bps", "micro_dev_diff"]
    keep_l1 = [c for c in keep_l1 if c in mp_panel.columns]
    m = panel.merge(mp_panel[keep_l1], on=["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome"], how="inner",
                    suffixes=("", "_l1ms"))
    print(f"after merge: {len(m)} rows")

    out = {}
    # Correlations: mp_skew vs L1 imb5_diff (proxy for book imbalance direction)
    # Use only rows with both non-null
    both_ok = m.mp_skew.notna() & m.imb5_diff.notna()
    if both_ok.sum() > 100:
        out["corr_mp_skew_vs_imb5_diff"] = float(m.loc[both_ok, "mp_skew"].corr(m.loc[both_ok, "imb5_diff"]))
        out["corr_mp_skew_vs_imb1_diff"] = float(m.loc[both_ok, "mp_skew"].corr(m.loc[both_ok, "imb1_diff"]))
    # micro_dev_diff is exact L1 microprice diff — should be ~1.0 corr if our L1 microprice matches
    if (m.mp_skew.notna() & m.micro_dev_diff.notna()).sum() > 100:
        ok = m.mp_skew.notna() & m.micro_dev_diff.notna()
        out["corr_mp_skew_vs_micro_dev_diff"] = float(m.loc[ok, "mp_skew"].corr(m.loc[ok, "micro_dev_diff"]))
        out["corr_mp_skew_vs_mp_weighted_skew"] = float(m.loc[m.mp_skew.notna() & m.mp_weighted_skew.notna(), "mp_skew"].corr(
                                                          m.loc[m.mp_skew.notna() & m.mp_weighted_skew.notna(), "mp_weighted_skew"]))

    # Standalone direction comparison
    rule_rows = []
    # Bet UP when imb5_diff > 0 (L1 imbalance)
    if "imb5_diff" in m.columns:
        m_test = m.copy()
        m_test["L1_dir"] = np.where(m_test.imb5_diff > 0, "Up",
                            np.where(m_test.imb5_diff < 0, "Down", "Skip"))
        # MP equivalent: bet UP when mp_skew > 0
        m_test["MP_dir"] = np.where(m_test.mp_skew > 0, "Up",
                            np.where(m_test.mp_skew < 0, "Down", "Skip"))
        for rule, col in [("L1_imb5_with", "L1_dir"), ("MP_skew_with", "MP_dir")]:
            for asset in ("BTC", "ETH", "SOL"):
                for tf in ("5m", "15m"):
                    sub = m_test[(m_test.asset == asset) & (m_test.tf == tf)]
                    up_mask = (sub[col] == "Up") & (sub.up_fill_ok == True)
                    dn_mask = (sub[col] == "Down") & (sub.dn_fill_ok == True)
                    up_pnl = sub.loc[up_mask, "pnl_up"].dropna()
                    dn_pnl = sub.loc[dn_mask, "pnl_dn"].dropna()
                    pnl = pd.concat([up_pnl, dn_pnl], ignore_index=True)
                    if len(pnl) < 100:
                        continue
                    wins = (((sub[col] == "Up") & (sub.outcome == "Up") & (sub.up_fill_ok == True)).sum() +
                            ((sub[col] == "Down") & (sub.outcome == "Down") & (sub.dn_fill_ok == True)).sum())
                    n = up_mask.sum() + dn_mask.sum()
                    rule_rows.append({
                        "rule": rule, "asset": asset, "tf": tf,
                        "n": int(n), "wr": float(wins / n),
                        "dpt": float(pnl.mean()), "sum_pnl": float(pnl.sum()),
                    })

    # Joint test: are L1 imb_with AND mp_skew_with INDEPENDENT signals?
    # Conditional probability test
    joint_rows = []
    if "imb5_diff" in m.columns:
        # Build joint indicators for UP bets (bet UP when each signal positive)
        for asset in ("BTC", "ETH", "SOL"):
            for tf in ("5m", "15m"):
                sub = m[(m.asset == asset) & (m.tf == tf) & (m.up_fill_ok == True) & m.pnl_up.notna() & m.mp_skew.notna()]
                if len(sub) < 200:
                    continue
                pnl = sub.pnl_up.values
                won = (sub.outcome.values == "Up")
                l1_pos = sub.imb5_diff.values > 0
                mp_pos = sub.mp_skew.values > 0
                # 4 conditions
                for name, mask_v in [("both_pos", l1_pos & mp_pos),
                                       ("only_L1", l1_pos & ~mp_pos),
                                       ("only_MP", ~l1_pos & mp_pos),
                                       ("neither", ~l1_pos & ~mp_pos)]:
                    if mask_v.sum() < 20:
                        continue
                    joint_rows.append({
                        "asset": asset, "tf": tf, "bet": "Up", "regime": name,
                        "n": int(mask_v.sum()), "wr": float(won[mask_v].mean()),
                        "dpt": float(pnl[mask_v].mean()),
                    })

    return out, pd.DataFrame(rule_rows), pd.DataFrame(joint_rows)


# -----------------------------------------------------------------
# Main entry
# -----------------------------------------------------------------
def main():
    print("=== Loading panel ===")
    panel = load_panel_with_pnl()

    print("\n=== TASK 2: standalone rules ===")
    df2 = task2_standalone(panel)
    df2.to_csv(WORK / "task2_standalone_rules.csv", index=False)
    print(f"Saved task2_standalone_rules.csv ({len(df2)} rows)")
    print("Top 10 by dpt:")
    print(df2.head(10).to_string(index=False))

    print("\n=== TASK 3: gate overlays ===")
    df3 = task3_gate_overlay(panel)
    df3.to_csv(WORK / "task3_gate_overlay.csv", index=False)
    print(f"Saved task3_gate_overlay.csv ({len(df3)} rows)")
    print("Top 15 by dpt_lift:")
    print(df3.head(15).to_string(index=False))

    print("\n=== TASK 4: 3-way validation on top combos ===")
    # Choose top combos: (a) all sleeves x ALL (baseline), (b) top-10 dpt_lift combos from task3
    top_t3 = df3[df3.n_gate >= 30].head(20)
    combos = [(r.sleeve, r.gate) for _, r in top_t3.iterrows()]
    # Also baseline: each sleeve unfiltered
    for s in {r.sleeve for _, r in top_t3.iterrows()}:
        combos.append((s, "ALL"))
    df4 = task4_three_way_validation(panel, combos)
    df4.to_csv(WORK / "task4_three_way_validation.csv", index=False)
    print(f"Saved task4_three_way_validation.csv ({len(df4)} rows)")
    print(f"Deployable: {df4.deployable.sum()}/{len(df4)}")
    if df4.deployable.sum() > 0:
        print(df4[df4.deployable].to_string(index=False))

    print("\n=== TASK 5: MP vs L1 imbalance ===")
    corr, rules5, joint = task5_mp_vs_l1(panel)
    print("Correlations:")
    for k, v in corr.items():
        print(f"  {k}: {v:.4f}")
    rules5.to_csv(WORK / "task5_mp_vs_l1_rules.csv", index=False)
    joint.to_csv(WORK / "task5_mp_vs_l1_joint.csv", index=False)
    print(f"Saved task5 rules ({len(rules5)} rows) + joint ({len(joint)} rows)")
    print("\nDirection rule head-to-head:")
    if len(rules5):
        print(rules5.sort_values(["asset","tf","rule"]).to_string(index=False))
    print("\nJoint regime test:")
    if len(joint):
        print(joint.to_string(index=False))
    with open(WORK / "task5_correlations.json", "w") as f:
        json.dump(corr, f, indent=2)


if __name__ == "__main__":
    import builtins
    _print = builtins.print
    def fp(*a, **k):
        k.setdefault('flush', True)
        _print(*a, **k)
    builtins.print = fp
    main()
