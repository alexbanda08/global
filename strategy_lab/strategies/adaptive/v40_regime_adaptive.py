"""
V40 Regime-Adaptive strategies.

All strategies take the same (df, regime_df) input contract. They consult the
`stable_regime` label (already forward-only + stability-filtered) and emit
long/short entry signals with regime-adapted parameters.

Functions:
  sig_v40_cci_adaptive(df, regime_df)
  sig_v40_st_adaptive(df, regime_df)
  sig_v40_switcher(df, regime_df)   -- fires CCI in LowVol, ST in MedVol, stands down in HighVol
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    sma = tp.rolling(n).mean()
    mad = tp.rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - sma) / (0.015 * mad.replace(0, np.nan))
    return cci


def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(n).mean()
    plus_di = 100 * pd.Series(plus, index=df.index).rolling(n).mean() / atr
    minus_di = 100 * pd.Series(minus, index=df.index).rolling(n).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.rolling(n).mean()


def _supertrend_flip(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.Series:
    hl2 = (df["high"] + df["low"]) / 2
    atr_tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1).rolling(n).mean()
    up = hl2 + mult * atr_tr
    dn = hl2 - mult * atr_tr
    trend = pd.Series(1, index=df.index)
    st = pd.Series(np.nan, index=df.index)
    for i in range(1, len(df)):
        if df["close"].iat[i] > st.iat[i-1] if not np.isnan(st.iat[i-1]) else False:
            trend.iat[i] = 1
        elif df["close"].iat[i] < st.iat[i-1] if not np.isnan(st.iat[i-1]) else False:
            trend.iat[i] = -1
        else:
            trend.iat[i] = trend.iat[i-1]
        st.iat[i] = dn.iat[i] if trend.iat[i] == 1 else up.iat[i]
    flip = trend.diff().fillna(0)
    return flip   # +2 = flip up (go long), -2 = flip down (go short)


# --------------------------------------------------------------- CCI adaptive
def sig_v40_cci_adaptive(df: pd.DataFrame, regime_df: pd.DataFrame,
                         adx_max: int = 22, adx_n: int = 14):
    """
    CCI reversion with regime-adapted thresholds:
      LowVol   -> (±100, 22) — more trades
      MedLowVol-> (±125, 22)
      MedVol   -> (±150, 22)
      MedHighVol-> (±175, 18)
      HighVol  -> (±200, 15) — fewer, more conservative
      Uncertain/Warming -> no trades
    """
    regime_labels = regime_df["label"].reindex(df.index).ffill()
    thresholds = {
        "LowVol":     (100, 22),
        "MedLowVol":  (125, 22),
        "MedVol":     (150, 22),
        "MedHighVol": (175, 18),
        "HighVol":    (200, 15),
    }
    cci = _cci(df, n=20)
    adx = _adx(df, n=adx_n)

    low = pd.Series(False, index=df.index)
    short = pd.Series(False, index=df.index)

    for lbl, (thr, adxm) in thresholds.items():
        mask = (regime_labels == lbl)
        # Long on extreme-down crossover
        cross_up = (cci.shift() < -thr) & (cci >= -thr)
        cross_dn = (cci.shift() > thr) & (cci <= thr)
        low |= mask & cross_up & (adx < adxm)
        short |= mask & cross_dn & (adx < adxm)

    return low.fillna(False), short.fillna(False)


# --------------------------------------------------------------- ST adaptive
def sig_v40_st_adaptive(df: pd.DataFrame, regime_df: pd.DataFrame,
                         ema_reg: int = 200):
    """
    SuperTrend flip with regime-adapted multiplier:
      LowVol   -> mult 2.5 (tighter)
      MedVol   -> mult 3.0 (standard)
      HighVol  -> mult 4.0 (wider)
      Uncertain-> no trades
    """
    regime_labels = regime_df["label"].reindex(df.index).ffill()
    ema200 = df["close"].ewm(span=ema_reg, adjust=False).mean()

    # Compute 3 SuperTrends concurrently; select signal per bar by regime
    flip_tight  = _supertrend_flip(df, n=10, mult=2.5)
    flip_mid    = _supertrend_flip(df, n=10, mult=3.0)
    flip_wide   = _supertrend_flip(df, n=10, mult=4.0)

    chosen_flip = pd.Series(0.0, index=df.index)
    map_mult = {"LowVol": flip_tight, "MedLowVol": flip_tight,
                "MedVol": flip_mid, "MedHighVol": flip_wide,
                "HighVol": flip_wide}
    for lbl, flip_series in map_mult.items():
        mask = (regime_labels == lbl)
        chosen_flip.loc[mask] = flip_series.loc[mask].values

    long  = (chosen_flip > 0) & (df["close"] > ema200)
    short = (chosen_flip < 0) & (df["close"] < ema200)
    return long.fillna(False), short.fillna(False)


# --------------------------------------------------------------- switcher
def sig_v40_switcher(df: pd.DataFrame, regime_df: pd.DataFrame):
    """
    Regime-switcher:
      LowVol  / MedLowVol  -> CCI reversion (mean-reverts well in calm)
      MedVol  / MedHighVol -> SuperTrend flip (best in trending)
      HighVol / Uncertain  -> STAND DOWN
    """
    regime_labels = regime_df["label"].reindex(df.index).ffill()

    cci_long, cci_short = sig_v40_cci_adaptive(df, regime_df)
    st_long,  st_short  = sig_v40_st_adaptive(df, regime_df)

    low_vol_mask = regime_labels.isin(["LowVol", "MedLowVol"])
    trend_mask   = regime_labels.isin(["MedVol", "MedHighVol"])

    long  = (cci_long & low_vol_mask) | (st_long & trend_mask)
    short = (cci_short & low_vol_mask) | (st_short & trend_mask)
    return long.fillna(False), short.fillna(False)
