"""
PAT+ACC-M walk-forward validator.

Audit the hyperparameter sweep claims for in-sample optimization bias.

Process:
  1. Load all per-slug PnL CSVs from the sweep (every variant has one row per
     slug with `slot_start_s` and `pnl`).
  2. Split slugs by slot_start_s into K time-ordered folds.
  3. For each fold i:
       train = data up to fold i  (in-sample tuning window)
       test  = fold i+1           (held-out, never seen during selection)
       pick best config by train mean PnL
       evaluate THAT config on test
       compare to baseline (PAT+ACC-M, t=5, sz=20, pc=1.0, f=10, s=5) on test
  4. Report:
     - Per-fold OOS PnL for selected config vs baseline
     - Stability: how often does the same config win across folds?
     - Aggregate OOS lift vs in-sample lift

Inputs: all _fast_full_*_*.csv files in strategy_lab/backtests/

Outputs:
  _walkforward_per_fold.csv
  _walkforward_config_stability.csv
  _walkforward_summary.csv

Usage:
    py -3 -X utf8 strategy_lab/backtests/pat_walkforward.py
"""
from __future__ import annotations
import glob
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"


# EXTENDED window FIXED (Apr 22 → May 19 with _06+_16+_19 sources).
# Previous attempt used _12 which was a sparse delta → fold 4 looked broken.
# Fixed sources give clean coverage with ~26h gap May 14-16.
BTC_5M_SWEEP_FILES = [
    "_fast_full_btc_btc_5m_FIXED.csv",  # baseline + t=60..240 + t5-COMBO + t210-COMBO
]
BTC_15M_SWEEP_FILES = [
    "_fast_full_btc_btc_15m_FIXED.csv",  # baseline + t=180/360/600 + t600-COMBO
]
ETH_5M_SWEEP_FILES = [
    "_fast_full_eth_eth_5m_FIXED.csv",
]
SOL_5M_SWEEP_FILES = [
    "_fast_full_sol_sol_5m_FIXED.csv",
]


def load_pnl(file_list: list[str]) -> pd.DataFrame:
    """Load and concatenate per-slug PnL across all sweep files."""
    parts = []
    for f in file_list:
        p = OUT_DIR / f
        if not p.exists():
            print(f"  WARN missing {p.name}")
            continue
        df = pd.read_csv(p)
        parts.append(df)
    if not parts:
        raise SystemExit("No PnL files found")
    df = pd.concat(parts, ignore_index=True)
    df = df.drop_duplicates(["slug", "strategy"], keep="first")
    # Pull slot_start_s from slug suffix
    df["slot_start_s"] = df["slug"].str.rsplit("-", n=1).str[-1].astype("int64")
    return df


BASELINE = "PAT+ACC-M"


def walkforward_folds(df: pd.DataFrame, k: int = 4) -> list[tuple[int, int, int]]:
    """Return list of (train_end_ts, test_start_ts, test_end_ts) tuples.
    All slugs in train_period have slot_start_s <= train_end_ts.
    Test slugs have train_end_ts < slot_start_s <= test_end_ts.
    """
    ts_min = int(df["slot_start_s"].min())
    ts_max = int(df["slot_start_s"].max())
    total_s = ts_max - ts_min
    # K equal-size folds for test, expanding train
    fold_size = total_s // (k + 1)  # first fold is train-only
    folds = []
    for i in range(k):
        train_end = ts_min + fold_size * (i + 1)
        test_start = train_end
        test_end = ts_min + fold_size * (i + 2)
        folds.append((train_end, test_start, test_end))
    return folds


def run_walkforward(df: pd.DataFrame, label: str, k: int = 4,
                    min_slugs_per_variant: int = 30,
                    deployable_only: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run walk-forward selection.

    For each fold:
      - Compute mean PnL per (strategy variant) on train
      - Pick best variant
      - Compute that variant's mean PnL on test
      - Also compute baseline's mean PnL on test
      - Compute oracle (best variant ON TEST — upper bound) for reference
    """
    folds = walkforward_folds(df, k)
    fold_rows = []
    stability_rows = []

    if deployable_only:
        # Only configs that fit $200 wallet: exclude AGG (sz=100), exclude sz10-f30
        excluded = {"PAT+ACC-M-t210-AGG", "PAT+ACC-M-t210-sz10-f30"}
        df = df[~df["strategy"].isin(excluded)].copy()
    variants = sorted(df["strategy"].unique())
    print(f"  {label}: {len(variants)} variants, {df['slug'].nunique()} slugs total"
          f"{' (deployable only)' if deployable_only else ''}")

    for i, (train_end, test_start, test_end) in enumerate(folds):
        train = df[df.slot_start_s <= train_end]
        test = df[(df.slot_start_s > test_start) & (df.slot_start_s <= test_end)]
        n_train_slugs = train["slug"].nunique()
        n_test_slugs = test["slug"].nunique()

        # Per-variant train means + test means
        train_means = train.groupby("strategy").agg(
            n=("pnl", "size"),
            mean=("pnl", "mean"),
            sum=("pnl", "sum"),
        ).reset_index()
        test_means = test.groupby("strategy").agg(
            n=("pnl", "size"),
            mean=("pnl", "mean"),
            sum=("pnl", "sum"),
        ).reset_index()

        # Filter variants with enough slugs in BOTH train and test
        train_means = train_means[train_means.n >= min_slugs_per_variant]
        test_means_df = test_means.set_index("strategy")
        common = train_means["strategy"].tolist()
        common = [s for s in common if s in test_means_df.index and
                  test_means_df.loc[s, "n"] >= min_slugs_per_variant]
        if not common:
            print(f"  fold {i+1}: no eligible variants, skipping")
            continue

        train_sub = train_means[train_means["strategy"].isin(common)].copy()
        # Pick best by train mean
        best_idx = train_sub["mean"].idxmax()
        best_variant = str(train_sub.loc[best_idx, "strategy"])
        train_pick_mean = float(train_sub.loc[best_idx, "mean"])

        # Test PnL of selected variant
        test_pick_mean = float(test_means_df.loc[best_variant, "mean"])
        test_pick_sum = float(test_means_df.loc[best_variant, "sum"])
        test_pick_n = int(test_means_df.loc[best_variant, "n"])

        # Baseline test
        if BASELINE in test_means_df.index:
            test_base_mean = float(test_means_df.loc[BASELINE, "mean"])
            test_base_sum = float(test_means_df.loc[BASELINE, "sum"])
            test_base_n = int(test_means_df.loc[BASELINE, "n"])
        else:
            test_base_mean = float("nan")
            test_base_sum = float("nan")
            test_base_n = 0

        # Oracle: best variant ON test (upper bound — proxy for "ceiling")
        oracle_idx = test_means_df.loc[common, "mean"].idxmax()
        oracle_variant = str(oracle_idx)
        oracle_mean = float(test_means_df.loc[oracle_variant, "mean"])

        # Stability: how does our train-pick rank on test?
        test_ranked = test_means_df.loc[common, "mean"].sort_values(ascending=False)
        test_rank = list(test_ranked.index).index(best_variant) + 1

        fold_rows.append({
            "fold": i + 1,
            "label": label,
            "train_end_ts": train_end,
            "train_end_date": datetime.fromtimestamp(train_end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "test_start_date": datetime.fromtimestamp(test_start, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "test_end_date": datetime.fromtimestamp(test_end, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "n_train_slugs": n_train_slugs,
            "n_test_slugs": n_test_slugs,
            "n_variants_eligible": len(common),
            "selected_variant": best_variant,
            "train_pick_mean": round(train_pick_mean, 4),
            "test_pick_mean": round(test_pick_mean, 4),
            "test_pick_sum": round(test_pick_sum, 2),
            "test_pick_n": test_pick_n,
            "test_baseline_mean": round(test_base_mean, 4),
            "test_baseline_sum": round(test_base_sum, 2),
            "test_baseline_n": test_base_n,
            "test_lift_pct": round((test_pick_mean - test_base_mean) / max(abs(test_base_mean), 0.01) * 100, 1)
                              if not np.isnan(test_base_mean) else None,
            "test_pick_rank_on_test": test_rank,
            "oracle_variant": oracle_variant,
            "oracle_mean": round(oracle_mean, 4),
            "selection_gap_pct": round((oracle_mean - test_pick_mean) / max(abs(oracle_mean), 0.01) * 100, 1),
        })

        # Stability detail
        for v in common:
            stability_rows.append({
                "fold": i + 1,
                "label": label,
                "variant": v,
                "train_mean": round(float(train_means.set_index("strategy").loc[v, "mean"]), 4),
                "test_mean": round(float(test_means_df.loc[v, "mean"]), 4),
                "train_n": int(train_means.set_index("strategy").loc[v, "n"]),
                "test_n": int(test_means_df.loc[v, "n"]),
                "is_train_pick": v == best_variant,
                "is_oracle": v == oracle_variant,
            })

    folds_df = pd.DataFrame(fold_rows)
    stab_df = pd.DataFrame(stability_rows)
    return folds_df, stab_df


def print_fold_table(df: pd.DataFrame, label: str):
    if df.empty:
        return
    print(f"\n{'='*120}")
    print(f"WALK-FORWARD RESULTS — {label}")
    print(f"{'='*120}")
    cols = ["fold", "n_train_slugs", "n_test_slugs", "selected_variant",
            "train_pick_mean", "test_pick_mean", "test_baseline_mean",
            "test_lift_pct", "test_pick_rank_on_test", "selection_gap_pct"]
    print(df[cols].to_string(index=False))
    # Aggregate
    if "test_pick_sum" in df.columns:
        agg_lift = (df["test_pick_sum"].sum() - df["test_baseline_sum"].sum()) / max(abs(df["test_baseline_sum"].sum()), 0.01) * 100
        print(f"\nAggregate across {len(df)} folds:")
        print(f"  Test sum (selected): ${df['test_pick_sum'].sum():,.2f}")
        print(f"  Test sum (baseline): ${df['test_baseline_sum'].sum():,.2f}")
        print(f"  Aggregate OOS lift:  {agg_lift:+.1f}%")
        print(f"  Mean rank of selected on test: {df['test_pick_rank_on_test'].mean():.1f} (1 = oracle)")
        print(f"  Folds where picked-variant beat baseline OOS: "
              f"{(df['test_pick_mean'] > df['test_baseline_mean']).sum()} / {len(df)}")


def main():
    print("Loading PnL data ...")
    btc5m  = load_pnl(BTC_5M_SWEEP_FILES)
    btc15m = load_pnl(BTC_15M_SWEEP_FILES)
    eth5m  = load_pnl(ETH_5M_SWEEP_FILES)
    sol5m  = load_pnl(SOL_5M_SWEEP_FILES)
    print(f"  btc_5m: {len(btc5m)} rows, {btc5m['strategy'].nunique()} variants")
    print(f"  btc_15m: {len(btc15m)} rows, {btc15m['strategy'].nunique()} variants")
    print(f"  eth_5m: {len(eth5m)} rows, {eth5m['strategy'].nunique()} variants")
    print(f"  sol_5m: {len(sol5m)} rows, {sol5m['strategy'].nunique()} variants")

    all_folds = []
    all_stab = []

    for label, df in [("btc_5m", btc5m), ("btc_15m", btc15m),
                       ("eth_5m", eth5m), ("sol_5m", sol5m)]:
        if df.empty:
            continue
        print(f"\nRunning walk-forward on {label} (DEPLOYABLE: sz<=50)...")
        f, s = run_walkforward(df, label, k=4, deployable_only=True)
        all_folds.append(f)
        all_stab.append(s)
        print_fold_table(f, label)

    folds_df = pd.concat(all_folds, ignore_index=True) if all_folds else pd.DataFrame()
    stab_df = pd.concat(all_stab, ignore_index=True) if all_stab else pd.DataFrame()
    folds_df.to_csv(OUT_DIR / "_walkforward_per_fold.csv", index=False)
    stab_df.to_csv(OUT_DIR / "_walkforward_config_stability.csv", index=False)

    # Config stability across folds
    print(f"\n\n{'='*100}")
    print("CONFIG SELECTION STABILITY — which variant wins each fold?")
    print(f"{'='*100}")
    if not folds_df.empty:
        sel_counts = folds_df.groupby(["label", "selected_variant"]).size().reset_index(name="folds_picked")
        for label in sorted(folds_df["label"].unique()):
            print(f"\n{label}:")
            print(sel_counts[sel_counts["label"] == label].sort_values("folds_picked",
                                                                       ascending=False).to_string(index=False))

    # Summary
    print(f"\n{'='*100}")
    print("AGGREGATE WALK-FORWARD SUMMARY (out-of-sample only)")
    print(f"{'='*100}")
    if not folds_df.empty:
        summary = folds_df.groupby("label").agg(
            n_folds=("fold", "size"),
            mean_oos_lift_pct=("test_lift_pct", "mean"),
            n_folds_beat_baseline=("test_lift_pct", lambda s: (s > 0).sum()),
            mean_rank_on_test=("test_pick_rank_on_test", "mean"),
            mean_selection_gap_pct=("selection_gap_pct", "mean"),
        ).round(2)
        print(summary.to_string())
    print(f"\nFiles written:")
    print(f"  {OUT_DIR / '_walkforward_per_fold.csv'}")
    print(f"  {OUT_DIR / '_walkforward_config_stability.csv'}")


if __name__ == "__main__":
    main()
