"""Orderbook publisher task (Phase 23 · D-27 / D-28).

1s-cadence loop. Reads ``focused_sleeve_ids`` set (populated by
``ws_terminal``'s ``subscribe_orderbook`` receiver — plan 23-02), fetches
``/book`` for each focused Polymarket sleeve via the existing
``PolyPaperExecutor.get_orderbook_snapshot`` CLOB direct-read path, then
publishes ``orderbook_snapshot`` events.

D-28 — focused-sleeve only. With at most ~6 _volume markets active in
the dashboard at any given moment, broadcasting all 6 every second
costs 6 RPS to CLOB plus 6× the WS bandwidth. Tracking which sleeve the
operator focused (per-WS-client state in ws_terminal) and only polling
that one saves 5/6 of bandwidth + CPU.

Publish path:
  - Production (tv-engine): the publisher is wired to ``notify_event``
    via a thin adapter so events flow through Postgres LISTEN/NOTIFY +
    the EventBus + ws_terminal — same path every other Phase 23 event
    uses (see ``backend/app/api/event_bus.py``).
  - Tests: an ``event_bus`` stub with ``async publish(kind, payload)``
    captures events without DB plumbing.

CLAUDE invariants:
    #11 read-only — no operator-write surface.
    #12 mid-bar mutation — subscribe is observability, not strategy
        state. Per-tick read of registry happens at tick start; mid-tick
        subscribe is observed in next tick. NOT a CLAUDE inv #12 violation
        per the threat-model T-23-03-08 disposition.
    #13 no public.* queries — book reads route through the executor's
        CLOB direct path (Storedata fallback only when configured).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# D-27 cadence — 1 second between book reads.
POLL_INTERVAL_SECONDS = 1.0

# UI-SPEC §5.9 N=5 locked. Mirrors the constant in
# backend/app/api/sleeves_orderbook.py.
TOP_N = 5


class FocusedSleeveRegistry:
    """Thread-safe set of focused sleeve_ids (one per active WS client).

    Lives module-level — both tv-api (writers via the
    ``subscribe_orderbook`` receiver in ``ws_terminal``) and tv-engine
    (the reader, this publisher) import the same singleton instance.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._set: set[str] = set()

    async def add(self, sleeve_id: str) -> None:
        async with self._lock:
            self._set.add(sleeve_id)

    async def remove(self, sleeve_id: str) -> None:
        async with self._lock:
            self._set.discard(sleeve_id)

    def snapshot(self) -> set[str]:
        """Return a *copy* of the focused-sleeve set.

        Snapshot is by-value — mutating the returned set does NOT affect
        the registry. Read is intentionally lock-free (set copy is atomic
        under the GIL) so the publisher's hot path never blocks on a
        client subscribe/unsubscribe.
        """
        return set(self._set)


# Module-level singleton — process-wide. Importable from both
# ws_terminal.py (writer) and engine main.py (reader = this publisher).
focused_sleeve_registry = FocusedSleeveRegistry()


def _coerce_levels(rows: Any) -> list[tuple[float, float]]:
    """Normalise mixed (price, size) tuple/list/dict rows into ``[(p, s), ...]``."""
    out: list[tuple[float, float]] = []
    if not rows:
        return out
    for row in rows:
        try:
            if isinstance(row, dict):
                p = float(row.get("price", 0.0))
                s = float(row.get("size", 0.0))
            else:
                p = float(row[0])
                s = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        out.append((p, s))
    return out


class OrderbookPublisher:
    """Polls focused Polymarket sleeves at 1s, publishes orderbook_snapshot events."""

    def __init__(
        self,
        *,
        focused_sleeve_registry: FocusedSleeveRegistry,
        paper_executor: Any,
        market_mapping: Any,
        event_bus: Any,
    ) -> None:
        self._registry = focused_sleeve_registry
        self._executor = paper_executor
        self._mapping = market_mapping
        self._bus = event_bus
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        """Main loop. Sleeps POLL_INTERVAL_SECONDS between iterations.

        ``self._stopped`` is checked between ticks AND used as the sleep
        primitive (``asyncio.wait_for`` on the event) so ``stop()``
        causes a clean exit without waiting out the full poll interval.
        """
        logger.info("orderbook_publisher.started")
        while not self._stopped.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=POLL_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                pass
        logger.info("orderbook_publisher.stopped")

    async def _tick(self) -> None:
        """One poll iteration. D-28 — early-return on empty registry."""
        focused = self._registry.snapshot()
        if not focused:
            return
        for sleeve_id in focused:
            # D-28 + threat T-23-03-02 — defence-in-depth: only Polymarket
            # sleeve_ids reach the executor. The ws_terminal receiver
            # already filters on this prefix; re-check here so a corrupted
            # registry can't drive book reads against HL sleeve_ids.
            if not sleeve_id.startswith("poly_updown_"):
                continue
            await self._tick_one(sleeve_id)

    async def _tick_one(self, sleeve_id: str) -> None:
        """Read + publish for a single focused sleeve. Exception-safe."""
        try:
            cid = await self._mapping.resolve_condition_id(sleeve_id)
        except Exception:  # noqa: BLE001 — log + drop, never crash loop
            logger.warning(
                "orderbook_publisher.resolve_failed",
                extra={
                    "event": "orderbook_publisher.resolve_failed",
                    "sleeve_id": sleeve_id,
                },
                exc_info=True,
            )
            return
        if cid is None:
            return

        try:
            snap = await self._executor.get_orderbook_snapshot(cid)
        except Exception:  # noqa: BLE001 — log + drop, never crash loop
            logger.warning(
                "orderbook_publisher.executor_failed",
                extra={
                    "event": "orderbook_publisher.executor_failed",
                    "sleeve_id": sleeve_id,
                },
                exc_info=True,
            )
            return

        if snap is None or snap.get("_stale") or not snap.get("ts"):
            return

        bids = sorted(
            _coerce_levels(snap.get("bids", [])), key=lambda r: -r[0]
        )[:TOP_N]
        asks = sorted(
            _coerce_levels(snap.get("asks", [])), key=lambda r: r[0]
        )[:TOP_N]
        payload: dict[str, Any] = {
            "sleeve_id": sleeve_id,
            "top_bids": [[float(p), float(s)] for p, s in bids],
            "top_asks": [[float(p), float(s)] for p, s in asks],
            "ts": int(snap.get("ts", time.time() * 1000)),
        }
        try:
            await self._bus.publish("orderbook_snapshot", payload)
        except Exception:  # noqa: BLE001 — log + drop, never crash loop
            logger.warning(
                "orderbook_publisher.publish_failed",
                extra={
                    "event": "orderbook_publisher.publish_failed",
                    "sleeve_id": sleeve_id,
                },
                exc_info=True,
            )

    def stop(self) -> None:
        """Signal the run loop to exit. Idempotent."""
        self._stopped.set()


def start_orderbook_publisher(
    *,
    focused_sleeve_registry: FocusedSleeveRegistry,
    paper_executor: Any,
    market_mapping: Any,
    event_bus: Any,
) -> OrderbookPublisher:
    """Factory for the engine TaskGroup. Returns the publisher instance.

    Caller is responsible for ``tg.create_task(pub.run(), name='orderbook_publisher')``
    and for invoking ``pub.stop()`` during shutdown.
    """
    return OrderbookPublisher(
        focused_sleeve_registry=focused_sleeve_registry,
        paper_executor=paper_executor,
        market_mapping=market_mapping,
        event_bus=event_bus,
    )


__all__ = [
    "FocusedSleeveRegistry",
    "OrderbookPublisher",
    "POLL_INTERVAL_SECONDS",
    "TOP_N",
    "focused_sleeve_registry",
    "start_orderbook_publisher",
]
