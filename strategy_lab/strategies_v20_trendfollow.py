"""
V20 — Modern trend-following strategies from 2026 research.

Sources (see WebSearch handbook):
- Heikin Ashi + SuperTrend trailing stop (BTC 1h classic; tested here on 4h)
- Dual-DEMA crossover with Ichimoku filter + ATR volatility guard
- OTT (Optimized Trend Tracker) with DEMA smoothing

All strategies:
  * 4h bars, Hyperliquid maker fees 0.015 %
  * long-only
  * advanced-simulator schema
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import talib


def _atr_pct(df, n=14):
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              df["close"].values, n), index=df.index)
    return atr / df["close"]


def _supertrend(df: pd.DataFrame, period=10, mult=3.0):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    atr = talib.ATR(h, l, c, period)
    hl2 = (h + l) / 2
    upper_basic = hl2 + mult * atr
    lower_basic = hl2 - mult * atr
    upper = np.full_like(c, np.nan); lower = np.full_like(c, np.nan)
    direction = np.zeros_like(c); line = np.full_like(c, np.nan)
    for i in range(len(c)):
        if i == 0 or np.isnan(atr[i]):
            upper[i] = upper_basic[i]; lower[i] = lower_basic[i]
            direction[i] = 1; line[i] = lower_basic[i]; continue
        upper[i] = upper_basic[i] if (upper_basic[i] < upper[i-1] or c[i-1] > upper[i-1]) else upper[i-1]
        lower[i] = lower_basic[i] if (lower_basic[i] > lower[i-1] or c[i-1] < lower[i-1]) else lower[i-1]
        if direction[i-1] == 1:
            direction[i] = -1 if c[i] < lower[i] else 1
            line[i] = upper[i] if direction[i] == -1 else lower[i]
        else:
            direction[i] = 1 if c[i] > upper[i] else -1
            line[i] = lower[i] if direction[i] == 1 else upper[i]
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def _heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha = pd.DataFrame(index=df.index)
    ha["close"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
    ha["open"] = 0.0
    ha["open"].iloc[0] = df["open"].iloc[0]
    for i in range(1, len(df)):
        ha["open"].iloc[i] = (ha["open"].iloc[i-1] + ha["close"].iloc[i-1]) / 2
    ha["high"] = pd.concat([df["high"], ha["open"], ha["close"]], axis=1).max(axis=1)
    ha["low"]  = pd.concat([df["low"],  ha["open"], ha["close"]], axis=1).min(axis=1)
    return ha


def _dema(s: pd.Series, n: int) -> pd.Series:
    return pd.Series(talib.DEMA(s.values, n), index=s.index)


def _ichimoku(df: pd.DataFrame, tenkan=9, kijun=26, senkou=52, displacement=26):
    h, l = df["high"], df["low"]
    tenkan_line = (h.rolling(tenkan).max() + l.rolling(tenkan).min()) / 2
    kijun_line = (h.rolling(kijun).max() + l.rolling(kijun).min()) / 2
    span_a = ((tenkan_line + kijun_line) / 2).shift(displacement)
    span_b = ((h.rolling(senkou).max() + l.rolling(senkou).min()) / 2).shift(displacement)
    return tenkan_line, kijun_line, span_a, span_b


def _ladder(df: pd.DataFrame, entries: pd.Series, exits: pd.Series,
            sl_r: float = 1.5, tp1_r: float = 1.0, tp2_r: float = 2.0,
            tp3_r: float = 3.5, trail_r: float = 2.5,
            tp1_frac: float = 0.40, tp2_frac: float = 0.30, tp3_frac: float = 0.30) -> dict:
    atr = _atr_pct(df)
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
def v20a_heikin_supertrend(df: pd.DataFrame,
                          st_period: int = 10, st_mult: float = 3.0,
                          ema_trend: int = 200) -> dict:
    """Heikin Ashi close vs SuperTrend line + HTF EMA filter."""
    ha = _heikin_ashi(df)
    st_line, st_dir = _supertrend(df, st_period, st_mult)
    ema200 = df["close"].ewm(span=ema_trend, adjust=False).mean()

    entries = (st_dir > 0) & (ha["close"] > st_line) & (df["close"] > ema200)
    exits   = (st_dir < 0) | (ha["close"] < st_line)
    return _ladder(df, entries, exits,
                   sl_r=1.5, tp1_r=1.0, tp2_r=2.2, tp3_r=4.0, trail_r=3.0)


def v20b_dema_ichimoku(df: pd.DataFrame,
                      dema_fast: int = 8, dema_slow: int = 21,
                      ema_floor: int = 50,
                      atr_max_pct: float = 0.06) -> dict:
    """DEMA(8) crosses DEMA(21) while above Ichimoku cloud and EMA50 floor."""
    close = df["close"]
    fast = _dema(close, dema_fast)
    slow = _dema(close, dema_slow)
    tenkan, kijun, span_a, span_b = _ichimoku(df)
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    ema50 = close.ewm(span=ema_floor, adjust=False).mean()
    atr_p = _atr_pct(df)

    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    bull = close > cloud_top
    vol_ok = atr_p < atr_max_pct
    entries = cross_up & bull & (close > ema50) & vol_ok
    exits = (fast < slow) | (close < ema50)
    return _ladder(df, entries, exits,
                   sl_r=1.5, tp1_r=1.0, tp2_r=2.0, tp3_r=3.5, trail_r=2.5)


def v20c_ott(df: pd.DataFrame,
             ma_len: int = 20, atr_mult: float = 2.0) -> dict:
    """
    OTT — Optimized Trend Tracker.
    MAvar = MA of close (DEMA here for responsiveness).
    LongStop = MAvar × (1 − atr_mult × ATR% / 100);
    Flip to 'UP' trend when close > prior LongStop.
    Entry: fresh flip UP; exit: flip DOWN.
    """
    close = df["close"]
    ma_var = _dema(close, ma_len)
    atr_p = _atr_pct(df)
    long_stop = ma_var * (1 - atr_mult * atr_p / 100.0)
    # Build trailing MAvar series
    ott = np.zeros(len(close))
    trend = np.zeros(len(close))
    ott[0] = ma_var.iloc[0]
    for i in range(1, len(close)):
        if np.isnan(ma_var.iloc[i]) or np.isnan(long_stop.iloc[i]):
            ott[i] = ott[i-1]; trend[i] = trend[i-1]; continue
        if close.iloc[i] > ott[i-1]:
            trend[i] = 1
            ott[i] = max(ott[i-1], long_stop.iloc[i])
        else:
            trend[i] = -1
            ott[i] = min(ott[i-1] if ott[i-1] > 0 else ma_var.iloc[i],
                         ma_var.iloc[i] * (1 + atr_mult * atr_p.iloc[i] / 100.0))
    trend_s = pd.Series(trend, index=close.index)
    fresh_up = (trend_s > 0) & (trend_s.shift(1) <= 0)
    ema200 = close.ewm(span=200, adjust=False).mean()
    entries = fresh_up & (close > ema200)
    exits = trend_s < 0
    return _ladder(df, entries, exits,
                   sl_r=1.5, tp1_r=1.0, tp2_r=2.0, tp3_r=3.5, trail_r=2.5)


def v20d_squeeze_ichimoku(df: pd.DataFrame,
                         bb_len: int = 20, bb_std: float = 2.0,
                         kc_len: int = 20, kc_mult: float = 1.5) -> dict:
    """Bollinger/Keltner squeeze + Ichimoku cloud break."""
    close = df["close"]
    mid = close.rolling(bb_len).mean()
    std = close.rolling(bb_len).std()
    bb_up = mid + bb_std * std; bb_dn = mid - bb_std * std
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              close.values, kc_len), index=df.index)
    kc_mid = close.ewm(span=kc_len, adjust=False).mean()
    kc_up = kc_mid + kc_mult * atr; kc_dn = kc_mid - kc_mult * atr
    squeezed = (bb_up < kc_up) & (bb_dn > kc_dn)

    _, kijun, span_a, span_b = _ichimoku(df)
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1)
    break_up = (close > cloud_top) & (close.shift(1) <= cloud_top.shift(1))

    entries = squeezed.shift(1).fillna(False) & break_up
    exits = close < kijun
    return _ladder(df, entries, exits,
                   sl_r=1.2, tp1_r=1.0, tp2_r=2.2, tp3_r=4.0, trail_r=2.5)


STRATEGIES_V20 = {
    "V20A_heikin_supertrend": v20a_heikin_supertrend,
    "V20B_dema_ichimoku":     v20b_dema_ichimoku,
    "V20C_ott":               v20c_ott,
    "V20D_squeeze_ichimoku":  v20d_squeeze_ichimoku,
}
