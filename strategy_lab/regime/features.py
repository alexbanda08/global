"""
Shared feature engineering for regime voters.

All functions are vectorized (pandas / numpy) and obey the no-lookahead rule:
every rolling window is trailing (never centered). Output is aligned to the
input index and warmup bars contain NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# Basic price transforms
# ---------------------------------------------------------------------
def log_returns(close: pd.Series) -> pd.Series:
    """
    r_t = log(P_t / P_{t-1}). First value is NaN by construction.
    """
    return np.log(close).diff()


def abs_returns(close: pd.Series) -> pd.Series:
    return log_returns(close).abs()


# ---------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------
def realized_vol(close: pd.Series, window: int = 20, annualize_bars: int | None = None) -> pd.Series:
    """
    Rolling std of log returns. If `annualize_bars` is given (e.g. 365*6
    for 4h = ~2190), returns annualized vol in fractional terms.
    """
    r = log_returns(close)
    rv = r.rolling(window, min_periods=window).std()
    if annualize_bars is not None:
        rv = rv * np.sqrt(annualize_bars)
    return rv


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's ATR. Vectorized and trailing-only.
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


# ---------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def ema_slope(close: pd.Series, fast: int = 20, slow: int = 50) -> pd.Series:
    """
    Normalized slope between fast and slow EMAs, in units of (price / slow-EMA).
    Positive → uptrend, negative → downtrend. Scale-free across assets.
    """
    e_fast = ema(close, fast)
    e_slow = ema(close, slow)
    return (e_fast - e_slow) / e_slow


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's Average Directional Index. Output in [0, 100].
    Values > 25 signal a trending market; > 40 signal a strong trend.
    Vectorized.
    """
    up = high.diff()
    dn = -low.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    plus_dm_s = pd.Series(plus_dm, index=high.index)
    minus_dm_s = pd.Series(minus_dm, index=high.index)

    atr_ = atr(high, low, close, period=period)
    # Wilder smoothing for +DM / -DM
    plus_di = 100.0 * plus_dm_s.ewm(alpha=1.0 / period, adjust=False,
                                    min_periods=period).mean() / atr_
    minus_di = 100.0 * minus_dm_s.ewm(alpha=1.0 / period, adjust=False,
                                      min_periods=period).mean() / atr_
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


# ---------------------------------------------------------------------
# Vol quantile state (for sideways low vs high split)
# ---------------------------------------------------------------------
def vol_quantile_state(
    vol: pd.Series,
    low_q: float = 0.33,
    high_q: float = 0.66,
    expanding_min_bars: int = 500,
) -> pd.Series:
    """
    Classify each bar's vol as 'low' / 'normal' / 'high' using expanding-window
    quantiles computed from PAST bars only (no look-ahead). Warmup bars are
    labelled 'normal'.

    Returns
    -------
    pd.Series of pandas Categorical with categories ['low', 'normal', 'high'].
    """
    # Expanding quantiles computed at t use data through t-1 → lag by 1 bar.
    low_thresh  = vol.shift(1).expanding(min_periods=expanding_min_bars).quantile(low_q)
    high_thresh = vol.shift(1).expanding(min_periods=expanding_min_bars).quantile(high_q)

    state = pd.Series(index=vol.index, dtype="object")
    state.loc[:] = "normal"
    state.loc[vol < low_thresh] = "low"
    state.loc[vol > high_thresh] = "high"
    # Warmup bars keep "normal" (threshold will be NaN there).
    state.loc[low_thresh.isna() | high_thresh.isna()] = "normal"
    return state.astype(pd.CategoricalDtype(["low", "normal", "high"], ordered=True))


# ---------------------------------------------------------------------
# Feature bundle for HMM / ML voters
# ---------------------------------------------------------------------
def feature_frame(
    df: pd.DataFrame,
    *,
    vol_window: int = 20,
    trend_fast: int = 20,
    trend_slow: int = 50,
    adx_period: int = 14,
) -> pd.DataFrame:
    """
    Build the joint feature matrix consumed by the HMM / ML voters.
    Output columns: log_return, realized_vol, ema_slope, adx, vol_state.
    """
    close = df["close"]
    out = pd.DataFrame(index=df.index)
    out["log_return"]   = log_returns(close)
    out["realized_vol"] = realized_vol(close, window=vol_window)
    out["ema_slope"]    = ema_slope(close, fast=trend_fast, slow=trend_slow)
    out["adx"]          = adx(df["high"], df["low"], close, period=adx_period)
    out["vol_state"]    = vol_quantile_state(out["realized_vol"])
    return out
