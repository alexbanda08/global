"""PolymarketClient — V2 CLOB venue client (Phase 14 Task 6).

Mirrors backend/app/venues/hyperliquid/client.py public API:
- place_entry_order(token_id, qty, limit_px, sleeve_id, side="buy")
- place_exit_order(token_id, qty, limit_px, sleeve_id)   # NO reduce_only
- cancel_order(order_id)
- get_orderbook_snapshot(token_id)
- get_fills(...)
- get_balance_allowance(asset_type, token_id=None)

VEN-09 (the $100k+ guard) is layered three ways:
  1. SPLIT API — there is no public `place_order` callable; an executor
     mis-routing a position-close to entry will fall through type checks.
  2. STATIC ASSERT — place_exit_order asserts `side == "sell"` BEFORE
     touching the SDK; AssertionError carries "POLY VEN-09 VIOLATION".
  3. PRE-CHECK — get_balance_allowance(CONDITIONAL, token_id) confirms
     position size ≥ qty; insufficient → REJECTED("EXIT_INSUFFICIENT_POSITION")
     with `pre_check_balance` populated for audit.

Per Phase 14 D-08 the Rust signer is gone; py-clob-client-v2 signs
EIP-712 v2 natively in-process. Per D-07 the host is read from
`TV_POLY_CLOB_HOST` (default clob-v2; flip to clob.polymarket.com
post-2026-04-28 cutover via env, no redeploy).
"""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from backend.app.core.secrets_registry import SecretsRegistry
from backend.app.venues.polymarket.live_gate import (
    LiveModeAckError,
    check_poly_live_ack,
)
from backend.app.venues.polymarket.models import (
    Fill,
    FillStatus,
    OrderbookSnapshot,
    OrderResult,
    OrderType,
)
from backend.app.venues.polymarket.rounding import (
    validate_fok_sell_decimals,
)
from pydantic import SecretStr

from backend.app.venues.polymarket.settings import PolySettings

if TYPE_CHECKING:  # pragma: no cover
    from datetime import date


# Sentinel signature/key strings the structlog processor strips.
_REDACTED = "[REDACTED]"
_REDACT_KEYS = frozenset(
    {"signature", "priv_key", "private_key", "private_key_ref", "key"}
)


def redact_secrets_processor(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor — redacts {signature, priv_key, ...} fields.

    T-14-02 / T-14-04 mitigation. Run BEFORE any renderer; redact
    nested dicts depth-1 (we don't recurse — keep cheap).
    """
    for k in list(event_dict.keys()):
        if k.lower() in _REDACT_KEYS:
            event_dict[k] = _REDACTED
        elif isinstance(event_dict[k], dict):
            inner = event_dict[k]
            for ik in list(inner.keys()):
                if ik.lower() in _REDACT_KEYS:
                    inner[ik] = _REDACTED
    return event_dict


# Do NOT call structlog.configure() here — that would unconditionally replace
# the process-wide pipeline (including the global redact_secrets processor
# registered in backend.app.core.logging.configure_logging), violating
# CLAUDE.md inv #10.  The global pipeline already covers all redaction
# patterns (field-name keys AND regex patterns for Fernet/hex private keys).
# The local redact_secrets_processor remains available for direct use in
# tests or if the global pipeline is extended.
log = structlog.get_logger("backend.app.venues.polymarket.client")


class PolymarketClient:
    """Async wrapper around py_clob_client_v2.ClobClient.

    SDK is sync; we wrap each call with `asyncio.to_thread` (mirrors
    HL pattern). Live mode requires a fresh POLY_LIVE_ACK YAML file.
    """

    def __init__(
        self,
        settings: PolySettings,
        paper_backend: Any | None = None,
        today: "date | None" = None,
        *,
        secrets_registry: SecretsRegistry | None = None,
        # Phase 18.6 W1.B (audit 2026-05-06 follow-up): live-side
        # 3-tier book reads. Live convergence with paper hot path —
        # what we test in shadow IS what runs in live (CLAUDE inv #13).
        book_mirror: Any | None = None,
        pg_pool: Any | None = None,
        alert_service: Any | None = None,
    ) -> None:
        self.settings = settings
        self._paper = paper_backend
        self._clob: Any | None = None
        # Phase 18.6 W1.B — Tier-1 (BookMirror) + Tier-3 (Storedata DB) plumbing.
        # Tier-2 (CLOB SDK) is the existing path via self._clob.
        self._book_mirror = book_mirror
        self._pg_pool = pg_pool
        self._alert_service = alert_service

        # Phase 17.2 SECRETS-UI-03: prefer SecretsRegistry over env vars.
        # Backward-compatible: if registry is None or doesn't have the
        # kind, the existing settings.private_key_ref / funder_address
        # path is unchanged. The plain-text private key + proxy are
        # cached on the client so set_max_usdc_allowance() can sign
        # raw ERC20 approve txs without rebuilding the SDK signer.
        self._signer_private_key: str | None = None
        self._proxy_address: str | None = None
        if secrets_registry is not None and secrets_registry.has("poly_signer_private_key"):
            self._signer_private_key = secrets_registry.get("poly_signer_private_key")
            self._proxy_address = secrets_registry.get("poly_proxy_address")
        # DIAG 2026-05-14: log registry-binding STATE only (no plaintext).
        log.info(
            "polymarket_client.ctor",
            registry_is_none=secrets_registry is None,
            registry_kinds=(
                sorted(secrets_registry.kinds) if secrets_registry is not None else []
            ),
            signer_bound=self._signer_private_key is not None,
            signer_len=(
                len(self._signer_private_key) if self._signer_private_key else 0
            ),
            proxy_bound=self._proxy_address is not None,
        )
        # Polygon RPC URL for raw eth_sendRawTransaction.  Plan 17.2
        # picks this up from `Settings.polygon_rpc_url` at the call
        # site (the engine_tasks worker constructs the client with
        # the URL); env var fallback for back-compat / tests.
        self._rpc_url: str = os.environ.get(
            "POLYGON_RPC_URL", "https://polygon-rpc.com"
        )

        if settings.mode == "live":
            from datetime import date as _date

            today_real = today or _date.today()
            ok, reason = check_poly_live_ack(
                mode="live",
                ack_path_template=settings.live_ack_path_template,
                today=today_real,
                configured_clob_host=settings.clob_host,
            )
            if not ok:
                raise LiveModeAckError(reason)

            # 2026-05-14 — fall back to secrets_registry when the
            # POLY_FUNDER_ADDRESS / POLY_PRIVATE_KEY_REF env vars aren't
            # set. Phase 17.2 SECRETS-UI-03 stores both under
            # `poly_proxy_address` + `poly_signer_private_key` in
            # trading.secrets; the operator-facing UI writes there, not
            # to env vars. Without this fallback the live gate refuses
            # to construct even though the credentials are present.
            funder_addr = settings.funder_address
            if not funder_addr and self._proxy_address:
                funder_addr = self._proxy_address
            if not funder_addr:
                raise LiveModeAckError(
                    "live mode requires POLY_FUNDER_ADDRESS or "
                    "poly_proxy_address in secrets registry"
                )
            private_key_secret: SecretStr | None = settings.private_key_ref
            if private_key_secret is None and self._signer_private_key:
                private_key_secret = SecretStr(self._signer_private_key)
            if private_key_secret is None:
                raise LiveModeAckError(
                    "live mode requires POLY_PRIVATE_KEY_REF or "
                    "poly_signer_private_key in secrets registry"
                )

            # Inject the resolved credentials so _build_clob_client sees
            # them regardless of source.
            live_settings = settings.model_copy(
                update={
                    "funder_address": funder_addr,
                    "private_key_ref": private_key_secret,
                }
            )
            self._clob = self._build_clob_client(live_settings)

        # Paper mode: no SDK build; route to PolyPaperExecutor.

    # -------- SDK construction --------

    @staticmethod
    def _build_clob_client(settings: PolySettings) -> Any:
        """Construct py_clob_client_v2.ClobClient — live mode only.

        Per D-08 we hand the SDK a key reference once; the SDK keeps
        the EIP-712 signer object inside its own process boundary.
        Per the actual SDK signature, the constructor uses `chain_id`
        (NOT `chain`) — Phase 14 D-07 reference predates SDK probe.

        2026-05-15 Phase 27 G7 burn-in fix #2: Polymarket CLOB v2
        requires API credentials (api_key + secret + passphrase) on
        every order-placement endpoint. Without `set_api_creds`, every
        `post_order` call is rejected with
        "API Credentials are needed to interact with this endpoint!".
        Pre-Phase 27 this bug was masked because orders never reached
        the submission stage (qty_compute_failed killed them at the
        BookMirror tuple-vs-object bug, fixed 4a6d44d).

        `create_or_derive_api_key()` POSTs to `/auth/api-key`, signs
        a derivation nonce with the L1 key, and returns ApiCreds. This
        is idempotent on Polymarket's side — re-deriving for the same
        L1 key returns the same creds. Per-process one-time call.
        """
        from py_clob_client_v2.client import ClobClient  # type: ignore[import-untyped]

        secret = settings.private_key_ref
        key = secret.get_secret_value() if secret is not None else None
        c = ClobClient(
            host=settings.clob_host,
            chain_id=settings.chain,
            key=key,
            signature_type=settings.signature_type,
            funder=settings.funder_address,
        )
        # Derive + bind API credentials so order endpoints accept signed orders.
        # Best-effort: if derivation fails (network glitch / 5xx), continue —
        # the failure will surface as "API Credentials needed" on the first
        # order attempt rather than crashing controller construction.
        if key:
            try:
                creds = c.create_or_derive_api_key()
                c.set_api_creds(creds)
                log.info("polymarket_client.api_creds_derived")
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "polymarket_client.api_creds_derive_failed",
                    error=str(exc)[:200],
                )
        return c

    # -------- public API: entry --------

    async def place_entry_order(
        self,
        token_id: int,
        qty: Decimal,
        limit_px: Decimal,
        sleeve_id: str,
        side: str = "buy",
    ) -> OrderResult:
        """Place a GTC entry order (default side=buy on V2 binaries)."""
        if self.settings.mode == "paper":
            return await self._paper_dispatch(
                "place_entry_order",
                token_id=token_id,
                qty=qty,
                limit_px=limit_px,
                sleeve_id=sleeve_id,
                side=side,
            )
        return await self._submit_order(
            token_id=token_id,
            qty=qty,
            limit_px=limit_px,
            side=side,
            sleeve_id=sleeve_id,
            order_type="GTC",
            intent="entry",
        )

    # -------- public API: exit (VEN-09 hot path) --------

    async def place_exit_order(
        self,
        token_id: int,
        qty: Decimal,
        limit_px: Decimal,
        sleeve_id: str,
        side: str = "sell",
    ) -> OrderResult:
        """Place a FAK exit order. side MUST be 'sell' (VEN-09)."""

        # === VEN-09 STATIC ASSERT — DO NOT REMOVE ===
        # A wrong-shaped exit call would otherwise flip a long position
        # into a hedged short. Hard assert at $100k+ scale.
        assert side == "sell", (
            f"POLY VEN-09 VIOLATION: place_exit_order called with "
            f"side={side!r}; only 'sell' is allowed."
        )

        if self.settings.mode == "paper":
            # Pre-check still runs in paper mode for parity with live.
            return await self._paper_dispatch(
                "place_exit_order",
                token_id=token_id,
                qty=qty,
                limit_px=limit_px,
                sleeve_id=sleeve_id,
                side=side,
            )

        # Pre-check: position must be ≥ qty.
        balance = await self._fetch_conditional_balance(token_id)
        if balance < qty:
            log.warning(
                "poly.exit.pre_check_insufficient",
                sleeve_id=sleeve_id,
                token_id=token_id,
                qty=str(qty),
                balance=str(balance),
            )
            return OrderResult(
                status=FillStatus.REJECTED,
                intent="exit",
                reason="EXIT_INSUFFICIENT_POSITION",
                pre_check_balance=balance,
            )

        return await self._submit_order(
            token_id=token_id,
            qty=qty,
            limit_px=limit_px,
            side="sell",
            sleeve_id=sleeve_id,
            order_type="FAK",
            intent="exit",
        )

    async def _forced_exit_market(
        self,
        token_id: int,
        qty: Decimal,
        limit_px: Decimal,
        sleeve_id: str,
    ) -> OrderResult:
        """Kill-switch / SL-cross forced FOK sell. NOT public."""

        # Same VEN-09 invariants — side hardcoded; call as if exit.
        # FOK sell-decimals validation per RESEARCH issue #121.
        # We compute maker/taker amounts as price*size; in V2 these are
        # the integer base-units. The 2dp/4dp rule applies to the
        # decimal representation pre-base-unit-conversion.
        validate_fok_sell_decimals(
            maker_amt=qty,
            taker_amt=(qty * limit_px),
        )
        return await self._submit_order(
            token_id=token_id,
            qty=qty,
            limit_px=limit_px,
            side="sell",
            sleeve_id=sleeve_id,
            order_type="FOK",
            intent="exit",
        )

    # -------- public API: cancel + reads --------

    async def cancel_order(self, order_id: str) -> dict:
        if self.settings.mode == "paper":
            return await self._paper_dispatch(
                "cancel_order", order_id=order_id
            )
        return await asyncio.to_thread(self._clob.cancel_order, order_id)

    async def get_orderbook_snapshot(
        self, token_id: int
    ) -> OrderbookSnapshot:
        """Live-mode 3-tier book read (Phase 18.6 W1.B audit 2026-05-06).

        Tier-1: BookMirror (TV-native WS, <10ms staleness, in-memory).
        Tier-2: CLOB SDK get_order_book (existing path; ~50ms RTT;
                NOTE Polymarket REST cache observed at 33s — fine for
                bar-close non-momo strategies but stale for momo's
                ws+120 fire offset, which Tier-1 covers).
        Tier-3: Storedata public.orderbook_snapshots_v2 — disaster
                fallback when both upstream tiers fail. Emits CRITICAL
                alert when it answers (means hot-path is degraded).

        Returns ``OrderbookSnapshot`` Pydantic model so existing callers
        (e.g. ``PolymarketMarketDataFeed.snapshot_at_bar_close``) keep
        working. Internally, dict-shape returns from BookMirror /
        Storedata are wrapped via ``_dict_to_orderbook_snapshot``.

        CLAUDE.md inv #13: this is the LIVE hot-path. Storedata-as-primary
        is FORBIDDEN — it's Tier-3-with-critical-alert only.
        """
        if self.settings.mode == "paper":
            return await self._paper_dispatch(
                "get_orderbook_snapshot", token_id=token_id
            )

        # 2026-05-14 DIAG: per-tier outcome trace (one log per call) —
        # 0 live fills + 0 `clob_orderbook_fetch_failed` warns mean the
        # live PolymarketClient silently falls through to the empty stub
        # for OPEN markets with rich CLOB books. Capture which tier
        # answered (or didn't) so the next session can pinpoint the gap.
        diag: dict[str, Any] = {
            "tier1": "skip_no_mirror",
            "tier2": "not_attempted",
            "tier3": "skip_no_pool",
        }

        # Tier 1: BookMirror.
        if self._book_mirror is not None:
            ws_book = self._book_mirror.get(str(token_id))
            if ws_book is None:
                diag["tier1"] = "miss_not_subscribed"
            elif not (ws_book.get("asks") or ws_book.get("bids")):
                diag["tier1"] = "empty_no_snapshot_yet"
            else:
                diag["tier1"] = "hit"
                diag["t1_n_bids"] = len(ws_book.get("bids") or [])
                diag["t1_n_asks"] = len(ws_book.get("asks") or [])
                log.info("live.book_diag", token_id=str(token_id), **diag)
                return self._dict_to_orderbook_snapshot(
                    ws_book, token_id=token_id, source="ws_mirror"
                )

        # Tier 2: CLOB SDK (existing path).
        raw_t2: Any = None
        try:
            raw_t2 = await asyncio.to_thread(
                self._clob.get_order_book, str(token_id)
            )
            diag["t2_raw_type"] = type(raw_t2).__name__
            diag["t2_raw_truthy"] = bool(raw_t2)
            snap = self._parse_orderbook(raw_t2)
            if snap is None:
                diag["tier2"] = "parse_returned_none"
            else:
                diag["t2_n_bids_parsed"] = len(snap.bids)
                diag["t2_n_asks_parsed"] = len(snap.asks)
                if len(snap.bids) > 0 or len(snap.asks) > 0:
                    diag["tier2"] = "hit"
                    log.info(
                        "live.book_diag", token_id=str(token_id), **diag
                    )
                    return snap
                diag["tier2"] = "parse_empty_levels"
        except Exception as exc:  # noqa: BLE001 — fall through to Tier-3
            diag["tier2"] = "exception"
            diag["t2_err"] = str(exc)[:200]
            log.warning(
                "live.clob_orderbook_fetch_failed",
                token_id=str(token_id),
                err=str(exc),
            )

        # LIVE-DISC-03: live mode never consults Storedata Tier-3 (CLAUDE inv #13).
        # Storedata-as-primary is FORBIDDEN for live hot-path. Return empty snapshot
        # so downstream qty-compute fails gracefully (qty_compute_failed_no_book).
        if self.settings.mode == "live":
            log.warning(
                "live.book_unreadable",
                token_id=str(token_id),
                tier1_state=diag.get("tier1", "skip_no_mirror"),
                tier2_state=diag.get("tier2", "not_attempted"),
            )
            return OrderbookSnapshot(
                market="",
                asset_id=str(token_id),
                bids=[],
                asks=[],
                timestamp=0,
                hash="",
            )

        # Tier 3: Storedata DB — paper-mode fallback only (never live).
        if self._pg_pool is not None:
            sd_book = await self._fetch_storedata_orderbook(token_id)
            if sd_book is None:
                diag["tier3"] = "miss_no_row"
            elif not (sd_book.get("asks") or sd_book.get("bids")):
                diag["tier3"] = "empty_levels"
            else:
                diag["tier3"] = "hit"
                diag["t3_n_bids"] = len(sd_book.get("bids") or [])
                diag["t3_n_asks"] = len(sd_book.get("asks") or [])
                log.info("live.book_diag", token_id=str(token_id), **diag)
                return self._dict_to_orderbook_snapshot(
                    sd_book, token_id=token_id, source="storedata"
                )

        # All tiers failed — return empty snapshot (caller treats as no liquidity).
        log.warning(
            "live.book_all_tiers_empty",
            token_id=str(token_id),
            **diag,
        )
        return OrderbookSnapshot(
            market="",
            asset_id=str(token_id),
            bids=[],
            asks=[],
            timestamp=0,
            hash="",
        )

    @staticmethod
    def _dict_to_orderbook_snapshot(
        book: dict[str, Any],
        *,
        token_id: int,
        source: str,
    ) -> OrderbookSnapshot:
        """Adapt a dict-shape book (from BookMirror / Storedata) to the
        Pydantic ``OrderbookSnapshot`` model.

        Dict shape: ``{bids: [{price, size}], asks: [{price, size}], ts: int}``.
        OrderbookSnapshot tuples: ``[(Decimal(price), Decimal(size)), ...]``.
        """

        def _to_tuples(rows: Any) -> list[tuple[Decimal, Decimal]]:
            out: list[tuple[Decimal, Decimal]] = []
            if not isinstance(rows, list):
                return out
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    px = Decimal(str(r.get("price", "0")))
                    sz = Decimal(str(r.get("size", "0")))
                except Exception:  # noqa: BLE001
                    continue
                if px <= 0 or sz <= 0:
                    continue
                out.append((px, sz))
            return out

        return OrderbookSnapshot(
            market=str(book.get("market", "")),
            asset_id=str(token_id),
            bids=_to_tuples(book.get("bids")),
            asks=_to_tuples(book.get("asks")),
            timestamp=int(book.get("ts", 0) or 0),
            hash=f"{source}:{token_id}",
        )

    async def _fetch_storedata_orderbook(self, token_id: int) -> dict | None:
        """Read freshest Storedata snapshot for token_id (live Tier-3).

        Mirrors the paper executor's ``_fetch_storedata_orderbook``: pulls
        first 10 levels per side from ``public.orderbook_snapshots_v2``.
        Returns ``None`` when no row exists (caller falls through to
        empty snapshot).
        """
        if self._pg_pool is None:
            return None
        cols_bid = ", ".join(f"bid_price_{i}, bid_size_{i}" for i in range(10))
        cols_ask = ", ".join(f"ask_price_{i}, ask_size_{i}" for i in range(10))
        sql = (
            f"SELECT timestamp_us, {cols_bid}, {cols_ask} "
            "FROM public.orderbook_snapshots_v2 "
            "WHERE exchange = 'polymarket' AND asset_id = $1 "
            "ORDER BY timestamp_us DESC LIMIT 1"
        )
        async with self._pg_pool.acquire() as conn:
            row = await conn.fetchrow(sql, str(token_id))
        if row is None:
            return None
        bids: list[dict[str, str]] = []
        asks: list[dict[str, str]] = []
        for i in range(10):
            bp = row[f"bid_price_{i}"]
            bs = row[f"bid_size_{i}"]
            ap = row[f"ask_price_{i}"]
            as_ = row[f"ask_size_{i}"]
            if bp is not None and bs is not None and bp > 0:
                bids.append({"price": str(bp), "size": str(bs)})
            if ap is not None and as_ is not None and ap > 0:
                asks.append({"price": str(ap), "size": str(as_)})
        bids.sort(key=lambda lvl: Decimal(lvl["price"]), reverse=True)
        asks.sort(key=lambda lvl: Decimal(lvl["price"]))
        ts_s = int(row["timestamp_us"]) // 1_000_000 if row["timestamp_us"] else 0
        return {"bids": bids, "asks": asks, "ts": ts_s}

    async def _legacy_clob_orderbook_fetch(self, token_id: int) -> Any:
        """Legacy direct CLOB fetch — kept for tests + opt-in compat. Not in
        the 3-tier dispatcher path."""
        raw = await asyncio.to_thread(
            self._clob.get_order_book, str(token_id)
        )
        return self._parse_orderbook(raw)

    async def get_fills(self, since: int | None = None) -> list[Fill]:
        if self.settings.mode == "paper":
            return await self._paper_dispatch("get_fills", since=since)
        raw_list = await asyncio.to_thread(self._clob.get_trades)
        out: list[Fill] = []
        for raw in raw_list or []:
            try:
                out.append(self._parse_fill(raw))
            except Exception as exc:  # noqa: BLE001
                log.warning("poly.fill.parse_skipped", err=str(exc))
        return out

    async def get_balance_allowance(
        self,
        asset_type: str,
        token_id: int | None = None,
    ) -> dict:
        """Pass-through wrapper. Used by exit pre-check + tests."""
        from py_clob_client_v2 import (  # type: ignore[import-untyped]
            AssetType,
            BalanceAllowanceParams,
        )

        at = (
            AssetType.CONDITIONAL
            if asset_type.upper() == "CONDITIONAL"
            else AssetType.COLLATERAL
        )
        params = BalanceAllowanceParams(
            asset_type=at,
            token_id=str(token_id) if token_id is not None else None,
            signature_type=self.settings.signature_type,
        )
        return await asyncio.to_thread(
            self._clob.get_balance_allowance, params
        )

    # -------- internals --------

    async def _fetch_conditional_balance(self, token_id: int) -> Decimal:
        """VEN-09 pre-check — read CONDITIONAL balance for this token_id.

        Returns Decimal in token base units (1.0 = 1 share). Rejects on
        SDK error by returning 0 (so the exit_pre_check rejects, fail-
        closed at $100k+).
        """
        try:
            raw = await self.get_balance_allowance(
                "CONDITIONAL", token_id
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "poly.balance.fetch_failed", token_id=token_id, err=str(exc)
            )
            return Decimal("0")
        bal = raw.get("balance", "0")
        try:
            return Decimal(str(bal))
        except Exception:  # noqa: BLE001
            return Decimal("0")

    async def _submit_order(
        self,
        *,
        token_id: int,
        qty: Decimal,
        limit_px: Decimal,
        side: str,
        sleeve_id: str,
        order_type: OrderType,
        intent: str,
    ) -> OrderResult:
        """Build, sign (SDK), post — wrap sync in to_thread.

        Internal invariant: (intent == "exit") iff (order_type ∈ {FAK,FOK}).
        """
        # Hard internal invariant — catches a refactor bug at the
        # only call site that bridges intent-string → order-type.
        is_exit_type = order_type in ("FAK", "FOK")
        assert (intent == "exit") == is_exit_type, (
            f"intent/order_type invariant violated: "
            f"intent={intent} order_type={order_type}"
        )

        from py_clob_client_v2 import (  # type: ignore[import-untyped]
            OrderArgsV2,
            PartialCreateOrderOptions,
        )

        # V2 SDK validates side ∈ {"BUY","SELL"} (uppercase).
        # Our public API accepts lowercase for HL parity; normalize here.
        order_args = OrderArgsV2(
            token_id=str(token_id),
            price=float(limit_px),
            size=float(qty),
            side=side.upper(),
        )
        # neg_risk + tick_size resolved per-order — never cached
        # (Pitfall 4). Caller (Phase 15 strategy) owns the lookup;
        # we accept None and let the SDK default for now.
        options = PartialCreateOrderOptions()

        try:
            unsigned = await asyncio.to_thread(
                self._clob.create_order, order_args, options
            )
            resp = await asyncio.to_thread(
                self._clob.post_order, unsigned, order_type
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            log.warning(
                "poly.submit.failed",
                sleeve_id=sleeve_id,
                token_id=token_id,
                err=msg,
            )
            return OrderResult(
                status=FillStatus.REJECTED,
                intent=intent,  # type: ignore[arg-type]
                reason=f"SDK_ERROR: {msg[:120]}",
            )

        return self._parse_submit_response(resp, intent)

    async def _paper_dispatch(self, method: str, **kwargs) -> Any:
        """Route paper-mode calls to the injected PolyPaperExecutor."""
        if self._paper is None:
            from backend.app.venues.polymarket.paper import (
                PolyPaperExecutor,
            )

            self._paper = PolyPaperExecutor(self.settings)
        fn = getattr(self._paper, method)
        return await fn(**kwargs)

    # -------- response parsers --------

    @staticmethod
    def _parse_orderbook(raw: dict) -> OrderbookSnapshot:
        def _pairs(rows):
            out = []
            for r in rows or []:
                px = Decimal(str(r.get("price", "0")))
                sz = Decimal(str(r.get("size", "0")))
                out.append((px, sz))
            return out

        ts_raw = raw.get("timestamp", "0")
        try:
            ts = int(str(ts_raw))
        except (ValueError, TypeError):
            ts = 0

        return OrderbookSnapshot(
            market=str(raw.get("market", "")),
            asset_id=str(raw.get("asset_id", "")),
            bids=_pairs(raw.get("bids")),
            asks=_pairs(raw.get("asks")),
            timestamp=ts,
            hash=str(raw.get("hash", "")),
        )

    @staticmethod
    def _parse_fill(raw: dict) -> Fill:
        return Fill(
            order_id=str(raw.get("order_id") or raw.get("orderID") or ""),
            token_id=int(raw.get("token_id") or raw.get("tokenId") or 0),
            side=raw.get("side", "buy"),
            status=raw.get("status", "matched"),
            makingAmount=Decimal(str(raw.get("makingAmount", "0"))),
            takingAmount=Decimal(str(raw.get("takingAmount", "0"))),
            fee=Decimal(str(raw.get("fee", "0"))),
            tx_hash=raw.get("tx_hash") or raw.get("txHash"),
        )

    @staticmethod
    def _parse_submit_response(resp: dict, intent: str) -> OrderResult:
        success = resp.get("success", False)
        status_raw = (resp.get("status") or "").lower()
        order_id = resp.get("orderID") or resp.get("order_id")
        error_msg = str(resp.get("errorMsg") or resp.get("error", ""))

        # VEN-09 server-side race: "not enough balance / allowance"
        # reaches us as a CLOB rejection AFTER pre-check passed.
        if intent == "exit" and (
            "not enough balance" in error_msg.lower()
            or "not enough allowance" in error_msg.lower()
        ):
            return OrderResult(
                status=FillStatus.REJECTED,
                intent="exit",
                reason="EXIT_RACE_DEPLETED",
                raw_response=resp,
            )

        if not success:
            return OrderResult(
                status=FillStatus.REJECTED,
                intent=intent,  # type: ignore[arg-type]
                reason=error_msg or "unknown rejection",
                raw_response=resp,
            )

        # Map server status to our FillStatus.
        if status_raw in ("matched", "confirmed", "mined"):
            status = FillStatus.FILLED
        elif status_raw == "partial":
            status = FillStatus.PARTIAL
        else:
            status = FillStatus.PENDING

        # 2026-05-20 — V2 CLOB response shape extraction. The v2 SDK
        # returns `makingAmount` + `takingAmount` per the matched order.
        # Direction-dependent decode:
        #   BUY  (intent=entry): we MAKE USDC, TAKE shares
        #                        → fill_qty=takingAmount, notional=makingAmount
        #   SELL (intent=exit):  we MAKE shares, TAKE USDC
        #                        → fill_qty=makingAmount, notional=takingAmount
        # fill_price = notional_usd / fill_qty
        # Pack BOTH V1 (filled, avg_price, intended) and V2 (filled_shares,
        # filled_usd) key names into raw_response so existing audit-row
        # writers (controllers/polymarket_updown.py:2270 reading
        # raw.get("filled") + raw.get("avg_price")) work unchanged, and
        # downstream parsers that match paper.py:614 shape also work.
        making_amount = resp.get("makingAmount")
        taking_amount = resp.get("takingAmount")
        raw_packed: dict[str, Any] = dict(resp)  # preserve original keys
        try:
            if making_amount is not None and taking_amount is not None:
                making_d = Decimal(str(making_amount))
                taking_d = Decimal(str(taking_amount))
                if intent == "entry":
                    fill_shares = taking_d
                    fill_notional = making_d
                else:  # exit / sell
                    fill_shares = making_d
                    fill_notional = taking_d
                if fill_shares > 0:
                    avg_price = fill_notional / fill_shares
                    raw_packed["filled"] = str(fill_shares)
                    raw_packed["avg_price"] = str(avg_price)
                    raw_packed["filled_shares"] = str(fill_shares)
                    raw_packed["filled_usd"] = str(fill_notional)
                    raw_packed["intended_usd"] = str(fill_notional)
                # tx_hash mirrors V1 audit-row key — transactionsHashes is V2.
                tx_hashes = resp.get("transactionsHashes")
                if isinstance(tx_hashes, list) and tx_hashes:
                    raw_packed["tx_hash"] = tx_hashes[0]
        except (InvalidOperation, ValueError, TypeError, ZeroDivisionError):
            # Defensive: never let a parse glitch on the response shape
            # block the order result. raw_packed retains original keys so
            # the audit row still records the submit ack.
            log.warning(
                "poly.submit.fill_extract_failed",
                intent=intent,
                making_amount=making_amount,
                taking_amount=taking_amount,
            )

        return OrderResult(
            status=status,
            intent=intent,  # type: ignore[arg-type]
            order_id=str(order_id) if order_id else None,
            raw_response=raw_packed,
        )

    # ------------------------------------------------------------------
    # Phase 17.2 SECRETS-UI-03 — ERC20 approve(spender, MAX_UINT256)
    # ------------------------------------------------------------------

    async def set_max_usdc_allowance(self) -> str:
        """Sign + submit ERC20 approve(CTF_Exchange, MAX_UINT256); return tx_hash.

        Picks up the signer private key from the SecretsRegistry passed
        at __init__ time (CONTEXT.md D-04: signing key never leaves the
        process running this client — typically tv-engine via the
        _engine_tasks_worker).

        Submits a Polygon legacy tx (chain_id=137) via httpx
        eth_sendRawTransaction. The raw tx is built and signed via
        eth_account.Account.sign_transaction — py-clob-client-v2 uses
        the same eth-account underneath, so we reuse the same key
        without instantiating the CLOB SDK (this method is
        mode-independent — works in paper and live).

        Returns the tx_hash hex string from the RPC; raises RuntimeError
        if no signer key was configured. Raw RPC errors propagate as
        httpx.HTTPError (caller maps to task status='failed').
        """
        # Entry log keyed by client_id so future operators can correlate
        # which worker instance handled a given task (root-caused 2026-05-14
        # tv-supervisor stale-client race — see commit history).
        log.info(
            "poly_set_max_allowance.entered",
            client_id=id(self),
            signer_bound=self._signer_private_key is not None,
        )

        from eth_account import Account  # type: ignore[import-untyped]

        from backend.app.api.poly_allowance import (
            APPROVE_SELECTOR,
            MAX_UINT256,
            SPENDER_ADDR,
            USDC_ADDR,
            _pad_addr,
        )

        # DIAG 2026-05-14: log key STATE only (length, truthy bool); never the value.
        # Helps diagnose registry-binding bugs without leaking plaintext.
        log.info(
            "poly_set_max_allowance.signer_state",
            signer_is_none=self._signer_private_key is None,
            signer_is_empty=self._signer_private_key == "",
            signer_len=len(self._signer_private_key) if self._signer_private_key else 0,
            proxy_is_none=self._proxy_address is None,
            proxy_len=len(self._proxy_address) if self._proxy_address else 0,
        )
        if not self._signer_private_key:
            raise RuntimeError(
                "polymarket signer private key not configured "
                "— set poly_signer_private_key in trading.secrets"
            )

        # Build approve(spender, MAX_UINT256) calldata.
        amount_hex = hex(MAX_UINT256)[2:].rjust(64, "0")  # 64 'f' chars
        data = APPROVE_SELECTOR + _pad_addr(SPENDER_ADDR) + amount_hex

        # Derive sender address from private key (signer's address; the
        # proxy/funder is a separate Polymarket-managed contract — the
        # ERC20 approve must be sent FROM the EOA that holds the USDC,
        # which is the signer's own address in this Plan 17.2 v1 flow).
        signer_account = Account.from_key(self._signer_private_key)
        sender = signer_account.address

        # Fetch nonce + gas price in a single batch (one round-trip).
        async with httpx.AsyncClient(timeout=10.0) as http:
            nonce_resp = await http.post(
                self._rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_getTransactionCount",
                    "params": [sender, "latest"],
                },
            )
            gas_resp = await http.post(
                self._rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "eth_gasPrice",
                    "params": [],
                },
            )
            # Clearer error than a bare KeyError('result') when the RPC
            # returns {"error": ...} (rate limit, auth failure, etc.).
            # Operator-facing message names the failing endpoint so they
            # can swap POLYGON_RPC_URL without spelunking logs.
            nonce_json = nonce_resp.json()
            if "result" not in nonce_json:
                raise RuntimeError(
                    f"Polygon RPC eth_getTransactionCount failed at "
                    f"{self._rpc_url}: {nonce_json.get('error', nonce_json)}. "
                    f"Set POLYGON_RPC_URL to a private endpoint "
                    f"(Alchemy/Infura/QuickNode) — the public polygon-rpc.com "
                    f"default is rate-limited."
                )
            gas_json = gas_resp.json()
            if "result" not in gas_json:
                raise RuntimeError(
                    f"Polygon RPC eth_gasPrice failed at "
                    f"{self._rpc_url}: {gas_json.get('error', gas_json)}."
                )
            nonce = int(nonce_json["result"], 16)
            gas_price = int(gas_json["result"], 16)

        tx = {
            "chainId": 137,
            "nonce": nonce,
            "gas": 100_000,
            "gasPrice": gas_price,
            "to": USDC_ADDR,
            "value": 0,
            "data": data,
        }
        signed = Account.sign_transaction(tx, self._signer_private_key)
        # eth-account 0.13+ uses raw_transaction; older releases used rawTransaction.
        raw_attr = getattr(signed, "raw_transaction", None) or signed.rawTransaction
        raw_tx = "0x" + raw_attr.hex()

        async with httpx.AsyncClient(timeout=10.0) as http:
            send_resp = await http.post(
                self._rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "eth_sendRawTransaction",
                    "params": [raw_tx],
                },
            )
            payload = send_resp.json()
        tx_hash = payload.get("result")
        if not tx_hash:
            err = payload.get("error", {})
            raise RuntimeError(
                f"eth_sendRawTransaction failed: {err.get('message', 'unknown')}"
            )
        log.info("poly.set_max_usdc_allowance.submitted", tx_hash=tx_hash)
        return tx_hash


__all__ = ["PolymarketClient", "redact_secrets_processor"]
