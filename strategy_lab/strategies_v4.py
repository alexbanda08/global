"""
V4 — New indicator library, each asset gets its own $10k.

Adds the user's newly-contributed indicators:
  * OTT (Optimized Trend Tracker) — Kivanc Ozbilgic / Anil Ozeksi
  * OTT Twin — two OTTs with different periods
  * Range-Filtered Kalman trend (AlgoAlpha)
  * Trend-Strength composite (AlgoAlpha-style)
Plus creative combos built from them.

Each strategy consumes a DataFrame with OHLCV and returns the usual
{entries, exits, sl_stop, tsl_stop} dict.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib


# ======================================================================
# Core helpers (duplicated from v2 to keep this module self-contained)
# ======================================================================
def _atr(df, n=14):
    return pd.Series(
        talib.ATR(df["high"].values, df["low"].values, df["close"].values, n),
        index=df.index,
    )


def _pack(entries, exits, df, atr_len=14, tsl_atr=3.0, sl_atr=None):
    atr = _atr(df, atr_len)
    out = dict(entries=entries, exits=exits,
               short_entries=None, short_exits=None,
               tsl_stop=(atr * tsl_atr) / df["close"])
    if sl_atr is not None:
        out["sl_stop"] = (atr * sl_atr) / df["close"]
    return out


# ======================================================================
# VAR moving average (Variable Index DynAvg — used by OTT)
# ======================================================================
def _var_ma(src: pd.Series, length: int = 2) -> pd.Series:
    valpha = 2.0 / (length + 1)
    diff = src.diff()
    vud  = diff.clip(lower=0)
    vdd  = (-diff).clip(lower=0)
    vUD  = vud.rolling(9).sum()
    vDD  = vdd.rolling(9).sum()
    vCMO = ((vUD - vDD) / (vUD + vDD)).fillna(0)
    # VAR[i] = α * |CMO|*src[i] + (1 - α*|CMO|) * VAR[i-1]
    k = (valpha * vCMO.abs()).clip(0, 1)
    out = np.zeros(len(src))
    prev = 0.0
    src_v = src.values
    k_v = k.values
    for i in range(len(src)):
        v = k_v[i] * src_v[i] + (1 - k_v[i]) * prev
        out[i] = v
        prev = v
    return pd.Series(out, index=src.index)


# ======================================================================
# OTT core — returns (MAvg, OTT line, direction)
# ======================================================================
def _ott(src: pd.Series, length: int = 2, pct: float = 1.4):
    ma = _var_ma(src, length)
    fark = ma * pct * 0.01

    n = len(src)
    long_stop  = (ma - fark).values.copy()
    short_stop = (ma + fark).values.copy()
    direction  = np.ones(n, dtype=np.int8)

    ma_v = ma.values
    for i in range(1, n):
        # trailing stops ratchet
        if ma_v[i] > long_stop[i-1]:
            long_stop[i] = max(long_stop[i], long_stop[i-1])
        if ma_v[i] < short_stop[i-1]:
            short_stop[i] = min(short_stop[i], short_stop[i-1])
        # direction flips
        prev = direction[i-1]
        if prev == -1 and ma_v[i] > short_stop[i-1]:
            direction[i] = 1
        elif prev == 1 and ma_v[i] < long_stop[i-1]:
            direction[i] = -1
        else:
            direction[i] = prev

    mt = np.where(direction == 1, long_stop, short_stop)
    ott = np.where(ma_v > mt, mt * (200 + pct) / 200, mt * (200 - pct) / 200)
    return ma, pd.Series(ott, index=src.index), pd.Series(direction, index=src.index)


# ======================================================================
# V4A — OTT classic (price crosses OTT long entry)
# ======================================================================
def v4a_ott(df, length: int = 2, pct: float = 1.4,
            regime_len: int = 200, tsl_atr: float = 3.5) -> dict:
    _, ott, direction = _ott(df["close"], length, pct)
    # shift ott[2] to match Pine's display: plot uses OTT[2] vs OTT[3]
    ott2 = ott.shift(2)
    ott3 = ott.shift(3)
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    entries = (df["close"] > ott2) & (df["close"].shift(1) <= ott2.shift(1)) & regime
    exits   = (df["close"] < ott2) & (df["close"].shift(1) >= ott2.shift(1))
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


# ======================================================================
# V4B — OTT Twin: fast OTT signals, slow OTT confirms direction
# ======================================================================
def v4b_ott_twin(df, fast_len: int = 2, fast_pct: float = 1.4,
                 slow_len: int = 30, slow_pct: float = 2.0,
                 tsl_atr: float = 3.5) -> dict:
    _, f_ott, f_dir = _ott(df["close"], fast_len, fast_pct)
    _, s_ott, s_dir = _ott(df["close"], slow_len, slow_pct)
    slow_up = s_dir > 0
    entries = (df["close"] > f_ott.shift(2)) & (df["close"].shift(1) <= f_ott.shift(3)) & slow_up
    exits   = (df["close"] < f_ott.shift(2)) & (df["close"].shift(1) >= f_ott.shift(3))
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


# ======================================================================
# V4C — Range-Filter + Kalman-smoothed trend (AlgoAlpha-inspired)
# ======================================================================
def _kalman_filter(src: pd.Series, alpha: float = 0.05) -> pd.Series:
    n = len(src)
    out = np.zeros(n)
    prev = src.iloc[0] if len(src) else 0
    src_v = src.values
    # Simple scalar Kalman: x = prev + α·(z − prev)
    for i in range(n):
        z = src_v[i]
        x = prev + alpha * (z - prev)
        out[i] = x
        prev = x
    return pd.Series(out, index=src.index)


def v4c_range_kalman(df, kalman_alpha: float = 0.05,
                     range_len: int = 100, range_mult: float = 2.5,
                     regime_len: int = 200, tsl_atr: float = 3.5) -> dict:
    # Smoothed price
    k = _kalman_filter(df["close"], kalman_alpha)
    # "Range" = average(|close - k|) over range_len, times multiplier
    abs_dev = (df["close"] - k).abs()
    rng = abs_dev.rolling(range_len).mean() * range_mult
    upper = k + rng
    lower = k - rng

    regime = df["close"] > df["close"].rolling(regime_len).mean()
    entries = (df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1)) & regime
    exits   = (df["close"] < lower) | (df["close"] < df["close"].rolling(regime_len).mean())
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


# ======================================================================
# V4D — Trend Strength composite (ADX + RSI + Aroon)
# ======================================================================
def v4d_trend_strength(df, adx_min: float = 22,
                       rsi_min: float = 52, aroon_min: float = 60,
                       regime_len: int = 150, tsl_atr: float = 3.5) -> dict:
    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    adx  = pd.Series(talib.ADX(h, l, c, 14), index=df.index)
    rsi  = pd.Series(talib.RSI(c, 14),        index=df.index)
    aroon_down, aroon_up = talib.AROON(h, l, 25)
    aroon_up   = pd.Series(aroon_up,   index=df.index)
    aroon_down = pd.Series(aroon_down, index=df.index)

    regime = df["close"] > df["close"].rolling(regime_len).mean()
    strong_trend = (adx > adx_min) & (rsi > rsi_min) & (aroon_up > aroon_min) & (aroon_up > aroon_down)

    fresh = strong_trend & (~strong_trend.shift(1).fillna(False))
    entries = fresh & regime
    exits   = (~strong_trend) | (df["close"] < df["close"].rolling(regime_len).mean())
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


# ======================================================================
# V4E — Creative: OTT trend + volume spike + Donchian entry
# ======================================================================
def v4e_ott_vol_donchian(df, ott_len: int = 2, ott_pct: float = 1.4,
                         don_len: int = 20, vol_avg: int = 20, vol_mult: float = 1.3,
                         regime_len: int = 200, tsl_atr: float = 3.5) -> dict:
    _, ott, direction = _ott(df["close"], ott_len, ott_pct)
    ott_up = direction > 0
    hi = df["high"].rolling(don_len).max().shift(1)
    vavg = df["volume"].rolling(vol_avg).mean()
    vol_spike = df["volume"] > vavg * vol_mult
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    entries = (df["close"] > hi) & vol_spike & regime & ott_up
    exits   = (~ott_up) | (df["close"] < df["close"].rolling(regime_len).mean())
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


# ======================================================================
# V4F — Creative: OTT up-trend PULLBACK entry (mean-rev in trend)
# ======================================================================
def v4f_ott_pullback(df, ott_len: int = 2, ott_pct: float = 1.4,
                     rsi_len: int = 14, rsi_buy_max: float = 45,
                     regime_len: int = 150, tsl_atr: float = 4.0) -> dict:
    _, ott, direction = _ott(df["close"], ott_len, ott_pct)
    ott_up = direction > 0
    rsi = pd.Series(talib.RSI(df["close"].values, rsi_len), index=df.index)
    regime = df["close"] > df["close"].rolling(regime_len).mean()

    # pullback signal: RSI has been below threshold and is now turning up while OTT is up
    pullback = (rsi < rsi_buy_max) & (rsi > rsi.shift(1))
    entries = pullback & ott_up & regime
    exits = (~ott_up) | (df["close"] < df["close"].rolling(regime_len).mean())
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


# ======================================================================
# V4G — Creative: Multi-TF OTT (higher-TF 1d trend gate on lower-TF entries)
# ======================================================================
def _bars_per_day(df):
    dt = df.index.to_series().diff().median()
    return max(1, int(round(pd.Timedelta(days=1) / dt))) if not pd.isna(dt) else 1


def v4g_mtf_ott(df, fast_len: int = 2, fast_pct: float = 1.4,
                htf_len: int = 2, htf_pct: float = 3.0,
                tsl_atr: float = 3.5) -> dict:
    _, _, fast_dir = _ott(df["close"], fast_len, fast_pct)
    # Daily OTT direction, broadcast back
    bpd = _bars_per_day(df)
    daily_close = df["close"].iloc[::bpd]
    _, _, htf_dir = _ott(daily_close, htf_len, htf_pct)
    htf_up = (htf_dir > 0).reindex(df.index, method="ffill").fillna(False)

    fresh_up = (fast_dir > 0) & (fast_dir.shift(1) <= 0)
    fresh_dn = (fast_dir < 0) & (fast_dir.shift(1) >= 0)
    entries = fresh_up & htf_up
    exits = fresh_dn
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


# ======================================================================
# V4H — Volatility-Regime switcher: trend in high vol, mean-rev in low vol
# ======================================================================
def v4h_vol_regime_switch(df, atr_len: int = 14, vol_lookback: int = 100,
                          regime_len: int = 200, tsl_atr: float = 3.5) -> dict:
    atr = _atr(df, atr_len)
    atr_pct = atr / df["close"]
    hi_vol = atr_pct > atr_pct.rolling(vol_lookback).median()

    # Trend mode signal
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    ema50 = df["close"].ewm(span=50, adjust=False).mean()
    trend_signal = (ema20 > ema50) & (ema20.shift(1) <= ema50.shift(1))

    # Mean-rev mode signal
    rsi = pd.Series(talib.RSI(df["close"].values, 14), index=df.index)
    mr_signal = (rsi.shift(1) < 30) & (rsi >= 30)

    regime = df["close"] > df["close"].rolling(regime_len).mean()
    entries = regime & ((hi_vol & trend_signal) | ((~hi_vol) & mr_signal))
    exits = df["close"] < df["close"].rolling(regime_len).mean()
    return _pack(entries, exits, df, tsl_atr=tsl_atr)


STRATEGIES_V4: dict[str, callable] = {
    "V4A_ott":              v4a_ott,
    "V4B_ott_twin":         v4b_ott_twin,
    "V4C_range_kalman":     v4c_range_kalman,
    "V4D_trend_strength":   v4d_trend_strength,
    "V4E_ott_vol_don":      v4e_ott_vol_donchian,
    "V4F_ott_pullback":     v4f_ott_pullback,
    "V4G_mtf_ott":          v4g_mtf_ott,
    "V4H_vol_regime":       v4h_vol_regime_switch,
}
