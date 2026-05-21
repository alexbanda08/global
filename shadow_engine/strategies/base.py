"""StrategyBase — interface all strategy modules implement.

Lifecycle:
    1. on_slug_active(slug)            — decide MINT (MAS only)
    2. on_l25_update(slug, books)      — decide POST_BID / POST_ASK / CANCEL / MARKET_BUY
    3. on_trade_print(slug, tick)      — react to taker prints (history tracking)
    4. on_order_fill(...)              — update inventory + check merge trigger
    5. on_slug_resolved(slug, outcome) — final merge + redeem + log PnL
"""
from __future__ import annotations

import uuid
from typing import Any

from ..base import (
    Decision, OpenOrder, SlugState, SlugActive, L25Update, TradePrint,
    OrderFill, SlugResolved, WalletBalance, Side, Action,
)


class StrategyBase:
    """Base class for all strategies. Override the relevant handlers."""

    code: str = "BASE"             # override in subclass

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.shadow_mode = bool(config.get("shadow_mode", True))
        self.wallet_balance: float = float(config.get("wallet_seed_usdc", 50.0))
        self.slug_states: dict[str, SlugState] = {}
        self._order_counter = 0

    # ============================================================
    # Event handlers — override in subclass
    # ============================================================

    def on_slug_active(self, evt: SlugActive) -> list[Decision]:
        """Slug just became active. Initialize state. (MAS: emit MINT here.)"""
        if not self._cell_enabled(evt.asset, evt.tf):
            return []
        state = SlugState(
            slug=evt.slug,
            asset=evt.asset,
            tf=evt.tf,
            slot_start_us=evt.slot_start_us,
            slot_end_us=evt.slot_end_us,
            condition_id=evt.condition_id,
        )
        self.slug_states[evt.slug] = state
        return []

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        """L25 update for an active slug. Default: noop."""
        return []

    def on_trade_print(self, evt: TradePrint) -> list[Decision]:
        """Trade just printed. Track for history (ACC-H needs this)."""
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []
        # Track recent asks (for ACC-H discount-capture)
        # Actually trade prices != ask prices, but we use them as a noisy proxy.
        # For ACC-H, ask history should come from L25 updates.
        return []

    def on_order_fill(self, evt: OrderFill) -> list[Decision]:
        """One of our orders filled. Update inventory + check merge."""
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        order = state.open_orders.get(evt.order_id)
        if order:
            order.remaining = max(0.0, order.remaining - evt.fill_size)
            if order.remaining <= 0:
                # Order fully consumed
                del state.open_orders[evt.order_id]

        return []

    def on_slug_resolved(self, evt: SlugResolved) -> list[Decision]:
        """Slug resolved. Final merge + redeem leftover."""
        state = self.slug_states.pop(evt.slug, None)
        if state is None:
            return []
        return []

    def on_wallet_balance(self, evt: WalletBalance) -> None:
        """Track wallet balance updates."""
        self.wallet_balance = evt.usdc_balance

    # ============================================================
    # Helpers
    # ============================================================

    def _next_order_id(self) -> str:
        """Generate a unique order id (shadow mode)."""
        self._order_counter += 1
        return f"{self.code}-{self._order_counter:08d}"

    def _cell_enabled(self, asset: str, tf: str) -> bool:
        """Check if this cell is enabled in config."""
        cell = f"{asset}_{tf}"
        cells = self.config.get("cells", [])
        return cell in cells

    def _slug_offset_s(self, slug: str, ts_us: int) -> float:
        """Seconds since slot_start for given slug at given time."""
        state = self.slug_states.get(slug)
        if state is None:
            return 0.0
        return (ts_us - state.slot_start_us) / 1_000_000

    def _post_only_order(self, slug: str, side: Side, is_bid: bool,
                          price: float, size: float, ts_us: int,
                          reason: str = "") -> Decision:
        """Build a POST_BID or POST_ASK decision + track in state."""
        order_id = self._next_order_id()
        state = self.slug_states[slug]
        order = OpenOrder(
            order_id=order_id,
            slug=slug,
            side=side,
            price=price,
            size=size,
            remaining=size,
            posted_us=ts_us,
            is_bid=is_bid,
        )
        state.open_orders[order_id] = order

        return Decision(
            strategy_code=self.code,
            action=Action.POST_BID if is_bid else Action.POST_ASK,
            slug=slug,
            ts_us=ts_us,
            side=side,
            price=price,
            size=size,
            order_id=order_id,
            reason=reason,
        )

    def _cancel_order(self, slug: str, order_id: str, ts_us: int,
                       reason: str = "") -> Decision:
        """Build a CANCEL decision + remove from state."""
        state = self.slug_states[slug]
        state.open_orders.pop(order_id, None)
        return Decision(
            strategy_code=self.code,
            action=Action.CANCEL,
            slug=slug,
            ts_us=ts_us,
            order_id=order_id,
            reason=reason,
        )

    def _merge_decision(self, slug: str, pairs: int, ts_us: int) -> Decision:
        """Build a MERGE decision."""
        state = self.slug_states[slug]
        state.inv_up -= pairs
        state.inv_dn -= pairs
        state.cash_recovered += pairs * 1.0
        state.merge_count += 1
        state.pairs_merged += pairs
        state.last_merge_ts_us = ts_us

        return Decision(
            strategy_code=self.code,
            action=Action.MERGE,
            slug=slug,
            ts_us=ts_us,
            pairs=pairs,
            condition_id=state.condition_id,
            reason="merge_paired_inventory",
        )

    def _redeem_decision(self, slug: str, outcome: Side, ts_us: int) -> list[Decision]:
        """Build REDEEM decision(s) for any leftover at slug end.

        Redemption credits the wallet balance with $1 per winning share.
        Losing-side leftover is lost (we already paid for it on the fill).
        """
        state = self.slug_states.get(slug)
        if state is None:
            return []

        decisions = []
        if outcome == Side.UP and state.inv_up > 0:
            redeem_value = state.inv_up * 1.0
            decisions.append(Decision(
                strategy_code=self.code,
                action=Action.REDEEM,
                slug=slug,
                ts_us=ts_us,
                side=Side.UP,
                size=state.inv_up,
                condition_id=state.condition_id,
                reason="settlement_redeem_winner",
            ))
            state.cash_recovered += redeem_value
            self.wallet_balance += redeem_value   # CRITICAL: credit wallet
            state.inv_up = 0
        elif outcome == Side.DOWN and state.inv_dn > 0:
            redeem_value = state.inv_dn * 1.0
            decisions.append(Decision(
                strategy_code=self.code,
                action=Action.REDEEM,
                slug=slug,
                ts_us=ts_us,
                side=Side.DOWN,
                size=state.inv_dn,
                condition_id=state.condition_id,
                reason="settlement_redeem_winner",
            ))
            state.cash_recovered += redeem_value
            self.wallet_balance += redeem_value   # CRITICAL: credit wallet
            state.inv_dn = 0

        return decisions
