"""Signal C - Polymarket microstructure flow.

Combines (a) 60s pre-window trade-tape pressure and (b) top-5 book ask-size
imbalance, squashed to a probability in [0.1, 0.9], then isotonic-calibrated
on the train slice.

Markets with no trade-tape rows (no trades in 60s pre-window) get flow=0,
falling back to book-imbalance-only signal. Per Task 4 inventory ~50% of
resolved markets are in this group.
"""
from __future__ import annotations
import argparse, os
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from strategy_lab.v2_signals.common import (
    load_features, save_features, ASSETS, DATA_DIR, chronological_split,
)


def flow_signal_per_market(flow_df: pd.DataFrame) -> pd.Series:
    """Per slug: ((yes_buy - yes_sell) - (no_buy - no_sell)) / total_volume.
    Positive = aggressive YES buying = pressure for UP. Range [-1, +1]."""
    pivoted = (flow_df.assign(signed=lambda d: np.where(d.taker_side=='buy',
                                                        d.total_size, -d.total_size))
                       .groupby(["slug", "outcome"])["signed"].sum().unstack(fill_value=0))
    yes = pivoted.get("Up", 0)
    no  = pivoted.get("Down", 0)
    total_vol = (flow_df.groupby("slug")["total_size"].sum()).replace(0, np.nan)
    return ((yes - no) / total_vol).fillna(0)


def book_imbalance_top5(book: pd.DataFrame) -> pd.Series:
    """Per slug: (no_ask5 - yes_ask5) / (no_ask5 + yes_ask5).
    Positive = NO has more sellers = MMs leaning NO is cheap = expect UP."""
    cols = [f"ask_size_{i}" for i in range(5)]
    pivoted = (book.assign(ask5=book[cols].sum(axis=1))
                   .groupby(["slug","outcome"])["ask5"].mean()
                   .unstack(fill_value=0))
    yes = pivoted.get("Up", 0)
    no  = pivoted.get("Down", 0)
    denom = (yes + no).replace(0, np.nan)
    return ((no - yes) / denom).fillna(0)


def combine_to_prob_c(raw_c: pd.Series) -> pd.Series:
    """Squash raw_c in [-1, +1] to prob_c in [0.1, 0.9]."""
    return 0.5 + 0.4 * raw_c.clip(-1, 1)


def isotonic_calibrate(raw_train, y_train, raw_to_cal):
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_train, y_train)
    return iso.transform(raw_to_cal)


def load_flow(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_flow_v3.csv"
    return pd.read_csv(p)


def load_book_depth(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_book_depth_v3.csv"
    bd = pd.read_csv(p)
    # Use only the snapshot at bucket_10s == 0 (window-start) to avoid leakage
    return bd[bd.bucket_10s == 0]


def build_one_asset(asset: str) -> None:
    feats = load_features(asset)
    flow = load_flow(asset)
    book = load_book_depth(asset)

    flow_sig = flow_signal_per_market(flow).rename("flow")
    imb      = book_imbalance_top5(book).rename("imb")
    feats = feats.merge(flow_sig, left_on="slug", right_index=True, how="left")
    feats = feats.merge(imb,      left_on="slug", right_index=True, how="left")
    feats[["flow", "imb"]] = feats[["flow", "imb"]].fillna(0)
    raw_c = 0.6 * feats["flow"] + 0.4 * feats["imb"]
    feats["prob_c_raw"] = combine_to_prob_c(raw_c)

    train, _ = chronological_split(feats)
    feats["prob_c"] = isotonic_calibrate(
        train["prob_c_raw"].values, train["outcome_up"].values, feats["prob_c_raw"].values
    )
    feats = feats.drop(columns=["flow", "imb", "prob_c_raw"])
    save_features(asset, feats)
    n_with_flow = (feats["slug"].isin(flow["slug"].unique())).sum()
    print(f"{asset}: prob_c written, n_with_flow={n_with_flow}/{len(feats)}, "
          f"mean={feats['prob_c'].mean():.3f}, std={feats['prob_c'].std():.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
