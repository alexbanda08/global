"""V24 XSM cross-sectional multi-filter sleeve config (Phase 9, Task 1 · STRAT-HL-04 + SIZING-WK1).

Per 09-CONTEXT D-01 / D-05 the XSM universe is FROZEN at phase start —
``UNIVERSE`` is a module-level constant. Runtime overrides via
``V24XSMConfig(universe=...)`` are discouraged; the default is the frozen
9-coin list and changes require a new phase + PR + documented justification
(see ``docs/XSM_UNIVERSE.md``).

Wk1 sizing ($25/slot × 4 slots = $100 basket) follows SIZING-WK1; parity
tolerance is widened to ±10% vs ±5% for USER sleeves — min-notional skips
amplify XSM parity noise (slot count varies week-over-week).
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

# 9-coin FROZEN universe — see docs/XSM_UNIVERSE.md for rationale + freeze date.
# Kept on ONE line so the Phase 9 acceptance grep (PLAN Task 1) matches literally.
UNIVERSE: tuple[str, ...] = ('BTC', 'ETH', 'SOL', 'AVAX', 'DOGE', 'MATIC', 'ADA', 'LINK', 'DOT')


class V24XSMConfig(BaseModel):
    """Config for ``V24XSMMultiFilterStrategy`` + ``HyperliquidXsmController``.

    All fields are ``Decimal`` for money/price fractions; integer parameters
    are ``int``. Frozen so controllers can hold it by value without worrying
    about downstream mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Universe + cadence
    universe: tuple[str, ...] = UNIVERSE
    timeframe: str = "1w"

    # Sizing (SIZING-WK1 — $25/slot × 4 = $100 wk1 basket)
    notional_per_slot_usd: Decimal = Decimal("25")
    max_slots: int = 4

    # Triple-bear filter lookbacks (STRAT-HL-07)
    btc_sma_long_days: int = 100
    btc_sma_short_days: int = 50
    breadth_sma_days: int = 50
    breadth_min_above: int = 5

    # Ranker inputs
    dd_lookback_days: int = 90
    relative_atr_period: int = 14

    # Exit barrier widths for weekly hold (wider than 4h USER sleeves)
    sl_atr_mult: Decimal = Decimal("3")
    tp_atr_mult: Decimal = Decimal("6")
    max_hold_weeks: int = 2
    cooldown_weeks: int = 1

    # Sizing + risk
    equity_usd: Decimal = Decimal("100")
    parity_tolerance_pct: Decimal = Decimal("10.0")


__all__ = ["UNIVERSE", "V24XSMConfig"]
