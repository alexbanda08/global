"""
Strategies v2 — iteration on the v1 winners with:
  * ATR-based stop losses and trailing stops (via vbt's sl_stop / tsl_stop)
  * Regime gating on 1d HTF
  * Portfolio-ready: all long-only for directional bias in crypto bull era

The execution engine applies sl_stop/tsl_stop at bar-level intra-bar
(vbt simulates HIGH/LOW against the stop), which matches TradingView's
Strategy Tester behaviour when `intra_order_cancellation=true`.

We deliberately keep parameter counts SMALL to avoid curve-fitting.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib


# ---------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------
def _cross_over(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))

def _cross_under(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return pd.Series(
        talib.ATR(df["high"].values, df["low"].values, df["close"].values, n),
        index=df.index,
    )


# ---------------------------------------------------------------------
# V2A — EMA+ADX with ATR trailing stop
# ---------------------------------------------------------------------
def ema_trend_adx_v2(df: pd.DataFrame, fast: int = 20, slow: int = 50,
                     adx_len: int = 14, adx_min: float = 20.0,
                     atr_trail_mult: float = 3.0) -> dict:
    ef = df["close"].ewm(span=fast, adjust=False).mean()
    es = df["close"].ewm(span=slow, adjust=False).mean()
    adx = pd.Series(
        talib.ADX(df["high"].values, df["low"].values, df["close"].values, adx_len),
        index=df.index,
    )
    atr = _atr(df, adx_len)
    entries = _cross_over(ef, es) & (adx > adx_min)
    exits = _cross_under(ef, es)
    # trailing stop as ATR fraction of entry price
    tsl_stop = (atr * atr_trail_mult) / df["close"]
    return dict(entries=entries, exits=exits,
                short_entries=None, short_exits=None,
                tsl_stop=tsl_stop)


# ---------------------------------------------------------------------
# V2B — Volume Breakout + regime (hardened)
# ---------------------------------------------------------------------
def volume_breakout_v2(df: pd.DataFrame, don_len: int = 20,
                       vol_avg: int = 20, vol_mult: float = 1.5,
                       atr_len: int = 14, regime_len: int = 200,
                       sl_atr: float = 2.0, tsl_atr: float = 3.5) -> dict:
    hi = df["high"].rolling(don_len).max().shift(1)
    vavg = df["volume"].rolling(vol_avg).mean()
    vol_spike = df["volume"] > vavg * vol_mult
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    atr = _atr(df, atr_len)

    entries = (df["close"] > hi) & vol_spike & regime
    # exit handled by stops; keep a failsafe exit on regime break
    exits = df["close"] < df["close"].rolling(regime_len).mean()
    sl_stop = (atr * sl_atr) / df["close"]
    tsl_stop = (atr * tsl_atr) / df["close"]
    return dict(entries=entries, exits=exits,
                short_entries=None, short_exits=None,
                sl_stop=sl_stop, tsl_stop=tsl_stop)


# ---------------------------------------------------------------------
# V2C — Donchian breakout, regime-gated, ATR-trailed
# ---------------------------------------------------------------------
def donchian_v2(df: pd.DataFrame, lookback: int = 20, exit_lookback: int = 10,
                atr_len: int = 14, tsl_atr: float = 3.0,
                regime_len: int = 200) -> dict:
    hi = df["high"].rolling(lookback).max().shift(1)
    lo = df["low"].rolling(exit_lookback).min().shift(1)
    atr = _atr(df, atr_len)
    regime = df["close"] > df["close"].rolling(regime_len).mean()

    entries = (df["close"] > hi) & regime
    exits = df["close"] < lo
    tsl_stop = (atr * tsl_atr) / df["close"]
    return dict(entries=entries, exits=exits,
                short_entries=None, short_exits=None,
                tsl_stop=tsl_stop)


# ---------------------------------------------------------------------
# V2D — Supertrend with regime filter (kills counter-trend signals)
# ---------------------------------------------------------------------
def supertrend_v2(df: pd.DataFrame, atr_len: int = 10, mult: float = 3.0,
                  regime_len: int = 200) -> dict:
    atr = _atr(df, atr_len)
    hl2 = (df["high"] + df["low"]) / 2
    up = hl2 - mult * atr
    dn = hl2 + mult * atr

    n = len(df)
    trend = np.zeros(n, dtype=np.int8)
    final_up = up.values.copy()
    final_dn = dn.values.copy()
    c = df["close"].values

    for i in range(1, n):
        if c[i-1] > final_up[i-1]:
            final_up[i] = max(up.iloc[i], final_up[i-1])
        if c[i-1] < final_dn[i-1]:
            final_dn[i] = min(dn.iloc[i], final_dn[i-1])

        if trend[i-1] == 1 and c[i] < final_up[i]:
            trend[i] = -1
        elif trend[i-1] == -1 and c[i] > final_dn[i]:
            trend[i] = 1
        else:
            trend[i] = trend[i-1] if trend[i-1] != 0 else (1 if c[i] > hl2.iloc[i] else -1)

    trend_s = pd.Series(trend, index=df.index)
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    long_in  = ((trend_s == 1) & (trend_s.shift(1) == -1)) & regime
    long_out = (trend_s == -1) & (trend_s.shift(1) == 1)
    return dict(entries=long_in, exits=long_out,
                short_entries=None, short_exits=None)


# ---------------------------------------------------------------------
# V2E — Ensemble: EMA trend + Volume confirmation + ATR exit
# ---------------------------------------------------------------------
def ensemble_trend_vol(df: pd.DataFrame,
                       ema_fast: int = 20, ema_slow: int = 50,
                       regime_len: int = 200,
                       vol_avg: int = 20, vol_mult: float = 1.3,
                       atr_len: int = 14, tsl_atr: float = 3.5) -> dict:
    """Confluence entry: trend up + volume spike + price above regime."""
    ef = df["close"].ewm(span=ema_fast, adjust=False).mean()
    es = df["close"].ewm(span=ema_slow, adjust=False).mean()
    vavg = df["volume"].rolling(vol_avg).mean()
    vol_spike = df["volume"] > vavg * vol_mult
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    atr = _atr(df, atr_len)

    trend_flip = _cross_over(ef, es)
    entries = trend_flip & vol_spike & regime
    exits = _cross_under(ef, es) | (df["close"] < df["close"].rolling(regime_len).mean())
    tsl_stop = (atr * tsl_atr) / df["close"]
    return dict(entries=entries, exits=exits,
                short_entries=None, short_exits=None,
                tsl_stop=tsl_stop)


# ---------------------------------------------------------------------
# V2F — Gaussian Channel + ATR trail
# ---------------------------------------------------------------------
def gaussian_channel_v2(df: pd.DataFrame, length: int = 144, mult: float = 1.414,
                        atr_len: int = 14, tsl_atr: float = 3.0,
                        regime_len: int = 200) -> dict:
    src = (df["high"] + df["low"] + df["close"] + df["close"]) / 4
    alpha = 2.0 / (length + 1)
    f1 = src.ewm(alpha=alpha, adjust=False).mean()
    f2 = f1.ewm(alpha=alpha, adjust=False).mean()
    f3 = f2.ewm(alpha=alpha, adjust=False).mean()
    fil = f3.ewm(alpha=alpha, adjust=False).mean()
    dev = (src - fil).abs().ewm(alpha=alpha, adjust=False).mean() * mult
    upper = fil + dev

    rising = fil > fil.shift(1)
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    entries = _cross_over(df["close"], upper) & rising & regime
    exits = _cross_under(df["close"], fil)
    atr = _atr(df, atr_len)
    tsl_stop = (atr * tsl_atr) / df["close"]
    return dict(entries=entries, exits=exits,
                short_entries=None, short_exits=None,
                tsl_stop=tsl_stop)


STRATEGIES_V2: dict[str, callable] = {
    "V2A_ema_trend_adx":    ema_trend_adx_v2,
    "V2B_volume_breakout":  volume_breakout_v2,
    "V2C_donchian_v2":      donchian_v2,
    "V2D_supertrend_regime":supertrend_v2,
    "V2E_ensemble_trend_vol":ensemble_trend_vol,
    "V2F_gaussian_channel": gaussian_channel_v2,
}
