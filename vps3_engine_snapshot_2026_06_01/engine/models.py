"""Pydantic + dataclass models for the BarEngine (Phase 7 D-01 / D-02; Phase 9 XSM state).

Shapes:

* ``BarRun`` (Pydantic v2) mirrors the ``engine.bar_runs`` row (Alembic
  revision ``0003_engine_bar_runs``). Used for typed loads on crash
  recovery and tests.
* ``SleeveRegistration`` (dataclass) is the in-memory record held by the
  ``BarEngine`` for each registered sleeve — carries the controller
  reference plus scheduling metadata.
* ``XSMHolding`` / ``XSMState`` (Pydantic v2, frozen) persist across
  weekly rebalances for the V24 XSM sleeve. Serialized atomically via
  ``backend.app.engine.state_store.AtomicStateStore`` (Phase 9 Task 4,
  STRAT-HL-08).

All are pure data. No IO, no side-effects. ``SleeveRegistration`` uses a
plain dataclass (not Pydantic) because ``controller`` is a live object with
an open DB pool — Pydantic would try to validate it and fail.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.controllers.base import SleeveController


class BarRun(BaseModel):
    """Typed row from ``engine.bar_runs``.

    Read path: SELECT … FROM engine.bar_runs WHERE sleeve_id=$1 AND
    status='started' AND completed_at IS NULL; used during crash-recovery
    scan at engine startup.

    Status transitions:

    * ``started`` → ``completed`` (controller returned normally)
    * ``started`` → ``failed``   (controller raised; ``error_summary`` populated)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bar_run_id: UUID
    sleeve_id: str
    symbol: str
    timeframe: str
    boundary_utc: datetime
    dispatched_at: datetime
    completed_at: datetime | None = None
    status: Literal["started", "completed", "failed"]
    error_summary: str | None = None


@dataclass
class SleeveRegistration:
    """One registered sleeve in the ``BarEngine``.

    Held in memory; not persisted. The ``controller`` is a live
    ``SleeveController`` instance sharing the engine's asyncpg pool. The
    ``bar_count`` field tells the engine how many closed bars to fetch
    via ``get_bars()`` before calling ``controller.on_bar_close(bars)``.
    """

    sleeve_id: str
    symbol: str
    timeframe: str
    controller: SleeveController
    bar_count: int = 100


class XSMHolding(BaseModel):
    """One slot in the V24 XSM sleeve — a single coin held week-over-week.

    ``position_id`` links back to ``trading.positions.position_id`` so the
    reconciler (Phase 9 Task 6) can cross-check live DB state against the
    persisted ``xsm_state.json``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    coin: str
    qty: Decimal
    entry_px: Decimal
    entry_week: datetime  # week-start UTC (Monday 00:00)
    position_id: UUID


class XSMState(BaseModel):
    """Persisted state for the V24 XSM sleeve (Phase 9 · STRAT-HL-08).

    Stored atomically at ``$TV_STATE_DIR/xsm_state.json`` via
    ``AtomicStateStore[XSMState]``. Crash-safe: ``AtomicStateStore.load``
    returns ``None`` if the file is missing or corrupt, and the XSM
    controller fails open by constructing a fresh state.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    universe: tuple[str, ...]
    holdings: tuple[XSMHolding, ...] = ()
    equity_usd: Decimal = Decimal("0")
    last_rebalance_utc: datetime | None = None
    filter_fired: bool = False
    filter_reason: str | None = None


class Keepalive(BaseModel):
    """One row from ``engine.keepalive`` (Phase 12, Task 1 · KILL-04/05/06/09).

    Written by:
    - ``POST /keepalive`` (operator_ui) — sets ``expires_at = now + window``.
    - ``POST /vacation`` (vacation_toggle) — sets ``vacation_until`` and
      ``expires_at = vacation_until + 1h``.

    Watchdog polls ``MAX(expires_at)`` and fires a clean freeze when the
    window expires AND no active vacation row covers the present moment.

    Frozen: keepalive rows are write-once audit rows.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    keepalive_id: UUID
    at: datetime
    source: Literal["operator_ui", "vacation_toggle"]
    vacation_until: datetime | None = None
    expires_at: datetime


class EquitySnapshot(BaseModel):
    """One row from ``engine.equity_snapshots`` (Phase 10, Task 2).

    Used by Rails 2/3/4/5/11 to compute DD-from-ATH and 24h window
    deltas. ``scope`` is either ``'portfolio'`` (aggregate across all
    sleeves) or ``'sleeve:<sleeve_id>'`` (per-sleeve). ``dd_pct`` is a
    denormalized convenience — the rail recomputes from equity + ath
    anyway, but the column is useful for direct SQL inspection.

    Frozen: snapshots are write-once audit rows. Mutation on the way
    out would indicate a logic bug (the rail would be re-using a stale
    object).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    at: datetime
    scope: str
    equity_usd: Decimal
    ath_usd: Decimal
    dd_pct: Decimal
    window_24h_low: Decimal | None = None


__all__ = [
    "BarRun",
    "EquitySnapshot",
    "Keepalive",
    "SleeveRegistration",
    "XSMHolding",
    "XSMState",
]
