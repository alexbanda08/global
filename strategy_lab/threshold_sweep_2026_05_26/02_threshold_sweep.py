"""Threshold sweep — TASK 1-5.

For each top 7 sleeve × each candidate gate × each threshold in the sweep:
  - Apply (existing R1 base sleeve) AND (this gate at this threshold)
  - Compute lockbox n, WR, $/tr, sum, bootstrap p
  - Identify the OPTIMAL threshold per (sleeve, gate) by lockbox sum_pnl

Default thresholds (used in prior rounds):
  mp_no_extreme < 50 bps, L > 5.97, |lambda_imb| > 0.3, vol_expand > 1.5,
  H > 0.55, dev_bps > 5, mp_skew_change_500ms > 0, imb5 > 0.3, queue_top > median (~0.5)

Output:
  data/v4/canonical/_results/threshold_sweep.csv  (sleeve x gate x threshold x metrics)
  data/v4/canonical/_results/threshold_profile_per_sleeve.csv
  data/v4/canonical/_results/threshold_optimized_stacks.csv
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

# Lockbox split: train 67% / val 17% / lockbox 16% (time-ordered)
TR_FRAC = 0.67
VL_FRAC = 0.17

MIN_N = 20  # min cell size on lockbox for a sweep result to be valid

# Top 7 sleeves
SLEEVES = [
    # (name, panel_file, asset, tf, offsets, hybrid_v1 R1 gates)
    ("BTC_S6_hybrid_v1", "threshold_panel_s6.parquet", "BTC", "5m", [60, 90, 120, 150],
     ["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50", "g_ribbon_agrees"]),
    ("ETH_S6_hybrid_v1", "threshold_panel_s6.parquet", "ETH", "5m", [60, 90, 120, 150],
     ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"]),
    ("SOL_S6_hybrid_v1", "threshold_panel_s6.parquet", "SOL", "5m", [60, 90, 120, 150],
     ["g_mfi_with", "g_within_dev", "g_bb_pos_with", "g_ribbon_agrees"]),
    ("BTC_S15_hybrid_v1", "threshold_panel_s15.parquet", "BTC", "5m", [150, 180, 210, 240],
     ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with", "g_tight_ribbon"]),
    ("ETH_S15_hybrid_v1", "threshold_panel_s15.parquet", "ETH", "5m", [150, 180, 210, 240],
     ["g_ribbon_agrees", "g_tr_above_ema200", "g_stoch_with", "g_bb_pos_with", "g_cci_with"]),
    ("S7_btc_5m_base", "threshold_panel_s6.parquet", "BTC", "5m", [120, 150, 180, 210, 240, 270, 300],
     ["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50", "g_tr_above_ema200", "g_ribbon_agrees"]),
    ("R2_btc_5m_s1_5_3bps", "threshold_panel_r2.parquet", "BTC", "5m", [60, 90, 120, 150, 180],
     ["g_within_dev", "g_rf_strong", "g_ribbon_agrees"]),
]


# Per-gate threshold sweep configuration.
# Each entry: gate_name -> {
#   "kind": "abs_lt" / "abs_gt_signed" / "abs_gt" / "gt" / "lt" / "abs_gt_dir" / "queue_top_gt_dir" / ...
#   "col": continuous source col(s)
#   "thresholds": [list of threshold values],
#   "default_thr": default threshold value,
#   "description": ...
# }
SWEEPS = {
    "g_mp_no_extreme": {
        "kind": "abs_lt", "col": "mp_skew",
        "thresholds": [20, 30, 50, 70, 100, 150],
        "default_thr": 50,
        "desc": "|mp_skew| < THR bps (tradability)",
    },
    "g_mp_change_with": {
        "kind": "abs_gt_signed", "col": "mp_skew_change_500ms",
        "thresholds": [0, 1, 2, 5, 10],  # 0 = original (any positive on side)
        "default_thr": 0,
        "desc": "|mp_skew_change_500ms| > THR with sign matching",
    },
    "g_mp_skew_with_strong": {
        "kind": "abs_gt_signed", "col": "mp_skew",
        "thresholds": [5, 10, 20, 30, 50],
        "default_thr": 5,
        "desc": "|mp_skew| > THR bps with sign matching",
    },
    "g_lm_high_stat": {
        "kind": "gt", "col": "lm_L_stat_at_fire",
        "thresholds": [3.0, 5.0, 5.97, 7.0, 10.0, 15.0, 20.0],
        "default_thr": 5.97,
        "desc": "L_stat > THR (jump significance)",
    },
    "g_lm_jump_window_60s": {
        "kind": "lm_jump_window", "col": "lm_has_jump_60s",
        "thresholds": [60],  # only 60s
        "default_thr": 60,
        "desc": "jump in last 60 seconds",
    },
    "g_lm_jump_window_120s": {
        "kind": "lm_jump_window", "col": "lm_has_jump_120s",
        "thresholds": [120],
        "default_thr": 120,
        "desc": "jump in last 120 seconds",
    },
    "g_lm_jump_window_300s": {
        "kind": "lm_jump_window", "col": "lm_n_jumps_in_last_300s",
        "thresholds": [300],
        "default_thr": 300,
        "desc": "any jump in last 300 seconds (count > 0)",
    },
    "g_hawkes_imbalance_with": {
        "kind": "abs_gt_signed", "col": "hawkes_lambda_imbalance",
        "thresholds": [0.1, 0.15, 0.2, 0.3, 0.5],
        "default_thr": 0.3,
        "desc": "|lambda_imbalance| > THR with sign matching",
    },
    "g_hawkes_lambda_high": {
        "kind": "gt", "col": "hawkes_lambda_total",
        "thresholds": [0.5, 1.0, 1.5, 2.0],
        "default_thr": 0.5,
        "desc": "lambda_total > THR (active flow)",
    },
    "g_vol_expanding": {
        "kind": "ratio_gt", "col": ("rv_60s", "rv_300s"),
        "thresholds": [1.2, 1.5, 1.8, 2.0, 2.5],
        "default_thr": 1.5,
        "desc": "rv_60s / rv_300s > THR (vol expanding)",
    },
    "g_vol_contracting": {
        "kind": "ratio_lt", "col": ("rv_60s", "rv_300s"),
        "thresholds": [0.5, 0.7, 0.85],
        "default_thr": 0.7,
        "desc": "rv_60s / rv_300s < THR (vol contracting)",
    },
    "g_hurst_trending": {
        "kind": "gt", "col": "hurst_300s",
        "thresholds": [0.50, 0.55, 0.60, 0.65, 0.70],
        "default_thr": 0.55,
        "desc": "H_300s > THR (trending)",
    },
    "g_hurst_reverting": {
        "kind": "lt", "col": "hurst_300s",
        "thresholds": [0.30, 0.35, 0.40, 0.45],
        "default_thr": 0.45,
        "desc": "H_300s < THR (mean-reverting)",
    },
    "g_imb5_strong_with": {
        "kind": "imb_dir_gt", "col": ("up_imb5", "dn_imb5"),
        "thresholds": [0.2, 0.3, 0.5, 0.7],
        "default_thr": 0.3,
        "desc": "imb5 on bet-side > THR",
    },
    "g_queue_top_high": {
        "kind": "queue_dir_gt", "col": ("up_queue_top_bid", "dn_queue_top_bid"),
        "thresholds": [0.4, 0.5, 0.6, 0.7],
        "default_thr": 0.5,  # ~median proxy
        "desc": "queue_top_bid on bet-side > THR",
    },
    "g_book_slope_steep_against": {
        "kind": "slope_dir_quantile", "col": ("up_bid_slope", "up_ask_slope", "dn_bid_slope", "dn_ask_slope"),
        "thresholds": [0.10, 0.25, 0.40],  # quantile thresholds (lower => stricter)
        "default_thr": 0.25,
        "desc": "(bid-ask) slope diff on bet-side below quantile THR",
    },
    "g_within_dev": {
        "kind": "abs_gt_signed", "col": "vwap_since_open_bps",
        "thresholds": [3, 5, 7, 10, 15, 20],
        "default_thr": 5,
        "desc": "|vwap_since_open_bps| > THR with sign matching",
    },
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def make_gate_mask(df: pd.DataFrame, gate_name: str, thr) -> np.ndarray:
    """Build boolean mask for a (gate, threshold) combination."""
    cfg = SWEEPS[gate_name]
    kind = cfg["kind"]
    col = cfg["col"]
    n = len(df)
    if isinstance(col, tuple):
        for c in col:
            if c not in df.columns:
                return np.zeros(n, dtype=bool)
    else:
        if col not in df.columns:
            return np.zeros(n, dtype=bool)

    direction = df["direction"].values
    dir_up = (direction == "UP")
    dir_dn = (direction == "DOWN")

    if kind == "abs_lt":
        v = df[col].abs()
        return (v < thr).fillna(False).values
    elif kind == "abs_gt":
        v = df[col].abs()
        return (v > thr).fillna(False).values
    elif kind == "gt":
        v = df[col]
        return (v > thr).fillna(False).values
    elif kind == "lt":
        v = df[col]
        return (v < thr).fillna(False).values
    elif kind == "abs_gt_signed":
        # |v| > thr AND sign(v) matches direction (UP=positive, DOWN=negative)
        v = df[col]
        sign_match = ((v > 0) & dir_up) | ((v < 0) & dir_dn)
        return (v.abs() > thr).fillna(False).values & sign_match.values
    elif kind == "lm_jump_window":
        # col is e.g. lm_has_jump_60s (bool) or lm_n_jumps_in_last_300s (int)
        v = df[col]
        if "n_jumps" in col:
            return (v > 0).fillna(False).values
        return v.fillna(False).astype(bool).values
    elif kind == "ratio_gt":
        num_col, den_col = col
        num = df[num_col]
        den = df[den_col]
        ratio = num / den.replace(0, np.nan)
        return (ratio > thr).fillna(False).values
    elif kind == "ratio_lt":
        num_col, den_col = col
        num = df[num_col]
        den = df[den_col]
        ratio = num / den.replace(0, np.nan)
        return (ratio < thr).fillna(False).values
    elif kind == "imb_dir_gt":
        up_col, dn_col = col
        up_v = df[up_col]
        dn_v = df[dn_col]
        m = ((up_v > thr) & dir_up) | ((dn_v > thr) & dir_dn)
        return m.fillna(False).values
    elif kind == "queue_dir_gt":
        up_col, dn_col = col
        up_v = df[up_col]
        dn_v = df[dn_col]
        m = ((up_v > thr) & dir_up) | ((dn_v > thr) & dir_dn)
        return m.fillna(False).values
    elif kind == "slope_dir_quantile":
        # diff = bid_slope - ask_slope (negative = book thick against move)
        up_bid, up_ask, dn_bid, dn_ask = col
        diff_up = df[up_bid] - df[up_ask]
        diff_dn = df[dn_bid] - df[dn_ask]
        # threshold is quantile -> compute panel-wide quantile per side
        q_up = diff_up.quantile(thr)
        q_dn = diff_dn.quantile(thr)
        m = ((diff_up < q_up) & dir_up) | ((diff_dn < q_dn) & dir_dn)
        return m.fillna(False).values
    else:
        raise ValueError(f"Unknown kind {kind}")


def apply_stack(df: pd.DataFrame, gates: list[str]) -> np.ndarray:
    """All R1 gates ==1."""
    m = np.ones(len(df), dtype=bool)
    for g in gates:
        m &= (df[g] == 1)
    return m


def cell_stats(sub: pd.DataFrame) -> dict:
    n = len(sub)
    if n == 0:
        return {"n": 0, "sum_pnl": 0.0, "dpt": 0.0, "WR": 0.0}
    return {
        "n": n,
        "sum_pnl": float(sub.pnl_legacy_usd.sum()),
        "dpt": float(sub.pnl_legacy_usd.mean()),
        "WR": float(sub.won.mean()),
    }


def split_train_val_lock(sub: pd.DataFrame):
    """Time-ordered split."""
    sub = sub.sort_values("fire_us").reset_index(drop=True)
    n = len(sub)
    n_tr = int(n * TR_FRAC)
    n_vl = int(n * VL_FRAC)
    return sub.iloc[:n_tr], sub.iloc[n_tr:n_tr + n_vl], sub.iloc[n_tr + n_vl:]


def bootstrap_p(full_pnl: np.ndarray, actual_dpt: float, n_lk: int, n_iter: int = 500) -> float:
    """500-shuffle bootstrap: how often does a random sample of size n_lk from `full_pnl`
    have mean >= actual_dpt? Returns one-sided p-value."""
    if n_lk == 0 or len(full_pnl) == 0:
        return 1.0
    rng = np.random.default_rng(42)
    null_dpts = np.empty(n_iter)
    for i in range(n_iter):
        sample = rng.choice(full_pnl, size=n_lk, replace=True)
        null_dpts[i] = float(sample.mean())
    return float(np.mean(null_dpts >= actual_dpt))


def sweep_one_sleeve(sleeve_name: str, panel_file: str, asset: str, tf_filter: str,
                     offsets: list[int], r1_gates: list[str]) -> pd.DataFrame:
    """For one sleeve, sweep every gate × threshold combination."""
    log(f"=== SWEEP {sleeve_name} ===")
    df = pd.read_parquet(RES / panel_file)

    mask = (df.asset == asset) & (df.fire_offset_s.isin(offsets))
    if "tf" in df.columns:
        mask &= (df.tf == tf_filter)
    universe = df[mask].copy()
    log(f"  universe: {len(universe):,}")
    if len(universe) == 0:
        return pd.DataFrame()

    # Apply R1 baseline
    r1_mask = apply_stack(universe, r1_gates)
    base = universe[r1_mask].copy().reset_index(drop=True)
    log(f"  base (R1 hybrid_v1): {len(base):,}")
    if len(base) == 0:
        return pd.DataFrame()

    # Baseline 3-way for reference
    tr_b, vl_b, lk_b = split_train_val_lock(base)
    base_full_pnl = base.pnl_legacy_usd.values
    base_lk_dpt = float(lk_b.pnl_legacy_usd.mean()) if len(lk_b) else 0.0
    base_boot_p = bootstrap_p(base_full_pnl, base_lk_dpt, len(lk_b))

    rows = []
    rows.append({
        "sleeve": sleeve_name, "gate": "(baseline_r1_only)", "threshold": None, "default_thr": None,
        "is_default": True, "is_optimal": False,
        "n_full": len(base), "WR_full": float(base.won.mean()),
        "dpt_full": float(base.pnl_legacy_usd.mean()),
        "sum_full": float(base.pnl_legacy_usd.sum()),
        "n_train": len(tr_b),
        "dpt_train": float(tr_b.pnl_legacy_usd.mean()) if len(tr_b) else 0.0,
        "WR_train": float(tr_b.won.mean()) if len(tr_b) else 0.0,
        "sum_train": float(tr_b.pnl_legacy_usd.sum()) if len(tr_b) else 0.0,
        "n_val": len(vl_b),
        "dpt_val": float(vl_b.pnl_legacy_usd.mean()) if len(vl_b) else 0.0,
        "WR_val": float(vl_b.won.mean()) if len(vl_b) else 0.0,
        "sum_val": float(vl_b.pnl_legacy_usd.sum()) if len(vl_b) else 0.0,
        "n_lockbox": len(lk_b),
        "dpt_lockbox": base_lk_dpt,
        "WR_lockbox": float(lk_b.won.mean()) if len(lk_b) else 0.0,
        "sum_lockbox": float(lk_b.pnl_legacy_usd.sum()) if len(lk_b) else 0.0,
        "boot_p_lockbox": base_boot_p,
    })

    # For each gate-threshold combo
    for gate_name, cfg in SWEEPS.items():
        for thr in cfg["thresholds"]:
            try:
                gate_mask = make_gate_mask(base, gate_name, thr)
            except Exception as e:
                log(f"  ERR {gate_name} thr={thr}: {e}")
                continue
            sub = base[gate_mask]
            if len(sub) < MIN_N:
                continue  # skip too-small cells
            tr, vl, lk = split_train_val_lock(sub)
            if len(lk) == 0:
                continue
            full_pnl = sub.pnl_legacy_usd.values
            lk_dpt = float(lk.pnl_legacy_usd.mean()) if len(lk) else 0.0
            p = bootstrap_p(full_pnl, lk_dpt, len(lk))
            is_default = (thr == cfg["default_thr"])
            rows.append({
                "sleeve": sleeve_name, "gate": gate_name, "threshold": thr,
                "default_thr": cfg["default_thr"], "is_default": is_default, "is_optimal": False,
                "n_full": len(sub), "WR_full": float(sub.won.mean()),
                "dpt_full": float(sub.pnl_legacy_usd.mean()),
                "sum_full": float(sub.pnl_legacy_usd.sum()),
                "n_train": len(tr),
                "dpt_train": float(tr.pnl_legacy_usd.mean()) if len(tr) else 0.0,
                "WR_train": float(tr.won.mean()) if len(tr) else 0.0,
                "sum_train": float(tr.pnl_legacy_usd.sum()) if len(tr) else 0.0,
                "n_val": len(vl),
                "dpt_val": float(vl.pnl_legacy_usd.mean()) if len(vl) else 0.0,
                "WR_val": float(vl.won.mean()) if len(vl) else 0.0,
                "sum_val": float(vl.pnl_legacy_usd.sum()) if len(vl) else 0.0,
                "n_lockbox": len(lk),
                "dpt_lockbox": lk_dpt,
                "WR_lockbox": float(lk.won.mean()) if len(lk) else 0.0,
                "sum_lockbox": float(lk.pnl_legacy_usd.sum()) if len(lk) else 0.0,
                "boot_p_lockbox": p,
            })

    return pd.DataFrame(rows)


def main():
    log("=" * 72)
    log("THRESHOLD SWEEP — Task 1-5")
    log("=" * 72)

    all_rows = []
    for (name, fp, asset, tf, offs, gates) in SLEEVES:
        r = sweep_one_sleeve(name, fp, asset, tf, offs, gates)
        all_rows.append(r)
    df = pd.concat(all_rows, ignore_index=True)

    # Mark per-(sleeve, gate) optimal by sum_lockbox
    out_rows = []
    for (sleeve, gate), grp in df.groupby(["sleeve", "gate"], dropna=False):
        if gate == "(baseline_r1_only)":
            out_rows.append(grp)
            continue
        # Optimal by sum_lockbox among (sleeve, gate) thresholds
        idx_best = grp.sum_lockbox.idxmax()
        grp = grp.copy()
        grp["is_optimal"] = False
        grp.loc[idx_best, "is_optimal"] = True
        out_rows.append(grp)
    df = pd.concat(out_rows, ignore_index=True).sort_values(["sleeve", "gate", "threshold"]).reset_index(drop=True)

    df.to_csv(RES / "threshold_sweep.csv", index=False)
    log(f"wrote threshold_sweep.csv ({len(df)} rows)")

    # ============== TASK 2 — Optimization gain (per sleeve x gate) ==============
    log("\n# TASK 2 — Per-(sleeve, gate) default vs optimal lift")
    gain_rows = []
    for (sleeve, gate), grp in df.groupby(["sleeve", "gate"]):
        if gate == "(baseline_r1_only)":
            continue
        default_row = grp[grp.is_default == True]
        optimal_row = grp[grp.is_optimal == True]
        if len(default_row) == 0 or len(optimal_row) == 0:
            continue
        d = default_row.iloc[0]
        o = optimal_row.iloc[0]
        gain_rows.append({
            "sleeve": sleeve, "gate": gate,
            "default_thr": d.threshold,
            "default_n_lk": d.n_lockbox, "default_dpt_lk": d.dpt_lockbox,
            "default_sum_lk": d.sum_lockbox, "default_WR_lk": d.WR_lockbox,
            "default_p": d.boot_p_lockbox,
            "optimal_thr": o.threshold,
            "optimal_n_lk": o.n_lockbox, "optimal_dpt_lk": o.dpt_lockbox,
            "optimal_sum_lk": o.sum_lockbox, "optimal_WR_lk": o.WR_lockbox,
            "optimal_p": o.boot_p_lockbox,
            "sum_lift_lk": o.sum_lockbox - d.sum_lockbox,
            "dpt_lift_lk": o.dpt_lockbox - d.dpt_lockbox,
            "n_change": o.n_lockbox - d.n_lockbox,
        })
    gain_df = pd.DataFrame(gain_rows)
    gain_df.to_csv(RES / "threshold_gain_per_sleeve_gate.csv", index=False)
    log(f"wrote threshold_gain_per_sleeve_gate.csv ({len(gain_df)} rows)")

    # ============== TASK 3 — Per-sleeve threshold profile ==============
    log("\n# TASK 3 — Per-sleeve optimal-threshold profile")
    profile_rows = []
    for sleeve in df.sleeve.unique():
        sleeve_opts = df[(df.sleeve == sleeve) & (df.is_optimal == True)]
        for _, r in sleeve_opts.iterrows():
            profile_rows.append({
                "sleeve": sleeve, "gate": r.gate, "optimal_threshold": r.threshold,
                "n_lk": r.n_lockbox, "dpt_lk": r.dpt_lockbox, "sum_lk": r.sum_lockbox,
                "WR_lk": r.WR_lockbox, "boot_p": r.boot_p_lockbox,
            })
    profile_df = pd.DataFrame(profile_rows)
    profile_df.to_csv(RES / "threshold_profile_per_sleeve.csv", index=False)
    log(f"wrote threshold_profile_per_sleeve.csv ({len(profile_df)} rows)")

    log("\nDONE")


if __name__ == "__main__":
    main()
