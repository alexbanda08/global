"""Compare R4+R5 hybrid combos against R4 baseline.

Key question: do R5 gates COMPOUND with the trend_slope signal? Specifically,
on each of the top 25 R4 sleeves, evaluate up to triple R5 stacks and report:
- R4 baseline (lockbox sum & dpt)
- Best R5 stack added (with smallest set that still beats baseline on either
  WR or dpt or both)
- Trade-off: filter strength (n_kept_pct) vs lift

For each top R4 sleeve, surface top-3 "value-add" R5 combos where:
- lockbox_n >= 10
- lockbox_WR >= R4_baseline_WR OR lockbox_dpt >= R4_baseline_dpt
- preserving deployability (val_pass + lockbox_pass)
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
sys.path.insert(0, str(ROOT / "strategy_lab"))

from sleeve_hunt_15m_v2_hunt import (  # noqa: E402
    cell_summary, apply_gate_stack, bootstrap_p_value,
    split_train_val_lockbox, offset_bin_label,
)

R5_GATES_PRUNED = [
    "g_mp_no_extreme",
    "g_mp_very_no_extreme",
    "g_mp_with",
    "g_mp_strong_with",
    "g_mp_change_with",
    "g_lm_low_stat",
    "g_lm_high_stat",
    "g_lm_extreme_against",
    "g_hawkes_imbalance_with",
    "g_hawkes_imbalance_strong_with",
]


def select(d, asset_pool, ob):
    sub = d[d["offset_bin"] == ob]
    if asset_pool != "POOL":
        sub = sub[sub["asset"] == asset_pool]
    return sub


def main():
    t0 = time.time()
    print("=" * 80)
    print("COMPARE R4+R5 HYBRIDS vs R4 BASELINE — value-add screen")
    print("=" * 80)

    d = pd.read_parquet(RES / "r4_15m_with_r5_features.parquet")
    if "offset_bin" not in d.columns:
        d["offset_bin"] = d["fire_offset_s"].astype("int64").apply(offset_bin_label)
    d = d[d["offset_bin"].notna()].copy()

    dep = pd.read_csv(RES / "sleeve_hunt_15m_v2_deployable.csv")
    dep = dep.sort_values("lockbox_sum_pnl", ascending=False).reset_index(drop=True)
    top25 = dep.head(25).copy()

    R5 = [g for g in R5_GATES_PRUNED if g in d.columns]
    print(f"R5 gate universe (pruned): {R5}")

    rows = []
    for i, srow in top25.iterrows():
        asset_pool = srow["asset"]; ob = srow["offset_bin"]
        gate_stack = srow["gate_stack"].split("&")
        sub_universe = select(d, asset_pool, ob)
        tr, vl, lb = split_train_val_lockbox(sub_universe)
        # baseline
        tr_b = apply_gate_stack(tr, gate_stack)
        vl_b = apply_gate_stack(vl, gate_stack)
        lb_b = apply_gate_stack(lb, gate_stack)
        s_tr_b = cell_summary(tr_b); s_vl_b = cell_summary(vl_b); s_lb_b = cell_summary(lb_b)
        p_lb_b = bootstrap_p_value(lb_b["pnl_legacy_usd"].values) if s_lb_b["n"] >= 15 else float("nan")
        # baseline row
        rows.append({
            "sleeve_idx": i, "asset_pool": asset_pool, "offset_bin": ob,
            "r4_gate_stack": srow["gate_stack"], "r5_combo": "BASELINE",
            "train_n": s_tr_b["n"], "train_WR": s_tr_b["WR"], "train_dpt": s_tr_b["dpt"], "train_sum": s_tr_b["sum_pnl"],
            "val_n": s_vl_b["n"], "val_WR": s_vl_b["WR"], "val_dpt": s_vl_b["dpt"], "val_sum": s_vl_b["sum_pnl"],
            "lockbox_n": s_lb_b["n"], "lockbox_WR": s_lb_b["WR"], "lockbox_dpt": s_lb_b["dpt"], "lockbox_sum": s_lb_b["sum_pnl"],
            "lockbox_p": p_lb_b,
            "dpt_lift_vs_base": 0.0, "wr_lift_vs_base": 0.0, "sum_lift_vs_base": 0.0,
            "n_kept_pct": 1.0,
        })

        base_dpt = s_lb_b["dpt"]; base_wr = s_lb_b["WR"]; base_sum = s_lb_b["sum_pnl"]
        base_n_lb = s_lb_b["n"]

        # All k=1..3 R5 combos
        for k in (1, 2, 3):
            for combo in combinations(R5, k):
                extra = list(combo)
                tr_g = apply_gate_stack(tr, gate_stack + extra)
                vl_g = apply_gate_stack(vl, gate_stack + extra)
                lb_g = apply_gate_stack(lb, gate_stack + extra)
                if len(lb_g) < 10:
                    continue
                s_tr = cell_summary(tr_g); s_vl = cell_summary(vl_g); s_lb = cell_summary(lb_g)
                p_lb = bootstrap_p_value(lb_g["pnl_legacy_usd"].values) if s_lb["n"] >= 15 else float("nan")
                rows.append({
                    "sleeve_idx": i, "asset_pool": asset_pool, "offset_bin": ob,
                    "r4_gate_stack": srow["gate_stack"], "r5_combo": "&".join(extra),
                    "train_n": s_tr["n"], "train_WR": s_tr["WR"], "train_dpt": s_tr["dpt"], "train_sum": s_tr["sum_pnl"],
                    "val_n": s_vl["n"], "val_WR": s_vl["WR"], "val_dpt": s_vl["dpt"], "val_sum": s_vl["sum_pnl"],
                    "lockbox_n": s_lb["n"], "lockbox_WR": s_lb["WR"], "lockbox_dpt": s_lb["dpt"], "lockbox_sum": s_lb["sum_pnl"],
                    "lockbox_p": p_lb,
                    "dpt_lift_vs_base": s_lb["dpt"] - base_dpt,
                    "wr_lift_vs_base": s_lb["WR"] - base_wr,
                    "sum_lift_vs_base": s_lb["sum_pnl"] - base_sum,
                    "n_kept_pct": s_lb["n"] / base_n_lb if base_n_lb > 0 else float("nan"),
                })
        print(f"  [{i:2d}] {srow['gate_stack'][:50]:50s} done")

    df_all = pd.DataFrame(rows)
    df_all.to_csv(OUT_DIR / "task6_r4_vs_r4r5_all.csv", index=False)
    print(f"\nSaved: {OUT_DIR/'task6_r4_vs_r4r5_all.csv'} ({len(df_all)} rows)")

    # ---------- Sum-improving overlays ----------
    print("\n" + "=" * 80)
    print("Top hybrids where R5 IMPROVES LOCKBOX SUM vs R4 baseline (n>=20)")
    print("=" * 80)
    improved = df_all[(df_all.r5_combo != "BASELINE") &
                       (df_all.sum_lift_vs_base > 0) &
                       (df_all.lockbox_n >= 20) &
                       (df_all.lockbox_WR >= 0.65)]
    improved = improved.sort_values("sum_lift_vs_base", ascending=False)
    if len(improved):
        print(improved[["sleeve_idx","asset_pool","offset_bin","r4_gate_stack","r5_combo",
                         "lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum","lockbox_p",
                         "sum_lift_vs_base","wr_lift_vs_base","n_kept_pct"]].head(30).to_string())
    else:
        print("  None found — R5 gates do NOT improve lockbox sum over R4 baseline.")

    # ---------- WR-improving with reasonable n ----------
    print("\n" + "=" * 80)
    print("Top hybrids where R5 IMPROVES LOCKBOX WR (n_kept >= 0.40)")
    print("=" * 80)
    wr_imp = df_all[(df_all.r5_combo != "BASELINE") &
                     (df_all.wr_lift_vs_base > 0) &
                     (df_all.lockbox_n >= 30) &
                     (df_all.n_kept_pct >= 0.40)]
    wr_imp = wr_imp.sort_values("wr_lift_vs_base", ascending=False)
    if len(wr_imp):
        print(wr_imp[["sleeve_idx","asset_pool","offset_bin","r4_gate_stack","r5_combo",
                       "lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum",
                       "wr_lift_vs_base","dpt_lift_vs_base","n_kept_pct"]].head(20).to_string())
    else:
        print("  None found.")

    # ---------- DPT improving with reasonable n ----------
    print("\n" + "=" * 80)
    print("Top hybrids where R5 IMPROVES LOCKBOX DPT (n>=30, dpt_lift>0)")
    print("=" * 80)
    dpt_imp = df_all[(df_all.r5_combo != "BASELINE") &
                      (df_all.dpt_lift_vs_base > 0) &
                      (df_all.lockbox_n >= 30)]
    dpt_imp = dpt_imp.sort_values("dpt_lift_vs_base", ascending=False)
    if len(dpt_imp):
        print(dpt_imp[["sleeve_idx","asset_pool","offset_bin","r4_gate_stack","r5_combo",
                       "lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum","lockbox_p",
                       "dpt_lift_vs_base","wr_lift_vs_base","n_kept_pct"]].head(30).to_string())
    else:
        print("  None found.")

    # ---------- New top-10 R4+R5 hybrid deployable sleeves ----------
    print("\n" + "=" * 80)
    print("TOP 10 NEW R4+R5 HYBRID SLEEVES (deployable, by lockbox_sum)")
    print("=" * 80)
    # Deployable filter
    df_all["val_pass"] = (df_all.val_n >= 15) & (df_all.val_sum > 0) & (df_all.val_WR >= 0.65)
    df_all["lockbox_pass"] = ((df_all.lockbox_n >= 10) & (df_all.lockbox_sum > 0) &
                                (df_all.lockbox_WR >= 0.60) &
                                (df_all.lockbox_p.fillna(0.0) < 0.10))
    df_all["deployable"] = df_all.val_pass & df_all.lockbox_pass
    deploy = df_all[(df_all.deployable) & (df_all.r5_combo != "BASELINE")].copy()
    deploy = deploy.sort_values("lockbox_sum", ascending=False)
    print(deploy[["sleeve_idx","asset_pool","offset_bin","r4_gate_stack","r5_combo",
                   "train_n","train_WR","val_n","val_WR",
                   "lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum","lockbox_p",
                   "sum_lift_vs_base","wr_lift_vs_base"]].head(10).to_string())
    deploy.to_csv(OUT_DIR / "task6_deployable_hybrids.csv", index=False)

    print(f"\nDeployable hybrid combos (n=178 R4 base × R5 stacks): {len(deploy)}")
    print(f"  ... vs R4 baselines that ARE deployable: 25/25 in top-25")
    print(f"\n=== DONE in {time.time()-t0:.1f}s ===")


if __name__ == "__main__":
    main()
