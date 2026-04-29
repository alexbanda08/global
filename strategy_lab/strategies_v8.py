"""
V8 — Modern crypto swing strategies built on the advanced simulator.

Features blended from the 2026 research:
  * Triple SuperTrend confluence (ATR 10/1, 11/2, 12/3) — entry
  * Chandelier Exit trailing stop (ATR-adaptive)
  * Multi-TP ladder (TP1/TP2/TP3 at R-multiples, with % scale-outs)
  * Ratcheting SL (to breakeven at TP1, to TP1 at TP2)
  * Hull Moving Average + ADX regime filter
  * Volatility percentile classifier for adaptive sizing & stops

Each strategy returns a dict with the advanced-simulator schema:
    entries, exits,
    sl_pct (float | pd.Series),
    tp1_pct / tp2_pct / tp3_pct (float | pd.Series),
    trail_pct (pd.Series | None)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import talib


# ---------------------------------------------------------------------
# Shared indicators
# ---------------------------------------------------------------------
def atr_pct(df: pd.DataFrame, n: int = 14) -> pd.Series:
    atr = pd.Series(
        talib.ATR(df["high"].values, df["low"].values, df["close"].values, n),
        index=df.index,
    )
    return atr / df["close"]


def supertrend(df: pd.DataFrame, period: int, mult: float) -> tuple[pd.Series, pd.Series]:
    """Return (line, direction) where direction=1 bullish, -1 bearish."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = talib.ATR(h, l, c, period)
    hl2 = (h + l) / 2
    upper_basic = hl2 + mult * atr
    lower_basic = hl2 - mult * atr

    upper = np.full_like(c, np.nan)
    lower = np.full_like(c, np.nan)
    direction = np.zeros_like(c)
    line = np.full_like(c, np.nan)

    for i in range(len(c)):
        if i == 0 or np.isnan(atr[i]):
            upper[i] = upper_basic[i]
            lower[i] = lower_basic[i]
            direction[i] = 1
            line[i] = lower_basic[i]
            continue
        upper[i] = upper_basic[i] if (upper_basic[i] < upper[i-1] or c[i-1] > upper[i-1]) else upper[i-1]
        lower[i] = lower_basic[i] if (lower_basic[i] > lower[i-1] or c[i-1] < lower[i-1]) else lower[i-1]
        if direction[i-1] == 1:
            if c[i] < lower[i]:
                direction[i] = -1; line[i] = upper[i]
            else:
                direction[i] = 1;  line[i] = lower[i]
        else:
            if c[i] > upper[i]:
                direction[i] = 1;  line[i] = lower[i]
            else:
                direction[i] = -1; line[i] = upper[i]

    return (pd.Series(line, index=df.index),
            pd.Series(direction, index=df.index))


def hma(close: pd.Series, n: int) -> pd.Series:
    """Hull MA: WMA(2*WMA(close, n/2) - WMA(close, n), sqrt(n))."""
    half = max(2, n // 2)
    sq   = max(2, int(np.sqrt(n)))
    wma_half = talib.WMA(close.values, half)
    wma_full = talib.WMA(close.values, n)
    raw = 2 * wma_half - wma_full
    h = talib.WMA(raw, sq)
    return pd.Series(h, index=close.index)


def vol_percentile(df: pd.DataFrame, atr_n: int = 14, lookback: int = 200) -> pd.Series:
    atr = atr_pct(df, atr_n)
    return atr.rolling(lookback).rank(pct=True)


# ---------------------------------------------------------------------
# V8A — Triple SuperTrend + Chandelier trail + 3-TP ladder
# ---------------------------------------------------------------------
def v8a_supertrend_stack(df: pd.DataFrame,
                         p1: int = 10, m1: float = 1.0,
                         p2: int = 11, m2: float = 2.0,
                         p3: int = 12, m3: float = 3.0,
                         htf_ema: int = 200,
                         chandelier_n: int = 22, chandelier_mult: float = 3.0,
                         atr_for_tp: int = 14,
                         tp1_r: float = 1.0, tp1_frac: float = 0.40,
                         tp2_r: float = 2.0, tp2_frac: float = 0.30,
                         tp3_r: float = 3.5, tp3_frac: float = 0.30,
                         trail_atr_mult: float = 3.0) -> dict:
    close = df["close"]
    _, d1 = supertrend(df, p1, m1)
    _, d2 = supertrend(df, p2, m2)
    _, d3 = supertrend(df, p3, m3)
    htf_ok = close > close.ewm(span=htf_ema, adjust=False).mean()

    all_bull = (d1 > 0) & (d2 > 0) & (d3 > 0)
    fresh = all_bull & ~all_bull.shift(1).fillna(False).astype(bool)
    entries = fresh & htf_ok

    # Exit when slow SuperTrend flips bearish
    exits = d3 < 0

    # Initial SL = Chandelier Exit distance from entry
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              df["close"].values, chandelier_n), index=df.index)
    sl_dist = (atr * chandelier_mult / close).clip(lower=0.005, upper=0.20)

    # TP levels as fractions of entry price (not R).  Use ATR% for TP spacing.
    atr_tp = atr_pct(df, atr_for_tp)
    tp1 = (atr_tp * tp1_r).clip(lower=0.003, upper=0.12)
    tp2 = (atr_tp * tp2_r).clip(lower=0.005, upper=0.20)
    tp3 = (atr_tp * tp3_r).clip(lower=0.008, upper=0.30)
    trail = (atr_tp * trail_atr_mult).clip(lower=0.005, upper=0.15)

    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=sl_dist,
        tp1_pct=tp1, tp1_frac=tp1_frac,
        tp2_pct=tp2, tp2_frac=tp2_frac,
        tp3_pct=tp3, tp3_frac=tp3_frac,
        trail_pct=trail,
    )


# ---------------------------------------------------------------------
# V8B — HMA regime + ADX filter + R-based TP ladder
# ---------------------------------------------------------------------
def v8b_hma_adx(df: pd.DataFrame,
                hma_len: int = 55, hma_slope_n: int = 5,
                adx_min: float = 22.0,
                atr_n: int = 14, sl_atr_mult: float = 1.5,
                tp1_r: float = 1.5, tp1_frac: float = 0.40,
                tp2_r: float = 2.5, tp2_frac: float = 0.30,
                tp3_r: float = 4.0, tp3_frac: float = 0.30,
                trail_atr_mult: float = 2.5) -> dict:
    close = df["close"]
    h = hma(close, hma_len)
    h_slope = h.diff(hma_slope_n)
    adx = pd.Series(talib.ADX(df["high"].values, df["low"].values,
                              df["close"].values, 14), index=df.index)

    regime_ok = (close > h) & (h_slope > 0) & (adx > adx_min)
    entries = regime_ok & ~regime_ok.shift(1).fillna(False).astype(bool)
    # Exit when HMA slope turns down AND price below HMA
    exits = (h_slope < 0) & (close < h)

    atr = atr_pct(df, atr_n)
    sl_pct = (atr * sl_atr_mult).clip(lower=0.005, upper=0.15)
    # R-based TPs — multiplier × risk-per-trade
    tp1 = (sl_pct * tp1_r).clip(lower=0.003, upper=0.20)
    tp2 = (sl_pct * tp2_r).clip(lower=0.005, upper=0.30)
    tp3 = (sl_pct * tp3_r).clip(lower=0.008, upper=0.45)
    trail = (atr * trail_atr_mult).clip(lower=0.005, upper=0.15)

    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=sl_pct,
        tp1_pct=tp1, tp1_frac=tp1_frac,
        tp2_pct=tp2, tp2_frac=tp2_frac,
        tp3_pct=tp3, tp3_frac=tp3_frac,
        trail_pct=trail,
    )


# ---------------------------------------------------------------------
# V8C — Volatility-regime-adaptive Donchian breakout
# ---------------------------------------------------------------------
def v8c_vol_regime_donchian(df: pd.DataFrame,
                            don_len: int = 20, ema_trend: int = 100,
                            vol_lookback: int = 200,
                            atr_n: int = 14,
                            sl_atr_mult: float = 2.0,
                            tp1_r_hi: float = 1.0, tp2_r_hi: float = 2.0,
                            tp1_r_mid: float = 1.5, tp2_r_mid: float = 2.5, tp3_r_mid: float = 4.0,
                            tp1_frac: float = 0.40,
                            tp2_frac: float = 0.30,
                            tp3_frac: float = 0.30,
                            trail_atr_mult: float = 2.5) -> dict:
    close = df["close"]
    hi = df["high"].rolling(don_len).max().shift(1)
    et = close.ewm(span=ema_trend, adjust=False).mean()
    volp = vol_percentile(df, atr_n, vol_lookback)

    # Regime: trade only when vol is not "low" (avoid choppy dead markets)
    vol_ok = volp > 0.25
    trend_ok = (close > et) & (et > et.shift(10))

    entries = (close > hi) & trend_ok & vol_ok
    entries = entries & ~entries.shift(1).fillna(False).astype(bool)
    exits = close < et

    atr = atr_pct(df, atr_n)
    sl_pct = (atr * sl_atr_mult).clip(lower=0.005, upper=0.15)

    # Regime-aware TP ladder — tighter in high vol, wider in normal vol.
    hi_vol = volp > 0.66
    tp1_r = np.where(hi_vol, tp1_r_hi, tp1_r_mid)
    tp2_r = np.where(hi_vol, tp2_r_hi, tp2_r_mid)
    tp1 = pd.Series(sl_pct.values * tp1_r, index=df.index).clip(lower=0.003, upper=0.15)
    tp2 = pd.Series(sl_pct.values * tp2_r, index=df.index).clip(lower=0.005, upper=0.22)
    tp3 = (sl_pct * tp3_r_mid).clip(lower=0.008, upper=0.35)
    trail = (atr * trail_atr_mult).clip(lower=0.005, upper=0.15)

    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=sl_pct,
        tp1_pct=tp1, tp1_frac=tp1_frac,
        tp2_pct=tp2, tp2_frac=tp2_frac,
        tp3_pct=tp3, tp3_frac=tp3_frac,
        trail_pct=trail,
    )


STRATEGIES_V8 = {
    "V8A_supertrend_stack":  v8a_supertrend_stack,
    "V8B_hma_adx_regime":    v8b_hma_adx,
    "V8C_vol_donchian":      v8c_vol_regime_donchian,
}
