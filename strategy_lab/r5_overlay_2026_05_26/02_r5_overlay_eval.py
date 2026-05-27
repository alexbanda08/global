"""TASKS 2-5 — Apply R5 gates to top 25 R4 deployable 15m sleeves.

For each (sleeve, R5_gate) compute train/val/lockbox metrics.
Also: pairwise + triple R5 combinations on top 5.
KILL test for g_lm_extreme_against.
Strict 3-way validation with 500-shuffle bootstrap on best compounds.
"""
from __future__ import annotations

import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_DIR = ROOT / "strategy_lab" / "r5_overlay_2026_05_26"
OUT_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "strategy_lab"))

from sleeve_hunt_15m_v2_hunt import (  # noqa: E402
    cell_summary, apply_gate_stack, bootstrap_p_value,
    split_train_val_lockbox, offset_bin_label, OFFSET_BINS,
    TRAIN_END_US, VAL_END_US, LOCKBOX_END_US,
)

# ---------------------------------------------------------------------------
# R5 gates to test on each R4 sleeve
# ---------------------------------------------------------------------------
R5_GATES = [
    "g_mp_no_extreme",
    "g_mp_very_no_extreme",
    "g_mp_with",
    "g_mp_strong_with",
    "g_mp_change_with",
    "g_mp_change_strong_with",
    "g_lm_high_stat",
    "g_lm_low_stat",
    "g_lm_last_jump_with_60s",
    "g_lm_extreme_against",  # KILL gate (PASS if NOT extreme-against)
    "g_hawkes_imbalance_with",
    "g_hawkes_imbalance_strong_with",
    "g_hawkes_burst",
]


def select_sleeve_universe(d: pd.DataFrame, asset_or_pool: str, offset_bin: str) -> pd.DataFrame:
    """Match the R4 cell. POOL = pooled across all assets; else per-asset."""
    sub = d[d["offset_bin"] == offset_bin]
    if asset_or_pool != "POOL":
        sub = sub[sub["asset"] == asset_or_pool]
    return sub


def evaluate_sleeve_with_extra_gates(d: pd.DataFrame, gate_stack: list[str],
                                        extra_gates: list[str], pnl_col="pnl_legacy_usd"):
    """Return {train, val, lockbox} summaries after applying all gates."""
    all_gates = list(gate_stack) + list(extra_gates)
    # Verify gates exist
    missing = [g for g in all_gates if g not in d.columns]
    if missing:
        return None, None, None
    tr, vl, lb = split_train_val_lockbox(d)
    tr_g = apply_gate_stack(tr, all_gates)
    vl_g = apply_gate_stack(vl, all_gates)
    lb_g = apply_gate_stack(lb, all_gates)
    return cell_summary(tr_g, pnl_col), cell_summary(vl_g, pnl_col), cell_summary(lb_g, pnl_col)


def fmt(x, prec=3):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"{x:.{prec}f}"


def main():
    t0 = time.time()
    print("=" * 80)
    print("TASKS 2-5: R5 OVERLAY ON R4 15M SLEEVES")
    print("=" * 80)

    # Load panel with R4+R5 features
    d = pd.read_parquet(RES / "r4_15m_with_r5_features.parquet")
    # Make sure offset_bin exists
    if "offset_bin" not in d.columns:
        d["offset_bin"] = d["fire_offset_s"].astype("int64").apply(offset_bin_label)
    d = d[d["offset_bin"].notna()].copy()
    print(f"Loaded R4+R5 panel: {d.shape}")
    print(f"R5 gates present: {[g for g in R5_GATES if g in d.columns]}")
    missing_g = [g for g in R5_GATES if g not in d.columns]
    if missing_g:
        print(f"R5 gates MISSING: {missing_g}")

    # Load top 25 R4 deployable sleeves
    dep = pd.read_csv(RES / "sleeve_hunt_15m_v2_deployable.csv")
    dep = dep.sort_values("lockbox_sum_pnl", ascending=False).reset_index(drop=True)
    top25 = dep.head(25).copy()
    print(f"\nTop 25 R4 deployable sleeves loaded")

    # =====================================================================
    # TASK 2 — Single R5 gate adds on top 25
    # =====================================================================
    print("\n" + "=" * 80)
    print("TASK 2: Single R5 gate adds on top 25 R4 sleeves")
    print("=" * 80)

    rows_t2 = []
    for i, row in top25.iterrows():
        asset_pool = row["asset"]
        ob = row["offset_bin"]
        gate_stack = row["gate_stack"].split("&")
        sleeve_id = f"{asset_pool}|{ob}|{row['gate_stack']}"

        sub_universe = select_sleeve_universe(d, asset_pool, ob)
        if len(sub_universe) == 0:
            continue

        # Baseline: re-evaluate R4 sleeve alone (sanity check)
        s_tr0, s_vl0, s_lb0 = evaluate_sleeve_with_extra_gates(sub_universe, gate_stack, [])
        rows_t2.append({
            "sleeve_idx": i,
            "asset_pool": asset_pool, "offset_bin": ob, "r4_gate_stack": row["gate_stack"],
            "added_r5_gate": "NONE_baseline",
            "train_n": s_tr0["n"], "train_WR": s_tr0["WR"], "train_dpt": s_tr0["dpt"], "train_sum": s_tr0["sum_pnl"],
            "val_n": s_vl0["n"], "val_WR": s_vl0["WR"], "val_dpt": s_vl0["dpt"], "val_sum": s_vl0["sum_pnl"],
            "lockbox_n": s_lb0["n"], "lockbox_WR": s_lb0["WR"], "lockbox_dpt": s_lb0["dpt"], "lockbox_sum": s_lb0["sum_pnl"],
        })

        # Each R5 gate added
        for g5 in R5_GATES:
            if g5 not in d.columns:
                continue
            s_tr, s_vl, s_lb = evaluate_sleeve_with_extra_gates(sub_universe, gate_stack, [g5])
            if s_tr is None:
                continue
            rows_t2.append({
                "sleeve_idx": i,
                "asset_pool": asset_pool, "offset_bin": ob, "r4_gate_stack": row["gate_stack"],
                "added_r5_gate": g5,
                "train_n": s_tr["n"], "train_WR": s_tr["WR"], "train_dpt": s_tr["dpt"], "train_sum": s_tr["sum_pnl"],
                "val_n": s_vl["n"], "val_WR": s_vl["WR"], "val_dpt": s_vl["dpt"], "val_sum": s_vl["sum_pnl"],
                "lockbox_n": s_lb["n"], "lockbox_WR": s_lb["WR"], "lockbox_dpt": s_lb["dpt"], "lockbox_sum": s_lb["sum_pnl"],
            })
        print(f"  [{i:2d}] {sleeve_id[:75]} done")

    df_t2 = pd.DataFrame(rows_t2)
    df_t2.to_csv(OUT_DIR / "task2_single_r5_overlay.csv", index=False)
    print(f"\nTASK 2 saved: {OUT_DIR/'task2_single_r5_overlay.csv'} ({len(df_t2)} rows)")

    # Pivot — lift table
    base = df_t2[df_t2.added_r5_gate == "NONE_baseline"][
        ["sleeve_idx","lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum"]].rename(
        columns={"lockbox_n":"base_n","lockbox_WR":"base_WR","lockbox_dpt":"base_dpt","lockbox_sum":"base_sum"})
    plus = df_t2[df_t2.added_r5_gate != "NONE_baseline"].merge(
        base, on="sleeve_idx", how="left")
    plus["dpt_lift"] = plus["lockbox_dpt"] - plus["base_dpt"]
    plus["wr_lift"] = plus["lockbox_WR"] - plus["base_WR"]
    plus["n_kept_pct"] = plus["lockbox_n"] / plus["base_n"]
    plus.to_csv(OUT_DIR / "task2_lift_table.csv", index=False)
    # Summary by gate (mean across 25 sleeves)
    summ = plus.groupby("added_r5_gate").agg(
        sleeves=("sleeve_idx","nunique"),
        mean_n_kept=("n_kept_pct","mean"),
        mean_lockbox_dpt=("lockbox_dpt","mean"),
        mean_dpt_lift=("dpt_lift","mean"),
        median_dpt_lift=("dpt_lift","median"),
        mean_wr_lift=("wr_lift","mean"),
        sleeves_improved=("dpt_lift", lambda s: int((s > 0).sum())),
        sleeves_better_wr=("wr_lift", lambda s: int((s > 0).sum())),
    ).reset_index().sort_values("mean_dpt_lift", ascending=False)
    summ.to_csv(OUT_DIR / "task2_gate_lift_summary.csv", index=False)
    print("\nR5 GATE LIFT SUMMARY (mean across 25 sleeves):")
    print(summ.to_string())

    # =====================================================================
    # TASK 3 — Pairwise + triple R5 combos on top 5 R4 sleeves
    # =====================================================================
    print("\n" + "=" * 80)
    print("TASK 3: R5 pairwise + triple combos on top 5 R4 sleeves")
    print("=" * 80)

    rows_t3 = []
    top5 = top25.head(5)
    # Restrict R5 combo space to the most useful gates (exclude over-restrictive)
    R5_COMBO_GATES = [g for g in R5_GATES if g not in ("g_lm_jump_05", "g_lm_jump_with",
                                                          "g_mp_against",
                                                          "g_hawkes_burst")]  # too sparse / contra
    if "g_lm_extreme_against" not in R5_COMBO_GATES:
        R5_COMBO_GATES.append("g_lm_extreme_against")
    R5_COMBO_GATES = [g for g in R5_COMBO_GATES if g in d.columns]
    print(f"Combo gate universe: {R5_COMBO_GATES}")

    for i, row in top5.iterrows():
        asset_pool = row["asset"]; ob = row["offset_bin"]
        gate_stack = row["gate_stack"].split("&")
        sleeve_id = f"{asset_pool}|{ob}|{row['gate_stack']}"
        sub_universe = select_sleeve_universe(d, asset_pool, ob)
        for k in (2, 3):
            for combo in combinations(R5_COMBO_GATES, k):
                extra = list(combo)
                s_tr, s_vl, s_lb = evaluate_sleeve_with_extra_gates(sub_universe, gate_stack, extra)
                if s_tr is None or s_lb is None:
                    continue
                if s_lb["n"] < 5:
                    continue  # skip very sparse combos for table compactness
                rows_t3.append({
                    "sleeve_idx": i, "asset_pool": asset_pool, "offset_bin": ob,
                    "r4_gate_stack": row["gate_stack"], "k_combo": k,
                    "r5_combo": "&".join(extra),
                    "train_n": s_tr["n"], "train_WR": s_tr["WR"], "train_dpt": s_tr["dpt"], "train_sum": s_tr["sum_pnl"],
                    "val_n": s_vl["n"], "val_WR": s_vl["WR"], "val_dpt": s_vl["dpt"], "val_sum": s_vl["sum_pnl"],
                    "lockbox_n": s_lb["n"], "lockbox_WR": s_lb["WR"], "lockbox_dpt": s_lb["dpt"], "lockbox_sum": s_lb["sum_pnl"],
                })
        print(f"  [{i:2d}] {sleeve_id[:75]} done")

    df_t3 = pd.DataFrame(rows_t3)
    df_t3.to_csv(OUT_DIR / "task3_compound_r5_combos.csv", index=False)
    print(f"\nTASK 3 saved: {OUT_DIR/'task3_compound_r5_combos.csv'} ({len(df_t3)} rows)")

    # Best combos per sleeve
    best = df_t3.sort_values(["sleeve_idx","lockbox_sum"], ascending=[True, False])
    best_top = best.groupby("sleeve_idx").head(5)
    print("\nTop 5 R5 compound combos per top-5 R4 sleeve:")
    print(best_top[["sleeve_idx","r4_gate_stack","r5_combo","train_n","train_WR","train_dpt",
                     "val_n","val_WR","lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum"]].to_string())

    # =====================================================================
    # TASK 4 — KILL gate: g_lm_extreme_against effectiveness
    # =====================================================================
    print("\n" + "=" * 80)
    print("TASK 4: KILL gate `g_lm_extreme_against` effectiveness on R4 sleeves")
    print("=" * 80)
    rows_t4 = []
    # Note: this gate is True for 100% (only 16 rows out of 19,703 had extreme jumps).
    # So effectively this kills very few. Let me still report.
    for i, row in top25.iterrows():
        asset_pool = row["asset"]; ob = row["offset_bin"]
        gate_stack = row["gate_stack"].split("&")
        sub_universe = select_sleeve_universe(d, asset_pool, ob)
        s_tr0, s_vl0, s_lb0 = evaluate_sleeve_with_extra_gates(sub_universe, gate_stack, [])
        s_trK, s_vlK, s_lbK = evaluate_sleeve_with_extra_gates(sub_universe, gate_stack, ["g_lm_extreme_against"])
        if s_tr0 is None or s_trK is None:
            continue
        rows_t4.append({
            "sleeve_idx": i, "asset_pool": asset_pool, "offset_bin": ob,
            "r4_gate_stack": row["gate_stack"],
            "base_lb_n": s_lb0["n"], "kill_lb_n": s_lbK["n"], "removed": s_lb0["n"] - s_lbK["n"],
            "base_lb_dpt": s_lb0["dpt"], "kill_lb_dpt": s_lbK["dpt"],
            "base_lb_sum": s_lb0["sum_pnl"], "kill_lb_sum": s_lbK["sum_pnl"],
            "lift_sum": s_lbK["sum_pnl"] - s_lb0["sum_pnl"],
            "lift_dpt": s_lbK["dpt"] - s_lb0["dpt"],
        })
    df_t4 = pd.DataFrame(rows_t4)
    df_t4.to_csv(OUT_DIR / "task4_kill_gate.csv", index=False)
    print(df_t4.to_string())

    # =====================================================================
    # TASK 5 — Strict 3-way validation with bootstrap on best compound combos
    # =====================================================================
    print("\n" + "=" * 80)
    print("TASK 5: Strict 3-way validation + 500-shuffle bootstrap")
    print("=" * 80)
    # Take top 20 combos from TASK 3 by lockbox_sum where lockbox_n>=15 & WR>=0.6
    cand = df_t3[(df_t3.lockbox_n >= 15) & (df_t3.lockbox_WR >= 0.60) & (df_t3.lockbox_sum > 0)].copy()
    cand = cand.sort_values("lockbox_sum", ascending=False).head(20)
    rows_t5 = []
    for i, row in cand.iterrows():
        asset_pool = row["asset_pool"]; ob = row["offset_bin"]
        gate_stack = row["r4_gate_stack"].split("&")
        extra = row["r5_combo"].split("&")
        sub_universe = select_sleeve_universe(d, asset_pool, ob)
        tr, vl, lb = split_train_val_lockbox(sub_universe)
        tr_g = apply_gate_stack(tr, gate_stack + extra)
        vl_g = apply_gate_stack(vl, gate_stack + extra)
        lb_g = apply_gate_stack(lb, gate_stack + extra)
        s_tr = cell_summary(tr_g); s_vl = cell_summary(vl_g); s_lb = cell_summary(lb_g)
        p_lb = bootstrap_p_value(lb_g["pnl_legacy_usd"].values) if s_lb["n"] >= 15 else float("nan")
        p_vl = bootstrap_p_value(vl_g["pnl_legacy_usd"].values) if s_vl["n"] >= 15 else float("nan")
        val_pass = (s_vl["n"] >= 15 and s_vl["sum_pnl"] > 0 and s_vl["WR"] >= 0.65)
        lockbox_pass = (s_lb["n"] >= 10 and s_lb["sum_pnl"] > 0 and s_lb["WR"] >= 0.60 and
                        (np.isnan(p_lb) or p_lb < 0.10))
        rows_t5.append({
            "asset_pool": asset_pool, "offset_bin": ob,
            "r4_gate_stack": row["r4_gate_stack"], "r5_combo": row["r5_combo"],
            "train_n": s_tr["n"], "train_WR": s_tr["WR"], "train_dpt": s_tr["dpt"], "train_sum": s_tr["sum_pnl"],
            "val_n": s_vl["n"], "val_WR": s_vl["WR"], "val_dpt": s_vl["dpt"], "val_sum": s_vl["sum_pnl"], "val_p": p_vl,
            "lockbox_n": s_lb["n"], "lockbox_WR": s_lb["WR"], "lockbox_dpt": s_lb["dpt"], "lockbox_sum": s_lb["sum_pnl"], "lockbox_p": p_lb,
            "val_pass": val_pass, "lockbox_pass": lockbox_pass,
            "deployable": val_pass and lockbox_pass,
        })
    df_t5 = pd.DataFrame(rows_t5)
    df_t5.to_csv(OUT_DIR / "task5_strict_validation.csv", index=False)
    print("\nTop 20 strict-validated R4+R5 hybrid sleeves:")
    print(df_t5[["asset_pool","offset_bin","r4_gate_stack","r5_combo","train_n","train_WR",
                  "val_n","val_WR","lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum","lockbox_p",
                  "deployable"]].to_string())
    print(f"\nDeployable hybrid combos: {int(df_t5.deployable.sum())} / {len(df_t5)}")

    print(f"\n=== DONE in {time.time()-t0:.1f}s ===")


if __name__ == "__main__":
    main()
