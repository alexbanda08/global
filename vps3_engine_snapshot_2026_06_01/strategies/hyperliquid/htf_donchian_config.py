"""HTFDonchianConfig — Pydantic config for the DOGE HTF Donchian strategy (Phase 8, Task 3).

Per 08-CONTEXT D-03: HTF Donchian is a 20-bar Donchian channel breakout with
a 5-bar higher-timeframe trend filter (coarse trend check on ``close``).

Defaults are tuned for 4h DOGE perps at $10 notional (SIZING-WK1 wk1). The
strategy class reads the config bound at ``__init__`` — matching the
``Strategy`` Protocol expected by ``HyperliquidSleeveController``.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class HTFDonchianConfig(BaseModel):
    """Frozen config for ``HTFDonchianStrategy``.

    Defaults match the D-03 recipe:

    * Donchian(20) high/low on ``bars[:-1]`` (look-ahead guard).
    * HTF trend filter: ``bars[-1].close`` vs ``bars[-1-htf_period].close``.
    * ATR(14), SL 2×ATR, TP 3×ATR, trail 1.5×ATR.
    * max_hold 24 bars (96h on 4h timeframe), cooldown 4 bars.
    * $10 notional, $10 equity, 1% risk-per-trade.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    timeframe: str = "4h"
    donchian_period: int = 20
    htf_period: int = 5
    atr_period: int = 14
    atr_sl_mult: Decimal = Decimal("2.0")
    atr_tp_mult: Decimal = Decimal("3.0")
    atr_trail_mult: Decimal = Decimal("1.5")
    max_hold_bars: int = 24
    cooldown_bars: int = 4
    notional_cap_usd: Decimal = Decimal("10")
    equity_usd: Decimal = Decimal("10")
    risk_per_trade_pct: Decimal = Decimal("1.0")


__all__ = ["HTFDonchianConfig"]
