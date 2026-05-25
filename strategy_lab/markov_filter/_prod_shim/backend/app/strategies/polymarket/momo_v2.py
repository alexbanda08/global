"""MomoV2Strategy — Binance-latency momentum signal at t+60s of each market.

Spec: ``strategy_lab/reports/TV_AGENT_MOMO_V2_SLEEVES_IMPLEMENTATION.md``
(2026-05-07). Near-clone of :mod:`backend.app.strategies.polymarket.momo`
(v1) with two key deltas:

================  ============================================  ===========================================
Aspect            momo (v1, current production)                 momo_v2 (this module)
================  ============================================  ===========================================
``ret_2m`` anchor ``log(close@(ws+120) / close@(ws))``          ``log(close@(ws+60) / close@(ws-60))``
Fire offset       ``ws + 120s`` (``t_plus_120`` phase)          ``ws + 60s`` (``t_plus_60`` phase)
================  ============================================  ===========================================

Backtest evidence at strict asof + L25 WS books (spec §0):

================  ====  =========  =====  ========
offset            n     pnl_mean   hit%   avg_vwap
================  ====  =========  =====  ========
ws+120 (v1)       966   +$9.98     87.2%  0.676
**ws+60 (v2)**    935   **+$13.67**  87.5%  0.612
================  ====  =========  =====  ========

The +$3.69/trade improvement comes from firing 60 seconds earlier — the
Polymarket book has had less time to absorb the Binance move (vwap 0.612
vs 0.676). Hit rate is essentially identical.

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


class MomoV2Strategy(PolymarketBinaryStrategy):
    """Top-q90 |ret_2m| gate; reads aux populated at t+60s.

    aux schema (populated by controller's ``_build_signal_aux`` when the
    ``BarContext.phase == 't_plus_60'`` branch fires)::

        aux = {
            "bar_ctx_phase":          "t_plus_60",  # gate
            "ret_2m":                 0.0034,       # log(close@ws+60 / close@ws-60)
            "abs_ret_2m_threshold":   0.0028,       # rolling 14d q90 of |ret_2m|
                                                    # (computed against v2 anchor —
                                                    # NOT shared with v1's cache)
        }

    Returns ``"NONE"`` on any other phase as a defensive guard. Master
    scheduler also partitions controllers by phase, but this is the
    second line of defense.
    """

    name = "momo_v2"

    def __init__(self) -> None:
        # Mode is implicit (always "sniper-style" — threshold-gated).
        # Constructor mirrors MomoStrategy v1.
        self.mode = "sniper"

    def signal(
        self,
        bars: list[Bar],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        # Phase gate — only fire on the t+60s dispatch.
        if aux.get("bar_ctx_phase") != "t_plus_60":
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
        # 2026-05-20 F7 RSI agreement gate — same semantics as v1 momo.
        rsi_14_raw = aux.get("rsi_14")
        rsi_14 = float(rsi_14_raw) if rsi_14_raw is not None else float("nan")
        f7_mode = aux.get("f7_filter_mode", "off")
        if not f7_passes(direction, rsi_14, f7_mode):
            return "NONE"
        return direction


__all__ = ["MomoV2Strategy"]
