"""V52 daily rebalance loop (Phase 8.1 Task 11 · D-08).

Wakes at UTC 00:00 + 5s daily, computes inv-vol P3 weights via the blender
(Task 10), UPDATEs ``engine.v52_streams.target_weight``, writes a
``engine.v52_stream_snapshots`` row per active stream, logs a structured
event. Idempotent: re-run on same day is a no-op via ``last_rebalance_at``.

Boundary helper: rounds-down-to-next-UTC-midnight + 5s. Cancellation-safe
(CancelledError → exit gracefully). Mirrors the pattern of
``writer_health.probe_loop`` from Phase 3.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from backend.app.strategies.v52.blender import (
    DIVERSIFIER_STREAMS,
    P3_STREAMS,
    P5_STREAMS,
    compute_stream_targets,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

REBALANCE_OFFSET_SECONDS = 5  # D-08: UTC 00:00 + 5s
ALL_STREAMS_CANONICAL = (*P3_STREAMS, *P5_STREAMS, *DIVERSIFIER_STREAMS)


def next_rebalance_seconds(now: datetime, offset_seconds: int = REBALANCE_OFFSET_SECONDS) -> float:
    """Seconds from `now` until next UTC midnight + offset."""
    next_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    target = next_midnight + timedelta(seconds=offset_seconds)
    delta = (target - now).total_seconds()
    if delta <= 0:
        # Today's window already passed → next day's
        target = target + timedelta(days=1)
        delta = (target - now).total_seconds()
    return delta


async def fetch_active_streams(pool: asyncpg.Pool) -> tuple[set[str], dict[str, float]]:
    """Read engine.v52_streams. Returns (active_stream_ids, equity_by_stream)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stream_id, cash, peak_equity, disabled FROM engine.v52_streams"
        )
    active: set[str] = set()
    equity: dict[str, float] = {}
    for r in rows:
        if r["disabled"]:
            continue
        active.add(r["stream_id"])
        equity[r["stream_id"]] = float(r["cash"]) if r["cash"] is not None else 0.0
    return active, equity


async def rebalance_once(
    pool: asyncpg.Pool,
    portfolio_equity: float,
    p3_returns: dict[str, np.ndarray] | None = None,
    now: datetime | None = None,
) -> dict[str, float]:
    """Single-tick rebalance. Idempotent on (stream_id, ts) snapshots."""
    now = now or datetime.now(UTC)
    active, _equity = await fetch_active_streams(pool)
    targets = compute_stream_targets(
        portfolio_equity=portfolio_equity,
        p3_returns=p3_returns or {},
        active_streams=active or None,
    )

    async with pool.acquire() as conn, conn.transaction():
        for stream_id, target_notional in targets.items():
            target_weight = (
                target_notional / portfolio_equity if portfolio_equity > 0 else 0.0
            )
            await conn.execute(
                """
                UPDATE engine.v52_streams
                   SET target_weight = $1,
                       last_rebalance_at = $2
                 WHERE stream_id = $3
                """,
                target_weight,
                now,
                stream_id,
            )
            await conn.execute(
                """
                INSERT INTO engine.v52_stream_snapshots
                    (stream_id, ts, notional, position_side)
                VALUES ($1, $2, $3, 0)
                ON CONFLICT (stream_id, ts) DO UPDATE
                  SET notional = EXCLUDED.notional
                """,
                stream_id,
                now,
                target_notional,
            )

    logger.info(
        "v52.rebalance.tick",
        extra={
            "event": "v52.rebalance.tick",
            "ts": now.isoformat(),
            "active_streams": sorted(active),
            "n_targets": len(targets),
            "equity": portfolio_equity,
        },
    )
    return targets


async def v52_rebalance_loop(
    pool: asyncpg.Pool,
    portfolio_equity_provider,  # callable () -> float
    stop: asyncio.Event,
    p3_returns_provider=None,  # callable () -> dict[stream_id, np.ndarray]
    offset_seconds: int = REBALANCE_OFFSET_SECONDS,
) -> None:
    """Daily UTC 00:00 + offset rebalance loop, registered in engine/main.py TaskGroup."""
    logger.info(
        "v52.rebalance.started",
        extra={"event": "v52.rebalance.started", "offset_seconds": offset_seconds},
    )
    try:
        while not stop.is_set():
            now = datetime.now(UTC)
            wait = next_rebalance_seconds(now, offset_seconds)
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
                break  # stop signalled
            except TimeoutError:
                pass

            try:
                equity = float(portfolio_equity_provider())
                p3_rets = p3_returns_provider() if p3_returns_provider else {}
                await rebalance_once(pool, equity, p3_returns=p3_rets)
            except Exception as exc:  # pragma: no cover
                logger.error(
                    "v52.rebalance.tick_failed",
                    extra={"event": "v52.rebalance.tick_failed", "error": repr(exc)},
                )
    except asyncio.CancelledError:
        logger.info("v52.rebalance.cancelled", extra={"event": "v52.rebalance.cancelled"})
        raise
    finally:
        logger.info("v52.rebalance.stopped", extra={"event": "v52.rebalance.stopped"})


__all__ = [
    "ALL_STREAMS_CANONICAL",
    "REBALANCE_OFFSET_SECONDS",
    "fetch_active_streams",
    "next_rebalance_seconds",
    "rebalance_once",
    "v52_rebalance_loop",
]
