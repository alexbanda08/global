"""kalshi_loop — per-15m-window offset-anchored fire scheduler (Phase 36-06).

Mirrors poly_sniper_v5_loop:

  1. Discovery tick every WINDOW_TICK_S (30s): compute the current 15m
     window's ``window_start_us`` from wall-clock, dedupe via
     ``seen_window_keys``, discover the active market for each sleeve,
     schedule one ``_fire_at_offset`` task per sleeve offset.
  2. _fire_at_offset: sleep until window_start_us + offset_s * 1e6,
     call controller.eval_and_fire, then (if placed) schedule
     _resolve_after_window for the sleeve.
  3. _resolve_after_window: sleep until window_end_us + RESOLUTION_BUFFER_S,
     call controller.resolve(sleeve, ticker).

OPS-02 boundary guard: offset=600 is naturally mid-window (600s into 900s
window), well clear of ±60s. The guard is kept for future sleeves.

CLAUDE.md inv #5: rails fire BEFORE signal — enforced in controller.
CLAUDE.md inv #13: ZERO Storedata dependency — controller + client own data.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
import math
from typing import Any

import structlog

log = structlog.get_logger("backend.app.engine.kalshi_loop")

# Tick period for the discovery poll.
WINDOW_TICK_S: float = 30.0
# How far past window-end to wait before reading Kalshi result.
RESOLUTION_BUFFER_S: float = 60.0
# Window length for Kalshi 15m markets (seconds).
WINDOW_DURATION_S: int = 900

# OPS-02: refuse to fire within ±60s of the 15m boundary.
_BOUNDARY_GUARD_S: int = 60


def _window_start_us(now_us: int | None = None) -> int:
    """Return the current 15m window start as microseconds.

    Windows align to 15m UTC boundaries (900s epoch multiples).
    """
    if now_us is None:
        now_us = int(time.time() * 1_000_000)
    now_s = now_us // 1_000_000
    boundary_s = (now_s // WINDOW_DURATION_S) * WINDOW_DURATION_S
    return boundary_s * 1_000_000


def _boundary_guard_ok(window_start_us: int, offset_s: int) -> bool:
    """Return True if fire time is ≥ 60s from either window boundary (OPS-02).

    For offset=600 in a 900s window: fire at +600, boundary at 0 and 900.
    Both checks: 600 >= 60 AND (900-600) >= 60 → True.
    """
    fire_offset_s = offset_s
    if fire_offset_s < _BOUNDARY_GUARD_S:
        return False
    if (WINDOW_DURATION_S - fire_offset_s) < _BOUNDARY_GUARD_S:
        return False
    return True


async def kalshi_loop(
    controller: Any,                    # KalshiUpdownController
    sleeves: tuple[Any, ...],           # Tuple[SniperV5Sleeve]
    stop_event: asyncio.Event,
) -> None:
    """Main scheduler loop — drives window discovery + offset-anchored fire.

    For each new 15m window, schedules one _fire_at_offset task per
    (sleeve, offset). Dedupes via seen_window_keys (window_start_us per
    sleeve_id). Cancels all pending tasks on stop_event.
    """
    # seen_window_keys: (sleeve_id, window_start_us) → True
    seen_window_keys: set[tuple[str, int]] = set()
    pending_tasks: list[asyncio.Task[None]] = []

    log.info(
        "kalshi_loop.started",
        n_sleeves=len(sleeves),
    )

    try:
        while not stop_event.is_set():
            window_start_us = _window_start_us()

            for sleeve in sleeves:
                for offset_s in sleeve.offsets:
                    key = (sleeve.sleeve_id, window_start_us, offset_s)
                    if key in seen_window_keys:
                        continue
                    # OPS-02 guard.
                    if not _boundary_guard_ok(window_start_us, offset_s):
                        log.warning(
                            "kalshi_loop.boundary_guard_skip",
                            sleeve_id=sleeve.sleeve_id,
                            offset_s=offset_s,
                        )
                        seen_window_keys.add(key)
                        continue
                    seen_window_keys.add(key)
                    task = asyncio.create_task(
                        _fire_at_offset(
                            controller, sleeve, window_start_us, offset_s,
                        ),
                        name=f"kalshi.fire.{sleeve.sleeve_id}.{window_start_us}.{offset_s}",
                    )
                    pending_tasks.append(task)

                # S4 "Poly edge, Kalshi fill": for the ALL/S4 fan-out sleeve,
                # sample the Polymarket pre-window signal for the UPCOMING window
                # at (next_start − 120s) — when the Poly book reflects the
                # pre-window edge Kalshi can't see. _fire_at_offset then executes
                # the cached decision on Kalshi in-window. Only when a Poly
                # pre-window fn is wired into the controller.
                if (
                    str(getattr(sleeve, "asset", "")).upper() == "ALL"
                    and getattr(controller, "_poly_prewindow_ctx_fn", None) is not None
                ):
                    next_start_us = window_start_us + WINDOW_DURATION_S * 1_000_000
                    skey = (f"{sleeve.sleeve_id}:s4sample", next_start_us)
                    if skey not in seen_window_keys:
                        seen_window_keys.add(skey)
                        pending_tasks.append(
                            asyncio.create_task(
                                _sample_prewindow(controller, sleeve, next_start_us),
                                name=f"kalshi.s4sample.{sleeve.sleeve_id}.{next_start_us}",
                            )
                        )

            # GC completed tasks.
            pending_tasks = [t for t in pending_tasks if not t.done()]

            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=WINDOW_TICK_S,
                )
            except asyncio.TimeoutError:
                pass

    finally:
        for t in pending_tasks:
            if not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
        log.info(
            "kalshi_loop.stopped",
            n_pending_cancelled=sum(1 for t in pending_tasks if t.done()),
        )


# Maximum lateness (seconds) tolerated before treating a fire as stale.
# If now is more than this many seconds past fire_us, skip the fire entirely.
_STALE_FIRE_SLACK_S: float = 5.0

# Closing-boundary threshold (microseconds from window start).
# If now >= window_start + (WINDOW_DURATION_S - _BOUNDARY_GUARD_S) seconds
# we are inside the tail boundary guard — fire is stale.
_CLOSING_BOUNDARY_US: int = (WINDOW_DURATION_S - _BOUNDARY_GUARD_S) * 1_000_000


async def _sample_prewindow(
    controller: Any,
    sleeve: Any,                  # SniperV5Sleeve (ALL/S4 fan-out)
    next_window_start_us: int,
) -> None:
    """Sleep until (next_window_start − 120s), then sample the Poly pre-window
    S4 signal for the upcoming slot (controller caches UP/DOWN decisions for
    in-window Kalshi execution). Best-effort: never raises into the loop."""
    sample_us = next_window_start_us - 120 * 1_000_000
    now_us = int(time.time() * 1_000_000)
    delay_s = (sample_us - now_us) / 1_000_000
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
    elif delay_s < -float(WINDOW_DURATION_S):
        return  # far too late (loop stalled) — skip this sample
    slot_start_unix_s = int(next_window_start_us // 1_000_000)
    try:
        await controller.sample_s4_prewindow(sleeve, slot_start_unix_s)
    except Exception as exc:  # noqa: BLE001 — sample must not break the loop
        log.warning(
            "kalshi_loop.s4_sample_failed",
            sleeve_id=sleeve.sleeve_id, error=str(exc),
        )


async def _fire_at_offset(
    controller: Any,
    sleeve: Any,            # SniperV5Sleeve
    window_start_us: int,
    offset_s: int,
) -> None:
    """Sleep until fire_us, then eval_and_fire; on placed result schedule resolve.

    Fire-time staleness guard (WR-05): re-checks wall-clock at actual fire time.
    If the event loop was stalled and the fire moment is already past the closing
    boundary guard OR past fire_us by more than _STALE_FIRE_SLACK_S, the fire is
    skipped and kalshi_loop.fire_stale_skip is logged instead of firing. This
    ensures the OPS-02 boundary protection applies even when discovery ran late.
    """
    fire_us = window_start_us + offset_s * 1_000_000
    now_us = int(time.time() * 1_000_000)
    delay_s = (fire_us - now_us) / 1_000_000
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return

    # Re-check wall clock at actual fire time (event loop may have been stalled).
    now_us = int(time.time() * 1_000_000)
    in_closing_boundary = now_us >= window_start_us + _CLOSING_BOUNDARY_US
    too_late = now_us > fire_us + int(_STALE_FIRE_SLACK_S * 1_000_000)
    if in_closing_boundary or too_late:
        log.warning(
            "kalshi_loop.fire_stale_skip",
            sleeve_id=sleeve.sleeve_id,
            offset_s=offset_s,
            late_ms=round((now_us - fire_us) / 1_000, 1),
            in_closing_boundary=in_closing_boundary,
            too_late=too_late,
        )
        return

    try:
        # ALL fan-out sleeve (Poly ALL_*_S4_prewindow model) fires the same rule
        # across BTC/ETH/SOL and returns one result per symbol; fixed-series
        # sleeves return a single result.
        if str(getattr(sleeve, "asset", "")).upper() == "ALL":
            fire_results = await controller.eval_and_fire_all(sleeve, fire_us)
        else:
            fire_results = [await controller.eval_and_fire(sleeve, fire_us)]
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error(
            "kalshi_loop.eval_and_fire_failed",
            sleeve_id=sleeve.sleeve_id,
            offset_s=offset_s,
            error=str(exc),
        )
        return

    # Schedule resolution per placed fire (ticker known + order exists). The ALL
    # sleeve may place on multiple symbols → one resolve task per ticker.
    # HEDGE_LATE sleeves run a mid-window underwater check before resolution.
    hedge_late = str(getattr(sleeve, "exit_policy", "HOLD")) == "HEDGE_LATE"
    for fire_result in fire_results:
        if (
            fire_result is not None
            and fire_result.all_gates_passed
            and fire_result.ticker is not None
            and fire_result.order_result is not None
        ):
            if hedge_late:
                asyncio.create_task(
                    _hedge_late_then_resolve(
                        controller, sleeve, fire_result, window_start_us,
                    ),
                    name=f"kalshi.hedge.{sleeve.sleeve_id}."
                         f"{fire_result.ticker}.{window_start_us}",
                )
            else:
                asyncio.create_task(
                    _resolve_after_window(
                        controller, sleeve, fire_result.ticker, window_start_us,
                    ),
                    name=f"kalshi.resolve.{sleeve.sleeve_id}."
                         f"{fire_result.ticker}.{window_start_us}",
                )


async def _hedge_late_then_resolve(
    controller: Any,
    sleeve: Any,
    fire_result: Any,
    window_start_us: int,
) -> None:
    """HEDGE_LATE (_H sleeve): sleep to window_end - lead_s, check the held book,
    conditionally cut. If the controller cuts the position early (deep
    underwater), no settle-resolution is scheduled; otherwise fall through to
    the identical-to-HOLD resolution. Mirrors poly _hedge_late_then_resolve.
    """
    lead_s = int(getattr(sleeve, "hedge_late_check_lead_s", 60))
    check_us = window_start_us + (WINDOW_DURATION_S - lead_s) * 1_000_000
    now_us = int(time.time() * 1_000_000)
    delay_s = (check_us - now_us) / 1_000_000
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
    try:
        cut = await controller.maybe_hedge_late_cut(sleeve, fire_result)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — degrade to normal resolution
        log.warning(
            "kalshi_loop.hedge_late_failed",
            sleeve_id=sleeve.sleeve_id, error=str(exc),
        )
        cut = False
    if cut:
        return  # position closed early; no settle-resolution for this fire
    await _resolve_after_window(
        controller, sleeve, fire_result.ticker, window_start_us,
    )


async def _resolve_after_window(
    controller: Any,
    sleeve: Any,
    ticker: str,
    window_start_us: int,
) -> None:
    """Sleep until window_end + buffer, then resolve via controller.resolve."""
    window_end_us = window_start_us + WINDOW_DURATION_S * 1_000_000
    now_us = int(time.time() * 1_000_000)
    delay_s = (window_end_us - now_us) / 1_000_000 + RESOLUTION_BUFFER_S
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return

    try:
        await controller.resolve(sleeve, ticker)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error(
            "kalshi_loop.resolve_failed",
            sleeve_id=sleeve.sleeve_id,
            ticker=ticker,
            error=str(exc),
        )


__all__ = [
    "RESOLUTION_BUFFER_S",
    "WINDOW_TICK_S",
    "kalshi_loop",
]
