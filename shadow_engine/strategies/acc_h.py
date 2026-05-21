"""ACC-H: Hybrid Maker + Discount-Capture Taker.

Inherits ACC-M (all maker BID + cancel + merge logic) and ADDS opportunistic
market BUYs based on a composite trigger:

  Rule A (33% coverage): discount-capture
    own_ask < $0.50 AND (60s_median_ask - own_ask) > $0.03

  Rule B (33% coverage): sharp-drop
    (max(trade_prices_last_5s) - own_ask) > $0.02

  Rule C (20% coverage): early-slot
    0 <= offset_from_slot_start_s <= 60
    (only if no maker bid has filled yet on this side)

Composite covers ~70% of decoded reference-wallet taker fires.

Reference: TV_DEPLOY_SPEC_ACC_H_2026_05_18.md
"""
from __future__ import annotations

from collections import deque
from typing import Any

from ..base import (
    Decision, L25Update, TradePrint, OrderFill, SlugActive, SlugResolved,
    Side, Action, taker_fee_per_share, to_cents,
)
from .acc_m import AccMStrategy


class AccHStrategy(AccMStrategy):
    """Maker pair-arb + discount-capture taker (V2 composite trigger)."""

    code = "ACC-H"

    EXTRA_DEFAULTS = {
        # Taker sizing
        "TAKER_SIZE": 5.0,
        "MIN_S_BETWEEN_TAKER_BUYS": 5.0,
        "MAX_TAKER_BUYS_PER_SLUG": 50,

        # Rule A: Discount-capture
        "MAX_TAKER_PRICE_DISCOUNT": 0.50,
        "MIN_ASK_DROP_60S": 0.03,
        "ROLLING_WINDOW_60S": 60.0,

        # Rule B: Sharp-drop
        "MIN_TRADE_DROP_5S": 0.02,
        "ROLLING_WINDOW_5S": 5.0,

        # Rule C: Early-slot
        "EARLY_SLOT_START_S": 0.0,
        "EARLY_SLOT_END_S": 60.0,

        # Rule D (H11): Buy-pressure-then-dip
        # Fire when 60s buy volume > threshold AND any 5s price dip occurred
        "MIN_BUY_VOL_60S": 50.0,            # > 50 shares of taker BUYS in 60s
        "MIN_PRICE_DIP_5S": 0.001,          # any small dip (> 0.1¢) in 5s

        # Inventory limits — looser than ACC-M because taker can rebalance
        "MAX_IMBALANCE_SHARES": 10.0,
        "ABSOLUTE_MAX_INVENTORY": 100.0,

        # Cells (mimic the hybrid reference wallet)
        "cells": ["btc_5m", "btc_15m", "eth_5m", "eth_15m"],
    }

    def __init__(self, config: dict[str, Any]):
        merged = {**self.EXTRA_DEFAULTS, **config}
        super().__init__(merged)
        # Per-slug ask history (rolling 60s) — for Rule A
        self._ask_history_60s: dict[str, dict[Side, deque]] = {}
        # Per-slug trade-price history (rolling 5s) — for Rules B + D
        self._trade_history_5s: dict[str, dict[Side, deque]] = {}
        # Per-slug taker-BUY volume history (rolling 60s) — for Rule D
        self._buy_vol_60s: dict[str, dict[Side, deque]] = {}

    # ============================================================
    # State management for histories
    # ============================================================

    def on_slug_active(self, evt: SlugActive) -> list[Decision]:
        decs = super().on_slug_active(evt)
        # Initialize per-slug histories
        self._ask_history_60s[evt.slug] = {Side.UP: deque(), Side.DOWN: deque()}
        self._trade_history_5s[evt.slug] = {Side.UP: deque(), Side.DOWN: deque()}
        self._buy_vol_60s[evt.slug] = {Side.UP: deque(), Side.DOWN: deque()}
        return decs

    def on_slug_resolved(self, evt: SlugResolved) -> list[Decision]:
        decs = super().on_slug_resolved(evt)
        # Cleanup histories
        self._ask_history_60s.pop(evt.slug, None)
        self._trade_history_5s.pop(evt.slug, None)
        self._buy_vol_60s.pop(evt.slug, None)
        return decs

    def _trim_history(self, deq: deque, ts_us: int, window_s: float):
        """Drop entries older than window_s from the deque."""
        cutoff_us = ts_us - int(window_s * 1_000_000)
        while deq and deq[0][0] < cutoff_us:
            deq.popleft()

    # ============================================================
    # L25 update — append to ask history + run normal decisions + check taker
    # ============================================================

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        # First: update ask history (for Rule A)
        ask_hist = self._ask_history_60s.get(evt.slug)
        if ask_hist is not None:
            ask_hist[Side.UP].append((evt.ts_us, evt.up.best_ask))
            ask_hist[Side.DOWN].append((evt.ts_us, evt.dn.best_ask))
            window = self.config["ROLLING_WINDOW_60S"]
            self._trim_history(ask_hist[Side.UP], evt.ts_us, window)
            self._trim_history(ask_hist[Side.DOWN], evt.ts_us, window)

        # Run inherited ACC-M decisions (cancel + post + merge)
        decisions = super().on_l25_update(evt)

        # ADD: composite taker trigger
        decisions.extend(self._taker_decisions(evt))

        return decisions

    # ============================================================
    # Trade print — append to trade history (for Rule B)
    # ============================================================

    def on_trade_print(self, evt: TradePrint) -> list[Decision]:
        trade_hist = self._trade_history_5s.get(evt.slug)
        if trade_hist is not None:
            trade_hist[evt.outcome].append((evt.ts_us, evt.price))
            self._trim_history(trade_hist[evt.outcome], evt.ts_us,
                                self.config["ROLLING_WINDOW_5S"])

        # Track BUY volume for Rule D (H11)
        buy_hist = self._buy_vol_60s.get(evt.slug)
        if buy_hist is not None and str(evt.taker_side).lower() == "buy":
            buy_hist[evt.outcome].append((evt.ts_us, evt.size))
            self._trim_history(buy_hist[evt.outcome], evt.ts_us,
                                self.config["ROLLING_WINDOW_60S"])
        return []

    # ============================================================
    # Composite taker trigger
    # ============================================================

    def _taker_decisions(self, evt: L25Update) -> list[Decision]:
        """Run the 3-rule composite check for each side."""
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        decisions = []
        for side, book in [(Side.UP, evt.up), (Side.DOWN, evt.dn)]:
            decision = self._maybe_market_buy(state, side, book, evt.ts_us)
            if decision:
                decisions.append(decision)
                # Don't fire BOTH sides in the same tick — avoid double-take
                break

        return decisions

    def _maybe_market_buy(self, state, side: Side, book, ts_us: int):
        current_ask = book.best_ask

        # Hard caps + rate limits
        current_inv = state.inv_up if side == Side.UP else state.inv_dn
        if current_inv >= self.config["ABSOLUTE_MAX_INVENTORY"]:
            return None

        last_take_us = state.last_taker_buy_us.get(side, 0)
        min_gap_us = int(self.config["MIN_S_BETWEEN_TAKER_BUYS"] * 1_000_000)
        if (ts_us - last_take_us) < min_gap_us:
            return None

        total_takers = state.taker_buy_count_up + state.taker_buy_count_dn
        if total_takers >= self.config["MAX_TAKER_BUYS_PER_SLUG"]:
            return None

        take_size = self.config["TAKER_SIZE"]
        cost = take_size * current_ask + take_size * taker_fee_per_share(current_ask)
        reserve = self.config["RESERVE_USDC"]
        if self.wallet_balance < cost + reserve:
            return None

        # ---------- Rule A: Discount-capture ----------
        if current_ask < self.config["MAX_TAKER_PRICE_DISCOUNT"]:
            ask_hist = self._ask_history_60s.get(state.slug, {}).get(side)
            if ask_hist and len(ask_hist) >= 10:
                asks = [a for _, a in ask_hist if a > 0]
                if asks:
                    sorted_asks = sorted(asks)
                    median_ask = sorted_asks[len(sorted_asks) // 2]
                    if median_ask - current_ask >= self.config["MIN_ASK_DROP_60S"]:
                        return self._build_market_buy(state, side, current_ask, take_size, ts_us, "discount_capture")

        # ---------- Rule B: Sharp-drop ----------
        trade_hist = self._trade_history_5s.get(state.slug, {}).get(side)
        if trade_hist and len(trade_hist) >= 3:
            max_recent = max(p for _, p in trade_hist if p > 0)
            if max_recent - current_ask >= self.config["MIN_TRADE_DROP_5S"]:
                return self._build_market_buy(state, side, current_ask, take_size, ts_us, "sharp_drop")

        # ---------- Rule C: Early-slot ----------
        offset_s = (ts_us - state.slot_start_us) / 1_000_000
        if self.config["EARLY_SLOT_START_S"] <= offset_s <= self.config["EARLY_SLOT_END_S"]:
            # Only fire if no maker bid has filled yet on this side
            fill_count = state.fill_count_up if side == Side.UP else state.fill_count_dn
            if fill_count == 0:
                return self._build_market_buy(state, side, current_ask, take_size, ts_us, "early_slot")

        # ---------- Rule D (H11): Buy-pressure-then-dip ----------
        # Wallet decoded: market-buy after 60s of buy volume on this side
        # AND any 5s price dip. 1.84x lift.
        buy_hist = self._buy_vol_60s.get(state.slug, {}).get(side)
        trade_hist = self._trade_history_5s.get(state.slug, {}).get(side)
        if buy_hist and trade_hist and len(trade_hist) >= 2:
            buy_vol = sum(sz for _, sz in buy_hist)
            if buy_vol > self.config["MIN_BUY_VOL_60S"]:
                # any dip in 5s (max in window > current price)
                max_recent = max(p for _, p in trade_hist if p > 0)
                if max_recent - current_ask >= self.config["MIN_PRICE_DIP_5S"]:
                    return self._build_market_buy(state, side, current_ask, take_size, ts_us, "buy_pressure_dip")

        return None

    def _build_market_buy(self, state, side: Side, price: float,
                           size: float, ts_us: int, reason: str) -> Decision:
        """Execute a market-buy immediately (update state + wallet)."""
        if side == Side.UP:
            state.inv_up += size
            state.taker_buy_count_up += 1
        else:
            state.inv_dn += size
            state.taker_buy_count_dn += 1
        cost = size * price
        fee = size * taker_fee_per_share(price)
        state.cash_spent += cost
        state.taker_fees += fee
        self.wallet_balance -= (cost + fee)
        state.last_taker_buy_us[side] = ts_us

        return Decision(
            strategy_code=self.code,
            action=Action.MARKET_BUY,
            slug=state.slug,
            ts_us=ts_us,
            side=side,
            price=price,
            size=size,
            reason=reason,
        )
