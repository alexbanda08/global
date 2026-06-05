"""Phase 30 Plan 30-10 — `poly_maker_loop`: event-driven maker-arb dispatcher.

The orchestrator that wires together Phase 30's components from Plans
30-02 through 30-09:

  * Subscribes to ``BookMirror`` (poll-snapshot) + ``TradeMirror`` (callback)
    to feed L25Update + TradePrint events to enabled (strategy, cell) tuples.
  * Discovers active slugs per cell via ``gamma_client.get_active_slug_for_window``
    (D-15 — gamma is the canonical source for live mode; the sibling-DB
    fallback Phase 27 retired is forbidden here).
  * Polls ``onchain_oracle.get_resolution`` per active slug; emits
    ``SlugResolved`` when winner is set; unsubscribes from book + trade mirrors.
  * Per-(strategy, cell) circuit breaker (D-06): 5 errors in 5 minutes
    flips the tuple into ``_disabled`` and emits a critical alert
    (kind=``poly_maker_auto_disabled``). Disabled tuples ignore further
    events until an env-var flip + ``systemctl restart`` (CLAUDE inv #11).
  * Env-kill parser (D-07): ``TV_POLY_MAKER_KILL=acc_h:btc_5m,mas:sol_5m``
    yields a ``set[StratCell]`` consulted BEFORE every dispatch.
  * Per-cell 5s merge-check timer re-fires the latest cached L25 to trigger
    MERGE evaluation continuously (paired-inventory drain).
  * Per-cell 5s ``maker_state`` ``notify_event`` (D-14) pushes sleeve state
    to ``/ws/terminal`` via the existing Phase 17.1 EventBus path; payload
    is < 1500 bytes per sleeve (Pitfall 6 bound).
  * Decision routing:
      - Shadow mode (Phase 30 default): EVERY Decision → ``AsyncShadowLogger``.
      - LIVE mode (Phase 30.1): MERGE → ``poly_merger.merge_pairs``; MAS MINT
        → ``LiveOnChainExecutor.split_position`` + synthetic ``OrderFill``;
        POST_BID/POST_ASK/CANCEL/TAKE/REDEEM raise ``NotImplementedError``
        (Phase 30.1 wires CLOB submission + redeem).

Threat-model closure (30-10 plan):
  * T-30-10:      ``_disabled`` checked BEFORE every dispatch path.
  * T-30-10-01:   ``_parse_kill_env`` regex-validates each token; malformed
                  tokens logged + skipped.
  * T-30-10-02:   ``maker_state`` payload schema is fixed; no private_key /
                  secret-shaped fields. structlog redaction processor still
                  catches stray leaks.
  * T-30-10-03:   No FastAPI endpoint exposes re-enable; only env-var flip.
  * T-30-10-04:   ``gamma_client`` failures isolated — logged + retried
                  next tick; do NOT trip ``_record_error`` (per-strategy
                  circuit breaker).
  * T-30-10-05:   ``condition_id`` sourced from gamma, passed through
                  SlugActive; merge_pairs reads via state, not the
                  sibling-DB schema retired in Phase 27.
  * T-30-10-06:   TradePrint dispatched only from TradeMirror; strategies
                  use for rule eval only.
  * T-30-10-07:   Every Decision carries ``strategy`` field; per-strategy
                  shadow_log file enforces repudiation-resistance.

CLAUDE.md invariants:
  * #4 (closed-bar discipline): L25 snapshots from BookMirror are already
    closed snapshots; this loop never sees raw frames.
  * #7 (no agent-callable kill): No tool exposed; ``_disabled`` is module-
    level state mutated only by ``_record_error``.
  * #10 (secrets never logged): ``private_key`` passed as kwarg, never
    logged. structlog redaction processor applied globally.
  * #11 (no agent-callable re-enable): Once disabled, only env-flip +
    systemctl restart re-enables a (strategy, cell).
  * #13 (TV-native data): gamma_client is canonical; the sibling-DB
    schema retired in Phase 27 is forbidden here.

This module DOES NOT modify ``engine/main.py``. Plan 30-11 wires the
spawn gate.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from collections import deque
from decimal import Decimal
from time import monotonic, time
from typing import TYPE_CHECKING, Any, NamedTuple

import structlog

from backend.app.engine.notify import notify_event
from backend.app.strategies.polymarket.maker.types import (
    Decision,
    L25Update,
    OrderFill,
    SlugActive,
    SlugResolved,
    TradePrint,
)
from backend.app.venues.polymarket.onchain_oracle import ResolutionOutcome

if TYPE_CHECKING:
    import asyncpg

    from backend.app.core.config import Settings
    from backend.app.engine.poly_maker_fill_sim import MakerFillSimulator
    from backend.app.services.alert_service import AlertService
    from backend.app.strategies.polymarket.maker.base import MakerStrategyBase
    from backend.app.strategies.polymarket.maker.shadow_log import (
        AsyncShadowLogger,
    )
    from backend.app.venues.polymarket.book_mirror import BookMirror
    from backend.app.venues.polymarket.gamma_client import GammaClient
    from backend.app.venues.polymarket.onchain_oracle import OnchainOracle
    from backend.app.venues.polymarket.trade_mirror import TradeMirror

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level types + state
# ---------------------------------------------------------------------------


class StratCell(NamedTuple):
    """A (strategy_code, cell) tuple — the granularity of kill / disable / log.

    ``strategy`` is the lowercase form ('acc_m' / 'acc_h' / 'mas'); ``cell``
    is the lowercase asset_tf form ('btc_15m' / 'btc_5m' / 'eth_5m' /
    'eth_15m' / 'sol_5m' / 'sol_15m').
    """

    strategy: str
    cell: str


# Circuit-breaker module-level state. Reset per process. Tests reset via
# ``_disabled.clear()`` + ``_error_windows.clear()`` between cases.
_error_windows: dict[StratCell, deque[float]] = {}
_disabled: set[StratCell] = set()

# Sub-loop tick cadences (sourced from settings at call time; module-level
# defaults exist for tests that don't fully construct a Settings stub).
_SLUG_DISCOVERY_TICK_S = 30.0
# E14 (ENGINE_BUG_MAP_2026_05_28): 60s → 20s so a slug's mark clears within
# ~20s of on-chain resolution (was up to 60s stale). Env-tunable via
# TV_POLY_MAKER_SLUG_RESOLUTION_TICK_S; kept >10s to bound oracle RPC rate.
_SLUG_RESOLUTION_TICK_S = 20.0
_BOOK_POLL_TICK_S = 0.1  # 10 Hz, mirrors poly_mint_sell_v2/book_subscriber

# Env-kill token regex — `^[a-z_]+:[a-z0-9_]+$`. Permissive enough to admit
# arbitrary cell suffixes (e.g. 'btc_5m', 'eth_15m') without enumerating
# every legal value at this layer.
_KILL_TOKEN_RE = re.compile(r"^[a-z_]+:[a-z0-9_]+$")


# ---------------------------------------------------------------------------
# Public parser + helpers
# ---------------------------------------------------------------------------


def _parse_kill_env(raw: str) -> set[StratCell]:
    """Parse ``TV_POLY_MAKER_KILL`` into a set of (strategy, cell) tuples.

    Format: ``acc_h:btc_5m,mas:sol_5m``. Comma-separated entries. Each entry
    must match ``^[a-z_]+:[a-z0-9_]+$`` (lowercase, underscores allowed).
    Malformed entries are logged with a warning and skipped — the loop
    NEVER crashes on a typo in the env var.

    Empty input → empty set.
    """
    if not raw:
        return set()

    out: set[StratCell] = set()
    for raw_token in raw.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if not _KILL_TOKEN_RE.match(token):
            log.warning("poly_maker_loop.kill_token_malformed", token=token)
            continue
        strategy, cell = token.split(":", 1)
        out.add(StratCell(strategy=strategy, cell=cell))
    return out


def _sleeve_id(strategy_code: str, asset: str, tf: str) -> str:
    """Build the canonical sleeve_id for a maker-arb sleeve.

    Format: ``poly_<strategy>_<asset>_<tf>_shadow`` (Phase 30 — shadow only).
    Phase 30.1 live promotion will swap ``_shadow`` → ``_live`` via a
    parallel ``_sleeve_id_live`` helper.

    >>> _sleeve_id("acc_m", "BTC", "15m")
    'poly_acc_m_btc_15m_shadow'
    """
    return (
        f"poly_{strategy_code.lower().replace('-', '_')}"
        f"_{asset.lower()}_{tf}_shadow"
    )


def _record_error(
    sc: StratCell,
    alerts: "AlertService | None",
    settings: "Settings | Any",
) -> bool:
    """Record one error against (strategy, cell); flip to ``_disabled`` at threshold.

    Sliding-window count: ``settings.tv_poly_maker_auto_disable_threshold``
    errors within ``settings.tv_poly_maker_auto_disable_window_s`` seconds.
    On crossing the threshold, the (strategy, cell) is added to ``_disabled``
    and a critical alert (``kind="poly_maker_auto_disabled"``) is scheduled
    (fire-and-forget — we don't await here so callers can use this from
    sync code paths).

    Returns:
        ``True`` if this call caused the (strategy, cell) to be disabled,
        ``False`` otherwise.
    """
    threshold = int(getattr(settings, "tv_poly_maker_auto_disable_threshold", 5))
    window_s = float(getattr(settings, "tv_poly_maker_auto_disable_window_s", 300.0))

    now = monotonic()
    window = _error_windows.setdefault(sc, deque())
    window.append(now)
    while window and now - window[0] > window_s:
        window.popleft()

    if sc in _disabled:
        return False

    if len(window) >= threshold:
        _disabled.add(sc)
        log.error(
            "poly_maker_loop.auto_disabled",
            strategy=sc.strategy,
            cell=sc.cell,
            errors_in_window=len(window),
            window_s=window_s,
        )
        if alerts is not None:
            # Fire-and-forget — we may be called from a non-async context.
            # Schedule the alert on the running event loop if one exists;
            # otherwise log + skip (test contexts may not have a loop).
            with contextlib.suppress(Exception):
                from backend.app.services.alert_service import AlertSeverity
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    coro = alerts.emit(
                        severity=AlertSeverity.CRITICAL,
                        kind="poly_maker_auto_disabled",
                        strategy=sc.strategy,
                        cell=sc.cell,
                        errors_in_window=len(window),
                        window_s=window_s,
                    )
                    if asyncio.iscoroutine(coro):
                        loop.create_task(coro)
        return True
    return False


# ---------------------------------------------------------------------------
# Decision routing
# ---------------------------------------------------------------------------


async def _route_decision(
    *,
    decision: "Decision",
    strategy: "MakerStrategyBase",
    shadow_log: "AsyncShadowLogger",
    shadow_mode: bool,
    live_executor: Any,
    poly_merger_w3: Any,
    poly_merger_wallet: str | None,
    private_key: str | None,
    pool: "asyncpg.Pool",
    alerts: "AlertService | None",
    settings: "Settings | Any",
    sleeve_id: str,
    merge_pairs_fn: Any,
    fill_sim: "MakerFillSimulator | None" = None,  # Phase 32 Plan 32-10 (back-compat None default)
) -> None:
    """Route a single Decision: log to shadow_log, then (LIVE) execute.

    Shadow mode (Phase 30 default): only ``shadow_log.log(...)`` runs.
    LIVE mode (Phase 30.1):
      * MERGE → ``merge_pairs_fn(w3, private_key, wallet, condition_id, ...)``
      * MINT (MAS only) → ``live_executor.split_position(condition_id, amount)``
        + synthetic ``OrderFill`` dispatched to strategy.
      * POST_BID/POST_ASK/CANCEL/TAKE/REDEEM → ``NotImplementedError``
        (Phase 30.1 wires CLOB submission + redeem).

    Unknown actions: logged warning, no crash.
    """
    # 1. Always log to shadow_log (the decision record is the truth source).
    slug_state = strategy.slug_states.get(decision.slug) if hasattr(strategy, "slug_states") else None
    # Phase 32 — sim hook (Plan 32-10): observe BEFORE shadow_log.log so sim can
    # append a synthetic fill row immediately after on the same tick.
    if fill_sim is not None and not getattr(settings, "tv_poly_maker_sim_disabled", False):
        try:
            fill_sim.observe(decision=decision, strategy=strategy, slug_state=slug_state)
        except Exception:
            log.exception("poly_maker_fill_sim.observe_failed", sleeve_id=sleeve_id)
            _record_error(StratCell(strategy=decision.strategy.lower().replace("-", "_"), cell=f"{getattr(strategy, 'asset', '?').lower()}_{getattr(strategy, 'tf', '?')}"), alerts, settings)
        # D-CF-5: if sim emitted a fill this tick, push maker_state so the dashboard
        # TanStack Query cache invalidates within the next paint (Plan 32-10).
        if fill_sim.fill_emitted_this_tick():
            try:
                async with pool.acquire() as _conn:
                    await notify_event(_conn, kind="maker_state", payload={
                        "sleeve_id": sleeve_id,
                        "slug": decision.slug,
                        "fills": fill_sim.stats()["n_fills"],
                    })
            except Exception:
                log.exception("poly_maker_fill_sim.notify_event_failed", sleeve_id=sleeve_id)
    try:
        shadow_log.log(decision, sim_fill=False, slug_state=slug_state)
    except Exception:
        log.exception("poly_maker_loop.shadow_log_failed", sleeve_id=sleeve_id)

    if shadow_mode:
        # Phase 30 default — decisions logged, no execution.
        return

    # 2. LIVE mode — branch on action.
    action = decision.action
    if action == "MERGE":
        if private_key is None or poly_merger_w3 is None or poly_merger_wallet is None:
            log.warning(
                "poly_maker_loop.live_merge_missing_creds",
                sleeve_id=sleeve_id,
                slug=decision.slug,
            )
            return
        slug_state = strategy.slug_states.get(decision.slug)
        if slug_state is None:
            log.warning(
                "poly_maker_loop.live_merge_no_state",
                sleeve_id=sleeve_id,
                slug=decision.slug,
            )
            return
        try:
            await merge_pairs_fn(
                w3=poly_merger_w3,
                private_key=private_key,
                wallet=poly_merger_wallet,
                condition_id=slug_state.condition_id,
                pairs=decision.size,
                sleeve_id=sleeve_id,
                settings=settings,
                alert_service=alerts,
                pool=pool,
            )
        except Exception:
            log.exception(
                "poly_maker_loop.merge_pairs_failed",
                sleeve_id=sleeve_id,
                slug=decision.slug,
            )
        return

    if action == "MINT":
        # Phase 32: synthetic-fill block lifted from LIVE-only to unconditional.
        # When fill_sim IS wired (production), fill_sim._observe_mint already handled
        # the synthetic OrderFill dispatch via fill_sim.observe() above (Plan 32-07).
        # When fill_sim is absent (back-compat path: tests without fill_sim, or
        # tv_poly_maker_sim_disabled=true), we synthesize inline — same behavior as
        # the original Phase 30 code so existing tests stay green (T-32-10-03).
        sim_active = fill_sim is not None and not getattr(settings, "tv_poly_maker_sim_disabled", False)
        if not sim_active:
            # Back-compat: inline synthetic fill when sim is absent/disabled.
            synthetic_fill = OrderFill(
                slug=decision.slug,
                side="up",
                ts_us=decision.ts_us,
                order_id=f"MAS-MINT-{decision.slug}",
                price=Decimal("1.0"),
                size=decision.size or Decimal(0),
                is_maker=False,
            )
            try:
                strategy.on_order_fill(synthetic_fill)
            except Exception:
                log.exception(
                    "poly_maker_loop.synthetic_fill_dispatch_failed",
                    sleeve_id=sleeve_id,
                )

        # LIVE path: on-chain split_position (unchanged from Phase 30 — only
        # the synthetic-fill construction moved to the sim above).
        if live_executor is not None and private_key is not None:
            slug_state_mint = strategy.slug_states.get(decision.slug) if hasattr(strategy, "slug_states") else None
            if slug_state_mint is None:
                log.warning(
                    "poly_maker_loop.live_mint_no_state",
                    sleeve_id=sleeve_id,
                    slug=decision.slug,
                )
                return
            try:
                await live_executor.split_position(
                    slug_state_mint.condition_id, decision.size or Decimal(0)
                )
            except Exception:
                log.exception(
                    "poly_maker_loop.split_position_failed",
                    sleeve_id=sleeve_id,
                    slug=decision.slug,
                )
        return

    if action in ("POST_BID", "POST_ASK", "TAKE"):
        # Phase 30.1 wires CLOB submission via presigned_pool.lookup_by_price.
        log.warning(
            "poly_maker_loop.live_clob_not_yet_implemented",
            action=action,
            sleeve_id=sleeve_id,
        )
        raise NotImplementedError(
            f"Phase 30.1 wires CLOB submission for action={action}"
        )

    if action == "CANCEL":
        log.warning(
            "poly_maker_loop.live_cancel_not_yet_implemented",
            sleeve_id=sleeve_id,
        )
        raise NotImplementedError("Phase 30.1 wires CLOB cancellation")

    if action == "REDEEM":
        if live_executor is None:
            log.warning(
                "poly_maker_loop.live_redeem_missing_creds",
                sleeve_id=sleeve_id,
            )
            return
        slug_state = strategy.slug_states.get(decision.slug)
        if slug_state is None:
            return
        try:
            await live_executor.redeem_positions(slug_state.condition_id)
        except Exception:
            log.exception(
                "poly_maker_loop.redeem_failed",
                sleeve_id=sleeve_id,
                slug=decision.slug,
            )
        return

    # Unknown action — log + continue (do not crash).
    log.warning(
        "poly_maker_loop.unknown_action",
        action=action,
        sleeve_id=sleeve_id,
        slug=decision.slug,
    )


# ---------------------------------------------------------------------------
# Event dispatchers
# ---------------------------------------------------------------------------


async def _dispatch_l25(
    *,
    evt: "L25Update",
    strategies_for_cell: list["MakerStrategyBase"],
    cell_keys: list[tuple[str, str]],
    kill_set: set[StratCell],
    shadow_loggers: dict[str, "AsyncShadowLogger"],
    alerts: "AlertService | None",
    settings: "Settings | Any",
    shadow_mode: bool = True,
    live_executor: Any = None,
    poly_merger_w3: Any = None,
    poly_merger_wallet: str | None = None,
    private_key: str | None = None,
    pool: Any = None,
    merge_pairs_fn: Any = None,
    fill_sim: "MakerFillSimulator | None" = None,  # Phase 32 Plan 32-10
) -> None:
    """Dispatch one L25Update to all enabled strategies for the given cells.

    The caller passes parallel lists ``strategies_for_cell`` + ``cell_keys``
    (same length). For each enabled (strategy, cell) tuple — i.e. not in
    ``kill_set`` AND not in ``_disabled`` — the strategy's ``on_l25_update``
    is called; resulting Decisions are routed via ``_route_decision``.
    """
    for strat, cell_key in zip(strategies_for_cell, cell_keys, strict=True):
        sc = StratCell(strategy=cell_key[0], cell=cell_key[1])
        if sc in kill_set or sc in _disabled:
            continue
        try:
            decisions = strat.on_l25_update(evt)
        except Exception:
            log.exception(
                "poly_maker_loop.on_l25_update_failed",
                strategy=sc.strategy,
                cell=sc.cell,
                slug=evt.slug,
            )
            _record_error(sc, alerts, settings)
            continue
        sl = shadow_loggers.get(strat.code)
        if sl is None or not decisions:
            continue
        sleeve_id = _sleeve_id(strat.code, strat.asset, strat.tf)
        for decision in decisions:
            await _route_decision(
                decision=decision,
                strategy=strat,
                shadow_log=sl,
                shadow_mode=shadow_mode,
                live_executor=live_executor,
                poly_merger_w3=poly_merger_w3,
                poly_merger_wallet=poly_merger_wallet,
                private_key=private_key,
                pool=pool,
                alerts=alerts,
                settings=settings,
                sleeve_id=sleeve_id,
                merge_pairs_fn=merge_pairs_fn,
                fill_sim=fill_sim,
            )


async def _dispatch_trade_print(
    *,
    evt: "TradePrint",
    strategies_for_cell: list["MakerStrategyBase"],
    cell_keys: list[tuple[str, str]],
    kill_set: set[StratCell],
    shadow_loggers: dict[str, "AsyncShadowLogger"],
    alerts: "AlertService | None",
    settings: "Settings | Any",
    shadow_mode: bool = True,
    live_executor: Any = None,
    poly_merger_w3: Any = None,
    poly_merger_wallet: str | None = None,
    private_key: str | None = None,
    pool: Any = None,
    merge_pairs_fn: Any = None,
    fill_sim: "MakerFillSimulator | None" = None,  # Phase 32 Plan 32-10
) -> None:
    """Dispatch one TradePrint to AccH strategies only.

    ACC-M + MAS return ``[]`` from their ``on_trade_print`` overrides — but
    the dispatcher gates on ``strategy.code == 'ACC-H'`` so we avoid the
    cross-strategy noise of calling no-op methods on every trade tick.

    Phase 32 Plan 32-10 (Pitfall 3 Option A): sim consumes the TradePrint
    FIRST (sync, fast O(1) per-order queue decrement), THEN existing ACC-H
    dispatch fires — ensures fill detection is not starved by strategy logic.
    """
    # Phase 32 — sim consumes TradePrint inline BEFORE ACC-H dispatch (Pitfall 3 A6)
    if fill_sim is not None and not getattr(settings, "tv_poly_maker_sim_disabled", False):
        try:
            fill_sim.on_trade_print(evt)
        except Exception:
            log.exception(
                "poly_maker_fill_sim.on_trade_print_failed",
                slug=getattr(evt, "slug", "?"),
            )

    for strat, cell_key in zip(strategies_for_cell, cell_keys, strict=True):
        if getattr(strat, "code", "") != "ACC-H":
            continue
        sc = StratCell(strategy=cell_key[0], cell=cell_key[1])
        if sc in kill_set or sc in _disabled:
            continue
        try:
            decisions = strat.on_trade_print(evt)
        except Exception:
            log.exception(
                "poly_maker_loop.on_trade_print_failed",
                strategy=sc.strategy,
                cell=sc.cell,
                slug=evt.slug,
            )
            _record_error(sc, alerts, settings)
            continue
        sl = shadow_loggers.get(strat.code)
        if sl is None or not decisions:
            continue
        sleeve_id = _sleeve_id(strat.code, strat.asset, strat.tf)
        for decision in decisions:
            await _route_decision(
                decision=decision,
                strategy=strat,
                shadow_log=sl,
                shadow_mode=shadow_mode,
                live_executor=live_executor,
                poly_merger_w3=poly_merger_w3,
                poly_merger_wallet=poly_merger_wallet,
                private_key=private_key,
                pool=pool,
                alerts=alerts,
                settings=settings,
                sleeve_id=sleeve_id,
                merge_pairs_fn=merge_pairs_fn,
                fill_sim=fill_sim,
            )


async def _query_existing_mas_inventory(
    *,
    live_executor: Any,
    token_id_up: str,
    token_id_dn: str,
    slug: str,
    alerts: "AlertService | None",
) -> tuple[Decimal, Decimal] | None:
    """Probe ``CTF.balanceOf`` for both sides of an active slug.

    Used by ``_slug_discovery_tick`` to detect a prior-process MINT that
    survived an engine restart (the in-memory ``slug_states`` was lost
    but on-chain shares remain). When the probe returns non-zero on
    either side, the caller seeds the MAS strategy's state directly and
    SKIPS the MINT decision — preventing the LIVE-mode double-deploy
    documented in the 2026-05-20 vps_ireland incident.

    Returns:
        ``(inv_up, inv_dn)`` Decimal tuple on success — even when both
        are zero (caller treats zero as "fresh slug, MINT normally").
        ``None`` on transient RPC failure — caller falls back to the
        legacy MINT path and the helper fires a CRITICAL alert so the
        operator knows the safety net is down for this tick.
    """
    if live_executor is None:
        # Shadow mode without a live_executor — no chain client. Caller
        # falls back to the legacy MINT path (logging-only in shadow).
        return None
    probe = getattr(live_executor, "get_ctf_balance", None)
    if probe is None:
        return None
    try:
        inv_up = await probe(token_id_up)
        inv_dn = await probe(token_id_dn)
    except Exception as exc:
        log.warning(
            "poly_maker_loop.mas_chain_balance_probe_failed",
            slug=slug,
            error=str(exc)[:200],
        )
        if alerts is not None:
            with contextlib.suppress(Exception):
                from backend.app.services.alert_service import AlertSeverity
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    coro = alerts.emit(
                        severity=AlertSeverity.CRITICAL,
                        kind="poly_maker_mas_chain_probe_failed",
                        slug=slug,
                        error=str(exc)[:200],
                    )
                    if asyncio.iscoroutine(coro):
                        loop.create_task(coro)
        return None
    return inv_up, inv_dn


async def _slug_discovery_tick(
    *,
    cell_keys: list[tuple[str, str]],
    cell_asset_tf: dict[tuple[str, str], tuple[str, str]],
    strategies_for_cell: dict[tuple[str, str], list["MakerStrategyBase"]],
    active_slugs: dict[tuple[str, str], str | None],
    active_slug_meta: dict[str, dict[str, Any]],
    per_cell_seen_slugs: dict[tuple[str, str], str],
    gamma_client: "GammaClient",
    book_mirror: "BookMirror",
    trade_mirror: "TradeMirror",
    kill_set: set[StratCell],
    shadow_loggers: dict[str, "AsyncShadowLogger"],
    alerts: "AlertService | None",
    settings: "Settings | Any",
    fill_sim: "MakerFillSimulator | None" = None,  # Phase 32 Plan 32-10
    live_executor: Any = None,  # mas double-mint defense — chain balance probe
) -> None:
    """Per-cell tick: ask gamma for the active slug for this (asset, tf) window.

    On NEW slug:
      * Update ``active_slugs[(asset, tf)]`` to the new slug.
      * Record metadata in ``active_slug_meta[slug]`` (used by resolution loop).
      * Subscribe BookMirror + TradeMirror to both token_ids.
      * Emit ``SlugActive`` to enabled strategies for the cell.

    Gamma failures are isolated — logged + skipped; ``_record_error`` is
    NOT incremented (per-strategy circuit breaker stays clean across gamma
    outages, T-30-10-04).
    """
    for cell_key in cell_keys:
        asset, tf = cell_asset_tf[cell_key]
        try:
            spec = await gamma_client.get_active_slug_for_window(asset=asset, tf=tf)
        except Exception as exc:
            # Per T-30-10-04: gamma errors NEVER trip the strategy circuit
            # breaker — they're infrastructure-level and retried next tick.
            log.warning(
                "poly_maker_loop.gamma_error",
                cell=cell_key,
                asset=asset,
                tf=tf,
                error=str(exc)[:200],
            )
            continue
        if spec is None:
            continue

        slug = spec.get("slug")
        if not slug:
            continue
        # Phase 31 fix: dedup SlugActive per CELL_KEY (strategy+cell), NOT
        # per (asset, tf). Two strategies on the same cell each need their
        # own SlugActive event. Previously the active_slugs[(asset, tf)]
        # check locked out the second strategy (ACC-PC silenced by ACC-H
        # winning the btc_15m race). active_slugs itself remains keyed by
        # (asset, tf) — used by resolution loops downstream — but per-cell
        # dispatch uses per_cell_seen_slugs to track who's already gotten
        # SlugActive for this slug.
        if per_cell_seen_slugs.get(cell_key) == slug:
            continue
        per_cell_seen_slugs[cell_key] = slug

        # NEW slug for this cell — wire up. Skip the on-chain side-effects
        # (book/trade subscribes, active_slugs update, oracle wiring) if
        # this slug was already wired by a sibling strategy on the same
        # (asset, tf) — those side-effects must happen exactly ONCE per slug.
        already_wired = active_slugs.get((asset, tf)) == slug
        condition_id = spec["condition_id"]
        token_id_up = spec["token_id_up"]
        token_id_dn = spec["token_id_dn"]

        if not already_wired:
            active_slugs[(asset, tf)] = slug
        active_slug_meta[slug] = {
            "condition_id": condition_id,
            "token_id_up": token_id_up,
            "token_id_dn": token_id_dn,
            "asset": asset,
            "tf": tf,
        }

        with contextlib.suppress(Exception):
            await book_mirror.subscribe(token_id_up)
            await book_mirror.subscribe(token_id_dn)
        with contextlib.suppress(Exception):
            await trade_mirror.subscribe(token_id_up, slug=slug, side="up")
            await trade_mirror.subscribe(token_id_dn, slug=slug, side="dn")

        # Emit SlugActive to enabled strategies for the cell.
        evt = SlugActive(
            slug=slug,
            asset=asset,
            tf=tf,
            ts_us=int(time() * 1_000_000),
            condition_id=condition_id,
            token_id_up=token_id_up,
            token_id_dn=token_id_dn,
        )
        for strat in strategies_for_cell.get(cell_key, []):
            sc = StratCell(strategy=cell_key[0], cell=cell_key[1])
            if sc in kill_set or sc in _disabled:
                continue

            # MAS double-mint defense (vps_ireland 2026-05-20 incident):
            # before emitting MINT for a freshly discovered active slug,
            # query the chain for any pre-existing position-token balance.
            # If the wallet already holds shares on either side, the
            # previous tv-engine process already minted this slug and lost
            # state across restart — seed inventory instead of re-minting.
            # Probes for MAS only; ACC-M / ACC-H never MINT.
            mas_seeded_from_chain = False
            if getattr(strat, "code", "") == "MAS":
                probe = await _query_existing_mas_inventory(
                    live_executor=live_executor,
                    token_id_up=token_id_up,
                    token_id_dn=token_id_dn,
                    slug=slug,
                    alerts=alerts,
                )
                if probe is not None:
                    inv_up_chain, inv_dn_chain = probe
                    if inv_up_chain > 0 or inv_dn_chain > 0:
                        seed_fn = getattr(strat, "seed_inventory", None)
                        if seed_fn is not None:
                            try:
                                seed_fn(evt, inv_up_chain, inv_dn_chain)
                                mas_seeded_from_chain = True
                                log.info(
                                    "poly_maker_loop.mas_seeded_from_chain_skip_mint",
                                    slug=slug,
                                    inv_up=str(inv_up_chain),
                                    inv_dn=str(inv_dn_chain),
                                )
                            except Exception:
                                log.exception(
                                    "poly_maker_loop.mas_seed_inventory_failed",
                                    strategy=sc.strategy,
                                    cell=sc.cell,
                                    slug=slug,
                                )

            if mas_seeded_from_chain:
                # Skip on_slug_active — state is already seeded; no MINT
                # decision should be emitted for this slug.
                continue

            try:
                decisions = strat.on_slug_active(evt)
            except Exception:
                log.exception(
                    "poly_maker_loop.on_slug_active_failed",
                    strategy=sc.strategy,
                    cell=sc.cell,
                    slug=slug,
                )
                _record_error(sc, alerts, settings)
                continue
            sl = shadow_loggers.get(strat.code)
            if sl is None or not decisions:
                continue
            for decision in decisions:
                with contextlib.suppress(Exception):
                    # Phase 32 — sim hook (Plan 32-10): observe BEFORE shadow_log.log
                    # (site 2 of 4 — slug_discovery_tick SlugActive decisions)
                    if fill_sim is not None and not getattr(settings, "tv_poly_maker_sim_disabled", False):
                        with contextlib.suppress(Exception):
                            fill_sim.observe(decision=decision, strategy=strat, slug_state=strat.slug_states.get(slug))
                    sl.log(decision, sim_fill=False, slug_state=strat.slug_states.get(slug))


async def _slug_resolution_tick(
    *,
    active_slugs: dict[tuple[str, str], str | None],
    active_slug_meta: dict[str, dict[str, Any]],
    cell_keys: list[tuple[str, str]],
    cell_asset_tf: dict[tuple[str, str], tuple[str, str]],
    strategies_for_cell: dict[tuple[str, str], list["MakerStrategyBase"]],
    onchain_oracle: "OnchainOracle",
    book_mirror: "BookMirror",
    trade_mirror: "TradeMirror",
    kill_set: set[StratCell],
    shadow_loggers: dict[str, "AsyncShadowLogger"],
    alerts: "AlertService | None",
    settings: "Settings | Any",
    fill_sim: "MakerFillSimulator | None" = None,  # Phase 32 Plan 32-10
) -> None:
    """Per active slug: ask onchain_oracle for resolution; on winner, emit
    ``SlugResolved`` + unsubscribe from book + trade mirrors.

    Oracle failures are tolerated (skip + retry next tick); slugs stay
    active until the oracle returns a non-UNRESOLVED outcome.
    """
    # Pre-fix: iterated active_slugs.items() — but `active_slugs[(asset, tf)]`
    # is OVERWRITTEN by discovery when a new slug rolls in (5min boundary).
    # Old closed slugs that hadn't yet resolved on-chain got dropped and never
    # polled. Result: zero REDEEMs across 33 closed slugs, dashboard PnL stuck
    # at -cash_spent permanently (looks like 100% loss).
    #
    # Post-fix: iterate active_slug_meta (which keeps EVERY slug we've wired)
    # so closed-but-pending-resolution slugs are polled until they resolve on
    # chain. Resolution success clears the slug from both maps + unsubscribes.
    resolved_slugs: list[tuple[str, str, str]] = []  # (slug, asset, tf)
    for slug, meta in list(active_slug_meta.items()):
        asset = meta.get("asset")
        tf = meta.get("tf")
        if not asset or not tf:
            continue
        try:
            outcome = await onchain_oracle.get_resolution(meta["condition_id"])
        except Exception as exc:
            log.warning(
                "poly_maker_loop.oracle_error",
                slug=slug,
                condition_id=meta["condition_id"],
                error=str(exc)[:200],
            )
            continue
        if outcome == ResolutionOutcome.UNRESOLVED:
            continue
        winner: str = "up" if outcome == ResolutionOutcome.UP else "dn"

        # Emit SlugResolved to ALL enabled strategies covering this (asset, tf).
        # Pre-fix used `next(...)` which picked only the FIRST cell_key matching
        # (asset, tf), so only ONE strategy per (asset, tf) ever received
        # on_slug_resolved. ACC-H / MAS / PAT-SHADOW on the same cell silently
        # never resolved -> REDEEM never emitted -> cash_received never credited
        # -> dashboard PnL stayed permanently negative (100% loss appearance).
        matching_cell_keys = [
            ck for ck, at in cell_asset_tf.items() if at == (asset, tf)
        ]
        for cell_key in matching_cell_keys:
            evt = SlugResolved(
                slug=slug, ts_us=int(time() * 1_000_000), winner=winner  # type: ignore[arg-type]
            )
            for strat in strategies_for_cell.get(cell_key, []):
                sc = StratCell(strategy=cell_key[0], cell=cell_key[1])
                if sc in kill_set or sc in _disabled:
                    continue
                # Bug 7 — capture slug_state ref BEFORE on_slug_resolved.
                # ACC-M.on_slug_resolved pops self.slug_states[slug] at end (inherited
                # by ACC-H/ACC-PC). Re-fetching via .get(slug) AFTER the call returns
                # None → _observe_redeem early-returns → cash_received never credited,
                # inv_up never decremented. Held reference keeps the object alive and
                # all mutations made during on_slug_resolved (final-merge inv decrement,
                # etc.) propagate through this ref. MAS doesn't pop so this is also
                # safe for MAS (same object identity).
                slug_state_ref = (
                    strat.slug_states.get(slug)
                    if hasattr(strat, "slug_states")
                    else None
                )
                try:
                    decisions = strat.on_slug_resolved(evt)
                except Exception:
                    log.exception(
                        "poly_maker_loop.on_slug_resolved_failed",
                        strategy=sc.strategy,
                        cell=sc.cell,
                        slug=slug,
                    )
                    _record_error(sc, alerts, settings)
                    continue
                sl = shadow_loggers.get(strat.code)
                _sim_on = fill_sim is not None and not getattr(
                    settings, "tv_poly_maker_sim_disabled", False
                )
                if sl is not None and decisions:
                    for decision in decisions:
                        with contextlib.suppress(Exception):
                            # Phase 32 — sim hook (Plan 32-10): observe BEFORE shadow_log.log
                            # (site 3 of 4 — slug_resolution_tick SlugResolved decisions)
                            if _sim_on:
                                with contextlib.suppress(Exception):
                                    fill_sim.observe(decision=decision, strategy=strat, slug_state=slug_state_ref)
                            sl.log(decision, sim_fill=False, slug_state=slug_state_ref)
                # E1 (ENGINE_BUG_MAP_2026_05_28) — ALWAYS settle the slug's sim
                # state at resolution, even when the strategy emitted no REDEEM
                # (loser-only slug) or popped its state. Clears the loser-side
                # mark so slug_pnl_so_far collapses to realized cash. Idempotent
                # + double-credit-safe (see fill_sim.settle_slug).
                if _sim_on and slug_state_ref is not None:
                    with contextlib.suppress(Exception):
                        fill_sim.settle_slug(
                            strategy=strat,
                            slug=slug,
                            winner=winner,
                            slug_state=slug_state_ref,
                        )

        # Unsubscribe from book + trade mirrors for both token_ids.
        with contextlib.suppress(Exception):
            await book_mirror.unsubscribe(meta["token_id_up"])
            await book_mirror.unsubscribe(meta["token_id_dn"])
        with contextlib.suppress(Exception):
            await trade_mirror.unsubscribe(meta["token_id_up"])
            await trade_mirror.unsubscribe(meta["token_id_dn"])
        resolved_slugs.append((slug, asset, tf))

    # Clear resolved entries from both maps. Only clear active_slugs[(asset, tf)]
    # if it still points to THIS slug — discovery may have already rotated to a
    # newer slug for the same cell.
    for slug, asset, tf in resolved_slugs:
        active_slug_meta.pop(slug, None)
        if active_slugs.get((asset, tf)) == slug:
            active_slugs[(asset, tf)] = None


async def _merge_check_tick(
    *,
    cell_keys: list[tuple[str, str]],
    strategies_for_cell: dict[tuple[str, str], list["MakerStrategyBase"]],
    cached_l25: dict[tuple[str, str, str], "L25Update"],
    kill_set: set[StratCell],
    shadow_loggers: dict[str, "AsyncShadowLogger"],
    alerts: "AlertService | None",
    settings: "Settings | Any",
    fill_sim: "MakerFillSimulator | None" = None,  # Phase 32 Plan 32-10
) -> None:
    """Periodic 5s merge-check: re-fire each cell's last cached L25 into the
    strategy so its ``_merge_decisions`` sub-pass evaluates against the
    most-recent inventory state. Empty-decision returns are common — that's
    fine; the goal is to keep the merge trigger active between organic L25
    arrivals.
    """
    for cell_key in cell_keys:
        for strat in strategies_for_cell.get(cell_key, []):
            sc = StratCell(strategy=cell_key[0], cell=cell_key[1])
            if sc in kill_set or sc in _disabled:
                continue
            # Find the most recent cached L25 for ANY slug for this cell.
            matching = [
                cached_l25[k]
                for k in cached_l25
                if k[0] == cell_key[0] and k[1] == cell_key[1]
            ]
            if not matching:
                continue
            # Use the most recent (last appended).
            evt = matching[-1]
            try:
                decisions = strat.on_l25_update(evt)
            except Exception:
                log.exception(
                    "poly_maker_loop.merge_check_failed",
                    strategy=sc.strategy,
                    cell=sc.cell,
                )
                _record_error(sc, alerts, settings)
                continue
            sl = shadow_loggers.get(strat.code)
            if sl is None or not decisions:
                continue
            for decision in decisions:
                with contextlib.suppress(Exception):
                    # Phase 32 — sim hook (Plan 32-10): observe BEFORE shadow_log.log
                    # (site 4 of 4 — merge_check_tick re-fired L25 decisions)
                    if fill_sim is not None and not getattr(settings, "tv_poly_maker_sim_disabled", False):
                        with contextlib.suppress(Exception):
                            fill_sim.observe(decision=decision, strategy=strat, slug_state=strat.slug_states.get(decision.slug))
                    sl.log(
                        decision,
                        sim_fill=False,
                        slug_state=strat.slug_states.get(decision.slug),
                    )


# Emit-on-change cache for _emit_state_tick: (sleeve_id, slug) -> signature of
# the last-pushed MEANINGFUL state. The 5s tick re-broadcast a maker_state for
# EVERY active slug every 5s (with an always-changing ts_us), so idle and
# accumulated/resolved slugs flooded /ws/terminal unconditionally (~40/s on the
# live VPS) — starving the chart's price_tick fanout and storming the
# /maker/sleeves refetch. We now push only when a meaningful field actually
# moved. The dashboard still REST-polls every 5s, so unchanged slugs lose
# nothing (sum_bids/sum_asks are derived + noisy and refreshed by that poll, so
# they're excluded from the change signature).
_last_emitted_state: dict[tuple[str, str], tuple] = {}


async def _emit_state_tick(
    *,
    cell_keys: list[tuple[str, str]],
    strategies_for_cell: dict[tuple[str, str], list["MakerStrategyBase"]],
    kill_set: set[StratCell],
    pool: "asyncpg.Pool",
    settings: "Settings | Any",
) -> None:
    """Per (strategy, cell): emit one ``maker_state`` ``notify_event`` to
    ``/ws/terminal`` carrying paired-inv, sum bids/asks, fills/cancels/merges,
    and rolling P&L. Payload < 1500 bytes (Pitfall 6).

    Emit-on-change: a slug is pushed only when its meaningful state moved since
    the last push (see ``_last_emitted_state``); unchanged/idle/dead slugs are
    skipped. A cell with zero active slugs emits nothing.
    """
    seen: set[tuple[str, str]] = set()
    for cell_key in cell_keys:
        sc = StratCell(strategy=cell_key[0], cell=cell_key[1])
        if sc in kill_set or sc in _disabled:
            continue
        for strat in strategies_for_cell.get(cell_key, []):
            sleeve_id = _sleeve_id(strat.code, strat.asset, strat.tf)
            # Iterate strategy's known slug_states. One notify per slug.
            # Snapshot keys to avoid RuntimeError if the dispatcher mutates
            # slug_states (slug add/remove) concurrently with this 5s tick.
            for slug, state in list(strat.slug_states.items()):
                # Compute payload — keep tight (< 1500 bytes).
                sum_bids = sum(
                    float(o.price) * float(o.size)
                    for o in state.open_orders.values()
                    if o.side == "up"
                ) if state.open_orders else 0.0
                sum_asks = sum(
                    float(o.price) * float(o.size)
                    for o in state.open_orders.values()
                    if o.side == "dn"
                ) if state.open_orders else 0.0
                paired = float(min(state.inv_up, state.inv_dn))
                # E5a (ENGINE_BUG_MAP_2026_05_28): include cash_recovered
                # (MERGE + REDEEM proceeds) so the live dashboard tick matches
                # shadow_log.py's slug_pnl_so_far (which includes it). Omitting
                # it made the live card diverge from the CSV.
                pnl_so_far = float(
                    state.cash_received
                    + state.cash_recovered
                    - state.cash_spent
                    + state.rebates_received
                    - state.taker_fees_paid
                )
                key = (sleeve_id, slug)
                seen.add(key)
                # Emit-on-change: skip the push when nothing meaningful moved
                # (inventory / fills / cancels / merges / pnl). ts_us and the
                # derived sum_bids/sum_asks are excluded from the signature.
                sig = (
                    round(paired, 4),
                    state.n_fills,
                    state.n_cancels,
                    state.n_merges,
                    round(pnl_so_far, 4),
                )
                if _last_emitted_state.get(key) == sig:
                    continue
                _last_emitted_state[key] = sig
                payload = {
                    "sleeve_id": sleeve_id,
                    "slug": slug,
                    "paired_inv": paired,
                    "sum_bids": sum_bids,
                    "sum_asks": sum_asks,
                    "n_fills": state.n_fills,
                    "n_cancels": state.n_cancels,
                    "n_merges": state.n_merges,
                    "pnl_so_far": pnl_so_far,
                    "ts_us": int(monotonic() * 1_000_000),
                }
                try:
                    async with pool.acquire() as conn:
                        await notify_event(conn, kind="maker_state", payload=payload)
                except Exception:
                    log.exception(
                        "poly_maker_loop.emit_state_failed",
                        sleeve_id=sleeve_id,
                        slug=slug,
                    )
    # Prune signatures for slugs no longer tracked so the change-cache can't
    # grow unbounded as slugs resolve / rotate out.
    for dead in [k for k in _last_emitted_state if k not in seen]:
        _last_emitted_state.pop(dead, None)


# ---------------------------------------------------------------------------
# Top-level loop
# ---------------------------------------------------------------------------


async def poly_maker_loop(
    *,
    book_mirror: "BookMirror",
    trade_mirror: "TradeMirror",
    strategies: list["MakerStrategyBase"],
    cell_assignments: dict[str, list[str]],
    kill_set: set[StratCell],
    shadow_loggers: dict[str, "AsyncShadowLogger"],
    gamma_client: "GammaClient",
    onchain_oracle: "OnchainOracle",
    pool: "asyncpg.Pool",
    alerts: "AlertService | None",
    settings: "Settings | Any",
    stop: asyncio.Event,
    shadow_mode: bool = True,
    live_executor: Any = None,
    poly_merger_w3: Any = None,
    poly_merger_wallet: str | None = None,
    private_key: str | None = None,
    merge_pairs_fn: Any = None,
    fill_sim: "MakerFillSimulator | None" = None,  # Phase 32 Plan 32-10
) -> None:
    """Event-driven dispatcher orchestrator.

    Lifecycle:
      1. Build (strategy_code, cell) → [strategies] index from
         ``cell_assignments``.
      2. Register ``trade_mirror.set_trade_callback`` → dispatches TradePrint
         to AccH strategies (Test 9).
      3. Spawn 4 sub-tasks:
         a. ``_slug_discovery_loop`` — every 30s, ask gamma per cell, emit
            SlugActive on new slugs (D-15 + Test 22).
         b. ``_slug_resolution_loop`` — every 60s, ask oracle per active
            slug, emit SlugResolved on winner.
         c. ``_book_poll_loop`` — every 100ms (10Hz), pull book snapshots
            from BookMirror, build L25Update, dispatch (Test 5).
         d. ``_merge_check_loop`` — every 5s, re-fire latest cached L25 to
            evaluate MERGE decisions (Test 12).
         e. ``_emit_state_loop`` — every 5s, emit ``maker_state`` per
            (strategy, cell) (Test 13, 14).
      4. Wait on ``stop.wait()``; on shutdown:
         a. Cancel all sub-tasks.
         b. Stop loggers (Test 19).
         c. Unsubscribe from book + trade mirrors for all active token_ids.

    Returns when ``stop`` is set; never raises (per-tick exceptions caught
    in inner ticks via ``_record_error``).
    """
    # ------------------------------------------------------------------
    # 1. Build indices
    # ------------------------------------------------------------------

    cell_keys: list[tuple[str, str]] = []
    cell_asset_tf: dict[tuple[str, str], tuple[str, str]] = {}
    strategies_for_cell: dict[tuple[str, str], list["MakerStrategyBase"]] = {}
    all_cell_keys_for_strategies: list[tuple[tuple[str, str], "MakerStrategyBase"]] = []

    # Index strategies by (code, asset, tf) — one instance per cell.
    # CRITICAL: pre-fix the index used s.code only, so when ACC-H / MAS had
    # two instances (5m + 15m), the dict comprehension OVERWROTE the first,
    # leaving one instance orphaned + the other handling BOTH cells (mixing
    # state across 5m and 15m slugs inside a single slug_states dict).
    # Live symptom: rows tagged tf=15m for slug btc-updown-5m-* etc.
    strategy_by_cell: dict[tuple[str, str, str], "MakerStrategyBase"] = {}
    for s in strategies:
        key = (s.code, getattr(s, "asset", "").upper(), getattr(s, "tf", ""))
        strategy_by_cell[key] = s

    for _strat_code_raw, cells in cell_assignments.items():
        # 2026-05-27 normalisation fix — `cell_assignments` from main.py is
        # keyed with the raw display form (e.g. "PAT-SHADOW"). The variable
        # used to be named `strat_code_lower` but no normalisation was ever
        # applied, so `cell_key[0]` carried "PAT-SHADOW" while the kill_set
        # built by `_parse_kill_env` only accepts lowercase+underscore form
        # (regex `^[a-z_]+:[a-z0-9_]+$`). Result: TV_POLY_MAKER_KILL silently
        # never matched the actual cell_key, so kill tokens were no-ops.
        # Normalise once here; both `strat_code_lower` and `strat_code_upper`
        # are now derived deterministically from the same source.
        strat_code_lower = _strat_code_raw.lower().replace("-", "_")
        strat_code_upper = strat_code_lower.upper().replace("_", "-")
        for cell in cells:
            # Parse 'btc_15m' -> ('BTC', '15m').
            parts = cell.split("_")
            if len(parts) < 2:
                log.warning(
                    "poly_maker_loop.unparseable_cell",
                    cell=cell,
                    strat=strat_code_lower,
                )
                continue
            asset = parts[0].upper()
            tf = "_".join(parts[1:])

            # Pick the strategy instance that ACTUALLY owns this (asset, tf).
            strat = strategy_by_cell.get((strat_code_upper, asset, tf))
            if strat is None:
                log.warning(
                    "poly_maker_loop.strategy_not_found_for_cell",
                    strat_code=strat_code_lower,
                    cell=cell,
                    expected_key=(strat_code_upper, asset, tf),
                )
                continue

            cell_key = (strat_code_lower, cell)
            cell_keys.append(cell_key)
            cell_asset_tf[cell_key] = (asset, tf)
            strategies_for_cell.setdefault(cell_key, []).append(strat)
            all_cell_keys_for_strategies.append((cell_key, strat))

    # Per-(strategy, cell, slug) cached L25 snapshot — keyed for merge-check.
    cached_l25: dict[tuple[str, str, str], L25Update] = {}

    # Per (asset, tf) active slug + global slug → metadata map.
    active_slugs: dict[tuple[str, str], str | None] = {
        at: None for at in cell_asset_tf.values()
    }
    active_slug_meta: dict[str, dict[str, Any]] = {}
    # Phase 31: per-CELL_KEY last-emitted-SlugActive slug. Lets multiple
    # strategies on the same cell each receive SlugActive exactly once.
    per_cell_seen_slugs: dict[tuple[str, str], str] = {}

    # Subscribed token_ids — tracked so shutdown can unsubscribe cleanly.
    subscribed_tokens: set[str] = set()

    # ------------------------------------------------------------------
    # 2. Register TradeMirror callback
    # ------------------------------------------------------------------

    async def _on_trade(evt: TradePrint) -> None:
        await _dispatch_trade_print(
            evt=evt,
            strategies_for_cell=[s for _, s in all_cell_keys_for_strategies],
            cell_keys=[ck for ck, _ in all_cell_keys_for_strategies],
            kill_set=kill_set,
            shadow_loggers=shadow_loggers,
            alerts=alerts,
            settings=settings,
            shadow_mode=shadow_mode,
            live_executor=live_executor,
            poly_merger_w3=poly_merger_w3,
            poly_merger_wallet=poly_merger_wallet,
            private_key=private_key,
            pool=pool,
            merge_pairs_fn=merge_pairs_fn,
            fill_sim=fill_sim,  # Phase 32 Plan 32-10
        )

    with contextlib.suppress(Exception):
        trade_mirror.set_trade_callback(_on_trade)

    # ------------------------------------------------------------------
    # 3. Spawn sub-loops
    # ------------------------------------------------------------------

    slug_discovery_tick_s = float(getattr(
        settings, "tv_poly_maker_slug_discovery_tick_s", _SLUG_DISCOVERY_TICK_S
    ))
    slug_resolution_tick_s = float(getattr(
        settings, "tv_poly_maker_slug_resolution_tick_s", _SLUG_RESOLUTION_TICK_S
    ))
    book_poll_tick_s = float(getattr(
        settings, "tv_poly_maker_book_poll_tick_s", _BOOK_POLL_TICK_S
    ))
    merge_check_tick_s = float(getattr(
        settings, "tv_poly_maker_merge_check_interval_s", 5
    ))
    emit_state_tick_s = float(getattr(
        settings, "tv_poly_maker_emit_interval_s", 5
    ))

    async def _stop_aware_sleep(seconds: float) -> bool:
        """Sleep up to ``seconds`` OR until ``stop`` is set. Returns True on stop."""
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    async def _slug_discovery_loop() -> None:
        while not stop.is_set():
            try:
                await _slug_discovery_tick(
                    cell_keys=cell_keys,
                    cell_asset_tf=cell_asset_tf,
                    strategies_for_cell=strategies_for_cell,
                    active_slugs=active_slugs,
                    active_slug_meta=active_slug_meta,
                    per_cell_seen_slugs=per_cell_seen_slugs,
                    gamma_client=gamma_client,
                    book_mirror=book_mirror,
                    trade_mirror=trade_mirror,
                    kill_set=kill_set,
                    shadow_loggers=shadow_loggers,
                    alerts=alerts,
                    settings=settings,
                    fill_sim=fill_sim,  # Phase 32 Plan 32-10
                    live_executor=live_executor,  # mas double-mint defense
                )
                # Track which tokens are currently subscribed.
                for meta in active_slug_meta.values():
                    subscribed_tokens.add(meta["token_id_up"])
                    subscribed_tokens.add(meta["token_id_dn"])
            except Exception:
                log.exception("poly_maker_loop.slug_discovery_loop_error")
            if await _stop_aware_sleep(slug_discovery_tick_s):
                return

    async def _slug_resolution_loop() -> None:
        while not stop.is_set():
            try:
                await _slug_resolution_tick(
                    active_slugs=active_slugs,
                    active_slug_meta=active_slug_meta,
                    cell_keys=cell_keys,
                    cell_asset_tf=cell_asset_tf,
                    strategies_for_cell=strategies_for_cell,
                    onchain_oracle=onchain_oracle,
                    book_mirror=book_mirror,
                    trade_mirror=trade_mirror,
                    kill_set=kill_set,
                    shadow_loggers=shadow_loggers,
                    alerts=alerts,
                    settings=settings,
                    fill_sim=fill_sim,  # Phase 32 Plan 32-10
                )
            except Exception:
                log.exception("poly_maker_loop.slug_resolution_loop_error")
            if await _stop_aware_sleep(slug_resolution_tick_s):
                return

    async def _book_poll_loop() -> None:
        """10Hz poll: pull book snapshots; dispatch L25Update per (slug, side)."""
        while not stop.is_set():
            try:
                for (asset, tf), slug in list(active_slugs.items()):
                    if slug is None:
                        continue
                    meta = active_slug_meta.get(slug)
                    if meta is None:
                        continue
                    # Phase 31: collect ALL cell_keys whose (asset, tf) matches.
                    # Multiple strategies can be registered on the same cell
                    # (e.g., ACC-H + MAS + ACC-PC all on btc_15m). Each gets
                    # its own L25Update via _dispatch_l25's per-strat loop.
                    matching_cell_keys = [
                        ck for ck, at in cell_asset_tf.items() if at == (asset, tf)
                    ]
                    if not matching_cell_keys:
                        continue
                    strats_for_this_cell = [
                        strat
                        for ck in matching_cell_keys
                        for strat in strategies_for_cell.get(ck, [])
                    ]
                    if not strats_for_this_cell:
                        continue
                    # Parallel cell_keys list aligns with strats_for_this_cell
                    # index-wise (used by _dispatch_l25 for kill_set filtering).
                    cell_keys_local = [
                        ck
                        for ck in matching_cell_keys
                        for _ in strategies_for_cell.get(ck, [])
                    ]

                    for side_name, token_id in (
                        ("up", meta["token_id_up"]),
                        ("dn", meta["token_id_dn"]),
                    ):
                        book = None
                        try:
                            book = book_mirror.get(token_id)
                        except Exception:
                            log.exception(
                                "poly_maker_loop.book_get_failed",
                                token_id=token_id,
                            )
                        if not book:
                            continue
                        bids_raw = book.get("bids", [])
                        asks_raw = book.get("asks", [])
                        bids = tuple(
                            (Decimal(str(lv.get("price", 0))), Decimal(str(lv.get("size", 0))))
                            for lv in bids_raw
                            if isinstance(lv, dict)
                        )
                        asks = tuple(
                            (Decimal(str(lv.get("price", 0))), Decimal(str(lv.get("size", 0))))
                            for lv in asks_raw
                            if isinstance(lv, dict)
                        )
                        ts_us = int(time() * 1_000_000)
                        evt = L25Update(
                            slug=slug,
                            side=side_name,  # type: ignore[arg-type]
                            ts_us=ts_us,
                            bids=bids,
                            asks=asks,
                        )
                        # Cache for merge-check (one entry per cell + slug).
                        cached_l25[(cell_key[0], cell_key[1], slug)] = evt
                        await _dispatch_l25(
                            evt=evt,
                            strategies_for_cell=strats_for_this_cell,
                            cell_keys=cell_keys_local,
                            kill_set=kill_set,
                            shadow_loggers=shadow_loggers,
                            alerts=alerts,
                            settings=settings,
                            shadow_mode=shadow_mode,
                            live_executor=live_executor,
                            poly_merger_w3=poly_merger_w3,
                            poly_merger_wallet=poly_merger_wallet,
                            private_key=private_key,
                            pool=pool,
                            merge_pairs_fn=merge_pairs_fn,
                            fill_sim=fill_sim,  # Phase 32 Plan 32-10
                        )
            except Exception:
                log.exception("poly_maker_loop.book_poll_loop_error")
            if await _stop_aware_sleep(book_poll_tick_s):
                return

    async def _merge_check_loop() -> None:
        while not stop.is_set():
            try:
                await _merge_check_tick(
                    cell_keys=cell_keys,
                    strategies_for_cell=strategies_for_cell,
                    cached_l25=cached_l25,
                    kill_set=kill_set,
                    shadow_loggers=shadow_loggers,
                    alerts=alerts,
                    settings=settings,
                    fill_sim=fill_sim,  # Phase 32 Plan 32-10
                )
            except Exception:
                log.exception("poly_maker_loop.merge_check_loop_error")
            if await _stop_aware_sleep(merge_check_tick_s):
                return

    async def _emit_state_loop() -> None:
        while not stop.is_set():
            try:
                await _emit_state_tick(
                    cell_keys=cell_keys,
                    strategies_for_cell=strategies_for_cell,
                    kill_set=kill_set,
                    pool=pool,
                    settings=settings,
                )
            except Exception:
                log.exception("poly_maker_loop.emit_state_loop_error")
            if await _stop_aware_sleep(emit_state_tick_s):
                return

    log.info(
        "poly_maker_loop.starting",
        n_cells=len(cell_keys),
        n_strategies=len(strategies),
        shadow_mode=shadow_mode,
    )

    sub_tasks: list[asyncio.Task[None]] = []
    sub_tasks.append(asyncio.create_task(_slug_discovery_loop(), name="poly_maker.slug_discovery"))
    sub_tasks.append(asyncio.create_task(_slug_resolution_loop(), name="poly_maker.slug_resolution"))
    sub_tasks.append(asyncio.create_task(_book_poll_loop(), name="poly_maker.book_poll"))
    sub_tasks.append(asyncio.create_task(_merge_check_loop(), name="poly_maker.merge_check"))
    sub_tasks.append(asyncio.create_task(_emit_state_loop(), name="poly_maker.emit_state"))

    try:
        # Wait for stop signal.
        await stop.wait()
    finally:
        # ----------------------------------------------------------------
        # 4. Graceful shutdown
        # ----------------------------------------------------------------
        log.info("poly_maker_loop.stopping")
        for t in sub_tasks:
            t.cancel()
        for t in sub_tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(t, timeout=2.0)

        # Stop all shadow loggers (flush queues, finalize CSV).
        for sl in shadow_loggers.values():
            with contextlib.suppress(Exception):
                await sl.stop()

        # Unsubscribe all known token_ids from both mirrors.
        for token_id in subscribed_tokens:
            with contextlib.suppress(Exception):
                await book_mirror.unsubscribe(token_id)
            with contextlib.suppress(Exception):
                await trade_mirror.unsubscribe(token_id)

        log.info("poly_maker_loop.stopped")


__all__ = [
    "StratCell",
    "_disabled",
    "_dispatch_l25",
    "_dispatch_trade_print",
    "_emit_state_tick",
    "_error_windows",
    "_merge_check_tick",
    "_parse_kill_env",
    "_record_error",
    "_route_decision",
    "_sleeve_id",
    "_slug_discovery_tick",
    "_slug_resolution_tick",
    "poly_maker_loop",
]
