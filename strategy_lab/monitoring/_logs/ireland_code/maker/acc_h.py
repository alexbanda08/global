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

        Order of operations per shadow_engine/strategies/acc_h.py:
          1. Append (ts, price) to trade_history[(slug, side)].
          2. If aggressor == "buy", append (ts, size) to buy_vol_history.
          3. Run rate-limit gates (MIN_S + MAX_PER_SLUG + ABS_MAX_INV).
          4. Evaluate 4 rules in order A → B → C → D; first hit fires.
          5. On fire: build Decision(action="TAKE", side=evt.side, ...);
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
        if not self._rate_limits_ok(evt.slug, evt.side, evt.ts_us, state):
            return []

        # 4. Evaluate rules in priority order.
        trigger: str | None = None
        if self._rule_a_discount(evt):
            trigger = "rule_a_discount"
        elif self._rule_b_sharp_drop(evt):
            trigger = "rule_b_sharp_drop"
        elif self._rule_c_early_slot(evt, state):
            trigger = "rule_c_early_slot"
        elif self._rule_d_buy_pressure_dip(evt):
            trigger = "rule_d_buy_pressure_dip"

        if trigger is None:
            return []

        # 5. Build TAKE Decision + record fire.
        self._record_taker_fire(evt.slug, evt.side, evt.ts_us)
        take_size = self.config.tv_poly_maker_min_post_shares
        return [Decision(
            ts_us=evt.ts_us,
            strategy=self.code,
            slug=evt.slug,
            asset=state.asset,
            tf=state.tf,
            action="TAKE",
            side=evt.side,
            price=evt.price,
            size=take_size,
            order_id=None,
            trigger_reason=trigger,
        )]

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

    def _rule_c_early_slot(self, evt: TradePrint, state) -> bool:
        """Rule C — within first 60s of slug AND no prior fill on side.

        Per shadow_engine spec: "Only fire if no maker bid has filled yet
        on this side." We approximate via ``state.n_fills`` (per-slug fills
        accumulator from inherited ACC-M `on_order_fill`) — a global
        per-slug counter rather than per-side; if any fill has happened on
        EITHER side, treat the early-slot opportunity as expired (less
        permissive than per-side check but matches CONTEXT's "no prior
        fill" framing). Acceptable for shadow mode.
        """
        offset_us = evt.ts_us - state.slug_active_ts_us
        if offset_us > _RULE_C_EARLY_SLOT_END_US:
            return False
        if offset_us < 0:
            return False
        if state.n_fills > 0:
            return False
        return True

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


__all__ = ["AccHStrategy"]
