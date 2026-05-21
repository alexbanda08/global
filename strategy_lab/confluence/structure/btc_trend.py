"""BTC trend slope helpers.

Rolling regression slope (per minute) on closes ending at ws_unix, normalized by
mean price so the output is unitless and comparable across price regimes.

Strict no-lookahead: only bars with ts_s <= ws_unix are used. Asof selection
mirrors `extended_backtest_with_robustness.asof()` semantics — bar end time
(ts_s + 60s) <= ws_unix.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd


def rolling_slope_norm(closes: np.ndarray) -> float:
    """Linear-regression slope (per-step) of `closes` divided by mean(closes).

    Output is unitless (1/step). Returns NaN if fewer than 5 finite samples.
    """
    if closes is None:
        return float("nan")
    arr = np.asarray(closes, dtype=float)
    finite = np.isfinite(arr)
    if finite.sum() < 5:
        return float("nan")
    arr = arr[finite]
    n = arr.size
    x = np.arange(n, dtype=float)
    # Closed-form OLS slope
    x_mean = x.mean()
    y_mean = arr.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom <= 0:
        return float("nan")
    slope = ((x - x_mean) * (arr - y_mean)).sum() / denom
    if y_mean <= 0 or not np.isfinite(y_mean):
        return float("nan")
    return float(slope / y_mean)


def _idx_le(ts_s: np.ndarray, ws_unix: int) -> int:
    """Largest index i where bar end time (ts_s[i] + 60) <= ws_unix.

    Mirrors extended_backtest.asof() semantics. Returns -1 if none.
    """
    end_us = (ts_s.astype("int64") + 60) * 1_000_000
    target_us = int(ws_unix) * 1_000_000
    return int(np.searchsorted(end_us, target_us, side="right")) - 1


def compute_trend_slopes(
    btc_kline: pd.DataFrame,
    ws_unix_arr: Sequence[int],
    minutes_1h: int = 60,
    minutes_4h: int = 240,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized 1h + 4h slopes for many ws_unix values.

    Args:
      btc_kline: DataFrame with columns ts_s (sorted ascending), price_close.
      ws_unix_arr: iterable of window_start_unix ints to evaluate at.
      minutes_1h, minutes_4h: lookback bar counts.

    Returns:
      (slope_1h_arr, slope_4h_arr) numpy arrays, length len(ws_unix_arr).
      NaN where insufficient data.
    """
    ts_s = btc_kline["ts_s"].to_numpy(dtype="int64")
    closes = btc_kline["price_close"].to_numpy(dtype=float)
    out1h = np.full(len(ws_unix_arr), np.nan, dtype=float)
    out4h = np.full(len(ws_unix_arr), np.nan, dtype=float)
    for i, ws in enumerate(ws_unix_arr):
        idx = _idx_le(ts_s, int(ws))
        if idx < 0:
            continue
        # 1h window
        lo1 = max(0, idx - minutes_1h + 1)
        if idx - lo1 + 1 >= 5:
            out1h[i] = rolling_slope_norm(closes[lo1 : idx + 1])
        # 4h window
        lo4 = max(0, idx - minutes_4h + 1)
        if idx - lo4 + 1 >= 5:
            out4h[i] = rolling_slope_norm(closes[lo4 : idx + 1])
    return out1h, out4h


def realized_vol_1h(btc_kline: pd.DataFrame, ws_unix: int, minutes: int = 60) -> float:
    """Realized volatility of log returns over the last `minutes` minutes.

    Returns std-dev of 1-step log-returns. Used by regime classifier.
    NaN if insufficient bars.
    """
    ts_s = btc_kline["ts_s"].to_numpy(dtype="int64")
    closes = btc_kline["price_close"].to_numpy(dtype=float)
    idx = _idx_le(ts_s, int(ws_unix))
    if idx < 0:
        return float("nan")
    lo = max(0, idx - minutes + 1)
    seg = closes[lo : idx + 1]
    seg = seg[np.isfinite(seg) & (seg > 0)]
    if seg.size < 5:
        return float("nan")
    rets = np.diff(np.log(seg))
    if rets.size < 4:
        return float("nan")
    return float(np.std(rets, ddof=1))
