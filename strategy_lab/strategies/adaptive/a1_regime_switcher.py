"""
A1 — Regime-Switcher v1 (Trend -> MR -> Flat).

Thesis: distinct return-generating processes dominate across regimes; a hard
switch on an exogenous classifier avoids averaging edges across incompatible
market states.

Source: Ang & Timmermann, "Regime Changes and Financial Markets"
(NBER WP 17182, 2011) — https://www.nber.org/papers/w17182

V1 scope: long-only. Perp-short branch (downtrend) deferred to V2 after
Phase 0.5d ships limit-mode shorts.

Entry rules:
    regime in {strong_uptrend, weak_uptrend} AND confidence > conf_threshold:
        if close crosses above EMA(fast) AND EMA(fast) > EMA(slow):
            LIMIT at close * (1 - 0.05%)   # approximates "close - 0.1*ATR"
    regime in {sideways_low_vol, sideways_high_vol}:
        if close < BB_lower:
            LIMIT at close * (1 - 0.10%)   # approximates BB_lower - 0.05*ATR
    else:
        no entry

Exits (OR of):
    regime-flip out of the current trade family (trend family ↔ MR family)
    time-stop at time_stop_bars after entry
    engine's sl_stop / tsl_stop fire (safety net)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from regime import classify_regime, REGIME_4H_PRESET
from regime.features import ema as _ema
from strategies.adaptive.common import time_stop_signal, atr_pct


def generate_signals(
    df: pd.DataFrame,
    *,
    regime_config=REGIME_4H_PRESET,
    conf_threshold: float = 0.65,              # 0.60 too lax on ETH/SOL (V1); 0.75 too strict on BTC (V2)
    ema_fast: int = 20,
    ema_slow: int = 50,
    bb_period: int = 20,
    bb_sigma: float = 2.0,
    time_stop_bars: int = 48,
    entry_trend_offset_pct: float = 0.0005,
    entry_mr_offset_pct: float = 0.0010,
    limit_valid_bars: int = 3,
    sl_atr_mult: float = 3.0,                   # widened from 2.0 after V1
    tsl_atr_mult: float = 4.0,                  # widened from 3.0
) -> dict:
    close = df["close"]
    ema_f = _ema(close, ema_fast)
    ema_s = _ema(close, ema_slow)
    bb_mid = close.rolling(bb_period).mean()
    bb_std = close.rolling(bb_period).std()
    bb_lower = bb_mid - bb_sigma * bb_std

    regime = classify_regime(df, config=regime_config)
    label = regime["label"].astype(str)
    conf = regime["confidence"]

    in_trend = label.isin(["strong_uptrend", "weak_uptrend"])
    in_mr = label.isin(["sideways_low_vol", "sideways_high_vol"])

    # --- Trend-leg entry: bullish cross of close above EMA_fast, w/ EMA stack
    cross_up_ema_f = (close > ema_f) & (close.shift(1) <= ema_f.shift(1))
    ema_stack_up = ema_f > ema_s
    trend_entry = (
        in_trend & (conf > conf_threshold) & cross_up_ema_f & ema_stack_up
    )

    # --- MR-leg entry: close breaks below BB_lower (oversold)
    mr_entry = in_mr & (close < bb_lower)

    entries = (trend_entry | mr_entry).fillna(False).astype(bool)

    # Tag each entry's family so regime-flip exit knows what "out of family" means.
    # Use separate series so we can OR the exit conditions.
    in_trade_family_trend = in_trend.copy()
    in_trade_family_mr = in_mr.copy()

    # --- Regime-flip exit: we assume positions are taken from ONE family;
    # approximate "out of family" by: if family of the CURRENT label differs
    # from the prev-bar's label-family, fire exit.
    fam_now = np.where(in_trend, "trend",
              np.where(in_mr, "mr", "flat"))
    fam_prev = pd.Series(fam_now, index=df.index).shift(1).fillna("flat")
    family_change = pd.Series(fam_now, index=df.index) != fam_prev

    # --- Time-stop
    time_exit = time_stop_signal(entries, time_stop_bars)

    exits = (family_change | time_exit).fillna(False).astype(bool)

    # Different entry offset per leg — pass per-bar offsets to the engine.
    offset = pd.Series(0.0, index=df.index)
    offset.loc[trend_entry] = entry_trend_offset_pct
    offset.loc[mr_entry] = entry_mr_offset_pct

    return {
        "entries": entries,
        "exits": exits,
        "short_entries": None,
        "short_exits": None,
        "entry_limit_offset": offset,
        "_meta": {
            "strategy_id": "a1_regime_switcher",
            "family_share_trend": float(trend_entry.sum() / max(1, entries.sum())),
            "family_share_mr":    float(mr_entry.sum()    / max(1, entries.sum())),
            "atr_pct_suggested_sl":  atr_pct(df) * sl_atr_mult,
            "atr_pct_suggested_tsl": atr_pct(df) * tsl_atr_mult,
            "limit_valid_bars": limit_valid_bars,
        },
    }
