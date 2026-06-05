"""Rail 3 — portfolio DD from ATH > 15% → halve risk (RAIL-04, Phase 10 Task 3).

Fires on the portfolio-aggregate equity curve when the most recent
equity has drawn down more than ``threshold_pct`` from ATH. Action:
``HALVE_RISK`` (controller halves ``risk_per_trade_pct`` on all sleeves).

Strict-``>`` boundary: exactly 15.00% does NOT fire; 15.01% fires.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any

from backend.app.engine.rails.framework import (
    RailAction,
    RailId,
    RailResult,
    RailSeverity,
)


def _dd_pct_from_ath(snapshots: Iterable[Any]) -> tuple[Decimal, Decimal, Decimal]:
    """Return (ath, current, dd_pct_from_ath)."""
    equities = [
        Decimal(
            str(
                getattr(s, "equity_usd", s["equity_usd"] if isinstance(s, dict) else 0)
            )
        )
        for s in snapshots
    ]
    if not equities:
        return Decimal("0"), Decimal("0"), Decimal("0")
    ath = max(equities)
    current = equities[-1]
    if ath == 0:
        return ath, current, Decimal("0")
    dd_pct = (ath - current) / ath * Decimal("100")
    return ath, current, dd_pct


def rail_03_portfolio_dd_15(
    *,
    portfolio_equity_snapshots_24h: Iterable[Any],
    threshold_pct: Decimal = Decimal("15.0"),
    now: datetime | None = None,  # noqa: ARG001 - reserved for future "since-ATH" signal
) -> RailResult:
    """Halve risk when portfolio DD from ATH > 15%."""
    ath, current, dd_pct = _dd_pct_from_ath(portfolio_equity_snapshots_24h)

    fired = dd_pct > threshold_pct
    payload: dict[str, Any] = {
        "ath_usd": str(ath),
        "current_equity_usd": str(current),
        "dd_pct": str(dd_pct),
        "threshold_pct": str(threshold_pct),
    }
    if not fired:
        return RailResult(
            rail_id=RailId.PORTFOLIO_DD_15,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"portfolio_dd={dd_pct:.4f}% <= {threshold_pct}%",
        )
    return RailResult(
        rail_id=RailId.PORTFOLIO_DD_15,
        fired=True,
        severity=RailSeverity.WARN,
        action=RailAction.HALVE_RISK,
        payload=payload,
        message=f"portfolio_dd={dd_pct:.4f}% > {threshold_pct}% → halve risk",
    )


__all__ = ["rail_03_portfolio_dd_15"]
