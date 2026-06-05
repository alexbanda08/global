"""Rail 5 — portfolio DD > 30% → REQUEST_KILL (RAIL-06, Phase 10 Task 3).

The critical final layer of the portfolio DD ladder. Fires when the
portfolio has drawn down more than 30% from ATH. Action:
``REQUEST_KILL`` + severity ``CRITICAL``. The controller writes a
``trading.events(kind='kill_switch_requested')`` row; Phase 12's kill
consumer reads it.

**CLAUDE.md §7 invariant**: this rail does NOT call any kill method.
There is no kill method on controllers or the portfolio. Rails only
REQUEST; Phase 12 implements the three-layer kill paths.
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from backend.app.engine.rails.framework import (
    RailAction,
    RailId,
    RailResult,
    RailSeverity,
)
from backend.app.engine.rails.rail_03_portfolio_dd_15 import _dd_pct_from_ath


def rail_05_portfolio_dd_30_kill(
    *,
    portfolio_equity_snapshots_24h: Iterable[Any],
    threshold_pct: Decimal = Decimal("30.0"),
) -> RailResult:
    """Request kill when portfolio DD > 30%."""
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
            rail_id=RailId.PORTFOLIO_DD_30_KILL,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"portfolio_dd={dd_pct:.4f}% <= {threshold_pct}%",
        )
    return RailResult(
        rail_id=RailId.PORTFOLIO_DD_30_KILL,
        fired=True,
        severity=RailSeverity.CRITICAL,
        action=RailAction.REQUEST_KILL,
        payload=payload,
        message=(
            f"portfolio_dd={dd_pct:.4f}% > {threshold_pct}% → request kill"
        ),
    )


__all__ = ["rail_05_portfolio_dd_30_kill"]
