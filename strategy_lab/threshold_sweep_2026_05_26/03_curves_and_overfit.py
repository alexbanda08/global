"""Threshold sweep — TASK 4, 5, 6, 7.

TASK 4 — Threshold curves analysis:
  - For each (sleeve, gate), classify curve as monotonic-up, monotonic-down, U-shaped, or flat
  - Use lockbox $/tr and sum vs threshold

TASK 5 — Optimized stacks per sleeve:
  Build the per-sleeve OPTIMIZED stack — pick the best 1-3 gate overlays with optimal thresholds.
  Compare to base hybrid_v1.

TASK 6 — Strict 3-way validation (train/val/lockbox + 500-shuffle bootstrap) on optimized stacks.

TASK 7 — Overfit check:
  For each (sleeve, gate), find the validation-optimal threshold and the lockbox-optimal threshold.
  If they differ, evaluate val-optimal threshold on lockbox (true OOS).
  Compare val-optimal-on-lockbox vs lockbox-optimal-on-lockbox.

Output:
  threshold_curves_classification.csv
  threshold_optimized_stacks.csv
  threshold_3way_validation.csv
  threshold_overfit_check.csv
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

# Import sweep config from the main sweep script
sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module
_sweep_mod = import_module("02_threshold_sweep")
SWEEPS = _sweep_mod.SWEEPS
SLEEVES = _sweep_mod.SLEEVES
make_gate_mask = _sweep_mod.make_gate_mask
apply_stack = _sweep_mod.apply_stack
split_train_val_lock = _sweep_mod.split_train_val_lock
bootstrap_p = _sweep_mod.bootstrap_p
cell_stats = _sweep_mod.cell_stats
TR_FRAC = _sweep_mod.TR_FRAC
VL_FRAC = _sweep_mod.VL_FRAC

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def classify_curve(sweep_df: pd.DataFrame, metric: str = "sum_lockbox") -> str:
    """Classify a per-(sleeve, gate) sweep across thresholds:
      - 'monotonic_up'    : metric increases with threshold (loose -> tight, $/tr improves)
      - 'monotonic_down'  : metric decreases with threshold
      - 'u_shaped'        : sweet-spot in the middle (max not at either end)
      - 'inv_u_shaped'    : minimum in middle (worst)
      - 'flat'            : range/mean < 5% (essentially insensitive)
    """
    if len(sweep_df) < 3:
        return "insufficient"
    sweep_df = sweep_df.sort_values("threshold").reset_index(drop=True)
    vals = sweep_df[metric].values
    # Flat? range / max-abs <5%
    abs_max = max(abs(vals).max(), 1.0)
    if (vals.max() - vals.min()) / abs_max < 0.05:
        return "flat"

    # Monotonic
    diffs = np.diff(vals)
    if (diffs >= 0).all():
        return "monotonic_up"
    if (diffs <= 0).all():
        return "monotonic_down"
    # U-shaped: max not at either endpoint
    argmax = int(np.argmax(vals))
    argmin = int(np.argmin(vals))
    n = len(vals)
    if argmax > 0 and argmax < n - 1:
        return "u_shaped"  # peak in middle
    if argmin > 0 and argmin < n - 1:
        return "inv_u_shaped"  # valley in middle
    return "mixed"


def task4_classify_curves():
    """Classify the curve type for each (sleeve, gate)."""
    log("# TASK 4 — Threshold curve classification")
    df = pd.read_csv(RES / "threshold_sweep.csv")
    df = df[df.gate != "(baseline_r1_only)"].copy()

    rows = []
    for (sleeve, gate), grp in df.groupby(["sleeve", "gate"]):
        # Only classify if multiple thresholds tested
        if len(grp) < 2:
            continue
        thr_n = grp.threshold.nunique()
        if thr_n < 2:
            shape_sum = "single_threshold"
            shape_dpt = "single_threshold"
        else:
            shape_sum = classify_curve(grp, "sum_lockbox")
            shape_dpt = classify_curve(grp, "dpt_lockbox")
        rows.append({
            "sleeve": sleeve, "gate": gate, "n_thresholds": thr_n,
            "curve_sum_lockbox": shape_sum, "curve_dpt_lockbox": shape_dpt,
            "min_sum_lk": float(grp.sum_lockbox.min()), "max_sum_lk": float(grp.sum_lockbox.max()),
            "min_dpt_lk": float(grp.dpt_lockbox.min()), "max_dpt_lk": float(grp.dpt_lockbox.max()),
        })
    out = pd.DataFrame(rows)
    out.to_csv(RES / "threshold_curves_classification.csv", index=False)
    log(f"wrote threshold_curves_classification.csv ({len(out)} rows)")

    # Summary
    log("Curve shapes (sum_lockbox):")
    print(out.curve_sum_lockbox.value_counts())


def task7_overfit_check():
    """For each (sleeve, gate), find val-optimal threshold and lockbox-optimal threshold.
    Apply val-optimal to lockbox to get the true OOS metric."""
    log("# TASK 7 — Overfit check (validation-optimal vs lockbox-optimal threshold)")
    df = pd.read_csv(RES / "threshold_sweep.csv")
    df = df[df.gate != "(baseline_r1_only)"].copy()

    rows = []
    for (sleeve, gate), grp in df.groupby(["sleeve", "gate"]):
        if len(grp) < 2 or grp.threshold.nunique() < 2:
            continue
        # val-optimal threshold (by sum_val)
        val_best = grp.loc[grp.sum_val.idxmax()]
        # lockbox-optimal
        lk_best = grp.loc[grp.sum_lockbox.idxmax()]

        rows.append({
            "sleeve": sleeve, "gate": gate, "n_thresholds": grp.threshold.nunique(),
            "val_opt_thr": val_best.threshold, "lk_opt_thr": lk_best.threshold,
            "thresholds_match": (val_best.threshold == lk_best.threshold),
            "val_opt_sum_val": val_best.sum_val,
            # val-optimal applied to lockbox = TRUE OOS
            "val_opt_sum_lk": val_best.sum_lockbox,  # this IS the val-opt's lockbox metric (held out at training time)
            "val_opt_dpt_lk": val_best.dpt_lockbox,
            "val_opt_WR_lk": val_best.WR_lockbox,
            "val_opt_n_lk": val_best.n_lockbox,
            # lockbox-optimal (what we'd cheat-pick)
            "lk_opt_sum_lk": lk_best.sum_lockbox,
            "lk_opt_dpt_lk": lk_best.dpt_lockbox,
            "lk_opt_WR_lk": lk_best.WR_lockbox,
            # gap = overfit penalty
            "sum_gap_lk": lk_best.sum_lockbox - val_best.sum_lockbox,
            "dpt_gap_lk": lk_best.dpt_lockbox - val_best.dpt_lockbox,
        })
    out = pd.DataFrame(rows)
    out.to_csv(RES / "threshold_overfit_check.csv", index=False)
    log(f"wrote threshold_overfit_check.csv ({len(out)} rows)")

    n_matched = int(out["thresholds_match"].sum())
    log(f"  val-opt thr == lk-opt thr: {n_matched}/{len(out)} ({n_matched/len(out)*100:.0f}%)")
    log(f"  mean sum_gap_lk (lk-opt − val-opt) = ${out.sum_gap_lk.mean():.0f}")
    log(f"  mean dpt_gap_lk = ${out.dpt_gap_lk.mean():.3f}")


def task5_and_6_build_optimized_stacks():
    """For each sleeve, build OPTIMIZED hybrid_v1 with top 3 overlays at optimal thresholds.
    Compare full / train / val / lockbox metrics.
    """
    log("# TASK 5+6 — Build optimized stacks and strict 3-way validation")

    # Pick top 3 gates per sleeve by val_sum_lk
    sweep = pd.read_csv(RES / "threshold_sweep.csv")
    sweep_g = sweep[sweep.gate != "(baseline_r1_only)"].copy()
    baseline = sweep[sweep.gate == "(baseline_r1_only)"].set_index("sleeve")

    rows = []
    for (sleeve_name, panel_file, asset, tf_filter, offsets, r1_gates) in SLEEVES:
        # Per (sleeve, gate), pick val-optimal threshold
        sleeve_sw = sweep_g[sweep_g.sleeve == sleeve_name].copy()
        if len(sleeve_sw) == 0:
            continue
        # Pick best val_opt threshold per gate
        val_opts = []
        for gate, grp in sleeve_sw.groupby("gate"):
            best = grp.loc[grp.sum_val.idxmax()]
            val_opts.append(best.to_dict())
        val_opts_df = pd.DataFrame(val_opts).sort_values("sum_val", ascending=False)
        # Filter: minimum lockbox n >= 20, val sum > 0
        val_opts_df = val_opts_df[(val_opts_df.n_val >= 10) & (val_opts_df.sum_val > 0)]
        if len(val_opts_df) == 0:
            log(f"  {sleeve_name}: no positive val-optimal gates")
            continue
        top3 = val_opts_df.head(3)

        # Build optimized stack
        df = pd.read_parquet(RES / panel_file)
        mask = (df.asset == asset) & (df.fire_offset_s.isin(offsets))
        if "tf" in df.columns:
            mask &= (df.tf == tf_filter)
        universe = df[mask].copy()
        if len(universe) == 0:
            continue

        for k_overlays in [1, 2, 3]:
            sel = top3.head(k_overlays)
            chosen_gates = []
            chosen_thrs = []
            chosen_descs = []

            cur_mask = apply_stack(universe, r1_gates)
            stack_str = " & ".join(r1_gates)
            for _, r in sel.iterrows():
                gate_name = r["gate"]
                thr = r["threshold"]
                gate_mask = make_gate_mask(universe, gate_name, thr)
                cur_mask = cur_mask & gate_mask
                chosen_gates.append(gate_name)
                chosen_thrs.append(thr)
                chosen_descs.append(f"{gate_name}@{thr}")
                stack_str += f" & {gate_name}@{thr}"

            sub = universe[cur_mask].copy()
            if len(sub) == 0:
                continue
            tr, vl, lk = split_train_val_lock(sub)
            full_pnl = sub.pnl_legacy_usd.values
            lk_dpt = float(lk.pnl_legacy_usd.mean()) if len(lk) else 0.0
            p = bootstrap_p(full_pnl, lk_dpt, len(lk))
            rows.append({
                "sleeve": sleeve_name, "k_overlays": k_overlays,
                "gate_stack": stack_str, "overlay_gates": " | ".join(chosen_descs),
                "n_full": len(sub),
                "dpt_full": float(sub.pnl_legacy_usd.mean()),
                "sum_full": float(sub.pnl_legacy_usd.sum()),
                "WR_full": float(sub.won.mean()),
                "n_train": len(tr),
                "dpt_train": float(tr.pnl_legacy_usd.mean()) if len(tr) else 0.0,
                "sum_train": float(tr.pnl_legacy_usd.sum()) if len(tr) else 0.0,
                "WR_train": float(tr.won.mean()) if len(tr) else 0.0,
                "n_val": len(vl),
                "dpt_val": float(vl.pnl_legacy_usd.mean()) if len(vl) else 0.0,
                "sum_val": float(vl.pnl_legacy_usd.sum()) if len(vl) else 0.0,
                "WR_val": float(vl.won.mean()) if len(vl) else 0.0,
                "n_lockbox": len(lk),
                "dpt_lockbox": lk_dpt,
                "sum_lockbox": float(lk.pnl_legacy_usd.sum()) if len(lk) else 0.0,
                "WR_lockbox": float(lk.won.mean()) if len(lk) else 0.0,
                "boot_p_lockbox": p,
                "deployable": bool(len(lk) >= 20 and lk.pnl_legacy_usd.sum() > 0
                                   and (lk.won.mean() >= 0.55 if len(lk) else False)
                                   and p <= 0.10),
            })

        # Add the baseline row for comparison
        if sleeve_name in baseline.index:
            b = baseline.loc[sleeve_name]
            rows.append({
                "sleeve": sleeve_name, "k_overlays": 0,
                "gate_stack": " & ".join(r1_gates), "overlay_gates": "(baseline_r1_only)",
                "n_full": int(b.n_full), "dpt_full": float(b.dpt_full),
                "sum_full": float(b.sum_full), "WR_full": float(b.WR_full),
                "n_train": int(b.n_train), "dpt_train": float(b.dpt_train),
                "sum_train": float(b.sum_train), "WR_train": float(b.WR_train),
                "n_val": int(b.n_val), "dpt_val": float(b.dpt_val),
                "sum_val": float(b.sum_val), "WR_val": float(b.WR_val),
                "n_lockbox": int(b.n_lockbox), "dpt_lockbox": float(b.dpt_lockbox),
                "sum_lockbox": float(b.sum_lockbox), "WR_lockbox": float(b.WR_lockbox),
                "boot_p_lockbox": float(b.boot_p_lockbox),
                "deployable": bool(b.n_lockbox >= 20 and b.sum_lockbox > 0
                                   and b.WR_lockbox >= 0.55 and b.boot_p_lockbox <= 0.10),
            })

    out = pd.DataFrame(rows).sort_values(["sleeve", "k_overlays"]).reset_index(drop=True)
    out.to_csv(RES / "threshold_optimized_stacks.csv", index=False)
    log(f"wrote threshold_optimized_stacks.csv ({len(out)} rows)")
    log("\nTop 10 optimized stacks by sum_lockbox:")
    print(out.nlargest(10, "sum_lockbox")[
        ["sleeve", "k_overlays", "overlay_gates", "n_lockbox", "WR_lockbox", "dpt_lockbox",
         "sum_lockbox", "boot_p_lockbox", "deployable"]
    ].to_string(index=False))


def main():
    task4_classify_curves()
    task7_overfit_check()
    task5_and_6_build_optimized_stacks()
    log("DONE")


if __name__ == "__main__":
    main()
