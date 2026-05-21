"""
Diagnose why mint_sell cells dropped from deployable list in clean analysis.
Print full per-fold breakdown for each mint_sell cell + FDR analysis.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from strategy_lab.ga_optimizer.path_b.events import load_path_b_events
from strategy_lab.ga_optimizer.path_b.robust_cells_clean import (
    make_disjoint_windows, analyze_clean, select_robust_actions, perm_test
)


def main():
    events = load_path_b_events()
    print(f"events: {len(events):,}")

    mintsell = events[events.sleeve_id.str.startswith("poly_mint_sell_")]
    print(f"\nmint_sell events: {len(mintsell):,}")
    print(f"  by sleeve x hour x dow:")
    print(mintsell.groupby(["sleeve_id","hour_bucket","dow_group"]).size().sort_values(ascending=False).head(20))

    windows = make_disjoint_windows(events)
    print(f"\nWindows: sel={windows['selection']}, held={windows['held_out']}")
    for f in ["fold_a","fold_b","fold_c"]:
        print(f"  {f}: {windows[f][0]:%Y-%m-%d %H:%M} → {windows[f][1]:%Y-%m-%d %H:%M}")

    # Per mint_sell cell — check fold counts
    print(f"\n=== Per mint_sell cell: fold counts ===")
    for cell_id in mintsell.cell_id.value_counts().head(20).index:
        cell_events = events[events.cell_id == cell_id]
        counts = []
        for fname in ["fold_a","fold_b","fold_c"]:
            f = windows[fname]
            n = ((cell_events.at_ts >= f[0]) & (cell_events.at_ts < f[1])).sum()
            counts.append(n)
        n_held = ((cell_events.at_ts >= windows['held_out'][0]) & (cell_events.at_ts < windows['held_out'][1])).sum()
        total = len(cell_events)
        # PnL per fold
        pnl_keep_per_fold = []
        for fname in ["fold_a","fold_b","fold_c"]:
            f = windows[fname]
            ws = cell_events[(cell_events.at_ts >= f[0]) & (cell_events.at_ts < f[1])]
            pnl_keep_per_fold.append(float(ws.pnl_same.sum()))
        print(f"  {cell_id[:80]}")
        print(f"    folds n: {counts}   held: {n_held}   total: {total}")
        print(f"    folds keep_pnl: {[f'{p:+.0f}' for p in pnl_keep_per_fold]}")

    # FDR analysis (Benjamini-Hochberg) on all 49 deployable
    print(f"\n=== Re-running with FDR correction (less strict than Bonferroni) ===")
    df, _ = analyze_clean(events, min_n_full=40, min_n_window=5, invert_safety_bp=100.0)
    df = select_robust_actions(df, min_folds_positive=2, min_n_per_fold=5)
    deployable = df[df.action != "SKIP"].copy()
    print(f"deployable: {len(deployable)}")

    events_c = events.copy()
    events_c["pnl_invert_conservative"] = events_c.pnl_invert - 25.0 * 0.01
    sel_events = events_c[(events_c.at_ts >= windows['selection'][0]) & (events_c.at_ts < windows['selection'][1])]
    held_events = events_c[(events_c.at_ts >= windows['held_out'][0]) & (events_c.at_ts < windows['held_out'][1])]

    perm_p = []
    for _, c in deployable.iterrows():
        ce = sel_events[sel_events.cell_id == c.cell_id]
        p = perm_test(ce, c.action, "pnl_invert_conservative", B=2000)
        perm_p.append(p["p_value"])
    deployable["perm_p"] = perm_p

    # Benjamini-Hochberg
    deployable = deployable.sort_values("perm_p").reset_index(drop=True)
    n = len(deployable)
    bh_q = 0.10  # FDR threshold
    deployable["bh_rank"] = range(1, n + 1)
    deployable["bh_critical"] = deployable.bh_rank / n * bh_q
    deployable["bh_passes"] = deployable.perm_p < deployable.bh_critical
    # Largest k where p[k] < (k/n) * Q passes
    passing = deployable[deployable.bh_passes]
    max_k = passing.bh_rank.max() if len(passing) else 0
    fdr_passes = deployable[deployable.bh_rank <= max_k]
    print(f"\nFDR (Benjamini-Hochberg) at q={bh_q}: {len(fdr_passes)} cells pass")

    # Held-out PnL for FDR-passing cells
    for _, c in fdr_passes.iterrows():
        ce_held = held_events[held_events.cell_id == c.cell_id]
        if c.action == "KEEP":
            held_pnl = float(ce_held.pnl_same.sum())
        else:
            held_pnl = float(ce_held.pnl_invert_conservative.sum())
        print(f"  {c.sleeve_id[:60]:<60s} {c.signal:<5s} {c.hour_bucket:<6s} {c.dow_group:<8s} {c.action:<6s}  "
              f"sel_pnl=${c.selection_pnl:+.0f}  held=${held_pnl:+.0f}  p={c.perm_p:.4f}")

    sel_days = (windows["selection"][1] - windows["selection"][0]).total_seconds() / 86400
    held_days = (windows["held_out"][1] - windows["held_out"][0]).total_seconds() / 86400
    print(f"\n=== FDR-passing aggregate ===")
    print(f"  sel:  ${fdr_passes.selection_pnl.sum():+.2f} over {sel_days:.1f}d = ${fdr_passes.selection_pnl.sum()/sel_days:+.2f}/day")
    held_total = 0.0
    for _, c in fdr_passes.iterrows():
        ce_held = held_events[held_events.cell_id == c.cell_id]
        held_total += float(ce_held.pnl_same.sum()) if c.action == "KEEP" else float(ce_held.pnl_invert_conservative.sum())
    print(f"  held: ${held_total:+.2f} over {held_days:.1f}d = ${held_total/held_days:+.2f}/day")


if __name__ == "__main__":
    main()
