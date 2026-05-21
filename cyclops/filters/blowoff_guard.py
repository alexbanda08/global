"""Blowoff-top exhaustion guard, regime-ASYMMETRIC.

Cyclops Day 3 cheat-code log:
    "Strong-trend overbought blowoff (BB touches upper band + RSI ≥ 60 +
     |MTF alignment| ≥ 3) = vertical exhaustion. On UP entries: hard SKIP.
     On DOWN entries: leave alone — those wins were working."

Asymmetric by design. The original Cyclops bot symmetrized this and lost
~10pp WR on down-trend setups; that's why we keep it directional.

Helpers below compute Bollinger Bands position and RSI on a closed-form
basis. The runner caches these once for the full 5m kline series.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from ..conventions import (
    BB_PERIOD,
    BB_STDEV,
    BLOWOFF_GUARD_DOWN,
    BLOWOFF_GUARD_UP,
    BLOWOFF_MIN_MTF_ABS,
    BLOWOFF_RSI_THRESHOLD,
    RSI_PERIOD,
)


# ---------------------------------------------------------------------------
# Indicators (closed-form, end-time-indexed)
# ---------------------------------------------------------------------------

def bollinger_position(
    closes: np.ndarray,
    end_us: np.ndarray,
    fire_us: int,
    period: int = BB_PERIOD,
    n_std: float = BB_STDEV,
) -> Tuple[str, float, float]:
    """Return (position, upper, lower) at the bar that ENDED at-or-before fire_us.

    position is one of: 'touch_upper' | 'touch_lower' | 'inside' | 'no_data'.
    Touch is defined as close ≥ upper or close ≤ lower; we use the bar's own
    close as the reference price (not the live tick) because the live price
    will already have moved by the time we evaluate.
    """
    if closes.size < period:
        return "no_data", float("nan"), float("nan")
    cutoff = int(np.searchsorted(end_us, int(fire_us), side="right"))
    if cutoff < period:
        return "no_data", float("nan"), float("nan")
    window = closes[cutoff - period:cutoff]
    ma = float(window.mean())
    sd = float(window.std(ddof=0))
    upper = ma + n_std * sd
    lower = ma - n_std * sd
    c = float(closes[cutoff - 1])
    if c >= upper:
        return "touch_upper", upper, lower
    if c <= lower:
        return "touch_lower", upper, lower
    return "inside", upper, lower


def rsi(
    closes: np.ndarray,
    end_us: np.ndarray,
    fire_us: int,
    period: int = RSI_PERIOD,
) -> float:
    """Standard Wilder RSI at the last bar ending at-or-before fire_us.

    Returns NaN if there's insufficient history.
    """
    if closes.size < period + 1:
        return float("nan")
    cutoff = int(np.searchsorted(end_us, int(fire_us), side="right"))
    if cutoff < period + 1:
        return float("nan")
    diffs = np.diff(closes[cutoff - period - 1:cutoff])
    gains = np.where(diffs > 0, diffs, 0.0)
    losses = np.where(diffs < 0, -diffs, 0.0)
    avg_gain = float(gains.mean())
    avg_loss = float(losses.mean())
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------

def is_blowoff_skip(
    direction: str,
    bb_position: str,
    rsi_value: float,
    mtf_abs: int,
    rsi_threshold: float = BLOWOFF_RSI_THRESHOLD,
    mtf_threshold: int = BLOWOFF_MIN_MTF_ABS,
    block_up: bool = BLOWOFF_GUARD_UP,
    block_down: bool = BLOWOFF_GUARD_DOWN,
) -> Tuple[bool, str]:
    """Return (should_skip, reason).

    direction must be 'Up' or 'Down'.
    """
    if bb_position == "no_data" or rsi_value != rsi_value:  # NaN-safe
        return False, "insufficient_indicator_history"

    blow_up = (
        bb_position == "touch_upper"
        and rsi_value >= rsi_threshold
        and mtf_abs >= mtf_threshold
    )
    blow_down = (
        bb_position == "touch_lower"
        and rsi_value <= (100.0 - rsi_threshold)
        and mtf_abs >= mtf_threshold
    )

    if direction == "Up" and block_up and blow_up:
        return True, f"blowoff_up_rsi{rsi_value:.1f}_mtf{mtf_abs}"
    if direction == "Down" and block_down and blow_down:
        return True, f"blowoff_down_rsi{rsi_value:.1f}_mtf{mtf_abs}"
    return False, "ok"
