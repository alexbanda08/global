"""Rail 4 — portfolio DD from ATH > 25% → halve leverage (RAIL-05, Phase 10 Task 3).

Fires when portfolio DD from ATH > 25%. Action: ``HALVE_LEVERAGE``.
Payload includes ``halved_leverage_until_utc = now + 4 weeks`` so the
controller has an expiry timestamp for auto-restore after 4 weeks
without firing (10-CONTEXT D-06).

Strict-``>`` boundary.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from backend.app.engine.rails.framework import (
    RailAction,
    RailId,
    RailResult,
    RailSeverity,
)
from backend.app.engine.rails.rail_03_portfolio_dd_15 import _dd_pct_from_ath

HALVE_LEVERAGE_DURATION = timedelta(weeks=4)


def rail_04_portfolio_dd_25(
    *,
    portfolio_equity_snapshots_24h: Iterable[Any],
    threshold_pct: Decimal = Decimal("25.0"),
    now: datetime | None = None,
) -> RailResult:
    """Halve leverage for 4 weeks when portfolio DD from ATH > 25%."""
    ath, current, dd_pct = _dd_pct_from_ath(portfolio_equity_snapshots_24h)

    fired = dd_pct > threshold_pct
    ref_now = now or datetime.now(tz=UTC)
    until_utc = ref_now + HALVE_LEVERAGE_DURATION
    payload: dict[str, Any] = {
        "ath_usd": str(ath),
        "current_equity_usd": str(current),
        "dd_pct": str(dd_pct),
        "threshold_pct": str(threshold_pct),
        "halved_leverage_until_utc": until_utc.isoformat(),
    }
    if not fired:
        return RailResult(
            rail_id=RailId.PORTFOLIO_DD_25,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"portfolio_dd={dd_pct:.4f}% <= {threshold_pct}%",
        )
    return RailResult(
        rail_id=RailId.PORTFOLIO_DD_25,
        fired=True,
        severity=RailSeverity.WARN,
        action=RailAction.HALVE_LEVERAGE,
        payload=payload,
        message=(
            f"portfolio_dd={dd_pct:.4f}% > {threshold_pct}% → halve leverage 4w"
        ),
    )


__all__ = ["HALVE_LEVERAGE_DURATION", "rail_04_portfolio_dd_25"]
