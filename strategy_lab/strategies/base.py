"""Strategy base class for mint-and-sell family.

Each strategy is a self-contained module that decides:
  - When to MINT inventory at slug start (and how much)
  - When/where to POST maker SELL orders
  - When/whether to MARKET-BUY as taker (for hybrid strategies)
  - When to merge leftover inventory at slug end

Shadow mode logs decisions only (no orders submitted).
Live mode submits orders via the CLOB client.

Strategy implementations live in this directory, named `mas_<code>.py`:
  - mas_a_broad.py     — pure maker, all 6 cells, small per-slug
  - mas_b_deep.py      — pure maker, BTC only, deep per-slug
  - mas_c_hybrid.py    — maker + taker, BTC+ETH
  - mas_d_*.py         — TBD after decoding 0xd44e2993

Run via shadow_runner.py or live_runner.py with a config selecting which
strategies + cells are active.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Action(str, Enum):
    """Decisions a strategy can emit on each tick."""
    MINT = "mint"                  # CTF.splitPosition at slug start
    POST_SELL = "post_sell"        # Limit maker SELL
    POST_BUY = "post_buy"          # Limit maker BUY (rare)
    MARKET_BUY = "market_buy"      # Taker buy (MAS-C and beyond)
    MARKET_SELL = "market_sell"    # Taker sell (rare)
    CANCEL = "cancel"              # Cancel an open order
    MERGE = "merge"                # CTF.mergePositions for leftover
    REDEEM = "redeem"              # CTF.redeem after settlement
    NOOP = "noop"


class Side(str, Enum):
    UP = "Up"
    DOWN = "Down"


@dataclass
class Decision:
    """A single strategy decision at a single tick."""
    strategy_code: str             # "MAS-A", "MAS-B", etc.
    action: Action
    slug: str
    asset: str                     # "btc", "eth", "sol"
    tf: str                        # "5m", "15m"
    ts_us: int                     # decision timestamp (microseconds UTC)
    side: Optional[Side] = None
    price: Optional[float] = None  # for limit orders
    size_shares: Optional[float] = None
    notional_usdc: Optional[float] = None  # for MINT
    reason: str = ""               # human-readable trigger condition


@dataclass
class SlugState:
    """Per-slug position tracking inside a strategy instance."""
    slug: str
    asset: str
    tf: str
    slot_start_us: int
    slot_end_us: int
    pre_mint_pairs: float = 0.0
    inventory_up: float = 0.0
    inventory_down: float = 0.0
    cash_usdc: float = 0.0
    rebates_usdc: float = 0.0
    mint_cost_usdc: float = 0.0
    n_post_sell_up: int = 0
    n_post_sell_dn: int = 0
    n_filled_sell_up: int = 0
    n_filled_sell_dn: int = 0
    n_taker_buy_up: int = 0
    n_taker_buy_dn: int = 0
    last_post_ts_us: int = 0
    open_orders: dict = field(default_factory=dict)  # order_id → details


@dataclass
class L25Snapshot:
    """One L25 book snapshot for a (slug, outcome)."""
    slug: str
    outcome: str               # "Up" or "Down"
    ts_us: int
    ask_prices: list[float]    # best 25 levels
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
    def size_at_best_ask(self) -> float:
        return self.ask_sizes[0] if self.ask_sizes else 0.0


@dataclass
class TradeTick:
    """One taker print observed on the wire (from trades WS)."""
    slug: str
    outcome: str
    ts_us: int
    price: float
    size: float
    taker_side: str            # "BUY" or "SELL"


@dataclass
class BinanceContext:
    """Binance kline context at a moment in time."""
    ts_us: int
    price: float
    ret_30s: float
    ret_60s: float
    ret_120s: float


class StrategyBase:
    """All strategies inherit from this. Override the relevant handlers.

    Lifecycle:
        1. on_slug_start(slug)          — decide MINT amount
        2. on_l25(snapshot)             — decide POST_SELL / CANCEL / etc.
        3. on_trade(tick)               — react to taker prints (MAS-C uses this)
        4. on_binance(ctx)              — react to underlying price moves
        5. on_order_fill(order_id, sz)  — update inventory tracking
        6. on_slug_end(slug)            — decide MERGE / REDEEM
    """

    code: str = "BASE"          # override in subclass
    cells: list[str] = []       # which cells this strategy trades

    def __init__(self, config: dict):
        self.config = config
        self.slug_states: dict[str, SlugState] = {}

    # ---- Handlers (override in subclass) ----

    def on_slug_start(self, slug: str, asset: str, tf: str,
                       slot_start_us: int, slot_end_us: int) -> list[Decision]:
        """Called once when a new slug becomes active."""
        return []

    def on_l25(self, slug: str, up_snap: L25Snapshot, dn_snap: L25Snapshot,
                state: SlugState) -> list[Decision]:
        """Called on every L25 update for this slug."""
        return []

    def on_trade(self, slug: str, tick: TradeTick, state: SlugState) -> list[Decision]:
        """Called on every taker print (MAS-C uses this for taker triggers)."""
        return []

    def on_binance(self, ctx: BinanceContext, state: SlugState) -> list[Decision]:
        """Called on Binance kline updates."""
        return []

    def on_order_fill(self, slug: str, order_id: str, filled_shares: float,
                        fill_price: float, state: SlugState) -> list[Decision]:
        """Called when one of our orders fills."""
        return []

    def on_slug_end(self, slug: str, outcome: str, state: SlugState) -> list[Decision]:
        """Called when slug resolves. Decide merge/redeem."""
        return []
