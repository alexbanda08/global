import math
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.build_signal_b import (
    realized_vol_daily, digital_fair_yes, isotonic_calibrate
)

def test_realized_vol_daily_simple():
    closes = pd.Series([100.0] * 1440)
    sig = realized_vol_daily(closes)
    assert sig < 1e-9

def test_realized_vol_daily_known():
    closes = pd.Series([100.0 * (1.001 ** i) for i in range(1440)])
    sig = realized_vol_daily(closes)
    expected = 0.001 * math.sqrt(1440)
    assert abs(sig - expected) < 1e-3

def test_digital_fair_yes_at_strike_returns_half():
    out = digital_fair_yes(s=100.0, s0=100.0, sigma_daily=0.02, t_seconds=300)
    assert abs(out - 0.5) < 1e-6

def test_digital_fair_yes_above_strike_returns_above_half():
    out = digital_fair_yes(s=101.0, s0=100.0, sigma_daily=0.02, t_seconds=300)
    assert out > 0.5

def test_digital_fair_yes_clipped():
    out = digital_fair_yes(s=200.0, s0=100.0, sigma_daily=0.02, t_seconds=300)
    assert 0.99 < out < 1.0

def test_isotonic_calibrate_monotone():
    raw = np.linspace(0.1, 0.9, 50)
    y = (raw + np.random.RandomState(0).normal(0, 0.05, 50) > 0.5).astype(int)
    cal = isotonic_calibrate(raw, y, raw_to_calibrate=raw)
    diffs = np.diff(cal)
    assert (diffs >= -1e-9).all()
