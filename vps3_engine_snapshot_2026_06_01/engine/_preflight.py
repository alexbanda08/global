"""Phase 26.3-03 — Polymarket live-mirror cascading preflight + spawn helpers.

Per CONTEXT D-05/D-06/D-07 + plan 26.3-03. This module sits alongside the
existing ``backend/app/engine/preflight.py`` (bar-boundary OPS-02) but
addresses a distinct concern — gating *live-mirror controller spawning*
behind a cascading safety check.

Public API
----------

- ``_run_live_mirror_preflight(app_state, settings, w3, pool, *, secrets_registry)``
  Returns ``(True, None)`` only when all 5 gates pass; ``(False, reason)``
  on first-fail. Gates run IN ORDER (cheap → expensive) with early-exit:

  1. ``POLY_FUNDER_ADDRESS`` resolvable in secrets registry.
  2. ``poly_signer_private_key`` PRESENT in secrets registry (presence
     only — value never read, never logged per CLAUDE.md inv #10).
  3. CTF Exchange allowance ≥ ``tv_poly_live_preflight_min_usdc_allowance``.
  4. NegRiskAdapter allowance ≥ same threshold.
  5. ``app_state.poly_redeemer_running == True``.

- ``_emit_blocked_audit_row(pool, reason)``
  INSERTs a ``kind='live_mirrors_blocked'`` row into ``trading.events``
  with ``data->>'reason'`` carrying the human-readable failure string.
  Mirrors the existing 26.1/26.2 ``live_mirrors_blocked`` audit pattern
  but discriminated via ``phase='26.3_preflight'``.

- ``_resolve_notional_for_sleeve(sleeve_id, settings)``
  Family detection — inverse pattern ``_sniper_INV$|_DOWN_INV$`` maps to
  ``tv_poly_live_notional_inverse_usd``; everything else falls into the
  momo bucket (``tv_poly_live_notional_momo_usd``). Conservative default
  per D-07.

- ``_spawn_live_mirrors(app_state, settings, w3, pool, *, secrets_registry,
  gamma_client=None, oracle=None, read_pool=None, executor_factory=None)``
  The main entry point — reads the allowlist CSV, runs the preflight, on
  pass instantiates ONE ``PolymarketClient`` (D-05) and builds one
  ``PolymarketUpdownController`` per allowlist entry with
  ``mode='live'`` + ``live_mirror_notional=<resolved>``. Returns the
  resulting controller list (empty on disabled / failed preflight).

Invariants
----------

- CLAUDE.md inv #10: ``poly_signer_private_key`` is checked via
  ``secrets_registry.has(...)`` — never read, never logged. The signer
  fail reason is the field NAME only.
- CLAUDE.md inv #13: live-mirror controllers consume TV-native data
  sources (``gamma_client``, ``oracle``, ``BookMirror`` via executor)
  per CONTEXT D-01.
- Boot does NOT crash on preflight failure — the caller logs CRITICAL +
  emits the audit row, then returns ``[]`` for paper-only fallback.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

from backend.app.venues.polymarket.allowance import check_allowance

if TYPE_CHECKING:
    from web3 import AsyncWeb3

    from backend.app.controllers.polymarket_updown import PolymarketUpdownController
    from backend.app.core.config import Settings

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Sleeve-family regex — per D-07
# ---------------------------------------------------------------------------

# Matches the two inverse sleeve_id tails in ALLOWLIST.md
# (`poly_updown_sol_5m_sniper_INV`, `poly_updown_eth_5m_sniper_DOWN_INV`).
# Anchored to end-of-string so partial matches don't accidentally route a
# future ``..._INVERSE_DAYTIME`` family into the inverse bucket.
_INVERSE_SLEEVE_PATTERN = re.compile(r"(_sniper_INV|_DOWN_INV)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_notional_for_sleeve(
    sleeve_id: str,
    settings: "Settings",
) -> Decimal:
    """Map a base sleeve_id → per-fire notional via the inverse-vs-momo regex.

    Inverse sleeves (`*_sniper_INV` / `*_DOWN_INV`) use the smaller
    ``tv_poly_live_notional_inverse_usd`` bucket; everything else falls
    into the (slightly larger) momo bucket. Returns ``Decimal`` so the
    downstream controller's ``LIVE_MIRROR_MAX_NOTIONAL`` cap comparison
    is precision-safe.
    """
    bucket = (
        settings.tv_poly_live_notional_inverse_usd
        if _INVERSE_SLEEVE_PATTERN.search(sleeve_id)
        else settings.tv_poly_live_notional_momo_usd
    )
    # Defensive str→Decimal — Pydantic may surface the field as float on
    # some env-loader paths; wrapping via str() preserves the textual
    # representation without binary-float distortion.
    return Decimal(str(bucket))


async def _run_live_mirror_preflight(
    app_state: Any,
    settings: "Settings",
    w3: "AsyncWeb3",
    pool: Any,
    *,
    secrets_registry: Any,
) -> tuple[bool, str | None]:
    """Cascading 5-gate preflight per CONTEXT D-06.

    Returns ``(True, None)`` only when ALL gates pass. Returns
    ``(False, reason)`` on the FIRST failure — subsequent gates are NOT
    exercised (saves RPC calls on funder/signer fails; saves a redundant
    Web3 round trip on ctf-fail).

    CLAUDE.md inv #10: ``poly_signer_private_key`` is checked for
    PRESENCE via ``secrets_registry.has(...)`` only — value never read,
    never appears in any log/log line/reason string.
    """
    # --- Gate 1: POLY_FUNDER_ADDRESS (fallback: poly_proxy_address) --------
    # In the v1 single-EOA setup, the funder (USDC holder) and the proxy
    # (operator wallet) are the same address. The Settings UI only writes
    # `poly_proxy_address` (lowercase, ALLOWED_KINDS). Fall back to it
    # when `POLY_FUNDER_ADDRESS` is absent so deploys that haven't been
    # double-keyed still pass preflight. Operator can override per
    # `POLY_FUNDER_ADDRESS` later if they split signer/funder.
    funder_address: str | None = None
    try:
        funder_address = secrets_registry.get("POLY_FUNDER_ADDRESS")
        if not funder_address:
            funder_address = secrets_registry.get("poly_proxy_address")
    except Exception:  # noqa: BLE001 — defensive; treat any registry error as missing
        funder_address = None
    if not funder_address:
        log.warning(
            "live_mirror_preflight.funder_missing",
            gate="POLY_FUNDER_ADDRESS",
            tried=["POLY_FUNDER_ADDRESS", "poly_proxy_address"],
        )
        return False, "POLY_FUNDER_ADDRESS / poly_proxy_address missing in secrets registry"

    # --- Gate 2: POLY_SIGNER_PRIVATE_KEY (presence only — never read/log) --
    try:
        signer_present = secrets_registry.has("poly_signer_private_key")
    except Exception:  # noqa: BLE001 — any registry exception → missing
        signer_present = False
    if not signer_present:
        # inv #10: log the FIELD NAME, never the value. Reason string
        # carries the same — verified in test #2 signer scenario.
        log.warning(
            "live_mirror_preflight.signer_missing",
            gate="POLY_SIGNER_PRIVATE_KEY",
        )
        return False, "POLY_SIGNER_PRIVATE_KEY missing in secrets registry"

    # --- Gate 3: CTF Exchange allowance ≥ threshold ------------------------
    threshold = Decimal(str(settings.tv_poly_live_preflight_min_usdc_allowance))
    try:
        ctf_allowance = await check_allowance(
            w3,
            funder_address,
            settings.tv_poly_ctf_address,
            settings.tv_poly_usdc_address,
        )
    except Exception as exc:  # noqa: BLE001 — RPC failure surfaced as gate-fail
        log.error(
            "live_mirror_preflight.ctf_rpc_failed",
            error=str(exc)[:200],
        )
        return False, f"CTF allowance RPC failed: {exc!s}"
    if ctf_allowance < threshold:
        return False, (
            f"CTF allowance ${ctf_allowance} < threshold ${threshold}"
        )

    # --- Gate 4: NegRiskAdapter allowance ≥ threshold ----------------------
    negrisk_addr = settings.tv_poly_neg_risk_adapter_address
    if not negrisk_addr:
        return False, "tv_poly_neg_risk_adapter_address unset"
    try:
        negrisk_allowance = await check_allowance(
            w3,
            funder_address,
            negrisk_addr,
            settings.tv_poly_usdc_address,
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "live_mirror_preflight.negrisk_rpc_failed",
            error=str(exc)[:200],
        )
        return False, f"NegRisk allowance RPC failed: {exc!s}"
    if negrisk_allowance < threshold:
        return False, (
            f"NegRisk allowance ${negrisk_allowance} < threshold ${threshold}"
        )

    # --- Gate 5: poly_redeemer task running --------------------------------
    if not getattr(app_state, "poly_redeemer_running", False):
        return False, "poly_redeemer task not running"

    log.info(
        "live_mirror_preflight.passed",
        funder=funder_address,
        ctf_allowance_usd=str(ctf_allowance),
        negrisk_allowance_usd=str(negrisk_allowance),
        threshold_usd=str(threshold),
    )
    return True, None


async def _emit_blocked_audit_row(pool: Any, reason: str) -> None:
    """INSERT ``kind='live_mirrors_blocked'`` row into ``trading.events``.

    Mirrors the existing 26.1/26.2 audit pattern but tagged with
    ``phase='26.3_preflight'`` so operator dashboards can distinguish the
    three preflight emitters.

    Failure-handling: wraps the INSERT in a try/except so a transient DB
    error during preflight does NOT propagate up into the engine boot
    path (we'd rather lose the audit row than crash the engine; the
    structlog CRITICAL line emitted by the caller is the non-DB fallback
    record of the event).
    """
    payload = json.dumps({"reason": reason, "phase": "26.3_preflight"})
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO trading.events (kind, at, data) "
                "VALUES ($1, now(), $2::jsonb)",
                "live_mirrors_blocked",
                payload,
            )
    except Exception:  # noqa: BLE001 — defensive; never crash engine boot
        log.exception("live_mirror_preflight.audit_row_failed")


# ---------------------------------------------------------------------------
# Sleeve_id → controller config parsing (D-13 — executor discretion)
# ---------------------------------------------------------------------------

# Map a base sleeve_id from ALLOWLIST.md → (strategy_mode, hedge_policy).
# The 7 sleeves are explicitly listed (deterministic, byte-identical to
# ALLOWLIST.md commit ae6fb0b) — no regex inference required. Any future
# sleeve added to the allowlist MUST also be added here.
#
# Note on controller fan-out semantics (D-13 discretion): each
# PolymarketUpdownController manages all 6 (sym, tf) slots for its
# strategy_mode + hedge_policy. The live-mirror spawn deduplicates by
# (strategy_mode, hedge_policy) so we don't construct redundant
# controllers. The operator's per-sleeve audit-row filtering at the
# dashboard layer handles the subset granularity.
_SLEEVE_CONFIG_MAP: dict[str, tuple[str, str | None]] = {
    "poly_updown_sol_5m_sniper_INV": ("inverse_sol_sniper", None),
    "poly_updown_eth_5m_sniper_DOWN_INV": ("inverse_sniper_down", None),
    "poly_updown_btc_15m_momo_HOLD": ("momo", "HOLD_ONLY"),
    "poly_updown_eth_15m_momo_v2_HOLD": ("momo_v2", "HOLD_ONLY"),
    "poly_updown_btc_15m_momo_v2_HOLD": ("momo_v2", "HOLD_ONLY"),
    "poly_updown_eth_15m_sniper": ("sniper", None),
    "poly_updown_btc_15m_momo_SELL": ("momo", "SELL_BID"),
    # 2026-05-15 — added btc_15m_momo_HEDGE per operator request after
    # paper-perf review (+$343 / 76.7% win / PF 2.78 over 43 trades on VPS3).
    "poly_updown_btc_15m_momo_HEDGE": ("momo", "HEDGE_HOLD"),
    # 2026-05-23 — added btc_5m_momo_HOLD per operator request after VPS3
    # F7 paper showed 70% WR on poly_updown_btc_5m_momo_HOLD_f7. Same
    # (momo, HOLD_ONLY) config as the existing btc_15m_momo_HOLD entry —
    # the dedupe path means we reuse the SAME live-mirror controller and
    # extend its slot_allowlist to also fire on (BTC, 5m). Live audit
    # rows tagged poly_updown_btc_5m_momo_HOLD_LIVE_f7 (D-02 _LIVE suffix
    # + auto _f7 from controller's default F7 mode for momo).
    "poly_updown_btc_5m_momo_HOLD": ("momo", "HOLD_ONLY"),
    # 2026-05-24 — added sol_5m_momo_v2_HOLD per operator request after VPS3
    # F7 paper showed positive edge on poly_updown_sol_5m_momo_v2_HOLD_f7.
    # Shares the (momo_v2, HOLD_ONLY) controller already spawned for
    # eth_15m_momo_v2_HOLD — dedupe extends slot_allowlist to also fire on
    # (SOL, 5m). Live audit rows tagged poly_updown_sol_5m_momo_v2_HOLD_LIVE_f7.
    "poly_updown_sol_5m_momo_v2_HOLD": ("momo_v2", "HOLD_ONLY"),
    # 2026-05-27 — added eth_5m_v3_2 per operator request after VPS3 shadow
    # showed 70.6% WR (24W/10L), +$298.83 lifetime PnL over 16 days
    # (~2 trades/day). Spawns its OWN dedicated controller because v3_2 is
    # a distinct strategy_mode (sniper-style + 3 selective gates: hour
    # blocklist {1,16,22 UTC} + macro 2-of-3 alignment + liq-quiet regime).
    # hedge_policy=None — v3 family controllers don't use hedge policies.
    # Notional: falls into momo bucket via _resolve_notional_for_sleeve →
    # tv_poly_live_notional_momo_usd = $1.00/fire. Controller restricts to
    # 5m TF (polymarket_updown.py:2133), so the slot_allowlist is the
    # singleton {("ETH", "5m")}. Live audit rows tagged with _LIVE suffix.
    # Note: liq-quiet gate is effectively no-op on Ireland (liq_db block
    # commented out in engine/main.py:1524); fails-open per D-05.
    "poly_updown_eth_5m_v3_2": ("v3_2", None),
}


def _parse_sleeve_to_controller_config(
    base_sleeve_id: str,
) -> tuple[str, str | None] | None:
    """Return ``(strategy_mode, hedge_policy)`` for a known sleeve_id, else None.

    Returning None signals "unknown sleeve" to the caller, which should
    log + skip (defense against env-var typos). The 7 known sleeves come
    from ALLOWLIST.md commit ``ae6fb0b``.
    """
    return _SLEEVE_CONFIG_MAP.get(base_sleeve_id)


# ---------------------------------------------------------------------------
# Spawn entry point (D-05)
# ---------------------------------------------------------------------------


async def _spawn_live_mirrors(
    app_state: Any,
    settings: "Settings",
    w3: "AsyncWeb3",
    pool: Any,
    *,
    secrets_registry: Any,
    gamma_client: Any | None = None,
    oracle: Any | None = None,
    read_pool: Any | None = None,
    book_mirror: Any | None = None,
    discovery: Any | None = None,
    executor_factory: Any | None = None,
) -> list["PolymarketUpdownController"]:
    """Spawn live-mirror controllers per ``TV_POLY_LIVE_ALLOWLIST``.

    Per CONTEXT D-05. Behavior contract:

    - Allowlist empty → log ``live_mirrors.disabled_no_allowlist`` + return ``[]``.
    - Preflight fails → log CRITICAL ``live_mirrors.deferred`` + emit
      ``live_mirrors_blocked`` audit row + return ``[]``.
    - Preflight passes → instantiate ONE ``PolymarketClient`` (single
      signing key per process; D-05) + iterate the deduped
      (strategy_mode, hedge_policy) configs from the allowlist + return
      the controller list. Caller appends to ``_all_controllers`` so the
      master scheduler picks them up.

    Args:
        app_state: namespace with ``poly_redeemer_running`` flag (Phase 26.2).
        settings: ``Settings`` instance (Phase 26.3 fields populated by 26.3-02).
        w3: pre-constructed ``AsyncWeb3`` for allowance reads.
        pool: write-pool for ``trading.events`` audit-row emission.
        secrets_registry: Phase 17.2 ``SecretsRegistry`` (frozen).
        gamma_client: Phase 26 ``GammaClient`` — passed through to the
            live controllers (CLAUDE.md inv #13 TV-native data).
        oracle: Phase 26 ``OnchainOracle`` — same rationale.
        read_pool: read-pool (tradingvenue_ro) for the controllers'
            ``pool`` kwarg (existing controllers use ``read_pool`` —
            mirror for live).
        book_mirror: Phase 18.6 WS BookMirror (TV-native Tier-1 reads).
        executor_factory: optional callable returning a configured
            executor. When None, a default ``PolymarketClient`` is
            constructed using ``settings``/``secrets_registry``. Provided
            primarily for tests + for callers that want to share an
            existing live client.

    Returns:
        List of constructed ``PolymarketUpdownController`` instances —
        empty when disabled or preflight failed.
    """
    allowlist_csv = (settings.tv_poly_live_allowlist or "").strip()
    if not allowlist_csv:
        log.info("live_mirrors.disabled_no_allowlist")
        return []

    preflight_ok, reason = await _run_live_mirror_preflight(
        app_state, settings, w3, pool, secrets_registry=secrets_registry,
    )
    if not preflight_ok:
        log.critical("live_mirrors.deferred", reason=reason)
        await _emit_blocked_audit_row(pool, reason or "unknown")
        return []

    # Phase 27 LIVE-DISC-02 — live mode REQUIRES PolyMarketDiscovery
    # (CLAUDE.md inv #13: TV-native data infrastructure for live).
    # The engine lifespan in main.py instantiates discovery before
    # _spawn_live_mirrors runs; missing discovery here is a fatal config
    # bug (refuse to spawn live mirrors rather than crash on controller
    # ctor).
    if discovery is None:
        log.critical("preflight.live_mirror.missing_discovery")
        await _emit_blocked_audit_row(pool, "live_mirror.missing_discovery")
        return []

    # Lazy import — avoids circular import (controller module imports a lot;
    # _preflight is consumed at engine boot only, never at controller-test time).
    from backend.app.controllers.polymarket_updown import (
        PolymarketUpdownController,
    )

    # Single PolymarketClient per process (D-05 — single signing key).
    # When the caller supplies ``executor_factory``, use it; otherwise
    # build a default live client from settings + secrets.
    if executor_factory is not None:
        poly_live_client = executor_factory()
    else:
        from backend.app.venues.polymarket.client import PolymarketClient
        from backend.app.venues.polymarket.settings import get_poly_settings

        poly_settings = get_poly_settings()
        # 2026-05-14 — force mode='live' on the live-mirror PolymarketClient.
        # PolySettings.mode defaults to "paper", which routes
        # PolymarketClient.get_orderbook_snapshot through _paper_dispatch's
        # lazily-constructed stub PolyPaperExecutor (no book_mirror, no
        # pg_pool, no http_client). Result: empty books → controllers log
        # `qty_compute_failed_no_book` → 0 live fills.
        # Setting mode='live' picks the proper 3-tier path
        # (BookMirror → CLOB SDK → Storedata) wired in client.py:331-415.
        poly_settings = poly_settings.model_copy(update={"mode": "live"})
        poly_live_client = PolymarketClient(
            poly_settings,
            secrets_registry=secrets_registry,
            pg_pool=read_pool,
            book_mirror=book_mirror,
        )

    # Dedupe (strategy_mode, hedge_policy) — multiple allowlist entries
    # mapping to the same controller config (e.g. btc_15m_momo_v2_HOLD +
    # eth_15m_momo_v2_HOLD both → (momo_v2, HOLD_ONLY)) construct ONE
    # controller. The controller fires across all its (sym, tf) slots
    # internally; per-sleeve granularity is a dashboard-layer concern.
    #
    # 2026-05-16 — collect the (sym, tf) for EACH allowlisted sleeve so
    # we can pass a per-controller slot_allowlist. Without this, allowlisting
    # ``btc_15m_momo_HOLD`` ALSO fires SOL+ETH and 5m for the same policy
    # (controller fans out over all 6 slots it owns).
    seen_configs: set[tuple[str, str | None]] = set()
    seen_sleeves_for_notional: dict[tuple[str, str | None], str] = {}
    slot_allowlist_by_cfg: dict[tuple[str, str | None], set[tuple[str, str]]] = {}
    for raw in allowlist_csv.split(","):
        base_sleeve_id = raw.strip()
        if not base_sleeve_id:
            continue
        cfg = _parse_sleeve_to_controller_config(base_sleeve_id)
        if cfg is None:
            log.warning(
                "live_mirrors.unknown_sleeve_skipped",
                sleeve_id=base_sleeve_id,
            )
            continue
        if cfg not in seen_configs:
            seen_configs.add(cfg)
            seen_sleeves_for_notional[cfg] = base_sleeve_id
            slot_allowlist_by_cfg[cfg] = set()
        # Parse (sym, tf) from canonical poly_updown_<sym>_<tf>_<rest> form
        parts = base_sleeve_id.split("_")
        if len(parts) >= 4 and parts[0] == "poly" and parts[1] == "updown":
            sym = parts[2].upper()
            tf = parts[3].lower()
            if sym in ("BTC", "ETH", "SOL") and tf in ("5m", "15m"):
                slot_allowlist_by_cfg[cfg].add((sym, tf))
            else:
                log.warning(
                    "live_mirrors.slot_parse_unknown",
                    sleeve_id=base_sleeve_id,
                    parsed_sym=sym,
                    parsed_tf=tf,
                )

    mirrors: list[PolymarketUpdownController] = []
    for (strategy_mode, hedge_policy), representative_sleeve in (
        seen_sleeves_for_notional.items()
    ):
        notional = _resolve_notional_for_sleeve(representative_sleeve, settings)
        slot_allowlist = frozenset(slot_allowlist_by_cfg.get(
            (strategy_mode, hedge_policy), set()
        ))
        ctor_kwargs: dict[str, Any] = {
            "pool": read_pool,
            "executor": poly_live_client,
            "mode": "live",
            "strategy_mode": strategy_mode,
            "live_mirror_notional": notional,
            "gamma_client": gamma_client,
            "oracle": oracle,
            "book_mirror": book_mirror,
            # Phase 27 LIVE-DISC-02 — wire TV-native PolyMarketDiscovery.
            # Engine lifespan (main.py) calls _spawn_live_mirrors with
            # ``discovery=app.state.poly_market_discovery`` semantically;
            # tv-engine has no FastAPI app so the live binding is the
            # ``discovery`` kwarg propagated here. Plan 27-01 SUMMARY.md
            # documents the no-FastAPI-app caveat.
            "discovery": discovery,
            # 2026-05-16 — per-(sym, tf) filter (see slot_allowlist_by_cfg
            # comment above). Empty → controller fires ALL its 6 slots
            # (back-compat with pre-2026-05-16 behavior).
            "slot_allowlist": slot_allowlist if slot_allowlist else None,
        }
        if hedge_policy is not None:
            ctor_kwargs["hedge_policy"] = hedge_policy
        controller = PolymarketUpdownController(**ctor_kwargs)
        mirrors.append(controller)
        log.info(
            "live_mirrors.controller_constructed",
            strategy_mode=strategy_mode,
            hedge_policy=hedge_policy,
            notional_usd=str(notional),
            representative_sleeve=representative_sleeve,
            slot_allowlist=sorted(slot_allowlist) if slot_allowlist else None,
        )

    log.info(
        "live_mirrors.spawned",
        count=len(mirrors),
        allowlist=allowlist_csv,
    )
    return mirrors


__all__ = [
    "_emit_blocked_audit_row",
    "_parse_sleeve_to_controller_config",
    "_resolve_notional_for_sleeve",
    "_run_live_mirror_preflight",
    "_spawn_live_mirrors",
]
