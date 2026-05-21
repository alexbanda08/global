"""Unit tests for the drawdown manager.

We synthesize balance trajectories rather than running the backtest, so the
tests stay deterministic and fast.
"""

from __future__ import annotations

import pytest

from cyclops.risk.drawdown_manager import DrawdownManager


T_START = 1_777_000_000          # arbitrary UTC second, mid-day
ONE_DAY = 86_400


def test_starts_unhalted():
    dm = DrawdownManager(start_balance=1000.0)
    dm.update(1000.0, T_START)
    halted, reason = dm.is_halted(1000.0)
    assert halted is False
    assert reason == "ok"


def test_peak_tracks_high_water():
    dm = DrawdownManager(start_balance=1000.0)
    dm.update(1050.0, T_START)
    dm.update(1020.0, T_START + 60)        # drop after new peak
    dm.update(1080.0, T_START + 120)       # new peak
    assert dm.peak == 1080.0


def test_drawdown_halt_triggers_at_threshold():
    dm = DrawdownManager(start_balance=1000.0, max_drawdown_pct=5.0)
    dm.update(1000.0, T_START)
    halted, _ = dm.is_halted(1000.0)
    assert not halted
    # Drop 5% from peak = 950 → halt
    dm.update(950.0, T_START + 60)
    halted, reason = dm.is_halted(950.0)
    assert halted
    assert "max_drawdown" in reason
    assert dm.n_pauses_drawdown == 1


def test_drawdown_recovery_target_is_halfway_back():
    # Disable daily-loss rule so we isolate the drawdown-recovery branch.
    dm = DrawdownManager(
        start_balance=1000.0, max_drawdown_pct=5.0, recovery_factor=0.5,
        daily_loss_limit_pct=99.0,
    )
    dm.update(1000.0, T_START)
    dm.update(940.0, T_START + 60)
    halted, _ = dm.is_halted(940.0)
    assert halted
    # Recovery target = peak * (1 - 0.5 * 5/100) = 1000 * 0.975 = 975
    # Still below → halted
    halted, _ = dm.is_halted(960.0)
    assert halted
    # Above 975 → resumes
    halted, _ = dm.is_halted(976.0)
    assert not halted


def test_daily_loss_halt_triggers_within_day():
    dm = DrawdownManager(
        start_balance=1000.0,
        max_drawdown_pct=99.0,   # disable drawdown rule for this test
        daily_loss_limit_pct=2.0,
    )
    dm.update(1000.0, T_START)
    halted, _ = dm.is_halted(1000.0)
    assert not halted
    # 2% daily loss = balance 980 → halt
    dm.update(979.0, T_START + 60)
    halted, reason = dm.is_halted(979.0)
    assert halted
    assert "daily_loss" in reason
    assert dm.n_pauses_daily == 1


def test_daily_halt_stays_locked_until_midnight():
    dm = DrawdownManager(
        start_balance=1000.0,
        max_drawdown_pct=99.0,
        daily_loss_limit_pct=2.0,
    )
    dm.update(1000.0, T_START)
    dm.update(979.0, T_START + 60)
    halted, _ = dm.is_halted(979.0)
    assert halted

    # Balance recovers WITHIN the same day — still halted.
    dm.update(1010.0, T_START + 7200)
    halted, reason = dm.is_halted(1010.0)
    assert halted
    assert reason == "daily_loss_locked"


def test_midnight_rolls_daily_halt():
    dm = DrawdownManager(
        start_balance=1000.0,
        max_drawdown_pct=99.0,
        daily_loss_limit_pct=2.0,
    )
    dm.update(1000.0, T_START)
    dm.update(979.0, T_START + 60)
    halted, _ = dm.is_halted(979.0)
    assert halted

    # Cross UTC midnight → new day → daily halt clears.
    dm.update(979.0, T_START + ONE_DAY)
    halted, reason = dm.is_halted(979.0)
    assert not halted
    assert reason == "ok"
    # And day_start_balance snapshots the new starting balance.
    assert dm.day_start_balance == 979.0


def test_both_halts_can_coexist_drawdown_wins():
    dm = DrawdownManager(
        start_balance=1000.0, max_drawdown_pct=5.0, daily_loss_limit_pct=2.0
    )
    dm.update(1000.0, T_START)
    dm.update(940.0, T_START + 60)
    halted, reason = dm.is_halted(940.0)
    assert halted
    # Drawdown is checked first.
    assert "drawdown" in reason


def test_stats_returns_counts():
    dm = DrawdownManager(start_balance=1000.0, max_drawdown_pct=5.0)
    dm.update(1000.0, T_START)
    dm.update(940.0, T_START + 60)
    dm.is_halted(940.0)
    s = dm.stats()
    assert s["start_balance"] == 1000.0
    assert s["peak"] == 1000.0
    assert s["n_pauses_drawdown"] == 1
    assert s["n_pauses_daily"] == 0
