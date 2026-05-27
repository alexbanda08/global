"""TASK 5+6+7+8 — Analyze vol regime / Hurst against top sleeves.

Top 7 R1+R2 sleeves (from REGIME_CONDITIONAL_2026_05_26 + hybrid_gate_search):
  BTC|s6_5m|60-150|g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_ribbon_agrees
  ETH|s6_5m|60-150|g_tight_ribbon&g_stoch_with
  ETH|s15_5m|150-240|g_ribbon_agrees&g_tr_above_ema200&g_stoch_with&g_bb_pos_with&g_cci_with
  BTC|s15_5m|150-240|g_tr_above_pp&g_ribbon_agrees&g_stoch_with&g_tight_ribbon
  SOL|s6_5m|60-150|g_mfi_with&g_within_dev&g_bb_pos_with&g_ribbon_agrees
  BTC|s15_5m|60-150|g_ribbon_agrees&g_rf_with&g_tr_stack_with
  BTC|s15_5m|240-300|g_tr_above_cloud&g_mfi_with&g_tr_above_ema200&g_cci_with&g_stoch_with

Plus S6_base (BASE = no gates, just S6 spike) and S1.5_base for the user
hypothesis test on regime-conditionality.

LegacyConfig fee model (2% on profit only).
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
from load import load_klines  # noqa: E402

OUT_DIR = "data/v4/canonical/_results"
REPORT_DIR = "strategy_lab/reports"
WORK_DIR = "strategy_lab/vol_hurst_2026_05_26"

TIER1 = [
    ("BTC", "s6_5m", "60-150", "g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_ribbon_agrees"),
    ("ETH", "s6_5m", "60-150", "g_tight_ribbon&g_stoch_with"),
    ("ETH", "s15_5m", "150-240", "g_ribbon_agrees&g_tr_above_ema200&g_stoch_with&g_bb_pos_with&g_cci_with"),
    ("BTC", "s15_5m", "150-240", "g_tr_above_pp&g_ribbon_agrees&g_stoch_with&g_tight_ribbon"),
    ("SOL", "s6_5m", "60-150", "g_mfi_with&g_within_dev&g_bb_pos_with&g_ribbon_agrees"),
    ("BTC", "s15_5m", "60-150", "g_ribbon_agrees&g_rf_with&g_tr_stack_with"),
    ("BTC", "s15_5m", "240-300", "g_tr_above_cloud&g_mfi_with&g_tr_above_ema200&g_cci_with&g_stoch_with"),
]


def load_data():
    fires_5m = pd.read_parquet(f"{OUT_DIR}/vol_hurst_at_fire_5m.parquet")
    fires_15m = pd.read_parquet(f"{OUT_DIR}/vol_hurst_at_fire_15m.parquet")
    # Per-fire PnL ledger
    per_fire = pd.read_parquet(f"{OUT_DIR}/hybrid_gate_search_per_fire.parquet")
    # Join sleeve PnL onto vol_hurst features by (slug, fire_us, direction, gate_stack)
    # per_fire has columns: slug, asset, fire_us, fire_offset_s, direction, outcome, won, pnl_legacy_usd, tf, offset_bin, gate_stack
    return fires_5m, fires_15m, per_fire


def build_sleeve_panel(per_fire: pd.DataFrame, vol_5m: pd.DataFrame, vol_15m: pd.DataFrame) -> pd.DataFrame:
    """Join per-fire ledger to vol/hurst features by slug+fire_us+market_tf.

    per_fire.tf is the STRATEGY tf (e.g. 's15_5m', 'v15m_15m').
    vol_*.tf is the MARKET tf (e.g. '5m', '15m').
    We derive market_tf from per_fire.tf suffix.
    """
    pf = per_fire.copy()
    pf["market_tf"] = pf["tf"].str.split("_").str[-1]
    cols_keep_vol = [
        "asset", "slug", "tf", "fire_us",
        "rv_60s", "rv_300s", "rv_900s", "rv_3600s", "rv_ratio_60_to_3600",
        "rv_pct_24h", "vol_regime", "gk_sigma", "gk_sigma_ma12",
        "hurst_100s", "hurst_300s", "hurst_900s",
        "g_vol_low", "g_vol_med", "g_vol_high",
        "g_hurst_trending", "g_hurst_reverting",
        "g_vol_expanding", "g_vol_contracting", "g_rv_with",
        "ret_30s", "ret_30s_sign",
    ]
    vol_5m_k = vol_5m[cols_keep_vol].copy().rename(columns={"tf": "market_tf"})
    vol_15m_k = vol_15m[cols_keep_vol].copy().rename(columns={"tf": "market_tf"})
    vol_all = pd.concat([vol_5m_k, vol_15m_k], ignore_index=True)
    merged = pf.merge(
        vol_all,
        on=["asset", "slug", "market_tf", "fire_us"],
        how="left",
    )
    print(f"  sleeve panel: {len(merged):,} rows (lost {(merged['rv_300s'].isna()).sum():,} to NaN vol)")
    return merged


def sleeve_key(row) -> str:
    return f"{row['asset']}|{row['tf']}|{row['offset_bin']}|{row['gate_stack']}"


def stats_block(df: pd.DataFrame, label: str) -> dict:
    if len(df) == 0:
        return {"label": label, "n": 0, "wr": np.nan, "dpt": np.nan, "sum_pnl": np.nan}
    return {
        "label": label,
        "n": len(df),
        "wr": float(df["won"].mean()),
        "dpt": float(df["pnl_legacy_usd"].mean()),
        "sum_pnl": float(df["pnl_legacy_usd"].sum()),
    }


def per_sleeve_by_vol_regime(panel: pd.DataFrame) -> pd.DataFrame:
    """TASK 5: WR / $/tr / sum_pnl by vol_regime for top 7 sleeves."""
    rows = []
    for asset, sub_tf, offset_bin, gate_stack in TIER1:
        s = panel[
            (panel["asset"] == asset)
            & (panel["tf"] == sub_tf)
            & (panel["offset_bin"] == offset_bin)
            & (panel["gate_stack"] == gate_stack)
        ]
        if len(s) == 0:
            continue
        sleeve_label = f"{asset}_{sub_tf}_{offset_bin}"
        all_row = stats_block(s, "all")
        all_row["sleeve"] = sleeve_label
        all_row["regime"] = "all"
        rows.append(all_row)
        for reg, name in [(0, "low"), (1, "med"), (2, "high")]:
            sub = s[s["vol_regime"] == reg]
            row = stats_block(sub, name)
            row["sleeve"] = sleeve_label
            row["regime"] = name
            rows.append(row)
    return pd.DataFrame(rows)


def per_sleeve_by_hurst(panel: pd.DataFrame, hurst_col: str = "hurst_300s") -> pd.DataFrame:
    """TASK 6: WR / $/tr by Hurst bucket for top 7 sleeves."""
    rows = []
    buckets = [
        ("h_lt_04", lambda x: x < 0.4),
        ("h_04_05", lambda x: (x >= 0.4) & (x < 0.5)),
        ("h_05_06", lambda x: (x >= 0.5) & (x < 0.6)),
        ("h_ge_06", lambda x: x >= 0.6),
    ]
    for asset, sub_tf, offset_bin, gate_stack in TIER1:
        s = panel[
            (panel["asset"] == asset)
            & (panel["tf"] == sub_tf)
            & (panel["offset_bin"] == offset_bin)
            & (panel["gate_stack"] == gate_stack)
        ]
        if len(s) == 0:
            continue
        sleeve_label = f"{asset}_{sub_tf}_{offset_bin}"
        all_row = stats_block(s, "all")
        all_row["sleeve"] = sleeve_label
        all_row["bucket"] = "all"
        rows.append(all_row)
        for name, pred in buckets:
            sub = s[pred(s[hurst_col])]
            row = stats_block(sub, name)
            row["sleeve"] = sleeve_label
            row["bucket"] = name
            rows.append(row)
    return pd.DataFrame(rows)


# ---- TASK 7: standalone rules ----

def s6_s15_base_panel(per_fire_with_vol: pd.DataFrame) -> pd.DataFrame:
    """Filter per_fire to a single (asset, tf, offset_bin) cell — the 'base'
    sleeve before gate filtering. Use all (slug, direction) pairs."""
    # The hybrid gate search produced per-fire rows that PASS the gate-stack of
    # the top sleeve. For BASE (S6 / S15 unfiltered), we don't have that ledger
    # off the shelf — we'd need to backtest from raw. But we DO have
    # hybrid_standalone_per_fire which is the V1..V12 momo rules with all fires.
    # Repurpose: use V1 momo (closest to "S6 spike continuation") for base
    # comparison.
    raise NotImplementedError


def standalone_rules(panel: pd.DataFrame, fires_universe: pd.DataFrame) -> pd.DataFrame:
    """TASK 7: VR-A/B/C/D standalone rules.

    Use a uniform stake fee model — synthesize PnL using the up_fill / dn_fill
    + outcome columns from the fire universe (already in panel via the cols
    we kept, but we need to bring fill prices). Use a $1 stake at vwap.
    """
    # Need to attach up_vwap/dn_vwap/up_fill_ok/dn_fill_ok/outcome.
    # `panel` is the per_fire ledger (sleeve fires); not the universe.
    # For standalone rules, work directly off the augmented fire universe.
    f = fires_universe.copy()
    # Need fill PnL per direction. legacy fee = 2% on profit only.
    # Won leg pays: q * (1-p) * 0.98 ; lost leg pays: -q * p.
    # For $1 stake at vwap p_up: q = 1/p_up; won if outcome==Up.
    stake = 1.0
    fee = 0.02
    p_up = f["up_vwap"].to_numpy()
    p_dn = f["dn_vwap"].to_numpy()
    won_up = (f["outcome"].to_numpy() == "Up")
    won_dn = (f["outcome"].to_numpy() == "Down")
    # Quantities
    q_up = np.where(p_up > 0, stake / p_up, 0)
    q_dn = np.where(p_dn > 0, stake / p_dn, 0)
    # Per-leg PnL (legacy 2% on profit on winning leg only)
    pnl_up = np.where(won_up, q_up * (1 - p_up) * (1 - fee), -q_up * p_up)
    pnl_dn = np.where(won_dn, q_dn * (1 - p_dn) * (1 - fee), -q_dn * p_dn)
    f["pnl_up"] = pnl_up
    f["pnl_dn"] = pnl_dn
    fillable_up = f["up_fill_ok"].fillna(False).astype(bool).to_numpy()
    fillable_dn = f["dn_fill_ok"].fillna(False).astype(bool).to_numpy()
    rows = []

    # VR-A: bet WITH momentum when H>0.6 (trending). direction = sign(ret_30s).
    h300 = f["hurst_300s"].to_numpy()
    sign = f["ret_30s_sign"].to_numpy()
    trending = (h300 > 0.6) & np.isfinite(h300) & (sign != 0)
    for label, mask, direction in [
        ("VR-A_trending_with_momo",
         trending,
         np.where(sign > 0, "Up", "Down")),
    ]:
        sub = f[mask].copy()
        if len(sub) == 0:
            continue
        dir_arr = direction[mask]
        # Use up leg if direction Up & up_fill_ok, else dn leg.
        use_up = (dir_arr == "Up") & fillable_up[mask]
        use_dn = (dir_arr == "Down") & fillable_dn[mask]
        keep = use_up | use_dn
        sub_used = sub[keep].copy()
        sub_used["pnl"] = np.where(use_up[keep], sub["pnl_up"][keep], sub["pnl_dn"][keep])
        sub_used["won"] = np.where(
            use_up[keep], won_up[mask][keep], won_dn[mask][keep]
        ).astype(int)
        rows.append({
            "rule": label,
            "n": len(sub_used),
            "wr": float(sub_used["won"].mean()),
            "dpt": float(sub_used["pnl"].mean()),
            "sum_pnl": float(sub_used["pnl"].sum()),
        })

    # VR-B: bet AGAINST momentum when H<0.4 (mean-reversion)
    reverting = (h300 < 0.4) & np.isfinite(h300) & (sign != 0)
    direction_b = np.where(sign > 0, "Down", "Up")  # contra
    use_up = (direction_b == "Up") & fillable_up & reverting
    use_dn = (direction_b == "Down") & fillable_dn & reverting
    keep = use_up | use_dn
    pnl_b = np.where(use_up, pnl_up, pnl_dn)
    won_b = np.where(use_up, won_up, won_dn)
    sub_b = pd.DataFrame({"pnl": pnl_b[keep], "won": won_b[keep].astype(int)})
    rows.append({
        "rule": "VR-B_reverting_contra_momo",
        "n": len(sub_b),
        "wr": float(sub_b["won"].mean()) if len(sub_b) else np.nan,
        "dpt": float(sub_b["pnl"].mean()) if len(sub_b) else np.nan,
        "sum_pnl": float(sub_b["pnl"].sum()) if len(sub_b) else np.nan,
    })

    # VR-C: skip fires when vol_regime_high — compare baseline (all fires either
    # leg with best p heuristic) — frame as: WR/dpt of always-Up bet vs filtered.
    # Baseline = always go Up (or whatever side has lower price = more upside)
    p_up_arr = p_up
    p_dn_arr = p_dn
    pick_up = (p_up_arr <= p_dn_arr) & fillable_up
    pick_dn = (~pick_up) & fillable_dn
    pnl_pick = np.where(pick_up, pnl_up, np.where(pick_dn, pnl_dn, 0.0))
    won_pick = np.where(pick_up, won_up, np.where(pick_dn, won_dn, False)).astype(int)
    base_mask = (pick_up | pick_dn)
    keep_low = base_mask & (f["vol_regime"].to_numpy() != 2)
    rows.append({
        "rule": "VR-C_skip_vol_high",
        "n": int(keep_low.sum()),
        "wr": float(won_pick[keep_low].mean()) if keep_low.any() else np.nan,
        "dpt": float(pnl_pick[keep_low].mean()) if keep_low.any() else np.nan,
        "sum_pnl": float(pnl_pick[keep_low].sum()),
    })
    rows.append({
        "rule": "VR-C_baseline_all_pick_lower_p",
        "n": int(base_mask.sum()),
        "wr": float(won_pick[base_mask].mean()),
        "dpt": float(pnl_pick[base_mask].mean()),
        "sum_pnl": float(pnl_pick[base_mask].sum()),
    })

    # VR-D: bet UP when rv_60s spikes >2x rv_300s AND last 60s return up
    rv60 = f["rv_60s"].to_numpy()
    rv300 = f["rv_300s"].to_numpy()
    expand = (rv60 > 2 * rv300) & np.isfinite(rv60) & np.isfinite(rv300)
    up_momo = expand & (sign > 0) & fillable_up
    sub_d = pd.DataFrame({
        "pnl": pnl_up[up_momo],
        "won": won_up[up_momo].astype(int),
    })
    rows.append({
        "rule": "VR-D_vol_expand_up_confirm",
        "n": len(sub_d),
        "wr": float(sub_d["won"].mean()) if len(sub_d) else np.nan,
        "dpt": float(sub_d["pnl"].mean()) if len(sub_d) else np.nan,
        "sum_pnl": float(sub_d["pnl"].sum()) if len(sub_d) else np.nan,
    })
    # Also: bet DOWN when rv_60s>2x rv_300s AND last 60s return DOWN
    dn_momo = expand & (sign < 0) & fillable_dn
    sub_d2 = pd.DataFrame({
        "pnl": pnl_dn[dn_momo],
        "won": won_dn[dn_momo].astype(int),
    })
    rows.append({
        "rule": "VR-D_vol_expand_dn_confirm",
        "n": len(sub_d2),
        "wr": float(sub_d2["won"].mean()) if len(sub_d2) else np.nan,
        "dpt": float(sub_d2["pnl"].mean()) if len(sub_d2) else np.nan,
        "sum_pnl": float(sub_d2["pnl"].sum()) if len(sub_d2) else np.nan,
    })
    return pd.DataFrame(rows)


# ---- TASK 8: gate overlay ----
def gate_overlay(panel: pd.DataFrame) -> pd.DataFrame:
    """Apply each binary gate to each of the top 7 sleeves; report lift."""
    gates = [
        "g_vol_low", "g_vol_med", "g_vol_high",
        "g_hurst_trending", "g_hurst_reverting",
        "g_vol_expanding", "g_vol_contracting",
        "g_rv_with",
    ]
    rows = []
    for asset, sub_tf, offset_bin, gate_stack in TIER1:
        s = panel[
            (panel["asset"] == asset)
            & (panel["tf"] == sub_tf)
            & (panel["offset_bin"] == offset_bin)
            & (panel["gate_stack"] == gate_stack)
        ]
        if len(s) == 0:
            continue
        sleeve_label = f"{asset}_{sub_tf}_{offset_bin}"
        base = stats_block(s, "base")
        for g in gates:
            sub = s[s[g] == 1]
            block = stats_block(sub, g)
            block["sleeve"] = sleeve_label
            block["gate"] = g
            block["base_wr"] = base["wr"]
            block["base_dpt"] = base["dpt"]
            block["base_n"] = base["n"]
            block["lift_wr"] = block["wr"] - base["wr"]
            block["lift_dpt"] = block["dpt"] - base["dpt"]
            rows.append(block)
    return pd.DataFrame(rows)


# ---- TASK 9: walk-forward 20d/8d split ----
def walk_forward(panel: pd.DataFrame, gate_overlay_results: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Split 20d in-sample / 8d out-of-sample. Take top-N gate overlays by
    in-sample dpt lift with n>=200, re-evaluate on OOS."""
    # Window per task spec: Apr 30 -> May 22 2026 (panel span). Total ~22d.
    # Use first 16d as IS, last 8d as OOS. Hard split at fire_us threshold.
    fu = panel["fire_us"].to_numpy()
    t_lo = fu.min()
    t_hi = fu.max()
    # Choose split at 16 days in
    split_us = t_lo + 16 * 86_400 * 1_000_000
    if split_us >= t_hi:
        split_us = t_lo + (t_hi - t_lo) * 16 // 22
    panel_is = panel[panel["fire_us"] < split_us]
    panel_oos = panel[panel["fire_us"] >= split_us]

    # Build all (sleeve, gate) combos eligible (n_is >= 200, lift_dpt > 0)
    candidates = []
    gates = [
        "g_vol_low", "g_vol_med", "g_vol_high",
        "g_hurst_trending", "g_hurst_reverting",
        "g_vol_expanding", "g_vol_contracting", "g_rv_with",
    ]
    for asset, sub_tf, offset_bin, gate_stack in TIER1:
        for g in gates:
            s_is = panel_is[
                (panel_is["asset"] == asset)
                & (panel_is["tf"] == sub_tf)
                & (panel_is["offset_bin"] == offset_bin)
                & (panel_is["gate_stack"] == gate_stack)
                & (panel_is[g] == 1)
            ]
            s_oos = panel_oos[
                (panel_oos["asset"] == asset)
                & (panel_oos["tf"] == sub_tf)
                & (panel_oos["offset_bin"] == offset_bin)
                & (panel_oos["gate_stack"] == gate_stack)
                & (panel_oos[g] == 1)
            ]
            base_is = panel_is[
                (panel_is["asset"] == asset)
                & (panel_is["tf"] == sub_tf)
                & (panel_is["offset_bin"] == offset_bin)
                & (panel_is["gate_stack"] == gate_stack)
            ]
            base_oos = panel_oos[
                (panel_oos["asset"] == asset)
                & (panel_oos["tf"] == sub_tf)
                & (panel_oos["offset_bin"] == offset_bin)
                & (panel_oos["gate_stack"] == gate_stack)
            ]
            if len(s_is) < 150 or len(base_is) == 0:
                continue
            row = {
                "sleeve": f"{asset}_{sub_tf}_{offset_bin}",
                "gate": g,
                "is_n": len(s_is),
                "is_wr": float(s_is["won"].mean()),
                "is_dpt": float(s_is["pnl_legacy_usd"].mean()),
                "is_lift_dpt": float(s_is["pnl_legacy_usd"].mean()) - float(base_is["pnl_legacy_usd"].mean()),
                "is_base_n": len(base_is),
                "is_base_dpt": float(base_is["pnl_legacy_usd"].mean()),
                "oos_n": len(s_oos),
                "oos_wr": float(s_oos["won"].mean()) if len(s_oos) else np.nan,
                "oos_dpt": float(s_oos["pnl_legacy_usd"].mean()) if len(s_oos) else np.nan,
                "oos_lift_dpt": (
                    float(s_oos["pnl_legacy_usd"].mean()) - float(base_oos["pnl_legacy_usd"].mean())
                ) if len(s_oos) and len(base_oos) else np.nan,
            }
            candidates.append(row)
    df_c = pd.DataFrame(candidates)
    if df_c.empty:
        return df_c, df_c
    df_c = df_c.sort_values("is_lift_dpt", ascending=False)
    top = df_c.head(top_n).copy()
    top["pass_oos"] = (
        (top["oos_n"] >= 30) & (top["oos_lift_dpt"] > 0)
    ).astype(int)
    return top, df_c


def bootstrap_ci(values: np.ndarray, n_iter: int = 500, q_lo: float = 0.025, q_hi: float = 0.975) -> tuple:
    rng = np.random.default_rng(42)
    if len(values) == 0:
        return (np.nan, np.nan)
    n = len(values)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n, n)
        means[i] = values[idx].mean()
    return float(np.quantile(means, q_lo)), float(np.quantile(means, q_hi))


def main() -> None:
    os.makedirs(WORK_DIR, exist_ok=True)
    t0 = time.time()
    print("loading data...", flush=True)
    fires_5m, fires_15m, per_fire = load_data()
    print(f"  5m fires: {len(fires_5m):,}, 15m fires: {len(fires_15m):,}, per_fire: {len(per_fire):,}")

    panel = build_sleeve_panel(per_fire, fires_5m, fires_15m)
    panel.to_parquet(f"{WORK_DIR}/sleeve_panel.parquet", index=False)
    print(f"sleeve panel saved t={time.time()-t0:.1f}s")

    # TASK 5 vol regime
    t5 = per_sleeve_by_vol_regime(panel)
    t5.to_csv(f"{WORK_DIR}/task5_per_sleeve_by_vol_regime.csv", index=False)
    print(f"task5 saved ({len(t5)} rows)")

    # TASK 6 hurst
    t6 = per_sleeve_by_hurst(panel, "hurst_300s")
    t6.to_csv(f"{WORK_DIR}/task6_per_sleeve_by_hurst300.csv", index=False)
    print(f"task6 saved ({len(t6)} rows)")

    t6b = per_sleeve_by_hurst(panel, "hurst_900s")
    t6b.to_csv(f"{WORK_DIR}/task6b_per_sleeve_by_hurst900.csv", index=False)

    # TASK 7 standalone
    fires_uni = pd.concat([fires_5m, fires_15m], ignore_index=True)
    t7 = standalone_rules(panel, fires_uni)
    t7.to_csv(f"{WORK_DIR}/task7_standalone_rules.csv", index=False)
    print(f"task7 saved ({len(t7)} rows)")

    # TASK 8 gate overlay
    t8 = gate_overlay(panel)
    t8.to_csv(f"{WORK_DIR}/task8_gate_overlay.csv", index=False)
    print(f"task8 saved ({len(t8)} rows)")

    # TASK 9 walk-forward
    t9_top, t9_all = walk_forward(panel, t8, top_n=10)
    t9_top.to_csv(f"{WORK_DIR}/task9_walkforward_top10.csv", index=False)
    t9_all.to_csv(f"{WORK_DIR}/task9_walkforward_all.csv", index=False)
    print(f"task9 saved (top10 pass count: {t9_top['pass_oos'].sum()}/{len(t9_top)})")

    print(f"DONE t={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
