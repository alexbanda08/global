"""Regime classifier — TREND / SIDEWAYS / VOLATILE labels per minute,
with hysteresis to prevent every-bar flips.

Inputs (per minute):
  - 1h trend slope magnitude (from btc_trend.rolling_slope_norm)
  - 1h realized vol (from btc_trend.realized_vol_1h)

Decision rule (raw, before hysteresis):
  vol_high     -> 'volatile'
  |slope| high -> 'trend'
  else         -> 'sideways'

Thresholds default to:
  vol_thresh = 0.0040   (~ 40 bps log-return std-dev over 1h)
  slope_thresh = 4.0e-5 (~ 4 bps per-minute slope, normalized)

These are rule-of-thumb defaults; the validation gate (G2/G3) tunes them.

Hysteresis: require N=5 consecutive raw labels of the new regime before
flipping. Initial state defaults to 'sideways'.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

DEFAULT_VOL_THRESH = 0.0040
DEFAULT_SLOPE_THRESH = 4.0e-5
DEFAULT_HYSTERESIS_BARS = 5

REGIME_TREND = "trend"
REGIME_SIDEWAYS = "sideways"
REGIME_VOLATILE = "volatile"

REGIME_FACTOR = {
    REGIME_TREND: 0.3,
    REGIME_SIDEWAYS: 0.0,
    REGIME_VOLATILE: -0.3,
}


def _raw_label(slope_1h: float, vol_1h: float,
               vol_thresh: float, slope_thresh: float) -> str:
    if not np.isfinite(vol_1h) or not np.isfinite(slope_1h):
        return REGIME_SIDEWAYS
    if vol_1h >= vol_thresh:
        return REGIME_VOLATILE
    if abs(slope_1h) >= slope_thresh:
        return REGIME_TREND
    return REGIME_SIDEWAYS


def classify_regime_series(
    slope_1h_arr: Iterable[float],
    vol_1h_arr: Iterable[float],
    vol_thresh: float = DEFAULT_VOL_THRESH,
    slope_thresh: float = DEFAULT_SLOPE_THRESH,
    hysteresis_bars: int = DEFAULT_HYSTERESIS_BARS,
    initial: str = REGIME_SIDEWAYS,
) -> np.ndarray:
    """Apply hysteresis-confirmed regime labels.

    Args:
      slope_1h_arr, vol_1h_arr: parallel arrays (one element per ws_unix
        sorted ascending in time).
      hysteresis_bars: require N consecutive raw labels of the candidate
        regime before flipping the confirmed state.
      initial: starting confirmed regime.

    Returns:
      np.ndarray of shape (n,) dtype=object with 'trend' / 'sideways' / 'volatile'.
    """
    slopes = np.asarray(list(slope_1h_arr), dtype=float)
    vols   = np.asarray(list(vol_1h_arr),   dtype=float)
    n = slopes.size
    out = np.empty(n, dtype=object)

    confirmed = initial
    candidate = initial
    streak = 0
    for i in range(n):
        raw = _raw_label(slopes[i], vols[i], vol_thresh, slope_thresh)
        if raw == confirmed:
            candidate = confirmed
            streak = 0
        elif raw == candidate:
            streak += 1
            if streak >= hysteresis_bars:
                confirmed = candidate
                streak = 0
        else:
            candidate = raw
            streak = 1
        out[i] = confirmed
    return out


def regime_factor(regime: str) -> float:
    """Map regime label to struct_score regime contribution."""
    return REGIME_FACTOR.get(regime, 0.0)
