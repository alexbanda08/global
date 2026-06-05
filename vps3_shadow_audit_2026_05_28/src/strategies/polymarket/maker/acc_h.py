"""Phase 30 Plan 07 — ACC-H = ACC-M maker bids + V3f composite taker.

Inherits all of ``AccMStrategy`` (POST_BID + CANCEL + MERGE) and ADDS a
4-rule OR composite taker on every trade-print event. V3f decoded at 78.9%
coverage from a $212k/day reference wallet (per ``TV_DEPLOY_SPEC_ACC_H_
2026_05_18.md`` §3.5).

Rules (port from ``shadow_engine/strategies/acc_h.py``):

  Rule A — Discount-capture:
    ``current_ask < $0.50 AND (60s_median_ask - current_ask) >= $0.03``
    → TAKE on ``evt.side``.

  Rule B — Sharp-drop:
    ``max(trade_prices_5s) - current_ask >= $0.02``
    → TAKE on ``evt.side``.

  Rule C — Early-slot:
    ``0 <= slug_offset_s <= 60 AND no_prior_fill_on_side``
    → TAKE on ``evt.side``.

  Rule D — Buy-pressure-then-dip:
    ``sum(buy_vol_60s) > 50 shares AND max_trade_5s - current_ask >= $0.001``
    → TAKE on ``evt.side``.

Rate limits (D-10 verbatim from chain decode; NOT shadow-tightened):

  * ``MIN_S_BETWEEN_TAKER_BUYS``  — 5.0s per side (default).
  * ``MAX_TAKER_BUYS_PER_SLUG``   — 50 (default).
  * ``ABSOLUTE_MAX_INVENTORY``    — 100 shares per side (looser than ACC-M's 50).

CLAUDE.md invariants honored:

- inv #4 (closed-bar): events are frozen+slots snapshots from BookMirror /
  TradeMirror; the strategy reads only.
- inv #10 (secrets never logged): ``structlog.get_logger(__name__)`` global
  + ``redact_secrets_processor`` covers any HEX leak.
- inv #13 (TV-native data): pure module — zero imports from ``engine.*``,
  ``venues.polymarket.client``, ``asyncpg``, ``httpx``, ``web3``,
  ``requests``, ``aiohttp``. Strategy never touches a feed directly.

Pitfall 5 (RESEARCH §"Pitfall 5"): every rolling deque is constructed with
``maxlen=N`` at slug-active time. NO in-loop popleft/trim calls in the hot
path; ``deque(maxlen=N).append()`` auto-drops the oldest entry in O(1).
Tested by ``test_16_pitfall_5`` — asserts no `trim` helper exists.

D-09 (CONTEXT verbatim): BOTH maker bids (inherited from ACC-M) AND
composite TAKE decisions emit from the first slug — no staged ramp.
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
    OrderFill,
    Side,
    SlugActive,
    SlugResolved,
    TradePrint,
)

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    from backend.app.core.config import Settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pitfall 5 — pre-sized deque maxlen values
# ---------------------------------------------------------------------------

#: 60s window at 2 Hz worst case → 120 entries (used for Rule A median + Rule D dip).
_ASKS_HISTORY_MAXLEN = 120

#: 5s window at 10 Hz worst case → 50 entries (used for Rule B max + Rule D dip).
_TRADES_HISTORY_MAXLEN = 50

#: 60s window at 5 Hz worst case → 300 entries (used for Rule D buy volume sum).
_BUY_VOL_HISTORY_MAXLEN = 300


# ---------------------------------------------------------------------------
# V3f decoded rule thresholds (TV_DEPLOY_SPEC_ACC_H_2026_05_18.md §3.5 + §4)
# ---------------------------------------------------------------------------

# Rule A — Discount-capture. Window enforced by ASKS_HISTORY_MAXLEN.
_RULE_A_MAX_TAKER_PRICE_DISCOUNT = Decimal("0.50")
_RULE_A_MIN_ASK_DROP_60S = Decimal("0.03")
_RULE_A_MIN_HISTORY_ENTRIES = 10

# Rule B — Sharp-drop. Window enforced by TRADES_HISTORY_MAXLEN.
_RULE_B_MIN_TRADE_DROP_5S = Decimal("0.02")
_RULE_B_MIN_HISTORY_ENTRIES = 3

# Rule C — Early-slot.
_RULE_C_EARLY_SLOT_END_US = 60 * 1_000_000

# Rule D — Buy-pressure-then-dip. Windows enforced by BUY_VOL + TRADES MAXLENs.
_RULE_D_MIN_BUY_VOL_60S = Decimal("50")
_RULE_D_MIN_PRICE_DIP_5S = Decimal("0.001")
_RULE_D_MIN_TRADES = 2

# Inventory cap — looser than ACC-M because the taker rebalances.
_ABSOLUTE_MAX_INVENTORY_ACC_H = Decimal("100")

# TAKER size (CLOB minimum 5; reuse settings field).
# Read from settings.tv_poly_maker_min_post_shares at fire time.

# Bug 10 — pair-cost arb gate. ALL V3f rules (A/B/C/D) must verify that
# taking this side + accumulating the opposite side via market also
# produces an arb edge after taker fees on BOTH sides. Without this gate,
# the strategy buys one side blindly based on price-history patterns
# even when ba_up + ba_dn + total_taker_fees >= $1.00 (no edge — guaranteed
# loss after slippage + gas). Spec REV-2026-05-19 §ACC-H mandates this
# but the original implementation (per shadow_engine port) omitted it.
# Operator complaint: "they were supposed to accumulate inventory in both
# sides when price sum up+down - 0.97, not simply buying without any
# measure". $1.00 is the bare-breakeven threshold — operator-tunable
# downward (e.g. 0.97 for 3¢ guard) via config in a follow-up.
_MAX_PAIR_COST_ACC_H = Decimal("1.00")

# Rule C re-implementation — dislocation threshold. The original spec text
# ("best_ask sum > 1.005 → TAKE both sides — early arb opportunity") was
# inverted; sum > $1 means OVERPRICED (negative edge). Correct semantics:
# fire when |sum_asks - 1.00| > threshold AND the pair-cost gate (above)
# passes. The underpriced side gets the TAKE (lower ask = greater upside
# at $1 redemption).
_RULE_C_MIN_DISLOCATION = Decimal("0.005")


# ---------------------------------------------------------------------------
# AccHStrategy
# ---------------------------------------------------------------------------

class AccHStrategy(AccMStrategy):
    """ACC-M maker + V3f 4-rule composite taker.

    Inherits all 5 event handlers from ``AccMStrategy`` and OVERRIDES:
      * ``on_slug_active`` — appends per-slug+side rolling-history deques.
      * ``on_l25_update`` — appends best_ask to history then runs ACC-M pipeline.
      * ``on_trade_print`` — feeds trade/buy-vol histories then runs the
        4-rule OR composite + rate-limit gates; emits TAKE on fire.
      * ``on_slug_resolved`` — also cleans up history deques.
    Other handlers (``on_order_fill``) inherit verbatim.
    """

    code = "ACC-H"

    def __init__(self, settings: "Settings", asset: str, tf: str) -> None:
        super().__init__(settings, asset, tf)
        # Rolling per-(slug, side) histories — pre-sized at slug_active time.
        # Each deque holds (ts_us, value [+ aux]) tuples; auto-drops oldest.
        self._ask_history: dict[tuple[str, Side], deque] = {}
        self._trade_history: dict[tuple[str, Side], deque] = {}
        self._buy_vol_history: dict[tuple[str, Side], deque] = {}
        # Rate-limit state per (slug, side).
        self._last_taker_fire_us: dict[tuple[str, Side], int] = {}
        # Taker-buy count per SLUG (sum across sides — D-10 spec).
        self._taker_buy_count_per_slug: dict[str, int] = {}

    # ==================================================================
    # Event handlers
    # ==================================================================

    def on_slug_active(self, evt: SlugActive) -> list[Decision]:
        """Inherit ACC-M slug seed + pre-size all ACC-H rolling deques.

        Pitfall 5: deques constructed ONCE per slug at activation with
        maxlen=N; subsequent on_l25_update / on_trade_print calls only
        .append() (O(1) with auto-drop). No in-loop popleft trimming.
        """
        decisions = super().on_slug_active(evt)
        for side in ("up", "dn"):
            key = (evt.slug, side)
            self._ask_history[key] = deque(maxlen=_ASKS_HISTORY_MAXLEN)
            self._trade_history[key] = deque(maxlen=_TRADES_HISTORY_MAXLEN)
            self._buy_vol_history[key] = deque(maxlen=_BUY_VOL_HISTORY_MAXLEN)
            self._last_taker_fire_us[key] = 0
        self._taker_buy_count_per_slug[evt.slug] = 0
        return decisions

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        """Record best_ask into ask history; then run ACC-M pipeline.

        The ask history feeds Rule A (60s median) + Rule D (current_ask vs
        max recent trade). Recording happens BEFORE inherited eval so the
        history reflects the current tick.
        """
        # Record best_ask (if present) into the per-(slug, side) history.
        key = (evt.slug, evt.side)
        hist = self._ask_history.get(key)
        if hist is not None and evt.asks:
            hist.append((evt.ts_us, evt.asks[0][0]))
        return super().on_l25_update(evt)

    def on_trade_print(self, evt: TradePrint) -> list[Decision]:
        """Feed trade + buy-vol histories; run V3f 4-rule OR composite.

        Order of operations per shadow_engine/strategies/acc_h.py + Bug 10:
          1. Append (ts, price) to trade_history[(slug, side)].
          2. If aggressor == "buy", append (ts, size) to buy_vol_history.
          3. Run rate-limit gates (MIN_S + MAX_PER_SLUG + ABS_MAX_INV).
          4. Bug 10: pair-cost arb gate. Pre-fix the V3f composite fired
             blindly on single-side price patterns even when the COMBINED
             pair (ba_up + ba_dn) cost more than $1.00 after taker fees —
             guaranteed loss. ALL rules now require ba_up + ba_dn +
             fee_up + fee_dn < _MAX_PAIR_COST_ACC_H.
          5. Evaluate 4 rules in order A → B → C → D; first hit fires.
             Rules A / B / D fire on evt.side. Rule C (dislocation) may
             override the fire side to the underpriced one.
          6. On fire: build Decision(action="TAKE", side=fire_side, ...);
             record the fire timestamp + bump counter.
        """
        # 1 + 2: append to histories.
        key = (evt.slug, evt.side)
        t_hist = self._trade_history.get(key)
        if t_hist is not None:
            t_hist.append((evt.ts_us, evt.price))
        if evt.aggressor == "buy":
            bv_hist = self._buy_vol_history.get(key)
            if bv_hist is not None:
                bv_hist.append((evt.ts_us, evt.size))

        # 3. Rate-limit gates.
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []

        # Phase B convergence-window — no NEW V3f composite takes within
        # ``tv_poly_maker_acc_h_stop_posting_offset_s`` of slug end. Histories
        # above still update (so post-window analysis is intact); only the
        # fire path short-circuits. See TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC §2.4.
        if state.slug_end_ts_us is not None:
            offset_s = int(
                getattr(
                    self.config,
                    f"tv_poly_maker_{self.code.lower().replace('-', '_')}_stop_posting_offset_s",
                    0,
                )
            )
            if offset_s > 0 and (state.slug_end_ts_us - evt.ts_us) < offset_s * 1_000_000:
                return []

        if not self._rate_limits_ok(evt.slug, evt.side, evt.ts_us, state):
            return []

        # 4. Bug 10 — pair-cost arb gate.
        if not self._pair_cost_arb_ok(evt.slug):
            return []

        # 5. Evaluate rules in priority order.
        fire_side: Side = evt.side
        trigger: str | None = None
        if self._rule_a_discount(evt):
            trigger = "rule_a_discount"
        elif self._rule_b_sharp_drop(evt):
            trigger = "rule_b_sharp_drop"
        else:
            rule_c_side = self._rule_c_early_slot(evt, state)
            if rule_c_side is not None:
                trigger = "rule_c_dislocation"
                fire_side = rule_c_side
            elif self._rule_d_buy_pressure_dip(evt):
                trigger = "rule_d_buy_pressure_dip"

        if trigger is None:
            return []

        # 6. Build TAKE Decision + record fire on the chosen side.
        self._record_taker_fire(evt.slug, fire_side, evt.ts_us)
        take_size = self.config.tv_poly_maker_min_post_shares
        return [Decision(
            ts_us=evt.ts_us,
            strategy=self.code,
            slug=evt.slug,
            asset=state.asset,
            tf=state.tf,
            action="TAKE",
            side=fire_side,
            price=evt.price,
            size=take_size,
            order_id=None,
            trigger_reason=trigger,
        )]

    # ==================================================================
    # Bug 10 — pair-cost arb gate
    # ==================================================================

    def _pair_cost_arb_ok(self, slug: str) -> bool:
        """Universal arb gate for V3f composite TAKE fires.

        Computes ``pair_cost = ba_up + ba_dn + taker_fee(ba_up) +
        taker_fee(ba_dn)`` from the per-side L25 cache. Returns True iff
        pair_cost < _MAX_PAIR_COST_ACC_H. If either side is missing from
        the cache (cold start) → False (safe-skip rather than half-blind
        fire). taker_fee uses the same Polymarket formula as ACC-M's PAT
        gate (taker_fee = 0.07 * p * (1-p), symmetric around p=0.5).
        """
        up_evt = self._l25_cache.get((slug, "up"))
        dn_evt = self._l25_cache.get((slug, "dn"))
        if up_evt is None or dn_evt is None:
            return False
        ba_up = self._best_ask(up_evt)
        ba_dn = self._best_ask(dn_evt)
        if ba_up is None or ba_dn is None:
            return False
        if not (Decimal("0") < ba_up < Decimal("1")):
            return False
        if not (Decimal("0") < ba_dn < Decimal("1")):
            return False
        pair_cost = ba_up + ba_dn + taker_fee(ba_up) + taker_fee(ba_dn)
        return pair_cost < _MAX_PAIR_COST_ACC_H

    def on_slug_resolved(self, evt: SlugResolved) -> list[Decision]:
        """Inherit ACC-M resolve + clean up ACC-H rolling histories."""
        decisions = super().on_slug_resolved(evt)
        for side in ("up", "dn"):
            key = (evt.slug, side)
            self._ask_history.pop(key, None)
            self._trade_history.pop(key, None)
            self._buy_vol_history.pop(key, None)
            self._last_taker_fire_us.pop(key, None)
        self._taker_buy_count_per_slug.pop(evt.slug, None)
        return decisions

    # ==================================================================
    # Rate limits
    # ==================================================================

    def _rate_limits_ok(self, slug: str, side: Side, ts_us: int, state) -> bool:
        """Three-gate rate-limit check (D-10 verbatim + ABS_MAX_INV)."""
        # Gate 1: MIN_S_BETWEEN_TAKER_BUYS per (slug, side).
        last = self._last_taker_fire_us.get((slug, side), 0)
        min_s = self.config.tv_poly_maker_acc_h_min_s_between_taker_buys
        min_gap_us = int(min_s * Decimal("1000000"))
        if last > 0 and (ts_us - last) < min_gap_us:
            return False
        # Gate 2: MAX_TAKER_BUYS_PER_SLUG (across both sides).
        count = self._taker_buy_count_per_slug.get(slug, 0)
        if count >= self.config.tv_poly_maker_acc_h_max_taker_buys_per_slug:
            return False
        # Gate 3: ABSOLUTE_MAX_INVENTORY per side (ACC-H looser cap = 100).
        current_inv = state.inv_up if side == "up" else state.inv_dn
        if current_inv >= _ABSOLUTE_MAX_INVENTORY_ACC_H:
            return False
        return True

    def _record_taker_fire(self, slug: str, side: Side, ts_us: int) -> None:
        """Bump per-(slug, side) last-fire ts + per-slug count."""
        self._last_taker_fire_us[(slug, side)] = ts_us
        self._taker_buy_count_per_slug[slug] = (
            self._taker_buy_count_per_slug.get(slug, 0) + 1
        )

    # ==================================================================
    # V3f rules (4 OR-combined; first hit wins)
    # ==================================================================

    def _rule_a_discount(self, evt: TradePrint) -> bool:
        """Rule A — current_ask < 0.50 AND (60s median - current_ask) >= 0.03.

        The 60s window is enforced by ``deque(maxlen=_ASKS_HISTORY_MAXLEN)``
        sizing alone (Pitfall 5): at 2 Hz × 60s = 120 entries, the deque
        naturally drops anything older. We sort the deque values and read
        the median entry. Matches ``shadow_engine/strategies/acc_h.py:189``
        behavior verbatim.
        """
        key = (evt.slug, evt.side)
        hist = self._ask_history.get(key)
        if hist is None or len(hist) < _RULE_A_MIN_HISTORY_ENTRIES:
            return False
        latest_ask = hist[-1][1]
        if latest_ask >= _RULE_A_MAX_TAKER_PRICE_DISCOUNT:
            return False
        asks = [a for _, a in hist if a > 0]
        if len(asks) < _RULE_A_MIN_HISTORY_ENTRIES:
            return False
        sorted_asks = sorted(asks)
        median_ask = sorted_asks[len(sorted_asks) // 2]
        if median_ask - latest_ask >= _RULE_A_MIN_ASK_DROP_60S:
            return True
        return False

    def _rule_b_sharp_drop(self, evt: TradePrint) -> bool:
        """Rule B — max(trade_prices_5s) - current_ask >= 0.02.

        5s window enforced by ``deque(maxlen=_TRADES_HISTORY_MAXLEN)`` at
        10 Hz × 5s = 50 entries — naturally drops older entries. Matches
        ``shadow_engine/strategies/acc_h.py:201`` behavior verbatim.
        """
        key = (evt.slug, evt.side)
        ask_hist = self._ask_history.get(key)
        if ask_hist is None or len(ask_hist) < 1:
            return False
        latest_ask = ask_hist[-1][1]
        trade_hist = self._trade_history.get(key)
        if trade_hist is None or len(trade_hist) < _RULE_B_MIN_HISTORY_ENTRIES:
            return False
        prices = [p for _, p in trade_hist if p > 0]
        if len(prices) < _RULE_B_MIN_HISTORY_ENTRIES:
            return False
        max_recent = max(prices)
        if max_recent - latest_ask >= _RULE_B_MIN_TRADE_DROP_5S:
            return True
        return False

    def _rule_c_early_slot(self, evt: TradePrint, state) -> "Side | None":
        """Rule C — early-slot dislocation (Bug 10 re-implementation).

        Original spec line ("best_ask sum > 1.005 → TAKE both sides — early
        arb opportunity") had inverted economics: sum > $1 = OVERPRICED,
        guaranteed loss after fees. Correct semantics: an early-slot price
        DISLOCATION (|ba_up + ba_dn - 1.00| > threshold) signals the book
        hasn't settled into equilibrium yet. Fire TAKE on the UNDERPRICED
        side (lower ask = greater upside at $1 par redemption).

        Returns:
          - The Side to fire ("up" or "dn") if dislocation present in the
            early-slot window AND no prior fill on this slug.
          - None if no fire.

        The universal pair-cost gate (_pair_cost_arb_ok) already filters
        out sum >= $1 + fees cases, so Rule C only matters when there IS
        an arb edge — Rule C selects WHICH side to take given the edge.
        """
        offset_us = evt.ts_us - state.slug_active_ts_us
        if offset_us > _RULE_C_EARLY_SLOT_END_US or offset_us < 0:
            return None
        if state.n_fills > 0:
            return None

        up_evt = self._l25_cache.get((evt.slug, "up"))
        dn_evt = self._l25_cache.get((evt.slug, "dn"))
        if up_evt is None or dn_evt is None:
            return None
        ba_up = self._best_ask(up_evt)
        ba_dn = self._best_ask(dn_evt)
        if ba_up is None or ba_dn is None:
            return None

        sum_asks = ba_up + ba_dn
        dislocation = abs(sum_asks - Decimal("1.00"))
        if dislocation < _RULE_C_MIN_DISLOCATION:
            return None

        # Fire on the side with the LOWER ask (more upside per dollar at
        # $1 redemption). Tie-breaks to evt.side.
        if ba_up < ba_dn:
            return "up"
        if ba_dn < ba_up:
            return "dn"
        return evt.side

    def _rule_d_buy_pressure_dip(self, evt: TradePrint) -> bool:
        """Rule D — 60s buy_vol > 50 shares AND 5s price dip >= 0.001.

        Window bounding via ``deque(maxlen=N)``: buy_vol maxlen=300
        (5 Hz × 60s), trades maxlen=50 (10 Hz × 5s). Matches
        ``shadow_engine/strategies/acc_h.py:220`` behavior verbatim.
        """
        key = (evt.slug, evt.side)
        ask_hist = self._ask_history.get(key)
        if ask_hist is None or len(ask_hist) < 1:
            return False
        latest_ask = ask_hist[-1][1]
        bv_hist = self._buy_vol_history.get(key)
        if bv_hist is None:
            return False
        total_buy_vol = sum((sz for _, sz in bv_hist), Decimal(0))
        if total_buy_vol <= _RULE_D_MIN_BUY_VOL_60S:
            return False
        trade_hist = self._trade_history.get(key)
        if trade_hist is None or len(trade_hist) < _RULE_D_MIN_TRADES:
            return False
        prices = [p for _, p in trade_hist if p > 0]
        if len(prices) < _RULE_D_MIN_TRADES:
            return False
        max_recent = max(prices)
        if max_recent - latest_ask >= _RULE_D_MIN_PRICE_DIP_5S:
            return True
        return False


class AccHV2Strategy(AccHStrategy):
    """Phase C ACC-H-V2 — adds convergence-cancel to V1 ACC-H. No other behavior
    diff. Cells extended to ``btc_15m,eth_15m`` via
    ``tv_poly_maker_acc_h_v2_cells``.

    Spec: ``global/strategy_lab/reports/TV_AGENT_SPEC_NEW_SLEEVES_V2_2026_05_27.md`` §2.2 + §2.5.
    """

    code: str = "ACC-H-V2"
    variant: str = "v2"


__all__ = ["AccHStrategy", "AccHV2Strategy"]
