"""Rail 6 — funding-rate spike > 0.15% / 8h (RAIL-07, Phase 10 Task 4).

Fires when the current 8h funding rate exceeds the threshold in either
direction:

* ``funding_rate_8h > +threshold`` → ``action=BLOCK_NEW_LONG`` (longs
  pay high carry; new longs are disadvantaged).
* ``funding_rate_8h < -threshold`` → ``action=BLOCK_NEW_SHORT``.
* ``|funding_rate_8h| <= threshold`` → ``fired=False``.

Strict-``>`` boundary on absolute comparison. Exactly at threshold does
NOT fire.

Pure function. Caller supplies the rate (Phase 3 collector or HL REST).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from backend.app.engine.rails.framework import (
    RailAction,
    RailId,
    RailResult,
    RailSeverity,
)


def rail_06_funding_spike(
    *,
    coin: str,
    funding_rate_8h: Decimal,
    threshold: Decimal = Decimal("0.0015"),
) -> RailResult:
    """Block new entries on one side when funding spikes beyond threshold.

    Parameters
    ----------
    coin:
        Symbol the rate applies to (e.g. ``'BTC'``).
    funding_rate_8h:
        Current 8h funding rate as a decimal fraction (0.0015 = 0.15%).
    threshold:
        Absolute threshold; both +threshold and -threshold are checked.
    """
    abs_rate = funding_rate_8h.copy_abs()
    payload: dict[str, Any] = {
        "coin": coin,
        "funding_rate_8h": str(funding_rate_8h),
        "threshold": str(threshold),
    }

    if abs_rate <= threshold:
        return RailResult(
            rail_id=RailId.FUNDING_SPIKE,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"funding rate {funding_rate_8h} within ±{threshold}",
        )

    if funding_rate_8h > threshold:
        return RailResult(
            rail_id=RailId.FUNDING_SPIKE,
            fired=True,
            severity=RailSeverity.WARN,
            action=RailAction.BLOCK_NEW_LONG,
            payload=payload,
            message=(
                f"funding spike positive {funding_rate_8h} > {threshold} → block_new_long"
            ),
        )
    # funding_rate_8h < -threshold → BLOCK_NEW_SHORT.
    return RailResult(
        rail_id=RailId.FUNDING_SPIKE,
        fired=True,
        severity=RailSeverity.WARN,
        action=RailAction.BLOCK_NEW_SHORT,
        payload=payload,
        message=(
            f"funding spike negative {funding_rate_8h} < -{threshold} → block_new_short"
        ),
    )


__all__ = ["rail_06_funding_spike"]
