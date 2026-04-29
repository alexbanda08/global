"""
V9 — Hybrid strategies.

Take the ENTRIES from our proven V3B / V4C / HWR1 winners and apply the
MULTI-TP LADDER from the research synthesis.  This is the minimum-change,
maximum-learning experiment: we isolate whether multi-TP + ratcheting SL
adds value on top of entries we already trust.

Each hybrid produces the advanced-simulator schema.
"""
from __future__ import annotations
import pandas as pd
import talib

from strategy_lab.strategies_v2 import volume_breakout_v2
from strategy_lab.strategies_v3 import v3b_adx
from strategy_lab.strategies_v4 import v4c_range_kalman
from strategy_lab.strategies_v7 import hwr1_bb_meanrev


def _atr_pct(df, n=14):
    atr = pd.Series(talib.ATR(df["high"].values, df["low"].values,
                              df["close"].values, n), index=df.index)
    return atr / df["close"]


def _ladder_wrap(df: pd.DataFrame, legacy: dict,
                 sl_r: float = 1.5,
                 tp1_r: float = 1.0, tp1_frac: float = 0.40,
                 tp2_r: float = 2.0, tp2_frac: float = 0.30,
                 tp3_r: float = 3.5, tp3_frac: float = 0.30,
                 trail_r: float = 2.5,
                 atr_n: int = 14) -> dict:
    """
    Convert a legacy strategy signal into the multi-TP ladder schema.

    SL, TPs and trail are all expressed in ATR-multiples of entry price.
    sl_r × ATR/price defines the initial stop; TPs/trail scale off the same
    risk unit so R:R is predictable.
    """
    atr = _atr_pct(df, atr_n)
    sl  = (atr * sl_r).clip(lower=0.005, upper=0.15)
    tp1 = (atr * tp1_r).clip(lower=0.003, upper=0.10)
    tp2 = (atr * tp2_r).clip(lower=0.005, upper=0.20)
    tp3 = (atr * tp3_r).clip(lower=0.008, upper=0.35)
    trail = (atr * trail_r).clip(lower=0.005, upper=0.15)

    entries = legacy["entries"]
    # Fresh-signal-only to match the advanced-sim's "one position at a time".
    entries = entries & ~entries.astype("boolean").shift(1).fillna(False).astype(bool)
    # Exits: pass through the legacy exits if any; else empty series.
    exits = legacy.get("exits")
    if exits is None:
        exits = pd.Series(False, index=df.index)

    return dict(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
        sl_pct=sl,
        tp1_pct=tp1, tp1_frac=tp1_frac,
        tp2_pct=tp2, tp2_frac=tp2_frac,
        tp3_pct=tp3, tp3_frac=tp3_frac,
        trail_pct=trail,
    )


# ---------------------------------------------------------------------
def v9a_v3b_plus_ladder(df: pd.DataFrame) -> dict:
    leg = v3b_adx(df)
    return _ladder_wrap(df, leg)


def v9b_v4c_plus_ladder(df: pd.DataFrame) -> dict:
    leg = v4c_range_kalman(df)
    return _ladder_wrap(df, leg)


def v9c_v2b_plus_ladder(df: pd.DataFrame) -> dict:
    leg = volume_breakout_v2(df)
    return _ladder_wrap(df, leg)


def v9d_hwr1_plus_ladder(df: pd.DataFrame) -> dict:
    leg = hwr1_bb_meanrev(df)
    # Mean-reversion needs tighter TPs (price doesn't travel as far).
    return _ladder_wrap(df, leg,
                        sl_r=2.0,
                        tp1_r=0.8, tp1_frac=0.50,
                        tp2_r=1.5, tp2_frac=0.30,
                        tp3_r=2.5, tp3_frac=0.20,
                        trail_r=1.5)


# ---------------------------------------------------------------------
# Bonus: V3B entry with ASYMMETRIC R/R (bigger TP1 share, further TP3, wider trail)
# ---------------------------------------------------------------------
def v9e_v3b_aggressive_runner(df: pd.DataFrame) -> dict:
    leg = v3b_adx(df)
    return _ladder_wrap(df, leg,
                        sl_r=1.5,
                        tp1_r=0.8, tp1_frac=0.25,   # small TP1 take
                        tp2_r=1.8, tp2_frac=0.25,
                        tp3_r=4.0, tp3_frac=0.50,   # let big chunk run
                        trail_r=3.0)


STRATEGIES_V9 = {
    "V9A_v3b_ladder":        v9a_v3b_plus_ladder,
    "V9B_v4c_ladder":        v9b_v4c_plus_ladder,
    "V9C_v2b_ladder":        v9c_v2b_plus_ladder,
    "V9D_hwr1_ladder":       v9d_hwr1_plus_ladder,
    "V9E_v3b_aggressive":    v9e_v3b_aggressive_runner,
}
