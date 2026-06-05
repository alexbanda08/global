"""Rail 2 — per-sleeve 24h drawdown > 8% (RAIL-03, Phase 10 Task 3).

Fires when the sleeve's equity has dropped more than ``threshold_pct``
from its 24h high. Action: ``PAUSE_SLEEVE``.

Boundary semantics: strict ``>``. A sleeve at exactly 8.00% DD does NOT
fire. 8.01% fires.

Pure function: takes a pre-loaded list of snapshots and returns a
``RailResult``. Zero IO. The controller loads snapshots via
``backend.app.engine.equity_snapshots.load_snapshots_24h`` and passes
them in.
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


def _compute_dd_pct_from_high(snapshots: Iterable[Any]) -> tuple[Decimal, Decimal, Decimal]:
    """Return (high_24h, min_24h, dd_pct_from_high).

    ``dd_pct = (high - min) / high * 100``. Matches 10-CONTEXT D-05 but
    uses the 24h HIGH (not snapshots[0]) as the denominator so a sleeve
    that recovered mid-window doesn't silently reset its DD reference.
    """
    equities = [Decimal(str(getattr(s, "equity_usd", s["equity_usd"] if isinstance(s, dict) else 0))) for s in snapshots]
    if not equities:
        return Decimal("0"), Decimal("0"), Decimal("0")
    high = max(equities)
    low = min(equities)
    if high == 0:
        return high, low, Decimal("0")
    dd_pct = (high - low) / high * Decimal("100")
    return high, low, dd_pct


def rail_02_sleeve_24h_dd(
    *,
    sleeve_id: str,
    sleeve_equity_snapshots_24h: Iterable[Any],
    threshold_pct: Decimal = Decimal("8.0"),
) -> RailResult:
    """Pause a sleeve when 24h DD > 8%.

    Parameters
    ----------
    sleeve_id:
        For audit only — included in the event payload.
    sleeve_equity_snapshots_24h:
        Oldest-first iterable of snapshot-like objects with an
        ``equity_usd`` attribute or key.
    threshold_pct:
        Strict-greater-than threshold. 8.0% is the v0.1 default from
        ``IMPLEMENTATION_GUIDE §6``.

    Returns
    -------
    RailResult with:

    * ``fired=True`` and ``action=PAUSE_SLEEVE`` when
      ``dd_pct_24h > threshold_pct``.
    * ``fired=False`` otherwise.
    """
    snaps = list(sleeve_equity_snapshots_24h)
    high, low, dd_pct_24h = _compute_dd_pct_from_high(snaps)

    fired = dd_pct_24h > threshold_pct
    payload: dict[str, Any] = {
        "sleeve_id": sleeve_id,
        "dd_pct_24h": str(dd_pct_24h),
        "threshold_pct": str(threshold_pct),
        "high_24h": str(high),
        "low_24h": str(low),
        "snapshot_count": len(snaps),
    }
    if not fired:
        return RailResult(
            rail_id=RailId.SLEEVE_24H_DD,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"dd_pct_24h={dd_pct_24h:.4f} <= threshold {threshold_pct}",
        )
    return RailResult(
        rail_id=RailId.SLEEVE_24H_DD,
        fired=True,
        severity=RailSeverity.WARN,
        action=RailAction.PAUSE_SLEEVE,
        payload=payload,
        message=(
            f"sleeve={sleeve_id} 24h DD={dd_pct_24h:.4f}% > {threshold_pct}% → pause"
        ),
    )


__all__ = ["rail_02_sleeve_24h_dd"]
