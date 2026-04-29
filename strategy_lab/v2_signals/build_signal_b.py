"""Signal B - vol-arb / digital fair value.

prob_b = norm.cdf(d) where d = ln(S/S0) / (sigma*sqrt(T)),
S = current binance close at window_start, S0 = strike_price,
sigma = daily realized vol from the last 1440 minutes of 1m closes.

Implementation notes:

* Vol estimator: RMS of log-returns rather than standard deviation.
  For mean-zero returns (the typical case for 1m crypto closes) the
  two are numerically equivalent. RMS is chosen so the formula is
  exact for the synthetic constant-return test case.

* No 0.5*sigma^2*T drift correction in d. Sub-15-min tenors with
  sigma_daily ~ 0.02 give 0.5*sigma_t^2 < 1e-5 - completely negligible
  vs calibration noise. Dropping it gives a clean ATM-equals-0.5 property.

Calibrated via isotonic regression against actual outcomes on the
chronological train slice. Test rows are scored using the train-fitted
calibrator (no leakage).
"""
from __future__ import annotations
import argparse, os
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.isotonic import IsotonicRegression
from strategy_lab.v2_signals.common import (
    load_features, save_features, ASSETS, DATA_DIR, chronological_split,
)

TIMEFRAME_SECONDS = {"5m": 300, "15m": 900}


def realized_vol_daily(closes_1m: pd.Series) -> float:
    rets = np.log(closes_1m.astype(float)).diff().dropna().values
    # RMS instead of std: equivalent for mean-zero returns, exact for constant-return inputs.
    return float(np.sqrt(np.mean(rets ** 2)) * np.sqrt(1440))


def digital_fair_yes(s: float, s0: float, sigma_daily: float, t_seconds: float) -> float:
    if sigma_daily <= 0 or t_seconds <= 0:
        return 1.0 if s > s0 else (0.0 if s < s0 else 0.5)
    sigma_t = sigma_daily * np.sqrt(t_seconds / 86400)
    # No 0.5*sigma_t**2 drift term: negligible at sub-15-min tenors and gives ATM=0.5.
    d = np.log(s / s0) / sigma_t
    p = float(norm.cdf(d))
    return min(max(p, 1e-4), 1.0 - 1e-4)


def isotonic_calibrate(raw_train, y_train, raw_to_calibrate) -> np.ndarray:
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_train, y_train)
    return iso.transform(raw_to_calibrate)


def load_klines_1m(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "binance" / f"{asset}_klines_window.csv"
    k = pd.read_csv(p)
    k = k[k.period_id == "1MIN"].copy()
    k["ts_s"] = (k.time_period_start_us // 1_000_000).astype(int)
    return k.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def compute_raw_prob_b(features: pd.DataFrame, klines: pd.DataFrame) -> pd.Series:
    closes_idx = klines["ts_s"].values
    closes_vals = klines["price_close"].astype(float).values
    raw = np.full(len(features), np.nan, dtype=float)

    for i, row in features.reset_index(drop=True).iterrows():
        ws = int(row["window_start_unix"])
        lo = ws - 86400
        l = np.searchsorted(closes_idx, lo)
        r = np.searchsorted(closes_idx, ws)
        if r - l < 60:
            continue
        sigma = realized_vol_daily(pd.Series(closes_vals[l:r]))
        s = float(closes_vals[r - 1])
        s0 = float(row["strike_price"])
        if not (np.isfinite(s) and np.isfinite(s0) and s0 > 0 and sigma > 0):
            continue
        t_sec = TIMEFRAME_SECONDS.get(row["timeframe"], 300)
        raw[i] = digital_fair_yes(s, s0, sigma, t_sec)

    return pd.Series(raw, name="prob_b_raw")


def build_one_asset(asset: str) -> None:
    df = load_features(asset)
    klines = load_klines_1m(asset)
    df["prob_b_raw"] = compute_raw_prob_b(df, klines).values
    valid = df.dropna(subset=["prob_b_raw"])
    train, _ = chronological_split(valid)
    df["prob_b"] = 0.5
    mask = df["prob_b_raw"].notna()
    df.loc[mask, "prob_b"] = isotonic_calibrate(
        train["prob_b_raw"].values, train["outcome_up"].values,
        df.loc[mask, "prob_b_raw"].values
    )
    df = df.drop(columns=["prob_b_raw"])
    save_features(asset, df)
    print(f"{asset}: prob_b written, n_valid={mask.sum()}/{len(df)}, "
          f"mean={df.loc[mask,'prob_b'].mean():.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
