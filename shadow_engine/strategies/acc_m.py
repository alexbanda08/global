"""ACC-M: Maker Pair Arbitrage (BID-only).

Strategy:
- Post limit BIDs on Up + Down sides when sum_bids < $1
- Maintain strict inventory balance (max 5-share imbalance)
- Cancel orders if displaced > 3¢ OR age > 20s
- Merge paired inventory continuously when min(inv_up, inv_dn) >= 5
- Redeem leftover single-side at slug resolution

Reference: TV_DEPLOY_SPEC_ACC_M_2026_05_18.md
"""
from __future__ import annotations

from typing import Any

from ..base import (
    Decision, SlugActive, L25Update, OrderFill, SlugResolved,
    Side, Action, maker_rebate_per_share, to_cents,
)
from .base import StrategyBase


class AccMStrategy(StrategyBase):
    """Pure maker pair-arbitrage strategy."""

    code = "ACC-M"

    DEFAULTS = {
        # Capital
        "wallet_seed_usdc": 50.0,
        "RESERVE_USDC": 5.0,

        # Posting
        "POST_SIZE": 5.0,
        "MIN_BID_PRICE": 0.05,
        "MAX_BID_PRICE": 0.95,
        "MAX_SUM_BIDS": 1.00,
        "MAX_SPREAD_PER_LEG": 0.05,

        # Cancel rules
        "CANCEL_THRESHOLD": 0.03,
        "MAX_ORDER_AGE_S": 20.0,
        "CANCEL_ON_FILL": False,
        "CANCEL_ON_CLOSE": False,

        # Inventory balance
        "MAX_IMBALANCE_SHARES": 5.0,
        "ABSOLUTE_MAX_INVENTORY": 50.0,

        # Merging
        "MERGE_THRESHOLD_PAIRS": 5,
        "STOP_POST_BUFFER_S": 30.0,

        # Cells
        "cells": ["btc_5m", "btc_15m"],
    }

    def __init__(self, config: dict[str, Any]):
        merged = {**self.DEFAULTS, **config}
        super().__init__(merged)

    # ============================================================
    # Decision pipeline
    # ============================================================

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        decisions: list[Decision] = []

        # 1. Check cancel rules for each open order
        decisions.extend(self._cancel_decisions(state, evt))

        # 2. Check post rules per side
        decisions.extend(self._post_decisions(state, evt))

        # 3. Check merge trigger
        decisions.extend(self._merge_decisions(state, evt.ts_us))

        return decisions

    # ============================================================
    # Cancel rules
    # ============================================================

    def _cancel_decisions(self, state, evt: L25Update) -> list[Decision]:
        decisions = []
        cancel_threshold = self.config["CANCEL_THRESHOLD"]
        max_age_s = self.config["MAX_ORDER_AGE_S"]

        for order_id in list(state.open_orders.keys()):
            order = state.open_orders[order_id]
            book = evt.up if order.side == Side.UP else evt.dn

            # Rule 1: displacement
            if order.is_bid:
                displacement = abs(order.price - book.best_bid)
            else:
                displacement = abs(order.price - book.best_ask)

            if displacement >= cancel_threshold:
                decisions.append(self._cancel_order(
                    state.slug, order_id, evt.ts_us, "displacement"))
                continue

            # Rule 2: age
            age_s = (evt.ts_us - order.posted_us) / 1_000_000
            if age_s >= max_age_s:
                decisions.append(self._cancel_order(
                    state.slug, order_id, evt.ts_us, "age"))

        return decisions

    # ============================================================
    # Post rules
    # ============================================================

    def _post_decisions(self, state, evt: L25Update) -> list[Decision]:
        # Filter: stop posting near close
        elapsed_s = self._slug_offset_s(state.slug, evt.ts_us)
        stop_buffer = self.config["STOP_POST_BUFFER_S"]
        if elapsed_s > state.slug_duration_s - stop_buffer:
            return []

        # Filter: spread per leg
        max_spread = self.config["MAX_SPREAD_PER_LEG"]
        if evt.up.spread > max_spread or evt.dn.spread > max_spread:
            return []

        # Filter: sum_bids must be < $1 for edge to exist
        sum_bids = evt.up.best_bid + evt.dn.best_bid
        if sum_bids >= self.config["MAX_SUM_BIDS"]:
            return []

        decisions = []
        for side, book in [(Side.UP, evt.up), (Side.DOWN, evt.dn)]:
            decision = self._maybe_post_bid(state, side, book, evt.ts_us)
            if decision:
                decisions.append(decision)

        return decisions

    def _maybe_post_bid(self, state, side: Side, book, ts_us: int):
        bid_price = book.best_bid
        min_price = self.config["MIN_BID_PRICE"]
        max_price = self.config["MAX_BID_PRICE"]
        post_size = self.config["POST_SIZE"]

        # Filter: price band
        if not (min_price <= bid_price <= max_price):
            return None

        # Filter: inventory balance
        max_imbalance = self.config["MAX_IMBALANCE_SHARES"]
        if side == Side.UP:
            if state.inv_up > state.inv_dn + max_imbalance:
                return None  # already too much Up
        else:
            if state.inv_dn > state.inv_up + max_imbalance:
                return None

        # Filter: hard cap
        cap = self.config["ABSOLUTE_MAX_INVENTORY"]
        current_inv = state.inv_up if side == Side.UP else state.inv_dn
        if current_inv >= cap:
            return None

        # Filter: already have an open BID on this side at same price
        for order in state.open_orders.values():
            if (order.is_bid and order.side == side
                    and to_cents(order.price) == to_cents(bid_price)):
                return None  # already have this exact order open

        # Filter: wallet balance
        reserve = self.config["RESERVE_USDC"]
        required = post_size * bid_price
        if self.wallet_balance < required + reserve:
            return None

        # Filter: cancel any STALE open BID on this side (different price)
        # Wait — actually cancel logic handles this. Only post if no current
        # bid exists on this side.
        for order in state.open_orders.values():
            if order.is_bid and order.side == side:
                return None  # already have a bid on this side, don't double-post

        return self._post_only_order(
            slug=state.slug,
            side=side,
            is_bid=True,
            price=bid_price,
            size=post_size,
            ts_us=ts_us,
            reason="post_bid_paired_arb",
        )

    # ============================================================
    # Merge rules
    # ============================================================

    def _merge_decisions(self, state, ts_us: int) -> list[Decision]:
        threshold = self.config["MERGE_THRESHOLD_PAIRS"]
        pairs = int(min(state.inv_up, state.inv_dn))
        if pairs < threshold:
            return []
        # Recycle the recovered USDC into wallet balance (shadow mode tracking)
        self.wallet_balance += pairs * 1.0
        return [self._merge_decision(state.slug, pairs, ts_us)]

    # ============================================================
    # Fill handling
    # ============================================================

    def on_order_fill(self, evt: OrderFill) -> list[Decision]:
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        # Update inventory
        if evt.side == Side.UP:
            state.inv_up += evt.fill_size
            state.fill_count_up += 1
        else:
            state.inv_dn += evt.fill_size
            state.fill_count_dn += 1

        # Update cash (we BOUGHT shares at fill_price)
        state.cash_spent += evt.fill_size * evt.fill_price
        state.rebates += evt.fill_size * maker_rebate_per_share(evt.fill_price)

        # Deduct from wallet (shadow tracking)
        self.wallet_balance -= evt.fill_size * evt.fill_price
        self.wallet_balance += evt.fill_size * maker_rebate_per_share(evt.fill_price)

        # Update open order tracking
        order = state.open_orders.get(evt.order_id)
        if order:
            order.remaining = max(0.0, order.remaining - evt.fill_size)
            if order.remaining <= 0:
                del state.open_orders[evt.order_id]

        # Check merge trigger immediately (don't wait for next L25)
        return self._merge_decisions(state, evt.ts_us)

    # ============================================================
    # Slug resolution
    # ============================================================

    def on_slug_resolved(self, evt: SlugResolved) -> list[Decision]:
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        decisions = []

        # 1. Force final merge of any paired inventory
        pairs = int(min(state.inv_up, state.inv_dn))
        if pairs > 0:
            decisions.append(self._merge_decision(state.slug, pairs, evt.settlement_ts_us))
            self.wallet_balance += pairs * 1.0

        # 2. Cancel any remaining open orders (cleanup)
        for order_id in list(state.open_orders.keys()):
            decisions.append(self._cancel_order(
                state.slug, order_id, evt.settlement_ts_us, "slug_end_cleanup"))

        # 3. Redeem leftover single-side
        decisions.extend(self._redeem_decision(state.slug, evt.outcome, evt.settlement_ts_us))

        # Pop state (cleanup)
        self.slug_states.pop(evt.slug, None)

        return decisions
