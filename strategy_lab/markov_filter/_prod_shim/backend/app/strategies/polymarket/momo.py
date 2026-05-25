"""MomoStrategy — Binance-latency momentum signal at t+120s of each market.

Phase 18.5 (per ``strategy_lab/reports/TV_AGENT_MOMO_SLEEVES_IMPLEMENTATION.md``,
2026-05-05). Different from the existing sig_ret5m signal:

- ``Updown5m/15m`` fires AT bar close on ``ret_5m = log(BTC@ws / BTC@ws-300)``
  — the BTC return over the 5 minutes BEFORE the new market opened.
- ``MomoStrategy`` fires AT t+120s of the new market on
  ``ret_2m = log(BTC@ws+120 / BTC@ws)`` — the BTC return over the FIRST
  2 minutes INSIDE the market.

Different signal window, different aux schema. The controller threads a
``BarContext`` with ``phase='t_plus_120'`` into ``_build_signal_aux``
which populates the new aux fields. A bar-close-phase BarContext yields
``aux['bar_ctx_phase'] = 'bar_close'`` and this strategy returns NONE
(harmless guard against accidental dispatch on the wrong phase).

INVARIANTS (CLAUDE.md #4):
- signal() is a PURE function: no IO, no time.time(), no mutation.
- Bars passed must be CLOSED.
- No imports from engine.*, venues.*, DB, or network.
- NEVER crash on missing / malformed aux — always return ``"NONE"``.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy,
    SignalConfig,
    SignalResult,
)
from backend.app.strategies.polymarket.f7_gate import f7_passes

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar


class MomoStrategy(PolymarketBinaryStrategy):
    """Top-q90 |ret_2m| gate; reads aux populated at t+120s.

    aux schema (populated by controller's ``_build_signal_aux`` when the
    ``BarContext.phase == 't_plus_120'`` branch fires)::

        aux = {
            "bar_ctx_phase":          "t_plus_120",  # gate
            "ret_2m":                 0.0034,        # log(close@ws+120 / close@ws)
            "abs_ret_2m_threshold":   0.0028,        # rolling 14d q90 of |ret_2m|
        }

    Returns ``"NONE"`` on bar-close phase (controller dispatches both
    phases to all controllers in master scheduler v0.1; this is the
    cheap defensive guard — master scheduler also has a phase-aware
    skip but the strategy is the second line of defense).
    """

    name = "momo"

    def __init__(self) -> None:
        # Mode is implicit (always "sniper-style" — threshold-gated).
        # Constructor takes no args to match the controller's instantiation
        # pattern, which builds one strategy per (symbol, tf) slot.
        self.mode = "sniper"

    def signal(
        self,
        bars: list[Bar],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        # Phase gate — only fire on the t+120s dispatch, never on bar-close.
        # Master scheduler also filters momo controllers off the bar-close
        # phase, but this is the strategy-side defensive guard.
        if aux.get("bar_ctx_phase") != "t_plus_120":
            return "NONE"
        ret_2m = aux.get("ret_2m")
        if ret_2m is None or not math.isfinite(ret_2m):
            return "NONE"
        thr = aux.get("abs_ret_2m_threshold")
        if thr is None or not math.isfinite(thr) or abs(ret_2m) < thr:
            return "NONE"
        direction: SignalResult
        if ret_2m > 0:
            direction = "UP"
        elif ret_2m < 0:
            direction = "DOWN"
        else:
            return "NONE"
        # 2026-05-20 F7 RSI agreement gate (TV_AGENT_F7_RSI_FILTER_SPEC).
        # Skip the fire when binance 1MIN RSI(14) disagrees with the
        # momo direction. Mode is per-controller (off | basic | extreme),
        # populated by `_build_signal_aux` from `self._f7_filter_mode`.
        # When mode == "off" (baselines or non-momo strategies) this is
        # an identity no-op — `f7_passes` returns True unconditionally.
        rsi_14_raw = aux.get("rsi_14")
        rsi_14 = float(rsi_14_raw) if rsi_14_raw is not None else float("nan")
        f7_mode = aux.get("f7_filter_mode", "off")
        if not f7_passes(direction, rsi_14, f7_mode):
            return "NONE"
        return direction


__all__ = ["MomoStrategy"]
