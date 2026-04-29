"""
D1 — HTF Regime x LTF Pullback.

Thesis: HTF regime suppresses false positives on LTF; LTF execution captures
better entry prices. Classic trend-plus-pullback structure improved by a
principled regime gate instead of a moving-average heuristic.

Source: Carver, "Systematic Trading" (2015) Ch.10 (multi-TF continuous
signals); Chan, "Algorithmic Trading" (2013) Ch.4 (MTF filters).

Entry (long-only V1):
    HTF 4h label in uptrend AND LTF 15m RSI(2) < rsi_threshold:
        LIMIT at LTF close * (1 - 0.05%)

Exits:
    HTF regime-flip out of uptrend  (via change_pt on forward-filled series)
    time-stop 16 bars (15m bars = 4h)
    engine's sl/tp  (safety nets)

Input contract: caller provides BOTH 15m and 4h DataFrames for the same
symbol + window. The function returns 15m-indexed signals.
"""
from __future__ import annotations

import pandas as pd

from regime import classify_regime, REGIME_4H_PRESET
from strategies.adaptive.common import (
    align_htf_regime_to_ltf,
    time_stop_signal,
    atr_pct,
    rsi,
)


def generate_signals(
    df_15m: pd.DataFrame,
    *,
    df_4h: pd.DataFrame,
    regime_config=REGIME_4H_PRESET,
    rsi_period: int = 2,
    rsi_threshold: float = 5.0,             # tightened from 10 after V1 matrix
    bb_period: int = 20,
    bb_sigma: float = 2.0,
    time_stop_bars: int = 16,
    entry_offset_pct: float = 0.0005,
    limit_valid_bars: int = 2,
    require_bullish_reversal: bool = True,  # new: entry bar must close above open
    require_bb_oversold: bool = True,       # new: close below BB_lower
) -> dict:
    if not df_15m.index.is_monotonic_increasing:
        raise ValueError("df_15m.index must be monotonic increasing")
    if not df_4h.index.is_monotonic_increasing:
        raise ValueError("df_4h.index must be monotonic increasing")

    # 1. HTF regime
    htf_regime = classify_regime(df_4h, config=regime_config)

    # 2. Forward-fill onto 15m grid (no lookahead — shifts by 1 HTF bar)
    ltf_regime = align_htf_regime_to_ltf(df_15m, htf_regime, htf_close_lag_bars=1)
    htf_label = ltf_regime["label"].astype(str)
    htf_in_uptrend = htf_label.isin(["strong_uptrend", "weak_uptrend"])

    # 3. LTF filter stack (all three must fire)
    close_15m = df_15m["close"]
    open_15m  = df_15m["open"]
    rsi_ltf = rsi(close_15m, period=rsi_period)
    rsi_gate = rsi_ltf < rsi_threshold

    bb_mid  = close_15m.rolling(bb_period).mean()
    bb_std  = close_15m.rolling(bb_period).std()
    bb_lwr  = bb_mid - bb_sigma * bb_std
    bb_gate = (close_15m < bb_lwr) if require_bb_oversold else pd.Series(True, index=close_15m.index)

    bull_rev = (close_15m > open_15m) & (close_15m > close_15m.shift(1))
    rev_gate = bull_rev if require_bullish_reversal else pd.Series(True, index=close_15m.index)

    entries = (htf_in_uptrend & rsi_gate & bb_gate & rev_gate).fillna(False).astype(bool)

    # 4. Exits: HTF-label change OUT of uptrend, or time-stop
    htf_left_uptrend = (~htf_in_uptrend) & htf_in_uptrend.shift(1).fillna(False)
    time_exit = time_stop_signal(entries, time_stop_bars)
    exits = (htf_left_uptrend | time_exit).fillna(False).astype(bool)

    return {
        "entries": entries,
        "exits":   exits,
        "short_entries": None,
        "short_exits":   None,
        "entry_limit_offset": pd.Series(entry_offset_pct, index=df_15m.index),
        "_meta": {
            "strategy_id": "d1_htf_regime_ltf_pullback",
            "htf_uptrend_pct": float(htf_in_uptrend.mean()),
            "rsi_oversold_pct": float(rsi_gate.mean()),
            "bb_oversold_pct":  float(bb_gate.mean()),
            "bull_reversal_pct": float(rev_gate.mean()),
            "combined_entry_pct": float(entries.mean()),
            "atr_pct_suggested_sl":  atr_pct(df_15m) * 1.5,
            "atr_pct_suggested_tp":  atr_pct(df_15m) * 3.0,
            "limit_valid_bars": limit_valid_bars,
        },
    }
