"""Phase 30 Plan 03 — ACC-M: Maker Pair Arbitrage (BID-only).

Port of ``C:\\Users\\alexandre bandarra\\Desktop\\global\\shadow_engine\\strategies\\acc_m.py``
adapted for TV's per-side ``L25Update`` event shape. The shadow_engine variant
receives one L25Update containing both sides; TV's L25Update is per-side, so
this strategy caches the last-known L25 snapshot per ``(slug, side)`` and
runs the full evaluation pipeline only once both sides are primed.

Reference: ``TV_DEPLOY_SPEC_ACC_M_2026_05_18.md`` §3 (decision rules) +
``TV_AGENT_HANDOFF_2026_05_18.md``.

Decision rules:
  1. POST BIDs on both Up + Down sides when ``sum_bids < $1.00``
  2. Strict inventory balance (max ``MAX_IMBALANCE_SHARES`` 5 imbalance)
  3. Cancel if displaced >= 3¢ from current best_bid OR aged >= 20s
  4. MERGE paired inventory continuously when ``min(inv_up, inv_dn) >= 5``
  5. REDEEM leftover single-side at slug resolution (winner side only)

CLAUDE.md invariants honored:

- inv #4 (closed-bar): event handlers receive only closed L25 snapshots
  from BookMirror (snapshot boundary enforced upstream).
- inv #10 (secrets): ``structlog.get_logger(__name__)`` at module top;
  the global ``redact_secrets_processor`` catches HEX_PRIVKEY leaks.
- inv #13 (TV-native data): pure-function module — no imports from
  ``engine.*``, ``venues.polymarket.client``, ``asyncpg``, ``httpx``,
  ``web3``, ``aiohttp``, or ``requests``. Strategy never touches a feed
  directly; it consumes events delivered by the engine.

Trading invariants (TV_DEPLOY_SPEC_ACC_M §3 + CLAUDE.md inv #1, #2):

- ``MIN_POST_SHARES`` = 5 (CLOB minimum) — no posts below this floor.
- POST_BID size is ALWAYS at the minimum (we're a paired-arb maker, not
  a size discoverer — keep flow small per tick).
- ``CANCEL_DISPLACEMENT_CENTS`` = 3 (3¢ threshold; tests 5+6).
- ``CANCEL_MAX_AGE_S`` = 20 (20s threshold; tests 7+8).
- ``MERGE_TRIGGER_PAIRS`` = 5 (boundary at >=; test 11).
- Spec §3.2: do NOT cancel near slug close; let orders fill or expire.
  (Phase 30 enforces the close-buffer at the dispatcher level — this
  module focuses on the pure decision rules.)
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from backend.app.strategies.polymarket.maker.base import (
    MakerStrategyBase,
    _next_order_id,
    quantize_price,
)
from backend.app.strategies.polymarket.maker.types import (
    Decision,
    L25Update,
    OpenOrder,
    OrderFill,
    Side,
    SlugActive,
    SlugResolved,
    SlugState,
    TradePrint,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from backend.app.core.config import Settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module constants (TV_DEPLOY_SPEC_ACC_M §3 — not operator-tunable)
# ---------------------------------------------------------------------------

#: Inventory imbalance cap (TV_DEPLOY_SPEC_ACC_M §4 + §3.1) — stop posting
#: on the side that is already ``MAX_IMBALANCE_SHARES`` ahead of the other.
_MAX_IMBALANCE_SHARES = Decimal("5")

#: Hard absolute cap on per-side inventory (TV_DEPLOY_SPEC_ACC_M §4).
_ABSOLUTE_MAX_INVENTORY = Decimal("50")

#: Edge filter — only post BIDs when ``sum_bids < MAX_SUM_BIDS`` (the spec's
#: $1.00 threshold; minted-pair worth $1 sets the arbitrage boundary).
_MAX_SUM_BIDS = Decimal("1.00")

#: Per-leg spread filter — skip wide books.
_MAX_SPREAD_PER_LEG = Decimal("0.05")

#: Price band — only post BIDs in this range.
_MIN_BID_PRICE = Decimal("0.05")
_MAX_BID_PRICE = Decimal("0.95")


# ---------------------------------------------------------------------------
# AccMStrategy
# ---------------------------------------------------------------------------

class AccMStrategy(MakerStrategyBase):
    """Pure maker pair-arbitrage strategy (BID-only on Polymarket binaries).

    Lifecycle:
      1. ``on_slug_active(evt)``        → seed empty ``SlugState``
      2. ``on_l25_update(evt)``         → cache per-side L25; if both sides
                                          primed, run cancel + post + merge
                                          pipeline
      3. ``on_order_fill(evt)``         → update inventory + counters;
                                          immediate merge check
      4. ``on_trade_print(evt)``        → ignored (ACC-H overrides)
      5. ``on_slug_resolved(evt)``      → force-merge paired + REDEEM
                                          winner residual; cleanup state

    Attributes:
        code        : "ACC-M" — class-level identity used in order IDs.
        config      : Pydantic Settings — read tv_poly_maker_* fields only.
        asset       : "BTC" / "ETH" / "SOL" (D-05: BTC-only on day-1).
        tf          : "5m" / "15m" (D-05: 15m only for ACC-M day-1).
        slug_states : dict[slug, SlugState] — per-slug mutable state.
        _l25_cache  : dict[(slug, side), L25Update] — last-seen per-side
                      snapshot. Used to combine the two sides into the
                      shadow_engine equivalent of an L25Update-with-both-sides.
    """

    code = "ACC-M"

    def __init__(self, settings: "Settings", asset: str, tf: str) -> None:
        self.config = settings
        self.asset = asset
        self.tf = tf
        self.slug_states: dict[str, SlugState] = {}
        self._l25_cache: dict[tuple[str, Side], L25Update] = {}
        self._order_counter = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_local_oid(self) -> str:
        """Build the next local order ID like ``ACC-M-00000001``."""
        self._order_counter += 1
        return _next_order_id(self.code, self._order_counter)

    def _best_bid(self, evt: L25Update) -> Decimal | None:
        """Top-of-book bid price, or None if no bids at all."""
        if not evt.bids:
            return None
        return evt.bids[0][0]

    def _best_ask(self, evt: L25Update) -> Decimal | None:
        """Top-of-book ask price, or None if no asks at all."""
        if not evt.asks:
            return None
        return evt.asks[0][0]

    def _spread(self, evt: L25Update) -> Decimal | None:
        """``best_ask - best_bid``, or None if either side missing."""
        bb = self._best_bid(evt)
        ba = self._best_ask(evt)
        if bb is None or ba is None:
            return None
        return ba - bb

    # ==================================================================
    # Event handlers (5 abstract methods)
    # ==================================================================

    def on_slug_active(self, evt: SlugActive) -> list[Decision]:
        """Seed an empty ``SlugState``. ACC-M emits no decisions on activation."""
        state = SlugState(
            slug=evt.slug,
            condition_id=evt.condition_id,
            token_id_up=evt.token_id_up,
            token_id_dn=evt.token_id_dn,
            asset=evt.asset,
            tf=evt.tf,
            slug_active_ts_us=evt.ts_us,
        )
        self.slug_states[evt.slug] = state
        return []

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        """Cache the per-side L25; if both sides primed, run the full pipeline.

        Order of the three sub-passes (verbatim from shadow_engine acc_m.py
        lines 66-83):
          1. cancel_decisions — displacement OR age rule
          2. post_decisions   — sum_bids + spread + price band + inv +
                                dedup filters
          3. merge_decisions  — paired inv >= threshold trigger

        We cache the incoming snapshot first so that the SECOND side's
        arrival has access to the most recent FIRST-side data.
        """
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        # Cache per-side L25.
        self._l25_cache[(evt.slug, evt.side)] = evt

        # Cancel pass: relies only on per-side best_bid (cached or current),
        # so we can run it on every tick.
        decisions: list[Decision] = []
        decisions.extend(self._cancel_decisions(state, evt))

        # Post pass + merge pass: require BOTH sides primed (sum_bids needs
        # both). Skip the post+merge passes until we have a cached snapshot
        # for both up and dn sides.
        up_cached = self._l25_cache.get((evt.slug, "up"))
        dn_cached = self._l25_cache.get((evt.slug, "dn"))
        if up_cached is not None and dn_cached is not None:
            decisions.extend(
                self._post_decisions(state, up_cached, dn_cached, evt.ts_us)
            )
            decisions.extend(self._merge_decisions(state, evt.ts_us))

            # Phase 31 — PAT taker overlay (TV_AGENT_CHANGES §1).
            # PAT fires immediate parallel buys on BOTH sides when the combined
            # pair cost (asks + taker fees) < $1. In SHADOW mode the
            # MarketBuy Decisions are emitted; maker_loop logs them to CSV
            # rather than submitting orders.
            if getattr(self.config, "tv_poly_maker_acc_m_enable_pat", False):
                decisions.extend(
                    self._pat_decisions(state, up_cached, dn_cached, evt.ts_us)
                )

        return decisions

    def on_trade_print(self, evt: TradePrint) -> list[Decision]:
        """ACC-M ignores trade prints (only ACC-H consumes them)."""
        return []

    def on_order_fill(self, evt: OrderFill) -> list[Decision]:
        """Update inventory + remove filled order. Triggers immediate merge check.

        Two fill kinds (Phase 31+):
        - Maker fills (POST_BID/POST_ASK) — order_id like ``ACC-M-NNNNNNNN``
          or ``ACC-H-NNNNNNNN``. Resolved against ``state.open_orders``.
        - Taker fills (TAKE-*) — emitted by the PAT overlay (Plan 31), the
          ACC-H V3f composite taker (Plan 30-07), and ACC-PC pair-completion
          taker (Plan 31). Bypass ``open_orders`` since takers are market BUYs
          that were never POSTed. Order id pattern: ``TAKE-{STRATEGY}-{ts_us}``.

        Without the TAKE-* branch, all taker fills would log
        ``acc_m.fill.unknown_order_id`` and drop on the floor, leaving
        slug_state.inv_up/dn/cash_spent at 0 even though the simulator
        emitted real fills.
        """
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        # Taker-fill branch (PAT / V3f / PC overlays — order_id starts with "TAKE-").
        # Bypass open_orders since these are market BUYs, not POSTed maker orders.
        if evt.order_id and evt.order_id.startswith("TAKE-"):
            if evt.side == "up":
                state.inv_up += evt.size
            else:
                state.inv_dn += evt.size
            state.cash_spent += evt.size * evt.price
            state.n_fills += 1
            return self._merge_decisions(state, evt.ts_us)

        # Maker-fill branch — must be in open_orders.
        order = state.open_orders.get(evt.order_id)
        if order is None:
            log.warning(
                "acc_m.fill.unknown_order_id",
                slug=evt.slug,
                order_id=evt.order_id,
                size=str(evt.size),
                price=str(evt.price),
            )
            return []

        # Update inventory + cash on the FILLED side.
        if evt.side == "up":
            state.inv_up += evt.size
        else:
            state.inv_dn += evt.size

        state.cash_spent += evt.size * evt.price

        # Remove the order from open_orders (we treat the fill as full-consume;
        # partial-fill semantics are tracked by the upstream order manager via
        # successive OrderFill events with decreasing size — Phase 30.1 live).
        del state.open_orders[evt.order_id]
        state.n_fills += 1

        # Immediate merge check (don't wait for next L25 tick).
        return self._merge_decisions(state, evt.ts_us)

    def on_slug_resolved(self, evt: SlugResolved) -> list[Decision]:
        """Force-merge paired residual + REDEEM winner side residual."""
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        decisions: list[Decision] = []

        # 1. Force final merge of any paired inventory.
        paired = min(state.inv_up, state.inv_dn)
        if paired > 0:
            decisions.append(
                Decision(
                    ts_us=evt.ts_us,
                    strategy=self.code,
                    slug=evt.slug,
                    asset=state.asset,
                    tf=state.tf,
                    action="MERGE",
                    side=None,
                    price=None,
                    size=paired,
                    order_id=None,
                    trigger_reason="merge_slug_end_paired",
                )
            )
            state.inv_up -= paired
            state.inv_dn -= paired
            state.n_merges += 1

        # 2. REDEEM whichever side won, if any residual.
        if evt.winner == "up" and state.inv_up > 0:
            decisions.append(
                Decision(
                    ts_us=evt.ts_us,
                    strategy=self.code,
                    slug=evt.slug,
                    asset=state.asset,
                    tf=state.tf,
                    action="REDEEM",
                    side="up",
                    price=None,
                    size=state.inv_up,
                    order_id=None,
                    trigger_reason="redeem_winner",
                )
            )
        elif evt.winner == "dn" and state.inv_dn > 0:
            decisions.append(
                Decision(
                    ts_us=evt.ts_us,
                    strategy=self.code,
                    slug=evt.slug,
                    asset=state.asset,
                    tf=state.tf,
                    action="REDEEM",
                    side="dn",
                    price=None,
                    size=state.inv_dn,
                    order_id=None,
                    trigger_reason="redeem_winner",
                )
            )

        # 3. State cleanup (parallel to shadow_engine's slug_states.pop).
        self.slug_states.pop(evt.slug, None)
        # Drop cached L25 snapshots for this slug too.
        for s in ("up", "dn"):
            self._l25_cache.pop((evt.slug, s), None)

        return decisions

    # ==================================================================
    # Private sub-pipelines (port from shadow_engine acc_m.py)
    # ==================================================================

    def _cancel_decisions(
        self,
        state: SlugState,
        evt: L25Update,
    ) -> list[Decision]:
        """Emit CANCEL Decisions for open orders that hit either rule.

        Rule 1 (displacement) — ``abs(order.price - best_bid_on_side) >=
        displacement_cents / 100``.
        Rule 2 (age) — ``(now - order.ts_posted_us) >= max_age_s * 1_000_000``.

        Both rules are read from ``self.config.tv_poly_maker_*``. Port from
        shadow_engine/strategies/acc_m.py lines 88-114.
        """
        decisions: list[Decision] = []
        displacement_cents = int(
            self.config.tv_poly_maker_cancel_displacement_cents
        )
        # Threshold in price units (Decimal cents → fractional price).
        displacement_price = Decimal(displacement_cents) / Decimal(100)
        max_age_us = int(self.config.tv_poly_maker_cancel_max_age_s) * 1_000_000

        # Snapshot the keys so we can mutate state.open_orders inside the loop
        # (the engine — not the strategy — owns the actual mutation; here we
        # just remove on CANCEL emit to match shadow_engine's semantics).
        for order_id in list(state.open_orders.keys()):
            order = state.open_orders[order_id]

            # We only act on orders matching the SIDE that just ticked,
            # because we only have a fresh best_bid for THIS side.
            # Cancels on the OTHER side are evaluated when the other-side
            # tick arrives.
            if order.side != evt.side:
                continue

            best_bid = self._best_bid(evt)
            if best_bid is None:
                # Book empty on this side — leave order in place; the next
                # tick with bids will re-evaluate.
                continue

            # Rule 1: displacement.
            displacement = abs(order.price - best_bid)
            if displacement >= displacement_price:
                decisions.append(
                    Decision(
                        ts_us=evt.ts_us,
                        strategy=self.code,
                        slug=evt.slug,
                        asset=state.asset,
                        tf=state.tf,
                        action="CANCEL",
                        side=order.side,
                        price=order.price,
                        size=order.size,
                        order_id=order_id,
                        trigger_reason="cancel_displaced_3c",
                    )
                )
                # Remove from open_orders to match the shadow_engine "we
                # eagerly drop the local-side bookkeeping" semantics. The
                # engine eventually reconciles via CLOB cancel ack in
                # Phase 30.1 live.
                del state.open_orders[order_id]
                state.n_cancels += 1
                continue

            # Rule 2: age.
            age_us = evt.ts_us - order.ts_posted_us
            if age_us >= max_age_us:
                decisions.append(
                    Decision(
                        ts_us=evt.ts_us,
                        strategy=self.code,
                        slug=evt.slug,
                        asset=state.asset,
                        tf=state.tf,
                        action="CANCEL",
                        side=order.side,
                        price=order.price,
                        size=order.size,
                        order_id=order_id,
                        trigger_reason="cancel_age_20s",
                    )
                )
                del state.open_orders[order_id]
                state.n_cancels += 1

        return decisions

    def _post_decisions(
        self,
        state: SlugState,
        up_snap: L25Update,
        dn_snap: L25Update,
        ts_us: int,
    ) -> list[Decision]:
        """Emit POST_BID Decisions for sides that pass all filters.

        Port from shadow_engine/strategies/acc_m.py lines 120-197.
        Adapted to receive per-side cached snapshots (TV API shape).

        Filters (in evaluation order):
          1. per-leg spread filter (``spread > MAX_SPREAD_PER_LEG`` → skip)
          2. sum_bids filter (``sum_bids >= MAX_SUM_BIDS`` → skip)
          3. price band (best_bid outside [MIN_BID_PRICE, MAX_BID_PRICE]
             → skip the side)
          4. inventory imbalance (heavier side > lighter + MAX_IMBALANCE
             → skip the heavy side)
          5. absolute cap (per-side inv >= ABSOLUTE_MAX → skip the side)
          6. dedup (already an open BID on this side at same price → skip)

        We never emit MORE than one POST_BID per side per tick.
        """
        decisions: list[Decision] = []

        # Spread filter — both legs must be tight.
        up_spread = self._spread(up_snap)
        dn_spread = self._spread(dn_snap)
        if up_spread is None or dn_spread is None:
            return []  # half-empty book; skip
        if up_spread > _MAX_SPREAD_PER_LEG or dn_spread > _MAX_SPREAD_PER_LEG:
            return []

        # Sum-bids filter.
        up_best_bid = self._best_bid(up_snap)
        dn_best_bid = self._best_bid(dn_snap)
        if up_best_bid is None or dn_best_bid is None:
            return []
        sum_bids = up_best_bid + dn_best_bid
        if sum_bids >= _MAX_SUM_BIDS:
            return []

        # Phase 31 (TV_AGENT_CHANGES §1) — POST_SIZE/MAX_IMBALANCE/ABS_MAX
        # read from acc_m-specific config fields. Falls back to module
        # constants if config field is unset/zero. ACC-H and ACC-PC inherit
        # this — ACC-H bumps from 5→20 by cascade (test-phase consistency).
        post_size = Decimal(self.config.tv_poly_maker_acc_m_post_size or 0) or \
            self.config.tv_poly_maker_min_post_shares
        max_imbalance = Decimal(
            self.config.tv_poly_maker_acc_m_max_imbalance_shares or 0
        ) or _MAX_IMBALANCE_SHARES
        abs_max = Decimal(
            self.config.tv_poly_maker_acc_m_absolute_max_inventory or 0
        ) or _ABSOLUTE_MAX_INVENTORY

        # Build POST_BID for each side that passes per-side filters.
        for side, best_bid in (("up", up_best_bid), ("dn", dn_best_bid)):
            # Price band.
            if not (_MIN_BID_PRICE <= best_bid <= _MAX_BID_PRICE):
                continue

            # Inventory imbalance — don't accumulate too much on the heavier side.
            if side == "up":
                if state.inv_up > state.inv_dn + max_imbalance:
                    continue
                current_inv = state.inv_up
            else:
                if state.inv_dn > state.inv_up + max_imbalance:
                    continue
                current_inv = state.inv_dn

            # Absolute cap.
            if current_inv >= abs_max:
                continue

            # Dedup — skip if any open BID on this side at SAME quantized price
            # OR more generally if ANY open BID on this side exists (shadow_engine
            # post_bid filter — only one BID per side at a time per the spec's
            # "Do NOT double-post" rule).
            already_open_same_side = False
            quantized = quantize_price(best_bid)
            for o in state.open_orders.values():
                if o.side == side:
                    already_open_same_side = True
                    break
            if already_open_same_side:
                continue

            # Build the POST_BID decision + track it in open_orders so the
            # next tick's _post_decisions sees an open order on this side and
            # short-circuits the dedup check.
            order_id = self._next_local_oid()
            order = OpenOrder(
                order_id=order_id,
                side=side,
                price=quantized,
                size=post_size,
                ts_posted_us=ts_us,
            )
            state.open_orders[order_id] = order

            decisions.append(
                Decision(
                    ts_us=ts_us,
                    strategy=self.code,
                    slug=state.slug,
                    asset=state.asset,
                    tf=state.tf,
                    action="POST_BID",
                    side=side,
                    price=quantized,
                    size=post_size,
                    order_id=order_id,
                    trigger_reason="post_initial_bid",
                )
            )

        return decisions

    def _merge_decisions(
        self,
        state: SlugState,
        ts_us: int,
    ) -> list[Decision]:
        """Emit a single MERGE Decision when ``min(inv_up, inv_dn) >=
        ``tv_poly_maker_merge_trigger_pairs``.

        Port from shadow_engine/strategies/acc_m.py lines 203-210.
        """
        threshold = Decimal(self.config.tv_poly_maker_merge_trigger_pairs)
        paired = min(state.inv_up, state.inv_dn)
        if paired < threshold:
            return []

        # Decrement inventory + bump counters (parallel to shadow_engine's
        # `wallet_balance += pairs * 1.0` recycling — we track on state, not
        # a global wallet float, because TV's PnL is computed from state at
        # the dashboard layer).
        state.inv_up -= paired
        state.inv_dn -= paired
        state.n_merges += 1

        return [
            Decision(
                ts_us=ts_us,
                strategy=self.code,
                slug=state.slug,
                asset=state.asset,
                tf=state.tf,
                action="MERGE",
                side=None,
                price=None,
                size=paired,
                order_id=None,
                trigger_reason=f"merge_paired_>={int(threshold)}",
            )
        ]

    def _pat_decisions(
        self,
        state: SlugState,
        up_evt: L25Update,
        dn_evt: L25Update,
        ts_us: int,
    ) -> list[Decision]:
        """Phase 31 PAT (Pair-Arb Taker) trigger — TV_AGENT_CHANGES §1.

        Fires parallel MarketBuys on BOTH sides when:
          1. Both asks present + price band 0 < ask < 1
          2. Min book depth at best ask on both sides
          3. Min time since slot open
          4. Rate limit since last PAT fire
          5. Per-slug fire cap not exceeded
          6. Pair cost (asks + taker fees) < pat_max_pair_cost
          7. Inventory caps respected

        On trigger: emit 2 TAKE Decisions (up + dn) with size capped by both
        asks' depth. SHADOW mode: maker_loop logs to CSV; no on-chain submit.
        Phase 30.1 live mode: maker_loop runs both via asyncio.gather for
        parallel submission (critical for arb — partial fills are acceptable).
        """
        cfg = self.config

        ba_up = self._best_ask(up_evt)
        ba_dn = self._best_ask(dn_evt)
        if ba_up is None or ba_dn is None:
            return []
        if not (Decimal("0") < ba_up < Decimal("1")):
            return []
        if not (Decimal("0") < ba_dn < Decimal("1")):
            return []

        # Rate limit (microseconds)
        min_us = int(cfg.tv_poly_maker_pat_min_s_between_fires) * 1_000_000
        if (ts_us - state.last_pat_fire_us) < min_us:
            return []

        # Per-slug cap
        if state.n_pat_fires >= int(cfg.tv_poly_maker_pat_max_fires_per_slug):
            return []

        # Min time after slot open
        min_open_us = (
            int(cfg.tv_poly_maker_pat_min_time_after_open_s) * 1_000_000
        )
        if (ts_us - state.slug_active_ts_us) < min_open_us:
            return []

        # Min book depth at best ask, both sides
        min_depth = Decimal(cfg.tv_poly_maker_pat_min_book_depth_each_side)
        depth_up = up_evt.asks[0][1] if up_evt.asks else Decimal("0")
        depth_dn = dn_evt.asks[0][1] if dn_evt.asks else Decimal("0")
        if depth_up < min_depth or depth_dn < min_depth:
            return []

        # Pair cost gate: bid+bid+fees < pat_max_pair_cost
        from backend.app.strategies.polymarket.maker.base import taker_fee
        fee_up = taker_fee(ba_up)
        fee_dn = taker_fee(ba_dn)
        pair_cost = ba_up + ba_dn + fee_up + fee_dn
        max_pair_cost = Decimal(str(cfg.tv_poly_maker_pat_max_pair_cost))
        if pair_cost <= Decimal("0") or pair_cost >= max_pair_cost:
            return []

        # Inventory caps
        abs_max = Decimal(cfg.tv_poly_maker_acc_m_absolute_max_inventory)
        if state.inv_up >= abs_max or state.inv_dn >= abs_max:
            return []

        # Take size = min(configured, depth_up, depth_dn) — but never below
        # CLOB minimum (5 shares).
        take_size = min(
            Decimal(cfg.tv_poly_maker_pat_take_size),
            depth_up,
            depth_dn,
        )
        if take_size < Decimal(cfg.tv_poly_maker_min_post_shares):
            return []

        # State update — fires increment together; record timestamp.
        state.n_pat_fires += 1
        state.last_pat_fire_us = ts_us

        reason = f"pat_pair_cost={pair_cost:.4f}"
        return [
            Decision(
                ts_us=ts_us,
                strategy=self.code,
                slug=state.slug,
                asset=state.asset,
                tf=state.tf,
                action="TAKE",
                side="up",
                price=ba_up,
                size=take_size,
                order_id=None,
                trigger_reason=reason,
            ),
            Decision(
                ts_us=ts_us,
                strategy=self.code,
                slug=state.slug,
                asset=state.asset,
                tf=state.tf,
                action="TAKE",
                side="dn",
                price=ba_dn,
                size=take_size,
                order_id=None,
                trigger_reason=reason,
            ),
        ]


__all__ = ["AccMStrategy"]
