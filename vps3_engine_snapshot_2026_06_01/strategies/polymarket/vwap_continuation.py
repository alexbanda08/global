"""VWAP Continuation strategy (Phase 35).

Per ``strategy_lab/reports/TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md``.

Late-fire momentum continuation on 5m crypto up-down markets. Bets WITH the
binance deviation from its 15m anchored VWAP at a fixed offset into each
slot. Optional filters: M1V Markov regime, F7 RSI, cross-asset confluence —
each sleeve configures which gates apply via the ctor flags.

INVARIANTS (CLAUDE.md inv #4):
- signal() is PURE. No IO, no time.time(), no mutation.
- All inputs arrive via the ``aux`` dict populated by
  ``build_bar_context_t_plus_n`` (poly_updown_loop.py).
- Returns ``"NONE"`` on any missing/invalid input — never crashes.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy,
    SignalConfig,
    SignalResult,
)

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.data.models import Bar


__all__ = ["VwapContinuationStrategy"]


class VwapContinuationStrategy(PolymarketBinaryStrategy):
    """Bets WITH the binance 15m anchored VWAP deviation.

    aux schema (populated by build_bar_context_t_plus_n)::

        aux = {
            "bar_ctx_phase":            "t_plus_240",          # must match self.offset_s
            "vwap_dev_bps":             float,                  # 10000·ln(close/vwap_15m)
            "vwap_15m_anchored":        float,                  # for audit only
            "rsi_14_for_signal":        float,                  # F7 input
            "markov_regime_w20_1m_va":  int,                    # M1V input (-1/0/1/2)
            "cross_asset_devs":         [(asset, dev_bps), ...],
        }
    """

    name = "vwap_continuation"

    def __init__(
        self,
        *,
        offset_s: int,
        thr_min_bps: float,
        thr_max_bps: float,
        require_m1v: bool = False,
        require_f7: bool = False,
        require_cross_full: bool = False,
        require_cross_partial: bool = False,
    ) -> None:
        self.offset_s = int(offset_s)
        self.thr_min = float(thr_min_bps)
        self.thr_max = float(thr_max_bps)
        self.require_m1v = bool(require_m1v)
        self.require_f7 = bool(require_f7)
        self.require_cross_full = bool(require_cross_full)
        self.require_cross_partial = bool(require_cross_partial)
        self.mode = "vwap_continuation"

    def signal(
        self,
        bars: list["Bar"],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"

        # 1. Phase gate — only fire on the matching late-fire phase.
        expected_phase = f"t_plus_{self.offset_s}"
        if aux.get("bar_ctx_phase") != expected_phase:
            return "NONE"

        # 2. dev_bps in [thr_min, thr_max] (exclusive on min, inclusive on max).
        dev_bps = aux.get("vwap_dev_bps")
        if dev_bps is None:
            return "NONE"
        try:
            dev_bps = float(dev_bps)
        except (TypeError, ValueError):
            return "NONE"
        if not math.isfinite(dev_bps):
            return "NONE"
        abs_dev = abs(dev_bps)
        if not (self.thr_min < abs_dev <= self.thr_max):
            return "NONE"

        # 3. Direction from sign.
        direction: SignalResult = "UP" if dev_bps > 0 else "DOWN"

        # 4. M1V gate — Bull required for UP, Bear required for DOWN.
        if self.require_m1v:
            regime = aux.get("markov_regime_w20_1m_va")
            if regime is None or not isinstance(regime, int):
                return "NONE"
            if direction == "UP" and regime != 2:    # 2 = Bull
                return "NONE"
            if direction == "DOWN" and regime != 0:  # 0 = Bear
                return "NONE"

        # 5. F7 RSI gate — RSI > 50 for UP, < 50 for DOWN.
        if self.require_f7:
            rsi = aux.get("rsi_14_for_signal")
            if rsi is None:
                return "NONE"
            try:
                rsi = float(rsi)
            except (TypeError, ValueError):
                return "NONE"
            if not math.isfinite(rsi):
                return "NONE"
            if direction == "UP" and rsi <= 50:
                return "NONE"
            if direction == "DOWN" and rsi >= 50:
                return "NONE"

        # 6. Cross-asset confluence gate.
        if self.require_cross_full or self.require_cross_partial:
            cross = aux.get("cross_asset_devs") or []
            agree = 0
            valid = 0
            for _, d in cross:
                if d is None:
                    continue
                try:
                    df = float(d)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(df):
                    continue
                valid += 1
                if direction == "UP" and df > 0:
                    agree += 1
                elif direction == "DOWN" and df < 0:
                    agree += 1
            if valid == 0:
                return "NONE"
            need = valid if self.require_cross_full else 1
            if agree < need:
                return "NONE"

        return direction
