"""Q1: multi-timeframe trend alignment.

For each of (1h, 15m, 5m): fit a linear regression on the last K closes
ending at-or-before ws_s_us. Compare normalized slope (fraction-of-price
per bar) to a configurable epsilon. Vote in {-1, 0, +1}. Alignment is the
signed sum across the three TFs → integer in [-3, +3].

Inputs use the canonical `load_klines_asof` shape:
    bars = (end_us: np.ndarray[int64], close: np.ndarray[float64])

The axis is pure: no I/O. The runner is responsible for assembling bars
at each TF (either pre-resampled parquet or client-side resample).
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from ..conventions import TREND_EPS_FRAC, TREND_K_BARS, TREND_MIN_ABS

Bars = Tuple[np.ndarray, np.ndarray]


def _slope_vote(bars: Bars, ws_s_us: int, k: int, eps_frac: float) -> int:
    """Slice the last `k` bars whose end_us <= ws_s_us, regress close on
    bar-index, return signed vote based on |slope| vs eps."""
    end_us, close = bars
    if end_us.size == 0:
        return 0
    cutoff = int(np.searchsorted(end_us, int(ws_s_us), side="right"))
    if cutoff < 2:
        return 0
    lo = max(0, cutoff - k)
    y = close[lo:cutoff]
    n = y.size
    if n < 2:
        return 0
    x = np.arange(n, dtype=np.float64)
    # Closed-form OLS slope. (sum((x-x̄)(y-ȳ)) / sum((x-x̄)^2))
    xm = x.mean()
    ym = y.mean()
    denom = ((x - xm) ** 2).sum()
    if denom <= 0 or ym <= 0:
        return 0
    slope = ((x - xm) * (y - ym)).sum() / denom
    # Normalize slope to fraction-of-price across the window (slope * n / mean).
    # This makes the threshold scale-invariant across timeframes since the
    # K values are tuned so each TF covers a similar real-time lookback.
    frac = slope * n / ym
    if frac > eps_frac:
        return 1
    if frac < -eps_frac:
        return -1
    return 0


def compute_trend_axis(
    bars_1h: Bars,
    bars_15m: Bars,
    bars_5m: Bars,
    ws_s_us: int,
    eps_frac: float = TREND_EPS_FRAC,
) -> int:
    """Return signed alignment in [-3, +3]."""
    v1h = _slope_vote(bars_1h, ws_s_us, TREND_K_BARS["1h"], eps_frac)
    v15 = _slope_vote(bars_15m, ws_s_us, TREND_K_BARS["15m"], eps_frac)
    v5 = _slope_vote(bars_5m, ws_s_us, TREND_K_BARS["5m"], eps_frac)
    return int(v1h + v15 + v5)


def trend_vote(alignment: int) -> int:
    """Collapse the [-3,+3] alignment to a {-1, 0, +1} axis vote."""
    if alignment >= TREND_MIN_ABS:
        return 1
    if alignment <= -TREND_MIN_ABS:
        return -1
    return 0
