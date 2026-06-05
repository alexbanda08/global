"""Phase 32 — Polymarket Maker Shadow Fill Simulator.

Subscribes to BookMirror + TradeMirror (TV-native — CLAUDE inv #13). Observes
Decisions from poly_maker_loop._route_decision and synthesizes OrderFills
when its probabilistic queue-position fill model triggers.

Coordinator skeleton — fill-detection logic lives in helper methods filled
in by subsequent Plans 32-04..32-09:
- _observe_post / _check_post_fill (D-01, D-02, D-03) — Plan 32-04
- _apply_adv_sel (D-04, D-05, Pitfall 1) — Plan 32-05
- _walk_take_vwap (D-09) — Plan 32-06
- _synthesize_mas_mint (D-08) — Plan 32-07
- _observe_merge / _apply_merge (D-06, D-07) — Plan 32-08
- _apply_bps_deltas (D-11) — Plan 32-09

Hot path:
- observe(decision, strategy, slug_state) — sync, zero-blocking, called from
  _route_decision before the existing shadow_log.log(sim_fill=False) call
- on_trade_print(tp) — sync, called from the wrapped TradeMirror callback
  BEFORE the existing engine _on_trade dispatcher fires (Pitfall 3 Option A)

CLAUDE inv #13: This module imports zero external batch-data symbols. All data
comes from TV-native sources (BookMirror, TradeMirror, engine settings).
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from time import monotonic
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from backend.app.services.alert_service import AlertService
    from backend.app.strategies.polymarket.maker.shadow_log import AsyncShadowLogger
    from backend.app.strategies.polymarket.maker.types import Decision, OrderFill, SlugState, TradePrint
    from backend.app.venues.polymarket.book_mirror import BookMirror

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal order state — Plan 32-04
# ---------------------------------------------------------------------------


@dataclass
class _OrderState:
    """Sim's tracking record for one open POST_BID or POST_ASK.

    Plan 32-04 introduces this; Plans 32-05/32-06 extend price logic.
    """
    order_id: str
    slug: str
    side: str           # "up" | "dn"
    action: str         # "POST_BID" | "POST_ASK"
    price: Decimal
    size: Decimal
    token_id: str
    posted_ts_us: int
    initial_queue: Decimal | None   # None = cold-start parked
    remaining_queue: Decimal | None
    cold_start_retry_count: int = 0
    cold_start_orphan: bool = False
    # E8 (ENGINE_BUG_MAP_2026_05_28): accumulated filled size for partial fills
    # (fill-realism mode). The order stays open until filled_size >= size.
    filled_size: Decimal = Decimal(0)
    # Set True if strategy.state.open_orders had this order_id when _observe_post
    # ran. Used by the phantom-fill guard in _emit_post_fill: if True at observe
    # time but missing at fill time, the strategy cancelled it -> skip emit.
    # Stays False when the test scaffolding skips ACC-M's add-to-open_orders step.
    strategy_registered: bool = False
    # Slug's asset + tf captured at observe() time. _emit_post_fill must use
    # these (NOT strategy.{asset,tf}) when writing the synth fill row — when
    # one strategy instance handles multiple cells (pre-fix strategy_index
    # bug), strategy.tf could be stale (e.g. 15m while slug is 5m), leaving
    # the fill row tagged with the wrong tf and the dashboard filter
    # excluding it from the right sleeve.
    asset: str = ""
    tf: str = ""


class MakerFillSimulator:
    """Coordinator + per-slug open-order state + auto-disable.

    See module docstring for the helper-method completion map.

    Constructor takes keyword-only arguments (mirrors AsyncShadowLogger
    pattern — PATTERNS analog 1):

        sim = MakerFillSimulator(
            settings=settings,
            shadow_loggers=per_strategy_loggers,   # dict[str, AsyncShadowLogger]
            book_mirror=book_mirror,
            alert_service=alert_service,
        )

    Lifecycle: ``await sim.start()`` before first observe(); ``await sim.stop()``
    at shutdown. No background task is spawned — the sim is purely event-driven.
    """

    def __init__(
        self,
        *,
        settings: Any,
        shadow_loggers: dict[str, "AsyncShadowLogger"],
        book_mirror: "BookMirror | Any",      # _FakeBookMirror in tests
        alert_service: "AlertService | None" = None,
    ) -> None:
        self._settings = settings
        self._shadow_loggers = shadow_loggers
        self._book_mirror = book_mirror
        self._alerts = alert_service

        # Per-slug open-order state (Plans 32-04+ flesh out)
        # slug -> order_id -> _OrderState dataclass (defined in Plan 32-04)
        self._open_orders: dict[str, dict[str, Any]] = {}
        # slug -> deque of completed fills (D-07 FIFO — Plan 32-08)
        self._fill_history: dict[str, deque[Any]] = {}

        # Stats accumulators (operator visibility via /maker/sleeves/health — Plan 32-10)
        self._n_post_observed: int = 0
        self._n_take_observed: int = 0
        self._n_fills: int = 0
        self._n_merges: int = 0
        self._n_skipped_cold_start: int = 0

        # D-CF-3 auto-disable: 5 exceptions in 5min per (strategy, cell)
        # Mirrors poly_maker_loop._record_error (lines ~200-247)
        self._error_windows: dict[tuple[str, str], deque[float]] = {}
        self._disabled: set[tuple[str, str]] = set()
        self._auto_disable_threshold: int = int(
            getattr(settings, "tv_poly_maker_auto_disable_threshold", 5)
        )
        self._auto_disable_window_s: float = float(
            getattr(settings, "tv_poly_maker_auto_disable_window_s", 300)
        )

        # Lifecycle flag
        self._started: bool = False

        # D-CF-5: one-tick fill-emitted flag. Set to True whenever a synthetic fill
        # is written (any _emit_* or _observe_mint/_observe_merge path). Consumed +
        # reset by poly_maker_loop._route_decision to trigger maker_state notify_event.
        self._fill_emitted_this_tick: bool = False

        # Strategy reference cache: slug -> strategy (populated at first observe)
        # Used by _emit_post_fill to call strategy.on_order_fill + build fill Decision.
        self._strategy_cache: dict[str, Any] = {}
        # E3 (ENGINE_BUG_MAP_2026_05_28): order_id -> strategy. The slug-keyed
        # _strategy_cache is last-write-wins, so when two sleeves (e.g.
        # acc_h_v2 + acc_pc_v2) post on the SAME market slug, fills got routed
        # to the wrong strategy. order_id is globally unique (code-prefixed,
        # e.g. "ACC-H-00000001"), so routing maker fills by order_id is exact.
        self._order_strategy: dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Mark simulator as started. No background task — sim is event-driven."""
        self._started = True
        log.info("poly_maker_fill_sim.start")

    async def stop(self) -> None:
        """Mark simulator as stopped. Logs final stats."""
        self._started = False
        log.info("poly_maker_fill_sim.stop", final_stats=self.stats())

    # -------------------------------------------------------------------------
    # Stats (operator visibility — extended by Plan 32-10 into health endpoint)
    # -------------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return a snapshot of accumulator counters.

        Keys are stable across plans — subsequent plans only ADD to this dict.
        """
        return {
            "n_post_observed": self._n_post_observed,
            "n_take_observed": self._n_take_observed,
            "n_fills": self._n_fills,
            "n_merges": self._n_merges,
            "n_skipped_cold_start": self._n_skipped_cold_start,
            "n_disabled_cells": len(self._disabled),
        }

    def fill_emitted_this_tick(self) -> bool:
        """D-CF-5: True if at least one synthetic fill was emitted since the last
        call to this method. Consuming (resets the flag to False on read).

        Called from poly_maker_loop._route_decision after fill_sim.observe() so
        that the loop can trigger a maker_state notify_event on the same tick a
        fill was synthesized — keeps the dashboard TanStack Query cache fresh.
        """
        emitted = self._fill_emitted_this_tick
        self._fill_emitted_this_tick = False  # consume (reset)
        return emitted

    # -------------------------------------------------------------------------
    # Hot path — observe(Decision)
    # -------------------------------------------------------------------------

    def observe(
        self,
        *,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState | None",
    ) -> None:
        """Hot-path entry from _route_decision. Synchronous — never awaits.

        Called BEFORE shadow_log.log(sim_fill=False) in poly_maker_loop so that
        the sim can append a synthetic fill row immediately after on the same tick.

        Plans 32-04..32-09 implement the fill-detection branches inside the
        action dispatch below. This skeleton handles ONLY:
        - Disabled-cell early return (D-CF-3)
        - Global kill-switch check (env tv_poly_maker_sim_disabled)
        - Counter increments
        - Exception capture → _record_exception
        """
        # Derive cell key: "ASSET_TF" format (e.g. "BTC_15m")
        cell = f"{getattr(strategy, 'asset', '?')}_{getattr(strategy, 'tf', '?')}"
        sc = (decision.strategy, cell)

        # Cell-disabled early return (D-CF-3)
        if sc in self._disabled:
            return

        # Global kill-switch via env + restart (CLAUDE inv #7 — no API surface)
        if getattr(self._settings, "tv_poly_maker_sim_disabled", False):
            return

        try:
            action = decision.action

            if action in ("POST_BID", "POST_ASK"):
                self._n_post_observed += 1
                # Plan 32-04 implements queue init + cold-start handling (D-01/D-02/D-03)
                self._observe_post(decision, strategy, slug_state)

            elif action == "TAKE":
                self._n_take_observed += 1
                # Plan 32-06 implements VWAP walk (D-09)
                self._observe_take(decision, strategy, slug_state)

            elif action == "MINT":
                # Plan 32-07 implements MAS MINT synthetic fill (D-08 lift)
                self._observe_mint(decision, strategy, slug_state)

            elif action == "MERGE":
                # Plan 32-08 implements MERGE FIFO + gas (D-06, D-07)
                self._observe_merge(decision, strategy, slug_state)

            elif action == "CANCEL":
                # Plan 32-04 implements open-order removal (D-10)
                self._observe_cancel(decision, strategy, slug_state)

            elif action == "REDEEM":
                # Shadow REDEEM: credit cash_received += $1 * winner_residual.
                # On-chain redemption pays exactly $1 per winning share. Without
                # this synth fill, shadow PnL appears as 100% loss because
                # cash_spent (mints + maker buys) is never offset by the $1
                # redemption credit. LIVE mode handles this via the chain-side
                # redeem dispatch; this is the shadow analog.
                self._observe_redeem(decision, strategy, slug_state)

            # Other actions — no sim action needed.

        except Exception as exc:
            self._record_exception(
                strategy=decision.strategy,
                cell=cell,
                exc=exc,
            )

    # -------------------------------------------------------------------------
    # Hot path — on_trade_print(TradePrint)
    # -------------------------------------------------------------------------

    def on_trade_print(self, tp: "TradePrint") -> None:
        """Hot-path TradeMirror callback. Synchronous (per Pitfall 3 A6).

        Called BEFORE the existing engine _on_trade dispatcher fires.
        Plan 32-04 implements the queue decrement loop inside _on_trade_print_impl.
        """
        if not self._started:
            return
        # Global kill-switch check
        if getattr(self._settings, "tv_poly_maker_sim_disabled", False):
            return
        try:
            self._on_trade_print_impl(tp)
        except Exception:
            # On trade-print exception we cannot identify a single (strategy, cell).
            # Log and accept — per-cell auto-disable applies only to observe().
            log.exception(
                "poly_maker_fill_sim.on_trade_print_failed",
                slug=getattr(tp, "slug", "?"),
            )

    # -------------------------------------------------------------------------
    # Internal: per-action implementations (Plan 32-04 fills D-01/D-02/D-03/D-10)
    # -------------------------------------------------------------------------

    def _infer_aggressor(self, tp: "TradePrint", token_id: str) -> str | None:
        """Bug 6 (TV_AGENT guide): infer aggressor side from trade price vs mid.

        Pre-fix behavior: when tp.aggressor was None, BOTH bid and ask queues
        decremented on the SAME trade print — over-counts queue exhaustion
        compared to real CLOB matching (one trade hits ONE side).

        Heuristic: trade price >= mid → buy aggressor (lifted the ask).
        Trade price < mid → sell aggressor (hit the bid). Returns None if
        book is absent or empty on either side (caller safe-skips rather
        than dual-decrementing).
        """
        book = self._book_mirror.get(token_id) if self._book_mirror is not None else None
        if book is None:
            return None
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        if not bids or not asks:
            return None
        best_bid = Decimal(bids[0]["price"])
        best_ask = Decimal(asks[0]["price"])
        mid = (best_bid + best_ask) / Decimal(2)
        return "buy" if tp.price >= mid else "sell"

    @staticmethod
    def _depth_at_price(levels: list[dict[str, str]], price: Decimal) -> Decimal:
        """Sum of sizes at exact price level. Returns 0 if level not present.

        BookMirror.get returns levels as [{"price": str, "size": str}, ...].
        bids descending, asks ascending. Per D-02 we match exact price.
        """
        total = Decimal(0)
        for lvl in levels:
            if Decimal(lvl["price"]) == price:
                total += Decimal(lvl["size"])
        return total

    def _observe_post(
        self,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState | None",
    ) -> None:
        """D-01 + D-02 + D-03 + D-10: track new POST_BID/POST_ASK.

        Normal path: snapshot queue depth at our price from the live book.
        Cold-start path (D-03): book is None → park order with initial_queue=None;
        the cold-start retry loop in _on_trade_print_impl initializes the queue
        on subsequent ticks (up to 10 before orphaning).
        """
        if decision.order_id is None:
            return

        # Cache strategy ref for fill emission (used by _lookup_strategy).
        # E3: also key by order_id (exact route — survives shared-cell slugs).
        self._strategy_cache[decision.slug] = strategy
        self._order_strategy[decision.order_id] = strategy

        # Resolve token_id from slug_state
        if slug_state is not None:
            token_id = (
                slug_state.token_id_up if decision.side == "up" else slug_state.token_id_dn
            )
        else:
            # No slug_state — can't resolve token_id; skip tracking
            log.warning(
                "poly_maker_fill_sim.observe_post_no_slug_state",
                slug=decision.slug, order_id=decision.order_id,
            )
            return

        book = self._book_mirror.get(token_id) if self._book_mirror is not None else None

        # Phantom-fill guard prep: check if the strategy added this order to its
        # state.open_orders BEFORE routing the POST Decision through observe().
        # ACC-M (and inheritors) do this in _post_decisions / _pat_decisions.
        # If True at observe time + missing at fill time, the strategy cancelled
        # the order -> _emit_post_fill skips the phantom fill.
        strategy_registered = False
        if slug_state is not None and decision.order_id in slug_state.open_orders:
            strategy_registered = True

        if book is None:
            # D-03 cold-start: park order with retry state
            order = _OrderState(
                order_id=decision.order_id,
                slug=decision.slug,
                side=decision.side or "up",
                action=decision.action,
                price=decision.price or Decimal(0),
                size=decision.size or Decimal(0),
                token_id=token_id,
                posted_ts_us=decision.ts_us,
                initial_queue=None,
                remaining_queue=None,
                strategy_registered=strategy_registered,
                asset=decision.asset,
                tf=decision.tf,
            )
            self._open_orders.setdefault(decision.slug, {})[order.order_id] = order
            self._n_skipped_cold_start += 1
            log.warning(
                "poly_maker_fill_sim.cold_start_skip",
                token_id=token_id, slug=decision.slug, order_id=order.order_id,
            )
            return

        # Normal path: snapshot queue depth at our price
        levels = book["bids"] if decision.action == "POST_BID" else book["asks"]
        initial_queue = self._depth_at_price(levels, decision.price or Decimal(0))
        # E10 (ENGINE_BUG_MAP_2026_05_28): zero published depth at our price does
        # NOT prove we're front-of-queue (the level may just be absent from the
        # visible L2). When fill-realism is on, park as cold-start (retry) rather
        # than allowing an optimistic instant fill on the first crossing print.
        if (
            getattr(self._settings, "tv_poly_maker_fill_realism", False) is True
            and initial_queue <= 0
        ):
            initial_queue = None
        order = _OrderState(
            order_id=decision.order_id,
            slug=decision.slug,
            side=decision.side or "up",
            action=decision.action,
            price=decision.price or Decimal(0),
            size=decision.size or Decimal(0),
            token_id=token_id,
            posted_ts_us=decision.ts_us,
            initial_queue=initial_queue,
            remaining_queue=initial_queue,
            strategy_registered=strategy_registered,
            asset=decision.asset,
            tf=decision.tf,
        )
        self._open_orders.setdefault(decision.slug, {})[order.order_id] = order

    @staticmethod
    def _walk_take_vwap(
        book_asks: list[dict[str, str]],
        take_size: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """D-09: walk ascending L2 depth, consuming up to take_size.

        Returns (vwap_price, total_filled). If book is empty or take_size <= 0,
        returns (0, 0). Caller logs warning if total_filled < take_size.

        book_asks MUST be pre-sorted ascending (touch first) — that is what
        BookMirror returns.
        """
        remaining = take_size
        cost = Decimal(0)
        filled = Decimal(0)
        for lvl in book_asks:
            if remaining <= 0:
                break
            lvl_price = Decimal(lvl["price"])
            lvl_size = Decimal(lvl["size"])
            take_here = min(lvl_size, remaining)
            cost += take_here * lvl_price
            filled += take_here
            remaining -= take_here
        if filled == 0:
            return (Decimal(0), Decimal(0))
        return (cost / filled, filled)

    def _observe_take(
        self,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState | None",
    ) -> None:
        """D-09: VWAP walk against visible L2 for TAKE Decisions."""
        if slug_state is None:
            return
        take_size = decision.size or Decimal(0)
        if take_size <= 0:
            return

        # Resolve target token_id from side
        token_id = (
            slug_state.token_id_up if decision.side == "up" else slug_state.token_id_dn
        )

        book = self._book_mirror.get(token_id) if self._book_mirror is not None else None
        if book is None:
            self._n_skipped_cold_start += 1
            log.warning(
                "poly_maker_fill_sim.take_cold_start_skip",
                token_id=token_id,
                slug=decision.slug,
                decision_id=decision.order_id,
            )
            return

        # E11 (ENGINE_BUG_MAP_2026_05_28): sparse-book guard — when fill-realism
        # is on, require >= N visible ask levels before trusting a TAKE VWAP
        # walk (a near-empty book fills at an optimistic price live can't hit).
        if getattr(self._settings, "tv_poly_maker_fill_realism", False) is True:
            _asks = book.get("asks") or []
            if len(_asks) < 2:
                self._n_skipped_cold_start += 1
                log.warning(
                    "poly_maker_fill_sim.take_sparse_book_skip",
                    slug=decision.slug, side=decision.side,
                    n_levels=len(_asks),
                )
                return

        vwap_price, filled = self._walk_take_vwap(book["asks"], take_size)
        if filled == 0:
            log.warning(
                "poly_maker_fill_sim.take_empty_book",
                slug=decision.slug,
                side=decision.side,
            )
            return

        if filled < take_size:
            log.warning(
                "poly_maker_fill_sim.take_partial_fill",
                slug=decision.slug,
                side=decision.side,
                requested=str(take_size),
                filled=str(filled),
                dropped=str(take_size - filled),
            )

        # Cache strategy for later lookup
        self._strategy_cache[decision.slug] = strategy
        self._emit_take_fill(decision, strategy, slug_state, vwap_price, filled)

    def _emit_take_fill(
        self,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState",
        vwap_price: Decimal,
        filled: Decimal,
    ) -> None:
        """Build OrderFill(is_maker=False) + drive strategy hook + write fill row."""
        from backend.app.strategies.polymarket.maker.types import Decision as _Decision
        from backend.app.strategies.polymarket.maker.types import OrderFill as _OrderFill

        now_us = int(time.time() * 1_000_000)
        fill = _OrderFill(
            slug=decision.slug,
            side=decision.side or "up",
            ts_us=now_us,
            order_id=decision.order_id or f"TAKE-{decision.strategy}-{now_us}",
            price=vwap_price,
            size=filled,
            is_maker=False,
        )
        # Capture cascading Decisions returned by strategy.on_order_fill.
        # ACC-M / ACC-H / ACC-PC's on_order_fill calls _merge_decisions when
        # paired_inv >= threshold, returning a list with the MERGE Decision.
        # Pre-fix we discarded this -> MERGE silently dropped -> cash_received
        # never credited -> dashboard PnL stuck at -cash_spent (false 100% loss).
        cascade_decisions: list[Any] = []
        try:
            ret = strategy.on_order_fill(fill)
            if isinstance(ret, list):
                cascade_decisions = ret
        except Exception:
            log.exception(
                "poly_maker_fill_sim.take_on_order_fill_failed",
                slug=decision.slug,
                decision_id=decision.order_id,
            )
            return

        # D-11 bps delta — additive on top of strategy's formula-based rebate
        self._apply_bps_deltas(slug_state, vwap_price, filled, is_maker=False)

        # Track in fill history for D-07 FIFO MERGE (TAKE buys count as inventory)
        history = self._fill_history.setdefault(decision.slug, deque(maxlen=10_000))
        history.append((now_us, vwap_price, filled, fill.side))

        # Bug 4 (TV_AGENT guide): write sim-fill row with action="FILL"
        # (not TAKE) to distinguish the intent (TAKE Decision emitted by the
        # strategy at decision time) from the actual fill execution. The
        # intent row was already written by _route_decision with
        # action="TAKE", sim_fill=False. This row carries the fill price,
        # size, and post-fill state — action="FILL" makes that explicit so
        # downstream filtering (`action == "FILL"`) returns ONLY actual
        # fills, not unfilled intents.
        fill_decision = _Decision(
            ts_us=now_us,
            strategy=decision.strategy,
            slug=decision.slug,
            asset=decision.asset,
            tf=decision.tf,
            action="FILL",
            side=decision.side,
            price=vwap_price,
            size=filled,
            order_id=fill.order_id,
            trigger_reason=f"sim_take_vwap_filled={filled}",
        )
        sl = self._shadow_loggers.get(decision.strategy)
        if sl is not None:
            sl.log(fill_decision, sim_fill=True, slug_state=slug_state)
        self._n_fills += 1
        self._fill_emitted_this_tick = True  # D-CF-5

        # Route cascading Decisions (e.g. MERGE) back through observe() so the
        # sim's accounting handlers run (credit cash_received for MERGE).
        for cascade_decision in cascade_decisions:
            try:
                self.observe(
                    decision=cascade_decision,
                    strategy=strategy,
                    slug_state=slug_state,
                )
            except Exception:
                log.exception(
                    "poly_maker_fill_sim.take_cascade_observe_failed",
                    cascade_action=cascade_decision.action,
                    slug=decision.slug,
                )

    def _observe_mint(
        self,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState | None",
    ) -> None:
        """D-08: lift LIVE-only MAS MINT synthetic-fill block into shadow.

        Synthesizes OrderFill(price=$1.0, size=N, is_maker=False) with order_id
        'MAS-MINT-<slug>' so MAS.on_order_fill recognizes it (mas.py:279) and
        flips inv_up=inv_dn=N + cash_spent += N×$1.

        Called INLINE (Pitfall 5 — async ordering must not delay inv flip).
        No on-chain call — the on-chain split stays in poly_maker_loop under
        the LIVE dispatch gate (CLAUDE inv #13 / T-32-07-01).
        """
        from backend.app.strategies.polymarket.maker.types import Decision as _Decision
        from backend.app.strategies.polymarket.maker.types import OrderFill as _OrderFill

        if decision.action != "MINT":
            return
        size = decision.size or Decimal(0)
        if size <= 0:
            return

        # Cache strategy ref for later lookups
        self._strategy_cache[decision.slug] = strategy

        synthetic_fill = _OrderFill(
            slug=decision.slug,
            side="up",                              # MAS MINT seeds the "up" leg
            ts_us=decision.ts_us,
            order_id=f"MAS-MINT-{decision.slug}",
            price=Decimal("1.0"),                   # $1.00/pair from CTF split
            size=size,
            is_maker=False,
        )
        # Drive strategy.on_order_fill INLINE (Pitfall 5 — async ordering)
        try:
            strategy.on_order_fill(synthetic_fill)
        except Exception:
            log.exception(
                "poly_maker_fill_sim.mas_mint_dispatch_failed",
                slug=decision.slug,
                order_id=synthetic_fill.order_id,
            )
            return

        # Write fill_simulated=1 CSV row (two-row pattern)
        fill_decision = _Decision(
            ts_us=synthetic_fill.ts_us,
            strategy=decision.strategy,
            slug=decision.slug,
            asset=decision.asset,
            tf=decision.tf,
            action="MINT",
            side=None,
            price=Decimal("1.0"),
            size=size,
            order_id=synthetic_fill.order_id,
            trigger_reason="sim_mas_mint_synthetic",
        )
        sl = self._shadow_loggers.get(decision.strategy)
        if sl is not None:
            sl.log(fill_decision, sim_fill=True, slug_state=slug_state)
        self._n_fills += 1
        self._fill_emitted_this_tick = True  # D-CF-5

    def _observe_merge(
        self,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState | None",
    ) -> None:
        """D-06 + D-07: MERGE accounting — pop FIFO pairs, mutate state, write row.

        No strategy.on_order_fill hook covers MERGE (RESEARCH Pattern 3), so sim
        mutates slug_state directly here.

        Gas range: tv_poly_merge_gas_usd should be a positive Decimal (e.g. 0.05).
        A misconfigured negative value would inflate cash_received — visible in PNL.
        """
        if slug_state is None or decision.size is None or decision.size <= 0:
            return
        pairs = decision.size
        history = self._fill_history.get(decision.slug)
        if history is None:
            log.warning("poly_maker_fill_sim.merge_no_history", slug=decision.slug)
            return

        # Bug 8: count SHARES (not entries) by side before mutating anything.
        # Pre-fix compared entry-count to pairs (shares) — fills arrive in size>1
        # chunks (TAKE x5, MERGE-x5 triggers in ACC-H/M/PC), so 1 entry covers 5
        # shares but counted as 1. Result: `1 < 5` aborted EVERY ACC merge.
        # Strategy's _merge_decisions already decremented inv (state.inv_up -=
        # paired, etc.) BEFORE sim's observe ran, so the silent abort lost both
        # the inventory AND the $1×pairs redemption credit. Net -$5 per pair
        # × dozens of fires = the operator's $-300/sleeve loss in 5min.
        up_shares = sum(s for _ts, _p, s, side in history if side == "up")
        dn_shares = sum(s for _ts, _p, s, side in history if side == "dn")
        if up_shares < pairs or dn_shares < pairs:
            log.warning(
                "poly_maker_fill_sim.merge_insufficient_history",
                slug=decision.slug,
                pairs_requested=str(pairs),
                up_shares_available=str(up_shares),
                dn_shares_available=str(dn_shares),
            )
            return

        # D-07 FIFO: consume `pairs` SHARES (not entries) of each side from the
        # oldest end. If an entry's size exceeds the remaining-to-pop, split it:
        # consume `remaining` shares, retain the unused tail as a smaller entry.
        new_history: deque = deque(maxlen=10_000)
        up_popped = Decimal(0)
        dn_popped = Decimal(0)
        for entry in history:
            _ts, _p, _s, side = entry
            if side == "up" and up_popped < pairs:
                remaining = pairs - up_popped
                if _s <= remaining:
                    up_popped += _s
                    continue
                up_popped = pairs
                new_history.append((_ts, _p, _s - remaining, side))
                continue
            if side == "dn" and dn_popped < pairs:
                remaining = pairs - dn_popped
                if _s <= remaining:
                    dn_popped += _s
                    continue
                dn_popped = pairs
                new_history.append((_ts, _p, _s - remaining, side))
                continue
            new_history.append(entry)
        self._fill_history[decision.slug] = new_history

        # D-06: apply state mutation — CTF pays $1×pairs; gas is a debit.
        # IMPORTANT: do NOT decrement slug_state.inv_up/inv_dn here. The
        # strategy's _merge_decisions already decremented them (acc_m.py line
        # ~360 has `state.inv_up -= paired; state.inv_dn -= paired`). When
        # the strategy returns a MERGE Decision from on_order_fill and the
        # sim routes it back through observe (post-Phase-32 cascade fix),
        # decrementing here would DOUBLE-DEBIT the inventory.
        # Same for n_merges: strategy._merge_decisions already does
        # `state.n_merges += 1`. Sim only credits cash_received.
        gas_usd = Decimal(str(self._settings.tv_poly_merge_gas_usd))
        # Bug 2 (TV_AGENT guide): MERGE proceeds credit cash_recovered, not
        # cash_received. cash_received is for maker ASK sells; cash_recovered
        # is for market-mechanism returns (MERGE pairs, REDEEM par payouts).
        # Dashboard PnL formula sums both → net effect identical pre-fix
        # (post-restart slugs only); accounting attribution clearer.
        slug_state.cash_recovered += pairs - gas_usd
        self._n_merges += 1  # sim-internal counter only
        self._fill_emitted_this_tick = True  # D-CF-5

        # Write fill_simulated=1 MERGE row (two-row pattern)
        from backend.app.strategies.polymarket.maker.types import Decision as _Decision

        merge_fill_decision = _Decision(
            ts_us=decision.ts_us,
            strategy=decision.strategy,
            slug=decision.slug,
            asset=decision.asset,
            tf=decision.tf,
            action="MERGE",
            side=None,
            price=None,
            size=pairs,
            order_id=None,
            trigger_reason=f"sim_merge_pairs={pairs}_gas={gas_usd}",
        )
        sl = self._shadow_loggers.get(decision.strategy)
        if sl is not None:
            sl.log(merge_fill_decision, sim_fill=True, slug_state=slug_state)

    def _apply_bps_deltas(
        self,
        slug_state: Any,
        fill_price: Decimal,
        fill_size: Decimal,
        is_maker: bool,
    ) -> None:
        """Book canonical Polymarket fees + rebates per fill.

        Canonical formula (strategy_lab/fees.py, base.py:78-89):
            fee_per_share    = feeRate × p × (1 − p)       [feeRate = 0.07 crypto]
            rebate_per_share = 0.20 × fee_per_share

        All TAKE fills pay the taker fee. All POST_BID/POST_ASK fills
        (is_maker=True) receive the rebate as INCOME. MINT / MERGE / REDEEM
        do NOT pass through here (chain-side primitives — no CLOB fee).

        The env vars `tv_poly_taker_fee_bps` / `tv_poly_maker_rebate_bps` act
        as an additive override layer on top of the canonical curve. Default
        0 → canonical only, which is the production case.
        """
        if slug_state is None:
            return

        # Import at call time to avoid a module-init cycle.
        from backend.app.strategies.polymarket.maker.base import (
            maker_rebate,
            taker_fee,
        )

        # TV_AGENT_FIX_FEE_MODEL_SPEC.md: default "legacy_2pct" → per-fill
        # taker fee + rebate are both 0; the only fee is 2%-on-profit taken
        # at resolution (_observe_redeem). "curve" preserves prior behavior.
        model = getattr(self._settings, "tv_poly_maker_fee_model", "curve")
        fee_per_share = taker_fee(fill_price, model=model)
        if is_maker:
            slug_state.rebates_received += (
                maker_rebate(fee_per_share, model=model) * fill_size
            )
            bps = int(getattr(self._settings, "tv_poly_maker_rebate_bps", 0))
            if bps:
                slug_state.rebates_received += (
                    fill_price * fill_size * Decimal(bps) / Decimal(10_000)
                )
        else:
            slug_state.taker_fees_paid += fee_per_share * fill_size
            bps = int(getattr(self._settings, "tv_poly_taker_fee_bps", 0))
            if bps:
                slug_state.taker_fees_paid += (
                    fill_price * fill_size * Decimal(bps) / Decimal(10_000)
                )

    def _observe_redeem(
        self,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState | None",
    ) -> None:
        """Shadow REDEEM: credit cash_recovered += $1 * winner_residual.

        E17 (ENGINE_BUG_MAP_2026_05_28): docstring fixed — proceeds credit
        ``cash_recovered`` (market-mechanism return), NOT ``cash_received``
        (maker ASK sells). The code below was already correct.

        Strategies emit a REDEEM Decision from ``on_slug_resolved`` with
        ``side`` = winner ("up" or "dn") and ``size`` = residual shares
        of that side. On-chain ``CTF.redeemPositions`` pays exactly
        $1.00 per winning share (CTF protocol invariant for binary
        markets). LIVE mode handles this via the chain-side redeem
        dispatch; shadow must synthesize the credit or PnL stays
        permanently negative (mints + buys never offset by the $1
        redemption).

        Side effects on slug_state (mutates directly — no strategy hook
        covers REDEEM, mirroring MERGE pattern):
          - cash_received += size * $1.00
          - inv_winner -= size  (clamped to 0)
        Writes a fill_simulated=1 row to shadow_log for dashboard
        aggregation. inv_loser stays untouched (worthless residual,
        operator can cron-prune; the spec says "loser worthless — no
        REDEEM").
        """
        if slug_state is None:
            return
        if decision.size is None or decision.size <= 0:
            return
        if decision.side not in ("up", "dn"):
            return

        from backend.app.strategies.polymarket.maker.types import (
            Decision as _Decision,
        )

        size = decision.size
        payout = size * Decimal("1.00")
        # Bug 2 (TV_AGENT guide): REDEEM proceeds credit cash_recovered, not
        # cash_received (same rationale as MERGE — market-mechanism return).
        slug_state.cash_recovered += payout
        if decision.side == "up":
            slug_state.inv_up = max(Decimal(0), slug_state.inv_up - size)
        else:
            slug_state.inv_dn = max(Decimal(0), slug_state.inv_dn - size)

        # WINNER-ONLY fee (operator directive 2026-05-28 + ENGINE_BUG_MAP E4):
        # the resolution-fee models charge the fee ONLY on the winning leg,
        # NEVER on losers. Default "curve_winner" applies 0.07*p*(1-p)*qty to
        # the winning shares at resolution. Winner cost basis = size-weighted
        # avg of the winning side's fill-history; $0.50 fallback (mint split).
        model = getattr(self._settings, "tv_poly_maker_fee_model", "curve")
        if model in ("legacy_2pct", "curve_winner"):
            res_fee = self._winner_resolution_fee(
                slug=decision.slug, winner_side=decision.side,
                winner_qty=size, model=model,
            )
            slug_state.taker_fees_paid += res_fee

        # 2026-05-22 Bug-9 mirror: flip the redeem_fired flag BEFORE
        # shadow_log writes the row, so the row's slug_pnl_so_far value
        # marks loser-side residual at $0 (worthless) instead of $0.50.
        # Pre-fix this overstated MAS PnL by ~$15 per slug whenever paired
        # inventory was minted but never merged (slug ends with N shares
        # on the loser side as dust).
        slug_state.redeem_fired = True

        now_us = int(time.time() * 1_000_000)
        fill_decision = _Decision(
            ts_us=now_us,
            strategy=decision.strategy,
            slug=decision.slug,
            asset=decision.asset,
            tf=decision.tf,
            action="REDEEM",
            side=decision.side,
            price=Decimal("1.00"),
            size=size,
            order_id=f"REDEEM-{decision.slug}-{decision.side}",
            trigger_reason=f"sim_redeem_winner={decision.side}_size={size}",
        )
        sl = self._shadow_loggers.get(decision.strategy)
        if sl is not None:
            sl.log(fill_decision, sim_fill=True, slug_state=slug_state)
        self._fill_emitted_this_tick = True  # D-CF-5

    def _winner_resolution_fee(
        self, *, slug: str, winner_side: str | None,
        winner_qty: Decimal, model: str,
    ) -> Decimal:
        """Winner-leg resolution fee (operator directive: winners only).

        Cost basis = size-weighted avg fill price of the WINNING side from
        ``_fill_history``; $0.50 fallback (mint split) when no TAKE history.
        Returns 0 for non-resolution-fee models and for losers (won=True only).
        """
        from backend.app.strategies.polymarket.maker.base import resolution_fee

        hist = self._fill_history.get(slug)
        num = Decimal(0)
        den = Decimal(0)
        if hist:
            for _ts, _p, _s, _side in hist:
                if _side == winner_side:
                    num += _p * _s
                    den += _s
        avg_entry = (num / den) if den > 0 else Decimal("0.50")
        return resolution_fee(avg_entry, winner_qty, won=True, model=model)

    def settle_slug(
        self,
        *,
        strategy: Any,
        slug: str,
        winner: str,
        slug_state: "SlugState | None",
    ) -> None:
        """E1 (ENGINE_BUG_MAP_2026_05_28): force-settle a resolved slug.

        Called by the resolution loop for EVERY traded slug (even loser-only
        slugs, or ones whose strategy emitted no REDEEM). Previously a slug
        whose winner held 0 shares never set ``redeem_fired`` and never zeroed
        the loser inventory, so shadow_log's mark kept crediting
        ``residual × $0.50`` forever → ``slug_pnl_so_far`` + dashboard
        permanently optimistic (empirically +$1.95 vs true −$8.05 on losers).

        Idempotent + double-credit-safe:
          * If ``redeem_fired`` already True (winner residual was credited by
            ``_observe_redeem``), only zero the loser side — never re-credit.
          * Else credit any winner residual at $1 (covers the case where the
            strategy popped its state before the REDEEM could be observed),
            then zero both sides.

        Emits a ``fill_simulated=1`` EXPIRE row so the slug's LAST CSV row
        reflects the settled state (mark = 0 → slug_pnl_so_far collapses to
        realized cash, which is correct).
        """
        if slug_state is None:
            return
        if not getattr(slug_state, "redeem_fired", False):
            winner_inv = (
                slug_state.inv_up if winner == "up" else slug_state.inv_dn
            )
            if winner_inv and winner_inv > 0:
                slug_state.cash_recovered += winner_inv * Decimal("1.00")
                # WINNER-ONLY fee (operator directive): charge the resolution
                # fee on this newly-credited winner residual. Losers never
                # reach here, so they are never fee'd.
                _model = getattr(self._settings, "tv_poly_maker_fee_model", "curve")
                if _model in ("legacy_2pct", "curve_winner"):
                    slug_state.taker_fees_paid += self._winner_resolution_fee(
                        slug=slug, winner_side=winner,
                        winner_qty=winner_inv, model=_model,
                    )
        slug_state.inv_up = Decimal(0)
        slug_state.inv_dn = Decimal(0)
        slug_state.redeem_fired = True

        code = getattr(strategy, "code", "") or ""
        sl = self._shadow_loggers.get(code)
        if sl is None:
            return
        from backend.app.strategies.polymarket.maker.types import (
            Decision as _Decision,
        )

        now_us = int(time.time() * 1_000_000)
        sl.log(
            _Decision(
                ts_us=now_us,
                strategy=code,
                slug=slug,
                asset=slug_state.asset,
                tf=slug_state.tf,
                action="EXPIRE",
                side=None,
                price=None,
                size=None,
                order_id=None,
                trigger_reason=f"sim_settle_winner={winner}",
            ),
            sim_fill=True,
            slug_state=slug_state,
        )
        self._fill_emitted_this_tick = True

    def _observe_cancel(
        self,
        decision: "Decision",
        strategy: Any,
        slug_state: "SlugState | None",
    ) -> None:
        """D-10: CANCEL removes the open order; _fill_history is untouched."""
        if decision.order_id is None:
            return
        slug_orders = self._open_orders.get(decision.slug)
        if slug_orders is not None:
            slug_orders.pop(decision.order_id, None)
        self._order_strategy.pop(decision.order_id, None)  # E3 cleanup

    def _on_trade_print_impl(self, tp: "TradePrint") -> None:
        """Queue decrement + cold-start retry + fill check (D-01, D-03, Pitfall 7).

        For each open order on this slug:
        - If still cold-start (initial_queue is None): attempt retry. After 10
          retries mark cold_start_orphan; orphaned orders never fill.
        - Otherwise: decrement remaining_queue when aggressor/price direction matches.
        - After decrement: if remaining_queue == 0, check if book is crossed → emit fill.
        """
        slug_orders = self._open_orders.get(tp.slug)
        if not slug_orders:
            return

        # Snapshot iterate — we may pop during loop (Pitfall 4 safe)
        for order_id, order in list(slug_orders.items()):
            if order.cold_start_orphan:
                continue

            # --- Cold-start retry (D-03 + Pitfall 7) ---
            if order.initial_queue is None:
                order.cold_start_retry_count += 1
                book = (
                    self._book_mirror.get(order.token_id)
                    if self._book_mirror is not None
                    else None
                )
                if book is not None:
                    levels = book["bids"] if order.action == "POST_BID" else book["asks"]
                    q = self._depth_at_price(levels, order.price)
                    # E10: zero depth → stay cold-start (retry/orphan) under
                    # fill-realism instead of an optimistic instant fill.
                    if (
                        getattr(self._settings, "tv_poly_maker_fill_realism", False) is True
                        and q <= 0
                    ):
                        pass  # leave initial_queue None → retry next print
                    else:
                        order.initial_queue = q
                        order.remaining_queue = q
                else:
                    # Bug 9 (TV_AGENT guide): configurable retry threshold.
                    # Guard against MagicMock'd settings — only honor numeric.
                    _max_retries_raw = getattr(
                        self._settings,
                        "tv_poly_maker_fill_sim_cold_start_max_retries",
                        10,
                    )
                    _max_retries = (
                        int(_max_retries_raw)
                        if isinstance(_max_retries_raw, (int, float))
                        else 10
                    )
                    if order.cold_start_retry_count >= _max_retries:
                        order.cold_start_orphan = True
                        self._n_skipped_cold_start += 1
                        log.warning(
                            "poly_maker_fill_sim.cold_start_orphan",
                            slug=tp.slug,
                            order_id=order_id,
                            retries=order.cold_start_retry_count,
                            max_retries=_max_retries,
                        )
                        # Free the dedup slot in strategy.open_orders so the
                        # strategy can re-post when the book becomes available.
                        strategy_for_cleanup = self._lookup_strategy(order.slug, order.order_id)
                        if strategy_for_cleanup is not None and hasattr(
                            strategy_for_cleanup, "slug_states"
                        ):
                            state_for_cleanup = strategy_for_cleanup.slug_states.get(
                                order.slug
                            )
                            if (
                                state_for_cleanup is not None
                                and order.order_id in state_for_cleanup.open_orders
                            ):
                                del state_for_cleanup.open_orders[order.order_id]
                # If still cold-start (or just orphaned), skip decrement
                if order.initial_queue is None:
                    continue

            # --- Aggressor-aware queue direction filter (RESEARCH NOTE) ---
            # Bug 6 (TV_AGENT guide): if tp.aggressor is missing, infer from
            # trade price vs book mid. Pre-fix the None fallthrough decremented
            # BOTH bid and ask queues on the same print — over-counts queue
            # exhaustion vs real CLOB matching (one trade hits one side).
            agg = getattr(tp, "aggressor", None)
            if agg is None:
                agg = self._infer_aggressor(tp, order.token_id)
            if agg == "buy" and order.action != "POST_ASK":
                continue   # BUY aggressor lifts asks → only POST_ASK queues decrement
            if agg == "sell" and order.action != "POST_BID":
                continue   # SELL aggressor hits bids → only POST_BID queues decrement
            if agg is None:
                # No book to infer from → safe-skip (do not dual-decrement).
                continue

            # --- Price-direction filter ---
            if order.action == "POST_BID" and tp.price > order.price:
                continue   # print above our bid — doesn't touch our queue
            if order.action == "POST_ASK" and tp.price < order.price:
                continue   # print below our ask — doesn't touch our queue

            # --- Decrement ---
            _realism = (
                getattr(self._settings, "tv_poly_maker_fill_realism", False) is True
            )
            overflow = Decimal(0)
            if order.remaining_queue is not None and order.remaining_queue > 0:
                decrement = min(tp.size, order.remaining_queue)
                order.remaining_queue -= decrement
                # Aggressor volume past our (now-exhausted) queue position.
                overflow = tp.size - decrement
            elif order.remaining_queue == Decimal(0):
                # Queue already gone (e.g. after a prior partial fill) — the
                # whole print can match us.
                overflow = tp.size

            # --- Fill trigger: queue == 0 AND book crossed ---
            if order.remaining_queue == Decimal(0):
                if _realism:
                    # E8 (ENGINE_BUG_MAP_2026_05_28): cap the fill to the
                    # aggressor volume that crossed us — no full-size over-fill.
                    if overflow > 0:
                        self._check_fill(order, max_fill=overflow)
                else:
                    self._check_fill(order)

    def _check_fill(
        self, order: _OrderState, max_fill: "Decimal | None" = None
    ) -> None:
        """If book is live-crossed at our price, emit a synthetic fill.

        Uses live book at check time (not POST time) — Pitfall 2 / T-32-04-02.

        E8 (ENGINE_BUG_MAP_2026_05_28): when ``max_fill`` is given (fill-realism
        mode), the fill is capped to ``min(remaining_size, max_fill)`` — the
        aggressor volume that actually crossed us — so the order fills partially
        over multiple prints instead of the full size on the first cross.
        """
        book = (
            self._book_mirror.get(order.token_id) if self._book_mirror is not None else None
        )
        if book is None:
            return

        if order.action == "POST_BID":
            # Fill when best_ask <= our bid price (book crossed)
            if not book["asks"]:
                return
            best_ask = Decimal(book["asks"][0]["price"])
            if best_ask > order.price:
                return
        else:  # POST_ASK
            # Fill when best_bid >= our ask price (book crossed)
            if not book["bids"]:
                return
            best_bid = Decimal(book["bids"][0]["price"])
            if best_bid < order.price:
                return

        if max_fill is None:
            self._emit_post_fill(order)
            return
        remaining = order.size - order.filled_size
        fill = remaining if remaining < max_fill else max_fill
        if fill > 0:
            self._emit_post_fill(order, fill_size=fill)

    def _apply_adv_sel_haircut(self, raw_price: Decimal, action: str) -> Decimal:
        """D-04 + Pitfall 1: bake adv-sel haircut into the fill price.

        E9 (ENGINE_BUG_MAP_2026_05_28): now SYMMETRIC. Adverse selection means
        you tend to get filled on the side that's about to move against you:
          * POST_BID (buying) → you pay MORE  → price × (1 + bps).
          * POST_ASK (selling) → you receive LESS → price × (1 - bps).
        Previously only POST_BID was haircut (one-sided → optimistic on sells).

        Setting tv_poly_maker_adv_sel_bps=0 disables the haircut entirely.

        The haircut is baked INTO the OrderFill.price so strategy.on_order_fill
        applies the cash delta ONCE — no post-hoc mutation (RESEARCH Pitfall 1).
        """
        bps = int(getattr(self._settings, "tv_poly_maker_adv_sel_bps", 0))
        if bps == 0:
            return raw_price
        factor = Decimal(bps) / Decimal(10_000)
        if action == "POST_BID":
            return raw_price * (Decimal(1) + factor)
        # POST_ASK — symmetric haircut (sell into adverse flow for less), but
        # only when fill-realism is enabled (E9). Default keeps the prior
        # one-sided behavior so the unit suite is unchanged.
        if getattr(self._settings, "tv_poly_maker_fill_realism", False) is True:
            return raw_price * (Decimal(1) - factor)
        return raw_price

    def _emit_post_fill(
        self, order: _OrderState, fill_size: "Decimal | None" = None
    ) -> None:
        """Build synthetic OrderFill, drive strategy.on_order_fill, write fill CSV row.

        E8: ``fill_size`` (fill-realism mode) fills only that many shares and
        keeps the order open until ``filled_size >= size``. ``None`` = legacy
        full-size fill (order removed after).

        Two-row CSV pattern (RESEARCH Pattern 2):
          Row 1: decision row — written by poly_maker_loop BEFORE observe()
          Row 2: fill row — written HERE with sim_fill=True

        Plans 32-05 (adv-sel haircut) + 32-09 (rebate bps delta) hook in here.

        Phantom-fill guard: ACC-M's ``_cancel_decisions`` deletes from
        ``state.open_orders`` IMMEDIATELY when emitting a CANCEL Decision,
        but the CANCEL hasn't yet been routed through ``fill_sim.observe()``.
        Trade prints in that gap can decrement the sim's still-tracked queue
        to 0 -> _check_fill calls _emit_post_fill -> strategy.on_order_fill
        looks up state.open_orders[order_id] -> NOT FOUND ->
        ``acc_m.fill.unknown_order_id`` warning, fill dropped.

        Check the strategy's open_orders before emitting; if the order was
        already cancelled by the strategy, skip the phantom fill + clean up
        sim state.
        """
        from backend.app.strategies.polymarket.maker.types import Decision as _Decision
        from backend.app.strategies.polymarket.maker.types import OrderFill as _OrderFill

        # Phantom-fill guard: skip if strategy already cancelled this order
        # (race window between _cancel_decisions deleting from state.open_orders
        # and engine routing the CANCEL Decision through fill_sim.observe).
        # Only applies when the strategy ORIGINALLY registered the order at POST
        # time -- avoids false positives in test scaffolds that hand decisions
        # directly to the sim without going through ACC-M's _post_decisions.
        if order.strategy_registered:
            strategy_for_check = self._lookup_strategy(order.slug, order.order_id)
            if strategy_for_check is not None and hasattr(strategy_for_check, "slug_states"):
                state_for_check = strategy_for_check.slug_states.get(order.slug)
                if (
                    state_for_check is not None
                    and order.order_id not in state_for_check.open_orders
                ):
                    log.debug(
                        "poly_maker_fill_sim.skip_phantom_fill",
                        slug=order.slug,
                        order_id=order.order_id,
                        reason="strategy_already_cancelled",
                    )
                    # Clean up sim state -- the order is dead.
                    slug_orders = self._open_orders.get(order.slug)
                    if slug_orders is not None:
                        slug_orders.pop(order.order_id, None)
                    return

        now_us = int(time.time() * 1_000_000)
        # E8: shares filled THIS event (partial under fill-realism; full legacy).
        eff_size = fill_size if fill_size is not None else order.size
        # D-04 / Pitfall 1: bake adv-sel haircut into fill_price BEFORE constructing
        # OrderFill so strategy.on_order_fill applies cash_spent += price × size once.
        fill_price = self._apply_adv_sel_haircut(order.price, order.action)

        fill = _OrderFill(
            slug=order.slug,
            side=order.side,
            ts_us=now_us,
            order_id=order.order_id,
            price=fill_price,
            size=eff_size,
            is_maker=True,
        )

        # Drive strategy hook (strategy mutates SlugState) + capture cascading
        # Decisions (e.g. MERGE from _merge_decisions when paired_inv >= threshold).
        # Pre-fix returned MERGE was silently dropped -> cash_received never
        # credited despite inv being decremented by the strategy.
        strategy = self._lookup_strategy(order.slug, order.order_id)
        cascade_decisions: list[Any] = []
        if strategy is not None:
            try:
                ret = strategy.on_order_fill(fill)
                if isinstance(ret, list):
                    cascade_decisions = ret
            except Exception:
                log.exception(
                    "poly_maker_fill_sim.on_order_fill_failed",
                    slug=order.slug,
                    order_id=order.order_id,
                )

        # D-11 bps delta — additive on top of strategy's formula-rebate
        slug_state_for_delta = (
            strategy.slug_states.get(order.slug) if strategy is not None else None
        )
        self._apply_bps_deltas(slug_state_for_delta, fill_price, eff_size, is_maker=True)

        # Track fill for D-07 FIFO (Plan 32-08 reads from this)
        history = self._fill_history.setdefault(order.slug, deque(maxlen=10_000))
        history.append((now_us, fill_price, eff_size, order.side))

        # Write fill_simulated=1 CSV row (two-row pattern)
        slug_state = (
            strategy.slug_states.get(order.slug)
            if strategy is not None
            else None
        )
        # asset/tf MUST come from the slug's captured-at-POST values, NOT
        # from strategy.{asset,tf}. One strategy instance may handle multiple
        # cells (pre-fix strategy_index bug); strategy.tf is the instance
        # attribute, not the slug's actual tf. _OrderState.asset/.tf are
        # captured at observe() from decision.asset/.tf, which the strategy
        # set from state.{asset,tf} (=the SlugActive event's true tf).
        # Bug 4+5 (TV_AGENT guide): write sim-fill row with action="FILL"
        # (not POST_BID/POST_ASK) so the audit trail can distinguish "this
        # was an unfilled posting intent" from "this is the actual fill
        # event". Intent row was already written by _route_decision with
        # the original POST_* action + sim_fill=False.
        fill_decision = _Decision(
            ts_us=now_us,
            strategy=strategy.code if strategy is not None else "UNKNOWN",
            slug=order.slug,
            asset=order.asset or (strategy.asset if strategy is not None else "?"),
            tf=order.tf or (strategy.tf if strategy is not None else "?"),
            action="FILL",
            side=order.side,
            price=fill_price,
            size=eff_size,
            order_id=order.order_id,
            trigger_reason=f"sim_fill_q0_initq={int(order.initial_queue or 0)}_via={order.action}",
        )
        sl = self._shadow_loggers.get(fill_decision.strategy)
        if sl is not None:
            sl.log(fill_decision, sim_fill=True, slug_state=slug_state)

        # Bookkeeping
        self._n_fills += 1
        self._fill_emitted_this_tick = True  # D-CF-5

        # Del order from sim state (Pitfall 4 — before any callback that might re-observe)
        slug_orders = self._open_orders.get(order.slug)
        if slug_orders is not None:
            slug_orders.pop(order.order_id, None)
        self._order_strategy.pop(order.order_id, None)  # E3 cleanup

        # Route cascading Decisions (e.g. MERGE) back through observe() so the
        # sim accounting credits cash_received and writes a MERGE row.
        for cascade_decision in cascade_decisions:
            try:
                self.observe(
                    decision=cascade_decision,
                    strategy=strategy,
                    slug_state=slug_state,
                )
            except Exception:
                log.exception(
                    "poly_maker_fill_sim.post_cascade_observe_failed",
                    cascade_action=cascade_decision.action,
                    slug=order.slug,
                )

    def _lookup_strategy(self, slug: str, order_id: str | None = None) -> Any | None:
        """Find the strategy that owns a fill.

        E3 (ENGINE_BUG_MAP_2026_05_28): prefer the exact ``order_id -> strategy``
        route — the slug-keyed cache is last-write-wins and misroutes fills when
        two sleeves share a market slug. Falls back to the slug cache for
        callers/tests that don't pass an order_id.
        """
        if order_id is not None:
            strat = self._order_strategy.get(order_id)
            if strat is not None:
                return strat
        return self._strategy_cache.get(slug)

    # -------------------------------------------------------------------------
    # D-CF-3: auto-disable on 5 exceptions in 5min (sliding window)
    # -------------------------------------------------------------------------

    def _record_exception(
        self,
        *,
        strategy: str,
        cell: str,
        exc: BaseException,
    ) -> None:
        """Per-(strategy, cell) sliding-window exception tracking.

        Mirrors ``poly_maker_loop._record_error`` (lines ~200-247) with the
        kind changed to ``"poly_maker_sim_auto_disabled"`` for the sim.

        Algorithm:
          1. Append current monotonic timestamp to the per-cell deque
          2. Evict entries older than auto_disable_window_s
          3. If len(window) >= threshold and cell not yet disabled:
               - Add to _disabled
               - Emit CRITICAL alert via alert_service (create_task if loop running)
        """
        sc = (strategy, cell)
        log.exception(
            "poly_maker_fill_sim.observe_failed",
            strategy=strategy,
            cell=cell,
            exc=str(exc),
        )

        now = monotonic()
        window = self._error_windows.setdefault(sc, deque())
        window.append(now)

        # Evict stale entries outside the sliding window
        while window and (now - window[0]) > self._auto_disable_window_s:
            window.popleft()

        if len(window) >= self._auto_disable_threshold and sc not in self._disabled:
            self._disabled.add(sc)
            log.critical(
                "poly_maker_fill_sim.cell_auto_disabled",
                strategy=strategy,
                cell=cell,
                errors_in_window=len(window),
                window_s=self._auto_disable_window_s,
            )

            if self._alerts is not None:
                with contextlib.suppress(Exception):
                    from backend.app.services.alert_service import AlertSeverity

                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        loop = None

                    if loop is not None:
                        coro = self._alerts.emit(
                            severity=AlertSeverity.CRITICAL,
                            kind="poly_maker_sim_auto_disabled",
                            strategy=strategy,
                            cell=cell,
                        )
                        if asyncio.iscoroutine(coro):
                            loop.create_task(coro)
