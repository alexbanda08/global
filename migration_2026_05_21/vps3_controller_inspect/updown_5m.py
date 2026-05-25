"""Updown5mStrategy — sig_ret5m Binance-latency-arbitrage signal (Phase 18.1).

Replaces the Phase 15 placeholder body. The signal logic is
**identical** between 5m and 15m — the timeframe-specific sniper quantile
(q90 on 5m vs q80 on 15m) is enforced UPSTREAM by the controller via
``aux["abs_ret_5m_threshold"]``. The strategy itself is timeframe-agnostic.

Logic (per RESEARCH §3.2, validated 2026-04-27 forward-walk holdout):

    if aux is None or aux["ret_5m"] is None / non-finite → NONE
    if mode == "sniper" and (threshold None or |ret_5m| < threshold) → NONE
    if ret_5m > 0 → UP
    if ret_5m < 0 → DOWN
    else → NONE

INVARIANTS (CLAUDE.md #4):
- signal() is a PURE function: no IO, no time.time(), no mutation of bars/aux.
- Only CLOSED bars must be passed by the caller.
- No imports from engine.*, venues.polymarket.client, DB, or network.
- NEVER crash on missing / malformed aux — always return "NONE".
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy,
    SignalConfig,
    SignalResult,
)

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.data.models import Bar


class Updown5mStrategy(PolymarketBinaryStrategy):
    """sig_ret5m strategy for 5m markets: bet sign of Binance 5m return.

    Optional sniper filter: only bet when |ret_5m| >= rolling threshold.
    The threshold is computed by the controller per timeframe:
      - 5m markets:  90th percentile of |ret_5m| (q10, top 10%)
      - 15m markets: 80th percentile of |ret_5m| (q20, top 20%)

    Args:
        mode: ``"volume"`` (every signal fires) or ``"sniper"`` (threshold-gated).
              Default ``"volume"``.
    """

    def __init__(self, mode: Literal["volume", "sniper"] = "volume") -> None:
        if mode not in ("volume", "sniper"):
            raise ValueError(f"mode must be 'volume'|'sniper', got {mode!r}")
        self.mode: Literal["volume", "sniper"] = mode

    def signal(
        self,
        bars: list[Bar],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        """Return UP/DOWN/NONE based on sign of aux['ret_5m'].

        Pure function: reads aux, returns literal string. No side effects,
        no mutation. Returns "NONE" on any missing / non-finite input.
        """
        if aux is None:
            return "NONE"
        ret_5m = aux.get("ret_5m")
        if ret_5m is None or not math.isfinite(ret_5m):
            return "NONE"

        if self.mode == "sniper":
            # Phase 18.2 D-11 — direction-aware threshold for v3_1/v4. When
            # both abs_ret_5m_threshold_up and abs_ret_5m_threshold_down are
            # present, pick by sign of ret_5m. Else fall through to the
            # legacy single-threshold path (v1/v2/v3/v3_2 — UNCHANGED).
            thr_up = aux.get("abs_ret_5m_threshold_up")
            thr_down = aux.get("abs_ret_5m_threshold_down")
            if thr_up is not None and thr_down is not None:
                directional_threshold = thr_up if ret_5m > 0 else thr_down
                if abs(ret_5m) < directional_threshold:
                    return "NONE"
            else:
                threshold = aux.get("abs_ret_5m_threshold")
                if threshold is None or abs(ret_5m) < threshold:
                    return "NONE"

        # V3 multi-horizon AND filter (set by controller for SOL 5m only):
        # require ret_5m, ret_15m, ret_1h to all share sign before firing.
        # Per TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md §1.3.
        if aux.get("require_multi_horizon"):
            ret_15m = aux.get("ret_15m")
            ret_1h = aux.get("ret_1h")
            if (
                ret_15m is None
                or ret_1h is None
                or not math.isfinite(ret_15m)
                or not math.isfinite(ret_1h)
            ):
                return "NONE"
            same_sign = (ret_5m > 0 and ret_15m > 0 and ret_1h > 0) or (
                ret_5m < 0 and ret_15m < 0 and ret_1h < 0
            )
            if not same_sign:
                return "NONE"

        if ret_5m > 0:
            return "UP"
        if ret_5m < 0:
            return "DOWN"
        return "NONE"


__all__ = ["Updown5mStrategy"]
