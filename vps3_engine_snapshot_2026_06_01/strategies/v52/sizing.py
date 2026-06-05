"""V52 position-sizing helper (Phase 8.1 Task 8).

Per V52 spec §2.5:
    size = min(
        risk_frac * cash / (sl_atr_mult * atr),
        cash * leverage_cap / price
    )

HL exchange-side max leverage = 5x (operator config; RESEARCH Open Q2),
code-side per-trade cap = 3.0x. The two don't conflict — code-side cap is
strictly tighter.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def size_from_atr(
    cash: float,
    atr: float,
    sl_atr_mult: float,
    price: float,
    risk_frac: float = 0.01,
    leverage_cap: float = 3.0,
) -> float:
    """Returns position size in base units (cash * cap is dollar notional;
    divide by price to convert).

    atr <= 0 → returns 0 + CRITICAL log (no trade).
    Defensive: any non-positive cash/price/sl_atr_mult → 0.
    """
    if cash <= 0 or price <= 0:
        return 0.0
    if not (sl_atr_mult > 0):
        raise AssertionError("sl_atr_mult must be > 0")
    if not (risk_frac > 0):
        raise AssertionError("risk_frac must be > 0")
    if not (leverage_cap > 0):
        raise AssertionError("leverage_cap must be > 0")
    if atr <= 0:
        logger.critical(
            "v52.sizing.zero_atr",
            extra={"event": "v52.sizing.zero_atr", "price": price, "cash": cash},
        )
        return 0.0
    risk_dollars = cash * risk_frac
    stop_dist = sl_atr_mult * atr
    size_risk = risk_dollars / stop_dist
    size_cap = (cash * leverage_cap) / price
    return float(min(size_risk, size_cap))


__all__ = ["size_from_atr"]
