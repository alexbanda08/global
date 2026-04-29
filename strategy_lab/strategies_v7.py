"""
V7 — "High Win Rate" strategy family.

Goal: win rate >= 50 % in EVERY year (2022, 2023, 2024, 2025), even at the
cost of lower CAGR.  The trend-following family (V2B/V3B/V4C) structurally
runs at ~35-45 % because it relies on rare big winners; HWR flips the
distribution: many small wins, fewer losses.

Three candidates, all long-only, all on 4h bars:

  HWR1_bb_meanrev
    Buy the lower Bollinger band in a neutral-to-bullish HTF regime.
    Exit at the mid-band (mean-reversion target) or a 2-ATR stop.
    Expected: WR 55-65 %, avg win small.

  HWR2_rsi_stoch_oversold
    Buy RSI<25 + Stoch<20 in a bull regime, exit at RSI>55 or a
    fixed 3 % stop.  Port of V6 logic but regime-gated and with
    tighter exits.
    Expected: WR 55-65 %.

  HWR3_pullback_1to1
    In an established uptrend (50EMA > 200EMA rising), buy pullbacks
    to the 20-EMA.  Symmetric 1:1 ATR TP/SL.  The directional bias
    (trend is your friend) is the alpha; 1:1 payoff + tiny positive
    drift yields WR near 55 %.
    Expected: WR 52-58 %.

All three return the same schema as strategies_v2/3/4:
    dict(entries, exits, short_entries=None, short_exits=None,
         sl_stop=pd.Series or None,
         tsl_stop=pd.Series or None,
         tp_stop=pd.Series or None)
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import talib


def _atr_pct(df: pd.DataFrame, n: int = 14) -> pd.Series:
    atr = pd.Series(
        talib.ATR(df["high"].values, df["low"].values, df["close"].values, n),
        index=df.index,
    )
    return atr / df["close"]


# ---------------------------------------------------------------------
def hwr1_bb_meanrev(df: pd.DataFrame,
                   bb_len: int = 20, bb_std: float = 2.0,
                   ema_len: int = 200, atr_len: int = 14,
                   atr_sl_mult: float = 2.0,
                   max_hold_bars: int = 24) -> dict:
    close = df["close"]
    mid = close.rolling(bb_len).mean()
    std = close.rolling(bb_len).std()
    upper = mid + bb_std * std
    lower = mid - bb_std * std
    ema_htf = close.ewm(span=ema_len, adjust=False).mean()
    # Regime: price within -10 % of EMA (neutral) or above (bullish)
    regime_ok = close > ema_htf * 0.90
    # Buy when we touch the lower band in a valid regime
    entries = (close <= lower) & regime_ok & (close > close.shift(1).fillna(close))
    # First-signal-only to avoid triggering every bar while below band
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    # Exit at the mid-band (take-profit target) — handled via tp_stop-equivalent
    # Since BB mid is a moving target, we also add a signal exit:
    #   close crosses above mid for the first time after entry (mean-reversion done)
    exits = (close >= mid) & (close.shift(1) < mid.shift(1))
    # Safety time exit: if still in position after max_hold_bars, strategy's own
    # exit doesn't know about position state, so we rely on an ATR stop.
    atr = _atr_pct(df, atr_len)
    sl = (atr * atr_sl_mult).clip(lower=0.005, upper=0.15)
    return dict(entries=entries.fillna(False).astype(bool),
                exits=exits.fillna(False).astype(bool),
                short_entries=None, short_exits=None,
                sl_stop=sl, tsl_stop=None, tp_stop=None)


# ---------------------------------------------------------------------
def hwr2_rsi_stoch_oversold(df: pd.DataFrame,
                            rsi_len: int = 14,
                            rsi_buy_below: float = 25.0,
                            rsi_exit_above: float = 55.0,
                            stoch_k: int = 14, stoch_d: int = 3,
                            stoch_below: float = 20.0,
                            ema_len: int = 200,
                            sl_pct: float = 0.03) -> dict:
    close = df["close"]
    rsi = pd.Series(talib.RSI(close.values, rsi_len), index=df.index)
    hh = df["high"].rolling(stoch_k).max()
    ll = df["low"].rolling(stoch_k).min()
    stoch = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    ema_htf = close.ewm(span=ema_len, adjust=False).mean()
    regime_ok = close > ema_htf * 0.90

    entries = (rsi < rsi_buy_below) & (stoch < stoch_below) & regime_ok
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    exits   = rsi > rsi_exit_above
    # Hard SL fraction (used at entry time by simulator).
    return dict(entries=entries.fillna(False).astype(bool),
                exits=exits.fillna(False).astype(bool),
                short_entries=None, short_exits=None,
                sl_stop=float(sl_pct), tsl_stop=None, tp_stop=None)


# ---------------------------------------------------------------------
def hwr3_pullback_1to1(df: pd.DataFrame,
                      ema_fast: int = 20, ema_slow: int = 50,
                      ema_trend: int = 200,
                      atr_len: int = 14,
                      atr_tp_mult: float = 1.0,
                      atr_sl_mult: float = 1.0,
                      pullback_pct: float = 0.005) -> dict:
    close = df["close"]
    ef = close.ewm(span=ema_fast,  adjust=False).mean()
    es = close.ewm(span=ema_slow,  adjust=False).mean()
    et = close.ewm(span=ema_trend, adjust=False).mean()
    trend_ok = (es > et) & (et > et.shift(20))   # 50 > 200, and 200 rising

    # Pullback: price touched within pullback_pct of 20 EMA in the past 2 bars,
    # and now is rising back above the 20-EMA.
    near_ema = (df["low"] <= ef * (1 + pullback_pct)) & (df["low"] >= ef * (1 - pullback_pct))
    touched = near_ema.rolling(3).max().astype(bool)
    entries = touched & trend_ok & (close > close.shift(1))
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    # Signal exits: trend breaks (50 EMA crosses below 200 EMA).
    exits = (es < et)

    atr = _atr_pct(df, atr_len)
    tp = (atr * atr_tp_mult).clip(lower=0.003, upper=0.10)
    sl = (atr * atr_sl_mult).clip(lower=0.003, upper=0.10)
    return dict(entries=entries.fillna(False).astype(bool),
                exits=exits.fillna(False).astype(bool),
                short_entries=None, short_exits=None,
                sl_stop=sl, tsl_stop=None, tp_stop=tp)


# ---------------------------------------------------------------------
# Round-2 refinements based on first HWR hunt
# ---------------------------------------------------------------------
def hwr1b_bb_strict(df: pd.DataFrame,
                    bb_len: int = 20, bb_std: float = 2.5,
                    ema_len: int = 200, confirm_bars: int = 1) -> dict:
    """HWR1 with stricter entry (wider band + N-bar confirm) — quality over quantity."""
    close = df["close"]
    mid = close.rolling(bb_len).mean()
    std = close.rolling(bb_len).std()
    lower = mid - bb_std * std
    ema_htf = close.ewm(span=ema_len, adjust=False).mean()
    regime_ok = close > ema_htf * 0.90
    # Price closed below band at least confirm_bars times in the last 3 bars,
    # AND the current bar is a bullish reversal (close > prior close).
    below = close <= lower
    confirmed = below.rolling(3).sum() >= confirm_bars
    entries = confirmed & regime_ok & (close > close.shift(1))
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    exits = (close >= mid)
    return dict(entries=entries.fillna(False).astype(bool),
                exits=exits.fillna(False).astype(bool),
                short_entries=None, short_exits=None,
                sl_stop=0.04, tsl_stop=None, tp_stop=None)


def hwr3b_pullback_asym(df: pd.DataFrame,
                        ema_fast: int = 20, ema_slow: int = 50,
                        ema_trend: int = 200,
                        atr_len: int = 14,
                        atr_tp_mult: float = 0.7,
                        atr_sl_mult: float = 1.8,
                        pullback_pct: float = 0.005,
                        rsi_min: float = 40.0) -> dict:
    """
    Pullback-to-EMA with ASYMMETRIC R/R (TP tighter than SL): trades the
    high-probability leg of a trend continuation.  Win rate is structurally
    boosted because TP is closer.  Each loss is larger though, so we need
    ~60% WR for positive expectancy.
    """
    close = df["close"]
    ef = close.ewm(span=ema_fast,  adjust=False).mean()
    es = close.ewm(span=ema_slow,  adjust=False).mean()
    et = close.ewm(span=ema_trend, adjust=False).mean()
    trend_ok = (ef > es) & (es > et) & (et > et.shift(20))  # three-tier stack, rising
    rsi = pd.Series(talib.RSI(close.values, 14), index=df.index)

    near_ema = (df["low"] <= ef * (1 + pullback_pct)) & (df["low"] >= ef * (1 - pullback_pct))
    touched = near_ema.rolling(2).max().astype(bool)
    entries = touched & trend_ok & (close > close.shift(1)) & (rsi > rsi_min)
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    exits = es < et  # trend break

    atr = _atr_pct(df, atr_len)
    tp = (atr * atr_tp_mult).clip(lower=0.003, upper=0.08)
    sl = (atr * atr_sl_mult).clip(lower=0.005, upper=0.12)
    return dict(entries=entries.fillna(False).astype(bool),
                exits=exits.fillna(False).astype(bool),
                short_entries=None, short_exits=None,
                sl_stop=sl, tsl_stop=None, tp_stop=tp)


def hwr4_keltner_bounce(df: pd.DataFrame,
                        ema_len: int = 50, atr_len: int = 14,
                        kc_mult: float = 2.0,
                        trend_ema: int = 200) -> dict:
    """
    Keltner-channel bounce: bulls buy the lower KC in an uptrend.  Uses ATR
    (not stdev) so it adapts to realized vol. Exit at EMA midline.
    """
    close = df["close"]
    mid = close.ewm(span=ema_len, adjust=False).mean()
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values, close.values, atr_len),
                    index=df.index)
    lower = mid - kc_mult * atr
    ema_trend = close.ewm(span=trend_ema, adjust=False).mean()
    regime_ok = close > ema_trend * 0.95

    entries = (close <= lower) & regime_ok & (close > close.shift(1))
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    exits = close >= mid

    sl = (atr / close * 2.5).clip(lower=0.005, upper=0.12)
    return dict(entries=entries.fillna(False).astype(bool),
                exits=exits.fillna(False).astype(bool),
                short_entries=None, short_exits=None,
                sl_stop=sl, tsl_stop=None, tp_stop=None)


def hwr5_tight_tp_wide_sl(df: pd.DataFrame,
                          ema_fast: int = 20,
                          ema_trend: int = 100,
                          atr_len: int = 14,
                          atr_tp_mult: float = 0.5,
                          atr_sl_mult: float = 2.5,
                          rsi_min: float = 45.0) -> dict:
    """
    Ultra-asymmetric: TP = 0.5 ATR, SL = 2.5 ATR.  Structurally very high WR
    (70%+) if trend drift exists.  Each loss wipes out 5 wins, so profitable
    only if WR >= 83%.  We use tight entry filters so trades are rare.
    """
    close = df["close"]
    ef = close.ewm(span=ema_fast,  adjust=False).mean()
    et = close.ewm(span=ema_trend, adjust=False).mean()
    rsi = pd.Series(talib.RSI(close.values, 14), index=df.index)

    # Entry: in uptrend (price above fast-EMA above trend-EMA),
    # RSI recovers from below 50 to above 50 (momentum turning up).
    trend_ok = (close > ef) & (ef > et) & (et > et.shift(10))
    rsi_cross = (rsi > 50) & (rsi.shift(1) <= 50) & (rsi > rsi_min)
    entries = trend_ok & rsi_cross
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    exits = close < et

    atr = _atr_pct(df, atr_len)
    tp = (atr * atr_tp_mult).clip(lower=0.002, upper=0.05)
    sl = (atr * atr_sl_mult).clip(lower=0.008, upper=0.15)
    return dict(entries=entries.fillna(False).astype(bool),
                exits=exits.fillna(False).astype(bool),
                short_entries=None, short_exits=None,
                sl_stop=sl, tsl_stop=None, tp_stop=tp)


STRATEGIES_V7 = {
    "HWR1_bb_meanrev":          hwr1_bb_meanrev,
    "HWR2_rsi_stoch_oversold":  hwr2_rsi_stoch_oversold,
    "HWR3_pullback_1to1":       hwr3_pullback_1to1,
    "HWR1b_bb_strict":          hwr1b_bb_strict,
    "HWR3b_pullback_asym":      hwr3b_pullback_asym,
    "HWR4_keltner_bounce":      hwr4_keltner_bounce,
    "HWR5_tight_tp_wide_sl":    hwr5_tight_tp_wide_sl,
}
