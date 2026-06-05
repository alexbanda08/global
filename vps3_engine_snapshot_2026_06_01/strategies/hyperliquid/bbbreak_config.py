"""BBBreakConfig — Pydantic config for the SOL/AVAX/TON BB-break strategy.

Per 07-CONTEXT D-03 defaults (clean-room from IMPLEMENTATION_GUIDE §4). Every
parameter is frozen so one config can be shared across many bar evaluations
without fear of mutation.

Defaults are tuned for 4h crypto perps at $10 notional (Phase 7 SIZING-WK1).
Downstream phases scale these by raising ``notional_cap_usd`` and
``equity_usd`` while keeping the other ratios intact.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class BBBreakConfig(BaseModel):
    """Frozen config for ``BBBreakStrategy``.

    Every numeric knob is a ``Decimal`` or typed scalar — no floats leak into
    sizing. Defaults match the D-03 recipe:

    * BB(20, 2.0) on ``close``.
    * ATR(14), SL at 2×ATR, TP at 3×ATR, trail at 1.5×ATR.
    * max_hold 24 bars (96h on 4h timeframe), cooldown 4 bars.
    * $10 notional, $10 equity, 1% risk-per-trade → $0.10 risk-budget.

    The 1% risk + $10 equity tend to produce qty > $10 / entry_px before the
    notional cap clamps. ``apply_notional_cap`` in ``strategies.base`` + the
    executor's ``NotionalCapExceeded`` assertion are the two safety nets.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    timeframe: str = "4h"
    bb_period: int = 20
    bb_std: float = 2.0
    breakout_confirm_bars: int = 1
    atr_period: int = 14
    atr_sl_mult: Decimal = Decimal("2.0")
    atr_tp_mult: Decimal = Decimal("3.0")
    atr_trail_mult: Decimal = Decimal("1.5")
    max_hold_bars: int = 24
    cooldown_bars: int = 4
    notional_cap_usd: Decimal = Decimal("10")
    equity_usd: Decimal = Decimal("10")
    risk_per_trade_pct: Decimal = Decimal("1.0")


__all__ = ["BBBreakConfig"]
