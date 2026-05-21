"""Phase 30 — Maker-arb event types + DTOs.

Pure dataclass module for the 3 maker strategies (ACC-M, ACC-H, MAS).

Inputs are EVENTS that flow into the strategy from BookMirror / TradeMirror /
the engine's slug lifecycle; outputs are DECISIONS returned by event handlers
that the engine then routes to shadow_log (Phase 30) or to the CLOB / on-chain
executors (Phase 30.1 live).

Pitfall 5 (RESEARCH §"Zero-allocation hot path"): every EVENT dataclass is
`frozen=True, slots=True`. This bakes in:

  * No `__dict__` per instance (slots) — ~10x smaller, no random hash slot.
  * Immutability (frozen) — strategies physically cannot mutate the event
    object, even by accident. Mutation raises `FrozenInstanceError`.

Pitfall 2 (RESEARCH §"Phase 30.1 live promotion"): `OpenOrder` carries a
`clob_order_id: str | None = None` field that stays `None` in shadow mode.
When Plan 30.1 swaps to live, the CLOB-assigned ID is written back into
this field — keeping `OpenOrder.order_id` (the local "ACC-M-00000001"
form) stable for cross-reference between shadow_log and on-chain audit.

This module imports NOTHING from `engine.*`, `venues.polymarket.client`,
asyncpg, or the network. It is purely structural — safe to import from any
test, any strategy, the engine, the API layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal


# ---------------------------------------------------------------------------
# Literal type aliases
# ---------------------------------------------------------------------------

#: Outcome side — mirrors poly_mint_sell_v2/order_manager.py:71 to keep the
#: vocabulary uniform across Polymarket-touching code.
Side = Literal["up", "dn"]

#: All actions a maker strategy event handler may emit. MERGE / MINT / REDEEM
#: carry no side+price+size (they're whole-position ops). POST_BID / POST_ASK /
#: CANCEL / TAKE all carry a (side, price, size, order_id).
Action = Literal["POST_BID", "POST_ASK", "CANCEL", "MERGE", "MINT", "REDEEM", "TAKE"]

#: Taker side on a trade print — who hit the resting order.
Aggressor = Literal["buy", "sell"]


# ---------------------------------------------------------------------------
# Events (input from feeds)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class L25Update:
    """L25 book snapshot for one (slug, side). Hot path — frozen+slots.

    `bids` / `asks` are tuples of (price, size) pairs ordered best-first
    (highest bid / lowest ask at index 0). Strategies treat these as
    closed snapshots — never mutated after construction.
    """
    slug: str
    side: Side
    ts_us: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]


@dataclass(frozen=True, slots=True)
class TradePrint:
    """A trade just printed on the wire for (slug, side)."""
    slug: str
    side: Side
    ts_us: int
    price: Decimal
    size: Decimal
    aggressor: Aggressor


@dataclass(frozen=True, slots=True)
class OrderFill:
    """One of our orders filled (partial or full).

    `is_maker=True` means we received the maker rebate (we were the resting
    order); `is_maker=False` means we paid the taker fee.
    """
    slug: str
    side: Side
    ts_us: int
    order_id: str            # local ID like "ACC-M-00000001"
    price: Decimal
    size: Decimal
    is_maker: bool


@dataclass(frozen=True, slots=True)
class SlugActive:
    """A new slug just opened — strategies can start participating."""
    slug: str
    asset: str               # "BTC" / "ETH" / "SOL"
    tf: str                  # "5m" / "15m"
    ts_us: int
    condition_id: str
    token_id_up: str
    token_id_dn: str


@dataclass(frozen=True, slots=True)
class SlugResolved:
    """The slug's outcome is locked (chainlink oracle resolved)."""
    slug: str
    ts_us: int
    winner: Side


# ---------------------------------------------------------------------------
# Decisions (output to executor / shadow_log)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Decision:
    """Output of strategy event handlers. NEVER mutated; logged to CSV.

    Field order is aligned with `SHADOW_LOG_COLUMNS` ordering used in
    Plan 30-08's CSV logger (see RESEARCH §"Code Examples" lines 605-720).

    For MERGE / MINT / REDEEM, `side` + `price` + `size` + `order_id` are
    all `None` (those are whole-position ops with no per-side parameters).
    For POST_BID / POST_ASK / CANCEL / TAKE, all 4 are populated.
    """
    ts_us: int
    strategy: str            # "ACC-M" / "ACC-H" / "MAS"
    slug: str
    asset: str
    tf: str
    action: Action
    side: Side | None
    price: Decimal | None
    size: Decimal | None
    order_id: str | None     # local ID — Pitfall 2: Phase 30.1 swaps to CLOB ID
    trigger_reason: str


# ---------------------------------------------------------------------------
# Mutable per-strategy state DTOs
# ---------------------------------------------------------------------------

@dataclass
class OpenOrder:
    """A posted-but-not-yet-filled order, tracked inside `SlugState.open_orders`.

    Mutable: when a partial fill lands, the engine decrements `size` directly
    (the engine — never the strategy — mutates this).

    Pitfall 2 forward-compat: `clob_order_id` is `None` in shadow mode. Phase
    30.1 live promotion writes the CLOB-assigned ID here so that the local
    `order_id` (ACC-M-00000001 format, stable across logs) cross-references
    cleanly with on-chain settlement.
    """
    order_id: str
    side: Side
    price: Decimal
    size: Decimal
    ts_posted_us: int
    clob_order_id: str | None = None  # Phase 30.1 live: CLOB-assigned; shadow: None


@dataclass
class SlugState:
    """Per-(strategy, slug) mutable state — owned by one strategy instance.

    Tracks inventory both sides, accumulated cash flows, open orders,
    rebates / fees, and counters used for sanity-checks + dashboard display.

    Subclass-specific rolling-history collections (e.g. ACC-H's recent_asks
    deques) are set up by the concrete strategy in its own state-init code —
    `SlugState` stays minimal here to keep the structural contract pure.
    """
    slug: str
    condition_id: str
    token_id_up: str
    token_id_dn: str
    asset: str
    tf: str
    slug_active_ts_us: int

    # Inventory
    inv_up: Decimal = Decimal(0)
    inv_dn: Decimal = Decimal(0)

    # Open orders (keyed by local order_id)
    open_orders: dict[str, OpenOrder] = field(default_factory=dict)

    # Cash accounting (per-slug, additive)
    cash_spent: Decimal = Decimal(0)         # USDC paid for shares (ACC bids hit)
    cash_received: Decimal = Decimal(0)      # USDC from share sales (MAS asks lifted)
    rebates_received: Decimal = Decimal(0)   # maker rebates collected
    taker_fees_paid: Decimal = Decimal(0)    # taker fees outgoing

    # Activity counters
    n_fills: int = 0
    n_cancels: int = 0
    n_merges: int = 0

    # Phase 31 — PAT taker overlay (TV_AGENT_CHANGES §1).
    # Track per-slug fire count + last-fire timestamp for the PAT trigger
    # rate limit. PAT fires both sides simultaneously, so a single counter
    # per slug (not per-side) — matches spec's "ss_up.n_pat_fires +=1;
    # ss_dn.n_pat_fires += 1" intent (they always increment together).
    n_pat_fires: int = 0
    last_pat_fire_us: int = 0

    # Phase 31 — ACC-PC pair-completion taker (TV_AGENT_CHANGES §4).
    # Per-slug counter + last-fire ts for the PC trigger rate limit.
    # CVD window is per-side and held on the strategy instance (NOT on
    # SlugState) because dataclass instantiation with a mutable default is
    # error-prone — strategies manage their own per-(slug, side) deques.
    n_pc_taker: int = 0
    last_pc_taker_us: int = 0


__all__ = [
    # Literals
    "Action",
    "Aggressor",
    "Side",
    # Events
    "L25Update",
    "OrderFill",
    "SlugActive",
    "SlugResolved",
    "TradePrint",
    # Decision
    "Decision",
    # State DTOs
    "OpenOrder",
    "SlugState",
]
