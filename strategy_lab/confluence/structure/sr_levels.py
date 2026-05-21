"""Swing-high / swing-low S/R extraction + nearest-distance helpers.

Definition of a swing point (per Phase 3 spec):
  - Swing high = local max where 30 bars BEFORE and 30 bars AFTER are <= it
  - Swing low  = local min where 30 bars BEFORE and 30 bars AFTER are >= it

Confirmation lag: a swing at index i can only be CONFIRMED at bar i + window
(we need 30 future bars to validate it). We keep that constraint by only
returning swings whose confirmation_ts <= query_ws_unix. This preserves the
strict no-lookahead invariant.

Distance: |current_price - level| / current_price * 10000 (bps).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

DEFAULT_LOOKBACK_DAYS = 5
DEFAULT_SWING_WINDOW_BARS = 30   # 30 bars on each side


def extract_swings(
    kline: pd.DataFrame,
    window_bars: int = DEFAULT_SWING_WINDOW_BARS,
) -> pd.DataFrame:
    """Find all swing highs/lows in the kline (sorted by ts_s ascending).

    Returns DataFrame with columns:
      ts_s_pivot      : timestamp of the swing pivot bar (start of bar)
      ts_s_confirm    : timestamp at which the swing is confirmed
                        (= ts_s_pivot + window_bars * 60)
      level           : pivot price_close
      kind            : 'high' or 'low'
    """
    if kline.empty or len(kline) < 2 * window_bars + 1:
        return pd.DataFrame(columns=["ts_s_pivot", "ts_s_confirm", "level", "kind"])

    ts_s = kline["ts_s"].to_numpy(dtype="int64")
    closes = kline["price_close"].to_numpy(dtype=float)
    n = closes.size
    w = window_bars

    rows = []
    for i in range(w, n - w):
        c = closes[i]
        if not np.isfinite(c) or c <= 0:
            continue
        # Slice excluding center bar
        lo = closes[i - w : i]
        hi = closes[i + 1 : i + 1 + w]
        if not (np.isfinite(lo).all() and np.isfinite(hi).all()):
            continue
        if c >= lo.max() and c >= hi.max():
            rows.append({
                "ts_s_pivot":   int(ts_s[i]),
                "ts_s_confirm": int(ts_s[i]) + w * 60,
                "level": float(c),
                "kind":  "high",
            })
        elif c <= lo.min() and c <= hi.min():
            rows.append({
                "ts_s_pivot":   int(ts_s[i]),
                "ts_s_confirm": int(ts_s[i]) + w * 60,
                "level": float(c),
                "kind":  "low",
            })

    if not rows:
        return pd.DataFrame(columns=["ts_s_pivot", "ts_s_confirm", "level", "kind"])
    return pd.DataFrame(rows).sort_values("ts_s_confirm").reset_index(drop=True)


def _idx_le(ts_s: np.ndarray, ws_unix: int) -> int:
    end_us = (ts_s.astype("int64") + 60) * 1_000_000
    target_us = int(ws_unix) * 1_000_000
    return int(np.searchsorted(end_us, target_us, side="right")) - 1


def nearest_distance_bps(
    swings: pd.DataFrame,
    kline: pd.DataFrame,
    ws_unix: int,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[float, float]:
    """For a single ws_unix:

    1. Get current_price = asof close at ws_unix.
    2. Filter swings to those:
        - confirmed by ws_unix (ts_s_confirm <= ws_unix), so no lookahead
        - within last `lookback_days` (ts_s_pivot >= ws_unix - lookback_days*86400)
    3. Resistance = nearest 'high' ABOVE current_price.
       Support    = nearest 'low'  BELOW current_price.

    Returns (dist_to_resistance_bps, dist_to_support_bps). NaN if no level found.
    """
    ts_s = kline["ts_s"].to_numpy(dtype="int64")
    closes = kline["price_close"].to_numpy(dtype=float)
    idx = _idx_le(ts_s, int(ws_unix))
    if idx < 0:
        return float("nan"), float("nan")
    cur = float(closes[idx])
    if not np.isfinite(cur) or cur <= 0:
        return float("nan"), float("nan")

    if swings.empty:
        return float("nan"), float("nan")

    cutoff_lo = int(ws_unix) - lookback_days * 86400
    mask = (
        (swings["ts_s_confirm"].astype("int64") <= int(ws_unix))
        & (swings["ts_s_pivot"].astype("int64") >= cutoff_lo)
    )
    sub = swings[mask]
    if sub.empty:
        return float("nan"), float("nan")

    highs = sub.loc[sub["kind"] == "high", "level"].to_numpy(dtype=float)
    lows  = sub.loc[sub["kind"] == "low",  "level"].to_numpy(dtype=float)

    # Resistance = nearest high strictly above current
    above = highs[highs > cur]
    if above.size:
        dist_r = (above.min() - cur) / cur * 10_000.0
    else:
        dist_r = float("nan")

    below = lows[lows < cur]
    if below.size:
        dist_s = (cur - below.max()) / cur * 10_000.0
    else:
        dist_s = float("nan")

    return dist_r, dist_s


def compute_distances_for_universe(
    swings: pd.DataFrame,
    kline: pd.DataFrame,
    ws_unix_arr: Sequence[int],
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized wrapper — returns (dist_resist_arr, dist_support_arr).

    swings is sorted by ts_s_confirm. We use searchsorted to slice the
    confirmed-by-ws subset and apply per-ws lookback inside the loop.
    """
    n = len(ws_unix_arr)
    out_r = np.full(n, np.nan, dtype=float)
    out_s = np.full(n, np.nan, dtype=float)
    if swings.empty or kline.empty:
        return out_r, out_s

    # Precompute kline asof index lookup arrays
    ts_s_kline = kline["ts_s"].to_numpy(dtype="int64")
    closes_kline = kline["price_close"].to_numpy(dtype=float)
    end_us = (ts_s_kline + 60) * 1_000_000

    confirm_arr = swings["ts_s_confirm"].to_numpy(dtype="int64")
    pivot_arr   = swings["ts_s_pivot"].to_numpy(dtype="int64")
    level_arr   = swings["level"].to_numpy(dtype=float)
    kind_arr    = swings["kind"].to_numpy()

    for i, ws in enumerate(ws_unix_arr):
        ws_i = int(ws)
        target_us = ws_i * 1_000_000
        idx_k = int(np.searchsorted(end_us, target_us, side="right")) - 1
        if idx_k < 0:
            continue
        cur = closes_kline[idx_k]
        if not np.isfinite(cur) or cur <= 0:
            continue

        # Slice swings with ts_s_confirm <= ws_i (binary search since sorted)
        cut = int(np.searchsorted(confirm_arr, ws_i, side="right"))
        if cut == 0:
            continue
        cutoff_lo = ws_i - lookback_days * 86400
        # Pivot lookback filter
        piv_sub = pivot_arr[:cut]
        mask = piv_sub >= cutoff_lo
        if not mask.any():
            continue

        levels = level_arr[:cut][mask]
        kinds = kind_arr[:cut][mask]
        highs = levels[kinds == "high"]
        lows  = levels[kinds == "low"]

        above = highs[highs > cur]
        if above.size:
            out_r[i] = (above.min() - cur) / cur * 10_000.0
        below = lows[lows < cur]
        if below.size:
            out_s[i] = (cur - below.max()) / cur * 10_000.0

    return out_r, out_s
