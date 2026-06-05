"""Sleeve registry — single source of truth for sleeve identity + taxonomy.

Phase 37 Wave 2. Every layer (API manifest, allowlists, endpoints, frontend
grouping, deprecation lifecycle) historically re-derived its own notion of
"what is this sleeve" from a ``poly_updown_`` prefix regex. This module is the
ONE place that:

1. Knows which prefixes are Polymarket sleeves (``POLY_SLEEVE_PREFIXES``).
2. Parses a ``sleeve_id`` into ``(symbol, tf)`` (``parse_sym_tf``).
3. Classifies a ``sleeve_id`` into its full taxonomy (``classify``):
   ``{class, family, subfamily, symbol, tf, variant, shadow, inverse}``.
4. Builds an enumerable registry of ``SleeveRecord``s with lifecycle status
   (``build_registry``), seeded from the caller's live + deprecated id lists.

Taxonomy (operator-stated 2026-05-29): **all Polymarket UpDown sleeves are ONE
class = ``updown``**. ``sniper_v5`` is a *family* of UpDown strategies, and
``V5/V6/V7/V8/V9/vL/H`` are *sub-families* inside it. ``symbol``/``tf``/``variant``
are parsed ONCE here — downstream never re-derives them from a prefix regex.

**Layering:** this module is pure (stdlib only). It does NOT import from
``backend.app.api`` or the engine — the API/engine pass their id lists in. This
keeps ``strategies`` free of upward dependencies and avoids the
``sleeves`` ↔ ``bots`` import cycle.

**Migration rule:** legacy ``sleeve_id``s are NEVER renamed (they are the
``trading.events`` join key). The registry MAPS each existing id to its
taxonomy; grouping/labelling/search read the mapped fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

# ---------------------------------------------------------------------------
# Prefixes + identity
# ---------------------------------------------------------------------------

#: Every Polymarket-family sleeve_id prefix. Order is irrelevant (disjoint).
POLY_SLEEVE_PREFIXES: Final[tuple[str, ...]] = (
    "poly_updown_",
    "poly-updown-",          # legacy uppercase-coerced form (Bots screen)
    "poly_sniper_v5_",
    "poly_fast_taker_",      # oracle-lag directional taker A/B (shadow, 2026-05-29)
    "shadow_poly_updown_",   # Shadow9 + fade/overlay paper sleeves
    "poly_acc_m_",           # maker-arb (not on VPS3, kept for parity)
    "poly_acc_h_",
    "poly_mas_",
)


def is_polymarket_sleeve(sleeve_id: str) -> bool:
    """True for any Polymarket-family sleeve_id (updown / sniper_v5 / shadow / maker)."""
    return sleeve_id.lower().startswith(POLY_SLEEVE_PREFIXES)


#: Kalshi sleeve_id prefixes (Phase 38). Kalshi runs the SAME updown strategy
#: class on a different venue; `venue='kalshi'` distinguishes it.
KALSHI_SLEEVE_PREFIXES: Final[tuple[str, ...]] = ("kalshi_sniper_", "kalshi_")


def is_kalshi_sleeve(sleeve_id: str) -> bool:
    """True for any Kalshi sleeve_id (Phase 38)."""
    return sleeve_id.lower().startswith(KALSHI_SLEEVE_PREFIXES)


def parse_sym_tf(sleeve_id: str) -> tuple[str, str] | None:
    """Extract ``(SYM_UPPER, tf)`` from a Polymarket sleeve_id.

    Layouts (underscore-split):
    - ``poly_updown_<sym>_<tf>_<variant>[_LIVE]``        → parts[2], parts[3]
    - ``poly_sniper_v5_<sym>_<tf>_<descriptor>``          → parts[3], parts[4]
    - ``shadow_poly_updown_<sym>_<tf>_<variant>``         → parts[3], parts[4]
    - ``poly_acc_m_<sym>_<tf>_*`` / ``poly_acc_h_<sym>_<tf>_*`` → parts[3], parts[4]
    - ``poly_mas_<sym>_<tf>_*``                           → parts[2], parts[3]

    ``sym`` may be ``ALL`` for fan-out shadow sleeves. Returns None when the
    layout doesn't match (caller should 404/422).
    """
    parts = sleeve_id.split("_")
    if sleeve_id.startswith("poly_updown_"):
        if len(parts) < 4:
            return None
        return parts[2].upper(), parts[3]
    # fast_taker: ``poly_fast_taker_<config>_<merge>_<sym>_<tf>`` — sym/tf are the
    # LAST two tokens (the config descriptor sits in the middle, unlike the other
    # families where sym/tf follow the prefix).
    if sleeve_id.startswith("poly_fast_taker_"):
        if len(parts) < 6:
            return None
        return parts[-2].upper(), parts[-1]
    if sleeve_id.startswith("poly_sniper_v5_"):
        if len(parts) < 5:
            return None
        return parts[3].upper(), parts[4]
    if sleeve_id.startswith("shadow_poly_updown_"):
        if len(parts) < 5:
            return None
        return parts[3].upper(), parts[4]
    if sleeve_id.startswith(("poly_acc_m_", "poly_acc_h_")):
        if len(parts) < 5:
            return None
        return parts[3].upper(), parts[4]
    if sleeve_id.startswith("poly_mas_"):
        if len(parts) < 4:
            return None
        return parts[2].upper(), parts[3]
    # Kalshi: ``kalshi_sniper_<sym>_<tf>_<variant>`` → parts[2], parts[3]
    if sleeve_id.startswith("kalshi_sniper_"):
        if len(parts) < 5:
            return None
        return parts[2].upper(), parts[3]
    return None


def _variant_tokens(sleeve_id: str) -> list[str]:
    """Tokens AFTER ``<prefix><sym>_<tf>_`` — the strategy variant descriptor."""
    parts = sleeve_id.split("_")
    if sleeve_id.startswith("poly_updown_"):
        return parts[4:]          # poly, updown, sym, tf, ...
    # fast_taker variant = config tokens between prefix and trailing sym_tf
    # (e.g. ["a25","merge"] / ["b2","nomerge"]).
    if sleeve_id.startswith("poly_fast_taker_"):
        return parts[3:-2]
    if sleeve_id.startswith("poly_sniper_v5_"):
        return parts[5:]          # poly, sniper, v5, sym, tf, ...
    if sleeve_id.startswith("shadow_poly_updown_"):
        return parts[5:]          # shadow, poly, updown, sym, tf, ...
    if sleeve_id.startswith(("poly_acc_m_", "poly_acc_h_")):
        return parts[5:]
    if sleeve_id.startswith("poly_mas_"):
        return parts[4:]
    if sleeve_id.startswith("kalshi_sniper_"):
        return parts[4:]          # kalshi, sniper, sym, tf, ...
    return []


# ---------------------------------------------------------------------------
# Taxonomy + classification
# ---------------------------------------------------------------------------

SLEEVE_CLASS_UPDOWN: Final[str] = "updown"

#: sniper_v5 sub-family markers, highest precedence first.
_SNIPER_V5_SUBFAMILY_ORDER: Final[tuple[str, ...]] = ("vL", "H", "v9", "v8", "v7", "v6")


class SleeveStatus(str, Enum):
    """Lifecycle status. ``deprecated``/``archived`` sleeves keep their record
    (enumerable + searchable) but are skipped for live construction (Wave 5)."""

    LIVE = "live"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class SleeveTaxonomy:
    sleeve_id: str
    sleeve_class: str          # "updown" for Polymarket + Kalshi UpDown sleeves
    family: str                # volume | sniper | v3 | v4 | momo | momo_v2 | vwap | sniper_v5 | kelly | prewindow | fade | ...
    subfamily: str | None      # sniper_v5 only: V5 | V6 | V7 | V8 | V9 | vL | H
    symbol: str | None         # BTC | ETH | SOL | ALL (None if unparseable)
    tf: str | None             # 5m | 15m | 1h | ... (None if unparseable)
    variant: str               # raw descriptor tokens joined by "_"
    shadow: bool               # shadow_poly_updown_* paper sleeve
    inverse: bool              # carries an _INV / _INV_NIGHT / _DOWN_INV marker
    venue: str = "poly"        # poly | kalshi | hl | unknown — the trading venue


def _sniper_v5_subfamily(tokens: list[str]) -> str:
    if tokens and tokens[-1] == "vL":
        return "vL"
    if tokens and tokens[-1] == "H":
        return "H"
    for marker in ("v9", "v8", "v7", "v6"):
        if marker in tokens:
            return marker.upper()
    return "V5"


def _detect_family(variant: str, *, is_sniper_v5: bool, is_shadow: bool) -> str:
    v = variant.lower()
    if is_sniper_v5:
        return "sniper_v5"
    if is_shadow:
        if "kelly" in v:
            return "kelly"
        if "prewindow" in v:
            return "prewindow"
        if "fade" in v:
            return "fade"
        # otherwise fall through to underlying-strategy detection below
    if "momo_v2" in v:
        return "momo_v2"
    if "momo" in v:
        return "momo"
    if "vwap" in v:
        return "vwap"
    if v.startswith("v3"):
        return "v3"
    if v.startswith("v4"):
        return "v4"
    if "sniper" in v:
        return "sniper"
    if "volume" in v:
        return "volume"
    return v.split("_")[0] if v else "base"


def classify(sleeve_id: str) -> SleeveTaxonomy:
    """Map a Polymarket sleeve_id to its full taxonomy. Pure + total.

    For non-Polymarket ids the family falls back to ``"unknown"`` with None
    symbol/tf — callers should gate on ``is_polymarket_sleeve`` first.
    """
    is_sniper_v5 = sleeve_id.startswith("poly_sniper_v5_")
    is_fast_taker = sleeve_id.startswith("poly_fast_taker_")
    is_shadow = sleeve_id.startswith("shadow_poly_updown_")
    is_kalshi = is_kalshi_sleeve(sleeve_id)
    sym_tf = parse_sym_tf(sleeve_id)
    symbol = sym_tf[0] if sym_tf else None
    tf = sym_tf[1] if sym_tf else None
    tokens = _variant_tokens(sleeve_id)
    variant = "_".join(tokens)

    if not is_polymarket_sleeve(sleeve_id) and not is_kalshi:
        return SleeveTaxonomy(
            sleeve_id=sleeve_id, sleeve_class="unknown", family="unknown",
            subfamily=None, symbol=symbol, tf=tf, variant=variant,
            shadow=False, inverse=False, venue="unknown",
        )

    family = _detect_family(variant, is_sniper_v5=is_sniper_v5, is_shadow=is_shadow)
    if is_fast_taker:
        # oracle-lag directional taker family; subfamily = the config token
        # (a25 = Config A merge-mimic $25; b2 = Config B no-merge $2).
        family = "fast_taker"
    if is_kalshi:
        # kalshi_sniper_* → sniper family on the kalshi venue (same updown class).
        family = "sniper"
    subfamily = _sniper_v5_subfamily(tokens) if is_sniper_v5 else None
    if is_fast_taker:
        subfamily = tokens[0].upper() if tokens else None
    inverse = any(t.upper() == "INV" for t in tokens) or "_inv" in f"_{variant.lower()}"

    return SleeveTaxonomy(
        sleeve_id=sleeve_id,
        sleeve_class=SLEEVE_CLASS_UPDOWN,
        family=family,
        subfamily=subfamily,
        symbol=symbol,
        tf=tf,
        variant=variant,
        shadow=is_shadow,
        inverse=inverse,
        venue="kalshi" if is_kalshi else "poly",
    )


# ---------------------------------------------------------------------------
# Registry records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SleeveRecord:
    taxonomy: SleeveTaxonomy
    status: SleeveStatus
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def sleeve_id(self) -> str:
        return self.taxonomy.sleeve_id


def build_registry(
    live_ids: tuple[str, ...] | list[str],
    deprecated_ids: frozenset[str] | set[str] | None = None,
    *,
    archived_ids: frozenset[str] | set[str] | None = None,
    params_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, SleeveRecord]:
    """Build the enumerable registry from the caller's id lists.

    The API layer passes its resolved ``_POLY_UPDOWN_SLEEVE_IDS`` (the live set)
    plus the deprecated/archived id sets. Deprecated/archived sleeves are KEPT
    as records (enumerable + searchable) with their status — they are not
    silently dropped. This is the seam Wave 5 (lifecycle) builds on.
    """
    deprecated = frozenset(deprecated_ids or ())
    archived = frozenset(archived_ids or ())
    params_by_id = params_by_id or {}

    registry: dict[str, SleeveRecord] = {}
    # Union so deprecated/archived ids missing from live_ids still get a record.
    for sid in (*live_ids, *deprecated, *archived):
        if sid in registry:
            continue
        if sid in archived:
            status = SleeveStatus.ARCHIVED
        elif sid in deprecated:
            status = SleeveStatus.DEPRECATED
        else:
            status = SleeveStatus.LIVE
        registry[sid] = SleeveRecord(
            taxonomy=classify(sid),
            status=status,
            params=params_by_id.get(sid, {}),
        )
    return registry


__all__ = [
    "KALSHI_SLEEVE_PREFIXES",
    "POLY_SLEEVE_PREFIXES",
    "SLEEVE_CLASS_UPDOWN",
    "SleeveRecord",
    "SleeveStatus",
    "SleeveTaxonomy",
    "build_registry",
    "classify",
    "is_kalshi_sleeve",
    "is_polymarket_sleeve",
    "parse_sym_tf",
]
