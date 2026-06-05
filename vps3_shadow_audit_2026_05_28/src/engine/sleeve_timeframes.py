"""Sleeve timeframe registry — single source of truth for bar periods.

Both tv-api (for ``_next_bar_boundary`` applied_at computation) and tv-engine
(for BarEngine wake scheduling) import this module. Never compute TF seconds
in two places — duplication risks bar-boundary drift across processes, and
inv #12 (operator writes apply at NEXT bar boundary) hangs on a single
authoritative TF map.

CLAUDE.md inv #12: operator writes apply at the NEXT bar boundary, never
mid-bar. This registry is the reference for which boundary that is when
the live ``BarEngine.next_bar_for`` is unavailable (e.g. tv-api process,
which is decoupled from the engine in v1).
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

# Timeframe seconds per sleeve. Extend here when new sleeves are added.
# V52 Champion (Phase 8.1): 4-hour bars on ETH/AVAX/SOL/LINK + BTC regime.
# V24-XSM (Phase 9): weekly bars.
# Poly Updown (Phase 15): 5m and 15m bars on BTC/ETH/SOL.
SLEEVE_TIMEFRAMES: Final[Mapping[str, int]] = MappingProxyType({
    # V52 Champion (HL perpetuals, 4h)
    "V52-ETH":  4 * 3600,
    "V52-AVAX": 4 * 3600,
    "V52-SOL":  4 * 3600,
    "V52-LINK": 4 * 3600,
    "V52-BTC":  4 * 3600,   # BTC regime sleeve
    # V24 XSM (HL weekly)
    "V24-XSM":  7 * 24 * 3600,
    # Polymarket Updown (5m)
    "POLY-UPDOWN-5M-BTC":  5 * 60,
    "POLY-UPDOWN-5M-ETH":  5 * 60,
    "POLY-UPDOWN-5M-SOL":  5 * 60,
    # Polymarket Updown (15m)
    "POLY-UPDOWN-15M-BTC": 15 * 60,
    "POLY-UPDOWN-15M-ETH": 15 * 60,
    "POLY-UPDOWN-15M-SOL": 15 * 60,
})


__all__ = ["SLEEVE_TIMEFRAMES"]
