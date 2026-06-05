"""Digest loop — daily 07:00 UTC summary post (Phase 20 Task 7 · ALERT-05).

Mirrors the freezegun-safe pattern from backend.app.data.hl_retention:
- Pure ``_seconds_until_next_dispatch(now, hour_utc)`` for unit tests
- ``digest_loop`` cooperative shutdown via asyncio.Event
- Selects pending rows from engine.alert_digest_buffer; posts ONE Discord
  embed; on success marks rows digest_sent_at=now()
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from backend.app.services.alert_dispatch import Channel

logger = logging.getLogger(__name__)


def _seconds_until_next_dispatch(now: datetime, hour_utc: int) -> float:
    """Pure: seconds until next ``hour_utc:00:00`` UTC. Always > 0."""
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def digest_loop(
    pool: "asyncpg.Pool",
    discord_channel: "Channel",
    stop_event: asyncio.Event,
    hour_utc: int = 7,
) -> None:
    """Daily 07:00 UTC digest post; cooperative shutdown via ``stop_event``."""
    logger.info("digest_loop.started", extra={"hour_utc": hour_utc})
    try:
        while not stop_event.is_set():
            wait_s = _seconds_until_next_dispatch(datetime.now(UTC), hour_utc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_s)
                return
            except TimeoutError:
                pass
            try:
                await _run_one(pool, discord_channel)
            except Exception as exc:  # noqa: BLE001
                logger.warning("digest_loop.iter_failed", extra={"error": str(exc)})
    except asyncio.CancelledError:
        logger.info("digest_loop.stopped")
        raise


async def _run_one(pool: "asyncpg.Pool", discord_channel: "Channel") -> None:
    """One digest iteration: SELECT pending → POST → UPDATE on success."""
    from backend.app.services.alert_service import AlertSeverity

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, kind, severity FROM engine.alert_digest_buffer "
            "WHERE digest_sent_at IS NULL "
            "AND emitted_at > now() - interval '24 hours' "
            "ORDER BY emitted_at"
        )
        if not rows:
            logger.info("digest_loop.no_pending_rows")
            return

        # Group by (kind, severity)
        counts: dict[tuple[str, str], int] = {}
        ids: list[int] = []
        for r in rows:
            key = (r["kind"], r["severity"])
            counts[key] = counts.get(key, 0) + 1
            ids.append(r["id"])

        detail = {
            "summary": [
                {"kind": k, "severity": s, "count": c}
                for (k, s), c in sorted(counts.items())
            ],
            "total": len(rows),
        }
        ok = await discord_channel.send(
            severity=AlertSeverity.INFO,
            kind="daily_digest",
            detail=detail,
        )
        if ok:
            await conn.execute(
                "UPDATE engine.alert_digest_buffer SET digest_sent_at = now() "
                "WHERE id = ANY($1::bigint[])",
                ids,
            )
            logger.info(
                "digest_loop.dispatched",
                extra={"row_count": len(rows), "groups": len(counts)},
            )
        else:
            logger.warning("digest_loop.dispatch_failed", extra={"row_count": len(rows)})


__all__ = ["digest_loop", "_seconds_until_next_dispatch", "_run_one"]
