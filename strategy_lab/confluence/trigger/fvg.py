"""Fair Value Gap (FVG) detection on 1-minute klines.

3-candle pattern (indices t-2, t-1, t):
  Bullish FVG: low[t]   > high[t-2]   (gap up; range = (high[t-2], low[t]))
  Bearish FVG: high[t]  < low[t-2]    (gap down; range = (high[t], low[t-2]))

A gap is "filled" once a subsequent candle's wick (low for bullish; high for
bearish) trades back into the gap range. We treat the FVG as ACTIVE if any
unfilled gap exists in the last `lookback_min` minutes ending at query_ts.

Side reported:
  'up'   — bullish FVG (price gapped up, magnet pulls upward)
  'down' — bearish FVG (price gapped down, magnet pulls downward)
  None   — no active gap
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACK_MIN = 30   # 30-minute lookback for FVG search

# Kline column conventions (from klines_full.csv):
#   time_period_start_us, price_high, price_low, price_close


def compute_fvg(
    klines_1m: pd.DataFrame,
    query_ts_s: int,
    lookback_min: int = LOOKBACK_MIN,
) -> tuple[bool, str | None]:
    """Detect the most recent active (unfilled) FVG in the lookback window.

    Args:
      klines_1m: 1-minute klines for the asset, columns must include
        `ts_s` (int seconds, bar OPEN time), `price_high`, `price_low`.
        Sorted ascending by ts_s.
      query_ts_s: seconds. Bars whose OPEN time + 60 <= query_ts_s are usable
        (strict no-lookahead — bar must have CLOSED before query_ts).
      lookback_min: how many minutes to look back for FVG patterns.

    Returns:
      (active, side) where side is 'up'/'down' or None.

    Strategy:
      1. Slice klines to (query_ts - lookback_min*60, query_ts] using
         end-time-indexing (bar end = ts_s + 60).
      2. Iterate windows of 3 bars (t-2, t-1, t). For each, test bullish then
         bearish gap conditions.
      3. For each detected gap, check whether ANY subsequent bar in the slice
         (and beyond, up to query_ts) has wicked into the gap range; if not,
         the gap is unfilled and the FVG is active.
      4. Return the side of the MOST RECENT unfilled gap.
    """
    if klines_1m is None or klines_1m.empty:
        return False, None

    # End-time-indexing: bar valid only if ts_s + 60 <= query_ts_s
    ts_s_arr = klines_1m["ts_s"].values
    valid_mask = (ts_s_arr.astype(np.int64) + 60) <= int(query_ts_s)
    if not valid_mask.any():
        return False, None

    lo_s = int(query_ts_s) - lookback_min * 60
    window_mask = valid_mask & (ts_s_arr >= lo_s)
    if window_mask.sum() < 3:
        return False, None

    sub = klines_1m.loc[window_mask, ["ts_s", "price_high", "price_low"]].reset_index(drop=True)
    highs = sub["price_high"].values.astype(float)
    lows = sub["price_low"].values.astype(float)
    n = len(sub)

    # Walk newest-first; first unfilled gap wins.
    # For gap at index t, "subsequent" bars are those with ts > sub.ts[t]
    # AND still <= query_ts. Within the slice that's just rows t+1..n-1, but
    # bars after the slice (ts beyond lookback start, before query_ts) can't
    # exist because slice ends at query_ts. So scan rows in [t+1, n).
    last_gap_idx: int | None = None
    last_gap_side: str | None = None
    for t in range(2, n):
        h_t2 = highs[t - 2]
        l_t2 = lows[t - 2]
        h_t = highs[t]
        l_t = lows[t]
        if not (np.isfinite(h_t2) and np.isfinite(l_t2) and np.isfinite(h_t) and np.isfinite(l_t)):
            continue

        bull_gap = l_t > h_t2   # range = (h_t2, l_t)
        bear_gap = h_t < l_t2   # range = (h_t, l_t2)

        if bull_gap:
            # Filled if any subsequent bar's LOW dips at or below h_t2
            if t + 1 < n:
                if (lows[t + 1:] <= h_t2).any():
                    continue
            last_gap_idx = t
            last_gap_side = "up"
        elif bear_gap:
            # Filled if any subsequent bar's HIGH rises at or above l_t2
            if t + 1 < n:
                if (highs[t + 1:] >= l_t2).any():
                    continue
            last_gap_idx = t
            last_gap_side = "down"

    if last_gap_side is None:
        return False, None
    return True, last_gap_side
