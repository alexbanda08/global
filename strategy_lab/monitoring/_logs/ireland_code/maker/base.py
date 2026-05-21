"""Phase 30 — `MakerStrategyBase` ABC + pure helpers.

Strategies are PURE-FUNCTION decision modules. No I/O. No imports from
``engine.*``, ``venues.polymarket.client``, DB, or network. All event
handlers return ``list[Decision]`` (empty list is valid for "no action").

CLAUDE.md invariants honored here:

- inv #4 (closed-bar discipline): event handlers receive only closed L25
  snapshots from BookMirror, never partially-built raw WS frames. The
  BookMirror layer enforces the snapshot boundary upstream.
- inv #10 (secrets never logged): ``structlog.get_logger(__name__)`` at
  module top. The global ``redact_secrets_processor`` (set in
  ``backend.app.core.logging``) catches HEX_PRIVKEY-shaped values
  automatically — no `private_key` value can be reached from this module.

Helper formulas come straight from the chain-validated Polymarket fee
model (see RESEARCH §"Pitfall 6 — Don't hand-roll the fee curve" and
``shadow_engine/base.py`` lines 41-49):

- Taker fee per share: ``0.07 * p * (1 - p)``  (symmetric around p=0.5)
- Maker rebate per share: ``0.20 * taker_fee_per_share``
- Price tick: 1¢ — every limit order MUST be quantized to the cent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    from backend.app.strategies.polymarket.maker.types import (
        Decision,
        L25Update,
        OrderFill,
        SlugActive,
        SlugResolved,
        TradePrint,
    )

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: CLOB minimum price increment (1¢). Limit orders are quantized to this tick.
_TICK = Decimal("0.01")

#: Polymarket taker fee rate (verified against chain-observable settlements
#: in the V3f decode). See ``shadow_engine/base.py:27``.
_TAKER_FEE_RATE = Decimal("0.07")

#: Maker rebate share — fraction of the equivalent taker fee returned to the
#: maker side. See ``shadow_engine/base.py:28``.
_MAKER_REBATE_SHARE = Decimal("0.20")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def quantize_price(p: Decimal) -> Decimal:
    """Round `p` to the nearest 1¢ tick using ROUND_HALF_UP.

    Examples:
        >>> quantize_price(Decimal("0.5234"))
        Decimal('0.52')
        >>> quantize_price(Decimal("0.5250"))
        Decimal('0.53')
    """
    return (p / _TICK).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * _TICK


def taker_fee(p: Decimal) -> Decimal:
    """Polymarket taker fee per share at price ``p``.

    Formula: ``0.07 * p * (1 - p)``. Symmetric around p=0.5 (max fee),
    approaches 0 at the extremes (p≈0 or p≈1).
    """
    return _TAKER_FEE_RATE * p * (Decimal(1) - p)


def maker_rebate(t_fee: Decimal) -> Decimal:
    """Maker rebate per share — 20% of the equivalent taker fee."""
    return _MAKER_REBATE_SHARE * t_fee


def median(values: list[Decimal]) -> Decimal:
    """Median of a Decimal list (sorted; averages middle two for even length).

    Raises:
        IndexError: if ``values`` is empty.
    """
    s = sorted(values)
    n = len(s)
    if n == 0:
        raise IndexError("median of empty list")
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / Decimal(2)


def _next_order_id(strategy_code: str, counter: int) -> str:
    """Build a local order ID like ``ACC-M-00000001``.

    The strategy_code prefix keeps ACC-M / ACC-H / MAS order IDs distinct
    in the shadow log and (Phase 30.1) in the CLOB-side cross-reference.
    """
    return f"{strategy_code}-{counter:08d}"


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class MakerStrategyBase(ABC):
    """Abstract base for ACC-M / ACC-H / MAS event-driven decision modules.

    Lifecycle:
        1. ``on_slug_active(evt)`` — a new slug opened (MAS may emit MINT).
        2. ``on_l25_update(evt)`` — L25 snapshot from BookMirror; strategies
           emit POST_BID / POST_ASK / CANCEL / MERGE decisions here.
        3. ``on_trade_print(evt)`` — trade print from TradeMirror; ACC-H
           uses these for its 4-rule composite-taker logic.
        4. ``on_order_fill(evt)`` — our order filled; update inventory.
        5. ``on_slug_resolved(evt)`` — outcome locked; emit final REDEEM
           decisions for residual.

    Invariants enforced by subclasses + tests:
      * NO imports from engine.*, venues.polymarket.client, DB, network.
      * Event handlers MUST NOT mutate the ``evt`` argument (frozen anyway).
      * Event handlers MAY mutate ``self.slug_states``.
      * All event handlers return ``list[Decision]`` (empty list is valid).
    """

    #: Subclasses set this to "ACC-M" / "ACC-H" / "MAS". Class-level default
    #: keeps the ABC importable without subclassing for tooling.
    code: str = ""

    @abstractmethod
    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        """React to an L25 book snapshot."""

    @abstractmethod
    def on_trade_print(self, evt: TradePrint) -> list[Decision]:
        """React to a trade print on the wire."""

    @abstractmethod
    def on_order_fill(self, evt: OrderFill) -> list[Decision]:
        """React to one of our orders being filled (partial or full)."""

    @abstractmethod
    def on_slug_active(self, evt: SlugActive) -> list[Decision]:
        """React to a new slug becoming active (MAS may emit MINT)."""

    @abstractmethod
    def on_slug_resolved(self, evt: SlugResolved) -> list[Decision]:
        """React to slug resolution (oracle outcome locked)."""


__all__ = [
    "MakerStrategyBase",
    "_next_order_id",
    "maker_rebate",
    "median",
    "quantize_price",
    "taker_fee",
]
