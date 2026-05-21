"""Vwap pre-flight guard.

P2 forensics showed the bottom vwap bucket bleeds the entire backtest:
  (0.00, 0.30]: n=320 trades, WR 11.6% vs breakeven 16.3% → mean PnL -$8.90/tr
  → -$2,848 total loss on a -$2,126 aggregate.

These are markets where the consensus has already shifted hard against
our `direction`. We fire INTO the consensus and get adversely selected.

Implementation: check the level-0 ASK price on the chosen direction's
tier1 row. If ask_price_0 < VWAP_MIN_GUARD → skip. This catches the doom
zone before the L25 walk runs.
"""

from __future__ import annotations

from typing import Tuple


def is_vwap_too_low(
    ask_price_l0: float,
    threshold: float,
) -> Tuple[bool, str]:
    """Return (should_skip, reason).

    threshold = 0 disables the guard (returns False).
    """
    if threshold <= 0:
        return False, "ok"
    if ask_price_l0 is None or ask_price_l0 != ask_price_l0:  # NaN-safe
        return True, "vwap_guard_missing_ask_l0"
    if float(ask_price_l0) < threshold:
        return True, f"vwap_guard_{ask_price_l0:.3f}<{threshold:.2f}"
    return False, "ok"
