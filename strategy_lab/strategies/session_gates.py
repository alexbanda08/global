"""
Session / time-of-day gates (Vector 5 in docs/research/33_NEW_STRATEGY_VECTORS.md).

Pure timestamp-derived boolean masks indexed on a UTC DatetimeIndex.
None of these read price/volume data — they are stateless calendars.

Three published 2025 effects motivate these gates:

  1. "Monday Asia Open Effect" (Zarattini, Pagani & Barbon, SFI 25-80)
     BTC intraday trend benchmark concentrates positive returns from
     Sun 23:00 UTC → Mon 23:00 UTC (Tokyo cash-equity open window).
     Effect strengthened post-2020 with institutional entry.

  2. "Tea-time" peak (Review of Quantitative Finance & Accounting)
     Volume / volatility / illiquidity peak ~16:00–17:00 UTC across
     38 exchanges and 1940 pairs. A natural vol-expansion window for
     breakout sleeves; a hostile window for mean-reversion sleeves.

  3. "US pump, Asia dump" — Asian session 00:00–07:00 UTC has historically
     produced flat-to-negative average hourly returns; US session positive.

The masks here are intentionally inclusive on the LEFT, exclusive on the RIGHT
(consistent with bar-labeling convention: a 4h bar timestamped 16:00 covers
[16:00, 20:00) UTC).

Usage pattern (apply at the equity-return level, not the signal level):

    eq_returns = eq_curve.pct_change().fillna(0)
    mask_long = monday_asia_open(eq_returns.index)
    eq_gated = (1 + eq_returns.where(mask_long, 0)).cumprod() * 10_000

Or as a sleeve-level long-only bias by combining with `sig_*` boolean output.
"""
from __future__ import annotations

import pandas as pd

__all__ = [
    "monday_asia_open",
    "asian_session",
    "us_session",
    "european_session",
    "teatime_volexp",
    "macro_event_pause",
    "weekend_chop",
    "describe",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_utc(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Defensive normalize: tz-naive → assume UTC; tz-aware → convert to UTC.

    Strategy_lab convention is naive UTC. Don't fight it; just don't crash if
    a caller passes a tz-aware index.
    """
    if idx.tz is None:
        return idx
    return idx.tz_convert("UTC").tz_localize(None)


# ---------------------------------------------------------------------------
# Session windows (all in UTC)
# ---------------------------------------------------------------------------

def monday_asia_open(idx: pd.DatetimeIndex) -> pd.Series:
    """True for bars in the Monday-Asia-Open trend window.

    Window: Sunday 23:00 UTC inclusive → Monday 23:00 UTC exclusive.
    (Sunday 23:00 UTC ≈ Monday 08:00 in Tokyo, the TSE cash-equity open;
     held 24h forward to capture the documented trend persistence.)

    Returns a bool Series aligned to idx.
    """
    idx = _ensure_utc(idx)
    dow = idx.dayofweek                 # Mon=0 ... Sun=6
    hr = idx.hour
    sun_after_23 = (dow == 6) & (hr >= 23)
    mon_before_23 = (dow == 0) & (hr < 23)
    mask = sun_after_23 | mon_before_23
    return pd.Series(mask, index=idx, name="monday_asia_open")


def asian_session(idx: pd.DatetimeIndex) -> pd.Series:
    """Asian session: 00:00–07:00 UTC.

    Historically flat-to-negative hourly returns. Use to *dampen* long
    trend sleeves (size *= 0.5) rather than to enter shorts — the
    asymmetry is too small to short on.
    """
    idx = _ensure_utc(idx)
    mask = (idx.hour >= 0) & (idx.hour < 7)
    return pd.Series(mask, index=idx, name="asian_session")


def us_session(idx: pd.DatetimeIndex) -> pd.Series:
    """US cash-equity session: 13:30–20:00 UTC (NYSE 09:30–16:00 ET).

    Highest BTC volume since ETF launch (~63% of daily turnover).
    """
    idx = _ensure_utc(idx)
    minute = idx.hour * 60 + idx.minute
    mask = (minute >= 13 * 60 + 30) & (minute < 20 * 60)
    return pd.Series(mask, index=idx, name="us_session")


def european_session(idx: pd.DatetimeIndex) -> pd.Series:
    """European cash-equity session: 07:00–15:30 UTC.

    Liquidity ramp; moderate trend persistence.
    """
    idx = _ensure_utc(idx)
    minute = idx.hour * 60 + idx.minute
    mask = (minute >= 7 * 60) & (minute < 15 * 60 + 30)
    return pd.Series(mask, index=idx, name="european_session")


def teatime_volexp(idx: pd.DatetimeIndex) -> pd.Series:
    """Tea-time vol-expansion window: 15:00–18:00 UTC.

    The 16:00–17:00 UTC global volatility peak is bracketed by a
    pre-position hour and a post-peak release hour. Use to *enable*
    breakout sleeves; use to *disable* mean-reversion sleeves.
    """
    idx = _ensure_utc(idx)
    mask = (idx.hour >= 15) & (idx.hour < 18)
    return pd.Series(mask, index=idx, name="teatime_volexp")


def weekend_chop(idx: pd.DatetimeIndex) -> pd.Series:
    """Saturday all day + Sunday 00:00–22:00 UTC.

    Lower liquidity, choppier price action, weaker trend persistence.
    Sunday 23:00 UTC onward is *excluded* because that's the start of
    the Monday-Asia-Open window above.
    """
    idx = _ensure_utc(idx)
    dow = idx.dayofweek
    hr = idx.hour
    sat = dow == 5
    sun_pre23 = (dow == 6) & (hr < 23)
    return pd.Series(sat | sun_pre23, index=idx, name="weekend_chop")


# ---------------------------------------------------------------------------
# Macro-event blackout
# ---------------------------------------------------------------------------

def macro_event_pause(
    idx: pd.DatetimeIndex,
    events: list[pd.Timestamp] | None = None,
    pre_minutes: int = 30,
    post_minutes: int = 30,
) -> pd.Series:
    """True for bars OUTSIDE a [-pre, +post] window around each event.

    Defaults to an empty event list (mask all True). Caller passes a list of
    UTC timestamps for FOMC / CPI / NFP / known tariff windows. Idea is to
    refuse new entries / flatten in the immediate vicinity of macro shocks
    (the Oct 10–11 2025 cascade is the canonical case for why this matters).

    Returns True where trading is *allowed* (so it composes with `&` as a
    standard "trade-allowed" gate).
    """
    idx = _ensure_utc(idx)
    if not events:
        return pd.Series(True, index=idx, name="macro_event_pause")

    pre = pd.Timedelta(minutes=pre_minutes)
    post = pd.Timedelta(minutes=post_minutes)
    blocked = pd.Series(False, index=idx)
    for t in events:
        t = pd.Timestamp(t)
        if t.tzinfo is not None:
            t = t.tz_convert("UTC").tz_localize(None)
        blocked |= (idx >= t - pre) & (idx < t + post)
    return pd.Series(~blocked.values, index=idx, name="macro_event_pause")


# ---------------------------------------------------------------------------
# Convenience for the probe runner
# ---------------------------------------------------------------------------

def describe(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Return a DataFrame with one column per session mask.

    Useful for sanity-checking coverage (e.g. ~14% of bars in monday_asia_open
    on a 4h grid: 6 bars/day × 1 day / 7 days ≈ 14.3%).
    """
    return pd.DataFrame({
        "monday_asia_open": monday_asia_open(idx),
        "asian_session": asian_session(idx),
        "us_session": us_session(idx),
        "european_session": european_session(idx),
        "teatime_volexp": teatime_volexp(idx),
        "weekend_chop": weekend_chop(idx),
    })
