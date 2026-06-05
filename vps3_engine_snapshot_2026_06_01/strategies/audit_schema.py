"""Canonical resolution-event schema — one normalized read across families.

Phase 37 Wave 3. Two writers emit ``kind='poly_updown_resolution'`` rows with
different payload shapes:

- **legacy updown / resolver** (``engine/poly_updown_resolver.py``): ``won`` bool,
  ``pnl_usd`` as a STRING (deliberate — preserves exact ``Decimal`` precision),
  ``entry_qty``/``entry_price``, ``signal``, ``symbol``.
- **sniper_v5** (``controllers/polymarket_sniper_v5.py``): ``event_type=
  'sleeve_fire_resolved'``, ``outcome``/``direction`` (``won`` derived),
  ``pnl_usd`` as a FLOAT, ``placed_size_usd``, ``fill_vwap``/``fill_shares``,
  ``fill_method``, ``asset``.

Rather than rewrite history or force one write-shape (the resolver's string is
correct for ``Decimal`` precision; see ``test_poly_updown_resolver.py``), this
module is the ONE place that NORMALIZES either shape into the dashboard's
canonical row. Every consumer reads through ``normalize_resolution_payload`` so
none of them re-implements the OR-the-kinds / cast-the-pnl dance.

Canonical event vocabulary (``EventType``): ``signal`` → ``placed`` → ``resolved``.
The sniper_v5 writer uses the legacy literal ``'sleeve_fire_resolved'`` as its
resolved marker; ``SNIPER_V5_RESOLVED_MARKER`` records that so detection lives
in one place. Pure module — stdlib only, no api/engine imports.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Final

# Kinds that carry a resolution payload.
KIND_RESOLUTION: Final[str] = "poly_updown_resolution"
KIND_SIGNAL: Final[str] = "poly_updown_signal"

#: sniper_v5's resolved-fire discriminator inside data->>'event_type'.
SNIPER_V5_RESOLVED_MARKER: Final[str] = "sleeve_fire_resolved"


class EventType(str, Enum):
    """Canonical lifecycle vocabulary for a sleeve audit event."""

    SIGNAL = "signal"      # a fire was evaluated (gates / no_signal / placed-or-not)
    PLACED = "placed"      # an order was placed (entry)
    RESOLVED = "resolved"  # the market resolved → win/loss + pnl


def is_sniper_v5_shape(data: dict[str, Any]) -> bool:
    """True when the payload is the sniper_v5 resolved-fire shape."""
    return str(data.get("event_type") or "").strip().lower() == SNIPER_V5_RESOLVED_MARKER


def normalize_resolution_payload(d: dict[str, Any]) -> dict[str, Any]:
    """Adapt either resolution-event payload into the canonical dashboard row.

    Returns a dict with stable keys: ``won`` (bool), ``pnl_usd`` (raw — str from
    the resolver, float from sniper_v5; consumers coerce), ``entry_value_usd``,
    ``signal``, ``entry_price``, ``entry_qty``, ``entry_strike``, ``symbol``,
    ``fill_method`` (None for non-sniper rows, so aggregators can drop synthetic
    placeholders). Does NOT carry ``at`` — callers add it.
    """
    if is_sniper_v5_shape(d):
        outcome = str(d.get("outcome") or "").strip().lower()
        direction = str(d.get("direction") or "").strip().lower()
        won = bool(outcome) and bool(direction) and outcome == direction
        return {
            "won": won,
            "pnl_usd": d.get("pnl_usd"),
            # Sniper-v5 stake is the actual placed dollar size, NOT
            # entry_qty * entry_price (a maker-arb / updown legacy computation).
            "entry_value_usd": d.get("placed_size_usd"),
            "signal": d.get("direction"),  # already UP / DOWN
            # Entry price = actual fill vwap. l25 up_vwap can be None on
            # synthetic fires; fill_vwap is always set when a fire was placed.
            "entry_price": d.get("fill_vwap"),
            "entry_qty": d.get("fill_shares"),
            "entry_strike": d.get("entry_strike") or d.get("strike"),
            "symbol": d.get("asset"),
            "fill_method": d.get("fill_method"),
        }
    # Legacy updown / maker-arb / resolver shape.
    eq = d.get("entry_qty")
    ep = d.get("entry_price")
    return {
        "won": bool(d.get("won")),
        "pnl_usd": d.get("pnl_usd"),
        "entry_value_usd": (float(eq) * float(ep) if eq and ep else None),
        "signal": d.get("signal"),
        "entry_price": ep,
        "entry_qty": eq,
        "entry_strike": d.get("entry_strike") or d.get("strike"),
        "symbol": d.get("symbol"),
        "fill_method": None,
    }


def resolution_pnl_float(d: dict[str, Any]) -> float | None:
    """Coerce a resolution payload's ``pnl_usd`` to float regardless of writer.

    Resolver writes a Decimal-exact string; sniper_v5 writes a float. Returns
    None when absent/unparseable so callers can skip cleanly.
    """
    raw = d.get("pnl_usd")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


__all__ = [
    "EventType",
    "KIND_RESOLUTION",
    "KIND_SIGNAL",
    "SNIPER_V5_RESOLVED_MARKER",
    "is_sniper_v5_shape",
    "normalize_resolution_payload",
    "resolution_pnl_float",
]
