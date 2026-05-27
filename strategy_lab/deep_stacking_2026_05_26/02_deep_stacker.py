"""Deep stacking — TASK 2-5: greedy add gates, 3-way validation, deep tests.

For each top sleeve:
  1. Start with R1 hybrid_v1 gate stack
  2. Greedy add R3+R5 gates one at a time (maximizes objective subject to n>=30)
  3. Record per-depth k: stack, n, WR, $/tr, sum
  4. Build diminishing returns curve

Outputs:
  data/v4/canonical/_results/deep_stack_results.csv  (per-sleeve × depth)
  data/v4/canonical/_results/deep_stack_per_gate_lift.csv
  data/v4/canonical/_results/deep_stack_universal_gates.csv
  data/v4/canonical/_results/deep_stack_negative_test.csv  (10-gate stacks)
  data/v4/canonical/_results/deep_stack_3way_validation.csv
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

# Top sleeves with their hybrid_v1 (R1) baselines
SLEEVES = [
    # (name, panel_file, asset, tf, offsets, hybrid_v1_gates)
    ("BTC_S6_60_150", "deep_stack_panel_s6.parquet", "BTC", "5m", [60, 90, 120, 150],
     ["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50", "g_ribbon_agrees"]),
    ("ETH_S6_60_150", "deep_stack_panel_s6.parquet", "ETH", "5m", [60, 90, 120, 150],
     ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"]),
    ("SOL_S6_60_150", "deep_stack_panel_s6.parquet", "SOL", "5m", [60, 90, 120, 150],
     ["g_mfi_with", "g_within_dev", "g_bb_pos_with", "g_ribbon_agrees"]),
    ("BTC_S15_150_240", "deep_stack_panel_s15.parquet", "BTC", "5m", [150, 180, 210, 240],
     ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with", "g_tight_ribbon"]),
    ("ETH_S15_150_240", "deep_stack_panel_s15.parquet", "ETH", "5m", [150, 180, 210, 240],
     ["g_ribbon_agrees", "g_tr_above_ema200", "g_stoch_with", "g_bb_pos_with", "g_cci_with"]),
    ("S7_btc_5m_base", "deep_stack_panel_v15m.parquet", "BTC", "15m", [480, 600, 720, 840],
     ["g_tr_stack_full_with", "g_tr_above_ema800", "g_ribbon_agrees", "g_tight_ribbon",
      "g_stoch_with", "g_tr_above_ema200"]),
]

# R3+R5 candidate gates to greedy-add (after R1 baseline)
R3R5_GATES = [
    # R5 microprice
    "g_r5_mp_no_extreme", "g_r5_mp_change_with", "g_r5_mp_skew_with",
    # R5 Lee-Mykland
    "g_r5_lm_high_stat", "g_r5_lm_recent_jump_with",
    # NOTE: g_r5_lm_extreme_against is a KILL gate — exclude as adder
    # R5 Hawkes
    "g_r5_hawkes_imbalance_with",
    # R5 Avellaneda
    "g_r5_as_low_uncert",
    # R3 vol/Hurst
    "g_r3_vol_expanding", "g_r3_vol_contracting",
    "g_r3_vol_high", "g_r3_vol_med",
    "g_r3_hurst_trending",
    # R3 microstructure
    "g_r3_imb5_with", "g_r3_imb5_strong_with",
    "g_r3_queue_top_high", "g_r3_imb_change_with",
    "g_r3_book_slope_steep_against",
]

MIN_N = 30


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def apply_stack(df: pd.DataFrame, gates: list[str]) -> np.ndarray:
    """Return boolean mask where ALL gates pass (==1)."""
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


def greedy_add_gate(base: pd.DataFrame, current_stack: list[str],
                    candidates: list[str], objective: str = "sum_pnl",
                    min_n: int = MIN_N) -> tuple[str | None, dict]:
    """For the current stack on `base`, find the best gate to add (max objective)
    subject to n >= min_n. Return (gate_name, new_stats) or (None, current_stats).
    """
    cur_mask = apply_stack(base, current_stack)
    cur_sub = base[cur_mask]
    cur_stats = cell_stats(cur_sub)

    best_gate = None
    best_score = -1e18
    best_stats = None
    for g in candidates:
        if g in current_stack:
            continue
        new_mask = cur_mask & (base[g].values == 1)
        if new_mask.sum() < min_n:
            continue
        sub = base[new_mask]
        st = cell_stats(sub)
        if objective == "sum_pnl":
            score = st["sum_pnl"]
        elif objective == "sum_x_wr":
            score = st["sum_pnl"] * st["WR"]
        else:
            score = st["dpt"]
        if score > best_score:
            best_score = score
            best_gate = g
            best_stats = st

    # Accept only if strictly improves sum_pnl
    if best_gate is None:
        return None, cur_stats
    if best_stats["sum_pnl"] <= cur_stats["sum_pnl"]:
        return None, cur_stats
    return best_gate, best_stats


def run_per_sleeve(sleeve_name: str, panel_file: str, asset: str, tf_filter: str,
                   offsets: list[int], hybrid_v1_gates: list[str]) -> pd.DataFrame:
    """For one sleeve, run greedy deep stacking and record per-depth metrics."""
    log(f"=== {sleeve_name} ===")
    df = pd.read_parquet(RES / panel_file)

    # Filter to this sleeve's universe
    mask = (df.asset == asset) & (df.fire_offset_s.isin(offsets))
    if "tf" in df.columns:
        mask &= (df.tf == tf_filter)
    universe = df[mask].copy()
    log(f"  universe: {len(universe):,} fires")
    if len(universe) == 0:
        return pd.DataFrame()

    # Baseline (NO gates)
    rows = []
    st = cell_stats(universe)
    rows.append({
        "sleeve": sleeve_name, "k": 0, "stack": "(baseline_no_gates)",
        "added_gate": "", **st,
    })
    log(f"  baseline: n={st['n']}, sum=${st['sum_pnl']:.0f}, dpt=${st['dpt']:.3f}, WR={st['WR']*100:.1f}%")

    # hybrid_v1 stack
    cur_stack = list(hybrid_v1_gates)
    cur_mask = apply_stack(universe, cur_stack)
    st = cell_stats(universe[cur_mask])
    rows.append({
        "sleeve": sleeve_name, "k": len(cur_stack), "stack": " & ".join(cur_stack),
        "added_gate": "(hybrid_v1)", **st,
    })
    log(f"  hybrid_v1 (k={len(cur_stack)}): n={st['n']}, sum=${st['sum_pnl']:.0f}, dpt=${st['dpt']:.3f}, WR={st['WR']*100:.1f}%")

    # Greedy add R3+R5 gates one at a time
    k = len(cur_stack)
    for step in range(15):  # max 15 adds (way beyond saturation)
        gate, stats_after = greedy_add_gate(
            universe, cur_stack, R3R5_GATES, objective="sum_pnl", min_n=MIN_N
        )
        if gate is None:
            log(f"  k={k+1}: NO improvement, stop")
            break
        cur_stack.append(gate)
        k += 1
        rows.append({
            "sleeve": sleeve_name, "k": k, "stack": " & ".join(cur_stack),
            "added_gate": gate, **stats_after,
        })
        log(f"  k={k}: +{gate}  -> n={stats_after['n']}, sum=${stats_after['sum_pnl']:.0f}, "
            f"dpt=${stats_after['dpt']:.3f}, WR={stats_after['WR']*100:.1f}%")

    return pd.DataFrame(rows)


def negative_test_deep_stack(sleeve_name: str, panel_file: str, asset: str, tf_filter: str,
                              offsets: list[int], hybrid_v1_gates: list[str],
                              all_adders: list[str]) -> dict:
    """Force-stack ALL gates (R1 + ALL R3+R5) and see what happens."""
    df = pd.read_parquet(RES / panel_file)
    mask = (df.asset == asset) & (df.fire_offset_s.isin(offsets))
    if "tf" in df.columns:
        mask &= (df.tf == tf_filter)
    universe = df[mask].copy()

    # Use top 5 most-frequent R3+R5 gates (those that are positive in literature)
    forced_adders = ["g_r5_mp_no_extreme", "g_r3_vol_expanding", "g_r5_lm_high_stat",
                     "g_r5_hawkes_imbalance_with", "g_r3_imb5_strong_with"]
    full_stack = list(hybrid_v1_gates) + forced_adders
    m = apply_stack(universe, full_stack)
    sub = universe[m]
    st = cell_stats(sub)
    return {"sleeve": sleeve_name, "n_gates": len(full_stack), "stack": " & ".join(full_stack), **st}


def three_way_split_validation(sleeve_name: str, panel_file: str, asset: str, tf_filter: str,
                               offsets: list[int], stack: list[str]) -> dict:
    """Train (first 67%) / val (next 17%) / lockbox (last 16%) split + 500 bootstrap on lockbox."""
    df = pd.read_parquet(RES / panel_file)
    mask = (df.asset == asset) & (df.fire_offset_s.isin(offsets))
    if "tf" in df.columns:
        mask &= (df.tf == tf_filter)
    universe = df[mask].copy()

    m = apply_stack(universe, stack)
    sub = universe[m].sort_values("fire_us").reset_index(drop=True)
    if len(sub) < 30:
        return {"sleeve": sleeve_name, "stack": " & ".join(stack), "n_total": len(sub),
                "deployable": False, "note": "too_few"}

    n = len(sub)
    n_tr = int(n * 0.67)
    n_vl = int(n * 0.17)
    train = sub.iloc[:n_tr]
    val = sub.iloc[n_tr:n_tr + n_vl]
    lock = sub.iloc[n_tr + n_vl:]

    # Bootstrap 500 shuffles
    rng = np.random.default_rng(42)
    n_lk = len(lock)
    full_pnl = sub.pnl_legacy_usd.values
    actual = float(lock.pnl_legacy_usd.mean())
    null_dpts = np.empty(500)
    for i in range(500):
        sample = rng.choice(full_pnl, size=max(n_lk, 1), replace=True)
        null_dpts[i] = float(sample.mean())
    boot_p = float(np.mean(null_dpts >= actual))

    return {
        "sleeve": sleeve_name, "stack": " & ".join(stack),
        "n_total": n, "k": len(stack),
        "n_train": len(train), "dpt_train": float(train.pnl_legacy_usd.mean()) if len(train) else 0.0,
        "wr_train": float(train.won.mean()) if len(train) else 0.0,
        "sum_train": float(train.pnl_legacy_usd.sum()) if len(train) else 0.0,
        "n_val": len(val), "dpt_val": float(val.pnl_legacy_usd.mean()) if len(val) else 0.0,
        "wr_val": float(val.won.mean()) if len(val) else 0.0,
        "sum_val": float(val.pnl_legacy_usd.sum()) if len(val) else 0.0,
        "n_lockbox": n_lk, "dpt_lockbox": actual,
        "wr_lockbox": float(lock.won.mean()) if n_lk else 0.0,
        "sum_lockbox": float(lock.pnl_legacy_usd.sum()) if n_lk else 0.0,
        "boot_p": boot_p,
        "deployable": bool(
            n_lk >= 20 and lock.pnl_legacy_usd.sum() > 0 and
            lock.won.mean() >= 0.55 and boot_p <= 0.10
        ),
    }


def per_gate_marginal_lift_per_sleeve(sleeve_name: str, panel_file: str, asset: str, tf_filter: str,
                                       offsets: list[int], hybrid_v1_gates: list[str]) -> pd.DataFrame:
    """For each R3+R5 gate, compute SINGLE-add lift (hybrid_v1 + 1 gate) — for universal scan."""
    df = pd.read_parquet(RES / panel_file)
    mask = (df.asset == asset) & (df.fire_offset_s.isin(offsets))
    if "tf" in df.columns:
        mask &= (df.tf == tf_filter)
    universe = df[mask].copy()

    base_mask = apply_stack(universe, hybrid_v1_gates)
    base_sub = universe[base_mask]
    base_stats = cell_stats(base_sub)
    rows = [{"sleeve": sleeve_name, "added_gate": "(baseline_hybrid_v1)", **base_stats,
             "dpt_lift": 0.0, "sum_lift": 0.0}]

    for g in R3R5_GATES:
        new_mask = base_mask & (universe[g].values == 1)
        if new_mask.sum() < MIN_N:
            continue
        new_sub = universe[new_mask]
        st = cell_stats(new_sub)
        rows.append({
            "sleeve": sleeve_name, "added_gate": g, **st,
            "dpt_lift": st["dpt"] - base_stats["dpt"],
            "sum_lift": st["sum_pnl"] - base_stats["sum_pnl"],
        })
    return pd.DataFrame(rows)


def main():
    log("=" * 72)
    log("DEEP STACKING — Tasks 2-6")
    log("=" * 72)

    # ===================== TASK 2: per-sleeve greedy deep stacking =====================
    log("\n\n# TASK 2 — Greedy deep stacking")
    all_rows = []
    for (name, fp, asset, tf, offs, v1_gates) in SLEEVES:
        rows = run_per_sleeve(name, fp, asset, tf, offs, v1_gates)
        all_rows.append(rows)
    deep_results = pd.concat(all_rows, ignore_index=True)
    deep_results.to_csv(RES / "deep_stack_results.csv", index=False)
    log(f"wrote deep_stack_results.csv ({len(deep_results)} rows)")

    # ===================== TASK 3 + 4 — single-gate marginal lifts (universal scan) =====================
    log("\n\n# TASK 3+4 — Single-gate marginal lifts per sleeve (for universal-gate detection)")
    all_lifts = []
    for (name, fp, asset, tf, offs, v1_gates) in SLEEVES:
        lifts = per_gate_marginal_lift_per_sleeve(name, fp, asset, tf, offs, v1_gates)
        all_lifts.append(lifts)
    lifts_df = pd.concat(all_lifts, ignore_index=True)
    lifts_df.to_csv(RES / "deep_stack_per_gate_lift.csv", index=False)
    log(f"wrote deep_stack_per_gate_lift.csv ({len(lifts_df)} rows)")

    # Universal gates: those positive on ≥4 of 6 sleeves
    only_gates = lifts_df[lifts_df.added_gate.str.startswith("g_")]
    univ = (only_gates.groupby("added_gate")
            .agg(n_sleeves=("sleeve", "nunique"),
                 mean_dpt_lift=("dpt_lift", "mean"),
                 median_dpt_lift=("dpt_lift", "median"),
                 mean_sum_lift=("sum_lift", "mean"),
                 n_positive=("sum_lift", lambda x: int((x > 0).sum())))
            .reset_index()
            .sort_values("mean_sum_lift", ascending=False))
    univ.to_csv(RES / "deep_stack_universal_gates.csv", index=False)
    log(f"wrote deep_stack_universal_gates.csv ({len(univ)} rows)")
    log("Top 10 universal gates by mean_sum_lift:")
    print(univ.head(10).to_string(index=False))

    # ===================== TASK 5 — negative test: deep stack ALL gates =====================
    log("\n\n# TASK 5 — Negative test: deep stack (R1 + 5 forced R3/R5 adders = 10-11 gates)")
    neg_rows = []
    for (name, fp, asset, tf, offs, v1_gates) in SLEEVES:
        st = negative_test_deep_stack(name, fp, asset, tf, offs, v1_gates, R3R5_GATES)
        neg_rows.append(st)
        log(f"  {name}: 10-gate stack n={st['n']}, sum=${st['sum_pnl']:.0f}, dpt=${st['dpt']:.3f}, WR={st['WR']*100:.1f}%")
    neg_df = pd.DataFrame(neg_rows)
    neg_df.to_csv(RES / "deep_stack_negative_test.csv", index=False)
    log(f"wrote deep_stack_negative_test.csv ({len(neg_df)} rows)")

    # ===================== TASK 6 — 3-way validation on top stacks =====================
    log("\n\n# TASK 6 — 3-way (train/val/lockbox) + 500-bootstrap on top deep stacks")
    val_rows = []
    for (name, fp, asset, tf, offs, v1_gates) in SLEEVES:
        # use best deep stack from TASK 2 results
        sub = deep_results[deep_results.sleeve == name].copy()
        if len(sub) == 0:
            continue
        # top deep stack by sum_pnl
        best = sub.iloc[sub.sum_pnl.argmax()]
        stack_list = best.stack.split(" & ") if best.stack != "(baseline_no_gates)" else []
        if not stack_list:
            continue
        v = three_way_split_validation(name, fp, asset, tf, offs, stack_list)
        v["best_k"] = best.k
        v["best_sum_full"] = best.sum_pnl
        v["best_dpt_full"] = best.dpt
        v["best_wr_full"] = best.WR
        val_rows.append(v)
        log(f"  {name}: k={best.k}, lockbox dpt=${v['dpt_lockbox']:.3f}, "
            f"sum=${v['sum_lockbox']:.0f}, n_lk={v['n_lockbox']}, "
            f"WR_lk={v['wr_lockbox']*100:.1f}%, p={v['boot_p']:.3f}, deploy={v['deployable']}")

    # Also validate hybrid_v1 baseline for comparison
    log("\n  hybrid_v1 baselines (3-way):")
    for (name, fp, asset, tf, offs, v1_gates) in SLEEVES:
        v = three_way_split_validation(name + "_HYBRIDV1", fp, asset, tf, offs, v1_gates)
        v["best_k"] = len(v1_gates)
        v["best_sum_full"] = 0
        v["best_dpt_full"] = 0
        v["best_wr_full"] = 0
        val_rows.append(v)
        log(f"  {name}_v1: k={len(v1_gates)}, lockbox dpt=${v['dpt_lockbox']:.3f}, "
            f"sum=${v['sum_lockbox']:.0f}, n_lk={v['n_lockbox']}, "
            f"WR_lk={v['wr_lockbox']*100:.1f}%, p={v['boot_p']:.3f}, deploy={v['deployable']}")

    val_df = pd.DataFrame(val_rows)
    val_df.to_csv(RES / "deep_stack_3way_validation.csv", index=False)
    log(f"wrote deep_stack_3way_validation.csv ({len(val_df)} rows)")

    # Done — summary
    log("\n" + "=" * 72)
    log("DONE")
    log("=" * 72)


if __name__ == "__main__":
    main()
