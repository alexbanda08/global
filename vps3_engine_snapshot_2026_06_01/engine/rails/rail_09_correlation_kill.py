"""Rail 9 — correlation kill: 3+ sleeves hit 24h DD in 24h (RAIL-10, Phase 10 Task 5).

Fires when ``threshold_count`` or more UNIQUE sleeves have fired Rail 2
(``rail_02_sleeve_24h_dd``) within the last 24h. The input is the list
of ``trading.events`` rows (pre-filtered upstream) with
``kind='rail_fired'`` and ``data.rail_id='rail_02_sleeve_24h_dd'``.

The rail DEDUPES by ``data.sleeve_id`` — 5 firings from the same sleeve
count as 1. The threshold is ``>=`` (3 unique sleeves fires), which is
the ONLY non-strict comparison in the rails — "3 sleeves blown" is the
canonical trigger, not "3.01 sleeves".

Action: ``REQUEST_KILL`` + severity ``CRITICAL``.

**CLAUDE.md §7 invariant**: this rail does NOT call any kill method;
it only requests via the RailAction enum. Phase 12 executes.
"""
from __future__ import annotations

from typing import Any

from backend.app.engine.rails.framework import (
    RailAction,
    RailId,
    RailResult,
    RailSeverity,
)


def rail_09_correlation_kill(
    *,
    recent_sleeve_dd_firings_24h: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    threshold_count: int = 3,
) -> RailResult:
    """Kill-request when 3+ UNIQUE sleeves fired Rail 2 in the last 24h.

    ``recent_sleeve_dd_firings_24h`` rows should each have either a
    top-level ``sleeve_id`` key OR a nested ``data.sleeve_id``. Both are
    accepted for flexibility. Unique sleeve_ids are counted via a set
    (dedupe).
    """
    # Extract unique sleeve ids. Use a set for dedupe.
    unique_sleeve_ids: set[str] = set()
    for row in recent_sleeve_dd_firings_24h:
        sid: str | None = None
        if isinstance(row, dict):
            sid = row.get("sleeve_id")
            if sid is None:
                inner = row.get("data")
                if isinstance(inner, dict):
                    sid = inner.get("sleeve_id")
        if sid:
            unique_sleeve_ids.add(sid)

    count = len(unique_sleeve_ids)
    payload: dict[str, Any] = {
        "unique_sleeve_count": count,
        "threshold_count": threshold_count,
        "breaching_sleeve_ids": sorted(unique_sleeve_ids),
    }

    if count >= threshold_count:
        return RailResult(
            rail_id=RailId.CORRELATION_KILL,
            fired=True,
            severity=RailSeverity.CRITICAL,
            action=RailAction.REQUEST_KILL,
            payload=payload,
            message=(
                f"{count} unique sleeves breached 24h DD in 24h window "
                f"(>= {threshold_count}) → request kill"
            ),
        )
    return RailResult(
        rail_id=RailId.CORRELATION_KILL,
        fired=False,
        severity=RailSeverity.INFO,
        action=RailAction.NONE,
        payload=payload,
        message=f"{count} unique sleeves breaches < {threshold_count}",
    )


__all__ = ["rail_09_correlation_kill"]
