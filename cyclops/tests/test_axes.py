"""Unit tests for the three axis modules.

Synthetic inputs only — no canonical data dependency. We're verifying:
  trend.py   — slope direction → vote sign, abstain near zero
  levels.py  — pivot detection + p_up direction near support / resistance
  momentum.py — composite score reacts to imbalance + CVD + aggressor flow
"""

from __future__ import annotations

import numpy as np

from cyclops.axes import trend, levels, momentum
from cyclops.conventions import (
    LEVELS_MIN_CERTAINTY,
    MOMENTUM_CVD_CAP_USD,
    MOMENTUM_MIN_STRENGTH,
    TREND_EPS_FRAC,
    TREND_K_BARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bars(n: int, base_ts_us: int, period_s: int, prices) -> tuple[np.ndarray, np.ndarray]:
    """Build a (end_us, close) tuple. `prices` is array-like length n."""
    end_us = np.array(
        [base_ts_us + (i + 1) * period_s * 1_000_000 for i in range(n)],
        dtype="int64",
    )
    close = np.asarray(prices, dtype="float64")
    assert close.size == n
    return end_us, close


def _ohlc_bars(n: int, base_ts_us: int, period_s: int, highs, lows, closes):
    end_us = np.array(
        [base_ts_us + (i + 1) * period_s * 1_000_000 for i in range(n)],
        dtype="int64",
    )
    return (
        end_us,
        np.asarray(highs, dtype="float64"),
        np.asarray(lows, dtype="float64"),
        np.asarray(closes, dtype="float64"),
    )


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def test_trend_monotonic_up_votes_plus3():
    """Strong uptrend on all three TFs → alignment +3 → vote +1."""
    ws_us = 2_000_000_000_000  # arbitrary anchor
    # 1h: 30 bars rising 50000 → 51500 (+0.1%/bar)
    p_1h = np.linspace(50_000, 51_500, TREND_K_BARS["1h"] + 5)
    bars_1h = _bars(p_1h.size, ws_us - 36 * 3600 * 1_000_000, 3600, p_1h)
    # 15m: 110 bars rising 50000 → 51500
    p_15m = np.linspace(50_000, 51_500, TREND_K_BARS["15m"] + 10)
    bars_15m = _bars(p_15m.size, ws_us - 120 * 900 * 1_000_000, 900, p_15m)
    # 5m: 300 bars rising
    p_5m = np.linspace(50_000, 51_500, TREND_K_BARS["5m"] + 12)
    bars_5m = _bars(p_5m.size, ws_us - 320 * 300 * 1_000_000, 300, p_5m)

    alignment = trend.compute_trend_axis(bars_1h, bars_15m, bars_5m, ws_us)
    assert alignment == 3
    assert trend.trend_vote(alignment) == 1


def test_trend_monotonic_down_votes_minus3():
    ws_us = 2_000_000_000_000
    p_1h = np.linspace(50_000, 48_500, TREND_K_BARS["1h"] + 5)
    bars_1h = _bars(p_1h.size, ws_us - 36 * 3600 * 1_000_000, 3600, p_1h)
    p_15m = np.linspace(50_000, 48_500, TREND_K_BARS["15m"] + 10)
    bars_15m = _bars(p_15m.size, ws_us - 120 * 900 * 1_000_000, 900, p_15m)
    p_5m = np.linspace(50_000, 48_500, TREND_K_BARS["5m"] + 12)
    bars_5m = _bars(p_5m.size, ws_us - 320 * 300 * 1_000_000, 300, p_5m)

    alignment = trend.compute_trend_axis(bars_1h, bars_15m, bars_5m, ws_us)
    assert alignment == -3
    assert trend.trend_vote(alignment) == -1


def test_trend_flat_abstains():
    ws_us = 2_000_000_000_000
    rng = np.random.default_rng(0)
    # Noise around 50_000 with std << eps_frac * price = 0.0005 * 50_000 = 25.
    # We pick std ~ 0.5: tiny slope, should be 0.
    p_1h = 50_000 + rng.normal(0, 0.5, TREND_K_BARS["1h"] + 5)
    bars_1h = _bars(p_1h.size, ws_us - 36 * 3600 * 1_000_000, 3600, p_1h)
    p_15m = 50_000 + rng.normal(0, 0.5, TREND_K_BARS["15m"] + 10)
    bars_15m = _bars(p_15m.size, ws_us - 120 * 900 * 1_000_000, 900, p_15m)
    p_5m = 50_000 + rng.normal(0, 0.5, TREND_K_BARS["5m"] + 12)
    bars_5m = _bars(p_5m.size, ws_us - 320 * 300 * 1_000_000, 300, p_5m)

    alignment = trend.compute_trend_axis(bars_1h, bars_15m, bars_5m, ws_us)
    assert alignment == 0
    assert trend.trend_vote(alignment) == 0


def test_trend_mixed_alignment():
    """One TF up, others flat → alignment +1, vote +1 (threshold met)."""
    ws_us = 2_000_000_000_000
    # 1h: strong up
    p_1h = np.linspace(50_000, 51_500, TREND_K_BARS["1h"] + 5)
    bars_1h = _bars(p_1h.size, ws_us - 36 * 3600 * 1_000_000, 3600, p_1h)
    # 15m and 5m: tight noise around 50k → vote 0
    rng = np.random.default_rng(1)
    p_15m = 50_000 + rng.normal(0, 0.5, TREND_K_BARS["15m"] + 10)
    bars_15m = _bars(p_15m.size, ws_us - 120 * 900 * 1_000_000, 900, p_15m)
    p_5m = 50_000 + rng.normal(0, 0.5, TREND_K_BARS["5m"] + 12)
    bars_5m = _bars(p_5m.size, ws_us - 320 * 300 * 1_000_000, 300, p_5m)

    alignment = trend.compute_trend_axis(bars_1h, bars_15m, bars_5m, ws_us)
    assert alignment == 1
    assert trend.trend_vote(alignment) == 1


def test_trend_empty_bars_abstains():
    empty = (np.array([], dtype="int64"), np.array([], dtype="float64"))
    assert trend.compute_trend_axis(empty, empty, empty, 1_000_000_000) == 0


def test_trend_eps_used():
    """Just-under-eps window-fraction → 0; just-over → ±1."""
    ws_us = 2_000_000_000_000
    base = 50_000.0
    n = TREND_K_BARS["1h"]
    # frac (over window) = slope * n / mean ≈ (p[-1] - p[0]) / mean
    # → step_per_bar = eps_target * base / n
    step_below = TREND_EPS_FRAC * 0.5 * base / n
    p_below = base + np.arange(n) * step_below
    bars_below = _bars(n, ws_us - n * 3600 * 1_000_000, 3600, p_below)
    assert trend._slope_vote(bars_below, ws_us, n, TREND_EPS_FRAC) == 0

    step_above = TREND_EPS_FRAC * 2.0 * base / n
    p_above = base + np.arange(n) * step_above
    bars_above = _bars(n, ws_us - n * 3600 * 1_000_000, 3600, p_above)
    assert trend._slope_vote(bars_above, ws_us, n, TREND_EPS_FRAC) == 1


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------

def test_find_pivots_simple_peak_and_valley():
    # Use k=2 to make the test compact.
    highs = np.array([10, 11, 12, 15, 12, 11, 10, 8, 7, 9, 10, 12])
    lows = np.array([9, 10, 11, 14, 11, 10, 9, 7, 6, 8, 9, 11])
    res, sup = levels.find_pivots(highs, lows, k=2)
    # Peak at idx 3 (value 15); valley at idx 8 (value 6)
    assert 15.0 in res
    assert 6.0 in sup


def test_levels_p_up_near_support_is_above_half():
    """Price hugging support, far from resistance → p_up > 0.5."""
    # 15m bars: resistance ~51000, support ~49000. Current price 49100.
    n = 60
    base_us = 1_000_000_000 * 1_000_000  # arbitrary
    period_s = 900
    rng = np.random.default_rng(42)
    closes = 50_000 + rng.normal(0, 50, n)
    highs = closes + 30
    lows = closes - 30
    # Insert clear pivots:
    #   resistance: idx 20 high = 51_000
    #   support:    idx 40 low  = 49_000
    highs[20] = 51_000
    lows[40] = 49_000
    # ws_s_us must be AFTER bar n-1 ends.
    ws_us = int(base_us + (n + 1) * period_s * 1_000_000)
    bars = _ohlc_bars(n, base_us, period_s, highs, lows, closes)
    p_up = levels.compute_levels_p_up(bars, ws_us, current_px=49_100.0)
    assert p_up > 0.5, f"expected p_up > 0.5 near support, got {p_up}"
    assert levels.levels_vote(p_up) == 1


def test_levels_p_up_near_resistance_is_below_half():
    n = 60
    base_us = 1_000_000_000 * 1_000_000
    period_s = 900
    rng = np.random.default_rng(7)
    closes = 50_000 + rng.normal(0, 50, n)
    highs = closes + 30
    lows = closes - 30
    highs[20] = 51_000
    lows[40] = 49_000
    ws_us = int(base_us + (n + 1) * period_s * 1_000_000)
    bars = _ohlc_bars(n, base_us, period_s, highs, lows, closes)
    p_up = levels.compute_levels_p_up(bars, ws_us, current_px=50_950.0)
    assert p_up < 0.5, f"expected p_up < 0.5 near resistance, got {p_up}"
    assert levels.levels_vote(p_up) == -1


def test_levels_abstain_when_no_pivots():
    # Empty arrays → abstain
    empty = (
        np.array([], dtype="int64"),
        np.array([], dtype="float64"),
        np.array([], dtype="float64"),
        np.array([], dtype="float64"),
    )
    p_up = levels.compute_levels_p_up(empty, ws_s_us=1, current_px=50_000.0)
    assert p_up == 0.5
    assert levels.levels_vote(p_up) == 0


def test_levels_vote_threshold():
    assert levels.levels_vote(0.5 + LEVELS_MIN_CERTAINTY + 1e-6) == 1
    assert levels.levels_vote(0.5 + LEVELS_MIN_CERTAINTY - 1e-6) == 0
    assert levels.levels_vote(0.5 - LEVELS_MIN_CERTAINTY - 1e-6) == -1


# ---------------------------------------------------------------------------
# Momentum
# ---------------------------------------------------------------------------

def _ob_bundle_single(bid_sizes, ask_sizes, ts_us: int = 1_000):
    """Single OB snapshot, 25 levels deep. Convenience for tests."""
    bid_p = np.full((1, 25), 0.50)
    ask_p = np.full((1, 25), 0.50)
    bsz = np.zeros((1, 25))
    asz = np.zeros((1, 25))
    bsz[0, : len(bid_sizes)] = bid_sizes
    asz[0, : len(ask_sizes)] = ask_sizes
    return np.array([ts_us], dtype="int64"), ask_p, asz, bid_p, bsz


def test_momentum_bid_heavy_imbalance_votes_positive():
    """Top-5 bids 10x ask depth, no trades → score = 0.4 * imb → > threshold."""
    ob = _ob_bundle_single(bid_sizes=[100] * 5, ask_sizes=[10] * 5, ts_us=100)
    score = momentum.compute_momentum_score(
        ob, trades_ts_us=None, trades_size_usd=None, trades_side=None,
        fire_us=200,
    )
    # imb = (500 - 50) / 550 ≈ 0.818 → score ≈ 0.327
    assert score > 0
    assert momentum.momentum_vote(score) == 1


def test_momentum_ask_heavy_imbalance_votes_negative():
    ob = _ob_bundle_single(bid_sizes=[10] * 5, ask_sizes=[100] * 5, ts_us=100)
    score = momentum.compute_momentum_score(
        ob, trades_ts_us=None, trades_size_usd=None, trades_side=None,
        fire_us=200,
    )
    assert score < 0
    assert momentum.momentum_vote(score) == -1


def test_momentum_balanced_book_abstains():
    ob = _ob_bundle_single(bid_sizes=[50] * 5, ask_sizes=[50] * 5, ts_us=100)
    score = momentum.compute_momentum_score(
        ob, trades_ts_us=None, trades_size_usd=None, trades_side=None,
        fire_us=200,
    )
    assert abs(score) < MOMENTUM_MIN_STRENGTH
    assert momentum.momentum_vote(score) == 0


def test_momentum_strong_buy_flow_pushes_score_up():
    """Balanced book but heavy buy CVD → positive momentum."""
    ob = _ob_bundle_single(bid_sizes=[50] * 5, ask_sizes=[50] * 5, ts_us=100)
    # 10 buy trades, each = cap/10, all within the 30s window
    fire_us = 100_000_000
    ts = np.array([fire_us - 1_000_000 * i for i in range(10)], dtype="int64")
    size = np.full(10, MOMENTUM_CVD_CAP_USD / 10, dtype="float64")
    side = np.ones(10, dtype="int64")
    score = momentum.compute_momentum_score(
        ob,
        trades_ts_us=ts,
        trades_size_usd=size,
        trades_side=side,
        fire_us=fire_us,
    )
    # cvd_usd = cap → cvd_norm clipped to 1.0; agg = 1.0; imb = 0.
    # score = 0.3 + 0.3 = 0.6
    assert score > MOMENTUM_MIN_STRENGTH
    assert momentum.momentum_vote(score) == 1


def test_momentum_empty_ob_returns_zero():
    empty_ob = (
        np.array([], dtype="int64"),
        np.zeros((0, 25)),
        np.zeros((0, 25)),
        np.zeros((0, 25)),
        np.zeros((0, 25)),
    )
    score = momentum.compute_momentum_score(
        empty_ob, None, None, None, fire_us=1_000_000,
    )
    assert score == 0.0
    assert momentum.momentum_vote(score) == 0
