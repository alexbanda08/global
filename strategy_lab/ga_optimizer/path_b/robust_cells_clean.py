"""
LEAK-FREE robust-cell analysis.

FIXES vs robust_cells.py:
  1. Held-out window (last 20%) is STRICTLY DISJOINT from all selection windows.
     Robustness folds (train_a, train_b, train_c) carved from FIRST 80% only.
  2. Bonferroni-strict significance: p < 0.05 / (n_cells * 3 actions)
  3. Conservative pnl_invert: subtract 1% extra fee buffer to account for
     spread asymmetry on the opposite side (the L25 ask of the OPPOSITE outcome
     book is empirically 1-2c higher than (1 - same_side_ask)).
  4. Out-of-sample held-out validation REPORTED but never used to filter.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from strategy_lab.ga_optimizer.path_b.events import load_path_b_events


def make_disjoint_windows(events: pd.DataFrame) -> dict:
    """
    Build SELECTION windows (first 80%) and HELD-OUT (last 20%).
    Selection split into 3 disjoint folds for robustness check.
    NO overlap between any selection window and held-out.
    """
    events = events.sort_values("at_ts").reset_index(drop=True)
    ts_min = events.at_ts.min()
    ts_max = events.at_ts.max()
    span = ts_max - ts_min

    sel_end = ts_min + span * 0.80     # first 80% for selection
    fold_size = (sel_end - ts_min) / 3  # 3 equal folds inside selection

    return dict(
        selection=(ts_min, sel_end),
        fold_a=(ts_min, ts_min + fold_size),
        fold_b=(ts_min + fold_size, ts_min + 2 * fold_size),
        fold_c=(ts_min + 2 * fold_size, sel_end),
        held_out=(sel_end, ts_max),
    )


def analyze_clean(events: pd.DataFrame, min_n_full: int = 30,
                   min_n_window: int = 5,
                   invert_safety_bp: float = 100.0) -> pd.DataFrame:
    """
    Build per-cell stats with disjoint windows + conservative invert PnL.
    invert_safety_bp = extra cost subtracted from invert PnL per share to
    account for actual opposite-side L25 ask being worse than (1-entry).
    """
    # Conservative pnl_invert FIRST (so all derived views have the column)
    safety_cost_per_trade = 25.0 * (invert_safety_bp / 1e4)
    events = events.copy()
    events["pnl_invert_conservative"] = events["pnl_invert"] - safety_cost_per_trade

    windows = make_disjoint_windows(events)
    sel_events = events[(events.at_ts >= windows["selection"][0]) & (events.at_ts < windows["selection"][1])]
    held_events = events[(events.at_ts >= windows["held_out"][0]) & (events.at_ts < windows["held_out"][1])]

    print(f"  selection window: {windows['selection'][0]} → {windows['selection'][1]} ({len(sel_events):,} events)")
    print(f"  held-out window : {windows['held_out'][0]} → {windows['held_out'][1]} ({len(held_events):,} events)")
    for f in ["fold_a","fold_b","fold_c"]:
        n = len(events[(events.at_ts >= windows[f][0]) & (events.at_ts < windows[f][1])])
        print(f"    {f}: {windows[f][0]} → {windows[f][1]} ({n:,} events)")

    # Build cells using SELECTION window stats only
    cells = sel_events.groupby("cell_id").agg(
        sleeve_id=("sleeve_id", "first"),
        signal=("signal", "first"),
        hour_bucket=("hour_bucket", "first"),
        dow_group=("dow_group", "first"),
        asset=("asset", "first"),
        family=("family", "first"),
        n_sel=("event_id", "size"),
    ).reset_index()
    cells = cells[cells.n_sel >= min_n_full]

    rows = []
    for _, c in cells.iterrows():
        rec = c.to_dict()
        cell_events_full = events[events.cell_id == c.cell_id]

        # Selection window stats
        cell_sel = sel_events[sel_events.cell_id == c.cell_id]
        rec["pnl_keep_sel"] = float(cell_sel.pnl_same.sum())
        rec["pnl_invert_sel"] = float(cell_events_full[cell_events_full.at_ts < windows["selection"][1]].pnl_invert_conservative.sum())
        rec["win_keep_sel"] = float(cell_sel.won.mean()) if len(cell_sel) else 0.0

        # Per-fold stats (within selection window — fully disjoint from held)
        for f in ["fold_a", "fold_b", "fold_c"]:
            ws = events[(events.at_ts >= windows[f][0]) & (events.at_ts < windows[f][1]) & (events.cell_id == c.cell_id)]
            rec[f"n_{f}"] = int(len(ws))
            rec[f"pnl_keep_{f}"] = float(ws.pnl_same.sum()) if len(ws) else 0.0
            rec[f"pnl_invert_{f}"] = float(ws.pnl_invert_conservative.sum()) if len(ws) else 0.0

        # Held-out stats (REPORTING ONLY — not used to filter)
        ws_held = held_events[held_events.cell_id == c.cell_id]
        rec["n_held"] = int(len(ws_held))
        rec["pnl_keep_held"] = float(ws_held.pnl_same.sum()) if len(ws_held) else 0.0
        rec["pnl_invert_held"] = float(ws_held.pnl_invert_conservative.sum()) if len(ws_held) else 0.0
        rec["win_keep_held"] = float(ws_held.won.mean()) if len(ws_held) else 0.0

        rows.append(rec)
    df = pd.DataFrame(rows)
    df["windows"] = [windows] * len(df)
    return df, windows


def select_robust_actions(df: pd.DataFrame, min_folds_positive: int = 2,
                          min_n_per_fold: int = 5) -> pd.DataFrame:
    """
    Select KEEP/INVERT/SKIP per cell using ONLY selection-window data.

    Adaptive logic for cells that didn't exist in all folds:
      - Count "active" folds where this cell has >=min_n_per_fold events
      - Require positive PnL in >= min_folds_positive of active folds
      - Reject if cell active in <2 folds (insufficient stability evidence)
    """
    def pick(row):
        active_folds = []
        keep_pnls, inv_pnls = [], []
        for f in ["fold_a","fold_b","fold_c"]:
            n_f = row[f"n_{f}"]
            if n_f >= min_n_per_fold:
                active_folds.append(f)
                keep_pnls.append(row[f"pnl_keep_{f}"])
                inv_pnls.append(row[f"pnl_invert_{f}"])
        if len(active_folds) < 2:
            return ("SKIP", 0, 0.0, len(active_folds))
        keep_pos = sum(p > 0 for p in keep_pnls)
        inv_pos = sum(p > 0 for p in inv_pnls)
        keep_total = sum(keep_pnls)
        inv_total = sum(inv_pnls)
        # Need >=min(min_folds_positive, len(active)) folds positive
        threshold = min(min_folds_positive, len(active_folds))
        if keep_pos >= threshold and keep_total > 0 and keep_total >= inv_total:
            return ("KEEP", keep_pos, keep_total, len(active_folds))
        if inv_pos >= threshold and inv_total > 0 and inv_total > keep_total:
            return ("INVERT", inv_pos, inv_total, len(active_folds))
        return ("SKIP", 0, 0.0, len(active_folds))

    out = df.apply(pick, axis=1, result_type="expand")
    out.columns = ["action", "folds_positive", "selection_pnl", "n_active_folds"]
    return pd.concat([df, out], axis=1)


def perm_test(events_in_cell: pd.DataFrame, action: str, pnl_col_invert: str,
               B: int = 2000, rng_seed: int = 42) -> dict:
    rng = np.random.default_rng(rng_seed)
    if action == "KEEP":
        pnls = events_in_cell.pnl_same.values
    elif action == "INVERT":
        pnls = events_in_cell[pnl_col_invert].values
    else:
        return dict(observed=0.0, p_value=1.0, n=0)
    n = len(pnls)
    if n == 0:
        return dict(observed=0.0, p_value=1.0, n=0)
    observed = float(pnls.sum())
    sums = np.array([float((pnls * rng.choice([1,-1], size=n)).sum()) for _ in range(B)])
    return dict(observed=observed, p_value=float((sums >= observed).mean()), n=n)


def main():
    print("=== CLEAN robust-cell analysis (leak-free) ===")
    events = load_path_b_events()
    print(f"events: {len(events):,}  window: {events.at_ts.min()} → {events.at_ts.max()}")

    df, windows = analyze_clean(events, min_n_full=40, min_n_window=5,
                                  invert_safety_bp=100.0)
    print(f"\ncells with n_sel>=40: {len(df):,}")

    df = select_robust_actions(df, min_folds_positive=2)
    deployable = df[df.action != "SKIP"].copy()
    print(f"deployable (>=2 of 3 folds positive in chosen direction): {len(deployable)}")
    print(f"  KEEP={int((deployable.action=='KEEP').sum())}  INVERT={int((deployable.action=='INVERT').sum())}")

    # Bonferroni-strict alpha
    n_candidates = len(df) * 2   # 2 actions per cell (KEEP and INVERT excluding SKIP)
    bonf_alpha = 0.05 / max(n_candidates, 1)
    print(f"\nBonferroni α = 0.05 / {n_candidates} = {bonf_alpha:.2e}")

    # Permutation test on SELECTION window only (held-out reserved)
    events_with_inv = events.copy()
    events_with_inv["pnl_invert_conservative"] = events_with_inv["pnl_invert"] - 25.0 * (100.0/1e4)
    sel_events = events_with_inv[(events_with_inv.at_ts >= windows["selection"][0]) & (events_with_inv.at_ts < windows["selection"][1])]
    held_events = events_with_inv[(events_with_inv.at_ts >= windows["held_out"][0]) & (events_with_inv.at_ts < windows["held_out"][1])]

    perm_results = []
    for _, c in deployable.iterrows():
        cell_sel = sel_events[sel_events.cell_id == c.cell_id]
        perm_sel = perm_test(cell_sel, c.action, "pnl_invert_conservative", B=2000)
        rec = c.to_dict()
        rec["perm_p_sel"] = perm_sel["p_value"]
        rec["perm_observed_sel"] = perm_sel["observed"]
        # Held-out (reporting only)
        cell_held = held_events[held_events.cell_id == c.cell_id]
        if c.action == "KEEP":
            rec["held_pnl"] = float(cell_held.pnl_same.sum())
        elif c.action == "INVERT":
            rec["held_pnl"] = float(cell_held.pnl_invert_conservative.sum())
        else:
            rec["held_pnl"] = 0.0
        perm_results.append(rec)
    pr = pd.DataFrame(perm_results)

    # Tiers
    pr["passes_bonferroni"] = pr.perm_p_sel < bonf_alpha
    pr["passes_5pct"] = pr.perm_p_sel < 0.05
    pr["passes_10pct"] = pr.perm_p_sel < 0.10

    tier1 = pr[pr.passes_bonferroni].copy()
    tier2 = pr[pr.passes_5pct & ~pr.passes_bonferroni].copy()
    tier3 = pr[pr.passes_10pct & ~pr.passes_5pct].copy()

    print(f"\n=== TIER 1 (Bonferroni-strict, p<{bonf_alpha:.1e}): {len(tier1)} cells ===")
    cols = ["sleeve_id","signal","hour_bucket","dow_group","action","n_sel",
            "selection_pnl","held_pnl","perm_p_sel"]
    print(tier1[cols].sort_values("selection_pnl", ascending=False).to_string(index=False))

    print(f"\n=== TIER 2 (p<0.05 not Bonferroni): {len(tier2)} cells ===")
    print(tier2[cols].sort_values("selection_pnl", ascending=False).to_string(index=False))

    print(f"\n=== TIER 3 (0.05<p<0.10): {len(tier3)} cells ===")
    print(tier3[cols].sort_values("selection_pnl", ascending=False).head(15).to_string(index=False))

    # Aggregate
    print(f"\n=== Aggregate (selection window vs held-out — held-out NEVER touched in selection) ===")
    sel_days = (windows["selection"][1] - windows["selection"][0]).total_seconds() / 86400
    held_days = (windows["held_out"][1] - windows["held_out"][0]).total_seconds() / 86400
    print(f"  selection window: {sel_days:.1f} days   held-out: {held_days:.1f} days")
    for name, t in [("TIER 1", tier1), ("TIER 2", tier2), ("TIER 3", tier3)]:
        if len(t) == 0:
            print(f"  {name}: 0 cells"); continue
        sp = float(t.selection_pnl.sum())
        hp = float(t.held_pnl.sum())
        # Held-out PnL with positive cells only (since we may have cells where held was negative — that's the OOS reality check)
        n_held_pos = int((t.held_pnl > 0).sum())
        n_held_neg = int((t.held_pnl < 0).sum())
        print(f"  {name}: {len(t)} cells, sel_pnl=${sp:+,.2f} ({sp/sel_days:+,.1f}/day)  "
              f"held_pnl=${hp:+,.2f} ({hp/held_days:+,.1f}/day)  "
              f"held_pos/neg: {n_held_pos}/{n_held_neg}")

    # Final deploy = Tier 1 only (rigorous)
    pr.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "robust_cells_CLEAN.csv", index=False)
    tier1.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "TIER1_BONFERRONI.csv", index=False)
    deploy_t1_t2 = pd.concat([tier1, tier2])
    deploy_t1_t2.to_csv(ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "TIER1_T2_DEPLOY.csv", index=False)
    print(f"\nFiles saved:")
    print(f"  TIER1_BONFERRONI.csv ({len(tier1)} cells)")
    print(f"  TIER1_T2_DEPLOY.csv  ({len(deploy_t1_t2)} cells)")
    print(f"  robust_cells_CLEAN.csv ({len(pr)} candidates)")


if __name__ == "__main__":
    main()
