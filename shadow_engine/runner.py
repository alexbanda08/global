"""Shadow runner — orchestrates events from feeds + strategies + logging.

Dispatches events to all registered strategies and collects their decisions.
In shadow mode, decisions are logged (not submitted on-chain).

Also simulates fills for posted orders based on incoming TradePrints:
- BID fills when a taker SELL prints at price <= our bid
- ASK fills when a taker BUY prints at price >= our ask
"""
from __future__ import annotations

import csv
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from .base import (
    Decision, Action, Side, SlugActive, L25Update, TradePrint,
    OrderFill, SlugResolved, WalletBalance, OpenOrder, to_cents,
)
from .strategies.base import StrategyBase


class ShadowRunner:
    """Coordinates feeds → strategies → logging."""

    def __init__(self, feeds: list, strategies: list[StrategyBase],
                 log_dir: Optional[Path] = None,
                 sim_fill_queue_share: bool = True):
        """
        Args:
            feeds: list of feed iterators that yield events
            strategies: list of strategy instances
            log_dir: where to write shadow_<strategy>_<date>.csv (None = no log)
            sim_fill_queue_share: if True, simulate fills with queue-share
                                   approximation; else optimistic (any taker fills)
        """
        self.feeds = feeds
        self.strategies = strategies
        self.log_dir = Path(log_dir) if log_dir else None
        self.sim_fill_queue_share = sim_fill_queue_share

        # Per-strategy: list of (slug, summary_dict) for completed slugs
        self.slug_results: dict[str, list[dict]] = defaultdict(list)

        # Open log files per strategy
        self._log_files: dict[str, Any] = {}
        self._log_writers: dict[str, Any] = {}

        # Per (slug, side) most recent L25 snapshot — used by fill simulator
        # to compute visible-queue at fill time
        self._last_books: dict[tuple, Any] = {}

        # For fill simulation: track open orders per (strategy_code, slug)
        # (strategy state already has open_orders but we mirror here for sim)

        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # Logging
    # ============================================================

    def _get_log_writer(self, strategy_code: str):
        if strategy_code not in self._log_files:
            if not self.log_dir:
                return None
            from datetime import datetime
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = self.log_dir / f"shadow_{strategy_code}_{date_str}.csv"
            f = open(path, "w", newline="", encoding="utf-8")
            w = csv.writer(f)
            w.writerow([
                "ts_us", "strategy", "slug", "action", "side", "price", "size",
                "order_id", "pairs", "reason", "inv_up", "inv_dn",
                "cash_spent", "cash_recovered", "rebates", "wallet_balance",
            ])
            self._log_files[strategy_code] = f
            self._log_writers[strategy_code] = w
        return self._log_writers[strategy_code]

    def _log_decision(self, strategy: StrategyBase, decision: Decision):
        w = self._get_log_writer(strategy.code)
        if w is None:
            return
        state = strategy.slug_states.get(decision.slug)
        w.writerow([
            decision.ts_us,
            decision.strategy_code,
            decision.slug,
            decision.action.name,
            decision.side.as_str() if decision.side is not None else "",
            decision.price if decision.price is not None else "",
            decision.size if decision.size is not None else "",
            decision.order_id or "",
            decision.pairs if decision.pairs is not None else "",
            decision.reason,
            state.inv_up if state else "",
            state.inv_dn if state else "",
            state.cash_spent if state else "",
            state.cash_recovered if state else "",
            state.rebates if state else "",
            strategy.wallet_balance,
        ])

    def _log_slug_summary(self, strategy: StrategyBase, slug: str, outcome: Side, final_pnl: float):
        """Append slug-level summary to a separate file."""
        if not self.log_dir:
            return
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        path = self.log_dir / f"slug_summary_{strategy.code}_{date_str}.csv"
        write_header = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow([
                    "slug", "strategy", "outcome", "inv_up_final", "inv_dn_final",
                    "fill_count_up", "fill_count_dn", "taker_buy_count_up",
                    "taker_buy_count_dn", "merge_count", "pairs_merged",
                    "cash_spent", "cash_received", "cash_recovered", "rebates",
                    "taker_fees", "mint_cost", "final_pnl",
                ])
            # need to look up the state — but it was already popped in on_slug_resolved
            # so we record what the result tracked separately
            results = self.slug_results.get(strategy.code, [])
            for r in results:
                if r["slug"] == slug:
                    w.writerow([
                        slug, strategy.code, outcome.as_str(),
                        r.get("inv_up_final", 0), r.get("inv_dn_final", 0),
                        r.get("fill_count_up", 0), r.get("fill_count_dn", 0),
                        r.get("taker_buy_count_up", 0), r.get("taker_buy_count_dn", 0),
                        r.get("merge_count", 0), r.get("pairs_merged", 0),
                        r.get("cash_spent", 0), r.get("cash_received", 0),
                        r.get("cash_recovered", 0), r.get("rebates", 0),
                        r.get("taker_fees", 0), r.get("mint_cost", 0),
                        final_pnl,
                    ])
                    break

    def close_logs(self):
        for f in self._log_files.values():
            f.close()
        self._log_files.clear()
        self._log_writers.clear()

    # ============================================================
    # Event dispatch + fill simulation
    # ============================================================

    def _dispatch(self, strategy: StrategyBase, evt) -> list[Decision]:
        """Dispatch event to one strategy, return its decisions."""
        if isinstance(evt, SlugActive):
            return strategy.on_slug_active(evt)
        elif isinstance(evt, L25Update):
            return strategy.on_l25_update(evt)
        elif isinstance(evt, TradePrint):
            return strategy.on_trade_print(evt)
        elif isinstance(evt, OrderFill):
            return strategy.on_order_fill(evt)
        elif isinstance(evt, SlugResolved):
            decs = strategy.on_slug_resolved(evt)
            # Snapshot final state before it's popped
            return decs
        elif isinstance(evt, WalletBalance):
            strategy.on_wallet_balance(evt)
            return []
        return []

    def _simulate_fills(self, strategy: StrategyBase, evt: TradePrint) -> list[OrderFill]:
        """Check if any of strategy's open orders would fill on this taker print.

        LIVE-REALISTIC fill model:
          - Our order is assumed to track best_bid (or best_ask) continuously
            via fast cancel+repost in live mode (sub-second reaction)
          - Fill PRICE = the current best_bid (or best_ask) at fill time, NOT
            our possibly-stale posted price
          - Queue share: our_share = post_size / (post_size + visible_queue)
          - Filter: only fill if our posted price is within REPRICE_TOLERANCE
            of current best (i.e., we would still be on the book in live)

        This avoids the replay artifact where orders sit at stale "in-the-money"
        prices and fill at our higher posted price, losing money on pair cost.
        """
        state = strategy.slug_states.get(evt.slug)
        if state is None:
            return []

        last_book = self._last_books.get((evt.slug, evt.outcome))
        if last_book is None:
            return []

        REPRICE_TOLERANCE = 0.05      # if our posted price is > 5¢ from current best,
                                       # assume we'd have cancelled in live; skip fill

        fills = []
        taker = evt.taker_side.lower()

        for order_id in list(state.open_orders.keys()):
            order = state.open_orders[order_id]
            if order.side != evt.outcome:
                continue

            if order.is_bid:
                # Skip if we'd have cancelled in live (too far from current best)
                if abs(order.price - last_book.best_bid) > REPRICE_TOLERANCE:
                    continue
                # Filling rule: taker SELL at price <= current best_bid (where we'd be)
                if not (taker == "sell" and evt.price <= last_book.best_bid + 1e-9):
                    continue
                # Fill price = CURRENT best_bid (assumes we tracked the book in live)
                fill_price = last_book.best_bid
                visible_queue = last_book.best_bid_size
            else:
                if abs(order.price - last_book.best_ask) > REPRICE_TOLERANCE:
                    continue
                if not (taker == "buy" and evt.price >= last_book.best_ask - 1e-9):
                    continue
                fill_price = last_book.best_ask
                visible_queue = last_book.best_ask_size

            # Queue-aware fill share
            if self.sim_fill_queue_share:
                if visible_queue > 0:
                    our_share = order.size / (order.size + visible_queue)
                else:
                    our_share = 1.0
                fill_share = min(order.remaining, evt.size * our_share)
            else:
                fill_share = min(order.remaining, evt.size)

            if fill_share < 0.01:
                continue

            fills.append(OrderFill(
                slug=evt.slug, order_id=order_id, side=order.side,
                is_maker=True, fill_size=fill_share,
                fill_price=fill_price,   # CURRENT best, not stale order.price
                ts_us=evt.ts_us,
            ))

        return fills

    # ============================================================
    # Main loop
    # ============================================================

    def run(self, progress_every: int = 10):
        """Run until all feeds are exhausted."""
        slug_count = 0
        t_start = time.time()

        for feed in self.feeds:
            for evt in feed:
                # Cache book snapshots so fill simulator can compute queue share
                if isinstance(evt, L25Update):
                    self._last_books[(evt.slug, Side.UP)] = evt.up
                    self._last_books[(evt.slug, Side.DOWN)] = evt.dn

                # Dispatch to all strategies
                for strategy in self.strategies:
                    decisions = self._dispatch(strategy, evt)
                    for d in decisions:
                        self._log_decision(strategy, d)

                # On TradePrint, simulate any fills for each strategy
                if isinstance(evt, TradePrint):
                    for strategy in self.strategies:
                        sim_fills = self._simulate_fills(strategy, evt)
                        for fill in sim_fills:
                            # Process the fill through the strategy
                            fill_decisions = strategy.on_order_fill(fill)
                            for d in fill_decisions:
                                self._log_decision(strategy, d)

                # On SlugResolved, snapshot result + log summary
                if isinstance(evt, SlugResolved):
                    slug_count += 1
                    for strategy in self.strategies:
                        # State already popped by on_slug_resolved, but we
                        # need to snapshot before that. Use a workaround:
                        # peek into recently popped slug.
                        # (Actually, on_slug_resolved is called before this point,
                        # so we need to capture state inside on_slug_resolved.)
                        # For now, just log basic info.
                        pass

                    if slug_count % progress_every == 0:
                        elapsed = time.time() - t_start
                        print(f"  [runner] {slug_count} slugs done in {elapsed:.1f}s")

        self.close_logs()
        elapsed = time.time() - t_start
        print(f"  [runner] FINISHED — {slug_count} slugs in {elapsed:.1f}s")
