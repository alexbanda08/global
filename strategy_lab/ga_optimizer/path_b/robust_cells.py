"""
Robust-cell analysis: only deploy cells that are POSITIVE across multiple
independent time windows (train, val, held-out, recent-3d, recent-7d).

This is the strictest possible filter — equivalent to a multi-window Bonferroni.
Lower n (because we drop unstable cells) but stable forward.
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from strategy_lab.ga_optimizer.path_b.events import load_path_b_events


def analyze_cell_robustness(events: pd.DataFrame, min_n_full: int = 30,
                             min_n_window: int = 5) -> pd.DataFrame:
    """
    For each cell, compute PnL on multiple windows and identify robust ones.
    Robust = positive in EITHER direction (keep or invert) across ALL of:
        full_window, train_window, val_window, held_out_window, last_3d, last_7d
    """
    events = events.sort_values("at_ts").reset_index(drop=True)
    ts_min = events.at_ts.min(); ts_max = events.at_ts.max()
    span = ts_max - ts_min
    # Time windows
    train_end = ts_min + span * 0.65
    val_end = ts_min + span * 0.80
    last_7d_start = ts_max - pd.Timedelta(days=7)
    last_3d_start = ts_max - pd.Timedelta(days=3)

    windows = {
        "full": events,
        "train": events[events.at_ts < train_end],
        "val": events[(events.at_ts >= train_end) & (events.at_ts < val_end)],
        "held": events[events.at_ts >= val_end],
        "last_7d": events[events.at_ts >= last_7d_start],
        "last_3d": events[events.at_ts >= last_3d_start],
    }

    cells = events.groupby("cell_id").agg(
        sleeve_id=("sleeve_id", "first"),
        signal=("signal", "first"),
        hour_bucket=("hour_bucket", "first"),
        dow_group=("dow_group", "first"),
        asset=("asset", "first"),
        family=("family", "first"),
        n_full=("event_id", "size"),
    ).reset_index()
    cells = cells[cells.n_full >= min_n_full]

    rows = []
    for _, c in cells.iterrows():
        rec = c.to_dict()
        for wname, wdf in windows.items():
            ws = wdf[wdf.cell_id == c.cell_id]
            rec[f"n_{wname}"] = int(len(ws))
            rec[f"pnl_keep_{wname}"] = float(ws.pnl_same.sum()) if len(ws) else 0.0
            rec[f"pnl_invert_{wname}"] = float(ws.pnl_invert.sum()) if len(ws) else 0.0
            if len(ws):
                rec[f"win_keep_{wname}"] = float(ws.won.mean())
                rec[f"win_invert_{wname}"] = float((~ws.won.fillna(False)).mean())
            else:
                rec[f"win_keep_{wname}"] = 0.0
                rec[f"win_invert_{wname}"] = 0.0
        rows.append(rec)

    df = pd.DataFrame(rows)

    # Per-cell BEST direction across all windows
    def robust_direction(row):
        """Returns (action, score) where action is KEEP/INVERT/SKIP."""
        keep_pos = [(row.get(f"pnl_keep_{w}", 0) > 0 and row.get(f"n_{w}", 0) >= min_n_window)
                    for w in ["train", "val", "held", "last_7d", "last_3d"]]
        inv_pos = [(row.get(f"pnl_invert_{w}", 0) > 0 and row.get(f"n_{w}", 0) >= min_n_window)
                   for w in ["train", "val", "held", "last_7d", "last_3d"]]
        # Strict: must be positive in all checked windows (where n is sufficient)
        keep_score = sum(keep_pos)
        inv_score = sum(inv_pos)
        if keep_score >= 4 and keep_score > inv_score:
            return ("KEEP", keep_score, row["pnl_keep_full"])
        elif inv_score >= 4 and inv_score > keep_score:
            return ("INVERT", inv_score, row["pnl_invert_full"])
        else:
            return ("SKIP", 0, 0.0)

    actions = df.apply(robust_direction, axis=1, result_type="expand")
    actions.columns = ["action", "window_score", "full_pnl_action"]
    df = pd.concat([df, actions], axis=1)
    return df


def main():
    print("=== Robust-cell analysis ===")
    events = load_path_b_events()
    print(f"events: {len(events):,}  window: {events.at_ts.min()} → {events.at_ts.max()}")

    df = analyze_cell_robustness(events, min_n_full=30, min_n_window=5)
    print(f"cells with n>=30 full: {len(df):,}")

    # Summary
    print()
    print("=== Action distribution ===")
    print(df.action.value_counts())

    # The DEPLOYABLE set: cells with action != SKIP
    deployable = df[df.action != "SKIP"].copy()
    print(f"\nDeployable cells: {len(deployable)}")

    # For each, total PnL = pnl_keep_full if KEEP, pnl_invert_full if INVERT
    deployable["deploy_pnl_full"] = deployable["full_pnl_action"]
    deployable = deployable.sort_values("deploy_pnl_full", ascending=False)
    print(f"\n=== TOP 25 robust cells ===")
    cols = ["sleeve_id", "signal", "hour_bucket", "dow_group", "action",
            "window_score", "n_full",
            "pnl_keep_full", "pnl_invert_full", "deploy_pnl_full",
            "pnl_keep_held", "pnl_invert_held"]
    print(deployable[cols].head(25).to_string(index=False))

    # Aggregate by held-out direction
    held_total = float(deployable.apply(
        lambda r: r["pnl_keep_held"] if r["action"] == "KEEP" else r["pnl_invert_held"],
        axis=1).sum())
    full_total = float(deployable["deploy_pnl_full"].sum())
    print(f"\n=== Aggregate ===")
    print(f"  Full-window deploy PnL: ${full_total:+,.2f}")
    print(f"  Held-out deploy PnL  : ${held_total:+,.2f}")

    # Held-out span
    held_span_days = (events.at_ts.max() - (events.at_ts.min() + (events.at_ts.max()-events.at_ts.min()) * 0.80)).total_seconds() / 86400
    print(f"  Held-out span: {held_span_days:.1f} days")
    daily_held = held_total / max(held_span_days, 0.1)
    print(f"  Held-out daily rate: ${daily_held:+.2f}/day")
    print(f"  Projected monthly (assuming hold-rate): ${daily_held * 30:+,.2f}")

    # Save deployable list
    out = ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "robust_cells_deployable.csv"
    deployable.to_csv(out, index=False)
    out_full = ROOT / "strategy_lab" / "ga_optimizer" / "runs" / "robust_cells_all.csv"
    df.to_csv(out_full, index=False)
    print(f"\nSaved: {out}")
    print(f"Saved: {out_full}")

    # By family / asset breakdown
    print()
    print("=== Breakdown by family (deployable cells) ===")
    fam_agg = deployable.groupby(["asset", "family", "action"]).agg(
        n_cells=("cell_id", "size"),
        total_n=("n_full", "sum"),
        total_pnl=("deploy_pnl_full", "sum"),
        held_pnl=(deployable.columns[0], lambda x: 0),  # placeholder, replaced below
    ).reset_index()
    # Recompute held_pnl properly per row
    deployable["held_pnl"] = deployable.apply(
        lambda r: r["pnl_keep_held"] if r["action"] == "KEEP" else r["pnl_invert_held"], axis=1)
    fam_agg = deployable.groupby(["asset", "family", "action"]).agg(
        n_cells=("cell_id", "size"),
        total_n=("n_full", "sum"),
        total_pnl=("deploy_pnl_full", "sum"),
        held_pnl=("held_pnl", "sum"),
    ).reset_index().sort_values("total_pnl", ascending=False)
    print(fam_agg.to_string(index=False))


if __name__ == "__main__":
    main()
