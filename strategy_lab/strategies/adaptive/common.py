"""
Shared utilities for adaptive strategies.

The functions here are vectorized and trailing-only — no look-ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# HTF -> LTF regime forward-fill (no look-ahead)
# ---------------------------------------------------------------------
def align_htf_regime_to_ltf(
    ltf_df: pd.DataFrame,
    htf_regime: pd.DataFrame,
    htf_close_lag_bars: int = 1,
) -> pd.DataFrame:
    """
    Forward-fill a higher-timeframe regime DataFrame onto a lower-timeframe
    index, respecting the no-lookahead rule.

    A 4h bar dated 2024-01-01 04:00 has its CLOSE at 2024-01-01 08:00. Its
    label can only be consumed by 15m bars whose OPEN is > close-time. We
    model that by shifting the HTF index forward by one HTF bar (so it
    becomes the timestamp at which the label is first observable), then
    reindex with ffill.

    Parameters
    ----------
    ltf_df : pd.DataFrame
        The lower-timeframe OHLCV frame — we only need its index.
    htf_regime : pd.DataFrame
        Output of classify_regime() on the higher-timeframe data.
    htf_close_lag_bars : int
        Defensive extra shift in HTF bars, applied before the reindex.
        Default 1 makes sure we never consume the same-bar label.

    Returns
    -------
    pd.DataFrame
        Same columns as htf_regime, reindexed to ltf_df.index, ffilled.
    """
    if not isinstance(htf_regime.index, pd.DatetimeIndex):
        raise TypeError("htf_regime.index must be DatetimeIndex")
    if not isinstance(ltf_df.index, pd.DatetimeIndex):
        raise TypeError("ltf_df.index must be DatetimeIndex")

    htf_step = htf_regime.index.to_series().diff().median()
    shift_amount = htf_step * htf_close_lag_bars
    shifted = htf_regime.copy()
    shifted.index = shifted.index + shift_amount

    # Reindex to LTF with forward-fill — labels stay constant between HTF bars.
    aligned = shifted.reindex(ltf_df.index, method="ffill")
    return aligned


# ---------------------------------------------------------------------
# ATR as fraction of price (for engine sl/tsl which are percent)
# ---------------------------------------------------------------------
def atr_pct(df: pd.DataFrame, period: int = 14, smoothing: int = 20) -> float:
    """
    Recent ATR / recent close, smoothed over `smoothing` bars, as a single
    scalar used to set engine sl_stop / tsl_stop. Called at strategy-build
    time, not per bar.
    """
    # Reuse the engine's ATR function — re-implemented here to keep the
    # strategies module decoupled from engine internals.
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    atr_frac = (atr / close).tail(smoothing).median()
    return float(atr_frac) if pd.notna(atr_frac) else 0.02


# ---------------------------------------------------------------------
# Trailing highest-high since entry (for chandelier-style exit)
# ---------------------------------------------------------------------
def highest_high_since_entry(
    high: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
) -> pd.Series:
    """
    Vectorized running max of `high` that resets at every entry bar and
    stays frozen after an exit until the next entry.

    Used to compute a per-bar Chandelier level = running_high - k * ATR.
    """
    # Build a "position id" that increments at each entry; forward-filled
    # exits set it back to NaN.
    idx = high.index
    pos_id = np.full(len(high), np.nan)
    current_id = 0
    in_pos = False
    for i in range(len(high)):
        if entries.iloc[i] and not in_pos:
            current_id += 1
            in_pos = True
        if in_pos:
            pos_id[i] = current_id
        if exits.iloc[i] and in_pos:
            in_pos = False

    pos_id_series = pd.Series(pos_id, index=idx)
    # groupby pos_id → cummax; NaN bars (flat) get NaN
    running = high.groupby(pos_id_series).cummax()
    return running


# ---------------------------------------------------------------------
# Time-stop: exits N bars after entry (signal-based)
# ---------------------------------------------------------------------
def time_stop_signal(entries: pd.Series, n_bars: int) -> pd.Series:
    """
    Return a boolean Series that fires True exactly `n_bars` bars after each
    True value in `entries`. Combined with other exit signals via logical OR.
    """
    out = pd.Series(False, index=entries.index)
    entry_idxs = np.flatnonzero(entries.values)
    for i in entry_idxs:
        target = i + n_bars
        if target < len(out):
            out.iloc[target] = True
    return out


# ---------------------------------------------------------------------
# RSI2 — Connors-style 2-period RSI
# ---------------------------------------------------------------------
def rsi(close: pd.Series, period: int = 2) -> pd.Series:
    """Classic Wilder RSI, vectorized."""
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    ema_dn = down.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = ema_up / ema_dn.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))
