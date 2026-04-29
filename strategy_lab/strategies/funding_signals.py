"""
Funding-rate signals (Vector 1 in 33_NEW_STRATEGY_VECTORS.md).

Two signal families:

  sig_funding_z_fade  — directional fade when funding hits extreme z-score.
                        Long when z < -threshold (shorts over-paying, often
                        a capitulation low); short when z > +threshold
                        (longs over-paying, often a local top).

  sig_funding_carry_dn — delta-neutral carry signal: long perp when funding
                         negative AND price near support; short perp when
                         funding positive AND price near resistance.
                         Returned as long/short masks for a perp-only book.

All signals consume:
  df    : OHLC frame at the bar timeframe (typically 4h)
  fund  : per-bar funding rate series (already aligned to df.index, usually
          via util.hl_data.funding_per_4h_bar — sum of the hourly rates that
          fell inside each bar). Units are decimal per bar (not annualized).

Both functions return (long_entries, short_entries) bool Series indexed on df.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["sig_funding_z_fade", "sig_funding_carry_dn"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift()
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n // 2).mean()


def _rolling_z(s: pd.Series, window: int) -> pd.Series:
    mu = s.rolling(window, min_periods=window // 4).mean()
    sd = s.rolling(window, min_periods=window // 4).std()
    return (s - mu) / sd.replace(0, np.nan)


# ---------------------------------------------------------------------------
# Signal: funding z-fade (directional)
# ---------------------------------------------------------------------------

def sig_funding_z_fade(
    df: pd.DataFrame,
    fund: pd.Series,
    z_window: int = 180,            # 180 4h-bars = 30 days
    z_long: float = -1.5,           # enter long when z below this
    z_short: float = +1.5,          # enter short when z above this
    require_atr_stretch: bool = True,
    atr_window: int = 14,
    atr_stretch: float = 1.5,
) -> tuple[pd.Series, pd.Series]:
    """Fade funding extremes.

    Logic:
      z = rolling-z of funding rate over `z_window` bars.
      Long  when z < z_long  AND price has stretched DOWN >= atr_stretch * ATR.
      Short when z > z_short AND price has stretched UP   >= atr_stretch * ATR.

    The ATR-stretch confluence is the V19 lesson: pure funding-Z fades have
    poor WR; gating on a structural overshoot (price has actually moved
    against the over-leveraged side) lifts WR materially.

    `fund` must be aligned to `df.index` (use util.hl_data.funding_per_4h_bar).
    Both df and fund must be on the SAME bar-clock (4h here).
    """
    fund = fund.reindex(df.index).fillna(0.0)
    z = _rolling_z(fund, z_window)

    if require_atr_stretch:
        atr = _atr(df, atr_window)
        # 5-bar return in ATR units
        ret_5 = df["close"] - df["close"].shift(5)
        stretch_dn = ret_5 < -atr_stretch * atr
        stretch_up = ret_5 > +atr_stretch * atr
    else:
        stretch_dn = pd.Series(True, index=df.index)
        stretch_up = pd.Series(True, index=df.index)

    long_entries = (z < z_long) & stretch_dn
    short_entries = (z > z_short) & stretch_up

    return long_entries.fillna(False), short_entries.fillna(False)


# ---------------------------------------------------------------------------
# Signal: funding carry (long perp when funding negative)
# ---------------------------------------------------------------------------

def sig_funding_carry_dn(
    df: pd.DataFrame,
    fund: pd.Series,
    fund_threshold_per_bar: float = -0.0001,  # -0.01% per 4h bar = ~ -0.22%/day
    confirm_bars: int = 6,                     # require negative for N consecutive bars
) -> tuple[pd.Series, pd.Series]:
    """Long perp when funding has been persistently negative.

    Crypto perp funding is ~85% positive on majors. Persistent negative-funding
    episodes (bears over-paying longs) tend to precede mean-reversion bounces.
    Pair the carry collected with the directional bounce.

    Symmetric short side fires when funding has been persistently very high
    positive (longs over-paying) — fade.
    """
    fund = fund.reindex(df.index).fillna(0.0)
    persistent_neg = fund.rolling(confirm_bars).max() < fund_threshold_per_bar
    persistent_pos = fund.rolling(confirm_bars).min() > -fund_threshold_per_bar * 5  # ~+0.05%

    long_entries = persistent_neg
    short_entries = persistent_pos
    return long_entries.fillna(False), short_entries.fillna(False)
