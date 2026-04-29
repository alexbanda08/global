"""
V3 — Volume Breakout with added TREND VALIDATORS.

Base strategy (V2B) unchanged. Each V3 variant adds one of:
  A) Higher-timeframe 1d 200-EMA rising  (uses 4h bars, simulates 1d via window)
  B) ADX(14) > 20 trend-strength gate
  C) Rising 50-SMA slope (short-term trend speed)
  D) Composite trend score (A + B + C must all be true)

Same walk-forward params carry over from V2B:
  don_len=30, vol_mult=1.3, regime_len=150, tsl_atr=4.5

Bugs this is designed to fix:
  * 2018 -13.8% loss  (strategy fires in a macro bear)
  * 2022 -14.7% loss  (false breakouts during the LUNA/FTX decline)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return pd.Series(
        talib.ATR(df["high"].values, df["low"].values, df["close"].values, n),
        index=df.index,
    )


# ---------------------------------------------------------------------
# Shared core
# ---------------------------------------------------------------------
BASE_PARAMS = dict(
    don_len=30, vol_avg=20, vol_mult=1.3,
    regime_len=150, atr_len=14, sl_atr=2.0, tsl_atr=4.5,
)


def _base_signals(df: pd.DataFrame, p: dict) -> tuple[pd.Series, pd.Series, pd.Series]:
    hi = df["high"].rolling(p["don_len"]).max().shift(1)
    vavg = df["volume"].rolling(p["vol_avg"]).mean()
    vol_spike = df["volume"] > vavg * p["vol_mult"]
    regime = df["close"] > df["close"].rolling(p["regime_len"]).mean()
    base_entry = (df["close"] > hi) & vol_spike & regime
    base_exit = df["close"] < df["close"].rolling(p["regime_len"]).mean()
    return base_entry, base_exit, regime


def _pack(entries: pd.Series, exits: pd.Series, df: pd.DataFrame,
          p: dict) -> dict:
    atr = _atr(df, p["atr_len"])
    return dict(
        entries=entries, exits=exits,
        short_entries=None, short_exits=None,
        sl_stop=(atr * p["sl_atr"]) / df["close"],
        tsl_stop=(atr * p["tsl_atr"]) / df["close"],
    )


# ---------------------------------------------------------------------
# V3A — 1D 200-EMA rising filter (simulated with 6-bar-per-day on 4h)
# ---------------------------------------------------------------------
def v3a_htf_rising(df: pd.DataFrame, **kw) -> dict:
    p = {**BASE_PARAMS, **kw}
    e, x, _ = _base_signals(df, p)

    bars_per_day = _bars_per_day(df)
    # Daily close proxy: sample the 4h close every `bars_per_day` bars,
    # compute 200-EMA, then reindex forward.
    daily = df["close"].iloc[::bars_per_day]
    ema200 = daily.ewm(span=200, adjust=False).mean()
    # Rising = ema > ema.shift(1) on the daily series.
    rising_daily = (ema200 > ema200.shift(1)).reindex(df.index, method="ffill").fillna(False)
    entries = e & rising_daily
    return _pack(entries, x, df, p)


def _bars_per_day(df: pd.DataFrame) -> int:
    dt = df.index.to_series().diff().median()
    if pd.isna(dt):
        return 6
    return max(1, int(round(pd.Timedelta(days=1) / dt)))


# ---------------------------------------------------------------------
# V3B — ADX gate
# ---------------------------------------------------------------------
def v3b_adx(df: pd.DataFrame, adx_min: float = 20.0, **kw) -> dict:
    p = {**BASE_PARAMS, **kw}
    e, x, _ = _base_signals(df, p)
    adx = pd.Series(
        talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14),
        index=df.index,
    )
    entries = e & (adx > adx_min)
    return _pack(entries, x, df, p)


# ---------------------------------------------------------------------
# V3C — Short-term trend-speed (50-SMA rising)
# ---------------------------------------------------------------------
def v3c_slope(df: pd.DataFrame, slope_len: int = 50, **kw) -> dict:
    p = {**BASE_PARAMS, **kw}
    e, x, _ = _base_signals(df, p)
    sma = df["close"].rolling(slope_len).mean()
    rising = sma > sma.shift(1)
    entries = e & rising
    return _pack(entries, x, df, p)


# ---------------------------------------------------------------------
# V3D — Composite trend-score (all 3 gates)
# ---------------------------------------------------------------------
def v3d_composite(df: pd.DataFrame, adx_min: float = 20.0,
                  slope_len: int = 50, **kw) -> dict:
    p = {**BASE_PARAMS, **kw}
    e, x, _ = _base_signals(df, p)

    bars_per_day = _bars_per_day(df)
    daily = df["close"].iloc[::bars_per_day]
    ema200 = daily.ewm(span=200, adjust=False).mean()
    rising_daily = (ema200 > ema200.shift(1)).reindex(df.index, method="ffill").fillna(False)

    adx = pd.Series(
        talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14),
        index=df.index,
    )
    sma = df["close"].rolling(slope_len).mean()
    slope_rising = sma > sma.shift(1)

    gates = rising_daily & (adx > adx_min) & slope_rising
    entries = e & gates
    return _pack(entries, x, df, p)


# ---------------------------------------------------------------------
# V3E — Softer composite: score >= 2 of 3 (OR gate on validators)
# ---------------------------------------------------------------------
def v3e_score2of3(df: pd.DataFrame, adx_min: float = 20.0,
                  slope_len: int = 50, **kw) -> dict:
    p = {**BASE_PARAMS, **kw}
    e, x, _ = _base_signals(df, p)

    bars_per_day = _bars_per_day(df)
    daily = df["close"].iloc[::bars_per_day]
    ema200 = daily.ewm(span=200, adjust=False).mean()
    g1 = (ema200 > ema200.shift(1)).reindex(df.index, method="ffill").fillna(False)

    adx = pd.Series(
        talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14),
        index=df.index,
    )
    g2 = adx > adx_min

    sma = df["close"].rolling(slope_len).mean()
    g3 = sma > sma.shift(1)

    score = g1.astype(int) + g2.astype(int) + g3.astype(int)
    entries = e & (score >= 2)
    return _pack(entries, x, df, p)


STRATEGIES_V3: dict[str, callable] = {
    "V3A_htf1d_rising":   v3a_htf_rising,
    "V3B_adx_gate":       v3b_adx,
    "V3C_sma_slope":      v3c_slope,
    "V3D_composite_all":  v3d_composite,
    "V3E_score2of3":      v3e_score2of3,
}
