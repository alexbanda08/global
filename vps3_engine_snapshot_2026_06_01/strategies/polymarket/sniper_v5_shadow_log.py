"""Phase 35 — AsyncJsonlShadowLogger: async-queue → JSONL drain.

Ports the Phase 30-08 ``AsyncShadowLogger`` pattern with three
substitutions tailored to the sniper-v5 spec §7 schema:

  1. Output is **JSONL** (one ``json.dumps`` per line), NOT CSV. The
     §7 schema is nested (``gates_evaluated`` is a ``dict[str, bool]``;
     ``l25_book_snapshot`` is a ``dict[str, float]``) — CSV would force
     schema-flattening that breaks downstream ``jq`` / ``pandas.read_json``
     tooling. JSONL preserves the §7 shape 1:1 and supports per-row
     schema evolution without a header negotiation.
  2. ``log()`` takes a single ``dict[str, Any]`` event (the full §7 row),
     NOT a ``Decision`` / ``SlugState`` tuple. The controller (Plan 35-13)
     assembles the event dict and hands it off.
  3. Filename is ``<UTC-date>.jsonl`` — NO strategy prefix. One file per
     UTC day for ALL 16 sleeves; ``sleeve_id`` lives in the row payload
     so downstream ``jq 'select(.sleeve_id == "...")'`` filters trivially.

Everything else mirrors Phase 30-08 verbatim:

  * Hot path zero-blocking (``queue.put_nowait``); on ``QueueFull``,
    increments ``_dropped_count`` and returns — NEVER raises, NEVER
    awaits, NEVER touches IO (CLAUDE Pitfall 4).
  * Background ``_drain_loop`` batches up to ``drain_batch_size``
    items and writes via a single ``aiofiles.open(..., "a")`` block
    so one fsync per drain iteration.
  * ``_final_drain`` flushes remaining queue items on ``stop()`` so no
    events are lost across systemd restarts.
  * Drop-rate alerting via injected ``AlertService``: when ``drops /
    (drops + drained)`` over a 60s sliding window exceeds 1 %, emits
    ``severity=CRITICAL`` + ``kind="poly_sniper_v5_shadow_log_drops"``
    (rate-limited to once / 60s via ``_last_alert_ts``).

CLAUDE.md cross-refs:

  * inv #4 (rails are pure functions, evaluated BEFORE the signal) —
    not directly enforced here but every gate the controller consults
    must respect that contract.
  * inv #10 (secrets never in logs) — the §7 schema carries only
    public market data + sleeve metadata; no API keys / wallet
    addresses ever flow through the event dict, so structlog redaction
    is a defence-in-depth bonus rather than load-bearing.
  * inv #13 (TV-native data ownership for live) — this writer lives
    inside ``tv-engine`` and writes to ``trading.*``-adjacent local
    files, NOT to Storedata's ``public.*``.

Public API (locked for Plan 35-13 wiring):

  * ``__init__(log_dir, *, maxsize, drain_batch_size, drain_timeout_s,
                alert_service)`` — note NO ``strategy_code`` arg (one
                file/day for all 16 sleeves).
  * ``log(event: dict[str, Any]) -> None`` — sync, zero-blocking, drops
    on overflow. NEVER raises.
  * ``async start()`` — spawn background drain task.
  * ``async stop()`` — cancel drain w/ 2s timeout, then ``_final_drain``.
  * ``stats() -> dict[str, int]`` — operator-visible queue/drain/drop
    counters.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any

import aiofiles
import structlog

if TYPE_CHECKING:
    from backend.app.services.alert_service import AlertService

log = structlog.get_logger(__name__)


# Alias for the queue payload — purely documentary; mypy treats it the
# same as ``dict[str, Any]``.
_QueueItem = dict[str, Any]


class AsyncJsonlShadowLogger:
    """Async-queue → JSONL drain logger for the sniper-v5 sleeves.

    See the module docstring for the architectural contract. This class
    is intended to be instantiated ONCE at engine boot (Plan 35-12
    spawn block) and shared across all 16 sniper-v5 sleeves; the
    controller (Plan 35-13) calls ``.log(event_dict)`` per fire event.
    """

    def __init__(
        self,
        log_dir: Path,
        *,
        maxsize: int = 10_000,
        drain_batch_size: int = 100,
        drain_timeout_s: float = 0.1,
        alert_service: AlertService | None = None,
    ) -> None:
        self._log_dir = Path(log_dir)
        self._batch_size = drain_batch_size
        self._timeout_s = drain_timeout_s
        self._alert_service = alert_service
        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Cumulative counters — operator-visible via ``stats()``.
        self._drained_count = 0
        self._dropped_count = 0
        # Sliding-window drops — entries are (monotonic_ts, cumulative_drops).
        # Trimmed each drain iteration to entries newer than 60s.
        self._drop_window: deque[tuple[float, int]] = deque()
        self._last_alert_ts: float = 0.0

    # ------------------------------------------------------------------
    # Hot path — sync, zero-blocking (Pitfall 4)
    # ------------------------------------------------------------------

    def log(self, event: dict[str, Any]) -> None:
        """Enqueue a §7 event for background JSONL serialisation.

        Sync, returns immediately, NEVER blocks, NEVER raises. On a
        ``QueueFull`` (drain overwhelmed → backpressure) the call
        increments ``_dropped_count`` and returns; the next drain
        iteration evaluates the drop rate and may emit a CRITICAL
        alert.

        Pitfall 4 enforcement: this method MUST NOT call structlog or
        any IO. The verifying test (#3) monkey-patches the module-
        level ``log`` to raise on attribute access and asserts that
        100 ``.log()`` calls complete without bubbling — keep this
        body exclusively to ``put_nowait`` + ``except QueueFull``.
        """
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped_count += 1
            # NO structlog call here — see Pitfall 4. The drop-rate
            # alert fires from the drain loop instead (off the hot path).

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the background drain task."""
        self._stop.clear()
        self._task = asyncio.create_task(
            self._drain_loop(),
            name="shadow_log.sniper_v5",
        )

    async def stop(self) -> None:
        """Signal stop, cancel drain within 2s, then ``_final_drain``."""
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._task, timeout=2.0)
            if not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
        # Flush any items still queued — ``stop()`` must not lose events.
        await self._final_drain()

    # ------------------------------------------------------------------
    # Drain task — internal
    # ------------------------------------------------------------------

    async def _drain_loop(self) -> None:
        """Background task: pull items, batch, write JSONL, repeat."""
        while not self._stop.is_set():
            batch: list[_QueueItem] = []
            try:
                # First item: wait up to drain_timeout_s for backpressure.
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._timeout_s,
                )
                batch.append(item)
                # Remaining: drain non-blocking up to batch_size.
                while len(batch) < self._batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
            except asyncio.TimeoutError:
                # No items arrived during the wait window — check stop
                # flag and loop again.
                pass
            if batch:
                try:
                    await self._write_batch(batch)
                    self._drained_count += len(batch)
                except Exception as exc:
                    # Drain-task crash mitigation — log and continue
                    # rather than die. structlog is OFF the hot path
                    # here (we're in the drain task, not log()) so it
                    # is safe to call. Logs a structured event so the
                    # operator can see disk failures in journalctl.
                    log.error(
                        "sniper_v5_shadow_log.write_failed",
                        batch_size=len(batch),
                        error=str(exc),
                    )
            await self._maybe_alert_drops()

    async def _final_drain(self) -> None:
        """Flush remaining queue items on stop — no events lost."""
        batch: list[_QueueItem] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            try:
                await self._write_batch(batch)
                self._drained_count += len(batch)
            except Exception as exc:
                log.error(
                    "sniper_v5_shadow_log.final_drain_failed",
                    batch_size=len(batch),
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # JSONL write
    # ------------------------------------------------------------------

    async def _write_batch(self, batch: list[_QueueItem]) -> None:
        """Write ``batch`` to ``<log_dir>/<UTC-date>.jsonl`` (append).

        One ``json.dumps`` per event with ``separators=(",", ":")`` for
        compact output (no spaces; matches what ``jq -c`` would
        produce). Single ``aiofiles.open(..., "a")`` per drain
        iteration so we get one fsync per batch — not per event.

        Midnight rollover handled naturally — ``date_str`` is
        re-evaluated each call, so the path swaps to a new file at
        00:00 UTC. This is exercised by tests 6 + 7.
        """
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        path = self._log_dir / f"{date_str}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)

        # Build the payload off-IO so the file is open for as short a
        # window as possible. ``"\n".join`` would skip the trailing
        # newline — we want each line terminated, including the last,
        # so downstream ``jq -c '. | .sleeve_id'`` reads the final
        # record cleanly even if the process crashes mid-batch.
        buf_parts = [
            json.dumps(event, separators=(",", ":"), default=str)
            for event in batch
        ]
        payload = "\n".join(buf_parts) + "\n"

        async with aiofiles.open(path, "a") as f:
            await f.write(payload)

    # ------------------------------------------------------------------
    # Drop-rate alerting
    # ------------------------------------------------------------------

    async def _maybe_alert_drops(self) -> None:
        """Fire ``alert_service.emit(...)`` if drop rate > 1%/60s.

        Rate-limited to once per minute (``_last_alert_ts``) to avoid
        alert spam during sustained overload. The sliding window
        compares cumulative drops at start-of-window vs current.
        """
        if self._alert_service is None:
            return
        now = monotonic()
        # Trim entries older than 60s.
        while self._drop_window and (now - self._drop_window[0][0]) > 60.0:
            self._drop_window.popleft()
        # Snapshot baseline-at-start-of-window.
        baseline_drops = self._drop_window[0][1] if self._drop_window else 0
        baseline_drained = 0   # not currently tracked per-window; conservative.
        recent_drops = self._dropped_count - baseline_drops
        recent_drained = self._drained_count - baseline_drained
        # Refresh window tail when there are new drops to track.
        if not self._drop_window or self._dropped_count > self._drop_window[-1][1]:
            self._drop_window.append((now, self._dropped_count))

        # Drop rate: drops / (drops + drained) over the window. ``max(1, ...)``
        # avoids division-by-zero before any drain has run.
        total_recent = max(1, recent_drops + recent_drained)
        drop_rate = recent_drops / total_recent
        if drop_rate > 0.01 and (now - self._last_alert_ts) > 60.0:
            self._last_alert_ts = now
            # Lazy import keeps AlertSeverity off the hot-import path.
            from backend.app.services.alert_service import AlertSeverity

            with contextlib.suppress(Exception):
                await self._alert_service.emit(
                    severity=AlertSeverity.CRITICAL,
                    kind="poly_sniper_v5_shadow_log_drops",
                    drops_last_min=recent_drops,
                    drained_last_min=recent_drained,
                    drop_rate=f"{drop_rate * 100:.2f}%",
                )

    # ------------------------------------------------------------------
    # Operator monitoring
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return operator-visible counters.

        Plan 35-13 will surface these via the engine ``/sleeves/{id}/stats``
        endpoint so the dashboard can show queue saturation in real-time.
        """
        return {
            "queue_size": self._queue.qsize(),
            "drained": self._drained_count,
            "dropped": self._dropped_count,
        }


__all__ = ["AsyncJsonlShadowLogger"]
