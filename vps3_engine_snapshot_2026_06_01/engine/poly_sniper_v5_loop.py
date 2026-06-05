"""Phase 35-12 Task 2 — Offset-anchored fire scheduler (RAIL-35-OFFSET-FIRE-01).

Parallel to ``poly_updown_loop``: NOT a reuse of the bar-boundary dispatch
mechanism. Per the spec §1, each sniper-v5 sleeve fires at the offsets
declared in its ``SniperV5Sleeve.offsets`` tuple. ``fire_us`` is computed
deterministically as ``slot.slot_start_us + offset_s * 1_000_000``.

Architecture:

    1. Slot discovery (``_slot_discovery_loop``): every ``SLOT_DISCOVERY_TICK_S``
       (5.0s), polls the injected ``slot_observer()`` callable for the current
       set of active slots.
    2. For each NEW slot (deduped via ``seen_slot_keys``) AND for each sleeve
       where ``sleeve.asset == slot.asset AND sleeve.tf == slot.tf AND
       sleeve.sleeve_id not in kill_set``, schedule one ``_fire_at_offset``
       task per offset in ``sleeve.offsets``.
    3. ``_fire_at_offset``: sleeps until wall-clock reaches ``fire_us``, then
       calls ``controller.eval_sleeve_fire(sleeve, slot, offset_s, fire_us)``.
       If the controller returns any placed FireResult (``all_gates_passed
       AND fill_vwap is not None``), spawns one ``_resolve_at_slot_end`` task
       per placed direction.
    4. ``_resolve_at_slot_end``: sleeps until ``slot.slot_end_us +
       RESOLUTION_BUFFER_S`` (60s default), then awaits
       ``oracle_resolve(condition_id)`` and calls
       ``controller.book_event_for_resolution``.

Why offset-anchored (not bar-boundary):
    The 16 sniper-v5 sleeves fire at 0/30/60/90/120/150/180/240/480/600/720/840
    seconds INTO each slot — not at slot_start. This is by design: the spec §1
    table shows each sleeve has its own latency target driven by the gate
    library it consumes. A 1s sleeve (sleeve 06 at offset=30s) wants to read
    panels that have ingested 30 1s bars; a 1m sleeve (sleeve 01 at offset=30s)
    wants the BookMirror to have warmed up its L25 mirror. Bar-boundary
    dispatch can't express this — hence the dedicated scheduler.

CLAUDE.md inv #4: gates fire pre-signal; controller (Plan 35-12 Task 1)
enforces this — the loop is just dispatch glue.
CLAUDE.md inv #11+#12: NEVER calls trader_writes (controller is paper-only).
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from backend.app.controllers.polymarket_sniper_v5 import SlotInfo
from backend.app.strategies.polymarket.sniper_v5_sleeves import (
    SNIPER_V5_SLEEVES,
    SniperV5Sleeve,
)

log = structlog.get_logger("backend.app.engine.poly_sniper_v5_loop")


# Slot discovery tick — how often the loop polls slot_observer.
SLOT_DISCOVERY_TICK_S = 5.0
# How long past slot_end_us to wait before reading the oracle.
# UMA settles markets ~30-60s after slot_end on average.
RESOLUTION_BUFFER_S = 60


async def poly_sniper_v5_loop(
    controller: Any,                          # PolymarketSniperV5Controller
    slot_observer: Callable[[], Awaitable[list[SlotInfo]]],
    oracle_resolve: Callable[[str], Awaitable[str | None]] | None,
    kill_set: frozenset[str],
    stop_event: asyncio.Event,
) -> None:
    """Main loop — drives slot discovery + offset-anchored fire dispatch.

    Phase 35.1 (2026-05-27): ``slot_observer`` is now an async callable. The
    prior sync signature couldn't accommodate the gamma-based discovery path
    (gamma_client.get_active_slug_for_window is async). Existing tests that
    pass sync observers are updated in lockstep.
    """
    seen_slot_keys: set[tuple[str, str, str, int]] = set()
    pending_tasks: list[asyncio.Task[None]] = []
    log.info(
        "poly_sniper_v5.loop_started",
        n_sleeves=len(SNIPER_V5_SLEEVES),
        kill_size=len(kill_set),
    )
    try:
        while not stop_event.is_set():
            try:
                slots = await slot_observer()
            except Exception as exc:  # noqa: BLE001 — observer failures isolated
                log.error(
                    "poly_sniper_v5.slot_observer_failed", error=str(exc),
                )
                slots = []
            for slot in slots:
                key = (slot.slug, slot.asset, slot.tf, slot.slot_start_us)
                if key in seen_slot_keys:
                    continue
                seen_slot_keys.add(key)
                for sleeve in SNIPER_V5_SLEEVES:
                    if sleeve.sleeve_id in kill_set:
                        continue
                    if sleeve.asset != slot.asset or sleeve.tf != slot.tf:
                        continue
                    for offset_s in sleeve.offsets:
                        task = asyncio.create_task(
                            _fire_at_offset(
                                controller, slot, sleeve, offset_s,
                                oracle_resolve,
                            ),
                            name=f"sniper_v5.fire.{sleeve.sleeve_id}."
                                 f"{slot.slug}.{offset_s}",
                        )
                        pending_tasks.append(task)
            # GC completed tasks so the list doesn't grow unboundedly.
            pending_tasks = [t for t in pending_tasks if not t.done()]
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=SLOT_DISCOVERY_TICK_S,
                )
            except TimeoutError:
                pass
    finally:
        # Cancel pending fire tasks on shutdown.
        for t in pending_tasks:
            if not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
        log.info(
            "poly_sniper_v5.loop_stopped",
            n_completed=sum(1 for t in pending_tasks if t.done()),
        )


async def _fire_at_offset(
    controller: Any,
    slot: SlotInfo,
    sleeve: SniperV5Sleeve,
    offset_s: int,
    oracle_resolve: Callable[[str], Awaitable[str | None]] | None,
) -> None:
    """Sleep until fire_us, then evaluate + (if all-pass) schedule resolution."""
    fire_us = slot.slot_start_us + offset_s * 1_000_000
    now_us = int(time.time() * 1_000_000)
    delay_s = (fire_us - now_us) / 1_000_000
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
    try:
        results = await controller.eval_sleeve_fire(
            sleeve, slot, offset_s, fire_us,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error(
            "poly_sniper_v5.eval_failed",
            sleeve_id=sleeve.sleeve_id, slug=slot.slug, offset_s=offset_s,
            error=str(exc),
        )
        return
    for fr in results:
        if fr.all_gates_passed and fr.fill_vwap is not None:
            # HEDGE_LATE sleeves run a mid-slot underwater check before the
            # normal resolution; all others go straight to slot-end resolve.
            exit_policy = getattr(sleeve, "exit_policy", "HOLD")
            if exit_policy == "HEDGE_LATE":
                asyncio.create_task(
                    _hedge_late_then_resolve(
                        controller, sleeve, slot, fr, oracle_resolve,
                    ),
                    name=f"sniper_v5.hedge.{sleeve.sleeve_id}."
                         f"{slot.slug}.{offset_s}.{fr.direction}",
                )
            elif exit_policy == "LAG_REVERSAL_STOP":
                asyncio.create_task(
                    _reversal_stop_then_resolve(
                        controller, sleeve, slot, fr, oracle_resolve,
                    ),
                    name=f"sniper_v5.revstop.{sleeve.sleeve_id}."
                         f"{slot.slug}.{offset_s}.{fr.direction}",
                )
            else:
                asyncio.create_task(
                    _resolve_at_slot_end(
                        controller, sleeve, slot, fr, oracle_resolve,
                    ),
                    name=f"sniper_v5.resolve.{sleeve.sleeve_id}."
                         f"{slot.slug}.{offset_s}.{fr.direction}",
                )


async def _resolve_at_slot_end(
    controller: Any,
    sleeve: SniperV5Sleeve,
    slot: SlotInfo,
    fr: Any,                  # FireResult
    oracle_resolve: Callable[[str], Awaitable[str | None]] | None,
) -> None:
    """Sleep until slot_end + buffer, then await oracle + emit resolution."""
    slot_end_us = _slot_end_us(slot)
    now_us = int(time.time() * 1_000_000)
    delay_s = (slot_end_us - now_us) / 1_000_000 + RESOLUTION_BUFFER_S
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
    outcome: str | None = None
    if oracle_resolve is not None:
        try:
            # oracle_resolve is async — directly await. NEVER wrap the call
            # with the cross-thread asyncio bridge primitive whose ``.result()``
            # deadlocks when invoked inside the same event loop (CONTEXT.md
            # WARNING 7).
            outcome = await oracle_resolve(slot.condition_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "poly_sniper_v5.resolve_failed",
                slug=slot.slug,
                condition_id=slot.condition_id,
                error=str(exc),
            )
    await controller.book_event_for_resolution(
        sleeve, slot, fr, slot_end_us, outcome,
    )


async def _hedge_late_then_resolve(
    controller: Any,
    sleeve: SniperV5Sleeve,
    slot: SlotInfo,
    fr: Any,                  # FireResult
    oracle_resolve: Callable[[str], Awaitable[str | None]] | None,
) -> None:
    """HEDGE_LATE: sleep to slot_end - lead_s, check book, conditionally cut.

    SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE_2026_05_27.md §4c. If the controller
    cuts the position early (deep underwater), no slot-end resolution is
    scheduled. Otherwise falls through to the identical-to-HOLD resolution.
    """
    window_s = 300 if slot.tf == "5m" else 900
    lead_s = getattr(sleeve, "hedge_late_check_lead_s", 60)
    check_us = slot.slot_start_us + (window_s - lead_s) * 1_000_000
    now_us = int(time.time() * 1_000_000)
    delay_s = (check_us - now_us) / 1_000_000
    if delay_s > 0:
        try:
            await asyncio.sleep(delay_s)
        except asyncio.CancelledError:
            return
    try:
        cut = await controller.maybe_hedge_late_cut(sleeve, slot, fr)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — degrade to normal resolution
        log.warning(
            "poly_sniper_v5.hedge_late_failed",
            sleeve_id=sleeve.sleeve_id, slug=slot.slug, error=str(exc),
        )
        cut = False
    if cut:
        return  # position closed early; no oracle resolution for this fire
    await _resolve_at_slot_end(controller, sleeve, slot, fr, oracle_resolve)


async def _reversal_stop_then_resolve(
    controller: Any,
    sleeve: SniperV5Sleeve,
    slot: SlotInfo,
    fr: Any,                  # FireResult
    oracle_resolve: Callable[[str], Awaitable[str | None]] | None,
) -> None:
    """LAG_REVERSAL_STOP: poll for a binance reversal until slot_end.

    TV_AGENT_SPEC_FAST_TAKER_LAGV2 §3.2. Every ``reversal_poll_s`` seconds calls
    ``controller.maybe_reversal_stop``; if it cuts (binance reversed >=
    reversal_stop_bps vs the entry direction) no slot-end resolution is
    scheduled. Otherwise falls through to the normal oracle resolution.
    """
    poll_s = max(1, int(getattr(sleeve, "reversal_poll_s", 5)))
    slot_end_us = _slot_end_us(slot)
    while True:
        now_us = int(time.time() * 1_000_000)
        if now_us >= slot_end_us:
            break
        try:
            await asyncio.sleep(poll_s)
        except asyncio.CancelledError:
            return
        try:
            cut = await controller.maybe_reversal_stop(sleeve, slot, fr)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — degrade to normal resolution
            log.warning(
                "poly_sniper_v5.reversal_stop_failed",
                sleeve_id=sleeve.sleeve_id, slug=slot.slug, error=str(exc),
            )
            cut = False
        if cut:
            return  # position closed early; no oracle resolution for this fire
    await _resolve_at_slot_end(controller, sleeve, slot, fr, oracle_resolve)


def _slot_end_us(slot: SlotInfo) -> int:
    """slot_end_us = slot_start_us + window_seconds * 1e6 (300s for 5m, 900s for 15m)."""
    window_s = 300 if slot.tf == "5m" else 900
    return slot.slot_start_us + window_s * 1_000_000


__all__ = [
    "RESOLUTION_BUFFER_S",
    "SLOT_DISCOVERY_TICK_S",
    "_fire_at_offset",
    "_hedge_late_then_resolve",
    "_reversal_stop_then_resolve",
    "_resolve_at_slot_end",
    "poly_sniper_v5_loop",
]
