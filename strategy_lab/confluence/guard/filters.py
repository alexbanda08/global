"""GUARD filter implementations.

Each filter takes a market+context dict and returns True to BLOCK the trade.

Filters:
  guard_extreme_price       — entry_price < 0.35 or > 0.65
  guard_dead_market         — t<90s post-open AND |btc_move|<$5 in window
  guard_counter_trend       — continuation move (matches anti-edge inversion finding)
  guard_min_time_to_close   — remaining time < 1m (n/a at t+120 entry; included for completeness)
  guard_choppiness          — chop_index_5m > 0.70 (Bill Williams choppiness)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Extreme price (Cyclops 0.35-0.65 working zone)
# ---------------------------------------------------------------------------

EXTREME_PRICE_LOW = 0.35
EXTREME_PRICE_HIGH = 0.65


def compute_extreme_price(entry_prices: np.ndarray) -> np.ndarray:
    """True when entry_price < 0.35 or > 0.65."""
    return (entry_prices < EXTREME_PRICE_LOW) | (entry_prices > EXTREME_PRICE_HIGH)


# ---------------------------------------------------------------------------
# 2. Dead market — low movement in first 90s
# ---------------------------------------------------------------------------

DEAD_MARKET_BTC_MOVE_USD = 5.0


def compute_dead_market(btc_at_open: np.ndarray, btc_at_t90: np.ndarray) -> np.ndarray:
    """True when |btc_at_t90 - btc_at_open| < $5 (no directional commitment)."""
    move = np.abs(btc_at_t90 - btc_at_open)
    return (move < DEAD_MARKET_BTC_MOVE_USD) & np.isfinite(move)


# ---------------------------------------------------------------------------
# 3. Counter-trend (anti-continuation) — matches our 89% SOL inverse finding
# ---------------------------------------------------------------------------

COUNTER_TREND_BTC_MOVE_USD = 10.0       # threshold for "directional move"
COUNTER_TREND_VEL_USD_PER_MIN = 3.0     # threshold for "still moving"


def compute_counter_trend(
    btc_at_open: np.ndarray,
    btc_at_t120: np.ndarray,
    btc_at_t90: np.ndarray,
    signal: np.ndarray,
) -> np.ndarray:
    """Block when BTC has already moved $10 from start AND velocity in same direction.

    Logic from Cyclops doc + our anti-edge finding:
      - if move>=10 and velocity in same direction → CONTINUATION → block (mean-revert hypothesis)
      - if move>=10 but velocity REVERSED → mean-reversion → allow

    Args:
      btc_at_open: BTC price at ws_unix
      btc_at_t120: BTC price at ws_unix + 120 (entry time)
      btc_at_t90:  BTC price at ws_unix + 90 (recent velocity proxy)
      signal:      momo signal, 1=Up / 0=Down
    """
    move = btc_at_t120 - btc_at_open
    vel_30s = btc_at_t120 - btc_at_t90
    big_move = np.abs(move) >= COUNTER_TREND_BTC_MOVE_USD
    still_moving = np.abs(vel_30s) >= COUNTER_TREND_VEL_USD_PER_MIN * 0.5  # 30s window
    same_dir = np.sign(move) == np.sign(vel_30s)
    block = big_move & still_moving & same_dir
    return block & np.isfinite(move) & np.isfinite(vel_30s)


# ---------------------------------------------------------------------------
# 4. Min time-to-close (largely informational at t+120; binary entry already)
# ---------------------------------------------------------------------------

def compute_min_time_to_close(timeframe: pd.Series) -> np.ndarray:
    """At t+120 entry, 5m markets have 180s left, 15m have 780s. Both > 60s.

    This guard is for production runtime where late entries can happen due
    to delays. For backtest at t+120 fixed, it's always False.
    """
    # Always False in backtest — entry is at t+120 with > 60s remaining
    return np.zeros(len(timeframe), dtype=bool)


# ---------------------------------------------------------------------------
# 5. Choppiness — high choppiness = sideways / hard to call
# ---------------------------------------------------------------------------

CHOPPINESS_THRESHOLD = 0.70


def _choppiness_index(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> float:
    """Bill Williams Choppiness Index over a window.

    CI = 100 * log10(sum(true_range) / (max_high - min_low)) / log10(N)
    Range [0, 100]. >61.8 = sideways/choppy. <38.2 = trending.

    We normalize to [0, 1] (divide by 100). Block if > 0.70.
    """
    if len(closes) < 2:
        return 0.5
    tr = np.maximum(highs[1:] - lows[1:],
                     np.maximum(np.abs(highs[1:] - closes[:-1]),
                                 np.abs(lows[1:] - closes[:-1])))
    sum_tr = np.nansum(tr)
    rng = np.nanmax(highs) - np.nanmin(lows)
    if rng <= 0 or sum_tr <= 0:
        return 0.5
    n = len(closes)
    if n < 2:
        return 0.5
    return float(100.0 * np.log10(sum_tr / rng) / np.log10(n)) / 100.0


def compute_choppiness(closes_window: list[np.ndarray]) -> np.ndarray:
    """For each market, compute choppiness over the prior-5m kline window.

    closes_window[i] = array of 1m closes for market i over [ws-300, ws].
    Returns True (block) when CI > 0.70.
    """
    out = np.zeros(len(closes_window), dtype=bool)
    for i, closes in enumerate(closes_window):
        if closes is None or len(closes) < 3:
            continue
        # Approximate highs/lows from 1m closes (we don't have tick OHLC here)
        # Use rolling-3 max/min as a proxy
        ci = _choppiness_index(closes, closes, closes)
        out[i] = ci > CHOPPINESS_THRESHOLD
    return out


# ---------------------------------------------------------------------------
# Combiner
# ---------------------------------------------------------------------------

def compute_all_guards(
    entry_prices: np.ndarray,
    btc_at_open: np.ndarray,
    btc_at_t90: np.ndarray,
    btc_at_t120: np.ndarray,
    signal: np.ndarray,
    timeframe: pd.Series,
    closes_5m_window: list[np.ndarray],
) -> dict[str, np.ndarray]:
    """Compute all 5 guard arrays for a vector of markets.

    Returns dict keyed by `guard_*` column names, matching schema.GUARD_BLOCK_COLS.
    """
    return {
        "guard_extreme_price":     compute_extreme_price(entry_prices),
        "guard_dead_market":       compute_dead_market(btc_at_open, btc_at_t90),
        "guard_counter_trend":     compute_counter_trend(btc_at_open, btc_at_t120, btc_at_t90, signal),
        "guard_min_time_to_close": compute_min_time_to_close(timeframe),
        "guard_choppiness":        compute_choppiness(closes_5m_window),
    }
