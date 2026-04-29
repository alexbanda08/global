"""
V11 — Regime-switching ENSEMBLE.

We've found:
  * V3B / V4C (trend-following) wins in bull/trending regimes
  * HWR1 (BB mean-reversion) wins in ranging / sideways regimes (XRP proof)
  * Neither is robust across ALL regimes

V11 classifies each bar's regime using price + volatility state, then
picks which sub-strategy to run at that time.  We use:

  Regime classifier (price-only, so it works for ALL 6 coins — not just
  BTC/ETH/SOL that have futures data):
    BULL  — close > EMA100  AND  ADX > 20        (strong up-trend)
    CHOP  — close near EMA100 (+/- 2%)  AND  ADX < 18  (ranging)
    BEAR  — close < EMA100  AND  EMA50 < EMA100  (down-trend) -> stay flat
    OTHER — transitional (no new entries)

  Sub-strategies:
    bull    -> V4C_range_kalman entries
    chop    -> HWR1_bb_meanrev entries (tighter stops, mean-rev targets)
    bear    -> no entries (long-only portfolio)

Output (advanced-simulator schema):
    entries = regime-aware union of V4C & HWR1 entries
    exits   = original V4C exits (trend break) + HWR1 exits (mid-band)
    sl / tp / trail set per the active regime at entry time
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import talib

from strategy_lab.strategies_v3 import v3b_adx
from strategy_lab.strategies_v4 import v4c_range_kalman
from strategy_lab.strategies_v7 import hwr1_bb_meanrev


def _atr_pct(df, n=14):
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              df["close"].values, n), index=df.index)
    return atr / df["close"]


def _regime(df: pd.DataFrame,
            ema_trend: int = 100, ema_fast: int = 50,
            adx_bull_min: float = 20.0, adx_chop_max: float = 18.0,
            chop_band: float = 0.02) -> pd.Series:
    """Returns a Series of strings: 'BULL' | 'CHOP' | 'BEAR' | 'OTHER'."""
    close = df["close"]
    ef = close.ewm(span=ema_fast,  adjust=False).mean()
    et = close.ewm(span=ema_trend, adjust=False).mean()
    adx = pd.Series(talib.ADX(df["high"].values, df["low"].values,
                              df["close"].values, 14), index=df.index)

    bull = (close > et) & (adx > adx_bull_min) & (ef > et)
    bear = (close < et) & (ef < et)
    # CHOP: price within chop_band of EMA100 AND ADX low
    near_ema = (close > et * (1 - chop_band)) & (close < et * (1 + chop_band))
    chop = near_ema & (adx < adx_chop_max) & ~bear

    regime = pd.Series("OTHER", index=df.index)
    regime[bull] = "BULL"
    regime[chop] = "CHOP"
    regime[bear] = "BEAR"
    return regime


def v11_regime_ensemble(df: pd.DataFrame) -> dict:
    regime = _regime(df)
    leg_trend = v4c_range_kalman(df)          # bull sub-strategy
    leg_mr    = hwr1_bb_meanrev(df)           # chop sub-strategy

    e_trend = leg_trend["entries"].astype(bool).fillna(False)
    e_mr    = leg_mr["entries"].astype(bool).fillna(False)

    # Active-sub-strategy entry
    entries = (e_trend & (regime == "BULL")) | (e_mr & (regime == "CHOP"))
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)

    # Record which regime fired for metadata (not used by sim)
    # Exits: combined signal-level exits
    x_trend = leg_trend.get("exits")
    x_mr    = leg_mr.get("exits")
    if x_trend is None: x_trend = pd.Series(False, index=df.index)
    if x_mr    is None: x_mr    = pd.Series(False, index=df.index)
    exits = (x_trend | x_mr).fillna(False).astype(bool)

    # Mixed SL/TP model:
    #  - When a bar is BULL at the entry moment we want wider TPs / TSL
    #    (capture big trends).
    #  - When CHOP: tight TPs (mean-rev targets).
    # We build two blended series and let the sim use them.
    atr = _atr_pct(df)

    # bull: SL 1.5 ATR, TP1 1.0 ATR, TP2 2.0 ATR, TP3 3.5 ATR, trail 2.5 ATR
    sl_bull  = (atr * 1.5).clip(0.005, 0.15)
    tp1_bull = (atr * 1.0).clip(0.003, 0.10)
    tp2_bull = (atr * 2.0).clip(0.005, 0.20)
    tp3_bull = (atr * 3.5).clip(0.008, 0.35)
    trail_bull = (atr * 2.5).clip(0.005, 0.15)
    # chop: SL 1.5 ATR, TP1 0.8 ATR, TP2 1.2 ATR, TP3 2.0 ATR, trail 1.2 ATR
    sl_chop  = (atr * 1.5).clip(0.005, 0.10)
    tp1_chop = (atr * 0.6).clip(0.003, 0.05)
    tp2_chop = (atr * 1.0).clip(0.004, 0.08)
    tp3_chop = (atr * 1.8).clip(0.005, 0.15)
    trail_chop = (atr * 1.2).clip(0.004, 0.08)

    chop_mask = (regime == "CHOP")
    sl    = sl_bull.where(~chop_mask,   sl_chop)
    tp1   = tp1_bull.where(~chop_mask,  tp1_chop)
    tp2   = tp2_bull.where(~chop_mask,  tp2_chop)
    tp3   = tp3_bull.where(~chop_mask,  tp3_chop)
    trail = trail_bull.where(~chop_mask, trail_chop)

    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits,
        sl_pct=sl,
        tp1_pct=tp1, tp1_frac=0.40,
        tp2_pct=tp2, tp2_frac=0.30,
        tp3_pct=tp3, tp3_frac=0.30,
        trail_pct=trail,
        # debug metadata:
        _regime=regime,
    )


STRATEGIES_V11 = {
    "V11_regime_ensemble": v11_regime_ensemble,
}
