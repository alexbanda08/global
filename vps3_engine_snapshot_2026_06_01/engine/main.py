"""tv-engine entry point - asyncio.TaskGroup lifespan.

Phase 3 hosts ``writer_health.probe_loop`` as the sole task. Phase 6+
adds ``BarEngine.run``, Phase 12+ adds kill/keepalive consumers.
Pattern mirrors ``backend.app.watchdog.main`` (proven in Phase 12).

On SIGTERM/SIGINT: set the ``stop`` event, which cancels the TaskGroup
cleanly. ``probe_loop`` handles ``CancelledError`` internally and logs
``writer_health.stopped`` before re-raising.
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import structlog

from backend.app.__about__ import __version__
from backend.app.api.bots import _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS
from backend.app.core.config import get_settings
from backend.app.core.logging import configure_logging
from backend.app.core.secrets_registry import load_secrets_registry
from backend.app.data.hl_retention import retention_sweep_loop
from backend.app.data.manifest import MANIFEST
from backend.app.data.writer_health import probe_loop
from backend.app.engine import snapshot_writer
from backend.app.engine.reconcile import reconcile_or_exit
from backend.app.engine.tasks_worker import (
    _engine_tasks_worker,
    record_engine_boot,
)
from backend.app.services.alert_factory import build_alert_service, register_alert_loops
from backend.app.services.poly_market_discovery import PolyMarketDiscovery
from backend.app.venues.hyperliquid.live_gate import check_bar_source_alignment
from backend.app.venues.hyperliquid.market_data import (
    HLFeedSettings,
    HLMarketDataFeed,
)
from backend.app.venues.polymarket.allowance import (
    LiveModeForbidden,
    assert_live_polymarket_allowance,
)
from backend.app.venues.polymarket.client import PolymarketClient
from backend.app.venues.polymarket.paper import PolyPaperExecutor
from backend.app.venues.polymarket.settings import get_poly_settings

logger = structlog.get_logger(__name__)


# Phase 34 — shadow gated sleeves spec.
# Source: ``strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`` §1.
#
# 11 INDEPENDENT sleeves. Each entry = exactly ONE controller instance with its
# own sleeve_id (operator directive 2026-05-22: NOT the HOLD/HEDGE/SELL × 11
# multiplication suggested by spec §1 body — the table header had 11 distinct
# rows and the operator wants 11 cards). Hedge policy is hardcoded per entry
# below — sniper-base uses HEDGE_HOLD (production default for non-momo
# strategies); momo / momo_v2 use HOLD_ONLY (simplest; no hedge logic during
# the shadow validation window).
#
# Each entry: (sleeve_id, base_strategy, asset, tf, gate_stack, gate_cell_strategy, hedge_policy).
#
# Gate enable: ``TV_POLY_SHADOW_GATED_ENABLED=true`` on the host env file.
# All 11 are paper-only (CLAUDE.md inv #11 — no live capital in shadow window).
def _validate_shadow_sleeve_spec(
    spec: tuple[tuple[str, str, str, str, tuple[str, ...], str, str], ...],
) -> None:
    """Phase 34 fix 2026-05-22 — config-load guard against the Bug #2 trap.

    Sniper sleeves fire at ``phase="bar_close"``. The bar_close BarContext
    does NOT populate ``ret_15m_for_mtf`` / ``ret_1h_for_mtf`` /
    ``markov_regime_w20_5m_va`` / ``markov_regime_w20_1m_va`` — those are
    t+60 / t+120-only fields. A sniper sleeve with mtf2/m5va/m1va in its
    gate_stack would silently get None → -1 → fail-closed every fire (no
    log distinguishes 'gate ran and rejected' from 'aux was never
    populated'). That's the silent fail that took out the original
    sleeve #2. Reject at config load instead.
    """
    _FORBIDDEN_FOR_SNIPER = frozenset({"mtf2", "m5va", "m1va"})
    for sleeve_id, base, _asset, _tf, gates, _cell, _hp in spec:
        if base == "sniper":
            bad = sorted(set(gates) & _FORBIDDEN_FOR_SNIPER)
            if bad:
                raise ValueError(
                    f"{sleeve_id}: sniper cells cannot use {bad} gates "
                    f"(bar_close BarContext doesn't populate the aux). "
                    f"Drop the gate, or change base to momo / momo_v2."
                )


_SHADOW_GATED_SLEEVES_SPEC: tuple[
    tuple[str, str, str, str, tuple[str, ...], str, str], ...
] = (
    ("poly_updown_sol_5m_sniper_hod",          "sniper",  "SOL", "5m",  ("hod",),         "sniper",  "HEDGE_HOLD"),
    # Phase 34 fix 2026-05-22: sleeve #2 dropped m5va gate (Markov regime
    # decorrelated from sniper signal — backtest showed n=55 → n=129,
    # WR 67%→74%, sum$ +$313→+$745). Renamed: removed "_m5va" suffix.
    # Historical events under old sleeve_id stay queryable in trading.events.
    ("poly_updown_eth_15m_sniper_hod",         "sniper",  "ETH", "15m", ("hod",),         "sniper",  "HEDGE_HOLD"),
    # Phase 34 fix 2026-05-22: sleeve #3 added m1va gate (1-MIN Markov
    # regime alignment lifts momo WR 78%→90%, n=61). Sleeve_id unchanged.
    ("poly_updown_btc_15m_momo_hod",           "momo",    "BTC", "15m", ("hod", "m1va"),  "momo",    "HOLD_ONLY"),
    ("poly_updown_btc_15m_sniper_hod",         "sniper",  "BTC", "15m", ("hod",),         "sniper",  "HEDGE_HOLD"),
    ("poly_updown_btc_5m_sniper_hod",          "sniper",  "BTC", "5m",  ("hod",),         "sniper",  "HEDGE_HOLD"),
    ("poly_updown_btc_5m_momo_v2_hod_mtf",     "momo_v2", "BTC", "5m",  ("hod", "mtf2"),  "momo_v2", "HOLD_ONLY"),
    ("poly_updown_btc_15m_momo_v2_hod",        "momo_v2", "BTC", "15m", ("hod",),         "momo_v2", "HOLD_ONLY"),
    ("poly_updown_sol_5m_momo_v2_hod",         "momo_v2", "SOL", "5m",  ("hod",),         "momo_v2", "HOLD_ONLY"),
    ("poly_updown_eth_15m_momo_v2_hod",        "momo_v2", "ETH", "15m", ("hod",),         "momo_v2", "HOLD_ONLY"),
    ("poly_updown_sol_15m_momo_v2_hod",        "momo_v2", "SOL", "15m", ("hod",),         "momo_v2", "HOLD_ONLY"),
    ("poly_updown_eth_5m_sniper_hod",          "sniper",  "ETH", "5m",  ("hod",),         "sniper",  "HEDGE_HOLD"),
)


# Phase 35 — VWAP continuation sleeves spec (paper-only, shadow validation).
# Source: ``strategy_lab/reports/TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`` §2.
#
# 5 independent late-fire sleeves. Each = ONE PolymarketUpdownController
# with strategy_mode='vwap_continuation' + its own (offset_s, thr range,
# gate requirements). hedge_policy=HOLD_ONLY throughout (no hedging during
# the shadow validation window).
#
# Format: (sleeve_id, asset, tf, offset_s, thr_min_bps, thr_max_bps,
#          require_m1v, require_f7, require_cross_full, require_cross_partial)
# Gate enable: ``TV_POLY_VWAP_CONT_ENABLED=true`` on the host env file.
_VWAP_CONT_SLEEVES_SPEC: tuple[
    tuple[str, str, str, int, float, float, bool, bool, bool, bool], ...
] = (
    ("poly_updown_btc_5m_vwap_off240_m1v",     "BTC", "5m", 240,  5.0, 10.0, True,  False, False, False),
    ("poly_updown_btc_5m_vwap_off60_f7_cross", "BTC", "5m",  60, 10.0, 15.0, False, True,  True,  False),
    ("poly_updown_btc_5m_vwap_off90_cross",    "BTC", "5m",  90, 10.0, 15.0, False, False, True,  False),
    ("poly_updown_eth_5m_vwap_off210_f7_m1v",  "ETH", "5m", 210, 10.0, 15.0, True,  True,  False, False),
    ("poly_updown_sol_5m_vwap_off60",          "SOL", "5m",  60, 20.0, 30.0, False, False, False, False),
)


# Phase 36 — Shadow9 sleeves spec (3 from SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md).
# All paper-only, fire across BTC/ETH/SOL under a SINGLE sleeve_id per spec
# (e.g., "shadow_poly_updown_ALL_5m_phase1_kelly"). Each entry =
#   (sleeve_id, strategy_mode, tf, slot_allowlist)
# slot_allowlist is the set of (sym, tf) the controller fires on; the
# strategy class handles the rest (phase gate, signal compute, Kelly mult).
_SHADOW9_SLEEVES_SPEC: tuple[
    tuple[str, str, str, tuple[tuple[str, str], ...]], ...
] = (
    (
        "shadow_poly_updown_ALL_5m_phase1_kelly",
        "vwap_kelly_ensemble",
        "5m",
        (("BTC", "5m"), ("ETH", "5m"), ("SOL", "5m")),
    ),
    # V10 — de-risked Kelly A/B (TV_AGENT_SPEC_V10_SLEEVES_2026_05_31.md §4):
    # |fair_edge_bp|>1000 floor + ½-Kelly + sign(fair_edge). Runs alongside the
    # phase1_kelly parent above for live OOS confirmation. Paper/shadow only.
    (
        "shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10",
        "vwap_kelly_fe1000",
        "5m",
        (("BTC", "5m"), ("ETH", "5m"), ("SOL", "5m")),
    ),
    (
        "shadow_poly_updown_ALL_5m_S3_prewindow",
        "prewindow_s3",
        "5m",
        (("BTC", "5m"), ("ETH", "5m"), ("SOL", "5m")),
    ),
    (
        "shadow_poly_updown_ALL_15m_S4_prewindow",
        "prewindow_s4_15m",
        "15m",
        (("BTC", "15m"), ("ETH", "15m"), ("SOL", "15m")),
    ),
)


# Phase 36b — 6 FADE companions + 6 OVERLAY filters from
# SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md (Sleeves #2-7 + Bonus).
# Each entry: (sleeve_id, strategy_mode, asset, tf, fade_cell_key OR overlay_gate_kind).
# Fade companions: strategy_mode='fade_sniper' or 'fade_momo_v2'; fade_cell_key
#   selects HoD top-8 set per spec table.
# Overlay filters: strategy_mode='overlay_sniper'/'overlay_momo'/'overlay_momo_v2';
#   overlay_gate_kind selects extra gate predicate.
_SHADOW9_FADE_OVERLAY_SPEC: tuple[
    tuple[str, str, str, str, str], ...
] = (
    # ─── 6 FADE companions (Sleeves #2-7) ────────────────────────────────
    ("shadow_poly_updown_btc_5m_fade_momo_v2",   "fade_momo_v2", "BTC", "5m",  "momo_v2_btc_5m"),
    ("shadow_poly_updown_btc_5m_fade_sniper",    "fade_sniper",  "BTC", "5m",  "sniper_btc_5m"),
    ("shadow_poly_updown_eth_15m_fade_sniper",   "fade_sniper",  "ETH", "15m", "sniper_eth_15m"),
    ("shadow_poly_updown_sol_5m_fade_sniper",    "fade_sniper",  "SOL", "5m",  "sniper_sol_5m"),
    ("shadow_poly_updown_sol_5m_fade_momo_v2",   "fade_momo_v2", "SOL", "5m",  "momo_v2_sol_5m"),
    ("shadow_poly_updown_sol_15m_fade_momo_v2",  "fade_momo_v2", "SOL", "15m", "momo_v2_sol_15m"),
    # ─── 6 OVERLAY filters (spec Bonus) ──────────────────────────────────
    ("shadow_poly_updown_eth_15m_sniper_m5v",                "overlay_sniper",   "ETH", "15m", "m5v_pass"),
    ("shadow_poly_updown_btc_5m_momo_v2_fairedge500",        "overlay_momo_v2",  "BTC", "5m",  "fairedge500"),
    ("shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30", "overlay_momo_v2",  "BTC", "15m", "fairedge500_cvd30"),
    ("shadow_poly_updown_sol_15m_sniper_fairedge500",        "overlay_sniper",   "SOL", "15m", "fairedge500"),
    ("shadow_poly_updown_sol_5m_momo_v1_m5v",                "overlay_momo",     "SOL", "5m",  "m5v_pass"),
    ("shadow_poly_updown_sol_5m_momo_v2_cvd_macd",           "overlay_momo_v2",  "SOL", "5m",  "cvd_macd"),
)


# Phase 34 fix 2026-05-22 — run validator at module load. Raises ValueError
# if any sniper sleeve gains a momentum-context gate that the bar_close
# BarContext doesn't populate. Prevents silent fail (Bug #2 trap).
_validate_shadow_sleeve_spec(_SHADOW_GATED_SLEEVES_SPEC)


# Module-level hook so tests / Phase 8+ can inject live controller
# instances without monkeypatching across import boundaries. In prod
# this is populated by the BarEngine boot wiring (Phase 6 ships the
# instances; Phase 7.1 adds the enumeration path here).
_HL_CONTROLLERS: list[Any] = []


def register_hl_controller(controller: Any) -> None:
    """Register an HL sleeve controller so the feed subscribes to its
    (symbols, timeframes). Called by Phase 6 BarEngine wiring at boot.

    Enforces a ``.symbols`` + ``.timeframes`` attribute contract; other
    attributes are ignored so concrete controllers can ship without a
    common base class beyond these two.
    """
    if not hasattr(controller, "symbols") or not hasattr(controller, "timeframes"):
        logger.warning(
            "hl_feed.controller_missing_attrs",
            controller=type(controller).__name__,
        )
        return
    _HL_CONTROLLERS.append(controller)


def _enumerate_hl_controllers() -> list[Any]:
    """Return the live controller list, or fall back to env-driven sleeves.

    Priority:
      1. Explicit registrations via ``register_hl_controller``.
      2. ENV fallback: TV_HL_SYMBOLS=SOL,ETH + TV_HL_TFS=5m,15m -> synthesize
         a single minimal controller so the feed has something to subscribe
         to before Phase 6 wires real controllers.
      3. Empty list (feed still boots: allMids + user only).
    """
    if _HL_CONTROLLERS:
        return list(_HL_CONTROLLERS)
    env_syms = os.getenv("TV_HL_SYMBOLS", "").strip()
    env_tfs = os.getenv("TV_HL_TFS", "").strip()
    if not env_syms and not env_tfs:
        return []

    class _EnvController:
        def __init__(self, symbols: list[str], timeframes: list[str]) -> None:
            self.symbols = symbols
            self.timeframes = timeframes

    return [
        _EnvController(
            symbols=[s.strip() for s in env_syms.split(",") if s.strip()],
            timeframes=[t.strip() for t in env_tfs.split(",") if t.strip()],
        )
    ]


# Phase 30 Plan 30-11 — fail-fast cell validation (T-30-11-01).
# Maker-arb cells are canonical ``asset_tf`` tokens where:
#   * asset ∈ {btc, eth, sol}
#   * tf    ∈ {5m, 15m}
# Anything else (e.g. ``btcnotf``) MUST raise at boot — the alternative is
# spawning a malformed strategy that silently no-ops for the life of the
# process. Fail-fast > silent failure at $100k+.
_CELL_RE = __import__("re").compile(r"^(btc|eth|sol)_(5m|15m)$")


def _parse_cell(cell_str: str) -> tuple[str, str]:
    """Parse a maker-arb cell token into ``(asset_upper, tf)``.

    >>> _parse_cell("btc_15m")
    ('BTC', '15m')

    Raises:
        ValueError: when ``cell_str`` does not match the canonical
            ``^(btc|eth|sol)_(5m|15m)$`` form (T-30-11-01).
    """
    m = _CELL_RE.match(cell_str.strip())
    if m is None:
        raise ValueError(
            f"invalid maker-arb cell {cell_str!r}; "
            "must match ^(btc|eth|sol)_(5m|15m)$ (T-30-11-01)"
        )
    return m.group(1).upper(), m.group(2)


async def _run_poly_allowance_preflight(
    settings: Any,
    has_live_controller: bool,
    *,
    get_secret_fn: Any,
    alert_factory: Any,
    db_pool: Any,
) -> bool:
    """Phase 26.1 LIVE-ALLOW-03 — boot-time Polymarket USDC allowance preflight.

    DORMANT in Phase 26.1 — `has_live_controller` is always False at boot
    (no `mode='live'` Polymarket controllers exist anywhere in this phase);
    the gate skips silently. Activates in Phase 26.3 when live mirror
    controllers spawn (per CONTEXT D-05).

    Behavior contract (CONTEXT D-05 + plan 26.1-05):
    - has_live_controller=False → return False (no force-paper needed; dormancy path)
    - has_live_controller=True AND allowance OK → return False (preflight pass)
    - has_live_controller=True AND allowance < threshold (LiveModeForbidden):
        - log CRITICAL `polymarket.allowance.preflight_failed`
        - emit CRITICAL alert via Phase 20 alert_factory
        - INSERT `kind='live_mirrors_blocked'` audit row to trading.events
        - return True (force_paper_mode flag — Phase 26.3 controllers consume)
        - do NOT re-raise (engine continues booting in paper mode)

    Args:
        settings: app.core.config.Settings (or test shim).
        has_live_controller: True if any `mode='live'` Polymarket controller is
            configured. In Phase 26.1: always False (no live controllers exist).
        get_secret_fn: callable resolving POLY_FUNDER_ADDRESS from SecretsRegistry.
        alert_factory: callable building/returning an AlertService for the
            CRITICAL emit. Production: ``build_alert_service`` (Phase 20); tests:
            lambda returning a MagicMock.
        db_pool: asyncpg pool for trading.events audit-row INSERT.

    Returns:
        bool — force_paper_mode flag. True iff live mode was refused; Phase
        26.3 controllers MUST read this from ``app.state.poly_force_paper_mode``
        at ctor time and downgrade themselves to paper.
    """
    import json as _json

    # Dormancy path (Phase 26.1 reality): no live controller configured.
    if not has_live_controller:
        logger.info(
            "polymarket.allowance.preflight_skipped",
            reason="no_live_controllers_configured",
            phase="26.1_dormant",
        )
        return False

    # Live-mode preflight — Phase 26.3 path. Constructs AsyncWeb3, resolves
    # wallet, calls assert_live_polymarket_allowance, catches LiveModeForbidden.
    from web3 import AsyncHTTPProvider, AsyncWeb3

    # 2026-05-20 — fall back to `poly_proxy_address` (the key the /settings UI
    # writes via Phase 17.2 SECRETS-UI-03). PolymarketClient already uses
    # this fallback at ctor time (venues/polymarket/client.py:175) but the
    # preflight didn't, so it force-paper-moded even when the wallet was
    # set via the UI. Symptom: `polymarket.allowance.preflight_no_wallet`
    # critical at boot despite `proxy_bound: true` in polymarket_client.ctor.
    wallet = (
        get_secret_fn("POLY_FUNDER_ADDRESS")
        or get_secret_fn("poly_proxy_address")
    )
    if not wallet:
        logger.critical(
            "polymarket.allowance.preflight_no_wallet",
            hint=(
                "set POLY_FUNDER_ADDRESS env var OR poly_proxy_address via "
                "/settings/secrets before live mode"
            ),
        )
        return True

    w3 = AsyncWeb3(AsyncHTTPProvider(settings.tv_poly_rpc_url))
    try:
        await assert_live_polymarket_allowance(
            w3=w3,
            settings=settings,
            wallet=wallet,
            has_live_controller=True,
        )
    except LiveModeForbidden as exc:
        logger.critical(
            "polymarket.allowance.preflight_failed",
            reason=str(exc),
            action="force_paper_mode",
        )
        # Phase 20 CRITICAL alert — Pushover + Discord.
        try:
            alerts = alert_factory(settings)
            await alerts.send(
                severity="critical",
                message=f"Live mirrors blocked: {exc}",
                source="poly_allowance_preflight",
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("alert_service_failed_during_preflight")
        # Audit row — `kind='live_mirrors_blocked'` is operator-monitorable.
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (kind, at, data) "
                    "VALUES ($1, now(), $2::jsonb)",
                    "live_mirrors_blocked",
                    _json.dumps({"reason": str(exc), "phase": "26.1_preflight"}),
                )
        except Exception:  # pragma: no cover — defensive
            logger.exception("audit_row_failed_during_preflight")
        return True

    # Preflight passed; live mode allowed to proceed (Phase 26.3 path).
    return False


async def _run_poly_redeemer_preflight(
    settings: Any,
    has_live_controller: bool,
    *,
    redeemer_enabled: bool,
    alert_factory: Any,
    db_pool: Any,
) -> bool:
    """Phase 26.2 LIVE-REDEEM-03 — boot-time redeemer pre-flight gate.

    DORMANT in Phase 26.2 — `has_live_controller` is always False; full
    activation in Phase 26.3 when live mirror controllers spawn. Wired so
    Phase 26.3 cannot enable live mode without the redeemer up. Otherwise
    every live win drains wallet (un-redeemed CTF tokens lock USDC).

    Behavior contract (CONTEXT D-07 + plan 26.2-06):
    - has_live_controller=False → return False (no force-paper; dormancy path)
    - has_live_controller=True AND redeemer_enabled=True → return False (pass)
    - has_live_controller=True AND redeemer_enabled=False:
        - log CRITICAL `poly_redeemer.preflight_failed`
        - emit CRITICAL alert via Phase 20 alert_factory
        - INSERT `kind='live_mirrors_blocked'` audit row to trading.events
        - return True (force_paper_mode flag — Phase 26.3 controllers consume)
        - do NOT re-raise (engine continues booting in paper mode)

    Args:
        settings: app.core.config.Settings (or test shim).
        has_live_controller: True if any `mode='live'` Polymarket controller is
            configured. In Phase 26.2: always False (no live controllers).
        redeemer_enabled: whether TV_POLY_REDEEMER_ENABLED is true AND task
            spawn succeeded (i.e. the redeemer loop is registered + running).
        alert_factory: callable building/returning an AlertService for the
            CRITICAL emit (production: build_alert_service; tests: MagicMock).
        db_pool: asyncpg pool for trading.events audit-row INSERT.

    Returns:
        bool — force_paper_mode flag. True iff live mode was refused.
    """
    import json as _json

    # Dormancy path (Phase 26.2 reality): no live controller configured.
    if not has_live_controller:
        logger.info(
            "poly_redeemer.preflight_skipped",
            reason="no_live_controllers_configured",
            phase="26.2_dormant",
            redeemer_enabled=redeemer_enabled,
        )
        return False

    # Live-mode path — Phase 26.3 activation. Refuse if redeemer not running.
    if redeemer_enabled:
        logger.info(
            "poly_redeemer.preflight_passed",
            has_live_controller=True,
            redeemer_enabled=True,
        )
        return False

    logger.critical(
        "poly_redeemer.preflight_failed",
        reason="redeemer_not_running",
        action="force_paper_mode",
    )
    # Phase 20 CRITICAL alert — Pushover + Discord.
    try:
        alerts = alert_factory(settings)
        await alerts.send(
            severity="critical",
            message=(
                "Live mirrors blocked: TV_POLY_REDEEMER_ENABLED=false but live "
                "Polymarket controllers configured. Wallet would drain without "
                "auto-redemption. Forcing paper mode for all controllers."
            ),
            source="poly_redeemer_preflight",
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception("alert_service_failed_during_redeemer_preflight")
    # Audit row — `kind='live_mirrors_blocked'` is operator-monitorable.
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO trading.events (kind, at, data) "
                "VALUES ($1, now(), $2::jsonb)",
                "live_mirrors_blocked",
                _json.dumps(
                    {"reason": "redeemer_not_running", "phase": "26.2_preflight"}
                ),
            )
    except Exception:  # pragma: no cover — defensive
        logger.exception("audit_row_failed_during_redeemer_preflight")
    return True


# ---------------------------------------------------------------------------
# Phase 29-15: Polymarket mint-and-sell v2 lifespan helpers
# ---------------------------------------------------------------------------
# Decisions D-12 (per-slug lifecycle), D-13 (4-concurrent cap), D-25 (lifespan
# replaces deleted shadow spawn). I-12 fix: `live_oncexec.validate()` is called
# explicitly — NOT the v1 plan's __aenter__/__aexit__ misuse.
#
# The supervisor lives at module level so unit tests can drive it directly
# with mocked schedulers + a stub asyncpg pool. The lifespan body in `_amain`
# only constructs deps + creates the supervisor task; the cap-enforcement
# logic is here so test 08 can fire 5 events at cap=4 against a pure helper.


async def slug_cycle_supervisor(
    schedulers: list[Any],
    executors: dict[str, Any],
    settings: Any,
    pool: Any,
    book_mirror: Any,
    alerts: Any,
    oracle_v2: Any,
    mode: str,
    stop: asyncio.Event,
) -> None:
    """Consume `SlotStartEvent`s from N schedulers; spawn SlotCycle tasks.

    Enforces the D-13 4-concurrent cap. Beyond-cap events are audited as
    `poly_mint_sell_v2_dropped` rows and skipped (no SlotCycle spawn).

    Args:
        schedulers: list of `SlotScheduler` (BTC/ETH/SOL × 5m/15m, max 6).
        executors: ``{"oncexec": OnChainExecutorProtocol, "clob": CLOBClientProtocol}``.
        settings: app.core.config.Settings — supplies max_concurrent_slugs.
        pool: asyncpg.Pool — used for the dropped-event audit row.
        book_mirror: shared TV-native BookMirror.
        alerts: AlertService for critical fanout from SlotCycle halts.
        oracle_v2: OnchainOracle for slot-end resolution.
        mode: "paper" | "live" — feeds into sleeve_id suffix (D-20).
        stop: asyncio.Event — when set, supervisor cancels feeders + cycles
            and returns cleanly.

    CLAUDE inv #7: this function is NOT exposed via any HTTP/WS/agent
    surface. Halt is internal-only via env-var flip + restart.
    """
    import json  # local import — supervisor is rarely-imported at boot
    from backend.app.services.poly_mint_sell_v2 import (
        book_subscriber as v2_book_sub,
    )
    from backend.app.services.poly_mint_sell_v2 import (
        monitor as v2_monitor,
    )
    from backend.app.services.poly_mint_sell_v2 import (
        order_manager as v2_order_manager,
    )
    from backend.app.services.poly_mint_sell_v2 import (
        slot_cycle as v2_cycle,
    )

    active_cycles: set[asyncio.Task[Any]] = set()
    max_concurrent = int(settings.tv_poly_mint_sell_v2_max_concurrent_slugs)
    event_q: asyncio.Queue[Any] = asyncio.Queue()

    async def _feed(sched: Any) -> None:
        """Pull events from one scheduler into the shared queue."""
        try:
            async for evt in sched.run():
                if stop.is_set():
                    sched.cancel()
                    return
                await event_q.put(evt)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — one feeder bug must not kill the rest
            logger.exception(
                "poly_mint_sell_v2.feed.crashed",
                asset=getattr(sched, "asset", "?"),
                tf=getattr(sched, "tf", "?"),
            )

    feeder_tasks = [
        asyncio.create_task(
            _feed(s), name=f"v2.feed.{s.asset}_{s.tf}"
        )
        for s in schedulers
    ]
    try:
        while not stop.is_set():
            try:
                evt = await asyncio.wait_for(event_q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            # Reap done cycles before checking the cap.
            active_cycles = {t for t in active_cycles if not t.done()}

            # D-13: refuse beyond-cap events; audit and skip.
            if len(active_cycles) >= max_concurrent:
                sleeve_id = (
                    f"poly_mint_sell_v2_{evt.asset.lower()}_"
                    f"{evt.tf}_{mode}"
                )
                if pool is not None:
                    try:
                        async with pool.acquire() as conn:
                            await conn.execute(
                                "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                                "VALUES (now(), $1, $2, $3::jsonb)",
                                sleeve_id,
                                "poly_mint_sell_v2_dropped",
                                json.dumps(
                                    {
                                        "reason": "max_concurrent_cap",
                                        "concurrent_count": len(active_cycles),
                                        "slot_start_unix": evt.slot_start_unix,
                                        "cap": max_concurrent,
                                    }
                                ),
                            )
                    except Exception:  # noqa: BLE001 — audit must not mask
                        logger.exception(
                            "poly_mint_sell_v2.dropped_audit_failed",
                            asset=evt.asset,
                            tf=evt.tf,
                        )
                logger.warning(
                    "poly_mint_sell_v2.dropped",
                    reason="cap",
                    asset=evt.asset,
                    tf=evt.tf,
                    cap=max_concurrent,
                    slot_start_unix=evt.slot_start_unix,
                )
                continue

            # B-02 corollary: SlotStartEvent.clob_token_ids is a tuple[str, str].
            book_sub = v2_book_sub.BookSubscriber(
                book_mirror=book_mirror,
                token_id_up=evt.clob_token_ids[0],
                token_id_dn=evt.clob_token_ids[1],
            )
            ord_mgr = v2_order_manager.OrderManager(settings=settings)
            hmonitor = v2_monitor.HealthMonitor(settings=settings)
            # Hotfix 9 (2026-05-18): in PAPER mode, give each SlotCycle its
            # OWN PaperCLOBClient. Reason: PaperCLOBClient holds a single
            # `_fill_callback` slot — when N concurrent SlotCycles all call
            # `set_fill_callback(self._on_fill)`, only the last setter wins,
            # so fills route to the WRONG SlotCycle's inventory and we get
            # `oversell` critical alerts (held_X < qty). Per-cycle instance
            # gives each cycle its own _orders + _fill_callback state.
            # LIVE mode keeps the shared `executors["clob"]` because
            # LiveCLOBClient owns a single user-WS connection across cells.
            if mode == "paper":
                from backend.app.services.poly_mint_sell_v2 import (
                    clob_paper as _v2_clob_paper,
                )
                cycle_clob = _v2_clob_paper.PaperCLOBClient()
            else:
                cycle_clob = executors["clob"]
            cycle = v2_cycle.SlotCycle(
                event=evt,
                mode=mode,
                settings=settings,
                pool=pool,
                book_subscriber=book_sub,
                order_manager=ord_mgr,
                oncexec=executors["oncexec"],
                clob=cycle_clob,
                monitor=hmonitor,
                oracle=oracle_v2,
                alerts=alerts,
            )
            task = asyncio.create_task(
                cycle.run(),
                name=f"v2.cycle.{cycle.sleeve_id}.{evt.slot_start_unix}",
            )
            active_cycles.add(task)
    finally:
        # Cancel feeders + in-flight cycles; await all (return_exceptions
        # so a single feeder/cycle CancelledError doesn't shadow the rest).
        for t in feeder_tasks:
            t.cancel()
        for t in active_cycles:
            t.cancel()
        if feeder_tasks or active_cycles:
            await asyncio.gather(
                *feeder_tasks, *active_cycles, return_exceptions=True
            )


def _spawn_v2_for_cells(
    tg: asyncio.TaskGroup,
    stop: asyncio.Event,
    cells: list[str],
    executors: dict[str, Any],
    settings: Any,
    pool: Any,
    book_mirror: Any,
    discovery: Any,
    alerts: Any,
    oracle_v2: Any,
    mode: str,
) -> None:
    """Build N `SlotScheduler` instances for `cells` and spawn one supervisor.

    Cells are `{asset_lc}_{tf}` strings (e.g. ``"btc_5m"``). Invalid entries
    (missing underscore, unknown asset/tf) are skipped silently with a
    warning. Valid asset/tf pairs are: BTC/ETH/SOL × 5m/15m.

    The supervisor task lives in the same TaskGroup as `poly_updown_scheduler`
    + `poly_redeemer_loop`; a crashed supervisor cancels the group (TaskGroup
    semantics) and triggers engine shutdown.
    """
    from backend.app.services.poly_mint_sell_v2 import slot_scheduler as v2_sched

    schedulers: list[Any] = []
    for cell in cells:
        if "_" not in cell:
            logger.warning(
                "poly_mint_sell_v2.cell_malformed", cell=cell
            )
            continue
        asset_lc, tf = cell.split("_", 1)
        asset_uc = asset_lc.upper()
        if asset_uc not in ("BTC", "ETH", "SOL") or tf not in ("5m", "15m"):
            logger.warning(
                "poly_mint_sell_v2.cell_unsupported",
                cell=cell,
                asset=asset_uc,
                tf=tf,
            )
            continue
        schedulers.append(
            v2_sched.SlotScheduler(asset=asset_uc, tf=tf, discovery=discovery)
        )

    if not schedulers:
        logger.warning(
            "poly_mint_sell_v2.no_valid_cells", input_cells=cells
        )
        return

    tg.create_task(
        slug_cycle_supervisor(
            schedulers,
            executors,
            settings,
            pool,
            book_mirror,
            alerts,
            oracle_v2,
            mode,
            stop,
        ),
        name=f"v2.supervisor.{mode}",
    )
    logger.info(
        "poly_mint_sell_v2.supervisor_spawned",
        mode=mode,
        cells=len(schedulers),
        cell_names=[f"{s.asset.lower()}_{s.tf}" for s in schedulers],
    )


async def _amain() -> int:
    """Async main: configure logging, open pool, run TaskGroup until stop."""
    configure_logging()
    settings = get_settings()
    logger.info("tv-engine.starting", unit="tv-engine")

    # Phase 7.1 DATA-11: boot gate FIRST. HL_LIVE_ACK present while
    # TV_BAR_SOURCE=storedata is a fatal misconfiguration — we refuse to
    # boot before any DB work, so the check fires even if storedata DSN
    # is missing. (Moved ahead of DSN check 2026-04-24 after VPS unit
    # `test_engine_main_refuses_boot_on_conflict` failed silently.)
    _live_ack = Path(
        os.getenv("HL_LIVE_ACK_PATH", "/etc/tv/HL_LIVE_ACK"),
    ).exists()
    _bar_source = os.getenv("TV_BAR_SOURCE", "storedata")
    if check_bar_source_alignment(_live_ack, _bar_source) == "conflict":
        logger.error(
            "tv_engine.boot_refused",
            reason="HL_LIVE_ACK present but TV_BAR_SOURCE=storedata",
            ack_path=os.getenv("HL_LIVE_ACK_PATH", "/etc/tv/HL_LIVE_ACK"),
            bar_source=_bar_source,
        )
        raise RuntimeError(
            "HL_LIVE_ACK present but TV_BAR_SOURCE=storedata — refusing boot (DATA-11)"
        )

    # Phase 17.2 deploy fix (2026-04-27): tv-engine needs TWO pools.
    # The previous single-pool design used `tv_storedata_db_url` (RO user)
    # for everything, which silently failed every write to trading.*/engine.*
    # Now: write_pool (tradingvenue user) for TV-owned writes; read_pool
    # (tradingvenue_ro user) for public.* reads (only used by writer_health
    # probe_loop). Both pools target the same storedata DB per Phase 2.4 D-05.
    write_dsn = settings.tv_db_url.get_secret_value()
    if not write_dsn:
        logger.critical(
            "tv-engine.tv_db_url_empty",
            hint="set TV_DB_URL in /etc/tv/tradingvenue.env",
        )
        return 1

    read_dsn = settings.tv_storedata_db_url.get_secret_value()
    if not read_dsn:
        logger.critical(
            "tv-engine.tv_storedata_db_url_empty",
            hint="set TV_STOREDATA_DB_URL in /etc/tv/tv-ro.env",
        )
        return 1

    pool = await asyncpg.create_pool(write_dsn, min_size=1, max_size=4)
    # Phase 24.1 (2026-05-05): bumped read_pool from 2 → 16 to handle the
    # parallel kline + sample + cid + token_id fetches in
    # ``build_bar_context``. With 3 symbols × ~8 DB ops each = 24 concurrent
    # queries; pool=2 created a queue depth that ballooned latency to 71s/
    # boundary. Pool=16 fits the parallel demand cleanly.
    read_pool = await asyncpg.create_pool(read_dsn, min_size=2, max_size=16)
    alerts = build_alert_service(settings, logger, db_pool=pool)

    # Phase 17.2 SECRETS-UI-03 — record this boot in trading.engine_boots
    # so tv-api's GET /settings/secrets can surface "engine restart
    # pending" if the operator rotated a credential after the row was
    # written.  Done BEFORE the TaskGroup so a startup crash leaves an
    # auditable boot row even if reconcile_or_exit aborts.
    await record_engine_boot(
        pool,
        version=__version__,
        git_sha=os.environ.get("TV_GIT_SHA", "unknown"),
    )

    # Load encrypted credentials from trading.secrets into a frozen
    # SecretsRegistry. Empty registry (0 rows) is valid; the venue
    # clients fall back to env vars per CLAUDE.md inv #8.
    secrets_registry = await load_secrets_registry(pool)
    logger.info(
        "tv-engine.secrets_registry.loaded",
        count=len(secrets_registry.kinds),
    )

    # ---- Phase 26.1 LIVE-ALLOW-03: Polymarket allowance preflight gate ----
    # DORMANT in Phase 26.1 — has_live_controller is always False; full
    # activation in Phase 26.3 when live mirror controllers spawn. Wired
    # here so the FIRST attempt to enable live mode in 26.3 cannot start
    # without green allowance. Per CONTEXT D-05 + plan 26.1-05.
    #
    # Order: Phase 26-04 config preflight (RPC URL non-None) FIRST, then
    # Phase 26.1 allowance preflight (on-chain read). Both gated by the
    # same has_live_controller flag — single source of truth.
    from backend.app.core.config import assert_live_polymarket_config

    # In Phase 26.1: NO `mode='live'` PolymarketUpdownController exists
    # in this lifespan body — every instantiation below uses mode="paper".
    # Phase 26.3 will replace this False with a real enumeration over
    # the configured controller manifests.
    #
    # 2026-05-16 — derive from TV_POLY_LIVE_ALLOWLIST so the redeemer +
    # allowance preflights run when live mirrors are configured. Previously
    # hardcoded to False, which preflight-skipped the redeemer at boot,
    # leaving it dormant even after _spawn_live_mirrors constructed the
    # live controllers a few hundred ms later (see /redeemer/status
    # running:false bug observed 2026-05-15).
    _live_allowlist_csv = (settings.tv_poly_live_allowlist or "").strip()
    has_live_controller = bool(_live_allowlist_csv)
    assert_live_polymarket_config(settings, has_live_controller)
    app_state_poly_force_paper_mode = await _run_poly_allowance_preflight(
        settings=settings,
        has_live_controller=has_live_controller,
        get_secret_fn=secrets_registry.get,
        alert_factory=lambda s: build_alert_service(s, logger, db_pool=pool),
        db_pool=pool,
    )
    # Phase 26.3 controllers will read this flag at ctor time. Until then
    # it's a published handle for /overview + future controller wiring.
    logger.info(
        "polymarket.allowance.preflight_result",
        force_paper_mode=app_state_poly_force_paper_mode,
        has_live_controller=has_live_controller,
        phase="26.1",
    )

    # ---- Phase 26.2 LIVE-REDEEM-03: Polymarket redeemer preflight gate ----
    # DORMANT in Phase 26.2 — has_live_controller is always False; full
    # activation in Phase 26.3. Refuses live mode if redeemer task is not
    # registered (TV_POLY_REDEEMER_ENABLED=false). Otherwise wins lock USDC
    # in un-redeemed CTF tokens — wallet drains after ~30 wins. Per CONTEXT
    # D-07 + plan 26.2-06.
    #
    # OR-combines with the 26.1 force_paper_mode flag — either gate failing
    # forces paper for all controllers.
    poly_redeemer_enabled = (
        os.getenv("TV_POLY_REDEEMER_ENABLED", "false").lower() == "true"
    )
    _redeemer_force_paper = await _run_poly_redeemer_preflight(
        settings=settings,
        has_live_controller=has_live_controller,
        redeemer_enabled=poly_redeemer_enabled,
        alert_factory=lambda s: build_alert_service(s, logger, db_pool=pool),
        db_pool=pool,
    )
    app_state_poly_force_paper_mode = (
        app_state_poly_force_paper_mode or _redeemer_force_paper
    )
    logger.info(
        "poly_redeemer.preflight_result",
        force_paper_mode=app_state_poly_force_paper_mode,
        has_live_controller=has_live_controller,
        redeemer_enabled=poly_redeemer_enabled,
        phase="26.2",
    )

    # Phase 17.2 SECRETS-UI-03 — Polymarket client constructed with the
    # registry so set_max_usdc_allowance() has a signer key. This is the
    # sole component that signs ERC20 approve txs on Polygon (CONTEXT.md
    # D-04). The polygon RPC URL flows through `_wait_for_n_confirmations`
    # in the _engine_tasks_worker; the same URL also overrides the
    # client-internal RPC for raw eth_sendRawTransaction.
    poly_settings = get_poly_settings()
    # Phase 18.6 W1.B (audit 2026-05-06): live PolymarketClient gets the
    # same 3-tier book read path as paper executor — BookMirror Tier-1 +
    # CLOB SDK Tier-2 + Storedata Tier-3 (with critical alert). Hot-path
    # convergence per CLAUDE inv #13. book_mirror is constructed inside
    # the TV_POLY_UPDOWN_ENABLED block below; we set it on poly_client via
    # attribute assignment after that block runs.
    poly_client = PolymarketClient(
        poly_settings,
        secrets_registry=secrets_registry,
        pg_pool=read_pool,
        alert_service=alerts,
    )
    poly_client._rpc_url = settings.polygon_rpc_url

    # Phase 16 BACKUP-06: boot-time EXACT-match position reconciliation.
    # Runs BEFORE the TaskGroup so any DB/venue divergence triggers
    # sys.exit(1) before any sibling task starts mutating state. Empty
    # venue_clients (paper-mode / pre-Phase-14/15) → trivial pass.
    venue_clients: dict[str, Any] = {}
    await reconcile_or_exit(pool=pool, alerts=alerts, venue_clients=venue_clients)

    # Phase 16 BACKUP-07: 5-min position snapshot directory. Default
    # under repo-relative `data/snapshots/`; operator can repoint to a
    # persistent volume mount via TV_SNAPSHOT_DIR.
    snapshot_dir = Path(os.getenv("TV_SNAPSHOT_DIR", "data/snapshots"))

    stop = asyncio.Event()

    def _handle_signal(*_args: Any) -> None:
        logger.info("tv-engine.signal_received")
        stop.set()

    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _handle_signal)
    except NotImplementedError:
        # Windows dev boxes - signal handlers not supported. Production
        # systemd runs on Linux where add_signal_handler works.
        pass

    # Phase 18.2 — LiqDB handle for V3.2 / V4 liq_quiet gate. Defined at
    # _amain scope so the finally block can close the pool cleanly. Lazy-
    # init happens inside the TV_POLY_UPDOWN_ENABLED block below — gated
    # by V3_2_ENABLED or V4_ENABLED. Stays None when neither variant is
    # enabled (default OK because the controller's v3_2_liq_quiet_passes
    # helper handles None via Exception catch — fail-open per D-05).
    liq_db: Any = None
    # Phase 18.6 W1 — BookMirror lifecycle hoisted to function scope so
    # the finally teardown sees it.
    book_mirror: Any = None
    # Phase 22.1 — TV-native Binance kline feed lifecycle (CLAUDE.md inv #13).
    # Hoisted to function scope so finally teardown can stop() the WS reader
    # task and unbind from bars._FEED_INSTANCE cleanly.
    binance_feed: Any = None
    # Phase 27 LIVE-DISC-01 — TV-native PolyMarketDiscovery lifecycle
    # (CLAUDE.md inv #13). Hoisted so finally teardown can stop() the refresh
    # task and unsubscribe BookMirror tokens cleanly before pool teardown.
    discovery: Any = None
    _discovery_gamma: Any = None
    # Phase 32 Plan 32-10 — MakerFillSimulator lifecycle hoisted to function
    # scope so the finally teardown can stop() the sim cleanly before pool
    # teardown. Instantiated only when tv_poly_maker_enabled + not sim_disabled.
    _maker_fill_sim: Any = None
    # Phase 36-07 — KalshiMarketDataFeed lifecycle hoisted to function scope so
    # the finally teardown can stop() the WS reader before pool teardown
    # (mirror book_mirror hoist at line ~967). Instantiated only when
    # tv_kalshi_enabled=True (default False → engine boots byte-identical).
    kalshi_feed: Any = None

    try:
        async with asyncio.TaskGroup() as tg:
            register_alert_loops(tg, alerts, settings, stop, pool=pool)
            tg.create_task(
                probe_loop(
                    pool=read_pool,  # public.* reads via RO user (tradingvenue_ro)
                    manifest=MANIFEST,
                    alert_service=alerts,
                    stop=stop,
                ),
                name="writer_health.probe_loop",
            )
            tg.create_task(
                retention_sweep_loop(
                    pool=pool,
                    alert_service=alerts,
                    stop=stop,
                    retention_days=int(
                        os.getenv("TV_HL_DATA_RETENTION_DAYS", "7"),
                    ),
                ),
                name="hl_retention.sweep_loop",
            )
            # Phase 16 BACKUP-07: position snapshot writer — sibling task,
            # NOT bolted onto BarEngine wake/eval (CLAUDE.md invariant #12
            # race protection). 300s monotonic cadence; 48h pruner.
            tg.create_task(
                snapshot_writer.run(
                    venue_clients=venue_clients,
                    snapshot_dir=snapshot_dir,
                    stop=stop,
                ),
                name="snapshot_writer.run",
            )
            # HLMarketDataFeed runs only in hl_live mode — storedata mode
            # has nothing to feed from the HL WS side.
            if os.getenv("TV_BAR_SOURCE", "storedata") == "hl_live":
                controllers = _enumerate_hl_controllers()
                feed = HLMarketDataFeed(
                    settings=HLFeedSettings(),
                    pool=pool,
                    alert_service=alerts,
                    controllers=controllers,
                )
                tg.create_task(feed.run(stop), name="hl_feed.run")
            # Phase 8.1 Task 11+15: V52 controller registration + daily rebalance loop.
            # Wired only when TV_V52_REBALANCE_ENABLED=1.
            #
            # Phase 8.1 in-flight 2026-04-29 (Option A wire): the original
            # plan deferred the controller registration to "operator's runner
            # script" which never materialized — `register_v52_controllers`
            # was never called, `engine.v52_streams` stayed empty, and the
            # rebalance loop iterated 0 streams (silent no-op). This block
            # closes that gap by:
            #   1. Seeding `engine.v52_streams` from ALL_V52_CONTROLLERS
            #      (idempotent — ON CONFLICT DO NOTHING)
            #   2. Calling register_v52_controllers with a lightweight
            #      shadow-portfolio adapter that routes register_hl_controller
            #      to the module-level _HL_CONTROLLERS list (so the HL feed
            #      subscribes to V52 (symbol, tf) pairs)
            #   3. Honoring TV_V52_LIVE_OK gate at the controller level
            #      (paper_only=True until flag flips)
            #
            # Shadow equity: TV_V52_SHADOW_EQUITY_USD (default $10000) so
            # rebalance targets compute non-zero weights and stream_snapshots
            # are observable. Live mode replaces this with a real provider
            # tied to portfolio.total_equity().
            if os.getenv("TV_V52_REBALANCE_ENABLED") == "1":
                from pathlib import Path as _Path

                from backend.app.controllers.v52 import ALL_V52_CONTROLLERS
                from backend.app.controllers.v52._register import (
                    register_v52_controllers,
                )
                from backend.app.engine.v52_rebalance import v52_rebalance_loop

                # 1. Seed engine.v52_streams from canonical controller list.
                async with pool.acquire() as _v52_conn:
                    for _ctrl in ALL_V52_CONTROLLERS:
                        await _v52_conn.execute(
                            "INSERT INTO engine.v52_streams "
                            "(stream_id, sleeve_class, sub_account, symbol) "
                            "VALUES ($1, $2, $3, $4) "
                            "ON CONFLICT (stream_id) DO NOTHING",
                            _ctrl.stream_id,
                            type(_ctrl).__name__,
                            _ctrl.sub_account,
                            _ctrl.symbol,
                        )

                # 2. Lightweight shadow-portfolio adapter — delegates
                # register_hl_controller to module-level register_hl_controller
                # so the HL feed subscribes V52 (symbol, tf) pairs. Kill switch
                # is parked as a no-op until live-mode wires a real portfolio
                # with executor + tier config (Phase 8 HyperliquidPortfolio).
                class _V52ShadowPortfolio:
                    def register_hl_controller(self, ctrl: Any) -> None:
                        register_hl_controller(ctrl)

                    def add_secondary_kill_switch(self, ks: Any) -> None:
                        # paper-only: kill switch parked. Live wire-up swaps
                        # this for real HyperliquidPortfolio.
                        pass

                # 3. Resolve regime artifact directory. None if missing →
                # controllers init without regime gating (cold-start path);
                # they no-op until JSON artifacts land.
                _v52_regime_dir_env = os.environ.get(
                    "TV_V52_REGIME_DIR", "/var/lib/tradingvenue/v52"
                )
                _v52_regime_dir: _Path | None = _Path(_v52_regime_dir_env)
                if not _v52_regime_dir.exists():
                    logger.warning(
                        "v52.regime_dir.missing",
                        path=_v52_regime_dir_env,
                        hint="run scripts/v52/fit_regime.py --all to seed",
                    )
                    _v52_regime_dir = None

                # 4. Register all 10 V52 controllers.
                _v52_registered = register_v52_controllers(
                    portfolio=_V52ShadowPortfolio(),
                    meta_cache=None,  # symbol-listed check skipped in shadow
                    regime_dir=_v52_regime_dir,
                )
                logger.info(
                    "v52.registered",
                    n=len(_v52_registered),
                    stream_ids=_v52_registered,
                )

                # 5. Shadow equity for rebalance target computation.
                _v52_shadow_equity = float(os.environ.get("TV_V52_SHADOW_EQUITY_USD", "10000"))

                tg.create_task(
                    v52_rebalance_loop(
                        pool=pool,
                        portfolio_equity_provider=lambda: _v52_shadow_equity,
                        stop=stop,
                    ),
                    name="v52_rebalance.loop",
                )
            # Phase 17.2 SECRETS-UI-03 — engine_tasks worker. Picks
            # rows from trading.engine_tasks via FOR UPDATE SKIP LOCKED
            # (T-17.2-13 prevents double-pick under concurrent workers),
            # flips status to 'broadcast' BEFORE chain submit, then
            # invokes poly_client.set_max_usdc_allowance() and waits
            # for confirmations via _wait_for_n_confirmations.
            tg.create_task(
                _engine_tasks_worker(
                    pool=pool,
                    poly_client=poly_client,
                    polygon_rpc_url=settings.polygon_rpc_url,
                    stop=stop,
                ),
                name="engine_tasks_worker",
            )
            # Phase 26.2 — Polymarket on-chain redemption loop (LIVE-REDEEM-01).
            # DORMANT in Phase 26.2 — operator opt-in via TV_POLY_REDEEMER_ENABLED;
            # 26.3 flips the default once the live mirrors ship. Without this,
            # every winning live fire locks USDC in un-redeemed CTF tokens.
            # The `poly_redeemer_running` flag on `redeemer_app_state` is read
            # by the /redeemer/status endpoint + the boot pre-flight gate.
            # Failure-handling: any spawn-time error (missing key, missing RPC
            # URL) is caught + logged; the flag stays False but engine boot
            # continues (T-26.2-18 — TaskGroup must not die from one bad spawn).
            #
            # Phase 26.3-03 ordering note: this block was MOVED above the
            # TV_POLY_UPDOWN_ENABLED block (was after, pre-26.3). The
            # `_spawn_live_mirrors` preflight (Phase 26.3) reads
            # `redeemer_app_state.poly_redeemer_running` as gate 5; that flag
            # must be set to True BEFORE the live-mirror spawn runs. Reordering
            # is safe — the redeemer block has zero deps on the poly_updown
            # block's locals.
            import types as _types

            redeemer_app_state = _types.SimpleNamespace(
                poly_redeemer_running=False,
            )
            if poly_redeemer_enabled:
                try:
                    from eth_account import Account as _EthAccount
                    from web3 import AsyncHTTPProvider as _AsyncHTTPProvider
                    from web3 import AsyncWeb3 as _AsyncWeb3

                    from backend.app.services.poly_redeemer import (
                        poly_redeemer_loop,
                    )
                    from backend.app.venues.polymarket.onchain_oracle import (
                        OnchainOracle,
                    )

                    if not settings.tv_poly_rpc_url:
                        raise RuntimeError(
                            "TV_POLY_REDEEMER_ENABLED=true but tv_poly_rpc_url is unset"
                        )

                    redeemer_w3 = _AsyncWeb3(
                        _AsyncHTTPProvider(settings.tv_poly_rpc_url)
                    )
                    redeemer_oracle = OnchainOracle(
                        rpc_url=settings.tv_poly_rpc_url,
                        ctf_address=settings.tv_poly_ctf_address,
                    )

                    # Resolve operator private key from SecretsRegistry. Key
                    # is `poly_signer_private_key` (Phase 17.2 plumbing).
                    private_key = secrets_registry.get("poly_signer_private_key")
                    if not private_key:
                        raise RuntimeError(
                            "poly_signer_private_key unset in secrets registry"
                        )
                    wallet_address = _EthAccount.from_key(private_key).address
                    redeemer_app_state.poly_wallet_address = wallet_address

                    redeemer_alerts = build_alert_service(
                        settings, logger, db_pool=pool
                    )

                    tg.create_task(
                        poly_redeemer_loop(
                            pool=pool,
                            w3=redeemer_w3,
                            oracle=redeemer_oracle,
                            settings=settings,
                            stop_event=stop,
                            private_key=private_key,
                            wallet=wallet_address,
                            ws_emit=None,
                            alert_service=redeemer_alerts,
                            app_state=redeemer_app_state,
                        ),
                        name="poly_redeemer.loop",
                    )
                    # Belt-and-suspenders: the loop also sets this at entry,
                    # but we set it here too so the pre-flight result reflects
                    # spawn-success even before the loop's first tick.
                    redeemer_app_state.poly_redeemer_running = True
                    logger.info(
                        "poly_redeemer.task_spawned",
                        wallet=wallet_address,
                    )
                except Exception as exc:  # noqa: BLE001 — spawn failure must not kill engine
                    redeemer_app_state.poly_redeemer_running = False
                    logger.error(
                        "poly_redeemer.spawn_failed",
                        error=str(exc),
                    )
            else:
                logger.info(
                    "poly_redeemer.disabled",
                    reason="TV_POLY_REDEEMER_ENABLED!=true",
                )
            # Phase 18.1: Polymarket Updown scheduler. Wired only when
            # TV_POLY_UPDOWN_ENABLED=1 — operator opt-in for shadow runs.
            # Closes the Phase 15 deploy-time gap where the controller was
            # built but never instantiated in tv-engine main. Paper-mode
            # only for now; live-mode flips after 18.1-04 sizing override
            # + 18.1-03 RedemptionWorker land.
            if os.getenv("TV_POLY_UPDOWN_ENABLED") == "1":
                from backend.app.controllers.polymarket_updown import (
                    PolymarketUpdownController,
                )
                from backend.app.engine.poly_updown_loop import (
                    poly_updown_scheduler,
                )
                from backend.app.portfolio import register_poly_updown

                # Phase 18.1 in-flight 2026-04-29: paper executor reads
                # orderbooks from Polymarket CLOB /book directly instead
                # of Storedata snapshots — fixes the 62% qty_compute_failed
                # rate caused by Storedata WS book lag (>30s on 5m, up
                # to 1h on 15m SOL). httpx client is owned by tv-engine
                # process; pool stays as a defense-in-depth fallback.
                # Default base_url tracks PolySettings.clob_host (env
                # TV_POLY_CLOB_HOST overrides) so the V2 cutover flip
                # propagates without code change.
                # Phase 18.2 V2 PAPER_DATA_SOURCE_PATCH: env knobs for the
                # CLOB read path. Defaults track the patch §4 spec.
                _rest_timeout_s = float(os.getenv("TV_POLY_PAPER_REST_TIMEOUT_S", "2.0"))
                _rest_retry_attempts = int(os.getenv("TV_POLY_PAPER_REST_RETRY_ATTEMPTS", "2"))
                _book_cache_ttl = int(os.getenv("TV_POLY_PAPER_BOOK_CACHE_TTL", "1"))
                # Phase 18.6 W0 (2026-05-06) BAND-AID: default ON for
                # shadow mode — CLOB returns empty/None for thin opposite
                # tokens, so a transient cannot produce empty-book without
                # bleeding hedge_skip events. Time-boxed ≤7d; Wave 3 flips
                # default back to "false" once Wave 1's TV-native WS
                # BookMirror is the validated Tier-1.
                # Live mode: this default-ON is FORBIDDEN per CLAUDE.md
                # inv #13. Live executor must wire BookMirror Tier-1 +
                # Storedata Tier-3-with-critical-alert.
                _db_fallback_enabled = (
                    os.getenv("TV_POLY_PAPER_DB_FALLBACK", "true").lower() == "true"
                )
                poly_clob_http = httpx.AsyncClient(
                    base_url=poly_settings.clob_host,
                    timeout=_rest_timeout_s,
                    headers={"User-Agent": "tradingvenue-paper/1.0"},
                )
                # Phase 18.6 W1 — TV-native WS BookMirror as Tier-1 hot-path
                # source. Single multiplexed connection to Polymarket's
                # public market WS; controllers subscribe at slot open,
                # unsubscribe at slot GC. Default OFF (safety: ship code,
                # operator flips on after smoke-verify). When OFF, executor
                # falls through to W0 band-aid (CLOB Tier-1, Storedata Tier-2).
                # Live mode: REQUIRED per CLAUDE.md inv #13 (forbidden to
                # run live with mirror=None).
                _book_mirror_enabled = (
                    os.getenv("TV_POLY_BOOK_MIRROR", "false").lower() == "true"
                )
                if _book_mirror_enabled:
                    from backend.app.venues.polymarket.book_mirror import BookMirror

                    # Phase 28.1: bridge BookMirror snapshots to tv-api via
                    # Redis SET/GET cache. Best-effort — if redis package
                    # missing or connection fails at boot, BookMirror still
                    # works locally and the bridge stays inactive (tv-api
                    # /book-health will return 503 with a clear detail).
                    _redis_client_for_book_mirror: Any | None = None
                    try:
                        import redis.asyncio as redis_asyncio  # type: ignore[import-not-found]

                        _redis_client_for_book_mirror = redis_asyncio.from_url(
                            settings.redis_url,
                            decode_responses=True,
                        )
                        # Ping so we get a fast failure at boot if Redis
                        # is unreachable, surfaced in the log line below.
                        await _redis_client_for_book_mirror.ping()
                        logger.info(
                            "poly_updown.book_mirror_redis_bridge_up",
                            redis_url=settings.redis_url,
                        )
                    except Exception as _redis_err:  # noqa: BLE001
                        logger.warning(
                            "poly_updown.book_mirror_redis_bridge_unavailable",
                            error=str(_redis_err),
                            note=(
                                "BookMirror runs without Redis bridge; "
                                "tv-api /book-health will return 503. "
                                "See Phase 28.1 CONTEXT D-04."
                            ),
                        )
                        _redis_client_for_book_mirror = None

                    book_mirror = BookMirror(
                        alert_service=alerts,
                        redis_client=_redis_client_for_book_mirror,
                    )
                    await book_mirror.start()
                    # Phase 18.6 W1.B (audit 2026-05-06) — wire mirror into
                    # the LIVE PolymarketClient so its get_orderbook_snapshot
                    # 3-tier dispatcher has Tier-1 available. Live + paper
                    # converge on the same hot-path source.
                    poly_client._book_mirror = book_mirror
                    logger.info(
                        "poly_updown.book_mirror_started",
                        live_client_wired=True,
                        redis_bridge=_redis_client_for_book_mirror is not None,
                    )

                # Phase 27 LIVE-DISC-01: TV-native PolyMarketDiscovery service
                # (CLAUDE.md inv #13). Always-on regardless of
                # TV_POLY_LIVE_ALLOWLIST — Plan 27-02 will wire controllers'
                # find() lookups; this ticker is the foundation of the trade
                # loop. Uses a dedicated GammaClient cache file to avoid
                # write contention with the lazy live-mirror GammaClient
                # instantiated downstream at line ~1211.
                from backend.app.venues.polymarket.gamma_client import (
                    GammaClient as _DiscoveryGammaClient,
                )

                _discovery_gamma_cache_path = (
                    settings.tv_poly_gamma_cache_path + ".discovery"
                )
                _discovery_gamma = _DiscoveryGammaClient(
                    base_url=settings.tv_poly_gamma_api_url,
                    cache_path=_discovery_gamma_cache_path,
                )
                discovery = PolyMarketDiscovery(
                    gamma_client=_discovery_gamma,
                    book_mirror=book_mirror,
                    alert_service=alerts,
                    db_pool=read_pool,
                    refresh_interval_s=int(
                        os.getenv("TV_POLY_DISCOVERY_REFRESH_S", "30")
                    ),
                    lookback_min=int(
                        os.getenv("TV_POLY_DISCOVERY_LOOKBACK_MIN", "30")
                    ),
                    lookahead_min=int(
                        os.getenv("TV_POLY_DISCOVERY_LOOKAHEAD_MIN", "15")
                    ),
                )
                await discovery.start()
                # app.state.poly_market_discovery = discovery — tv-engine has
                # no FastAPI app object; controllers receive `discovery` as a
                # constructor kwarg in Plan 27-02 (the comment preserves the
                # 27-01 PLAN.md spec for traceability).
                logger.info(
                    "poly_market_discovery.started",
                    refresh_s=discovery._refresh_interval_s,
                    lookback_min=discovery._lookback_min,
                    lookahead_min=discovery._lookahead_min,
                )

                # Phase 22.1: TV-native Binance kline feed (CLAUDE.md inv #13).
                # Boot ordering: backfill 14d → open WS → wait_ready → bind to
                # bars._FEED_INSTANCE → THEN start scheduler. The poly_updown
                # master scheduler reads from feed via fetch_close_asof's
                # feed-first branch (Phase 22.1-02). When TV_KLINE_FEED_NATIVE
                # =false, this block is skipped and bars._FEED_INSTANCE stays
                # None → the existing Storedata SQL path is used.
                _kline_feed_enabled = (
                    os.getenv("TV_KLINE_FEED_NATIVE", "true").lower() == "true"
                )
                if _kline_feed_enabled:
                    from backend.app.feeds.binance_market_data import (
                        BinanceMarketDataFeed,
                    )
                    from backend.app.data import bars as _bars_module

                    logger.info("binance_feed.boot_starting")
                    # Phase 35 — VWAP continuation needs 1s klines for the
                    # anchored-VWAP cache. Enable when TV_POLY_VWAP_CONT_ENABLED=true
                    # so deploys without VWAP sleeves don't pay the extra WS bandwidth.
                    _vwap_1s = (
                        os.getenv("TV_POLY_VWAP_CONT_ENABLED", "false").lower() == "true"
                    )
                    binance_feed = BinanceMarketDataFeed(
                        alert_service=alerts,
                        enable_1s_stream=_vwap_1s,
                    )
                    try:
                        await binance_feed.backfill_from_rest(days=14)
                        logger.info("binance_feed.backfill_complete")
                        await binance_feed.start()
                        # Timeout 90s: 1m bar closes happen on the minute,
                        # so WS-mid-bar connect can wait up to 60s for the
                        # first k.x=true message that triggers _ready_event.
                        # 30s was tight and raced the close cadence.
                        await binance_feed.wait_ready(timeout_s=90.0)
                        _bars_module.set_feed_instance(binance_feed)
                        logger.info("binance_feed.ready_bound")
                    except (asyncio.TimeoutError, Exception) as e:
                        # Boot-failure path: don't fail the engine. Critical
                        # alert fires; bars module stays in DB-fallback mode
                        # (pre-22.1 behavior) so trading continues degraded
                        # but online. Operator sees the alert in real time.
                        logger.exception(
                            "binance_feed.boot_failed",
                            error=str(e)[:200],
                        )
                        try:
                            from backend.app.services.alert_service import (
                                AlertSeverity,
                            )

                            await alerts.emit(
                                severity=AlertSeverity.CRITICAL,
                                kind="binance_feed_boot_failed",
                                error=str(e)[:200],
                                claude_md_ref="inv #13",
                            )
                        except Exception:  # pragma: no cover
                            logger.exception(
                                "binance_feed.boot_failure_alert_emit_failed"
                            )
                        binance_feed = None
                        _bars_module.set_feed_instance(None)
                else:
                    logger.info(
                        "binance_feed.disabled",
                        reason="TV_KLINE_FEED_NATIVE!=true",
                    )

                paper_executor = PolyPaperExecutor(
                    settings=poly_settings,
                    pg_pool=read_pool,
                    http_client=poly_clob_http,
                    cache_ttl_seconds=_book_cache_ttl,
                    rest_timeout_s=_rest_timeout_s,
                    rest_retry_attempts=_rest_retry_attempts,
                    db_fallback_enabled=_db_fallback_enabled,
                    book_mirror=book_mirror,
                    alert_service=alerts,
                )
                logger.info(
                    "poly_updown.paper_executor_wired",
                    clob_host=poly_settings.clob_host,
                    rest_timeout_s=_rest_timeout_s,
                    rest_retry_attempts=_rest_retry_attempts,
                    cache_ttl_s=_book_cache_ttl,
                    db_fallback_enabled=_db_fallback_enabled,
                    book_mirror_enabled=_book_mirror_enabled,
                )
                # Phase 18.2 V2: parallel strategy-mode controllers.
                # TV_POLY_STRATEGY_MODES=volume[,sniper] — comma list.
                # Default 'volume' preserves VPS2 V1 behavior (single
                # controller, default sleeve_id format). VPS3 sets
                # 'volume,sniper' to run both modes side-by-side.
                modes_csv = os.getenv("TV_POLY_STRATEGY_MODES", "volume")
                strategy_modes = [m.strip() for m in modes_csv.split(",") if m.strip()]
                if not strategy_modes:
                    strategy_modes = ["volume"]
                # Phase 18.2 — extend valid modes to include V3 patches
                # (v3_1, v3_2, v4) per D-09. Existing volume/sniper/v3
                # validation preserved.
                # Phase 18.3 — v3_3 added (V3.2 + multi-horizon for SOL A/B).
                # Phase 18.5 — "momo" added (Binance-latency at t+120s,
                # always spawns 3 controllers per hedge_policy variant
                # when TV_POLY_MOMO_ENABLED=true; gated below).
                _valid_poly_modes = (
                    "volume",
                    "sniper",
                    "v3",
                    "v3_1",
                    "v3_2",
                    "v3_3",
                    "v4",
                    "momo",
                    "momo_v2",
                )
                for sm in strategy_modes:
                    if sm not in _valid_poly_modes:
                        raise ValueError(
                            f"TV_POLY_STRATEGY_MODES contains invalid mode "
                            f"{sm!r}; expected one of {_valid_poly_modes}"
                        )
                # Phase 18.2 — LiqDB init DEFERRED 2026-05-01.
                # The HL liquidation collector path is not viable
                # (storedata-hyperliquid-events-live filters out non-liq
                # fills correctly but VPS3 doesn't have a working realtime
                # liq feed yet — operator pursuing alternate path).
                # Until that lands: liq_db stays None, V3_2_LIQ_QUIET_ENABLED
                # defaults to "false" in the controller helper, and the
                # liq_quiet gate is a no-op (returns True).
                # When liq feed is ready: re-enable by uncommenting the
                # init block below + flipping V3_2_LIQ_QUIET_ENABLED=true
                # in the env. The liq_db.py service + controller kwarg
                # remain in-tree, dormant, ready for reactivation.
                #
                # if any(sm in ("v3_2", "v4") for sm in strategy_modes):
                #     from backend.app.services.liq_db import LiqDB
                #
                #     liq_db = LiqDB()
                #     try:
                #         await liq_db.init_pool()
                #         logger.info("liq_db.ready")
                #     except Exception as exc:  # noqa: BLE001  fail-open per D-05
                #         logger.warning(
                #             "liq_db.init_failed_fail_open",
                #             error=str(exc),
                #         )
                #         liq_db = None
                # Phase 24: collect ALL controllers into a list for either
                # the master scheduler (single shared BarContext) or the
                # legacy per-mode dispatch. Decision made AFTER inverse
                # block runs so master sees the full controller set.
                _all_controllers: list[tuple[Any, str]] = []
                for sm in strategy_modes:
                    # Phase 18.5 — momo is constructed below as 3
                    # parallel controllers (HOLD_ONLY/HEDGE_HOLD/SELL_BID)
                    # gated behind TV_POLY_MOMO_ENABLED. Skip here so
                    # we don't accidentally spawn a 4th default-policy
                    # momo controller.
                    if sm == "momo":
                        continue
                    # Phase 18.5+ — momo_v2 also constructed below as 3
                    # parallel controllers per (asset, tf) gated behind
                    # TV_POLY_MOMO_V2_ENABLED. Skip here.
                    if sm == "momo_v2":
                        continue
                    poly_controller = PolymarketUpdownController(
                        pool=read_pool,
                        executor=paper_executor,
                        mode="paper",
                        strategy_mode=sm,  # type: ignore[arg-type]
                        liq_db=liq_db,
                        book_mirror=book_mirror,
                    )
                    sleeve_ids = register_poly_updown(poly_controller)
                    # Phase 33 (D-06) — Defense-in-depth: filter deprecated
                    # sleeve_ids from the registered set. bots.py D-05 already
                    # strips them from _POLY_UPDOWN_SLEEVE_IDS; this catches
                    # any sleeve_id arriving through the controller path.
                    if _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS:
                        sleeve_ids = tuple(
                            sid for sid in sleeve_ids
                            if sid not in _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS
                        )
                    logger.info(
                        "poly_updown.controller_registered",
                        sleeve_ids=sleeve_ids,
                        mode="paper",
                        strategy_mode=sm,
                    )
                    _all_controllers.append((poly_controller, sm))

                # Phase 18.5 — momo controllers (paper-only shadow). When
                # ``momo`` is in TV_POLY_STRATEGY_MODES AND
                # TV_POLY_MOMO_ENABLED=true, spawn 3 controllers (one per
                # hedge_policy variant). Each controller manages 6
                # (sym, tf) slots → 18 momo sleeves total. Master
                # scheduler dispatches them at the t+120s boundary
                # (NOT bar-close).
                _momo_in_modes = "momo" in strategy_modes
                _momo_enabled = (
                    os.getenv("TV_POLY_MOMO_ENABLED", "false").lower() == "true"
                )
                # Phase 18.6 W0 (2026-05-06): per-policy gate via env CSV.
                # Default HOLD_ONLY only — HEDGE_HOLD + SELL_BID disabled
                # until Phase 18.6 Wave 2 PASS (TV-native WS BookMirror
                # validated). Reason: opposite-book CLOB reads are
                # structurally lossy for thin tokens, so HEDGE/SELL
                # policies fired 0 hedges in 215 resolutions on 2026-05-06.
                # Re-enable post-Wave-2 with TV_POLY_MOMO_HEDGE_POLICIES=
                # HOLD_ONLY,HEDGE_HOLD,SELL_BID.
                _valid_momo_policies = ("HOLD_ONLY", "HEDGE_HOLD", "SELL_BID")
                _momo_policies_csv = os.getenv(
                    "TV_POLY_MOMO_HEDGE_POLICIES", "HOLD_ONLY"
                )
                _momo_policies = tuple(
                    p.strip().upper()
                    for p in _momo_policies_csv.split(",")
                    if p.strip()
                )
                for _p in _momo_policies:
                    if _p not in _valid_momo_policies:
                        raise ValueError(
                            f"TV_POLY_MOMO_HEDGE_POLICIES contains invalid "
                            f"policy {_p!r}; expected subset of "
                            f"{_valid_momo_policies}"
                        )
                if _momo_in_modes and _momo_enabled:
                    logger.info(
                        "poly_updown.momo_active_policies",
                        policies=_momo_policies,
                        disabled_pending_phase_18_6_wave_2=tuple(
                            p for p in _valid_momo_policies if p not in _momo_policies
                        ),
                    )
                    for _hp in _momo_policies:
                        momo_ctrl = PolymarketUpdownController(
                            pool=read_pool,
                            executor=paper_executor,
                            mode="paper",
                            strategy_mode="momo",
                            hedge_policy=_hp,  # type: ignore[arg-type]
                            liq_db=liq_db,
                            book_mirror=book_mirror,
                        )
                        sleeve_ids = register_poly_updown(momo_ctrl)
                        # Phase 33 (D-06) — Defense-in-depth deprecation skip.
                        if _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS:
                            sleeve_ids = tuple(
                                sid for sid in sleeve_ids
                                if sid not in _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS
                            )
                        logger.info(
                            "poly_updown.momo_controller_registered",
                            sleeve_ids=sleeve_ids,
                            mode="paper",
                            hedge_policy=_hp,
                        )
                        _all_controllers.append((momo_ctrl, f"momo_{_hp}"))
                elif _momo_in_modes and not _momo_enabled:
                    logger.info(
                        "poly_updown.momo_disabled",
                        reason="TV_POLY_MOMO_ENABLED!=true",
                    )

                # Phase 18.5+ — momo_v2 controllers (paper-only shadow).
                # Spawn 3 controllers (one per hedge_policy variant) when
                # ``momo_v2`` is in TV_POLY_STRATEGY_MODES AND
                # TV_POLY_MOMO_V2_ENABLED=true. Each manages 6 (sym, tf)
                # slots → 18 momo_v2 sleeves total. Master scheduler
                # dispatches them at the t+60s boundary (NOT bar-close,
                # NOT t+120). Coexists with v1 momo per spec §0.
                _momo_v2_in_modes = "momo_v2" in strategy_modes
                _momo_v2_enabled = (
                    os.getenv("TV_POLY_MOMO_V2_ENABLED", "false").lower() == "true"
                )
                # Single master switch per spec §6 — always spawn all 3
                # policies (HOLD_ONLY/HEDGE_HOLD/SELL_BID) when enabled.
                # No per-policy CSV gate (v2 spec is "spawn all 18").
                _momo_v2_policies = ("HOLD_ONLY", "HEDGE_HOLD", "SELL_BID")
                if _momo_v2_in_modes and _momo_v2_enabled:
                    logger.info(
                        "poly_updown.momo_v2_active_policies",
                        policies=_momo_v2_policies,
                    )
                    for _hp in _momo_v2_policies:
                        momo_v2_ctrl = PolymarketUpdownController(
                            pool=read_pool,
                            executor=paper_executor,
                            mode="paper",
                            strategy_mode="momo_v2",
                            hedge_policy=_hp,  # type: ignore[arg-type]
                            liq_db=liq_db,
                            book_mirror=book_mirror,
                        )
                        sleeve_ids = register_poly_updown(momo_v2_ctrl)
                        # Phase 33 (D-06) — Defense-in-depth deprecation skip.
                        if _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS:
                            sleeve_ids = tuple(
                                sid for sid in sleeve_ids
                                if sid not in _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS
                            )
                        logger.info(
                            "poly_updown.momo_v2_controller_registered",
                            sleeve_ids=sleeve_ids,
                            mode="paper",
                            hedge_policy=_hp,
                        )
                        _all_controllers.append(
                            (momo_v2_ctrl, f"momo_v2_{_hp}")
                        )
                elif _momo_v2_in_modes and not _momo_v2_enabled:
                    logger.info(
                        "poly_updown.momo_v2_disabled",
                        reason="TV_POLY_MOMO_V2_ENABLED!=true",
                    )

                # Phase 18.4 — Inverse sleeves (anti-edge shadow).
                # The flag check MUST be the first thing in this block so
                # nothing from inverse.py runs when disabled — no class
                # instantiation, no controller construction, no import
                # beyond what the controller's module-level imports
                # already pulled (those are pure helpers and constants;
                # they sit dormant unless an inverse strategy_mode is
                # explicitly handed to the controller, which only happens
                # below). Default ``false`` — opt-in. Forces explicit
                # enable via /etc/tv/tradingvenue.env.
                _inverse_enabled = (
                    os.getenv("TV_INVERSE_SLEEVES_ENABLED", "false").lower() == "true"
                )
                if _inverse_enabled:
                    from backend.app.strategies.polymarket.inverse import (
                        INVERSE_KINDS,
                    )

                    for inv_mode in INVERSE_KINDS:
                        inv_controller = PolymarketUpdownController(
                            pool=read_pool,
                            executor=paper_executor,
                            mode="paper",
                            strategy_mode=inv_mode,  # type: ignore[arg-type]
                            liq_db=liq_db,
                            book_mirror=book_mirror,
                        )
                        sleeve_ids = register_poly_updown(inv_controller)
                        # Phase 33 (D-06) — Defense-in-depth deprecation skip.
                        if _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS:
                            sleeve_ids = tuple(
                                sid for sid in sleeve_ids
                                if sid not in _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS
                            )
                        logger.info(
                            "poly_updown.inverse_controller_registered",
                            sleeve_ids=sleeve_ids,
                            mode="paper",
                            strategy_mode=inv_mode,
                        )
                        _all_controllers.append((inv_controller, inv_mode))
                else:
                    logger.info(
                        "poly_updown.inverse_disabled",
                        reason="TV_INVERSE_SLEEVES_ENABLED!=true",
                    )

                # Phase 34 — Shadow gated sleeves (HoD / MTF / Markov).
                # 11 INDEPENDENT controllers, one per spec entry. Each is its
                # own sleeve_id (NO HOLD/HEDGE/SELL multiplication — operator
                # directive 2026-05-22). Hedge policy hardcoded in spec.
                # All paper-only (CLAUDE.md inv #11). Gated on env flag so
                # legacy deploys boot unchanged. Each controller carries:
                #   - strategy_mode = base_strategy (sniper/momo/momo_v2)
                #   - hedge_policy  = spec entry (HEDGE_HOLD for sniper,
                #                     HOLD_ONLY for momo/momo_v2)
                #   - audit_sleeve_id = the standalone sleeve_id from spec
                #     (e.g., "poly_updown_btc_5m_sniper_hod")
                #   - slot_allowlist = the one (sym, tf) this shadow targets
                #   - gate_stack + gate_cell_strategy from spec
                _shadow_gated_enabled = (
                    os.getenv("TV_POLY_SHADOW_GATED_ENABLED", "false").lower() == "true"
                )
                if _shadow_gated_enabled:
                    _shadow_spawned: list[str] = []
                    for (
                        _shadow_sleeve_id,
                        _shadow_base_strategy,
                        _shadow_asset,
                        _shadow_tf,
                        _shadow_gate_stack,
                        _shadow_gate_cell,
                        _shadow_hp,
                    ) in _SHADOW_GATED_SLEEVES_SPEC:
                        shadow_ctrl = PolymarketUpdownController(
                            pool=read_pool,
                            executor=paper_executor,
                            mode="paper",
                            strategy_mode=_shadow_base_strategy,  # type: ignore[arg-type]
                            hedge_policy=_shadow_hp,  # type: ignore[arg-type]
                            liq_db=liq_db,
                            book_mirror=book_mirror,
                            slot_allowlist=frozenset(
                                [(_shadow_asset.upper(), _shadow_tf.lower())]
                            ),
                            gate_stack=_shadow_gate_stack,
                            gate_cell_strategy=_shadow_gate_cell,
                            audit_sleeve_id=_shadow_sleeve_id,
                        )
                        register_poly_updown(shadow_ctrl)
                        _all_controllers.append(
                            (shadow_ctrl, _shadow_sleeve_id)
                        )
                        _shadow_spawned.append(_shadow_sleeve_id)
                    logger.info(
                        "poly_updown.shadow_gated_registered",
                        n=len(_shadow_spawned),
                        sleeve_ids=_shadow_spawned,
                    )
                else:
                    logger.info(
                        "poly_updown.shadow_gated_disabled",
                        reason="TV_POLY_SHADOW_GATED_ENABLED!=true",
                    )

                # Phase 35 — VWAP continuation sleeves (5 paper-only sleeves
                # with late-fire dispatch at offsets {60, 90, 210, 240}).
                # Each spec entry → 1 controller. strategy_mode='vwap_continuation'.
                # hedge_policy=HOLD_ONLY throughout. Gated on env flag.
                _vwap_cont_enabled = (
                    os.getenv("TV_POLY_VWAP_CONT_ENABLED", "false").lower() == "true"
                )
                if _vwap_cont_enabled:
                    _vwap_spawned: list[str] = []
                    for (
                        _vwap_sleeve_id,
                        _vwap_asset,
                        _vwap_tf,
                        _vwap_offset,
                        _vwap_thr_min,
                        _vwap_thr_max,
                        _vwap_need_m1v,
                        _vwap_need_f7,
                        _vwap_need_cross_full,
                        _vwap_need_cross_partial,
                    ) in _VWAP_CONT_SLEEVES_SPEC:
                        vwap_ctrl = PolymarketUpdownController(
                            pool=read_pool,
                            executor=paper_executor,
                            mode="paper",
                            strategy_mode="vwap_continuation",  # type: ignore[arg-type]
                            hedge_policy="HOLD_ONLY",
                            liq_db=liq_db,
                            book_mirror=book_mirror,
                            slot_allowlist=frozenset(
                                [(_vwap_asset.upper(), _vwap_tf.lower())]
                            ),
                            audit_sleeve_id=_vwap_sleeve_id,
                            vwap_offset_s=_vwap_offset,
                            vwap_thr_min_bps=_vwap_thr_min,
                            vwap_thr_max_bps=_vwap_thr_max,
                            vwap_require_m1v=_vwap_need_m1v,
                            vwap_require_f7=_vwap_need_f7,
                            vwap_require_cross_full=_vwap_need_cross_full,
                            vwap_require_cross_partial=_vwap_need_cross_partial,
                            vwap_asset=_vwap_asset,
                            vwap_tf=_vwap_tf,
                        )
                        register_poly_updown(vwap_ctrl)
                        _all_controllers.append((vwap_ctrl, _vwap_sleeve_id))
                        _vwap_spawned.append(_vwap_sleeve_id)
                    logger.info(
                        "poly_updown.vwap_cont_registered",
                        n=len(_vwap_spawned),
                        sleeve_ids=_vwap_spawned,
                    )
                else:
                    logger.info(
                        "poly_updown.vwap_cont_disabled",
                        reason="TV_POLY_VWAP_CONT_ENABLED!=true",
                    )

                # Phase 36 — Shadow9 sleeves (3 new strategies from
                # SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md): Kelly
                # ensemble (Sleeve #1) at t+120 + S3 pre-window (Sleeve #8)
                # at slot_start-60 + S4 pre-window (Sleeve #9) at
                # slot_start-120. All paper-only (mode='paper'). Each fires
                # across BTC/ETH/SOL via slot_allowlist; hedge_policy=
                # HOLD_ONLY throughout. Sleeve #1 dynamically sizes via
                # Kelly tier ($25-$100); others use flat $25.
                _shadow9_enabled = (
                    os.getenv("TV_POLY_SHADOW9_ENABLED", "false").lower() == "true"
                )
                if _shadow9_enabled:
                    _shadow9_spawned: list[str] = []
                    for (
                        _s9_sleeve_id,
                        _s9_strategy_mode,
                        _s9_tf,
                        _s9_slot_allowlist,
                    ) in _SHADOW9_SLEEVES_SPEC:
                        s9_ctrl = PolymarketUpdownController(
                            pool=read_pool,
                            executor=paper_executor,
                            mode="paper",
                            strategy_mode=_s9_strategy_mode,  # type: ignore[arg-type]
                            hedge_policy="HOLD_ONLY",
                            liq_db=liq_db,
                            book_mirror=book_mirror,
                            slot_allowlist=frozenset(
                                (s.upper(), t.lower())
                                for (s, t) in _s9_slot_allowlist
                            ),
                            audit_sleeve_id=_s9_sleeve_id,
                        )
                        register_poly_updown(s9_ctrl)
                        _all_controllers.append((s9_ctrl, _s9_sleeve_id))
                        _shadow9_spawned.append(_s9_sleeve_id)
                    logger.info(
                        "poly_updown.shadow9_registered",
                        n=len(_shadow9_spawned),
                        sleeve_ids=_shadow9_spawned,
                    )
                else:
                    logger.info(
                        "poly_updown.shadow9_disabled",
                        reason="TV_POLY_SHADOW9_ENABLED!=true",
                    )

                # Phase 36b — 6 FADE companions + 6 OVERLAY filters from the
                # same SHADOW9 spec (Sleeves #2-7 + Bonus). Each entry → ONE
                # controller. Gated on TV_POLY_SHADOW9_FADE_OVERLAY_ENABLED.
                _shadow9_fade_enabled = (
                    os.getenv("TV_POLY_SHADOW9_FADE_OVERLAY_ENABLED", "false")
                    .lower() == "true"
                )
                if _shadow9_fade_enabled:
                    _s9b_spawned: list[str] = []
                    for (
                        _s9b_sleeve_id, _s9b_mode, _s9b_asset, _s9b_tf, _s9b_key,
                    ) in _SHADOW9_FADE_OVERLAY_SPEC:
                        # Branch ctor kwargs by mode (fade vs overlay).
                        _kwargs: dict[str, Any] = dict(
                            pool=read_pool,
                            executor=paper_executor,
                            mode="paper",
                            strategy_mode=_s9b_mode,
                            hedge_policy="HOLD_ONLY",
                            liq_db=liq_db,
                            book_mirror=book_mirror,
                            slot_allowlist=frozenset(
                                [(_s9b_asset.upper(), _s9b_tf.lower())]
                            ),
                            audit_sleeve_id=_s9b_sleeve_id,
                        )
                        if _s9b_mode in ("fade_sniper", "fade_momo_v2"):
                            _kwargs["fade_cell_key"] = _s9b_key
                        else:
                            _kwargs["overlay_gate_kind"] = _s9b_key
                        s9b_ctrl = PolymarketUpdownController(**_kwargs)
                        register_poly_updown(s9b_ctrl)
                        _all_controllers.append((s9b_ctrl, _s9b_sleeve_id))
                        _s9b_spawned.append(_s9b_sleeve_id)
                    logger.info(
                        "poly_updown.shadow9_fade_overlay_registered",
                        n=len(_s9b_spawned),
                        sleeve_ids=_s9b_spawned,
                    )
                else:
                    logger.info(
                        "poly_updown.shadow9_fade_overlay_disabled",
                        reason="TV_POLY_SHADOW9_FADE_OVERLAY_ENABLED!=true",
                    )

                # Phase 26.3-03 — Live mirror twin spawning (LIVE-MIRROR-02/03).
                # Reads TV_POLY_LIVE_ALLOWLIST CSV; runs cascading 5-gate
                # preflight (funder → signer → CTF allowance → NegRisk
                # allowance → redeemer running). On preflight pass:
                # instantiates ONE live PolymarketClient (D-05 single signing
                # key) and constructs one PolymarketUpdownController per
                # deduped (strategy_mode, hedge_policy) config derived from
                # the allowlist (D-13 discretion). Mirrors are APPENDED to
                # _all_controllers so the master scheduler picks them up via
                # the existing fan-out pattern (Phase 24) — no scheduler
                # changes required.
                #
                # On empty allowlist OR preflight failure: returns [] →
                # paper-only fallback (engine continues booting; CRITICAL
                # log + live_mirrors_blocked audit row emitted on failure).
                #
                # AsyncWeb3 construction is lazy + gated: only build when the
                # allowlist is non-empty AND tv_poly_rpc_url is set, so
                # paper-only deploys pay no web3 import cost.
                _live_mirrors_count = 0
                if (settings.tv_poly_live_allowlist or "").strip():
                    from web3 import AsyncHTTPProvider as _MirrorHTTPProvider
                    from web3 import AsyncWeb3 as _MirrorWeb3

                    from backend.app.engine._preflight import (
                        _spawn_live_mirrors,
                    )

                    if not settings.tv_poly_rpc_url:
                        logger.critical(
                            "live_mirrors.deferred",
                            reason="tv_poly_rpc_url unset",
                        )
                    else:
                        _mirror_w3 = _MirrorWeb3(
                            _MirrorHTTPProvider(settings.tv_poly_rpc_url)
                        )
                        # Lazy GammaClient + OnchainOracle for live-mirror
                        # data path (CLAUDE.md inv #13 TV-native). Shared
                        # with the live PolymarketClient instantiated inside
                        # _spawn_live_mirrors.
                        from backend.app.venues.polymarket.gamma_client import (
                            GammaClient,
                        )
                        from backend.app.venues.polymarket.onchain_oracle import (
                            OnchainOracle as _MirrorOracle,
                        )

                        _mirror_gamma = GammaClient(
                            base_url=settings.tv_poly_gamma_api_url,
                            cache_path=settings.tv_poly_gamma_cache_path,
                        )
                        _mirror_oracle = _MirrorOracle(
                            rpc_url=settings.tv_poly_rpc_url,
                            ctf_address=settings.tv_poly_ctf_address,
                        )

                        # 2026-05-14 — catch LiveModeAckError so a missing
                        # daily poly_live_ack file (REG-02 compliance gate)
                        # disables live mirrors for the day but DOES NOT
                        # crash the whole engine. Paper trading continues.
                        # Operator creates the YAML at
                        # `/opt/tradingvenue/state/poly_live_ack_<YYYY-MM-DD>.ok`
                        # per backend/app/venues/polymarket/live_gate.py.
                        from backend.app.venues.polymarket.live_gate import (
                            LiveModeAckError,
                        )
                        try:
                            # Phase 27 LIVE-DISC-02 — pass TV-native discovery
                            # service into live-mirror spawn.
                            # Semantic: discovery=app.state.poly_market_discovery
                            # (tv-engine has no FastAPI app — local var is the binding).
                            live_mirrors = await _spawn_live_mirrors(
                                redeemer_app_state,
                                settings,
                                _mirror_w3,
                                pool,
                                secrets_registry=secrets_registry,
                                gamma_client=_mirror_gamma,
                                oracle=_mirror_oracle,
                                read_pool=read_pool,
                                book_mirror=book_mirror,
                                discovery=discovery,
                            )
                        except LiveModeAckError as exc:
                            logger.critical(
                                "live_mirrors.ack_gate_failed",
                                reason=str(exc),
                            )
                            live_mirrors = []
                        for _live_ctrl in live_mirrors:
                            _sm = getattr(_live_ctrl, "strategy_mode", "live")
                            _all_controllers.append(
                                (_live_ctrl, f"{_sm}_LIVE")
                            )
                        _live_mirrors_count = len(live_mirrors)
                        logger.info(
                            "live_mirrors.appended_to_master_scheduler",
                            count=_live_mirrors_count,
                            total_controllers=len(_all_controllers),
                        )
                else:
                    logger.info("live_mirrors.disabled_no_allowlist")

                # Phase 24 dispatch — single master scheduler vs legacy
                # per-mode tasks. Flag-gated so rollback is just an env
                # toggle + restart. Master pre-builds shared BarContext
                # per (symbol, tf, ws_s) and dispatches all controllers
                # against the same kline + threshold + CLOB book snapshot,
                # collapsing the multi-controller race to <50ms.
                _use_master = (
                    os.getenv("TV_POLY_USE_MASTER_SCHEDULER", "false").lower() == "true"
                )
                if _use_master and _all_controllers:
                    from backend.app.engine.poly_updown_loop import (
                        poly_updown_master_scheduler,
                    )

                    _primary_ctrl, _primary_mode = _all_controllers[0]
                    _sibling_ctrls = [c for c, _ in _all_controllers[1:]]
                    _sibling_modes = [m for _, m in _all_controllers[1:]]
                    tg.create_task(
                        poly_updown_master_scheduler(
                            _primary_ctrl, _sibling_ctrls, stop,
                        ),
                        name="poly_updown.master_scheduler",
                    )
                    logger.info(
                        "poly_updown.master_scheduler_started",
                        n_controllers=len(_all_controllers),
                        primary_mode=_primary_mode,
                        sibling_modes=_sibling_modes,
                    )
                else:
                    # Legacy per-mode dispatch (rollback path or _all_controllers empty)
                    for _ctrl, _mode in _all_controllers:
                        tg.create_task(
                            poly_updown_scheduler(_ctrl, stop),
                            name=f"poly_updown.scheduler.{_mode}",
                        )
                # Phase 18.1 paper resolver: pays out filled paper bets
                # against chainlink-sourced public.market_resolutions_v2.
                # Closes the shadow-mode-without-WR loop. Independent of
                # the scheduler — runs on its own 30s tick. Uses read_pool
                # (tradingvenue_ro user) — same as the controller — because
                # the SELECT JOIN reads public.markets + public.market_resolutions_v2
                # which only RO has SELECT on, and RO ALSO has INSERT on
                # trading.events (verified GRANT level 2026-04-28: schema
                # RO is enforced via public.* grants only, not trading.*).
                #
                # 2026-05-18 — resolver no longer depends on Storedata.
                # On-chain CTF.payoutNumerators is the resolution source (same
                # data Polymarket's UMA oracle writes to settle the market).
                # The TV_POLY_UPDOWN_RESOLVER_ENABLED env gate stays for
                # operator overrides but Ireland can re-enable it now.
                #
                # Pool: write_pool (tradingvenue user) — the resolver reads
                # trading.events + writes poly_updown_resolution rows. Pre-rewrite
                # it used read_pool because the SELECT JOINed Storedata's
                # public.* schema; post-rewrite there is no Storedata read,
                # so the resolver lives entirely in the trading.* schema and
                # doesn't need the RO user's public.* grant.
                if os.getenv("TV_POLY_UPDOWN_RESOLVER_ENABLED", "true").lower() == "true":
                    from backend.app.engine.poly_updown_resolver import (
                        poly_updown_resolver_loop,
                    )
                    from backend.app.venues.polymarket.onchain_oracle import (
                        OnchainOracle as _ResolverOracle,
                    )

                    if not settings.tv_poly_rpc_url:
                        logger.warning(
                            "poly_updown.resolver.disabled",
                            reason="tv_poly_rpc_url unset; cannot read on-chain oracle",
                        )
                    else:
                        _resolver_oracle = _ResolverOracle(
                            rpc_url=settings.tv_poly_rpc_url,
                            ctf_address=settings.tv_poly_ctf_address,
                        )
                        tg.create_task(
                            poly_updown_resolver_loop(
                                pool, _resolver_oracle, stop
                            ),
                            name="poly_updown.resolver",
                        )
                        logger.info("poly_updown.resolver.spawned")
                else:
                    logger.info(
                        "poly_updown.resolver.disabled",
                        reason="TV_POLY_UPDOWN_RESOLVER_ENABLED=false",
                    )

                # ---------------------------------------------------------------
                # Phase 35-12 — Polymarket sniper-v5 shadow suite (16 paper sleeves)
                # ---------------------------------------------------------------
                # Default tv_poly_sniper_v5_enabled=False → no spawn (engine boots
                # byte-identical to pre-Phase-35). When ON, instantiates 7
                # streaming panels + AsyncJsonlShadowLogger + Controller +
                # SlotObserver + OracleResolve + spawns poly_sniper_v5_loop in
                # the TaskGroup. All 16 sleeves are paper-only — no trader_writes
                # calls anywhere in the path (CLAUDE.md inv #11+#12).
                if settings.tv_poly_sniper_v5_enabled:
                    from pathlib import Path as _SniperV5Path

                    from backend.app.controllers.polymarket_sniper_v5 import (
                        PolymarketSniperV5Controller,
                        SlotInfo as _SniperV5SlotInfo,
                    )
                    from backend.app.engine.poly_sniper_v5_loop import (
                        poly_sniper_v5_loop,
                    )
                    from backend.app.features.daily_vwap import DailyVwapPanel
                    from backend.app.features.f7_v7_panel import F7V7Panel
                    from backend.app.features.hawkes_panel import HawkesPanel
                    from backend.app.features.microprice import MicropricePanel
                    from backend.app.features.range_filter_1h import (
                        RangeFilter1hPanel,
                    )
                    from backend.app.features.range_filter_1s import (
                        RangeFilterPanel,
                    )
                    from backend.app.features.regime_panel import RegimePanel
                    from backend.app.features.sms_panel import SmsPanel
                    from backend.app.features.ta_indicators_1s import (
                        TAIndicatorsPanel,
                    )
                    from backend.app.features.traders_reality_1s import (
                        TradersRealityPanel,
                    )
                    from backend.app.features.vol_hurst import VolHurstPanel
                    from backend.app.strategies.polymarket.sniper_v5_shadow_log import (
                        AsyncJsonlShadowLogger,
                    )
                    from backend.app.strategies.polymarket.sniper_v5_sleeves import (
                        SNIPER_V5_SLEEVES,
                    )
                    from backend.app.strategies.polymarket.sniper_v5_v9_data import (
                        V9DataStore,
                    )

                    # 11 panels (7 Phase 35 V5 + 4 V6/V7/V8 extension) —
                    # instantiated argument-free; state lazy-initialized per
                    # (asset, tf, slug) on first ingest. New panels for the
                    # V6+V7+V8 unified deploy (2026-05-27):
                    #   * ta_indicators_1s — V6 §3.6 / V7 §3.8 / V8 §3.9
                    #   * f7_v7_panel     — V7 §3.9 / V8 reuses
                    #   * hawkes_panel    — V6 §3.9
                    #   * range_filter_1h — V8 §3.1
                    # (RegimePanel already gained 1h tf + adx/+DI/-DI/rv_60m
                    #  in commits bcd3f10 + 9ceb489; VolHurst gained hurst_60
                    #  in e4eb85d. Both are still single-instance.)
                    _sniper_v5_panels = {
                        "traders_reality": TradersRealityPanel(),
                        "range_filter": RangeFilterPanel(),
                        "microprice": MicropricePanel(),
                        "regime": RegimePanel(),
                        "sms": SmsPanel(),
                        "vol_hurst": VolHurstPanel(),
                        "daily_vwap": DailyVwapPanel(),
                        # V6 / V7 / V8 extension panels
                        "ta_indicators": TAIndicatorsPanel(),
                        "f7_v7": F7V7Panel(),
                        "hawkes": HawkesPanel(),
                        "range_filter_1h": RangeFilter1hPanel(),
                    }

                    # Wire panels into BinanceMarketDataFeed (Phase 35-12 register
                    # methods). SmsPanel exposes on_1m_bar (not on_1s_bar) — it
                    # aggregates 1m bars into 5m+15m windows internally.
                    if binance_feed is not None and hasattr(
                        binance_feed, "register_1s_handler"
                    ):
                        binance_feed.register_1s_handler(
                            _sniper_v5_panels["traders_reality"].on_1s_bar
                        )
                        binance_feed.register_1s_handler(
                            _sniper_v5_panels["range_filter"].on_1s_bar
                        )
                        # V6/V7/V8 extension — 1s ingestion
                        binance_feed.register_1s_handler(
                            _sniper_v5_panels["ta_indicators"].on_1s_bar
                        )
                        binance_feed.register_1s_handler(
                            _sniper_v5_panels["hawkes"].on_1s_bar
                        )
                    if binance_feed is not None and hasattr(
                        binance_feed, "register_1m_handler"
                    ):
                        binance_feed.register_1m_handler(
                            _sniper_v5_panels["regime"].on_1m_bar
                        )
                        binance_feed.register_1m_handler(
                            _sniper_v5_panels["sms"].on_1m_bar
                        )
                        binance_feed.register_1m_handler(
                            _sniper_v5_panels["vol_hurst"].on_1m_bar
                        )
                        binance_feed.register_1m_handler(
                            _sniper_v5_panels["daily_vwap"].on_1m_bar
                        )
                        # V6/V7/V8 extension — 1m ingestion
                        binance_feed.register_1m_handler(
                            _sniper_v5_panels["f7_v7"].on_1m_bar
                        )
                        binance_feed.register_1m_handler(
                            _sniper_v5_panels["range_filter_1h"].on_1m_bar
                        )

                        # BUG FIX — panels were cold after every restart.
                        # backfill_from_rest (run at boot above) populates the
                        # feed's close-only deque but NEVER replays bars through
                        # the 1m panel handlers, so the sniper-v5 feature panels
                        # started cold and re-warmed only from live WS bars (5m
                        # ~5h, 15m ~15h, 1h ~60h of uptime). Seed them now — AFTER
                        # boot backfill + AFTER the 1m handlers are registered —
                        # by replaying recent REST 1m bars (full OHLCV so Regime's
                        # ADX warms correctly). Defensive: the feed swallows fetch
                        # failures; wrap here too so boot never crashes.
                        try:
                            _panel_seed_days = int(
                                getattr(
                                    settings, "tv_binance_panel_seed_days", 4
                                )
                            )
                            await binance_feed.seed_1m_handlers_from_rest(
                                days=_panel_seed_days
                            )
                        except Exception:  # noqa: BLE001 — never crash boot
                            logger.exception(
                                "binance_feed.panel_seed_failed"
                            )

                        # Warm the 1s feature panels (traders_reality ema_50/
                        # ema_800, range_filter, ta, hawkes) + vwap_store
                        # (dev_bps/cvd) INSTANTLY from REST 1s klines — else they
                        # cold-start ~15-30 min after every restart and the
                        # EMA-gated Kalshi/sniper sleeves go blind (2026-05-31
                        # Kalshi live no-fire). No-op when the 1s stream is off.
                        try:
                            _panel_seed_1s_min = int(
                                getattr(
                                    settings,
                                    "tv_binance_panel_seed_1s_minutes",
                                    120,
                                )
                            )
                            await binance_feed.seed_1s_handlers_from_rest(
                                minutes=_panel_seed_1s_min
                            )
                        except Exception:  # noqa: BLE001 — never crash boot
                            logger.exception(
                                "binance_feed.panel_seed_1s_failed"
                            )

                    # Async JSONL shadow logger (one file/day for all 16 sleeves).
                    _sniper_v5_logger = AsyncJsonlShadowLogger(
                        log_dir=_SniperV5Path(
                            settings.tv_poly_sniper_v5_log_dir
                        ),
                        maxsize=settings.tv_poly_sniper_v5_queue_maxsize,
                        drain_batch_size=settings.tv_poly_sniper_v5_drain_batch_size,
                        drain_timeout_s=settings.tv_poly_sniper_v5_drain_timeout_s,
                        alert_service=alerts,
                    )
                    await _sniper_v5_logger.start()

                    # Controller — wires panels + book + logger + settings.
                    # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — pass the
                    # canonical 3-tier book primitive
                    # (``paper_executor.get_orderbook_snapshot``) for the
                    # controller's OWN fill / snapshot reads. ``book_mirror``
                    # is kept ALONGSIDE for synchronous gate dispatch (the
                    # sniper-v5 gates like ``g_imb5_strong_with`` /
                    # ``g_depth_250_strict`` are pure-sync and read the
                    # in-memory mirror directly).
                    # V9 trade flow (B1/B2/B3 gates) — TV-native in-memory buffer
                    # fed by a dedicated TradeMirror (below). The controller wires
                    # this in as ``v9_data_store``; gates read it synchronously at
                    # fire time. Empty buffer (cold start / WS down) → gates return
                    # False, sleeves stay silent, no boot impact.
                    # TV-native multi-CEX liquidation feed (OKX/Bybit/Gate/
                    # Bitget) — feeds the A2 short-cascade gate in place of the
                    # frozen HL hl-s3-fills source (Binance deferred per geoblock).
                    from backend.app.feeds.cex_liquidations_feed import (
                        CexLiquidationFeed as _CexLiqFeed,
                    )
                    # min_notional=0 — count ALL liquidations so the A2 cascade
                    # sum is complete (the $5k cap excluded the smaller ETH/SOL
                    # liqs and starved their cascade). buffer_size bumped so a
                    # 300s cascade window isn't truncated by dust eviction.
                    _cex_liq_feed = _CexLiqFeed(
                        min_notional_usd=0.0, buffer_size=100_000,
                        alert_service=alerts,
                    )
                    _v9_data_store = V9DataStore(
                        ttl_s=int(getattr(settings, "tv_poly_v9_trade_ttl_s", 1800)),
                        cex_liq_feed=_cex_liq_feed,
                    )
                    # TV-native Polymarket trade feed (replaces Storedata parquet).
                    # Dedicated WS connection for the sniper-v5 path (separate from
                    # BookMirror + the maker-arb TradeMirror).
                    from backend.app.venues.polymarket.trade_mirror import (
                        TradeMirror as _SniperV5TradeMirror,
                    )
                    _sniper_v5_trade_mirror = _SniperV5TradeMirror()

                    async def _sniper_v5_on_trade(tp) -> None:
                        _v9_data_store.on_trade_print(tp)

                    _sniper_v5_trade_mirror.set_trade_callback(_sniper_v5_on_trade)
                    await _sniper_v5_trade_mirror.start()

                    _sniper_v5_controller = PolymarketSniperV5Controller(
                        panels=_sniper_v5_panels,
                        book_mirror=book_mirror,
                        book_snapshot_fn=paper_executor.get_orderbook_snapshot,
                        shadow_logger=_sniper_v5_logger,
                        settings=settings,
                        read_pool=read_pool,
                        write_pool=pool,  # Phase 35.2 — trading.events parallel write
                        alert_service=alerts,
                        v9_data_store=_v9_data_store,
                    )


                    # Register controller's on_book_update with BookMirror so
                    # microprice + sparse-book-event tracker get every L25 update.
                    if book_mirror is not None and hasattr(
                        book_mirror, "register_callback"
                    ):
                        book_mirror.register_callback(
                            _sniper_v5_controller.on_book_update
                        )

                    # Slug reconstruction helper. Format per
                    # backend/app/engine/poly_updown_loop.py:
                    # "{symbol-lower}-updown-{tf}-{window_start_unix}"
                    def _sniper_v5_reconstruct_slug(
                        symbol: str, tf: str, window_start_unix: int,
                    ) -> str:
                        return (
                            f"{symbol.lower()}-updown-{tf}-"
                            f"{window_start_unix}"
                        )

                    # Slot observer — observes the primary
                    # Slot observer — Phase 35.1 architecture fix (2026-05-27):
                    # eagerly resolves the active Chainlink window for every
                    # (asset, tf) cell via gamma_client. INDEPENDENT of any
                    # other controller's trade state — this is what allows
                    # sniper-v5 to observe windows even when no other strategy
                    # is firing. Also subscribes BookMirror to both legs of
                    # each discovered slot so depth+microprice gates have data
                    # by the time offset_s elapses.
                    #
                    # Per-(asset, tf) cache keyed on slot_start_unix avoids
                    # redundant gamma calls within the same window: ~6 gamma
                    # calls/min instead of 72/min (cache hits skip gamma; only
                    # cache misses at window boundaries trigger refresh).
                    #
                    # Prior implementation read primary._slots — per-sleeve
                    # TRADE tracking, empty when no primary trade fires. That
                    # caused Phase 35 G6 deploy failure (zero JSONL emissions
                    # over 10+ min on VPS3, 2026-05-27 ~09:08-09:18 CEST).
                    import time as _sniper_v5_time
                    _sniper_v5_slot_cache: dict[
                        tuple[str, str], tuple[int, _SniperV5SlotInfo]
                    ] = {}
                    _sniper_v5_subscribed_tokens: set[str] = set()
                    _SNIPER_V5_TF_SECS = {"5m": 300, "15m": 900}

                    async def _sniper_v5_slot_observer() -> list[_SniperV5SlotInfo]:
                        slots_out: list[_SniperV5SlotInfo] = []
                        now_unix = int(_sniper_v5_time.time())
                        for asset in ("BTC", "ETH", "SOL"):
                            for tf in ("5m", "15m"):
                                tf_sec = _SNIPER_V5_TF_SECS[tf]
                                window_start = (now_unix // tf_sec) * tf_sec
                                cached = _sniper_v5_slot_cache.get((asset, tf))
                                if cached is not None and cached[0] == window_start:
                                    # Same window as last poll — reuse cached slot
                                    slots_out.append(cached[1])
                                    continue
                                # Cache miss → query gamma for this window
                                try:
                                    meta = await _discovery_gamma.get_active_slug_for_window(
                                        asset=asset, tf=tf,
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    logger.warning(
                                        "poly_sniper_v5.gamma_resolve_failed",
                                        asset=asset, tf=tf, error=str(exc),
                                    )
                                    continue
                                if meta is None:
                                    continue
                                # Defensive: gamma may have advanced; reject if
                                # its window_start doesn't match our wall-clock
                                # window (prevents stale-cache emissions).
                                if int(meta.get("slot_start_unix", 0)) != window_start:
                                    continue
                                slot_info = _SniperV5SlotInfo(
                                    slug=str(meta["slug"]),
                                    asset=asset,
                                    tf=tf,
                                    slot_start_us=window_start * 1_000_000,
                                    ws_s=window_start,
                                    condition_id=str(meta["condition_id"]),
                                    token_id_up=str(meta["token_id_up"]),
                                    token_id_dn=str(meta["token_id_dn"]),
                                )
                                slots_out.append(slot_info)
                                _sniper_v5_slot_cache[(asset, tf)] = (
                                    window_start, slot_info,
                                )
                                # Eager BookMirror subscribe — refcounted
                                # (book_mirror.subscribe is idempotent across
                                # multiple subscribers).
                                if book_mirror is not None:
                                    for tok in (
                                        meta["token_id_up"],
                                        meta["token_id_dn"],
                                    ):
                                        tok_str = str(tok)
                                        if tok_str in _sniper_v5_subscribed_tokens:
                                            continue
                                        try:
                                            await book_mirror.subscribe(tok_str)
                                            _sniper_v5_subscribed_tokens.add(tok_str)
                                        except Exception as exc:  # noqa: BLE001
                                            logger.warning(
                                                "poly_sniper_v5.book_subscribe_failed",
                                                token_id=tok_str, error=str(exc),
                                            )
                                # Register the slug+tokens with the microprice
                                # panel — without this its on_book_update no-ops
                                # (empty token map) and every mp_skew gate
                                # (g_mp_skew_with / g_mp_no_extreme*) stays False.
                                _mp_panel = _sniper_v5_panels.get("microprice")
                                if _mp_panel is not None:
                                    try:
                                        _mp_panel.register_slug(
                                            str(meta["slug"]),
                                            str(meta["token_id_up"]),
                                            str(meta["token_id_dn"]),
                                        )
                                    except Exception as exc:  # noqa: BLE001
                                        logger.warning(
                                            "poly_sniper_v5.mp_register_failed",
                                            slug=str(meta["slug"]), error=str(exc),
                                        )
                                # TradeMirror subscribe — TV-native trade flow for
                                # V9 B1/B2/B3 gates; carries slug+side so each
                                # TradePrint maps to its outcome.
                                for _tok, _side in (
                                    (meta["token_id_up"], "up"),
                                    (meta["token_id_dn"], "dn"),
                                ):
                                    try:
                                        await _sniper_v5_trade_mirror.subscribe(
                                            str(_tok),
                                            slug=str(meta["slug"]),
                                            side=_side,
                                        )
                                    except Exception as exc:  # noqa: BLE001
                                        logger.warning(
                                            "poly_sniper_v5.trade_subscribe_failed",
                                            token_id=str(_tok), error=str(exc),
                                        )
                        return slots_out

                    # Kill set (CSV env override; default empty).
                    _sniper_v5_kill_set = frozenset(
                        sid.strip()
                        for sid in (settings.tv_poly_sniper_v5_kill or "").split(",")
                        if sid.strip()
                    )

                    # Oracle resolve: reuse redeemer_oracle if available, else
                    # build one from RPC URL, else None (resolution logs skip).
                    _sniper_v5_oracle_resolve: Any = None
                    _sniper_v5_local_oracle = None
                    try:
                        _sniper_v5_local_oracle = redeemer_oracle  # noqa: F823
                    except (NameError, UnboundLocalError):
                        _sniper_v5_local_oracle = None
                    if _sniper_v5_local_oracle is None and settings.tv_poly_rpc_url:
                        from backend.app.venues.polymarket.onchain_oracle import (
                            OnchainOracle as _SniperV5OnchainOracle,
                        )
                        _sniper_v5_local_oracle = _SniperV5OnchainOracle(
                            rpc_url=settings.tv_poly_rpc_url,
                            ctf_address=settings.tv_poly_ctf_address,
                        )
                    if _sniper_v5_local_oracle is not None:
                        async def _sniper_v5_resolve(
                            condition_id: str,
                        ) -> str | None:
                            try:
                                out = await _sniper_v5_local_oracle.get_resolution(
                                    condition_id
                                )
                                if out is None:
                                    return None
                                name = getattr(out, "name", str(out))
                                lower = name.lower()
                                if lower == "up":
                                    return "Up"
                                if lower == "down":
                                    return "Down"
                                return None
                            except Exception:  # noqa: BLE001
                                return None
                        _sniper_v5_oracle_resolve = _sniper_v5_resolve

                    # fast_taker (poly_fast_taker_* sleeves) — the oracle-lag
                    # gate reads binance+chainlink spot from polymarket_rtds.
                    # That feed runs in tv-api (chart/tile consumer); the
                    # sniper-v5 controller runs HERE in tv-engine, a SEPARATE
                    # process, so its in-memory price store is empty unless we
                    # ALSO run the RTDS feed in-engine. One extra public WS (no
                    # auth); without it g_oracle_lag_bps_ge always sees None and
                    # the fast_taker sleeves never fire.
                    if getattr(settings, "tv_poly_sniper_v5_panels_only", False):
                        # Ireland live-only box: the feature panels above are
                        # built + fed by the binance 1s/1m handlers (so the
                        # Kalshi live EMA gates have data), but the Poly
                        # sniper-v5 SHADOW sleeve loop is NOT spawned — zero
                        # shadow fires / events on a live venue. The RTDS +
                        # CEX-liq feeds serve only the sniper-v5/fast_taker loop,
                        # so they're skipped too.
                        logger.info(
                            "poly_sniper_v5.panels_only",
                            note=(
                                "panels feed Kalshi live gates; "
                                "sniper-v5 shadow sleeves NOT spawned"
                            ),
                            n_panels=len(_sniper_v5_panels),
                        )
                    else:
                        # Warm the CEX liquidation buffer from Storedata's
                        # collector tables BEFORE the loop + WS runners start, so
                        # the A2 short-cascade gate isn't blind for the first
                        # window after a restart (empty buffer → 0 fires). Quick
                        # read-only batch read; never crashes boot.
                        try:
                            await _cex_liq_feed.backfill_from_storedata(
                                read_pool,
                                lookback_s=int(getattr(
                                    settings, "tv_poly_liq_backfill_s", 900
                                )),
                            )
                        except Exception:  # noqa: BLE001 — never crash boot
                            logger.exception("poly_sniper_v5.liq_backfill_failed")
                        from backend.app.services import (
                            polymarket_rtds as _sniper_v5_rtds,
                        )
                        tg.create_task(
                            _sniper_v5_rtds.run_rtds_feed(),
                            name="poly_sniper_v5.oracle_lag_rtds_feed",
                        )
                        tg.create_task(
                            poly_sniper_v5_loop(
                                _sniper_v5_controller,
                                _sniper_v5_slot_observer,
                                _sniper_v5_oracle_resolve,
                                _sniper_v5_kill_set,
                                stop,
                            ),
                            name="poly_sniper_v5.loop",
                        )
                        # CEX liquidation feed — long-running, self-reconnecting;
                        # feeds the A2 cascade proxy via V9DataStore.get_hl_short_proxy.
                        tg.create_task(
                            _cex_liq_feed.start(),
                            name="poly_sniper_v5.cex_liq_feed",
                        )
                        logger.info(
                            "poly_sniper_v5.spawned",
                            n_sleeves=len(SNIPER_V5_SLEEVES),
                            kill_set_size=len(_sniper_v5_kill_set),
                            log_dir=settings.tv_poly_sniper_v5_log_dir,
                            notional_usd=str(
                                settings.tv_poly_sniper_v5_notional_usd
                            ),
                        )
                else:
                    logger.info(
                        "poly_sniper_v5.disabled",
                        reason="TV_POLY_SNIPER_V5_ENABLED=false",
                    )

                # Phase 36-07 — Kalshi updown controller + feed + loop.
                # Default tv_kalshi_enabled=False → no spawn; engine boots
                # byte-identical to pre-Phase-36.  When True, builds
                # KalshiClient + KalshiMarketDataFeed (TV-native WS, D-05) +
                # KalshiUpdownController and spawns kalshi_loop in the
                # TaskGroup.  Reuses the sniper-v5 panel dict (built above)
                # so the same TV-native TR/EMA panels feed both Poly and
                # Kalshi gate evaluation — zero extra panel instances.
                #
                # Credentials:
                #   - Paper mode: KalshiPaperSimulator is used internally;
                #     credentials are optional (WS feed still needs them for
                #     auth — RESEARCH §pitfall 7).
                #   - Live mode: credentials required.  Missing in live mode →
                #     CRITICAL alert + spawn skipped (fail-closed, engine
                #     continues).
                # CLAUDE.md inv #11/#12 honored: no SIGHUP/hot-reload; env +
                # restart only.  inv #13: ZERO Storedata dependency.
                if settings.tv_kalshi_enabled:
                    from backend.app.venues.kalshi.client import (
                        KalshiClient as _KalshiClient,
                    )
                    from backend.app.venues.kalshi.market_data import (
                        KalshiMarketDataFeed as _KalshiMarketDataFeed,
                    )
                    from backend.app.controllers.kalshi_updown import (
                        KalshiUpdownController as _KalshiUpdownController,
                    )
                    from backend.app.engine.kalshi_loop import (
                        kalshi_loop as _kalshi_loop,
                    )
                    from backend.app.strategies.kalshi.sniper_kalshi_sleeves import (
                        KALSHI_SNIPER_SLEEVES as _KALSHI_SNIPER_SLEEVES,
                    )
                    from backend.app.venues.kalshi.settings import (
                        kalshi_credentials_from_registry as _kalshi_creds_fn,
                    )

                    # Prefer operator-entered creds from the Settings UI
                    # (kalshi_api_key_id + kalshi_private_key in the decrypted
                    # secrets_registry); fall back to env + on-disk PEM path.
                    _kalshi_creds = _kalshi_creds_fn(settings, secrets_registry)

                    # Credentials are required in BOTH paper and live mode.
                    # Kalshi WS auth is mandatory even for public channels
                    # (RESEARCH §pitfall 7); paper feed cannot connect without
                    # a signed WS handshake.  Fail-closed on missing creds
                    # regardless of mode so the engine never reaches
                    # KalshiMarketDataFeed.__init__ with credentials=None
                    # (which would raise AttributeError and crash the TaskGroup).
                    _kalshi_live_mode = (
                        getattr(settings, "tv_kalshi_mode", "paper") == "live"
                    )
                    if _kalshi_creds is None:
                        from backend.app.services.alert_service import (
                            AlertSeverity as _KalshiAlertSeverity,
                        )

                        _kalshi_mode_str = getattr(settings, "tv_kalshi_mode", "paper")
                        if _kalshi_live_mode:
                            logger.critical(
                                "kalshi.spawn_aborted_no_creds",
                                mode="live",
                                note=(
                                    "tv_kalshi_api_key_id or PEM file missing; "
                                    "set TV_KALSHI_API_KEY_ID + "
                                    "TV_KALSHI_PRIVATE_KEY_PATH and restart"
                                ),
                            )
                            await alerts.emit(
                                severity=_KalshiAlertSeverity.CRITICAL,
                                kind="kalshi_spawn_aborted_no_creds",
                                message=(
                                    "Kalshi live mode enabled but credentials "
                                    "missing — spawn skipped"
                                ),
                            )
                        else:
                            # Paper mode also needs creds for WS auth.
                            logger.warning(
                                "kalshi.spawn_aborted_no_creds",
                                mode=_kalshi_mode_str,
                                note=(
                                    "Kalshi WS needs auth even for public channels "
                                    "(RESEARCH pitfall 7); set TV_KALSHI_API_KEY_ID + "
                                    "TV_KALSHI_PRIVATE_KEY_PATH"
                                ),
                                reason="no_credentials",
                            )
                        logger.info(
                            "kalshi.disabled",
                            reason="no_credentials",
                        )
                    else:
                        # Build client (paper or live).
                        _kalshi_client = _KalshiClient(
                            settings=settings,
                            credentials=_kalshi_creds,
                            alert_service=alerts,
                        )

                        # Build + start the TV-native Kalshi WS feed.
                        # Lifecycle hoisted to function scope so finally-block
                        # can stop() it before pool teardown (RESEARCH §pitfall
                        # 7: WS auth required even for public channels).
                        kalshi_feed = _KalshiMarketDataFeed(
                            settings=settings,
                            credentials=_kalshi_creds,
                        )
                        tg.create_task(
                            kalshi_feed.start(stop),
                            name="kalshi.feed",
                        )

                        # Reuse sniper-v5 panels when available; the Kalshi
                        # gates only consume panels["traders_reality"] (EMA/TR).
                        # If sniper_v5 is off, _sniper_v5_panels is undefined —
                        # use an empty dict (gates degrade to False, no crash).
                        try:
                            _kalshi_panels = _sniper_v5_panels  # type: ignore[name-defined]
                        except NameError:
                            _kalshi_panels = {}

                        # Phase 38 — trading.events audit sink so the Kalshi
                        # sleeve surfaces in the dashboard like the Polymarket
                        # UpDown sleeves (canonical signal/resolution kinds).
                        from backend.app.engine.kalshi_event_logger import (
                            KalshiEventLogger as _KalshiEventLogger,
                        )
                        _kalshi_event_logger = _KalshiEventLogger(
                            pool=pool,
                            notional_usd=getattr(settings, "tv_kalshi_notional_usd", 5),
                            fee_usd_per_fill=getattr(settings, "tv_kalshi_fee_usd_per_fill", 0),
                            mode=getattr(settings, "tv_kalshi_mode", "paper"),
                        )

                        # Live sleeve-id allowlist (D-06 belt-and-suspenders).
                        # When live AND tv_kalshi_live_sleeve_ids is set, ONLY
                        # those sleeve_ids load — keeps experimental sleeves
                        # (e.g. the s4 prewindow ALL fan-out) OUT of live even
                        # though mode is global. Empty CSV = run all sleeves
                        # (preserves paper/shadow behavior on VPS3).
                        _kalshi_active_sleeves = _KALSHI_SNIPER_SLEEVES
                        _kalshi_live_ids_raw = (
                            getattr(settings, "tv_kalshi_live_sleeve_ids", "") or ""
                        )
                        if _kalshi_live_mode and _kalshi_live_ids_raw.strip():
                            _kalshi_allow_ids = {
                                _s.strip()
                                for _s in _kalshi_live_ids_raw.split(",")
                                if _s.strip()
                            }
                            _kalshi_active_sleeves = tuple(
                                _sl
                                for _sl in _KALSHI_SNIPER_SLEEVES
                                if _sl.sleeve_id in _kalshi_allow_ids
                            )
                            logger.info(
                                "kalshi.live_sleeve_filter",
                                allow=sorted(_kalshi_allow_ids),
                                active=[
                                    _sl.sleeve_id for _sl in _kalshi_active_sleeves
                                ],
                                excluded=[
                                    _sl.sleeve_id
                                    for _sl in _KALSHI_SNIPER_SLEEVES
                                    if _sl.sleeve_id not in _kalshi_allow_ids
                                ],
                            )

                        # S4 "Poly edge, Kalshi fill" (operator 2026-05-31): bind
                        # build_bar_context_pre_window over the primary Poly
                        # controller so the Kalshi S4 samples the POLY pre-window
                        # edge (Poly book + binance dev/cvd) at slot_start−120 and
                        # fills on Kalshi in-window. None when no Poly controller
                        # is spawned → S4 falls back to the in-window Kalshi aux.
                        _kalshi_poly_prewindow_fn = None
                        try:
                            _poly_pw_ctrl = poly_controller  # type: ignore[name-defined]
                        except NameError:
                            _poly_pw_ctrl = None
                        if _poly_pw_ctrl is not None:
                            import functools as _ft_kalshi
                            from backend.app.engine.poly_updown_loop import (
                                build_bar_context_pre_window as _bbcpw,
                            )
                            _kalshi_poly_prewindow_fn = _ft_kalshi.partial(
                                _bbcpw, _poly_pw_ctrl
                            )
                            logger.info(
                                "kalshi.s4_poly_edge_wired",
                                note="S4 signal sourced from Poly pre-window book",
                            )

                        # Build controller.
                        _kalshi_controller = _KalshiUpdownController(
                            panels=_kalshi_panels,
                            client=_kalshi_client,
                            feed=kalshi_feed,
                            sleeves=_kalshi_active_sleeves,
                            settings=settings,
                            alert_service=alerts,
                            shadow_logger=_kalshi_event_logger,
                            # S4 prewindow port — the in-engine binance 1s feed
                            # supplies dev_bps/cvd_30s/fair-value inputs. May be
                            # None if sniper_v5 is disabled (S4 skips gracefully).
                            binance_feed=binance_feed,
                            # S4 "Poly edge, Kalshi fill" — None → in-window fallback.
                            poly_prewindow_ctx_fn=_kalshi_poly_prewindow_fn,
                        )

                        # Spawn the window-offset scheduler loop.
                        tg.create_task(
                            _kalshi_loop(
                                _kalshi_controller,
                                _kalshi_active_sleeves,
                                stop,
                            ),
                            name="kalshi_updown.loop",
                        )
                        logger.info(
                            "kalshi.spawned",
                            n_sleeves=len(_kalshi_active_sleeves),
                            mode=getattr(settings, "tv_kalshi_mode", "paper"),
                            series=getattr(
                                settings, "tv_kalshi_series", "KXBTC15M"
                            ),
                        )
                else:
                    logger.info(
                        "kalshi.disabled",
                        reason="TV_KALSHI_ENABLED=false",
                    )

                # Old mint_sell shadow spawn removed per Phase 29 D-02. v2 replacement
                # spawned by SlotScheduler block (Plan 29-15) — see below.
                #
                # Phase 29-15: v2 mint-and-sell engine — N SlotSchedulers +
                # one supervisor task. Mode-dispatch injects paper or live
                # executors. Live path calls live_oncexec.validate() explicitly
                # (I-12 fix). On any preflight / validate / creds failure:
                # critical alert + no spawn. Engine boot CONTINUES so other
                # sleeves stay up — refusing to spawn v2 is fail-CLOSED for
                # mint-and-sell only.
                if settings.tv_poly_mint_sell_v2_enabled:
                    cells_csv = settings.tv_poly_mint_sell_v2_cells.strip()
                    v2_cells = [c.strip() for c in cells_csv.split(",") if c.strip()]
                    if not v2_cells:
                        logger.info(
                            "poly_mint_sell_v2.no_cells_enabled",
                            mode=settings.tv_poly_mint_sell_v2_mode,
                        )
                    else:
                        from backend.app.venues.polymarket.onchain_oracle import (
                            OnchainOracle as _V2OnchainOracle,
                        )

                        # Reuse `redeemer_oracle` if redeemer is enabled, else
                        # build a fresh OnchainOracle for v2 (D-29 + D-30).
                        if poly_redeemer_enabled and redeemer_app_state.poly_redeemer_running:
                            _v2_oracle = redeemer_oracle
                        else:
                            if not settings.tv_poly_rpc_url:
                                logger.error(
                                    "poly_mint_sell_v2.no_rpc_url",
                                    note="tv_poly_rpc_url unset; v2 cannot spawn",
                                )
                                _v2_oracle = None
                            else:
                                _v2_oracle = _V2OnchainOracle(
                                    rpc_url=settings.tv_poly_rpc_url,
                                    ctf_address=settings.tv_poly_ctf_address,
                                )

                        if _v2_oracle is None:
                            logger.warning(
                                "poly_mint_sell_v2.spawn_aborted_no_oracle",
                            )
                        elif settings.tv_poly_mint_sell_v2_mode == "live":
                            # LIVE mode — preflight + validate() gate the spawn.
                            from backend.app.services.poly_mint_sell_v2 import (
                                allowance as _v2_allowance,
                            )
                            from backend.app.services.poly_mint_sell_v2 import (
                                clob_client as _v2_clob_client,
                            )
                            from backend.app.services.poly_mint_sell_v2 import (
                                onchain_executor as _v2_oncexec,
                            )

                            # B-03 corollary: read L1 + L2 creds from the
                            # already-in-scope secrets_registry (loaded at
                            # line ~378 via load_secrets_registry).
                            _v2_pk = secrets_registry.get("poly_mint_sell_v2_private_key")
                            if not _v2_pk:
                                raise RuntimeError(
                                    "poly_mint_sell_v2_private_key unset in "
                                    "secrets registry; run "
                                    "scripts/derive_poly_1271_credentials.py"
                                )
                            # Derive wallet from L1 key.
                            from eth_account import Account as _V2EthAccount

                            _v2_wallet = _V2EthAccount.from_key(_v2_pk).address

                            # AlertService for the v2 spawn block — separate
                            # from the lifespan-wide `alerts` so failures route
                            # with kind=poly_mint_sell_v2_* by convention.
                            _v2_alerts = build_alert_service(
                                settings, logger, db_pool=pool
                            )

                            # Build a dedicated AsyncWeb3 for preflight reads.
                            if not settings.tv_poly_rpc_url:
                                logger.critical(
                                    "poly_mint_sell_v2.no_rpc_url_live",
                                )
                                from backend.app.services.alert_service import (
                                    AlertSeverity as _V2AlertSeverity,
                                )

                                await _v2_alerts.emit(
                                    severity=_V2AlertSeverity.CRITICAL,
                                    kind="poly_mint_sell_v2_no_rpc_url_live",
                                    message="v2 cannot spawn live: tv_poly_rpc_url unset",
                                )
                            else:
                                from eth_account import (  # noqa: F401  — already imported above; idempotent
                                    Account as _EthAccount,
                                )
                                from web3 import (
                                    AsyncHTTPProvider as _AsyncHTTPProvider,
                                )
                                from web3 import AsyncWeb3 as _AsyncWeb3

                                _v2_preflight_w3 = _AsyncWeb3(
                                    _AsyncHTTPProvider(settings.tv_poly_rpc_url)
                                )
                                try:
                                    _v2_preflight = await _v2_allowance.preflight(
                                        _v2_preflight_w3, _v2_wallet, settings
                                    )
                                except Exception as _v2_pf_exc:  # noqa: BLE001
                                    logger.critical(
                                        "poly_mint_sell_v2.preflight_crashed",
                                        error=str(_v2_pf_exc)[:200],
                                    )
                                    from backend.app.services.alert_service import (
                                        AlertSeverity as _V2AlertSeverity,
                                    )

                                    await _v2_alerts.emit(
                                        severity=_V2AlertSeverity.CRITICAL,
                                        kind="poly_mint_sell_v2_preflight_crashed",
                                        error=str(_v2_pf_exc)[:200],
                                    )
                                    _v2_preflight = None

                                if _v2_preflight is None:
                                    pass  # alert already sent
                                elif not _v2_preflight.passed:
                                    logger.critical(
                                        "poly_mint_sell_v2.preflight_failed",
                                        summary=_v2_preflight.summary,
                                    )
                                    from backend.app.services.alert_service import (
                                        AlertSeverity as _V2AlertSeverity,
                                    )

                                    await _v2_alerts.emit(
                                        severity=_V2AlertSeverity.CRITICAL,
                                        kind="poly_mint_sell_v2_preflight_failed",
                                        summary=_v2_preflight.summary,
                                    )
                                else:
                                    logger.info(
                                        "poly_mint_sell_v2.preflight_passed",
                                    )
                                    _v2_live_w3 = _AsyncWeb3(
                                        _AsyncHTTPProvider(
                                            settings.tv_poly_rpc_url
                                        )
                                    )
                                    _v2_live_oncexec = _v2_oncexec.LiveOnChainExecutor(
                                        w3=_v2_live_w3,
                                        private_key=_v2_pk,
                                        wallet_address=_v2_wallet,
                                        settings=settings,
                                    )
                                    # I-12: explicit validate() — not __aenter__.
                                    try:
                                        await _v2_live_oncexec.validate()
                                    except RuntimeError as _v2_val_exc:
                                        logger.critical(
                                            "poly_mint_sell_v2.executor_validate_failed",
                                            error=str(_v2_val_exc),
                                        )
                                        from backend.app.services.alert_service import (
                                            AlertSeverity as _V2AlertSeverity,
                                        )

                                        await _v2_alerts.emit(
                                            severity=_V2AlertSeverity.CRITICAL,
                                            kind="poly_mint_sell_v2_executor_validate_failed",
                                            error=str(_v2_val_exc),
                                        )
                                    else:
                                        # B-03 corollary: L2 creds None-check.
                                        _v2_ak = secrets_registry.get("poly_mint_sell_v2_api_key")
                                        _v2_as = secrets_registry.get("poly_mint_sell_v2_api_secret")
                                        _v2_ap = secrets_registry.get("poly_mint_sell_v2_api_passphrase")
                                        if not (_v2_ak and _v2_as and _v2_ap):
                                            logger.critical(
                                                "poly_mint_sell_v2.api_creds_missing",
                                            )
                                            from backend.app.services.alert_service import (
                                                AlertSeverity as _V2AlertSeverity,
                                            )

                                            await _v2_alerts.emit(
                                                severity=_V2AlertSeverity.CRITICAL,
                                                kind="poly_mint_sell_v2_api_creds_missing",
                                                message=(
                                                    "v2 API creds missing in "
                                                    "secrets_registry; run "
                                                    "scripts/derive_poly_1271_credentials.py"
                                                ),
                                            )
                                        else:
                                            # py_clob_client_v2 is the installed
                                            # module on this venv (NOT
                                            # py_clob_client — plan import
                                            # path corrected here).
                                            from py_clob_client_v2.client import (  # type: ignore[import-untyped]
                                                ClobClient as _V2ClobClient,
                                            )
                                            from py_clob_client_v2.clob_types import (  # type: ignore[import-untyped]
                                                ApiCreds as _V2ApiCreds,
                                            )

                                            _v2_clob_obj = _V2ClobClient(
                                                host="https://clob.polymarket.com",
                                                key=_v2_pk,
                                                chain_id=137,
                                                signature_type=3,
                                                funder=_v2_wallet,
                                                creds=_V2ApiCreds(
                                                    api_key=_v2_ak,
                                                    api_secret=_v2_as,
                                                    api_passphrase=_v2_ap,
                                                ),
                                            )
                                            _v2_live_clob = (
                                                _v2_clob_client.LiveCLOBClient(
                                                    clob=_v2_clob_obj,
                                                    settings=settings,
                                                )
                                            )
                                            _v2_executors = {
                                                "oncexec": _v2_live_oncexec,
                                                "clob": _v2_live_clob,
                                            }
                                            _spawn_v2_for_cells(
                                                tg,
                                                stop,
                                                v2_cells,
                                                _v2_executors,
                                                settings,
                                                pool,
                                                book_mirror,
                                                discovery,
                                                _v2_alerts,
                                                _v2_oracle,
                                                mode="live",
                                            )
                        else:
                            # PAPER mode — paper executors, no preflight gate.
                            from backend.app.services.poly_mint_sell_v2 import (
                                clob_paper as _v2_clob_paper,
                            )
                            from backend.app.services.poly_mint_sell_v2 import (
                                onchain_paper as _v2_onchain_paper,
                            )

                            _v2_alerts = build_alert_service(
                                settings, logger, db_pool=pool
                            )
                            _v2_executors = {
                                "oncexec": _v2_onchain_paper.PaperOnChainExecutor(),
                                "clob": _v2_clob_paper.PaperCLOBClient(),
                            }
                            _spawn_v2_for_cells(
                                tg,
                                stop,
                                v2_cells,
                                _v2_executors,
                                settings,
                                pool,
                                book_mirror,
                                discovery,
                                _v2_alerts,
                                _v2_oracle,
                                mode="paper",
                            )
                else:
                    logger.info(
                        "poly_mint_sell_v2.disabled",
                        reason="tv_poly_mint_sell_v2_enabled=false",
                    )

                # ----------------------------------------------------------
                # Phase 30 Plan 30-11 — Polymarket maker-arb suite spawn
                # ----------------------------------------------------------
                # D-07/D-08 — env-var gated; default tv_poly_maker_enabled=false
                # → no spawn (clean boot, no risk). Enabling requires SSH edit
                # to /etc/tv/tradingvenue.env + systemctl restart (CLAUDE inv
                # #11 — no SIGHUP / hot-reload).
                #
                # D-05 — 6 day-1 cells default:
                #   ACC-M: btc_15m
                #   ACC-H: btc_5m
                #   MAS:   eth_5m, eth_15m, sol_5m, sol_15m
                # One strategy instance per cell (per-slug state stays clean).
                # Three AsyncShadowLogger instances (one per strategy code,
                # shared across cells of the same strategy).
                #
                # Phase 30 is shadow-only (D-01). Phase 30.1 will flip
                # tv_poly_maker_shadow_mode=false + wire live_executor +
                # poly_merger_w3/wallet + private_key.
                # Phase 37 (operator 2026-05-29) — maker-arb suite DEPRECATED
                # (not working). Skip spawn even if the enable flag is set.
                if settings.tv_poly_maker_enabled and not settings.tv_poly_maker_deprecated:
                    from backend.app.engine.poly_maker_loop import (
                        _parse_kill_env,
                        poly_maker_loop,
                    )
                    from backend.app.engine.sleeve_manifest import (
                        _maker_arb_sleeve_id,
                    )
                    from backend.app.strategies.polymarket.maker.acc_h import (
                        AccHStrategy,
                        AccHV2Strategy,
                    )
                    from backend.app.strategies.polymarket.maker.acc_m import (
                        AccMStrategy,
                        AccMV2Strategy,
                    )
                    from backend.app.strategies.polymarket.maker.mas import (
                        MasStrategy,
                        MasV2Strategy,
                    )
                    # Phase 31 — NEW shadow sleeves (TV_AGENT_CHANGES §4 + §5).
                    from backend.app.strategies.polymarket.maker.acc_pc import (
                        AccPCStrategy,
                        AccPCV2Strategy,
                    )
                    from backend.app.strategies.polymarket.maker.pat_shadow import (
                        PatShadowStrategy,
                    )
                    from backend.app.strategies.polymarket.maker.shadow_log import (
                        AsyncShadowLogger,
                    )
                    from backend.app.venues.polymarket.gamma_client import (
                        GammaClient as _MakerGammaClient,
                    )
                    from backend.app.venues.polymarket.onchain_oracle import (
                        OnchainOracle as _MakerOnchainOracle,
                    )
                    from backend.app.venues.polymarket.trade_mirror import (
                        TradeMirror,
                    )

                    # Parse cell CSVs from settings.
                    _maker_cell_assignments: dict[str, list[str]] = {
                        "ACC-M": [
                            c.strip()
                            for c in settings.tv_poly_maker_acc_m_cells.split(",")
                            if c.strip()
                        ],
                        "ACC-H": [
                            c.strip()
                            for c in settings.tv_poly_maker_acc_h_cells.split(",")
                            if c.strip()
                        ],
                        "MAS": [
                            c.strip()
                            for c in settings.tv_poly_maker_mas_cells.split(",")
                            if c.strip()
                        ],
                        # Phase 31 — NEW shadow sleeves.
                        "ACC-PC": [
                            c.strip()
                            for c in settings.tv_poly_maker_acc_pc_cells.split(",")
                            if c.strip()
                        ],
                        "PAT-SHADOW": [
                            c.strip()
                            for c in settings.tv_poly_maker_pat_shadow_cells.split(",")
                            if c.strip()
                        ],
                        # Phase C — V2 sleeves (TV_AGENT_SPEC_NEW_SLEEVES_V2_2026_05_27.md).
                        # Each V2 sleeve runs in parallel with its V1 sibling for a 14d A/B.
                        # cell_assignments key MUST stay raw display-form because the
                        # poly_maker_loop normaliser converts at loop entry (commit 67d89a1).
                        "ACC-M-V2": [
                            c.strip()
                            for c in settings.tv_poly_maker_acc_m_v2_cells.split(",")
                            if c.strip()
                        ] if settings.tv_poly_maker_acc_m_v2_enabled else [],
                        "ACC-H-V2": [
                            c.strip()
                            for c in settings.tv_poly_maker_acc_h_v2_cells.split(",")
                            if c.strip()
                        ] if settings.tv_poly_maker_acc_h_v2_enabled else [],
                        "ACC-PC-V2": [
                            c.strip()
                            for c in settings.tv_poly_maker_acc_pc_v2_cells.split(",")
                            if c.strip()
                        ] if settings.tv_poly_maker_acc_pc_v2_enabled else [],
                        "MAS-V2": [
                            c.strip()
                            for c in settings.tv_poly_maker_mas_v2_cells.split(",")
                            if c.strip()
                        ] if settings.tv_poly_maker_mas_v2_enabled else [],
                    }

                    # Build one strategy per cell (T-30-11-01: _parse_cell
                    # validates each cell; invalid → ValueError at boot).
                    _maker_strategies: list[Any] = []
                    for _cell in _maker_cell_assignments["ACC-M"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            AccMStrategy(settings, _asset, _tf)
                        )
                    for _cell in _maker_cell_assignments["ACC-H"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            AccHStrategy(settings, _asset, _tf)
                        )
                    for _cell in _maker_cell_assignments["MAS"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            MasStrategy(settings, _asset, _tf)
                        )
                    # Phase 31 — NEW sleeves.
                    for _cell in _maker_cell_assignments["ACC-PC"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            AccPCStrategy(settings, _asset, _tf)
                        )
                    for _cell in _maker_cell_assignments["PAT-SHADOW"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            PatShadowStrategy(settings, _asset, _tf)
                        )
                    # Phase C — V2 sleeve spawn blocks.
                    for _cell in _maker_cell_assignments["ACC-M-V2"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            AccMV2Strategy(settings, _asset, _tf)
                        )
                    for _cell in _maker_cell_assignments["ACC-H-V2"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            AccHV2Strategy(settings, _asset, _tf)
                        )
                    for _cell in _maker_cell_assignments["ACC-PC-V2"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            AccPCV2Strategy(settings, _asset, _tf)
                        )
                    for _cell in _maker_cell_assignments["MAS-V2"]:
                        _asset, _tf = _parse_cell(_cell)
                        _maker_strategies.append(
                            MasV2Strategy(settings, _asset, _tf)
                        )

                    # D-07: parse TV_POLY_MAKER_KILL (settings.tv_poly_maker_kill).
                    _maker_kill_set = _parse_kill_env(
                        settings.tv_poly_maker_kill or ""
                    )
                    logger.info(
                        "poly_maker.kill_set",
                        kills=[
                            f"{sc.strategy}:{sc.cell}"
                            for sc in _maker_kill_set
                        ],
                    )

                    # Three shadow loggers (one per strategy code; shared
                    # across cells of the same strategy).
                    _maker_log_dir = Path(settings.tv_poly_maker_log_dir)
                    _maker_shadow_loggers: dict[str, Any] = {
                        "ACC-M": AsyncShadowLogger(
                            "ACC-M",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        "ACC-H": AsyncShadowLogger(
                            "ACC-H",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        "MAS": AsyncShadowLogger(
                            "MAS",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        # Phase 31 — NEW shadow sleeves (TV_AGENT_CHANGES §4 + §5).
                        "ACC-PC": AsyncShadowLogger(
                            "ACC-PC",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        "PAT-SHADOW": AsyncShadowLogger(
                            "PAT-SHADOW",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        # Phase C — V2 sleeve shadow loggers. Writes to
                        # /var/log/tv/maker/{acc-m-v2,acc-h-v2,acc-pc-v2,mas-v2}_<date>.csv.
                        "ACC-M-V2": AsyncShadowLogger(
                            "ACC-M-V2",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        "ACC-H-V2": AsyncShadowLogger(
                            "ACC-H-V2",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        "ACC-PC-V2": AsyncShadowLogger(
                            "ACC-PC-V2",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                        "MAS-V2": AsyncShadowLogger(
                            "MAS-V2",
                            _maker_log_dir,
                            maxsize=settings.tv_poly_maker_queue_maxsize,
                            drain_batch_size=settings.tv_poly_maker_drain_batch_size,
                            drain_timeout_s=settings.tv_poly_maker_drain_timeout_s,
                            alert_service=alerts,
                        ),
                    }
                    for _logger_obj in _maker_shadow_loggers.values():
                        await _logger_obj.start()

                    # TradeMirror — separate WS connection from BookMirror
                    # per Pitfall 3 Option B (book + trade frames are on the
                    # same /ws/market endpoint but multiplexing them through
                    # one connection would mix message-rate constraints).
                    _maker_trade_mirror = TradeMirror()
                    await _maker_trade_mirror.start()

                    # Phase 32 Plan 32-10 — MakerFillSimulator instantiation.
                    # Lazy import inside lifespan to avoid circular dependency.
                    # Conditional on maker enabled + sim not disabled — operator
                    # can set TV_POLY_MAKER_SIM_DISABLED=true to skip (T-32-10-04).
                    if not settings.tv_poly_maker_sim_disabled:
                        from backend.app.engine.poly_maker_fill_sim import (
                            MakerFillSimulator,
                        )
                        _maker_fill_sim = MakerFillSimulator(
                            settings=settings,
                            shadow_loggers=_maker_shadow_loggers,
                            book_mirror=book_mirror,
                            alert_service=alerts,
                        )
                        await _maker_fill_sim.start()
                        logger.info("poly_maker_fill_sim.started")

                    # GammaClient — dedicated cache file to avoid contention
                    # with the discovery GammaClient (line ~1161).
                    _maker_gamma = _MakerGammaClient(
                        base_url=settings.tv_poly_gamma_api_url,
                        cache_path=settings.tv_poly_gamma_cache_path + ".maker",
                    )

                    # OnchainOracle — reuse the same RPC + CTF address as the
                    # rest of the lifespan. Boot guard: skip the maker spawn
                    # if RPC is unset; we'd crash later on resolution polls.
                    if not settings.tv_poly_rpc_url:
                        logger.critical(
                            "poly_maker.no_rpc_url",
                            hint=(
                                "TV_POLY_RPC_URL unset; maker-arb suite cannot "
                                "poll on-chain oracle. Spawn skipped."
                            ),
                        )
                    else:
                        _maker_oracle = _MakerOnchainOracle(
                            rpc_url=settings.tv_poly_rpc_url,
                            ctf_address=settings.tv_poly_ctf_address,
                        )

                        # Register the 6 day-1 sleeve_ids so Phase 28 tiles
                        # (OracleLagTile, BookHealthTile) light up without
                        # code changes. The sleeve_manifest registry is the
                        # introspection surface; ``introspect_sleeves``
                        # builds entries from the sleeve_ids passed in by
                        # the API layer.
                        _maker_sleeve_ids: list[str] = []
                        for _strat_code, _cells in _maker_cell_assignments.items():
                            for _cell in _cells:
                                _asset, _tf = _parse_cell(_cell)
                                _sid = _maker_arb_sleeve_id(
                                    _strat_code, _asset, _tf
                                )
                                _maker_sleeve_ids.append(_sid)
                        logger.info(
                            "poly_maker.sleeves_registered",
                            sleeve_ids=_maker_sleeve_ids,
                            n=len(_maker_sleeve_ids),
                        )

                        # Cross-restart re-mint defense (CLAUDE inv #2):
                        # scan today's mas CSV + pre-seed each MAS strategy's
                        # _pending_csv_recovery with prior inventory. When
                        # gamma's discovery re-fires SlugActive for a slug
                        # the previous process already minted, MAS reads the
                        # recovery stash + seed_inventory's the state without
                        # emitting a duplicate MINT. Without this, after every
                        # tv-engine restart MAS would re-mint every active slug
                        # ($30 per slug double-deploy in live mode).
                        from backend.app.strategies.polymarket.maker.mas import (
                            recover_mas_state_from_csv,
                        )
                        _today_str = datetime.now(UTC).strftime("%Y-%m-%d")
                        _mas_csv_path = _maker_log_dir / f"mas_{_today_str}.csv"
                        for _strat in _maker_strategies:
                            if isinstance(_strat, MasStrategy):
                                _n_recovered = recover_mas_state_from_csv(
                                    _strat, _mas_csv_path
                                )
                                if _n_recovered > 0:
                                    logger.info(
                                        "mas.boot_recovery.queued",
                                        asset=_strat.asset,
                                        tf=_strat.tf,
                                        n_slugs=_n_recovered,
                                    )

                        tg.create_task(
                            poly_maker_loop(
                                book_mirror=book_mirror,
                                trade_mirror=_maker_trade_mirror,
                                strategies=_maker_strategies,
                                cell_assignments=_maker_cell_assignments,
                                kill_set=_maker_kill_set,
                                shadow_loggers=_maker_shadow_loggers,
                                gamma_client=_maker_gamma,
                                onchain_oracle=_maker_oracle,
                                pool=pool,
                                alerts=alerts,
                                settings=settings,
                                shadow_mode=settings.tv_poly_maker_shadow_mode,
                                live_executor=None,
                                poly_merger_w3=None,
                                poly_merger_wallet=None,
                                private_key=None,
                                stop=stop,
                                fill_sim=_maker_fill_sim,  # Phase 32 Plan 32-10
                            ),
                            name="poly_maker.loop",
                        )
                        logger.info(
                            "poly_maker.spawned",
                            n_strategies=len(_maker_strategies),
                            n_cells=sum(
                                len(c) for c in _maker_cell_assignments.values()
                            ),
                            shadow_mode=settings.tv_poly_maker_shadow_mode,
                            kill_set_size=len(_maker_kill_set),
                        )
                else:
                    logger.info(
                        "poly_maker.disabled",
                        reason=(
                            "maker-arb suite DEPRECATED 2026-05-29 (operator: not working)"
                            if settings.tv_poly_maker_enabled
                            and settings.tv_poly_maker_deprecated
                            else "TV_POLY_MAKER_ENABLED=false"
                        ),
                    )

            # Phase 25 Tier B — Polygon gas-cost fee settler.
            # Operator opt-in: TV_POLY_FEE_SETTLER_ENABLED=true
            if os.getenv("TV_POLY_FEE_SETTLER_ENABLED", "false").lower() == "true":
                from backend.app.services.poly_fee_settler import (
                    poly_fee_settler_loop,
                )

                tg.create_task(
                    poly_fee_settler_loop(pool, stop),
                    name="poly_fee_settler.loop",
                )
                logger.info("poly_fee_settler.task_spawned")
            # Phase 6+: tg.create_task(BarEngine(pool=pool).run(), ...)
            # Phase 12+: tg.create_task(kill_event_consumer(...), ...)
            await stop.wait()
            raise asyncio.CancelledError  # triggers TaskGroup cancel
    except* asyncio.CancelledError:
        # Expected path on SIGTERM. Swallow so the finally block runs
        # without re-raising into SystemExit(non-zero).
        pass
    finally:
        # 2026-05-08 fix: every teardown step bounded by asyncio.wait_for so
        # one hung await doesn't burn systemd's 90s stop-sigterm budget.
        # Pre-fix VPS2 symptom: stop-sigterm timed out → SIGKILL signal=9
        # on every restart because asyncpg read_pool.close() blocked on
        # in-flight slow SQL queries (16-conn pool × N kline lookups
        # against legacy binance_klines_v2 path). Per-step caps:
        #   liq_db / book_mirror / binance_feed: 5s each
        #   pool / read_pool: 10s each
        # Total worst case: 35s of teardown vs systemd's 90s budget.
        async def _bounded(coro_factory, label: str, timeout_s: float) -> None:
            try:
                await asyncio.wait_for(coro_factory(), timeout=timeout_s)
            except asyncio.TimeoutError:
                logger.warning(
                    f"{label}.shutdown_timeout",
                    timeout_s=timeout_s,
                    note="forced past timeout — systemd-friendly graceful exit",
                )
            except Exception:  # pragma: no cover - defensive teardown
                logger.exception(f"{label}.shutdown_failed")

        # Phase 18.2 — close LiqDB pool first (if initialized) so its
        # connection slot is freed before the asyncpg pools shut down.
        if liq_db is not None:
            await _bounded(liq_db.close, "liq_db", 5.0)
        # Phase 27 LIVE-DISC-01 — stop PolyMarketDiscovery BEFORE BookMirror
        # so the discovery refresh-loop's eager-subscribe TODO branch can't
        # race a half-closed BookMirror. Reverse dependency order.
        if discovery is not None:
            try:
                await asyncio.wait_for(discovery.stop(), timeout=5.0)
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                logger.warning(
                    "lifespan.discovery_stop_failed", error=str(exc)[:200]
                )
        if _discovery_gamma is not None:
            try:
                await asyncio.wait_for(_discovery_gamma.close(), timeout=2.0)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
        # Phase 32 Plan 32-10 — stop MakerFillSimulator (5s budget; sim is
        # event-driven with no background queue so stop() is effectively instant).
        if _maker_fill_sim is not None:
            await _bounded(_maker_fill_sim.stop, "poly_maker_fill_sim", 5.0)
        # Phase 36-07 — close KalshiMarketDataFeed cleanly before BookMirror
        # and pool teardown (mirror book_mirror ordering).
        if kalshi_feed is not None:
            await _bounded(kalshi_feed.stop, "kalshi_feed", 5.0)
        # Phase 18.6 W1 — close BookMirror cleanly so its WS task doesn't
        # leak past pool teardown.
        if book_mirror is not None:
            await _bounded(book_mirror.stop, "book_mirror", 5.0)
        # Phase 22.1 — close BinanceMarketDataFeed cleanly + unbind from
        # bars module. Order matters: unbind first so any straggler
        # coroutines fall back to DB path (instead of seeing partially
        # closed feed state) before we cancel the WS reader task.
        if binance_feed is not None:
            try:
                from backend.app.data import bars as _bars_module

                _bars_module.set_feed_instance(None)
            except Exception:  # pragma: no cover - defensive teardown
                logger.exception("binance_feed.unbind_failed")
            await _bounded(binance_feed.stop, "binance_feed", 5.0)
            logger.info("binance_feed.shutdown_complete")
        # asyncpg pools last — they may have in-flight queries (esp. the
        # 16-conn read_pool that VPS2's legacy SQL kline path saturates).
        # Without a timeout, pool.close() awaits each connection's current
        # query to finish — a single 30s SQL kills graceful shutdown.
        await _bounded(pool.close, "tv_db_pool", 10.0)
        await _bounded(read_pool.close, "tv_storedata_pool", 10.0)
        logger.info("tv-engine.stopped")
    return 0


def main() -> None:
    """Sync entry point for ``python -m backend.app.engine.main``.

    2026-05-08 fix: previously `asyncio.run(_amain())` was the entry, but on
    VPS2 every shutdown showed the same pattern in journalctl:
        20:19:52.651 tv-engine.signal_received
        20:19:52.765 tv-engine.stopped       ← _amain() returned cleanly here
        20:21:22     systemd SIGKILL          ← but process didn't exit for 90s
    The 90s is `asyncio.run`'s internal cleanup — `shutdown_default_executor`
    hangs waiting for a stuck threadpool worker thread (likely a blocking
    socket/DB read that didn't honor cancellation). All async work is done
    by the time _amain() returns, so we can skip the rest of asyncio.run's
    cleanup entirely. Manual loop + `os._exit(rc)` exits in <1s.

    Trade-off: Python finalizers don't run (no atexit handlers, no
    `__del__`). All resources we care about (DB pools, WS clients, file
    handles) are explicitly closed in _amain()'s finally block, so this
    is safe. systemd sees a clean exit-code-0 and restart cycles run fast.
    """
    import os

    loop = asyncio.new_event_loop()
    try:
        rc = loop.run_until_complete(_amain())
    finally:
        # Skip loop.close() to avoid the executor-shutdown hang. The OS
        # will reclaim FDs, sockets, and threads when the process exits.
        os._exit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()


__all__ = ["main"]
