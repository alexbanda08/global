"""
V19 — Grid trading in sideways regimes.

Research basis (2026):
- Grid profitability requires a RANGE-BOUND market.  The killer is a range
  break: if price leaves the grid, you're left with inventory imbalance.
- Regime classifier: ADX(14) < 20 AND price within ±N×ATR of its 200-EMA.
- Range sizing: center ± k × ATR(14) with geometric spacing.
- Hard stop on close beyond range.
- Reset grid when center drifts or ADX > 25 (trend resumed).

V19 designs:

  V19A_static_grid_sideways
    Classic symmetric grid, 10 levels ± 3% from current price.
    ACTIVE only when ADX < 20 AND close within 3% of EMA200.
    FLAT otherwise.

  V19B_atr_grid_adaptive
    Grid sized dynamically = center ± 3 × ATR(14), 8 levels.
    Same regime gating but range re-centers when price drifts 1 × ATR.

Both use long-only (we buy at lower levels, sell when price tags the
next level up — inventory sits in cash otherwise).  Reported metrics
match the vbt-free simulator (per-position).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import talib


def _atr_pct(df, n=14):
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              df["close"].values, n), index=df.index)
    return atr / df["close"]


def _regime_sideways(df: pd.DataFrame,
                     ema_len: int = 200,
                     adx_max: float = 20.0,
                     band_pct: float = 0.03) -> pd.Series:
    close = df["close"]
    ema = close.ewm(span=ema_len, adjust=False).mean()
    adx = pd.Series(talib.ADX(df["high"].values, df["low"].values,
                              close.values, 14), index=df.index)
    in_band = (close > ema * (1 - band_pct)) & (close < ema * (1 + band_pct))
    return (adx < adx_max) & in_band


# ---------------------------------------------------------------------
def v19a_static_grid(df: pd.DataFrame,
                     n_levels: int = 10,
                     range_pct: float = 0.03,
                     tp_pct_per_level: float = 0.0065,  # ~0.65% per rung
                     sl_pct: float = 0.05,
                     ema_len: int = 200,
                     adx_max: float = 20.0) -> dict:
    """
    Simulate a discretised grid as a per-bar signal: entry at each lower
    grid step, exit at each upper grid step.  Returns a ladder-schema
    dict for the advanced simulator.
    """
    close = df["close"]
    regime = _regime_sideways(df, ema_len, adx_max, range_pct)
    center = close.ewm(span=ema_len, adjust=False).mean()

    # Grid approximation: enter long when close drops below center×(1 - step)
    # for any step = {1,2,3}×range_pct/n_levels, AND we're in sideways regime.
    step_pct = range_pct / max(1, n_levels // 2)
    entry_thresh = center * (1 - step_pct)       # one-rung-below-center trigger
    entries = (close < entry_thresh) & regime
    # Fresh signal only
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    # Exit when price reverts to center OR regime breaks
    exits = (close >= center) | (~regime)

    atr = _atr_pct(df)
    # Use tp ≈ 1 step (~0.65%) and SL = sl_pct (5%) hard stop.
    sl = pd.Series(sl_pct, index=df.index)
    tp1 = pd.Series(tp_pct_per_level, index=df.index)
    tp2 = pd.Series(tp_pct_per_level * 2, index=df.index)
    tp3 = pd.Series(tp_pct_per_level * 3, index=df.index)
    trail = atr * 1.5

    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=sl,
        tp1_pct=tp1, tp1_frac=0.40,
        tp2_pct=tp2, tp2_frac=0.30,
        tp3_pct=tp3, tp3_frac=0.30,
        trail_pct=trail,
    )


def v19b_atr_grid_adaptive(df: pd.DataFrame,
                            atr_mult_range: float = 3.0,
                            atr_mult_step: float = 0.75,
                            adx_max: float = 22.0,
                            ema_len: int = 200,
                            sl_atr: float = 4.0) -> dict:
    """ATR-based grid — range size adapts to realized vol."""
    close = df["close"]
    atr_abs = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                                   close.values, 14), index=df.index)
    center = close.ewm(span=ema_len, adjust=False).mean()
    regime = _regime_sideways(df, ema_len, adx_max, band_pct=0.04)

    # Entry: close dropped more than atr_mult_step × ATR below center in a
    # sideways regime, bounce back starting (close > prior close).
    below = close < (center - atr_mult_step * atr_abs)
    rebound = close > close.shift(1)
    entries = below & rebound & regime
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)

    # Exit: close reverted to center, or regime break, or price broke range.
    above_range = close > (center + atr_mult_range * atr_abs)
    below_range = close < (center - atr_mult_range * atr_abs)
    exits = (close >= center) | (~regime) | above_range | below_range

    atr_p = atr_abs / close
    sl = (atr_p * sl_atr).clip(0.005, 0.12)
    tp1 = (atr_p * atr_mult_step * 1.0).clip(0.003, 0.06)
    tp2 = (atr_p * atr_mult_step * 1.8).clip(0.005, 0.10)
    tp3 = (atr_p * atr_mult_step * 3.0).clip(0.008, 0.18)
    trail = (atr_p * 2.0).clip(0.005, 0.12)

    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=sl,
        tp1_pct=tp1, tp1_frac=0.50,
        tp2_pct=tp2, tp2_frac=0.30,
        tp3_pct=tp3, tp3_frac=0.20,
        trail_pct=trail,
    )


STRATEGIES_V19 = {
    "V19A_static_grid":     v19a_static_grid,
    "V19B_atr_grid":        v19b_atr_grid_adaptive,
}
