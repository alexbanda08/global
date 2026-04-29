"""Signal A — multi-horizon momentum agreement.

prob_a = empirical P(outcome_up=1 | votes_up bucket, asset, tf) on train slice.
"""
from __future__ import annotations
import argparse
import os
import pandas as pd
import numpy as np
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS

TRAIN_FRAC = 0.8


def compute_votes_up(df: pd.DataFrame) -> pd.Series:
    return ((df.ret_5m > 0).astype(int)
            + (df.ret_15m > 0).astype(int)
            + (df.ret_1h > 0).astype(int))


def calibrate_prob_a(full: pd.DataFrame, train: pd.DataFrame, min_samples: int = 20) -> pd.DataFrame:
    """Return full with a 'prob_a' column, fitted on train."""
    keys = ["asset", "timeframe", "votes_up"]
    bucket_stats = (train.groupby(keys)["outcome_up"]
                         .agg(["mean", "count"])
                         .reset_index()
                         .rename(columns={"mean": "p_up_bucket", "count": "n_bucket"}))
    out = full.merge(bucket_stats, on=keys, how="left")
    fallback = (out["n_bucket"].isna()) | (out["n_bucket"] < min_samples)
    out["prob_a"] = np.where(fallback, 0.5, out["p_up_bucket"])
    return out.drop(columns=["p_up_bucket", "n_bucket"])


def chronological_split(df: pd.DataFrame, train_frac: float = TRAIN_FRAC) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    cut = int(len(df) * train_frac)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def build_one_asset(asset: str) -> None:
    df = load_features(asset)
    df["votes_up"] = compute_votes_up(df)
    train, _ = chronological_split(df)
    df = calibrate_prob_a(df, train)
    save_features(asset, df)
    print(f"{asset}: prob_a written, mean={df['prob_a'].mean():.3f}, "
          f"std={df['prob_a'].std():.3f}, "
          f"buckets={df.groupby('votes_up')['prob_a'].mean().to_dict()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
