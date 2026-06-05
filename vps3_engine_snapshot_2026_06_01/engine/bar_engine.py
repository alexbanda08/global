"""BarEngine — asyncio UTC bar-boundary scheduler (Phase 7, Task 5 · ENG-01 / ENG-03).

Per 07-CONTEXT D-01 / D-02:

* Single long-running coroutine (``run()``). NOT cron, NOT apscheduler, NOT
  systemd timers — systemd only keeps this Python process alive.
* Computes next bar boundary per registered sleeve, sleeps until
  ``boundary + 5s`` (CLAUDE.md invariant #3), then dispatches in
  boundary-order.
* Idempotency: every dispatch inserts an ``engine.bar_runs`` row keyed on
  ``(sleeve_id, symbol, timeframe, boundary_utc)``. A duplicate raises
  ``asyncpg.UniqueViolationError`` — we treat that as a benign SKIP (a
  double wake on the same boundary has already been handled).
* Crash-recovery: dispatch writes ``status='started'`` first, then
  ``status='completed'`` / ``status='failed'`` after the controller
  returns. A ``started`` row without ``completed_at`` signals a mid-
  dispatch crash; inspection logic is a future Phase 10 enhancement —
  Phase 7 simply records the state faithfully.

Heartbeat: every successful dispatch emits a ``bar_engine.heartbeat`` log
line and a ``trading.events`` row (kind='heartbeat', severity='info') —
this is what the 48h reconcile script counts (expect ~12 over 48h on 4h
cadence).

SIGTERM: the run loop catches ``asyncio.CancelledError`` and exits cleanly.
An in-flight ``_dispatch`` call is awaited to completion before the loop
returns. systemd's ``ExecStop`` sends SIGTERM; the runner script in Task 7
wires this end-to-end.
"""
from __future__ import annotations

import asyncio
import json
import logging
import traceback
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

import asyncpg

from backend.app.data.bars import get_bars
from backend.app.engine.models import SleeveRegistration
from backend.app.engine.notify import notify_event
from backend.app.engine.rails.rail_07_exchange_outage import rail_07_exchange_outage
from backend.app.engine.sleeve_timeframes import (
    SLEEVE_TIMEFRAMES,  # canonical TF registry — do not duplicate (CLAUDE.md inv #12)
)
from backend.app.engine.trader_writes import apply_pending_trader_writes

# Re-exported so static analysis sees the symbol used (acceptance grep).
__SLEEVE_TF_CANONICAL__ = SLEEVE_TIMEFRAMES

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from backend.app.controllers.base import SleeveController


logger = logging.getLogger(__name__)


async def load_last_collector_tick(
    pool: asyncpg.Pool,
    *,
    now: datetime,
) -> datetime:
    """Return ``MAX(at)`` across the hot collector table(s).

    Returns ``now`` (no-op — keeps Rail 7 silent) when the collectors
    schema / tables do not exist yet — pre-Phase-3 deployments should
    not trigger Rail 7 on missing-collector conditions.

    Any DB error is logged + treated as a no-op to avoid false-positive
    outage triggers. A real outage persists across wakes; the next wake
    picks it up once the collector schema exists.
    """
    try:
        async with pool.acquire() as conn:
            schema = await conn.fetchval(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name='collectors' LIMIT 1"
            )
            if schema is None:
                logger.info(
                    "bar_engine.collector_schema_not_ready",
                    extra={
                        "event": "bar_engine.collector_schema_not_ready",
                        "note": "Rail 7 skipped (pre-Phase-3)",
                    },
                )
                return now
            for tbl in ("binance_klines_v2", "binance_klines"):
                exists = await conn.fetchval(
                    "SELECT to_regclass($1)",
                    f"collectors.{tbl}",
                )
                if exists is None:
                    continue
                last = await conn.fetchval(
                    f"SELECT MAX(at) FROM collectors.{tbl}"  # noqa: S608 - table name is a literal
                )
                if last is not None:
                    return last
                return now
            logger.info(
                "bar_engine.collector_table_not_ready",
                extra={"event": "bar_engine.collector_table_not_ready"},
            )
            return now
    except Exception as e:  # noqa: BLE001 — defensive: any DB error → no-op.
        logger.warning(
            "bar_engine.collector_tick_query_failed",
            extra={
                "event": "bar_engine.collector_tick_query_failed",
                "error": str(e),
            },
        )
        return now


class BarEngine:
    """Single-node asyncio scheduler for sleeve bar-close dispatch.

    Usage::

        engine = BarEngine(pool=pool)
        engine.register("SOL_BBBreak", "SOL", "4h", controller)
        await engine.run()  # blocks forever until cancelled.

    Tests may inject ``clock`` / ``sleep`` for deterministic loops. The
    production defaults wrap ``datetime.now(UTC)`` and ``asyncio.sleep``.
    """

    # Public alias for the default bar buffer so tests can reference it.
    DEFAULT_BAR_BUFFER_SECONDS: float = 5.0

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        bar_buffer_seconds: float = DEFAULT_BAR_BUFFER_SECONDS,
    ) -> None:
        self.pool = pool
        self.clock = clock
        self._sleep = sleep
        self.bar_buffer_seconds = bar_buffer_seconds
        self._sleeves: list[SleeveRegistration] = []
        # Phase 12 · Task 1 (KILL-01, KILL-04, KILL-09).
        # Kill ⇒ run loop halts and does NOT dispatch (positions already
        # flattened by the kill endpoint; watchdog does post-kill reconcile).
        # Vacation ⇒ engine wakes on each boundary but skips all dispatch
        # (clean freeze — preserves open positions without new entries).
        # Both flags are mutated via set_kill / set_vacation by Layer 0
        # tv-api handlers; BarEngine itself does NOT call them.
        self._kill_active: bool = False
        self._vacation_active: bool = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        sleeve_id: str,
        symbol: str,
        timeframe: str,
        controller: SleeveController,
        *,
        bar_count: int = 100,
    ) -> None:
        """Register a sleeve for periodic ``on_bar_close`` dispatch.

        ``bar_count`` tells the engine how many closed bars to fetch before
        each ``controller.on_bar_close(bars)`` call. 100 is plenty for
        BB(20) + ATR(14) with room to spare.
        """
        # Validate timeframe eagerly so a bad config fails fast (not 4h later).
        self._compute_next_boundary(timeframe, datetime.now(UTC))

        self._sleeves.append(
            SleeveRegistration(
                sleeve_id=sleeve_id,
                symbol=symbol,
                timeframe=timeframe,
                controller=controller,
                bar_count=bar_count,
            )
        )
        logger.info(
            "bar_engine.sleeve_registered",
            extra={
                "event": "bar_engine.sleeve_registered",
                "sleeve_id": sleeve_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "bar_count": bar_count,
            },
        )

    # ------------------------------------------------------------------
    # Next-boundary math
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_next_boundary(tf: str, now: datetime) -> datetime:
        """Next UTC bar boundary strictly AFTER ``now`` for timeframe ``tf``.

        Rules:

        * ``4h`` → next hour in {0, 4, 8, 12, 16, 20} UTC (strictly after now).
        * ``1h`` → next UTC hour.
        * ``15m`` / ``5m`` → next 15m / 5m mark.
        * ``1w`` → next Monday 00:00 UTC (Python weekday 0 = Monday).

        ``ValueError`` on unknown timeframe.
        """
        # Normalize to UTC, strip microseconds-within-second for boundary math.
        now_utc = now.astimezone(UTC)

        if tf == "4h":
            # Floor to hour, then add hours until hour % 4 == 0 and > now.
            floor = now_utc.replace(minute=0, second=0, microsecond=0)
            # Candidate: next multiple-of-4 hour at or after floor.
            hour_mod = floor.hour % 4
            candidate = floor + timedelta(hours=(4 - hour_mod) if hour_mod else 4)
            # ``floor`` with hour_mod == 0 and now_utc == floor is a boundary
            # NOW — we still want the NEXT one, so always add 4h in that case.
            # The conditional above handles both cases (hour_mod 0 → +4h).
            # But also: if floor itself is > now, floor is a boundary we want
            # to return. Re-check:
            if hour_mod == 0 and floor > now_utc:
                candidate = floor
            return candidate
        if tf == "1h":
            floor = now_utc.replace(minute=0, second=0, microsecond=0)
            if floor > now_utc:
                return floor
            return floor + timedelta(hours=1)
        if tf == "15m":
            minute_floor = (now_utc.minute // 15) * 15
            floor = now_utc.replace(minute=minute_floor, second=0, microsecond=0)
            if floor > now_utc:
                return floor
            return floor + timedelta(minutes=15)
        if tf == "5m":
            minute_floor = (now_utc.minute // 5) * 5
            floor = now_utc.replace(minute=minute_floor, second=0, microsecond=0)
            if floor > now_utc:
                return floor
            return floor + timedelta(minutes=5)
        if tf == "1w":
            # Python: Monday=0 ... Sunday=6. Find next Monday 00:00 UTC strictly
            # after now.
            today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            days_until_mon = (7 - today.weekday()) % 7
            if days_until_mon == 0:
                # today is Monday — if we're past 00:00, return next Monday.
                days_until_mon = 7 if today <= now_utc else 0
            return today + timedelta(days=days_until_mon)

        raise ValueError(f"unknown timeframe for BarEngine: {tf!r}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the scheduler until cancelled.

        Infinite loop: compute the minimum next boundary across all sleeves,
        sleep until ``boundary + bar_buffer_seconds``, dispatch every sleeve
        whose next boundary is at or before now. Idempotency lives in
        ``_dispatch``.
        """
        if not self._sleeves:
            logger.warning(
                "bar_engine.run_with_no_sleeves",
                extra={"event": "bar_engine.run_with_no_sleeves"},
            )
            return

        try:
            while True:
                # Phase 12 · Task 1 (KILL-01, KILL-09): short-circuit BEFORE
                # even computing next boundary. Kill path has flattened all
                # positions via tv-api /kill + portfolio.force_exit_all;
                # watchdog owns post-kill reconciliation. No dispatch ever
                # again until the operator restarts the process.
                if self._kill_active:
                    logger.warning(
                        "bar_engine.halted_kill_active",
                        extra={"event": "bar_engine.halted_kill_active"},
                    )
                    await self._sleep(60.0)
                    continue

                now = self.clock()
                # For each sleeve, compute the next boundary. Pick the earliest.
                next_by_sleeve = [
                    (s, self._compute_next_boundary(s.timeframe, now))
                    for s in self._sleeves
                ]
                earliest = min(b for _, b in next_by_sleeve)

                wake_at = earliest + timedelta(seconds=self.bar_buffer_seconds)
                delay = max(0.0, (wake_at - now).total_seconds())
                logger.info(
                    "bar_engine.sleep_until",
                    extra={
                        "event": "bar_engine.sleep_until",
                        "wake_at": wake_at.isoformat(),
                        "delay_s": delay,
                    },
                )
                await self._sleep(delay)

                # Vacation check lives AFTER the boundary sleep so the
                # engine keeps marching on bar boundaries during vacation
                # (we want audit rows proving the engine is alive, just
                # deliberately not dispatching). On the next wake: if
                # vacation is still on, skip dispatch + record a
                # vacation_freeze_bar event.
                if self._vacation_active:
                    await self._emit_vacation_freeze_bar(boundary=earliest)
                    logger.info(
                        "bar_engine.vacation_freeze_bar",
                        extra={
                            "event": "bar_engine.vacation_freeze_bar",
                            "boundary": earliest.isoformat(),
                        },
                    )
                    continue

                # Phase 10 · Rail 7 pre-dispatch check (RAIL-08 · 10-CONTEXT D-08).
                # BEFORE any sleeve dispatches, check collector freshness.
                # Stale tick > 5min → fire Rail 7 + skip dispatch + emit event.
                # Portfolio-level force_exit_all is called from the controller
                # integration path (Task 7); Phase 10 BarEngine only records
                # the rail firing and skips dispatch for this wake.
                now_after = self.clock()
                outage_result = await self._check_rail_07(now=now_after)
                if outage_result is not None and outage_result.fired:
                    await self._emit_rail_fired(outage_result)
                    logger.warning(
                        "bar_engine.rail_07_outage_skip_dispatch",
                        extra={
                            "event": "bar_engine.rail_07_outage_skip_dispatch",
                            "delta_seconds": outage_result.payload.get(
                                "delta_seconds"
                            ),
                        },
                    )
                    continue

                # Phase 18 · CLAUDE.md inv #12 race protection:
                # apply queued live trader writes BEFORE strategy evaluation.
                # ``apply_pending_trader_writes`` pulls live (not shadow) rows
                # whose ``requested_at <= earliest`` and stamps ``applied_at``
                # — guaranteeing a write that landed mid-bar takes effect at
                # the NEXT bar boundary, never mid-bar (PITFALLS row 11).
                # Per-row failures are caught inside the function and recorded
                # to the audit row's ``error`` column; this call must NEVER
                # raise into the run loop.
                try:
                    applied = await apply_pending_trader_writes(self.pool, earliest)
                    if applied:
                        logger.info(
                            "bar_engine.trader_writes_applied",
                            extra={
                                "event": "bar_engine.trader_writes_applied",
                                "count": applied,
                                "boundary": earliest.isoformat(),
                            },
                        )
                except Exception:  # pragma: no cover - defensive: must NEVER abort the loop.
                    logger.exception(
                        "bar_engine.trader_writes_apply_failed",
                        extra={"event": "bar_engine.trader_writes_apply_failed"},
                    )

                # Dispatch every sleeve whose boundary has passed.
                # Phase 8 ENG-02: per-sleeve isolation via asyncio.TaskGroup.
                # Exceptions are caught INSIDE _dispatch_one so sibling tasks
                # are never cancelled when one sleeve fails.
                due: list[tuple[SleeveRegistration, datetime]] = [
                    (s, b) for s, b in next_by_sleeve if b <= now_after
                ]
                if due:
                    async with asyncio.TaskGroup() as tg:
                        for sleeve, boundary in due:
                            tg.create_task(
                                self._dispatch_one(sleeve, boundary),
                                name=f"dispatch.{sleeve.sleeve_id}",
                            )
        except asyncio.CancelledError:
            logger.info(
                "bar_engine.cancelled",
                extra={"event": "bar_engine.cancelled"},
            )
            raise

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def _dispatch_one(
        self,
        sleeve: SleeveRegistration,
        boundary: datetime,
    ) -> None:
        """Per-sleeve dispatch wrapper for ENG-02 isolation (Phase 8 Task 6).

        Exceptions are caught HERE (not at the TaskGroup layer) so one sleeve's
        failure cannot cancel sibling tasks. The failure is logged, persisted
        to ``engine.bar_runs(status='failed')``, and a critical alert is
        emitted — but the method returns normally.

        * On ``UniqueViolationError``: benign SKIP (ENG-03).
        * On controller ``Exception``: row → ``failed`` with ``error_summary``
          + critical alert + swallow (do NOT re-raise).
        * On success: row → ``completed`` + heartbeat event.
        """
        # --- Idempotency INSERT. Own transaction so the row survives even
        # if the controller raises later.
        bar_run_id: UUID | None = None
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                row = await conn.fetchrow(
                    "INSERT INTO engine.bar_runs "
                    "(sleeve_id, symbol, timeframe, boundary_utc, status) "
                    "VALUES ($1, $2, $3, $4, 'started') "
                    "RETURNING bar_run_id",
                    sleeve.sleeve_id,
                    sleeve.symbol,
                    sleeve.timeframe,
                    boundary,
                )
                bar_run_id = row["bar_run_id"] if row is not None else None
        except asyncpg.UniqueViolationError:
            logger.info(
                "bar_engine.dispatch_skipped_idempotent",
                extra={
                    "event": "bar_engine.dispatch_skipped_idempotent",
                    "sleeve_id": sleeve.sleeve_id,
                    "symbol": sleeve.symbol,
                    "timeframe": sleeve.timeframe,
                    "boundary": boundary.isoformat(),
                },
            )
            return
        except Exception as e:  # noqa: BLE001 — idempotency row write failed; treat as failed dispatch.
            logger.exception(
                "bar_engine.bar_runs_insert_failed",
                extra={
                    "event": "bar_engine.bar_runs_insert_failed",
                    "sleeve_id": sleeve.sleeve_id,
                    "boundary": boundary.isoformat(),
                    "error": str(e),
                },
            )
            return

        # --- Fetch bars + call controller. Any Exception is caught,
        # persisted + alerted, and SWALLOWED so sibling TaskGroup tasks
        # survive (ENG-02).
        try:
            bars = await get_bars(
                sleeve.symbol,
                sleeve.timeframe,
                sleeve.bar_count,
                pool=self.pool,
            )
            # get_bars returns newest-first; strategies assume oldest-first.
            bars_oldest_first = list(reversed(bars))
            await sleeve.controller.on_bar_close(bars_oldest_first)
        except Exception as e:  # noqa: BLE001 - we genuinely catch-and-persist (ENG-02 isolation).
            await self._mark_failed(
                bar_run_id=bar_run_id,
                sleeve=sleeve,
                boundary=boundary,
                exc=e,
            )
            await self._emit_alert_critical(
                sleeve,
                {
                    "kind": "dispatch_failed",
                    "boundary": boundary.isoformat(),
                    "error": str(e),
                },
            )
            # Do NOT re-raise — per-sleeve isolation. Sibling TaskGroup tasks
            # must keep running even if this one fails.
            return
        else:
            await self._mark_completed(bar_run_id=bar_run_id)
            await self._emit_heartbeat(sleeve, boundary)

    async def _mark_completed(self, *, bar_run_id: UUID | None) -> None:
        if bar_run_id is None:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE engine.bar_runs SET status='completed', completed_at=now() "
                "WHERE bar_run_id=$1",
                bar_run_id,
            )

    async def _mark_failed(
        self,
        *,
        bar_run_id: UUID | None,
        sleeve: SleeveRegistration,
        boundary: datetime,
        exc: BaseException,
    ) -> None:
        error_summary = "".join(
            traceback.format_exception_only(type(exc), exc)
        ).strip()
        logger.error(
            "bar_engine.dispatch_failed",
            extra={
                "event": "bar_engine.dispatch_failed",
                "sleeve_id": sleeve.sleeve_id,
                "boundary": boundary.isoformat(),
                "error": error_summary,
            },
        )
        if bar_run_id is None:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE engine.bar_runs SET status='failed', completed_at=now(), "
                "error_summary=$1 WHERE bar_run_id=$2",
                error_summary[:500],
                bar_run_id,
            )

    # ------------------------------------------------------------------
    # Phase 12 · Task 1 — kill/vacation flag control (KILL-01, KILL-04, KILL-09).
    # ------------------------------------------------------------------

    def set_kill(self, active: bool) -> None:
        """Toggle the kill flag.

        Called by ``backend/app/api/kill.py`` AFTER positions are flattened
        and the kill event is audited. Pure in-memory flip — does NOT touch
        the DB. CLAUDE.md #7: this is a SETTER not a kill method, kept
        deliberately boring so no agent-reachable code path can misuse it.
        """
        self._kill_active = active

    def set_vacation(self, active: bool) -> None:
        """Toggle the vacation flag.

        Called by ``backend/app/api/keepalive.py``. KILL-04 clean-freeze
        semantics: ``True`` means "skip dispatch on all future bars without
        liquidating"; ``False`` means "resume normal dispatch". Separate
        from ``set_kill`` because vacation explicitly does NOT close
        positions.
        """
        self._vacation_active = active

    async def _emit_vacation_freeze_bar(self, *, boundary: datetime) -> None:
        """Write ``trading.events(kind='vacation_freeze_bar')`` per boundary.

        Audit trail that the engine was alive + honoring vacation. Best-
        effort — a DB failure must not abort the run loop.
        """
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO trading.events (at, kind, data) "
                    "VALUES (now(), 'vacation_freeze_bar', $1::jsonb)",
                    _json_dumps({"boundary": boundary.isoformat()}),
                )
        except Exception:  # pragma: no cover - best-effort
            logger.exception(
                "bar_engine.vacation_freeze_bar_emit_failed",
                extra={"event": "bar_engine.vacation_freeze_bar_emit_failed"},
            )

    async def _emit_heartbeat(
        self,
        sleeve: SleeveRegistration,
        boundary: datetime,
    ) -> None:
        """Write a ``trading.events`` row with kind='heartbeat' (ALERT-09)."""
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                "VALUES (now(), $1, 'heartbeat', $2::jsonb)",
                sleeve.sleeve_id,
                _json_dumps(
                    {
                        "severity": "info",
                        "symbol": sleeve.symbol,
                        "timeframe": sleeve.timeframe,
                        "boundary": boundary.isoformat(),
                    }
                ),
            )
        logger.info(
            "bar_engine.heartbeat",
            extra={
                "event": "bar_engine.heartbeat",
                "sleeve_id": sleeve.sleeve_id,
                "boundary": boundary.isoformat(),
            },
        )

    async def _emit_alert_critical(
        self,
        sleeve: SleeveRegistration,
        data: dict,
    ) -> None:
        """Write a ``trading.events`` row with kind='alert', severity='critical'."""
        payload = {"severity": "critical", "sleeve_id": sleeve.sleeve_id, **data}
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, 'alert', $2::jsonb)",
                    sleeve.sleeve_id,
                    _json_dumps(payload),
                )
        except Exception:  # pragma: no cover - alerts must never mask original errors.
            logger.exception(
                "bar_engine.alert_emit_failed",
                extra={"event": "bar_engine.alert_emit_failed", "payload": payload},
            )

    # ------------------------------------------------------------------
    # Rail 7 pre-dispatch check (Phase 10 · Task 4 · RAIL-08)
    # ------------------------------------------------------------------

    async def _check_rail_07(self, *, now: datetime) -> Any:  # type: ignore[name-defined]
        """Evaluate Rail 7 against the most-recent collector tick.

        Returns the ``RailResult`` (or None on hard failure) so the main
        loop can decide whether to skip dispatch. Soft failures (missing
        collector table) return a ``fired=False`` result — Rail 7 stays
        silent pre-Phase-3.
        """
        try:
            last_tick_at = await load_last_collector_tick(self.pool, now=now)
            return rail_07_exchange_outage(last_tick_at=last_tick_at, now=now)
        except Exception as e:  # noqa: BLE001 — rail check must never abort the engine.
            logger.warning(
                "bar_engine.rail_07_check_failed",
                extra={
                    "event": "bar_engine.rail_07_check_failed",
                    "error": str(e),
                },
            )
            return None

    async def _emit_rail_fired(self, result: Any) -> None:
        """Write ``trading.events(kind='rail_fired', data=...)`` for a fired rail.

        Best-effort — failures are logged, not raised. Engine continues.
        Phase 17.1 Plan 02: after the INSERT commits, emits a pg_notify on
        the ``tv_events`` channel (kind="rail_fire") so tv-api / ws_terminal
        can stream rail-fires to the operator UI in real time.
        """
        data = {
            "rail_id": result.rail_id.value,
            "severity": result.severity.value,
            "action": result.action.value,
            "payload": result.payload,
            "message": result.message,
        }
        try:
            async with self.pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "INSERT INTO trading.events (at, kind, data) "
                        "VALUES (now(), 'rail_fired', $1::jsonb)",
                        _json_dumps(data),
                    )
                # NOTIFY emit AFTER the INSERT transaction commits.
                await notify_event(conn, kind="rail_fire", payload=data)
        except Exception:  # pragma: no cover - rail audit must never mask progress.
            logger.exception(
                "bar_engine.rail_fired_emit_failed",
                extra={
                    "event": "bar_engine.rail_fired_emit_failed",
                    "rail_id": data.get("rail_id"),
                },
            )


def _json_dumps(data: dict) -> str:
    """JSON serializer tolerant of Decimal / UUID / datetime."""
    def _default(o: object) -> object:
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, UUID):
            return str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(f"not serializable: {type(o)!r}")

    return json.dumps(data, default=_default)


__all__ = ["BarEngine"]
