"""V52 Champion signal functions (Phase 8.1 Task 6).

Six pure-function signal generators per V52 spec §4. Each returns
``(long_signals: pd.Series[bool], short_signals: pd.Series[bool])`` aligned
to the input bar index.

Invariants (enforced by hypothesis tests in `test_v52_signals.py`):
  - **No look-ahead:** signal at index `i` uses ONLY bars `[0..i]`.
  - **Deterministic:** identical inputs → identical outputs.
  - **NaN-free output:** never emit NaN booleans (False on missing data).
  - Frozen ATR/CCI/MFI/BB conventions matching `perps_simulator*.py`.

Edge-case rules (RESEARCH Q5/Q6):
  - MFI: pos=neg=0 → 50; pos>0 neg=0 → 100; pos=0 neg>0 → 0; clip to [0,100].
  - VP rotation: <60 bars → False; all-zero-volume window → False.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _typical_price(bars: pd.DataFrame) -> pd.Series:
    return (bars["high"] + bars["low"] + bars["close"]) / 3.0


def _empty_pair(idx: pd.Index) -> tuple[pd.Series, pd.Series]:
    z = pd.Series(False, index=idx, dtype=bool)
    return z.copy(), z.copy()


# ---------------------------------------------------------------------
# §4.1 — CCI Extreme Reversal (V30)
# ---------------------------------------------------------------------


def sig_cci_extreme(
    bars: pd.DataFrame, period: int = 20, threshold: float = 100.0
) -> tuple[pd.Series, pd.Series]:
    """Long when CCI crosses up through -threshold; short when crosses down through +threshold."""
    if len(bars) < period + 2:
        return _empty_pair(bars.index)
    tp = _typical_price(bars)
    sma = tp.rolling(period, min_periods=period).mean()
    mad = tp.rolling(period, min_periods=period).apply(
        lambda x: np.mean(np.abs(x - np.mean(x))), raw=True
    )
    cci = (tp - sma) / (0.015 * mad.replace(0.0, np.nan))
    cci = cci.fillna(0.0)
    prev = cci.shift(1).fillna(0.0)
    longs = (prev <= -threshold) & (cci > -threshold)
    shorts = (prev >= threshold) & (cci < threshold)
    return longs.fillna(False).astype(bool), shorts.fillna(False).astype(bool)


# ---------------------------------------------------------------------
# §4.2 — SuperTrend Flip (V30; V45 vol filter)
# ---------------------------------------------------------------------


def _wilder_atr(bars: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1).fillna(close.iloc[0] if len(close) else 0.0)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def sig_supertrend_flip(
    bars: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0,
    with_vol_filter: bool = False,
    vol_lookback: int = 20,
) -> tuple[pd.Series, pd.Series]:
    """SuperTrend flip — long when band flips bullish; short on bearish flip.

    `with_vol_filter=True` (V45 STF_AVAX) gates entries on rolling-sigma
    above the lookback median.
    """
    if len(bars) < period + 2:
        return _empty_pair(bars.index)

    hl2 = (bars["high"] + bars["low"]) / 2.0
    atr_v = _wilder_atr(bars, period)
    upper = hl2 + multiplier * atr_v
    lower = hl2 - multiplier * atr_v
    close = bars["close"].to_numpy(dtype=float)

    direction = np.zeros(len(bars), dtype=int)  # +1 bullish, -1 bearish
    final_upper = upper.to_numpy(dtype=float)
    final_lower = lower.to_numpy(dtype=float)
    direction[0] = 1
    for i in range(1, len(bars)):
        if np.isnan(final_upper[i]) or np.isnan(final_lower[i]):
            direction[i] = direction[i - 1]
            continue
        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
            if direction[i] == 1 and final_lower[i] < final_lower[i - 1]:
                final_lower[i] = final_lower[i - 1]
            if direction[i] == -1 and final_upper[i] > final_upper[i - 1]:
                final_upper[i] = final_upper[i - 1]

    dir_series = pd.Series(direction, index=bars.index)
    flip_long = (dir_series == 1) & (dir_series.shift(1) == -1)
    flip_short = (dir_series == -1) & (dir_series.shift(1) == 1)

    if with_vol_filter:
        ret = bars["close"].pct_change().fillna(0.0)
        sigma = ret.rolling(vol_lookback, min_periods=vol_lookback).std()
        med = sigma.rolling(vol_lookback * 3, min_periods=vol_lookback).median()
        gate = (sigma > med).fillna(False)
        flip_long = flip_long & gate
        flip_short = flip_short & gate

    return (
        flip_long.fillna(False).astype(bool),
        flip_short.fillna(False).astype(bool),
    )


# ---------------------------------------------------------------------
# §4.3 — Lateral BB Fade (V29)
# ---------------------------------------------------------------------


def sig_lateral_bb_fade(
    bars: pd.DataFrame, period: int = 20, std: float = 2.0
) -> tuple[pd.Series, pd.Series]:
    """Fade the touch — long when low pierces lower band; short when high pierces upper band."""
    if len(bars) < period + 2:
        return _empty_pair(bars.index)
    ma = bars["close"].rolling(period, min_periods=period).mean()
    sd = bars["close"].rolling(period, min_periods=period).std()
    upper = ma + std * sd
    lower = ma - std * sd
    longs = (bars["low"] <= lower) & (bars["close"] > lower)
    shorts = (bars["high"] >= upper) & (bars["close"] < upper)
    return longs.fillna(False).astype(bool), shorts.fillna(False).astype(bool)


# ---------------------------------------------------------------------
# §4.4 — MFI Extreme (V50)
# ---------------------------------------------------------------------


def sig_mfi_extreme(
    bars: pd.DataFrame,
    period: int = 14,
    upper: float = 75.0,
    lower: float = 25.0,
) -> tuple[pd.Series, pd.Series]:
    """MFI reversal — long when MFI crosses up from below `lower`; short reverse.

    Edge cases (RESEARCH Q6):
      pos=neg=0 → 50; pos>0 neg=0 → 100; pos=0 neg>0 → 0; clip to [0, 100].
    """
    if len(bars) < period + 2:
        return _empty_pair(bars.index)
    tp = _typical_price(bars)
    mf = tp * bars["volume"]
    diff = tp.diff()
    pos = mf.where(diff > 0, 0.0)
    neg = mf.where(diff < 0, 0.0)

    pos_sum = pos.rolling(period, min_periods=period).sum()
    neg_sum = neg.rolling(period, min_periods=period).sum()

    mfi = pd.Series(50.0, index=bars.index, dtype=float)
    mask_both_pos = (pos_sum > 0) & (neg_sum > 0)
    mfi.loc[mask_both_pos] = (
        100.0 - (100.0 / (1.0 + pos_sum.loc[mask_both_pos] / neg_sum.loc[mask_both_pos]))
    )
    mfi.loc[(pos_sum > 0) & (neg_sum == 0)] = 100.0
    mfi.loc[(pos_sum == 0) & (neg_sum > 0)] = 0.0
    # both zero → keep 50.0 default
    mfi = mfi.clip(0.0, 100.0).fillna(50.0)

    prev = mfi.shift(1).fillna(50.0)
    longs = (prev <= lower) & (mfi > lower)
    shorts = (prev >= upper) & (mfi < upper)
    return longs.fillna(False).astype(bool), shorts.fillna(False).astype(bool)


# ---------------------------------------------------------------------
# §4.5 — Volume Profile Rotation 60/15 (V50)
# ---------------------------------------------------------------------


def sig_volume_profile_rot(
    bars: pd.DataFrame, window: int = 60, bins: int = 30
) -> tuple[pd.Series, pd.Series]:
    """Volume-Profile rotation: rotate when close moves out of prior 15-bar
    POC zone defined by the last `window`-bar volume profile.

    Edge cases (RESEARCH Q5):
      - <window bars → False
      - All-zero volume in window → False
    """
    n = len(bars)
    longs = pd.Series(False, index=bars.index, dtype=bool)
    shorts = pd.Series(False, index=bars.index, dtype=bool)
    if n < window + 2:
        return longs, shorts

    close = bars["close"].to_numpy(dtype=float)
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    vol = bars["volume"].to_numpy(dtype=float)

    for i in range(window, n):
        h = high[i - window : i]
        l = low[i - window : i]
        v = vol[i - window : i]
        if v.sum() <= 0 or not np.isfinite(v.sum()):
            continue
        lo = float(np.min(l))
        hi = float(np.max(h))
        if hi <= lo:
            continue
        edges = np.linspace(lo, hi, bins + 1)
        # Approximate volume per bin by attributing each bar's volume to the
        # bin containing its (h+l)/2.
        midpoints = (h + l) / 2.0
        idx = np.clip(np.searchsorted(edges, midpoints, side="right") - 1, 0, bins - 1)
        prof = np.zeros(bins, dtype=float)
        for k, mp_v in zip(idx, v, strict=False):
            prof[int(k)] += float(mp_v)
        poc_bin = int(np.argmax(prof))
        poc_low = float(edges[poc_bin])
        poc_high = float(edges[poc_bin + 1])
        prev_close = close[i - 1]
        cur = close[i]
        # Long: rotate up out of POC zone after dipping inside it
        if prev_close <= poc_high and cur > poc_high:
            longs.iloc[i] = True
        if prev_close >= poc_low and cur < poc_low:
            shorts.iloc[i] = True

    return longs, shorts


# ---------------------------------------------------------------------
# §4.6 — Signed Volume Divergence (V50)
# ---------------------------------------------------------------------


def sig_signed_vol_div(
    bars: pd.DataFrame, lookback: int = 20
) -> tuple[pd.Series, pd.Series]:
    """Signed-volume divergence — bullish div: price LL, signed-vol HL; bearish reverse."""
    if len(bars) < lookback + 2:
        return _empty_pair(bars.index)
    sign = np.sign(bars["close"].diff().fillna(0.0))
    signed_vol = (sign * bars["volume"]).fillna(0.0)
    sv_cum = signed_vol.rolling(lookback, min_periods=lookback).sum()

    price_now = bars["close"]
    price_ago = bars["close"].shift(lookback)
    sv_now = sv_cum
    sv_ago = sv_cum.shift(lookback)

    # Bullish divergence: price made lower-low but cumulative signed vol made higher-low
    longs = (price_now < price_ago) & (sv_now > sv_ago)
    shorts = (price_now > price_ago) & (sv_now < sv_ago)
    return longs.fillna(False).astype(bool), shorts.fillna(False).astype(bool)


__all__ = [
    "sig_cci_extreme",
    "sig_supertrend_flip",
    "sig_lateral_bb_fade",
    "sig_mfi_extreme",
    "sig_volume_profile_rot",
    "sig_signed_vol_div",
]
