"""Triple-bear regime filter for V24 XSM (Phase 9, Task 2 · STRAT-HL-07).

Pure function: given daily bars for BTC + each coin in the XSM universe,
returns a ``FilterResult`` telling the controller whether to go flat.

Three bearish regime conditions (ANY firing → ``fired=True``):

1. ``btc_below_100d_sma``
   — BTC's last close is below its 100-day SMA.
2. ``btc_50d_slope_negative``
   — today's 50d SMA is lower than yesterday's 50d SMA (slope flipped negative).
3. ``breadth_below_5_of_9``
   — fewer than ``breadth_min_above`` of the ``len(universe_daily)`` coins
   have their last close above their own 50d SMA.

No IO, no imports from ``backend.app.{venues,db,executors,engine,controllers}``.
Strategy-layer purity invariant preserved (same as Phases 7+8).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.app.strategies.base import sma

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar


@dataclass(frozen=True)
class FilterResult:
    """Output of ``triple_bear_filter``.

    ``reason`` is a space-separated string of the condition names that
    fired (e.g. ``"btc_below_100d_sma breadth_below_5_of_9"``), or
    ``None`` when no condition fired.
    """

    fired: bool
    reason: str | None


# Condition names — kept as module constants so the acceptance grep can
# match them verbatim in source. Do not rename without updating PLAN Task 2.
_COND_BTC_BELOW_100D = "btc_below_100d_sma"
_COND_BTC_50D_SLOPE = "btc_50d_slope_negative"
_COND_BREADTH = "breadth_below_5_of_9"


def triple_bear_filter(
    *,
    btc_daily: list[Bar],
    universe_daily: dict[str, list[Bar]],
    btc_sma_long_days: int = 100,
    btc_sma_short_days: int = 50,
    breadth_sma_days: int = 50,
    breadth_min_above: int = 5,
) -> FilterResult:
    """Evaluate the 3 bearish regime conditions against daily closed bars.

    Parameters
    ----------
    btc_daily:
        BTC daily bars, oldest-first. Must contain at least
        ``max(btc_sma_long_days, btc_sma_short_days + 1)`` bars.
    universe_daily:
        Mapping ``coin -> daily bars`` for every coin in the XSM universe
        (including BTC). Each list must contain at least ``breadth_sma_days``
        bars.
    btc_sma_long_days, btc_sma_short_days, breadth_sma_days:
        Lookback lengths for the SMAs (defaults match STRAT-HL-07).
    breadth_min_above:
        Breadth threshold — if fewer than this many coins are above their
        own 50d SMA, the breadth condition fires (default 5 out of 9).

    Returns
    -------
    FilterResult
        ``fired=True`` iff any condition fired; ``reason`` names them.

    Raises
    ------
    ValueError
        Propagated from ``sma`` when a series lacks enough bars.
    """
    fired: list[str] = []

    # Condition 1: BTC close < BTC 100d SMA.
    btc_100 = sma(btc_daily, btc_sma_long_days)
    if btc_daily[-1].close < btc_100:
        fired.append(_COND_BTC_BELOW_100D)

    # Condition 2: today's 50d SMA < yesterday's 50d SMA.
    #   today    = sma(btc_daily[-N:], N)    — window ending on last bar
    #   yesterday= sma(btc_daily[-N-1:-1], N) — window shifted back by 1 bar
    if len(btc_daily) < btc_sma_short_days + 1:
        raise ValueError(
            f"btc_50d_slope needs at least {btc_sma_short_days + 1} bars, "
            f"got {len(btc_daily)}"
        )
    btc_50_today = sma(btc_daily, btc_sma_short_days)
    btc_50_yesterday = sma(btc_daily[:-1], btc_sma_short_days)
    if btc_50_today < btc_50_yesterday:
        fired.append(_COND_BTC_50D_SLOPE)

    # Condition 3: < breadth_min_above coins above their 50d SMA.
    above_count = 0
    for _coin, bars in universe_daily.items():
        coin_sma = sma(bars, breadth_sma_days)
        if bars[-1].close > coin_sma:
            above_count += 1
    if above_count < breadth_min_above:
        fired.append(_COND_BREADTH)

    if fired:
        return FilterResult(fired=True, reason=" ".join(fired))
    return FilterResult(fired=False, reason=None)


__all__ = ["FilterResult", "triple_bear_filter"]
