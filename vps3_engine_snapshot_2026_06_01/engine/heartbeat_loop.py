"""Heartbeat loop — daily 13:00 UTC proof-of-life (Phase 20 Task 7 · ALERT-09).

Posts a single ``[HEARTBEAT]`` Discord embed daily so silence != healthy.
``get_state_callable`` is provided by main.py wiring so the loop stays
decoupled from engine internals.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from backend.app.engine.digest_loop import _seconds_until_next_dispatch

if TYPE_CHECKING:
    from backend.app.services.alert_dispatch import Channel

logger = logging.getLogger(__name__)


async def heartbeat_loop(
    discord_channel: "Channel",
    stop_event: asyncio.Event,
    get_state_callable: Callable[[], dict[str, Any]],
    hour_utc: int = 13,
) -> None:
    """Daily 13:00 UTC heartbeat post; cooperative shutdown via ``stop_event``."""
    logger.info("heartbeat_loop.started", extra={"hour_utc": hour_utc})
    try:
        while not stop_event.is_set():
            wait_s = _seconds_until_next_dispatch(datetime.now(UTC), hour_utc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_s)
                return
            except TimeoutError:
                pass
            try:
                await _run_one(discord_channel, get_state_callable)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "heartbeat_loop.iter_failed", extra={"error": str(exc)}
                )
    except asyncio.CancelledError:
        logger.info("heartbeat_loop.stopped")
        raise


async def _run_one(
    discord_channel: "Channel",
    get_state_callable: Callable[[], dict[str, Any]],
) -> None:
    """One heartbeat iteration: build payload + post."""
    from backend.app.services.alert_service import AlertSeverity

    state = get_state_callable() or {}
    detail = {
        "ts": datetime.now(UTC).isoformat(),
        "uptime_h": state.get("uptime_h"),
        "v52_streams_active": state.get("v52_streams_active"),
        "last_critical_at": state.get("last_critical_at"),
        "message": "[HEARTBEAT] tv-engine alive",
    }
    ok = await discord_channel.send(
        severity=AlertSeverity.INFO, kind="heartbeat", detail=detail
    )
    if ok:
        logger.info("heartbeat_loop.dispatched")
    else:
        logger.warning("heartbeat_loop.dispatch_failed")


__all__ = ["heartbeat_loop", "_run_one"]
