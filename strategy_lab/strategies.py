"""
Strategy Library — 8 fundamentally different architectures.

Each function takes a DataFrame with OHLCV columns and returns a dict:
    {"entries": Series[bool], "exits": Series[bool],
     "short_entries": Series[bool] | None, "short_exits": Series[bool] | None}

Conventions:
  * All indicator columns computed from close/high/low only (never open of
    the *same* bar — open is for execution, not for signals).
  * No `.shift(-1)` or future-dependent windows. The engine shifts signals
    by +1 to enforce next-bar-open execution.
  * Keep every strategy long-only by default; add shorts only where the
    architecture naturally produces a symmetric signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import talib


# =====================================================================
# Helpers
# =====================================================================
def _cross_over(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_under(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def _htf_trend(df: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    """Slow regime filter: True when SMA(fast) > SMA(slow)."""
    return df["close"].rolling(fast).mean() > df["close"].rolling(slow).mean()


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    return pd.Series(
        talib.ATR(df["high"].values, df["low"].values, df["close"].values, length),
        index=df.index,
    )


# =====================================================================
# 1. EMA Trend + ADX filter (classic trend-follow, long-only)
# =====================================================================
def ema_trend_adx(df: pd.DataFrame, fast: int = 20, slow: int = 50,
                  adx_len: int = 14, adx_min: float = 20.0) -> dict:
    ef = df["close"].ewm(span=fast, adjust=False).mean()
    es = df["close"].ewm(span=slow, adjust=False).mean()
    adx = pd.Series(
        talib.ADX(df["high"].values, df["low"].values, df["close"].values, adx_len),
        index=df.index,
    )
    trend = ef > es
    entries = _cross_over(ef, es) & (adx > adx_min)
    exits = _cross_under(ef, es)
    return dict(entries=entries, exits=exits, short_entries=None, short_exits=None)


# =====================================================================
# 2. Donchian Breakout + ATR trail (turtle-style, long-only)
# =====================================================================
def donchian_breakout(df: pd.DataFrame, lookback: int = 20,
                      atr_len: int = 14, atr_mult: float = 2.5) -> dict:
    # use .shift(1) so we compare current close against yesterday's channel (no look-ahead)
    hi = df["high"].rolling(lookback).max().shift(1)
    lo = df["low"].rolling(lookback).min().shift(1)
    atr = _atr(df, atr_len)

    entries = df["close"] > hi
    # trailing stop — exit when close falls below entry_high - atr*mult
    # approximated as close < rolling_low_half or close < hi - atr*mult
    trail = (hi - atr * atr_mult)
    exits = (df["close"] < lo) | (df["close"] < trail)
    return dict(entries=entries, exits=exits, short_entries=None, short_exits=None)


# =====================================================================
# 3. RSI Mean Reversion — long-only, gated by 200 SMA uptrend
# =====================================================================
def rsi_mean_reversion(df: pd.DataFrame, rsi_len: int = 14,
                       buy_th: float = 30, sell_th: float = 55,
                       regime_len: int = 200) -> dict:
    rsi = pd.Series(talib.RSI(df["close"].values, rsi_len), index=df.index)
    regime = df["close"] > df["close"].rolling(regime_len).mean()
    entries = _cross_over(rsi, pd.Series(buy_th, index=df.index)) & regime
    exits = _cross_over(rsi, pd.Series(sell_th, index=df.index))
    return dict(entries=entries, exits=exits, short_entries=None, short_exits=None)


# =====================================================================
# 4. Bollinger + Keltner Squeeze breakout (vol-expansion, long-only)
# =====================================================================
def squeeze_breakout(df: pd.DataFrame, bb_len: int = 20, bb_std: float = 2.0,
                     kc_len: int = 20, kc_mult: float = 1.5,
                     momentum_len: int = 12) -> dict:
    basis = df["close"].rolling(bb_len).mean()
    dev = df["close"].rolling(bb_len).std(ddof=0)
    bb_up = basis + bb_std * dev
    bb_dn = basis - bb_std * dev

    atr = _atr(df, kc_len)
    kc_up = basis + kc_mult * atr
    kc_dn = basis - kc_mult * atr

    squeeze_on = (bb_up < kc_up) & (bb_dn > kc_dn)
    squeeze_off = (~squeeze_on) & squeeze_on.shift(1).fillna(False)

    # Momentum sign — simple linreg slope proxy: close - sma(close, N)
    mom = df["close"] - df["close"].rolling(momentum_len).mean()

    entries = squeeze_off & (mom > 0)
    # exit when momentum crosses back down, or 20 bars of exposure, or close crosses bb basis
    exits = _cross_under(mom, pd.Series(0.0, index=df.index)) | _cross_under(df["close"], basis)
    return dict(entries=entries, exits=exits, short_entries=None, short_exits=None)


# =====================================================================
# 5. MACD momentum with HTF confirmation (long+short)
# =====================================================================
def macd_htf(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9,
             htf_len: int = 200) -> dict:
    macd, sig, hist = talib.MACD(df["close"].values, fast, slow, signal)
    macd = pd.Series(macd, index=df.index)
    sig = pd.Series(sig, index=df.index)
    bull_regime = df["close"] > df["close"].rolling(htf_len).mean()
    bear_regime = df["close"] < df["close"].rolling(htf_len).mean()

    long_in  = _cross_over(macd, sig) & bull_regime
    long_out = _cross_under(macd, sig)
    short_in = _cross_under(macd, sig) & bear_regime
    short_out = _cross_over(macd, sig)
    return dict(entries=long_in, exits=long_out,
                short_entries=short_in, short_exits=short_out)


# =====================================================================
# 6. Supertrend (ATR Moneyline-inspired, long+short)
# =====================================================================
def supertrend(df: pd.DataFrame, atr_len: int = 10, mult: float = 3.0) -> dict:
    atr = _atr(df, atr_len)
    hl2 = (df["high"] + df["low"]) / 2
    up = (hl2 - mult * atr)
    dn = (hl2 + mult * atr)

    # Iterative trailing — can't be fully vectorised; tight python loop.
    n = len(df)
    trend = np.zeros(n, dtype=np.int8)     # +1 long, -1 short
    final_up = up.values.copy()
    final_dn = dn.values.copy()
    close = df["close"].values

    for i in range(1, n):
        if close[i-1] > final_up[i-1]:
            final_up[i] = max(up.iloc[i], final_up[i-1])
        if close[i-1] < final_dn[i-1]:
            final_dn[i] = min(dn.iloc[i], final_dn[i-1])

        if trend[i-1] == 1 and close[i] < final_up[i]:
            trend[i] = -1
        elif trend[i-1] == -1 and close[i] > final_dn[i]:
            trend[i] = 1
        else:
            trend[i] = trend[i-1] if trend[i-1] != 0 else (1 if close[i] > hl2.iloc[i] else -1)

    trend_s = pd.Series(trend, index=df.index)
    long_in  = (trend_s == 1) & (trend_s.shift(1) == -1)
    long_out = (trend_s == -1) & (trend_s.shift(1) == 1)
    short_in = long_out.copy()
    short_out = long_in.copy()
    return dict(entries=long_in, exits=long_out,
                short_entries=short_in, short_exits=short_out)


# =====================================================================
# 7. Gaussian Channel trend (simplified 4-pole Gaussian filter)
# =====================================================================
def gaussian_channel(df: pd.DataFrame, length: int = 144, mult: float = 1.414) -> dict:
    """Long when close > upper channel; exit when close < filter."""
    # 4-pole Gaussian weights approximation via repeated EMA
    src = (df["high"] + df["low"] + df["close"] + df["close"]) / 4   # ohlc4-ish
    alpha = 2.0 / (length + 1)
    f1 = src.ewm(alpha=alpha, adjust=False).mean()
    f2 = f1.ewm(alpha=alpha, adjust=False).mean()
    f3 = f2.ewm(alpha=alpha, adjust=False).mean()
    fil = f3.ewm(alpha=alpha, adjust=False).mean()
    dev = (src - fil).abs().ewm(alpha=alpha, adjust=False).mean() * mult
    upper = fil + dev

    rising = fil > fil.shift(1)
    entries = _cross_over(df["close"], upper) & rising
    exits = _cross_under(df["close"], fil)
    return dict(entries=entries, exits=exits, short_entries=None, short_exits=None)


# =====================================================================
# 8. Volume Breakout + Trend (from volumebrekout.pine idea, generalised)
# =====================================================================
def volume_breakout(df: pd.DataFrame, don_len: int = 20,
                    vol_avg: int = 20, vol_mult: float = 1.5,
                    atr_len: int = 14, regime_len: int = 200) -> dict:
    """Donchian-style breakout that REQUIRES a volume spike for entry,
    combined with a higher-timeframe regime filter."""
    hi = df["high"].rolling(don_len).max().shift(1)
    lo = df["low"].rolling(don_len).min().shift(1)
    vavg = df["volume"].rolling(vol_avg).mean()
    vol_spike = df["volume"] > vavg * vol_mult
    regime = df["close"] > df["close"].rolling(regime_len).mean()

    atr = _atr(df, atr_len)
    entries = (df["close"] > hi) & vol_spike & regime
    exits = (df["close"] < lo) | (df["close"] < (hi - 2.0 * atr))
    return dict(entries=entries, exits=exits, short_entries=None, short_exits=None)


# =====================================================================
# Registry
# =====================================================================
STRATEGIES: dict[str, callable] = {
    "01_ema_trend_adx":      ema_trend_adx,
    "02_donchian_breakout":  donchian_breakout,
    "03_rsi_mean_rev":       rsi_mean_reversion,
    "04_squeeze_breakout":   squeeze_breakout,
    "05_macd_htf":           macd_htf,
    "06_supertrend":         supertrend,
    "07_gaussian_channel":   gaussian_channel,
    "08_volume_breakout":    volume_breakout,
}
