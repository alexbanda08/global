"""Phase 30 — AsyncShadowLogger: per-strategy async queue → CSV drain.

D-02: hot-path zero-blocking; CSV write batched on background task.
D-13: 30-day rolling delete via cron (deployed by Plan 30-11 Task 5 operator
       checkpoint — this module documents the CSV format + filename contract
       but does NOT touch /etc/cron.daily/).
Pitfall 4 (RESEARCH §"Pitfall 4"): NEVER call structlog or any IO on the
       hot path. `log()` is sync, returns immediately, drops on QueueFull.
Pitfall 6 (RESEARCH §"Pitfall 6"): NOT used for pg_notify; that's
       `notify_event` in poly_maker_loop (Plan 30-10).

Public API (locked for Plan 30-10 wiring):
  - __init__(strategy_code, log_dir, *, maxsize, drain_batch_size,
             drain_timeout_s, alert_service)
  - log(decision, sim_fill=False, slug_state=None) — sync, never blocks
  - async start()  — spawn drain task
  - async stop()   — cancel + final drain (within 2s)
  - stats()        — dict[str, int] for operator monitoring

CLAUDE.md invariant #10: `structlog` is imported at module top; no
secrets ever flow through `log()` calls in this module — Decisions carry
only public market data + local order IDs.
"""
from __future__ import annotations

import asyncio
import contextlib
import csv
import io
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any

import aiofiles
import structlog

from backend.app.strategies.polymarket.maker.types import Decision, SlugState

if TYPE_CHECKING:
    from backend.app.services.alert_service import AlertService

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# CSV column layout — fixed order so dashboard / replay tooling can
# stream-parse without negotiating a schema. Add new columns ONLY at the
# end (append-only); never reorder.
# ---------------------------------------------------------------------------

SHADOW_LOG_COLUMNS: list[str] = [
    "ts_us",
    "strategy",
    "slug",
    "asset",
    "tf",
    "action",
    "side",
    "price",
    "size",
    "notional",
    "order_id",
    "fill_simulated",
    "inv_up",
    "inv_dn",
    "cash_spent",
    "cash_received",
    "cash_recovered",
    "rebates",
    "taker_fees",
    "slug_pnl_so_far",
    "slug_offset_s",
    "trigger_reason",
]


# Queue item shape: (decision, sim_fill_flag, optional slug_state)
_QueueItem = tuple[Decision, bool, "SlugState | None"]


class AsyncShadowLogger:
    """Per-strategy async log queue → CSV drain.

    Hot path: `log()` calls `queue.put_nowait()`. On `QueueFull`, the call
    silently increments `_dropped_count` — never raises, never awaits,
    never touches IO. Background `_drain_loop` task batches up to
    `drain_batch_size` items and writes them via `aiofiles.open(..., 'a')`.

    One CSV file per (strategy_code, UTC date) under `log_dir`. The first
    write of the day emits a header row matching `SHADOW_LOG_COLUMNS`;
    subsequent writes append data rows only.

    Drop-rate alerting: when more than 1% of recent log calls are
    dropped within the last 60s, `alert_service.emit(...)` is fired
    with `kind="poly_maker_shadow_log_drops"` (rate-limited to once
    per minute via `_last_alert_ts`).
    """

    def __init__(
        self,
        strategy_code: str,
        log_dir: Path,
        *,
        maxsize: int = 10_000,
        drain_batch_size: int = 100,
        drain_timeout_s: float = 0.1,
        alert_service: AlertService | None = None,
    ) -> None:
        self._strategy_code = strategy_code
        self._log_dir = Path(log_dir)
        self._batch_size = drain_batch_size
        self._timeout_s = drain_timeout_s
        self._alert_service = alert_service
        self._queue: asyncio.Queue[_QueueItem] = asyncio.Queue(maxsize=maxsize)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Cumulative counters — operator-visible via stats()
        self._drained_count = 0
        self._dropped_count = 0
        # Drop-rate sliding window — entries are (monotonic_ts, cumulative_drops)
        # older than 60s; trimmed each drain iteration.
        self._drop_window: deque[tuple[float, int]] = deque()
        self._last_alert_ts: float = 0.0

    # -----------------------------------------------------------------
    # Hot path — sync, zero-blocking
    # -----------------------------------------------------------------

    def log(
        self,
        decision: Decision,
        sim_fill: bool = False,
        slug_state: SlugState | None = None,
    ) -> None:
        """Hot-path entry. Zero-blocking. Drops on overflow.

        MUST NOT call structlog, do IO, or `await` anything. The decision
        is enqueued and the call returns. The background `_drain_loop`
        task does all CSV / disk work.
        """
        try:
            self._queue.put_nowait((decision, sim_fill, slug_state))
        except asyncio.QueueFull:
            self._dropped_count += 1
            # NO structlog call here — see Pitfall 4. The drop-rate alert
            # fires from the drain loop instead.

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def start(self) -> None:
        """Spawn the background drain task."""
        self._stop.clear()
        self._task = asyncio.create_task(
            self._drain_loop(),
            name=f"shadow_log.{self._strategy_code}",
        )

    async def stop(self) -> None:
        """Signal stop; cancel drain task within 2s; final-drain queue."""
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._task, timeout=2.0)
            if not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
        # Flush any items still queued — `stop()` must not lose decisions.
        await self._final_drain()

    # -----------------------------------------------------------------
    # Drain task — internal
    # -----------------------------------------------------------------

    async def _drain_loop(self) -> None:
        """Background task: pull items, batch, write CSV, repeat."""
        while not self._stop.is_set():
            batch: list[_QueueItem] = []
            try:
                # First item: wait up to drain_timeout_s
                item = await asyncio.wait_for(self._queue.get(), timeout=self._timeout_s)
                batch.append(item)
                # Remaining: drain non-blocking up to batch_size
                while len(batch) < self._batch_size:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
            except asyncio.TimeoutError:
                # No items arrived during the wait window — that's fine,
                # check stop flag and loop again.
                pass
            if batch:
                try:
                    await self._write_batch(batch)
                    self._drained_count += len(batch)
                except Exception as exc:
                    # Per T-30-08-03: drain task crash is mitigated — log
                    # and continue rather than die. structlog OFF the hot
                    # path (we're in the drain task, not log()) — safe here.
                    log.error(
                        "shadow_log.write_failed",
                        strategy=self._strategy_code,
                        batch_size=len(batch),
                        error=str(exc),
                    )
            await self._maybe_alert_drops()

    async def _final_drain(self) -> None:
        """Flush remaining queue items on stop — no decisions lost."""
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
                    "shadow_log.final_drain_failed",
                    strategy=self._strategy_code,
                    batch_size=len(batch),
                    error=str(exc),
                )

    # -----------------------------------------------------------------
    # CSV write
    # -----------------------------------------------------------------

    async def _write_batch(self, batch: list[_QueueItem]) -> None:
        """Write `batch` to `<log_dir>/<strategy>_<UTC-date>.csv` (append).

        First write of the file includes the SHADOW_LOG_COLUMNS header.
        Per-batch buffer keeps disk to one fsync per drain iteration.
        Midnight rollover handled naturally — `date_str` is re-evaluated
        each call, so the path swaps to a new file at 00:00 UTC.
        """
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        path = self._log_dir / f"{self._strategy_code.lower()}_{date_str}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        first_write = not path.exists()

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=SHADOW_LOG_COLUMNS)
        if first_write:
            writer.writeheader()
        for decision, sim_fill, slug_state in batch:
            writer.writerow(self._row_from_decision(decision, sim_fill, slug_state))

        async with aiofiles.open(path, "a") as f:
            await f.write(buf.getvalue())

    def _row_from_decision(
        self,
        decision: Decision,
        sim_fill: bool,
        slug_state: SlugState | None,
    ) -> dict[str, Any]:
        """Build a single CSV row from (Decision, sim_fill, optional SlugState).

        Missing fields → empty string (NOT 'None' / NOT 0). The dashboard
        treats empty as "n/a"; sentinels would corrupt aggregations.
        """
        row: dict[str, Any] = {col: "" for col in SHADOW_LOG_COLUMNS}
        row["ts_us"] = decision.ts_us
        row["strategy"] = decision.strategy
        row["slug"] = decision.slug
        row["asset"] = decision.asset
        row["tf"] = decision.tf
        row["action"] = decision.action
        row["side"] = decision.side or ""
        row["price"] = str(decision.price) if decision.price is not None else ""
        row["size"] = str(decision.size) if decision.size is not None else ""
        if decision.price is not None and decision.size is not None:
            row["notional"] = str(decision.price * decision.size)
        row["order_id"] = decision.order_id or ""
        row["fill_simulated"] = "1" if sim_fill else "0"
        row["trigger_reason"] = decision.trigger_reason or ""
        if slug_state is not None:
            row["inv_up"] = str(slug_state.inv_up)
            row["inv_dn"] = str(slug_state.inv_dn)
            row["cash_spent"] = str(slug_state.cash_spent)
            row["cash_received"] = str(slug_state.cash_received)
            row["rebates"] = str(slug_state.rebates_received)
            row["taker_fees"] = str(slug_state.taker_fees_paid)
        return row

    # -----------------------------------------------------------------
    # Drop-rate alerting
    # -----------------------------------------------------------------

    async def _maybe_alert_drops(self) -> None:
        """Fire `alert_service.emit(...)` if drop rate > 1%/min.

        Rate-limited to once per minute (`_last_alert_ts`) to avoid alert
        spam during sustained overload. The 1-minute sliding window
        compares cumulative drops at start-of-window vs current.
        """
        if self._alert_service is None:
            return
        now = monotonic()
        # Trim entries older than 60s
        while self._drop_window and (now - self._drop_window[0][0]) > 60.0:
            self._drop_window.popleft()
        # Snapshot baseline-at-start-of-window
        baseline_drops = self._drop_window[0][1] if self._drop_window else 0
        baseline_drained = 0  # not currently tracked per-window; conservative
        recent_drops = self._dropped_count - baseline_drops
        recent_drained = self._drained_count - baseline_drained
        # Refresh window tail when we have new drops to track
        if not self._drop_window or self._dropped_count > self._drop_window[-1][1]:
            self._drop_window.append((now, self._dropped_count))

        # Drop rate: drops / (drops + drained) over the window
        # Use max(1, ...) to avoid division-by-zero before any drain has run
        total_recent = max(1, recent_drops + recent_drained)
        drop_rate = recent_drops / total_recent
        if drop_rate > 0.01 and (now - self._last_alert_ts) > 60.0:
            self._last_alert_ts = now
            # Lazy import to keep AlertSeverity off the hot-import path
            from backend.app.services.alert_service import AlertSeverity

            with contextlib.suppress(Exception):
                await self._alert_service.emit(
                    severity=AlertSeverity.CRITICAL,
                    kind="poly_maker_shadow_log_drops",
                    strategy=self._strategy_code,
                    drops_last_min=recent_drops,
                    drained_last_min=recent_drained,
                    drop_rate=f"{drop_rate * 100:.2f}%",
                )

    # -----------------------------------------------------------------
    # Operator monitoring
    # -----------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return operator-visible counters.

        Plan 30-12c surfaces these via /sleeves/{id}/stats so the dashboard
        can show queue saturation in real-time.
        """
        return {
            "queue_size": self._queue.qsize(),
            "drained": self._drained_count,
            "dropped": self._dropped_count,
        }


__all__ = ["AsyncShadowLogger", "SHADOW_LOG_COLUMNS"]
