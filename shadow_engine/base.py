"""Core types for the shadow engine.

Events come IN from feeds, Decisions go OUT to executors.
SlugState tracks per-slug position for each strategy instance.

Designed for zero-allocation in hot path: dataclasses with __slots__,
integer-cent price quantization, msgspec-compatible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional


# ============================================================
# Constants
# ============================================================

CENT = 0.01
CENT_INT = 1                       # in cents
PRICE_TICK_CENTS = 1               # CLOB minimum price increment
SHARE_TICK = 1                     # CLOB minimum share increment
CLOB_MIN_ORDER_SHARES = 5          # Polymarket CLOB minimum

# Fee model (verified)
TAKER_FEE_RATE = 0.07              # 7% per share at p=0.5
MAKER_REBATE_SHARE = 0.20          # 20% of taker fee, paid to maker

# Conversion helpers (integer-cent quantization for hot path)
def to_cents(price: float) -> int:
    """Round price to integer cents."""
    return int(round(price * 100))


def from_cents(cents: int) -> float:
    """Convert integer cents back to float price."""
    return cents / 100.0


def taker_fee_per_share(price: float) -> float:
    """Polymarket taker fee curve."""
    p = max(0.0, min(1.0, price))
    return TAKER_FEE_RATE * p * (1.0 - p)


def maker_rebate_per_share(price: float) -> float:
    """Polymarket maker rebate (20% of taker fee equivalent)."""
    return MAKER_REBATE_SHARE * taker_fee_per_share(price)


# ============================================================
# Sides + Outcomes
# ============================================================

class Side(IntEnum):
    UP = 0
    DOWN = 1

    @property
    def other(self) -> "Side":
        return Side.DOWN if self == Side.UP else Side.UP

    def as_str(self) -> str:
        return "Up" if self == Side.UP else "Down"

    @classmethod
    def from_str(cls, s: str) -> "Side":
        return cls.UP if s == "Up" else cls.DOWN


class Action(IntEnum):
    """Strategy decision types."""
    NOOP = 0
    POST_BID = 1
    POST_ASK = 2
    CANCEL = 3
    MARKET_BUY = 4
    MARKET_SELL = 5
    MINT = 6
    MERGE = 7
    REDEEM = 8


# ============================================================
# Events (from feeds)
# ============================================================

@dataclass(slots=True)
class SlugActive:
    """Slug just became active — strategies can start participating."""
    slug: str
    asset: str           # "btc", "eth", "sol"
    tf: str              # "5m", "15m"
    slot_start_us: int
    slot_end_us: int
    condition_id: Optional[str] = None


@dataclass(slots=True)
class L25Snapshot:
    """L25 book snapshot for a single (slug, outcome)."""
    slug: str
    outcome: Side
    ts_us: int
    ask_prices: list[float]   # best 25 levels (price descending? ascending?)
    ask_sizes: list[float]
    bid_prices: list[float]
    bid_sizes: list[float]

    @property
    def best_ask(self) -> float:
        return self.ask_prices[0] if self.ask_prices else float("nan")

    @property
    def best_bid(self) -> float:
        return self.bid_prices[0] if self.bid_prices else float("nan")

    @property
    def best_ask_size(self) -> float:
        return self.ask_sizes[0] if self.ask_sizes else 0.0

    @property
    def best_bid_size(self) -> float:
        return self.bid_sizes[0] if self.bid_sizes else 0.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def mid(self) -> float:
        return (self.best_ask + self.best_bid) / 2.0


@dataclass(slots=True)
class L25Update:
    """L25 update covering BOTH sides of a slug."""
    slug: str
    ts_us: int
    up: L25Snapshot
    dn: L25Snapshot


@dataclass(slots=True)
class TradePrint:
    """A trade just printed on the wire."""
    slug: str
    outcome: Side
    ts_us: int
    price: float
    size: float
    taker_side: str          # "buy" or "sell"


@dataclass(slots=True)
class OrderFill:
    """Our order was filled (partial or full)."""
    slug: str
    order_id: str
    side: Side
    is_maker: bool
    fill_size: float
    fill_price: float
    ts_us: int


@dataclass(slots=True)
class SlugResolved:
    """Slug resolved by chainlink."""
    slug: str
    outcome: Side
    settlement_ts_us: int


@dataclass(slots=True)
class WalletBalance:
    """Wallet balance update."""
    usdc_balance: float
    last_updated_us: int


# ============================================================
# Decisions (to executors)
# ============================================================

@dataclass(slots=True)
class Decision:
    """A strategy decision to be executed (or shadow-logged)."""
    strategy_code: str
    action: Action
    slug: str
    ts_us: int
    side: Optional[Side] = None
    price: Optional[float] = None
    size: Optional[float] = None
    notional: Optional[float] = None
    order_id: Optional[str] = None       # for CANCEL
    pairs: Optional[int] = None          # for MERGE
    condition_id: Optional[str] = None   # for MINT / REDEEM
    reason: str = ""                     # human-readable trigger


# ============================================================
# Per-strategy per-slug state
# ============================================================

@dataclass(slots=True)
class OpenOrder:
    """Tracks a posted (but not yet filled/cancelled) order."""
    order_id: str
    slug: str
    side: Side
    price: float
    size: float                          # original size
    remaining: float                     # unfilled portion
    posted_us: int
    is_bid: bool                         # True for BID, False for ASK


@dataclass(slots=True)
class SlugState:
    """Per-slug position tracking inside a strategy instance."""
    slug: str
    asset: str
    tf: str
    slot_start_us: int
    slot_end_us: int
    condition_id: Optional[str] = None

    # Inventory
    inv_up: float = 0.0
    inv_dn: float = 0.0

    # Cash accounting
    mint_cost: float = 0.0               # USDC spent on mint (MAS)
    cash_spent: float = 0.0              # USDC paid for shares (ACC)
    cash_received: float = 0.0           # USDC from share sales (MAS)
    cash_recovered: float = 0.0          # USDC from merge (ACC)
    rebates: float = 0.0                 # maker rebates earned
    taker_fees: float = 0.0              # taker fees paid

    # Counters
    fill_count_up: int = 0
    fill_count_dn: int = 0
    taker_buy_count_up: int = 0
    taker_buy_count_dn: int = 0
    merge_count: int = 0
    pairs_merged: float = 0.0

    # Open orders by order_id
    open_orders: dict[str, OpenOrder] = field(default_factory=dict)

    # Timestamps
    last_post_ts_us: int = 0
    last_merge_ts_us: int = 0
    last_taker_buy_us: dict[Side, int] = field(default_factory=dict)

    # ACC-H specific: rolling ask history per side (last 60s of asks)
    recent_asks_up: list[tuple[int, float]] = field(default_factory=list)
    recent_asks_dn: list[tuple[int, float]] = field(default_factory=list)

    @property
    def paired_inventory(self) -> float:
        return min(self.inv_up, self.inv_dn)

    @property
    def imbalance(self) -> float:
        """Positive = more Up; negative = more Down."""
        return self.inv_up - self.inv_dn

    @property
    def total_inventory(self) -> float:
        return self.inv_up + self.inv_dn

    @property
    def slug_duration_s(self) -> int:
        return (self.slot_end_us - self.slot_start_us) // 1_000_000

    def slug_pnl(self) -> float:
        """Current realized PnL (without slug-end redemption)."""
        return self.cash_received + self.cash_recovered + self.rebates \
               - self.cash_spent - self.mint_cost - self.taker_fees

    def slug_pnl_with_settlement(self, outcome: Side) -> float:
        """Final PnL including settlement redemption of leftover."""
        redeem = 0.0
        if outcome == Side.UP and self.inv_up > 0:
            redeem = self.inv_up * 1.0
        elif outcome == Side.DOWN and self.inv_dn > 0:
            redeem = self.inv_dn * 1.0
        return self.slug_pnl() + redeem
