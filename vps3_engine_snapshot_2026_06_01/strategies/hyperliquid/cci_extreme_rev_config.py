"""CCIExtremeRevConfig — Pydantic config for the ETH CCI reversal strategy (Phase 8, Task 4).

Per 08-CONTEXT D-04: CCI(20) extreme reversal on 4h ETH perps. Tighter TP
(2×ATR vs 3×ATR for BBBreak) and shorter max_hold (12 bars = 48h on 4h) —
reversal strategies typically aim for a mean-revert bounce, not a trend
continuation.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CCIExtremeRevConfig(BaseModel):
    """Frozen config for ``CCIExtremeRevStrategy``.

    Defaults match the D-04 recipe:

    * CCI(20) on typical price = (high + low + close) / 3.
    * ``cci_extreme_threshold=150`` — |CCI| > 150 is the entry gate.
      (Canonical reversal thresholds are 100 or 200; 150 is the 08-CONTEXT pick.)
    * ATR(14), SL 2.5×ATR (wider — reversal trades have more noise), TP 2×ATR
      (tighter — reversal bounces are smaller), trail 1.5×ATR.
    * max_hold 12 bars (48h on 4h timeframe) — shorter than BBBreak's 24.
    * cooldown 4 bars.
    * $10 notional, $10 equity, 1% risk-per-trade.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    timeframe: str = "4h"
    cci_period: int = 20
    cci_extreme_threshold: Decimal = Decimal("150")
    atr_period: int = 14
    atr_sl_mult: Decimal = Decimal("2.5")
    atr_tp_mult: Decimal = Decimal("2.0")
    atr_trail_mult: Decimal = Decimal("1.5")
    max_hold_bars: int = 12
    cooldown_bars: int = 4
    notional_cap_usd: Decimal = Decimal("10")
    equity_usd: Decimal = Decimal("10")
    risk_per_trade_pct: Decimal = Decimal("1.0")


__all__ = ["CCIExtremeRevConfig"]
