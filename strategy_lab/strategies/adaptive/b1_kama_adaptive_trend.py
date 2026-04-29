"""
B1 — KAMA Adaptive Trend (ER-gated).

Thesis: Kaufman's KAMA self-throttles via Efficiency Ratio (ER = directional
movement / total movement). It flattens in chop and accelerates in trend,
cutting whipsaws without lag tuning.

Source: Kaufman, "Trading Systems and Methods" 6e Ch.17 (Wiley 2019).
Uses TA-Lib's KAMA (`talib.KAMA`) for the moving average.

Entry (long-only V1):
    ER > er_threshold (default 0.30) AND close crosses above KAMA:
        LIMIT at close * (1 - 0.05%)

Exits:
    tsl_stop (engine trailing stop)      — Chandelier approximation
    time-stop 100 bars
    regime-flip out of trend family      — safety net for bear regimes
"""
from __future__ import annotations

import numpy as np
import pandas as pd

try:
    import talib
    _HAS_TALIB = True
except ImportError:
    _HAS_TALIB = False

from regime import classify_regime, REGIME_4H_PRESET
from regime.features import adx as _adx
from strategies.adaptive.common import time_stop_signal, atr_pct


def _kama_fallback(close: pd.Series, period: int = 10,
                   fast: int = 2, slow: int = 30) -> pd.Series:
    """
    Pure-numpy KAMA if TA-Lib is missing. Matches Kaufman's original.
    """
    change = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period).sum()
    er = (change / volatility).clip(lower=0, upper=1).fillna(0)
    fastest = 2.0 / (fast + 1)
    slowest = 2.0 / (slow + 1)
    sc = (er * (fastest - slowest) + slowest) ** 2
    kama = pd.Series(np.nan, index=close.index)
    kama.iloc[period] = close.iloc[period]
    for i in range(period + 1, len(close)):
        prev = kama.iloc[i - 1]
        if pd.isna(prev):
            kama.iloc[i] = close.iloc[i]
        else:
            kama.iloc[i] = prev + sc.iloc[i] * (close.iloc[i] - prev)
    return kama


def _efficiency_ratio(close: pd.Series, period: int = 10) -> pd.Series:
    change = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period).sum()
    return (change / volatility).clip(lower=0, upper=1).fillna(0)


def generate_signals(
    df: pd.DataFrame,
    *,
    regime_config=REGIME_4H_PRESET,
    kama_period: int = 10,
    kama_fast: int = 2,
    kama_slow: int = 30,
    er_threshold: float = 0.40,               # raised from 0.30 after V1 matrix
    adx_min_entry: float = 25.0,              # new gate — only trade trending bars
    time_stop_bars: int = 100,
    entry_offset_pct: float = 0.0005,
    limit_valid_bars: int = 3,
    tsl_atr_mult: float = 4.5,                # widened from 3.0
) -> dict:
    close = df["close"]
    if _HAS_TALIB:
        kama = pd.Series(talib.KAMA(close.to_numpy(), timeperiod=kama_period),
                         index=close.index)
    else:
        kama = _kama_fallback(close, period=kama_period,
                              fast=kama_fast, slow=kama_slow)
    er = _efficiency_ratio(close, period=kama_period)
    adx14 = _adx(df["high"], df["low"], close, period=14)

    cross_up = (close > kama) & (close.shift(1) <= kama.shift(1))
    entries = (
        cross_up & (er > er_threshold) & (adx14 >= adx_min_entry)
    ).fillna(False).astype(bool)

    # Regime-flip exit — treat anything leaving the trend family as a stop.
    regime = classify_regime(df, config=regime_config)
    label = regime["label"].astype(str)
    in_trend = label.isin(["strong_uptrend", "weak_uptrend"])
    left_trend = (~in_trend) & in_trend.shift(1).fillna(False)

    # Time-stop
    time_exit = time_stop_signal(entries, time_stop_bars)

    exits = (left_trend | time_exit).fillna(False).astype(bool)

    return {
        "entries": entries,
        "exits":   exits,
        "short_entries": None,
        "short_exits":   None,
        "entry_limit_offset": pd.Series(entry_offset_pct, index=df.index),
        "_meta": {
            "strategy_id": "b1_kama_adaptive_trend",
            "er_mean": float(er.mean(skipna=True)),
            "er_threshold_hit_pct": float((er > er_threshold).mean()),
            "talib_available": _HAS_TALIB,
            "atr_pct_suggested_sl":  atr_pct(df) * 2.5,
            "atr_pct_suggested_tsl": atr_pct(df) * tsl_atr_mult,
            "adx_mean_at_entry": float(adx14[entries].mean()) if entries.any() else 0.0,
            "limit_valid_bars": limit_valid_bars,
        },
    }
