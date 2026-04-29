"""
V12 — PULLBACK-IN-TREND + BOLLINGER-SQUEEZE entry families.

These are *replacements* for the breakout entries of V3B/V4C, not filters
on top of them.  Known from trading literature to have structurally higher
win rates than breakout entries because we buy oversold legs of up-trends
(V12A) or post-compression expansions with a clean stop (V12B).

All long-only, 4 h timeframe, advanced-simulator schema.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import talib


def _atr_pct(df, n=14):
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              df["close"].values, n), index=df.index)
    return atr / df["close"]


def _ladder(df, entries, exits,
            sl_r=1.5,
            tp1_r=1.0, tp1_frac=0.40,
            tp2_r=2.0, tp2_frac=0.30,
            tp3_r=3.5, tp3_frac=0.30,
            trail_r=2.5, atr_n=14):
    atr = _atr_pct(df, atr_n)
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=(atr * sl_r).clip(0.005, 0.15),
        tp1_pct=(atr * tp1_r).clip(0.003, 0.10), tp1_frac=tp1_frac,
        tp2_pct=(atr * tp2_r).clip(0.005, 0.20), tp2_frac=tp2_frac,
        tp3_pct=(atr * tp3_r).clip(0.008, 0.35), tp3_frac=tp3_frac,
        trail_pct=(atr * trail_r).clip(0.005, 0.15),
    )


# ---------------------------------------------------------------------
# V12A — Pullback-to-EMA20 in a 4h up-trend with RSI guard
# ---------------------------------------------------------------------
def v12a_pullback_trend(df: pd.DataFrame,
                       ema_trend: int = 200, ema_fast: int = 20,
                       slope_lookback: int = 20,
                       rsi_min: float = 42.0, rsi_max: float = 62.0,
                       pullback_depth_atr: float = 0.8) -> dict:
    """
    Entry:
      * 4h EMA(200) rising over last `slope_lookback` bars (trend is up)
      * Price dipped within `pullback_depth_atr` × ATR of EMA(20) in last 3 bars
      * Current bar is bullish (close > open, close > prior close)
      * RSI between rsi_min and rsi_max (not overbought, not oversold)
    Exit: price closes below EMA(50) OR trend slope turns negative.
    """
    close = df["close"]
    ef = close.ewm(span=ema_fast,  adjust=False).mean()
    em = close.ewm(span=50,        adjust=False).mean()
    et = close.ewm(span=ema_trend, adjust=False).mean()
    atr_p = _atr_pct(df)

    trend_up = et > et.shift(slope_lookback)
    # Distance of low to fast EMA (fraction of price)
    dist_to_ema = (df["low"] - ef) / close
    dipped = (dist_to_ema.abs() <= pullback_depth_atr * atr_p).rolling(3).max().astype(bool)

    rsi = pd.Series(talib.RSI(close.values, 14), index=df.index)
    rsi_ok = (rsi > rsi_min) & (rsi < rsi_max)

    bullish = (close > df["open"]) & (close > close.shift(1))

    entries = trend_up & dipped & rsi_ok & bullish & (close > ef)
    exits = (close < em) | (~trend_up)
    return _ladder(df, entries, exits)


# ---------------------------------------------------------------------
# V12B — Bollinger-Band squeeze breakout
# ---------------------------------------------------------------------
def v12b_bb_squeeze_break(df: pd.DataFrame,
                         bb_len: int = 20, bb_std: float = 2.0,
                         squeeze_pctile: float = 0.35,
                         squeeze_lookback: int = 60,
                         ema_trend: int = 100) -> dict:
    """
    Entry:
      * BB width is in the bottom squeeze_pctile of recent squeeze_lookback bars (compression)
      * Close breaks above upper BB (expansion + direction)
      * 4h trend up (close > EMA100)
    Exit: close crosses mid-BB (regression to mean).
    """
    close = df["close"]
    mid = close.rolling(bb_len).mean()
    std = close.rolling(bb_len).std()
    upper = mid + bb_std * std
    lower = mid - bb_std * std
    bw = (upper - lower) / mid.abs()

    squeezed = bw <= bw.rolling(squeeze_lookback).quantile(squeeze_pctile)

    et = close.ewm(span=ema_trend, adjust=False).mean()
    trend_up = close > et

    entries = squeezed.shift(1).fillna(False) & (close > upper) & trend_up
    exits = close < mid
    return _ladder(df, entries, exits,
                   sl_r=1.2, tp1_r=0.8, tp2_r=1.5, tp3_r=3.0, trail_r=2.0)


# ---------------------------------------------------------------------
# V12C — Two consecutive higher-lows (3-bar reversal pattern)
# ---------------------------------------------------------------------
def v12c_higher_lows(df: pd.DataFrame,
                    ema_trend: int = 100,
                    adx_min: float = 18.0) -> dict:
    """
    Entry:
      * 2 consecutive higher lows (low[-1] > low[-2] > low[-3])
      * Close > EMA(100) (above trend)
      * ADX > adx_min (trend present)
      * Current bar bullish (close > open)
    Exit: price crosses below EMA(50).
    """
    close = df["close"]
    ema50 = close.ewm(span=50,        adjust=False).mean()
    et = close.ewm(span=ema_trend, adjust=False).mean()
    adx = pd.Series(talib.ADX(df["high"].values, df["low"].values,
                              df["close"].values, 14), index=df.index)

    hl = (df["low"] > df["low"].shift(1)) & (df["low"].shift(1) > df["low"].shift(2))
    entries = hl & (close > et) & (adx > adx_min) & (close > df["open"])
    exits = close < ema50
    return _ladder(df, entries, exits,
                   sl_r=1.2, tp1_r=1.0, tp2_r=2.0, tp3_r=3.5, trail_r=2.0)


# ---------------------------------------------------------------------
# V12D — NR7 (narrow-range-7) breakout
# ---------------------------------------------------------------------
def v12d_nr7_break(df: pd.DataFrame,
                  nr_lookback: int = 7,
                  ema_trend: int = 100) -> dict:
    """
    NR7 = the bar whose range (high - low) is the smallest of the last
    `nr_lookback` bars.  A close above the NR7 bar's high (within the
    following 2 bars) in an up-trend is a reliable high-WR breakout.
    """
    rng = df["high"] - df["low"]
    nr = rng == rng.rolling(nr_lookback).min()
    nr_high = df["high"].where(nr).ffill()
    close = df["close"]
    et = close.ewm(span=ema_trend, adjust=False).mean()
    recent_nr = nr.rolling(3).max().astype(bool)  # NR7 within last 3 bars
    entries = recent_nr & (close > nr_high) & (close > et)
    exits = close < close.ewm(span=50, adjust=False).mean()
    return _ladder(df, entries, exits,
                   sl_r=1.2, tp1_r=1.0, tp2_r=2.2, tp3_r=4.0, trail_r=2.5)


STRATEGIES_V12 = {
    "V12A_pullback_trend":   v12a_pullback_trend,
    "V12B_bb_squeeze_break": v12b_bb_squeeze_break,
    "V12C_higher_lows":      v12c_higher_lows,
    "V12D_nr7_break":        v12d_nr7_break,
}
