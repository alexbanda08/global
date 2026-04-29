"""
Pure price-action signals — no indicators (no MA, no oscillator, no volatility band).

Built to be a NEW signal family with near-zero conceptual overlap with the V52
stack (CCI, ST-flip, BB-fade, MFI, VolumeProfile, SignedVolumeDiv).

Three variants:
  1. sig_pivot_break              — close breaks last k-bar pivot, after N-bar quiet
  2. sig_pivot_break_retest       — same, but require a pullback retest within W bars
  3. sig_inside_bar_break         — mother-bar/inside-bar break (classic Al Brooks)

All return (long_sig, short_sig) bool Series aligned to df.index, with
shift(1) applied to be next-bar-fillable in the canonical simulator.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


# ----------------------------------------------------------------- helpers
def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h = df["high"].astype(float); l = df["low"].astype(float)
    c = df["close"].astype(float).shift(1)
    tr = pd.concat([(h - l).abs(), (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def _pivot_high(high: pd.Series, k: int = 3) -> pd.Series:
    """True at bar t if high[t-k] is the local max in [t-2k .. t]. Available at bar t (no look-ahead)."""
    win = 2 * k + 1
    rolled_max = high.rolling(win).max()
    centred = high.shift(k)
    is_pivot = (centred == rolled_max) & (centred.notna())
    return is_pivot


def _pivot_low(low: pd.Series, k: int = 3) -> pd.Series:
    win = 2 * k + 1
    rolled_min = low.rolling(win).min()
    centred = low.shift(k)
    is_pivot = (centred == rolled_min) & (centred.notna())
    return is_pivot


def _last_pivot_level(price: pd.Series, is_pivot: pd.Series, lookback: int = 60) -> pd.Series:
    """At bar t, return the most-recent pivot price within [t-lookback, t-1] (inclusive of pivot bar)."""
    # pivot price at bar t is high[t-k]; here `price` is already shifted by k via _pivot_high construction
    # is_pivot[t] means high[t-k] is the pivot — its price is high.shift(k)[t]
    # But callers will pass the already-shifted price.
    out = price.where(is_pivot)
    return out.ffill(limit=lookback)


# ----------------------------------------------------------------- 1. pivot break
def sig_pivot_break(df: pd.DataFrame, k: int = 3, quiet_bars: int = 8,
                    quiet_atr_mult: float = 1.5,
                    lookback: int = 60) -> tuple[pd.Series, pd.Series]:
    """
    Long entry: close > most-recent pivot-high (formed within `lookback` bars),
                AND the (high-low) range over the last `quiet_bars` is <= quiet_atr_mult * ATR
                (i.e. the breakout follows a consolidation).
    Short entry: mirror on pivot-low.
    """
    high = df["high"].astype(float); low = df["low"].astype(float); close = df["close"].astype(float)
    atr = _atr(df, 14)

    is_ph = _pivot_high(high, k)
    is_pl = _pivot_low(low, k)
    pivot_high_price = high.shift(k).where(is_ph)
    pivot_low_price = low.shift(k).where(is_pl)

    last_ph = pivot_high_price.ffill(limit=lookback)
    last_pl = pivot_low_price.ffill(limit=lookback)

    # quiet range over the last quiet_bars (excluding current bar)
    win_high = high.shift(1).rolling(quiet_bars).max()
    win_low = low.shift(1).rolling(quiet_bars).min()
    range_quiet = (win_high - win_low) <= (quiet_atr_mult * atr)

    long_break = (close > last_ph) & (close.shift(1) <= last_ph.shift(1)) & range_quiet & last_ph.notna()
    short_break = (close < last_pl) & (close.shift(1) >= last_pl.shift(1)) & range_quiet & last_pl.notna()

    long_sig = long_break.shift(1).fillna(False).astype(bool)
    short_sig = short_break.shift(1).fillna(False).astype(bool)
    return long_sig, short_sig


# ----------------------------------------------------------------- 2. pivot break + retest
def sig_pivot_break_retest(df: pd.DataFrame, k: int = 3, quiet_bars: int = 8,
                            quiet_atr_mult: float = 1.5,
                            retest_window: int = 6,
                            retest_tol_atr: float = 0.5,
                            lookback: int = 60) -> tuple[pd.Series, pd.Series]:
    """
    Trigger pattern (long):
      Step 1: a `pivot_break` long candidate fires at bar B (breakout above pivot-high P).
      Step 2: within `retest_window` bars after B, price retraces to within
              `retest_tol_atr * ATR` of P (low touches the band).
      Step 3: the retest bar closes above P AGAIN -> entry signal.
    Mirror for shorts.
    """
    high = df["high"].astype(float); low = df["low"].astype(float); close = df["close"].astype(float)
    atr = _atr(df, 14)

    long_break, short_break = sig_pivot_break(df, k, quiet_bars, quiet_atr_mult, lookback)
    # Note: sig_pivot_break already shifted by 1; we want the un-shifted breakout to reason about retest -> reconstruct
    long_break_now = long_break.shift(-1).fillna(False).astype(bool)
    short_break_now = short_break.shift(-1).fillna(False).astype(bool)

    # The breakout level for each break is `last_ph` / `last_pl` at the break bar.
    is_ph = _pivot_high(high, k); is_pl = _pivot_low(low, k)
    pivot_high_price = high.shift(k).where(is_ph).ffill(limit=lookback)
    pivot_low_price = low.shift(k).where(is_pl).ffill(limit=lookback)

    long_entry = pd.Series(False, index=df.index)
    short_entry = pd.Series(False, index=df.index)

    # Iterate breakouts (sparse), confirm retest within window
    long_break_idx = np.flatnonzero(long_break_now.values)
    for bi in long_break_idx:
        level = pivot_high_price.iat[bi]
        if pd.isna(level):
            continue
        tol = retest_tol_atr * (atr.iat[bi] if not pd.isna(atr.iat[bi]) else 0)
        end = min(bi + retest_window, len(df) - 1)
        for j in range(bi + 1, end + 1):
            # retest condition: low touches level band AND close back above level
            if low.iat[j] <= level + tol and close.iat[j] > level:
                long_entry.iat[j] = True
                break

    short_break_idx = np.flatnonzero(short_break_now.values)
    for bi in short_break_idx:
        level = pivot_low_price.iat[bi]
        if pd.isna(level):
            continue
        tol = retest_tol_atr * (atr.iat[bi] if not pd.isna(atr.iat[bi]) else 0)
        end = min(bi + retest_window, len(df) - 1)
        for j in range(bi + 1, end + 1):
            if high.iat[j] >= level - tol and close.iat[j] < level:
                short_entry.iat[j] = True
                break

    long_sig = long_entry.shift(1).fillna(False).astype(bool)
    short_sig = short_entry.shift(1).fillna(False).astype(bool)
    return long_sig, short_sig


# ----------------------------------------------------------------- 3. inside-bar break
def sig_inside_bar_break(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Mother bar M, inside bar I (high_I < high_M and low_I > low_M).
    Long: next bar closes > high_M.  Short: next bar closes < low_M.
    """
    h = df["high"].astype(float); l = df["low"].astype(float); c = df["close"].astype(float)
    inside = (h < h.shift(1)) & (l > l.shift(1))
    mh = h.shift(1).where(inside).ffill(limit=4)
    ml = l.shift(1).where(inside).ffill(limit=4)
    long_brk = (c > mh) & (c.shift(1) <= mh.shift(1))
    short_brk = (c < ml) & (c.shift(1) >= ml.shift(1))
    return (long_brk.shift(1).fillna(False).astype(bool),
            short_brk.shift(1).fillna(False).astype(bool))
