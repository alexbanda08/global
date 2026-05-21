"""Q2: support / resistance pivots on 15m bars.

Find swing-high (resistance) and swing-low (support) pivots over the prior
`LEVELS_LOOKBACK_DAYS` of 15m closes (a swing point requires `K_CONFIRM`
strictly-lower/higher bars on EACH side). Then compute p_up from the
relative distance of `current_px` to the nearest pivot on each side.

p_up ∈ [0.5 - LEVELS_SCALE, 0.5 + LEVELS_SCALE]
  - p_up > 0.5 + LEVELS_MIN_CERTAINTY → vote +1 (price closer to support)
  - p_up < 0.5 - LEVELS_MIN_CERTAINTY → vote -1 (price closer to resistance)
  - else                              → vote 0 (abstain)

The axis is pure. The runner assembles the 15m bar arrays.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from ..conventions import (
    LEVELS_K_CONFIRM,
    LEVELS_LOOKBACK_DAYS,
    LEVELS_MIN_CERTAINTY,
    LEVELS_SCALE,
)

OhlcBars = Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]  # end_us, high, low, close


def find_pivots(highs: np.ndarray, lows: np.ndarray, k: int = LEVELS_K_CONFIRM):
    """Return (resistance_levels, support_levels) — 1-D arrays of pivot prices.

    A bar at index i is a swing high if highs[i] > highs[i-k..i-1] AND
    highs[i] > highs[i+1..i+k]. Strict inequality; flat highs do not pivot.
    Symmetric for swing lows.
    """
    n = highs.size
    if n < 2 * k + 1:
        return np.empty(0), np.empty(0)
    res_idx, sup_idx = [], []
    for i in range(k, n - k):
        left_h = highs[i - k : i]
        right_h = highs[i + 1 : i + 1 + k]
        if highs[i] > left_h.max() and highs[i] > right_h.max():
            res_idx.append(i)
        left_l = lows[i - k : i]
        right_l = lows[i + 1 : i + 1 + k]
        if lows[i] < left_l.min() and lows[i] < right_l.min():
            sup_idx.append(i)
    return highs[res_idx], lows[sup_idx]


def compute_levels_p_up(
    bars_15m: OhlcBars,
    ws_s_us: int,
    current_px: float,
    lookback_days: int = LEVELS_LOOKBACK_DAYS,
    k_confirm: int = LEVELS_K_CONFIRM,
    scale: float = LEVELS_SCALE,
) -> float:
    """Return p_up in [0.5 - scale, 0.5 + scale], or 0.5 if abstaining."""
    end_us, highs, lows, _close = bars_15m
    if end_us.size == 0 or not (current_px > 0):
        return 0.5
    cutoff = int(np.searchsorted(end_us, int(ws_s_us), side="right"))
    if cutoff < 2 * k_confirm + 1:
        return 0.5
    # Restrict to the lookback window.
    window_us = lookback_days * 86_400 * 1_000_000
    lo = int(np.searchsorted(end_us, int(ws_s_us) - window_us, side="left"))
    lo = max(0, lo)
    if cutoff - lo < 2 * k_confirm + 1:
        return 0.5
    res_levels, sup_levels = find_pivots(highs[lo:cutoff], lows[lo:cutoff], k_confirm)

    res_above = res_levels[res_levels > current_px]
    sup_below = sup_levels[sup_levels < current_px]
    if res_above.size == 0 or sup_below.size == 0:
        return 0.5

    dist_above = float(res_above.min() - current_px)
    dist_below = float(current_px - sup_below.max())
    denom = dist_above + dist_below
    if denom <= 0:
        return 0.5
    ratio = (dist_above - dist_below) / denom
    return 0.5 + scale * ratio


def levels_vote(p_up: float, threshold: float = LEVELS_MIN_CERTAINTY) -> int:
    """Collapse p_up to a {-1, 0, +1} axis vote."""
    if p_up > 0.5 + threshold:
        return 1
    if p_up < 0.5 - threshold:
        return -1
    return 0
