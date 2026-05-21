"""Phase 31 — PAT-SHADOW: research sleeve (TV_AGENT_CHANGES_2026_05_19.md §5).

Pure PAT trigger with NO maker BIDs (POST_SIZE=0). Permissive parameters
(``pat_max_pair_cost=1.02`` vs HYBRID's ``1.00``). Purpose: collect data
on how often the PAT trigger fires at relaxed thresholds, to inform future
tightening of the production PAT params.

Inherits ``AccMStrategy`` but disables the maker post path by reading
``tv_poly_maker_pat_shadow_post_size=0``. Replaces the PAT param set with
``tv_poly_maker_pat_shadow_*`` so this sleeve has its own knobs separate
from PAT+ACC-M HYBRID.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from backend.app.strategies.polymarket.maker.acc_m import AccMStrategy
from backend.app.strategies.polymarket.maker.base import taker_fee
from backend.app.strategies.polymarket.maker.types import (
    Decision,
    L25Update,
    SlugState,
)

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.core.config import Settings

log = structlog.get_logger(__name__)


class PatShadowStrategy(AccMStrategy):
    """PAT-only research sleeve. Same PAT trigger logic as HYBRID with
    permissive thresholds; no maker BIDs.

    Inherits AccMStrategy for the slug-lifecycle plumbing (state init, fill
    handling, slug resolve) but overrides on_l25_update to skip the maker
    post pass and run a PAT-shadow check instead.
    """

    code = "PAT-SHADOW"

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        """Skip maker post path; run only cancel + PAT-shadow trigger.

        Cancel still runs in case the sleeve was reconfigured at runtime to
        emit POST_BIDs (defensive — config tweak shouldn't strand orders).
        """
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        # Cache per-side L25 (parent expects this for any post/merge path).
        self._l25_cache[(evt.slug, evt.side)] = evt

        decisions: list[Decision] = []
        decisions.extend(self._cancel_decisions(state, evt))

        # Skip _post_decisions + _merge_decisions entirely — PAT-SHADOW is
        # research-only. Run the PAT trigger with PAT-SHADOW params.
        up_cached = self._l25_cache.get((evt.slug, "up"))
        dn_cached = self._l25_cache.get((evt.slug, "dn"))
        if up_cached is not None and dn_cached is not None:
            decisions.extend(
                self._pat_shadow_decisions(state, up_cached, dn_cached, evt.ts_us)
            )

        return decisions

    def _pat_shadow_decisions(
        self,
        state: SlugState,
        up_evt: L25Update,
        dn_evt: L25Update,
        ts_us: int,
    ) -> list[Decision]:
        """Same gates as _pat_decisions but reads pat_shadow_* config and
        emits PAT-SHADOW-tagged Decisions for CSV.
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

        # Rate limit
        min_us = int(cfg.tv_poly_maker_pat_shadow_min_s_between_fires) * 1_000_000
        if (ts_us - state.last_pat_fire_us) < min_us:
            return []

        # Per-slug cap (PAT-SHADOW has higher cap than HYBRID — 30 vs 10)
        if state.n_pat_fires >= int(cfg.tv_poly_maker_pat_shadow_max_fires_per_slug):
            return []

        # Min time after slot open
        min_open_us = (
            int(cfg.tv_poly_maker_pat_shadow_min_time_after_open_s) * 1_000_000
        )
        if (ts_us - state.slug_active_ts_us) < min_open_us:
            return []

        # Min book depth at best ask
        min_depth = Decimal(cfg.tv_poly_maker_pat_shadow_min_book_depth_each_side)
        depth_up = up_evt.asks[0][1] if up_evt.asks else Decimal("0")
        depth_dn = dn_evt.asks[0][1] if dn_evt.asks else Decimal("0")
        if depth_up < min_depth or depth_dn < min_depth:
            return []

        # Pair cost gate (PAT-SHADOW permissive: max_pair_cost=1.02)
        fee_up = taker_fee(ba_up)
        fee_dn = taker_fee(ba_dn)
        pair_cost = ba_up + ba_dn + fee_up + fee_dn
        max_pair_cost = Decimal(str(cfg.tv_poly_maker_pat_shadow_max_pair_cost))
        if pair_cost <= Decimal("0") or pair_cost >= max_pair_cost:
            return []

        # Inventory caps (reuse ACC-M's abs max — PAT-SHADOW doesn't have its own)
        abs_max = Decimal(cfg.tv_poly_maker_acc_m_absolute_max_inventory)
        if state.inv_up >= abs_max or state.inv_dn >= abs_max:
            return []

        take_size = min(
            Decimal(cfg.tv_poly_maker_pat_shadow_take_size),
            depth_up,
            depth_dn,
        )
        if take_size < Decimal(cfg.tv_poly_maker_min_post_shares):
            return []

        state.n_pat_fires += 1
        state.last_pat_fire_us = ts_us

        reason = f"pat_shadow_pair_cost={pair_cost:.4f}"
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


__all__ = ["PatShadowStrategy"]
