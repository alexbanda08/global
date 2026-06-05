"""Rail 11 — abs-$ day-loss layer (RAIL-11, Phase 10 Task 6).

Two parallel rails over ``engine.equity_snapshots`` portfolio rows:

* ``rail_11a_abs_day_loss_warn`` — fires when
  ``max(24h equity) - min(24h equity) > warn_threshold_usd``. Action:
  ``NONE`` (informational WARN alert; controller emits an alert but
  does NOT pause/halve/kill).
* ``rail_11b_abs_day_loss_kill`` — same delta, higher threshold →
  ``action=REQUEST_KILL`` + severity ``CRITICAL``.

Strict-``>``. Exactly at threshold does NOT fire.

Thresholds come from env vars in ``risk_guardrails``:

* ``RAIL_ABS_DAY_LOSS_WARN_USD`` (default 5000)
* ``RAIL_ABS_DAY_LOSS_KILL_USD`` (default 15000)
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


def _window_delta_usd(snapshots: Iterable[Any]) -> tuple[Decimal, Decimal, Decimal]:
    """Return (max_24h, min_24h, delta = max - min). Empty input → (0,0,0)."""
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
    mx = max(equities)
    mn = min(equities)
    return mx, mn, mx - mn


def rail_11a_abs_day_loss_warn(
    *,
    equity_snapshots_24h: Iterable[Any],
    threshold_usd: Decimal,
) -> RailResult:
    """Warn when abs-$ 24h loss > ``threshold_usd``."""
    mx, mn, delta = _window_delta_usd(equity_snapshots_24h)
    payload: dict[str, Any] = {
        "max_24h_usd": str(mx),
        "min_24h_usd": str(mn),
        "loss_24h_usd": str(delta),
        "threshold_usd": str(threshold_usd),
    }
    fired = delta > threshold_usd
    if not fired:
        return RailResult(
            rail_id=RailId.ABS_DAY_LOSS_WARN,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"abs_day_loss={delta} <= warn_threshold={threshold_usd}",
        )
    return RailResult(
        rail_id=RailId.ABS_DAY_LOSS_WARN,
        fired=True,
        severity=RailSeverity.WARN,
        action=RailAction.NONE,
        payload=payload,
        message=f"abs_day_loss={delta} > warn_threshold={threshold_usd}",
    )


def rail_11b_abs_day_loss_kill(
    *,
    equity_snapshots_24h: Iterable[Any],
    threshold_usd: Decimal,
) -> RailResult:
    """Request kill when abs-$ 24h loss > ``threshold_usd``."""
    mx, mn, delta = _window_delta_usd(equity_snapshots_24h)
    payload: dict[str, Any] = {
        "max_24h_usd": str(mx),
        "min_24h_usd": str(mn),
        "loss_24h_usd": str(delta),
        "threshold_usd": str(threshold_usd),
    }
    fired = delta > threshold_usd
    if not fired:
        return RailResult(
            rail_id=RailId.ABS_DAY_LOSS_KILL,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload=payload,
            message=f"abs_day_loss={delta} <= kill_threshold={threshold_usd}",
        )
    return RailResult(
        rail_id=RailId.ABS_DAY_LOSS_KILL,
        fired=True,
        severity=RailSeverity.CRITICAL,
        action=RailAction.REQUEST_KILL,
        payload=payload,
        message=f"abs_day_loss={delta} > kill_threshold={threshold_usd} → request kill",
    )


__all__ = ["rail_11a_abs_day_loss_warn", "rail_11b_abs_day_loss_kill"]
