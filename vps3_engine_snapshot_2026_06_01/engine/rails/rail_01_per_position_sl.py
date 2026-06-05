"""Rail 1 — per-position SL hit (RAIL-02, Phase 10 Task 3).

Wraps ``backend.app.executors.barriers.check_barriers`` for audit. When
the SL barrier fires on the last closed bar, Rail 1 emits an INFO
severity result with ``action=CLOSE_POSITION``.

The executor's own barrier logic already closes the position — Rail 1 is
the audit layer. CLAUDE.md invariant #1: ``reduce_only=True`` on every
exit is enforced by the executor, not this rail.

Pure function: no IO. Controller composes ``BarrierInputs`` + ``TrailState``
on top of the raw ``Position`` row before calling.
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
from backend.app.executors.barriers import (
    BarrierInputs,
    TrailState,
    check_barriers,
)


def rail_01_per_position_sl(
    *,
    position: BarrierInputs,
    last_bar: Any,
    trail_state: TrailState,
    now: datetime,
) -> RailResult:
    """Fire an INFO audit result when the per-position SL barrier hits.

    Delegates entirely to ``check_barriers``; if ``sl_hit=True`` returns
    a ``fired=True`` result with ``CLOSE_POSITION`` action. The
    controller's existing pipeline handles the actual close; this is the
    uniform-audit layer that lets operators trace every SL via
    ``trading.events(kind='rail_fired', data.rail_id='rail_01_...')``.

    Parameters
    ----------
    position:
        Barrier-input view of the open position (side, entry_at, tp_px,
        sl_px, max_hold_td).
    last_bar:
        Last closed bar (duck-typed — has ``.high``, ``.low``, ``.close``).
    trail_state:
        In-memory trail state (current_trail_px, atr_px).
    now:
        Reference timestamp; usually ``bars[-1].close_time``.
    """
    result = check_barriers(
        position=position,
        last_bar=last_bar,
        trail_state=trail_state,
        now=now,
    )

    if not result.sl_hit:
        return RailResult(
            rail_id=RailId.PER_POSITION_SL,
            fired=False,
            severity=RailSeverity.INFO,
            action=RailAction.NONE,
            payload={},
            message="sl_not_hit",
        )

    payload: dict[str, Any] = {
        "side": position.side,
        "sl_px": str(position.sl_px),
        "last_bar_low": str(last_bar.low),
        "last_bar_high": str(last_bar.high),
        "last_bar_close": str(last_bar.close),
    }
    return RailResult(
        rail_id=RailId.PER_POSITION_SL,
        fired=True,
        severity=RailSeverity.INFO,
        action=RailAction.CLOSE_POSITION,
        payload=payload,
        message=f"sl_hit side={position.side} sl_px={position.sl_px}",
    )


__all__ = ["rail_01_per_position_sl"]
