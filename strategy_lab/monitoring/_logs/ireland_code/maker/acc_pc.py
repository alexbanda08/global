"""Phase 31 — ACC-PC: Pair-Completion Taker (TV_AGENT_CHANGES_2026_05_19.md §4).

Inherits ``AccMStrategy`` (POST_BID + CANCEL + MERGE) and ADDS a reactive
pair-completion taker that fires ONLY when:

  1. Per-side inventory is imbalanced (``abs(inv_up - inv_dn) >= 1``)
  2. Slot has been open long enough (``pc_min_time_before_taker_s``)
  3. Pair cost gate: ``avg_lead_cost + lag_ask + taker_fee < pc_max_pair_cost``
  4. Maker bid on lag side is sufficiently far from ask (avoid self-filling)
  5. CVD (cumulative volume delta) on lag side shows buyer pressure
  6. Rate + per-slug fire caps not exceeded
  7. Inventory cap on lag side not breached

The taker rebalances toward neutral while preserving the pair-arb economic
edge. Designed for ``btc_15m`` cells per the cell-remap table (TV_AGENT_CHANGES §6).

CLAUDE.md invariants honored (same as ACC-M / ACC-H):
- inv #4 (closed-bar events from feed)
- inv #10 (structlog redact processor)
- inv #13 (pure module, no engine/venue imports)
"""
from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from backend.app.strategies.polymarket.maker.acc_m import AccMStrategy
from backend.app.strategies.polymarket.maker.base import taker_fee
from backend.app.strategies.polymarket.maker.types import (
    Decision,
    L25Update,
    Side,
    SlugActive,
    SlugState,
    TradePrint,
)

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.core.config import Settings

log = structlog.get_logger(__name__)


#: Rolling CVD window — 30s at 2 Hz upper bound = 60 entries.
_CVD_WINDOW_MAXLEN = 60


class AccPCStrategy(AccMStrategy):
    """Maker + pair-completion-taker overlay.

    Inherits everything from AccMStrategy:
      - on_slug_active  → seed SlugState (then we extend below)
      - on_l25_update   → cancel + post + merge passes (we add PC taker)
      - on_order_fill   → inventory update + immediate merge check
      - on_slug_resolved → force-merge + REDEEM winner residual

    Extends with:
      - on_trade_print  → update CVD window per (slug, side)
      - on_l25_update   → after maker passes, check PC trigger and emit
                          TAKE Decision if all gates pass
    """

    code = "ACC-PC"

    def __init__(self, settings: "Settings", asset: str, tf: str) -> None:
        super().__init__(settings, asset, tf)
        # Per-(slug, side) CVD rolling deques. Append (ts_us, signed_size)
        # tuples on every TradePrint; evict by maxlen + by 30s age in lookup.
        self._cvd: dict[tuple[str, Side], deque[tuple[int, Decimal]]] = {}
        # Per-(slug, side) average lead-cost cache — updated on fills via
        # SlugState.cash_spent / inv_<side>. Read at PC check time.

    # ------------------------------------------------------------------
    # State init — extend AccM's seed to add CVD deques
    # ------------------------------------------------------------------

    def on_slug_active(self, evt: SlugActive) -> list[Decision]:
        result = super().on_slug_active(evt)
        # Initialize empty CVD deques for both sides.
        self._cvd[(evt.slug, "up")] = deque(maxlen=_CVD_WINDOW_MAXLEN)
        self._cvd[(evt.slug, "dn")] = deque(maxlen=_CVD_WINDOW_MAXLEN)
        return result

    # ------------------------------------------------------------------
    # CVD tracking
    # ------------------------------------------------------------------

    def on_trade_print(self, evt: TradePrint) -> list[Decision]:
        """Update CVD window on every trade print for the lag-side check.

        Signed size: BUY taker → +size, SELL taker → -size. Aggregated over
        30s for the pc_cvd_threshold gate.
        """
        cvd_q = self._cvd.get((evt.slug, evt.side))
        if cvd_q is None:
            # Slug not active yet (or already resolved) — ignore.
            return []
        # aggressor="buy" → +size, "sell" → -size.
        signed = evt.size if evt.aggressor == "buy" else -evt.size
        cvd_q.append((evt.ts_us, signed))
        # Parent (ACC-M) ignores trade prints — no decisions from this path.
        return []

    # ------------------------------------------------------------------
    # PC taker check — runs on every L25Update after maker passes
    # ------------------------------------------------------------------

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        # First, run all the maker logic (cancel + post + merge + PAT if
        # enabled — though for ACC-PC's cells, we expect PAT disabled and
        # PC overlay takes the place of PAT).
        decisions = super().on_l25_update(evt)

        cfg = self.config
        if not getattr(cfg, "tv_poly_maker_acc_pc_enable_pc_taker", False):
            return decisions

        state = self.slug_states.get(evt.slug)
        if state is None:
            return decisions

        # Both-sides primed check (same as ACC-M's post/merge path).
        up_cached = self._l25_cache.get((evt.slug, "up"))
        dn_cached = self._l25_cache.get((evt.slug, "dn"))
        if up_cached is None or dn_cached is None:
            return decisions

        pc_decision = self._pc_taker_decision(
            state, up_cached, dn_cached, evt.ts_us
        )
        if pc_decision is not None:
            decisions.append(pc_decision)

        return decisions

    # ------------------------------------------------------------------
    # PC taker trigger (TV_AGENT_CHANGES §4 — check_pc_taker)
    # ------------------------------------------------------------------

    def _pc_taker_decision(
        self,
        state: SlugState,
        up_evt: L25Update,
        dn_evt: L25Update,
        ts_us: int,
    ) -> Decision | None:
        """Reactive pair-completion taker. Fire ONLY when imbalanced AND profitable.

        Returns a single TAKE Decision (on the lag side) or None.
        """
        cfg = self.config

        imbalance = abs(state.inv_up - state.inv_dn)
        if imbalance < Decimal("1"):
            return None

        # Identify lag (under-held) vs lead (over-held) side.
        if state.inv_up < state.inv_dn:
            lag_side: Side = "up"
            lag_evt = up_evt
            lead_inv = state.inv_dn
        else:
            lag_side = "dn"
            lag_evt = dn_evt
            lead_inv = state.inv_up

        # Min time since slot open.
        min_open_us = (
            int(cfg.tv_poly_maker_pc_min_time_before_taker_s) * 1_000_000
        )
        if (ts_us - state.slug_active_ts_us) < min_open_us:
            return None

        # Per-slug fire cap.
        if state.n_pc_taker >= int(cfg.tv_poly_maker_pc_max_taker_per_slug):
            return None

        # Rate limit.
        rate_us = int(cfg.tv_poly_maker_pc_min_s_between_taker_s) * 1_000_000
        if (ts_us - state.last_pc_taker_us) < rate_us:
            return None

        lag_ask = self._best_ask(lag_evt)
        if lag_ask is None:
            return None
        if not (Decimal("0") < lag_ask < Decimal("1")):
            return None

        # Inventory cap on lag side.
        lag_inv = state.inv_up if lag_side == "up" else state.inv_dn
        abs_max = Decimal(cfg.tv_poly_maker_acc_pc_absolute_max_inventory)
        if lag_inv >= abs_max:
            return None

        # Pair cost gate: avg cost paid on LEAD side + lag ask + lag fee < threshold.
        if lead_inv <= Decimal("0"):
            return None
        avg_lead_cost = state.cash_spent / lead_inv
        fee = taker_fee(lag_ask)
        pair_cost = avg_lead_cost + lag_ask + fee
        max_pair = Decimal(str(cfg.tv_poly_maker_pc_max_pair_cost))
        if pair_cost >= max_pair:
            return None

        # Spread filter: don't take if our maker BID on lag side is close to ask.
        # (Skip if any open bid on lag side is within pc_min_spread_to_taker of ask.)
        min_spread = Decimal(str(cfg.tv_poly_maker_pc_min_spread_to_taker))
        for o in state.open_orders.values():
            if o.side == lag_side:
                if (lag_ask - o.price) <= min_spread:
                    return None

        # CVD filter: only fire when lag side has buyer pressure.
        cvd_q = self._cvd.get((state.slug, lag_side))
        cvd_30s = Decimal("0")
        if cvd_q is not None:
            window_start_us = ts_us - int(cfg.tv_poly_maker_pc_cvd_window_s) * 1_000_000
            cvd_30s = sum((d for (t, d) in cvd_q if t >= window_start_us), Decimal("0"))
        cvd_threshold = Decimal(str(cfg.tv_poly_maker_pc_cvd_threshold))
        if cvd_30s <= cvd_threshold:
            return None

        # Size: min(configured, imbalance) — never below CLOB minimum.
        take_size = min(
            Decimal(cfg.tv_poly_maker_pc_taker_size),
            imbalance,
        )
        if take_size < Decimal(cfg.tv_poly_maker_min_post_shares):
            return None

        # State update
        state.n_pc_taker += 1
        state.last_pc_taker_us = ts_us

        return Decision(
            ts_us=ts_us,
            strategy=self.code,
            slug=state.slug,
            asset=state.asset,
            tf=state.tf,
            action="TAKE",
            side=lag_side,
            price=lag_ask,
            size=take_size,
            order_id=None,
            trigger_reason=f"pc_pair_cost={pair_cost:.4f},cvd30s={cvd_30s:.2f}",
        )


__all__ = ["AccPCStrategy"]
