"""Rail 7 — exchange outage: no collector tick > 5min (RAIL-08, Phase 10 Task 4).

Fires when the most-recent collector tick is older than
``threshold_minutes`` minutes ago. Action: ``CLOSE_ALL`` + severity
``CRITICAL``. The BarEngine checks Rail 7 BEFORE any per-sleeve dispatch
(10-CONTEXT D-08); on fire, calls ``portfolio.force_exit_all('exchange_outage')``
+ writes a ``trading.events(kind='rail_fired')`` row and skips sleeve
dispatch for this wake.

Pure function. The BarEngine queries ``max(at) FROM collectors.*`` and
passes the result in.

**CLAUDE.md §7 invariant**: this rail never calls a kill method. Close-
all is fundamentally different from kill — it flattens positions via
the normal executor path; kill is a coordinated three-layer shutdown
implemented in Phase 12.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.engine.rails.framework import (
    RailAction,
    RailId,
    RailResult,
    RailSeverity,
)


def rail_07_exchange_outage(
    *,
    last_tick_at: datetime,
    now: datetime,
    threshold_minutes: int = 5,
) -> RailResult:
    """Close all positions if the last collector tick is stale.

    Parameters
    ----------
    last_tick_at:
        Timestamp of the most recent collector row.
    now:
        Reference timestamp (usually ``BarEngine.clock()``).
    threshold_minutes:
        How old (in minutes) ``last_tick_at`` can be before Rail 7 fires.
        5 min is the v0.1 default from 10-CONTEXT D-08.
    """
    delta = now - last_tick_at
    delta_seconds = delta.total_seconds()
    payload: dict[str, Any] = {
        "last_tick_at": last_tick_at.isoformat(),
        "now": now.isoformat(),
        "delta_seconds": delta_seconds,
        "threshold_minutes": threshold_minutes,
    }

    if delta_seconds <= threshold_minutes * 60:
        return RailResult(
            rail_id=RailId.EXCHANGE_OUTAGE,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"collector fresh (delta={delta_seconds:.1f}s)",
        )
    return RailResult(
        rail_id=RailId.EXCHANGE_OUTAGE,
        fired=True,
        severity=RailSeverity.CRITICAL,
        action=RailAction.CLOSE_ALL,
        payload=payload,
        message=(
            f"collector stale {delta_seconds:.1f}s > {threshold_minutes}min → close_all"
        ),
    )


__all__ = ["rail_07_exchange_outage"]
