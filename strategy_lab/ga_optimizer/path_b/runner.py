"""CLI runner for Path B GA."""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from strategy_lab.ga_optimizer.path_b.events import load_path_b_events
from strategy_lab.ga_optimizer.path_b.cells import build_cell_index, cell_baseline
from strategy_lab.ga_optimizer.path_b.ga_filter import PathBConfig, run_path_b_ga


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", type=int, default=100)
    ap.add_argument("--generations", type=int, default=80)
    ap.add_argument("--min-n-cell", type=int, default=20)
    ap.add_argument("--train-frac", type=float, default=0.65)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--sharpe-weight", type=float, default=0.20)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print("=== Path B GA: filter-learning on production events ===")
    print("[loading] production events...")
    events = load_path_b_events()
    print(f"  total events: {len(events):,}")
    print(f"  window: {events.at_ts.min()} → {events.at_ts.max()}")
    print(f"  unique cells (sleeve_id,signal,hour_bucket,dow_group): {events.cell_id.nunique():,}")

    # DATE-based split (not index-based — event density varies hour-to-hour)
    events = events.sort_values("at_ts").reset_index(drop=True)
    ts_min = events.at_ts.min(); ts_max = events.at_ts.max()
    span = ts_max - ts_min
    train_end_ts = ts_min + span * args.train_frac
    val_end_ts   = ts_min + span * (args.train_frac + args.val_frac)
    events_train = events[events.at_ts < train_end_ts]
    events_val   = events[(events.at_ts >= train_end_ts) & (events.at_ts < val_end_ts)]
    events_held  = events[events.at_ts >= val_end_ts]
    print(f"  train: {len(events_train):,} ({events_train.at_ts.min()} → {events_train.at_ts.max()})")
    print(f"  val  : {len(events_val):,} ({events_val.at_ts.min()} → {events_val.at_ts.max()})")
    print(f"  held : {len(events_held):,} ({events_held.at_ts.min()} → {events_held.at_ts.max()})")

    print("\n[cells] building cell index on full universe...")
    cells, _ = build_cell_index(events, min_n=args.min_n_cell)
    print(f"  {len(cells)} cells with n>={args.min_n_cell}")

    base = cell_baseline(cells)
    print(f"\n[baseline] greedy best-per-cell:")
    print(f"  KEEP-all total: ${base['totals']['KEEP']:+.2f}")
    print(f"  INVERT-all total: ${base['totals']['INVERT']:+.2f}")
    print(f"  BEST per-cell total: ${base['totals']['BEST']:+.2f}")
    print(f"  chosen actions: KEEP={base['totals']['n_keep']} INVERT={base['totals']['n_invert']} SKIP={base['totals']['n_skip']}")

    config = PathBConfig(
        population_size=args.population, n_generations=args.generations,
        min_n_cell=args.min_n_cell, train_fraction=args.train_frac,
        val_fraction=args.val_frac, sharpe_weight=args.sharpe_weight,
        seed=args.seed,
    )
    run_dir = ROOT / "strategy_lab" / "ga_optimizer" / "runs" / f"path_b_{int(time.time())}"
    result = run_path_b_ga(cells, events_train, events_val, events_held, config, run_dir)
    print(f"\n[Path B] run dir: {run_dir}")
    print(f"  best train pnl: ${result['best_overall']['train']['pnl']:+.2f}")
    print(f"  best val   pnl: ${result['best_overall']['val']['pnl']:+.2f}")
    print(f"  held-out   pnl: ${result['held_out']['pnl']:+.2f}")


if __name__ == "__main__":
    main()
