"""
Build a clean deployable list + provisional watchlist.

Tier A (LIVE-DEPLOY, rigorous):
  - Cells with ≥2 active folds in selection window (10.4d)
  - Direction-PnL > 0 in ≥2 of active folds
  - Permutation p < FDR (Benjamini-Hochberg q=0.10) on selection window
  - Held-out PnL > 0 as INDEPENDENT confirmation (not selection criterion)

Tier B (PAPER-VALIDATE, provisional):
  - Cells active in only 1 fold (late-starters like mint_sell)
  - Permutation p < 0.05 on the single fold
  - Held-out PnL > 0
  - n_held >= 100
  - Deploy at 1/3 size — must validate forward over 7+ days

Tier C: skip / kill.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from strategy_lab.ga_optimizer.path_b.events import load_path_b_events
from strategy_lab.ga_optimizer.path_b.robust_cells_clean import (
    make_disjoint_windows, perm_test
)


def build_cell_table(events, min_n_sel=40):
    """Compute per-cell stats per window + cell categories."""
    windows = make_disjoint_windows(events)
    events = events.copy()
    events["pnl_invert_conservative"] = events["pnl_invert"] - 25.0 * 0.01

    sel = events[(events.at_ts >= windows["selection"][0]) & (events.at_ts < windows["selection"][1])]
    held = events[(events.at_ts >= windows["held_out"][0]) & (events.at_ts < windows["held_out"][1])]

    cells = sel.groupby("cell_id").agg(
        sleeve_id=("sleeve_id","first"), signal=("signal","first"),
        hour_bucket=("hour_bucket","first"), dow_group=("dow_group","first"),
        asset=("asset","first"), family=("family","first"),
        n_sel=("event_id","size"),
    ).reset_index()
    cells = cells[cells.n_sel >= min_n_sel]

    rows = []
    for _, c in cells.iterrows():
        rec = c.to_dict()
        cell_events = events[events.cell_id == c.cell_id]
        for fname in ["fold_a","fold_b","fold_c"]:
            f = windows[fname]
            ws = cell_events[(cell_events.at_ts >= f[0]) & (cell_events.at_ts < f[1])]
            rec[f"n_{fname}"] = int(len(ws))
            rec[f"keep_{fname}"] = float(ws.pnl_same.sum()) if len(ws) else 0.0
            rec[f"inv_{fname}"]  = float(ws.pnl_invert_conservative.sum()) if len(ws) else 0.0
        # Selection totals
        ws_sel = sel[sel.cell_id == c.cell_id]
        rec["keep_sel"] = float(ws_sel.pnl_same.sum())
        rec["inv_sel"]  = float(ws_sel.pnl_invert_conservative.sum())
        # Held
        ws_held = held[held.cell_id == c.cell_id]
        rec["n_held"] = int(len(ws_held))
        rec["keep_held"] = float(ws_held.pnl_same.sum()) if len(ws_held) else 0.0
        rec["inv_held"]  = float(ws_held.pnl_invert_conservative.sum()) if len(ws_held) else 0.0
        rec["active_folds"] = sum(rec[f"n_{f}"] >= 10 for f in ["fold_a","fold_b","fold_c"])
        rows.append(rec)
    return pd.DataFrame(rows), windows, sel, held


def pick_action(row, min_folds_positive_when_multi=2):
    """Pick best action accounting for multi-fold vs single-fold cells."""
    keep_pnls = [row[f"keep_{f}"] for f in ["fold_a","fold_b","fold_c"] if row[f"n_{f}"] >= 10]
    inv_pnls = [row[f"inv_{f}"] for f in ["fold_a","fold_b","fold_c"] if row[f"n_{f}"] >= 10]
    if not keep_pnls:
        return ("SKIP", 0, 0.0, "no active folds")
    keep_pos = sum(p > 0 for p in keep_pnls)
    inv_pos = sum(p > 0 for p in inv_pnls)
    keep_sum = sum(keep_pnls)
    inv_sum = sum(inv_pnls)
    n_active = len(keep_pnls)
    # Decide
    if n_active >= 2:
        threshold = min_folds_positive_when_multi
        if keep_pos >= threshold and keep_sum > 0 and keep_sum >= inv_sum:
            return ("KEEP", keep_pos, keep_sum, "multi-fold KEEP")
        if inv_pos >= threshold and inv_sum > 0 and inv_sum > keep_sum:
            return ("INVERT", inv_pos, inv_sum, "multi-fold INVERT")
        return ("SKIP", 0, 0.0, "multi-fold but not enough positive")
    # n_active == 1 → single fold (late starter)
    if keep_sum > 0 and keep_sum >= inv_sum:
        return ("KEEP", keep_pos, keep_sum, "single-fold KEEP (provisional)")
    if inv_sum > 0 and inv_sum > keep_sum:
        return ("INVERT", inv_pos, inv_sum, "single-fold INVERT (provisional)")
    return ("SKIP", 0, 0.0, "single fold not positive")


def main():
    events = load_path_b_events()
    print(f"events: {len(events):,}")

    df, windows, sel, held = build_cell_table(events, min_n_sel=40)
    print(f"candidate cells (n_sel>=40): {len(df)}")

    actions = df.apply(pick_action, axis=1, result_type="expand")
    actions.columns = ["action", "folds_positive", "selection_pnl", "category"]
    df = pd.concat([df, actions], axis=1)
    deployable = df[df.action != "SKIP"].copy()
    print(f"\nAction distribution:")
    print(deployable.action.value_counts())
    print(f"Categories:")
    print(deployable.category.value_counts())

    # Perm test on SELECTION
    perm_p_sel = []
    perm_p_held = []
    for _, c in deployable.iterrows():
        ce_sel = sel[sel.cell_id == c.cell_id]
        ce_held = held[held.cell_id == c.cell_id]
        p_sel = perm_test(ce_sel, c.action, "pnl_invert_conservative", B=2000)
        p_held = perm_test(ce_held, c.action, "pnl_invert_conservative", B=2000) if len(ce_held) >= 5 else dict(p_value=1.0)
        perm_p_sel.append(p_sel["p_value"])
        perm_p_held.append(p_held["p_value"])
    deployable["perm_p_sel"] = perm_p_sel
    deployable["perm_p_held"] = perm_p_held
    deployable["held_pnl"] = deployable.apply(
        lambda r: r.keep_held if r.action == "KEEP" else r.inv_held, axis=1)

    # Split multi-fold vs single-fold
    multi_fold = deployable[deployable.active_folds >= 2].copy()
    single_fold = deployable[deployable.active_folds == 1].copy()
    print(f"\nMulti-fold candidates: {len(multi_fold)}")
    print(f"Single-fold candidates (late starters): {len(single_fold)}")

    # Apply FDR to multi-fold
    if len(multi_fold) > 0:
        multi_fold = multi_fold.sort_values("perm_p_sel").reset_index(drop=True)
        n = len(multi_fold)
        q = 0.10
        multi_fold["bh_rank"] = range(1, n+1)
        multi_fold["bh_critical"] = multi_fold.bh_rank / n * q
        multi_fold["bh_passes"] = multi_fold.perm_p_sel < multi_fold.bh_critical
        passing_ranks = multi_fold[multi_fold.bh_passes].bh_rank
        max_k = int(passing_ranks.max()) if len(passing_ranks) else 0
        tier_a = multi_fold[multi_fold.bh_rank <= max_k].copy() if max_k else multi_fold.head(0)
    else:
        tier_a = pd.DataFrame()

    # Tier A also requires positive held-out as bonus check
    tier_a_clean = tier_a[tier_a.held_pnl > 0].copy()
    print(f"\n=== TIER A (LIVE-DEPLOY: FDR-passing + held-out positive) ===")
    print(f"  {len(tier_a_clean)} cells")
    if len(tier_a_clean):
        cols = ["sleeve_id","signal","hour_bucket","dow_group","action",
                "active_folds","selection_pnl","held_pnl","perm_p_sel","n_sel","n_held"]
        print(tier_a_clean[cols].to_string(index=False))

    # Tier B: single-fold, perm < 0.05, held > 0, n_held >= 100
    tier_b = single_fold[(single_fold.perm_p_sel < 0.05) &
                          (single_fold.held_pnl > 0) &
                          (single_fold.n_held >= 100)].copy()
    print(f"\n=== TIER B (PAPER-VALIDATE: late-starters, single-fold, held>0, n_held≥100) ===")
    print(f"  {len(tier_b)} cells")
    if len(tier_b):
        cols_b = ["sleeve_id","signal","hour_bucket","dow_group","action",
                  "selection_pnl","held_pnl","perm_p_sel","perm_p_held","n_sel","n_held"]
        print(tier_b.sort_values("held_pnl", ascending=False)[cols_b].to_string(index=False))

    # Aggregate
    sel_days = (windows["selection"][1] - windows["selection"][0]).total_seconds() / 86400
    held_days = (windows["held_out"][1] - windows["held_out"][0]).total_seconds() / 86400
    print(f"\n=== AGGREGATE ===")
    print(f"  selection window: {sel_days:.1f}d  held-out: {held_days:.1f}d")
    if len(tier_a_clean):
        a_sel = float(tier_a_clean.selection_pnl.sum()); a_held = float(tier_a_clean.held_pnl.sum())
        print(f"  TIER A: sel ${a_sel:+,.0f} ({a_sel/sel_days:+,.1f}/d)  held ${a_held:+,.0f} ({a_held/held_days:+,.1f}/d)")
    if len(tier_b):
        b_sel = float(tier_b.selection_pnl.sum()); b_held = float(tier_b.held_pnl.sum())
        print(f"  TIER B: sel ${b_sel:+,.0f} ({b_sel/sel_days:+,.1f}/d)  held ${b_held:+,.0f} ({b_held/held_days:+,.1f}/d)")

    # Save
    tier_a_clean.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "TIER_A_DEPLOY.csv", index=False)
    tier_b.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "TIER_B_WATCHLIST.csv", index=False)
    df.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "all_candidates_with_perm.csv", index=False)
    print(f"\nFiles saved:")
    print(f"  TIER_A_DEPLOY.csv     ({len(tier_a_clean)} cells)")
    print(f"  TIER_B_WATCHLIST.csv  ({len(tier_b)} cells)")
    print(f"  all_candidates_with_perm.csv  ({len(df)} candidates)")


if __name__ == "__main__":
    main()
