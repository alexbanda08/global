"""Unit tests for the P3 pre-flight guards: hours, reentry, blowoff."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from cyclops.filters.hours_guard import is_trading_hour
from cyclops.filters.reentry_lock import ReentryLock
from cyclops.filters.blowoff_guard import (
    bollinger_position,
    is_blowoff_skip,
    rsi,
)
from cyclops.filters.ob_manipulation import is_ob_manipulated


def _utc_ts(year, month, day, hour=12, minute=0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp())


# ---------------------------------------------------------------------------
# Hours guard
# ---------------------------------------------------------------------------

def test_hours_guard_allows_window_open():
    ts = _utc_ts(2026, 5, 6, 14)  # Wednesday 14:00 UTC
    ok, reason = is_trading_hour(ts, start_utc=13.0, stop_utc=21.0)
    assert ok is True
    assert reason == "ok"


def test_hours_guard_blocks_pre_open():
    ts = _utc_ts(2026, 5, 6, 10)
    ok, reason = is_trading_hour(ts, start_utc=13.0, stop_utc=21.0)
    assert ok is False
    assert "pre_open" in reason


def test_hours_guard_blocks_post_close():
    ts = _utc_ts(2026, 5, 6, 22)
    ok, reason = is_trading_hour(ts, start_utc=13.0, stop_utc=21.0)
    assert ok is False
    assert "post_close" in reason


def test_hours_guard_blocks_weekend():
    ts = _utc_ts(2026, 5, 9, 14)  # Saturday 2026-05-09
    ok, reason = is_trading_hour(ts, start_utc=13.0, stop_utc=21.0,
                                  weekend_off=True)
    assert ok is False
    assert "weekend" in reason


def test_hours_guard_pause_window():
    ts = _utc_ts(2026, 5, 6, 16, 30)  # 16:30 inside the pause
    ok, reason = is_trading_hour(ts, start_utc=13.0, stop_utc=21.0,
                                  pause_windows=[(16.0, 17.0)])
    assert ok is False
    assert "pause" in reason


def test_hours_guard_fractional_hours():
    ts = _utc_ts(2026, 5, 6, 8, 45)  # 8:45 UTC
    ok, _ = is_trading_hour(ts, start_utc=8.75, stop_utc=21.0)
    assert ok is True


# ---------------------------------------------------------------------------
# Reentry lock
# ---------------------------------------------------------------------------

def test_reentry_lock_first_call_allows():
    lock = ReentryLock(cooldown_sec=30)
    blocked, _ = lock.block_if_locked("slug-x", now_us=1_000_000_000)
    assert blocked is False


def test_reentry_lock_blocks_within_cooldown():
    lock = ReentryLock(cooldown_sec=30)
    lock.lock("slug-x", now_us=1_000_000_000)
    blocked, reason = lock.block_if_locked("slug-x", now_us=1_010_000_000)  # +10s
    assert blocked is True
    assert "reentry" in reason
    assert lock.n_blocked == 1


def test_reentry_lock_clears_after_cooldown():
    lock = ReentryLock(cooldown_sec=30)
    lock.lock("slug-x", now_us=1_000_000_000)
    blocked, _ = lock.block_if_locked("slug-x", now_us=1_031_000_000)  # +31s
    assert blocked is False


def test_reentry_lock_independent_per_slug():
    lock = ReentryLock(cooldown_sec=30)
    lock.lock("slug-a", now_us=1_000_000_000)
    blocked, _ = lock.block_if_locked("slug-b", now_us=1_005_000_000)
    assert blocked is False


# ---------------------------------------------------------------------------
# Blowoff indicators + guard
# ---------------------------------------------------------------------------

def test_bollinger_returns_no_data_on_short_series():
    closes = np.linspace(50_000, 51_000, 5)
    end_us = np.arange(5, dtype="int64") * 300 * 1_000_000
    pos, _u, _l = bollinger_position(closes, end_us, fire_us=10_000_000_000, period=20)
    assert pos == "no_data"


def test_bollinger_detects_touch_upper():
    # 19 flat bars + final spike => last close above upper band.
    closes = np.full(20, 50_000.0)
    closes[-1] = 50_500.0
    end_us = (np.arange(20) + 1) * 300 * 1_000_000
    fire_us = int(end_us[-1] + 1)  # AFTER the last bar ends
    pos, upper, _ = bollinger_position(closes, end_us, fire_us, period=20)
    assert pos == "touch_upper"


def test_rsi_at_extremes():
    end_us = (np.arange(20) + 1) * 300 * 1_000_000
    # 20 consecutive up-bars → only gains → RSI ≈ 100
    up_closes = np.linspace(50_000, 51_000, 20)
    val = rsi(up_closes, end_us, fire_us=int(end_us[-1] + 1), period=14)
    assert val > 95.0
    # 20 consecutive down-bars → only losses → RSI ≈ 0
    down_closes = np.linspace(51_000, 50_000, 20)
    val = rsi(down_closes, end_us, fire_us=int(end_us[-1] + 1), period=14)
    assert val < 5.0


def test_blowoff_skips_up_entry_at_overbought_blowoff():
    skip, reason = is_blowoff_skip(
        direction="Up",
        bb_position="touch_upper",
        rsi_value=70.0,
        mtf_abs=3,
    )
    assert skip is True
    assert "blowoff_up" in reason


def test_blowoff_allows_down_entry_at_overbought_blowoff():
    """Asymmetry: same indicators, Down side stays open by default."""
    skip, _ = is_blowoff_skip(
        direction="Down",
        bb_position="touch_upper",
        rsi_value=70.0,
        mtf_abs=3,
    )
    assert skip is False


def test_blowoff_allows_when_indicators_missing():
    skip, _ = is_blowoff_skip(
        direction="Up", bb_position="no_data", rsi_value=float("nan"), mtf_abs=3
    )
    assert skip is False


def test_blowoff_allows_when_mtf_is_weak():
    skip, _ = is_blowoff_skip(
        direction="Up", bb_position="touch_upper", rsi_value=70.0, mtf_abs=1
    )
    assert skip is False


# ---------------------------------------------------------------------------
# OB manipulation (deferred — only the no-data path is tested)
# ---------------------------------------------------------------------------

def test_ob_manipulation_returns_insufficient_data_by_default():
    skip, reason = is_ob_manipulated(None)
    assert skip is False
    assert reason == "insufficient_data"


def test_ob_manipulation_detects_large_span():
    # Two snapshots with vastly different L5 imbalance.
    bsz1 = np.array([1.0] * 5)
    asz1 = np.array([100.0] * 5)
    bsz2 = np.array([100.0] * 5)
    asz2 = np.array([1.0] * 5)
    skip, reason = is_ob_manipulated([(bsz1, asz1), (bsz2, asz2)], threshold=0.5)
    assert skip is True
    assert "ob_manipulated" in reason
