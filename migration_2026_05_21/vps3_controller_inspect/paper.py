"""PolyPaperExecutor — paper-mode fill simulator (Phase 14 Task 7).

Phase 18.1 in-flight (2026-04-29): orderbook source switched from
Storedata snapshots to the Polymarket CLOB ``/book`` HTTP endpoint
directly. Storedata's WS book writer was 30s+ stale on ~62% of bar
boundaries (especially 15m and SOL — books up to 1h old), causing
``qty_compute_failed`` rejection on signals that should have fired.
The CLOB ``/book`` endpoint is unauthenticated, ~50 req/s public, and
returns the live resting order state — no snapshot lag.

Read paths in priority order:
  1. CLOB ``/book`` HTTP (httpx, no auth)         — primary
  2. Storedata ``public.orderbook_snapshots_v2``  — fallback if CLOB
     errors AND a pg_pool was injected (kept so the existing test
     harness still works without rewriting every fixture)

Per memory/feedback_data_source_matrix.md the CLOB direct read is the
authoritative source for paper-fill simulation now; Storedata snapshots
remain a 7-day archive for backtest replay (out-of-band of paper mode).

This module has ZERO py_clob_client_v2 imports — the SDK is sync and
overweight for a public ``/book`` GET. We use httpx directly (matches
CLAUDE.md tech-stack-locked HTTP client).

VEN-09 assertions are still enforced in paper mode — a wrong-shaped
exit bug is the same shape regardless of routing.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from decimal import Decimal
from typing import Any

import httpx
import structlog

from backend.app.venues.polymarket.models import FillStatus, OrderResult
from backend.app.venues.polymarket.settings import PolySettings

log = structlog.get_logger("backend.app.venues.polymarket.paper")

# Stale threshold — defense-in-depth. The CLOB read path stamps ``ts``
# at fetch time so a healthy CLOB response always passes this gate; the
# gate exists to defend the Storedata fallback path (snapshots can be
# arbitrarily old) and as a guard for any future caching mistake.
#
# Phase 18.1 forensics 2026-04-28: prior 15min value let fills through
# against snapshots from already-resolved 5m markets (snapshot writer
# stops collecting ~7min after market end, so a 14-min-old snap was
# accepted as fresh). 30s is tight enough that any non-trivially-stale
# data is rejected for both 5m and 15m sleeves on the Storedata path.
STALE_AFTER_SECONDS = 30  # tightened from 15min after stale-fill bug

# httpx timeout for CLOB /book. Polymarket CLOB p95 < 500ms; 5s gives
# 10x headroom and still keeps the bar-close hot path responsive.
# Phase 18.2 V2 patch: this is now the upper-bound default; per-instance
# override via PolyPaperExecutor(rest_timeout_s=...) or env
# TV_POLY_PAPER_REST_TIMEOUT_S in engine wiring.
CLOB_HTTP_TIMEOUT_S = 5.0

# Default retry policy for CLOB GET. Per Phase 18.2 V2 PAPER_DATA_SOURCE_PATCH:
# transient 5xx/timeout deserves a quick retry before falling back/empty.
DEFAULT_REST_RETRY_ATTEMPTS = 2  # = 1 initial + 2 retries = 3 total tries
DEFAULT_REST_RETRY_BACKOFF_S = 0.1  # multiplied by (attempt+1)


class PolyPaperExecutor:
    """Paper-mode executor simulating fills off Storedata snapshots."""

    def __init__(
        self,
        settings: PolySettings,
        pg_pool: Any | None = None,
        cache_ttl_seconds: int = 1,
        cache_max_size: int = 256,
        slippage_bps: float = 2.0,
        *,
        http_client: httpx.AsyncClient | None = None,
        rest_timeout_s: float = CLOB_HTTP_TIMEOUT_S,
        rest_retry_attempts: int = DEFAULT_REST_RETRY_ATTEMPTS,
        db_fallback_enabled: bool | None = None,
        # Phase 18.6 W1 — TV-native WS BookMirror as Tier-1 hot-path source.
        # When set, _fetch_orderbook reads from the mirror first; falls back
        # to CLOB then Storedata. None preserves W0 band-aid behavior
        # (CLOB Tier-1, Storedata Tier-2).
        book_mirror: Any | None = None,
        # Phase 18.6 W1 — alert service for Storedata-Tier-3 critical alert
        # when WS+CLOB both fail and Storedata answers (operator must see
        # hot-path degradation in real time).
        alert_service: Any | None = None,
    ) -> None:
        # Phase 18.2 V2 PAPER_DATA_SOURCE_PATCH: live CLOB is the source of
        # truth for paper fills. The DB path remains as an emergency
        # fallback gated by ``db_fallback_enabled`` so a CLOB outage doesn't
        # silently revert paper to stale snapshots in production. Cache TTL
        # default dropped 5s → 1s — the live book IS the truth, no need to
        # cache beyond a single on_tick cycle.
        self.settings = settings
        self._pool = pg_pool  # asyncpg fallback; None = no fallback
        self._ttl = cache_ttl_seconds
        self._max = cache_max_size
        self._slippage_bps = slippage_bps
        self._cache: OrderedDict[int, tuple[float, dict]] = OrderedDict()

        # Phase 18.1 in-flight 2026-04-29: CLOB direct read path.
        # ``http_client`` injection lets the engine main owns the lifecycle
        # (single AsyncClient + connection pooling); tests pass None to
        # exercise the Storedata fallback without network calls. Either
        # source must be wired or _fetch_orderbook returns an empty book.
        self._http: httpx.AsyncClient | None = http_client
        self._rest_timeout_s = rest_timeout_s
        self._rest_retry_attempts = rest_retry_attempts

        # DB fallback policy:
        # - When http_client is None (test path / no CLOB wired) → fallback
        #   ALWAYS allowed; pg_pool is the only source.
        # - When http_client IS set (production wiring) → fallback default
        #   off; explicit opt-in via TV_POLY_PAPER_DB_FALLBACK=true (engine
        #   wiring) or constructor kwarg. Patch §1: stale Storedata reads
        #   silently break paper-vs-live parity, so default-off is safer.
        # Phase 18.6 W0 (2026-05-06) BAND-AID: default ON regardless of
        # http_client. CLOB HTTP is structurally lossy for thin opposite-
        # side tokens (verified: 0 hedges fired in 215 momo resolutions
        # while realfill on the same trades found 99.8% feasibility
        # against Storedata WS-captured snapshots).
        # TIME-BOXED to ≤7 days. Wave 3 reverts this default to False
        # once Wave 1 ships TV-native WS BookMirror as Tier-1.
        # Operator opt-out: TV_POLY_PAPER_DB_FALLBACK=false (engine wiring).
        # Live mode: this default-ON is FORBIDDEN per CLAUDE.md inv #13;
        # live executor must wire BookMirror Tier-1 + alert-loud Tier-3.
        if db_fallback_enabled is None:
            db_fallback_enabled = True
        self._db_fallback_enabled = db_fallback_enabled

        # Phase 18.6 W1 — Tier-1 + alert plumbing.
        self._book_mirror = book_mirror
        self._alert_service = alert_service

    # -------- public API (shape-mirrors PolymarketClient) --------

    async def place_entry_order(
        self,
        token_id: int,
        qty: Decimal | None = None,
        limit_px: Decimal = Decimal("0"),
        sleeve_id: str = "",
        side: str = "buy",
        *,
        notional_usd: Decimal | None = None,
    ) -> OrderResult:
        """Place an entry order. Two modes — pass exactly one of:

        - ``qty=Decimal(N)``      → V1 share-first path. Walks book consuming
                                    N shares (each level filled at its price).
        - ``notional_usd=Decimal(N)`` → V2 USD-first path. Walks book consuming
                                       $N USD; ``filled_shares`` = sum of
                                       (notional_per_level / price_per_level).

        Phase 18.2 V2: USD-first is the validated path for sig_ret5m + HYBRID.
        Avoids V1's bug where controller pre-computed shares from best_ask,
        missing thin top-of-book on partial fills.

        Returns OrderResult with raw_response containing BOTH V1 keys
        (``filled``, ``intended``) AND V2 keys (``filled_shares``, ``filled_usd``,
        ``intended_usd``) so existing parsers + V2 parsers both work.
        """
        if (qty is None) == (notional_usd is None):
            raise ValueError(
                "place_entry_order: exactly one of qty or notional_usd must be set "
                f"(got qty={qty}, notional_usd={notional_usd})"
            )
        if not sleeve_id:
            raise ValueError("place_entry_order: sleeve_id is required")
        return await self._simulate(
            token_id=token_id,
            qty=qty,
            notional_usd=notional_usd,
            limit_px=limit_px,
            side=side,
            sleeve_id=sleeve_id,
            intent="entry",
        )

    async def place_exit_order(
        self,
        token_id: int,
        qty: Decimal,
        limit_px: Decimal,
        sleeve_id: str,
        side: str = "sell",
    ) -> OrderResult:
        # VEN-09 STATIC ASSERT mirrors live path. This is intentional:
        # paper must catch the same shape-of-bug.
        assert side == "sell", (
            f"POLY VEN-09 VIOLATION (paper): place_exit_order called with "
            f"side={side!r}; only 'sell' is allowed."
        )
        return await self._simulate(
            token_id=token_id,
            qty=qty,
            limit_px=limit_px,
            side="sell",
            sleeve_id=sleeve_id,
            intent="exit",
        )

    async def cancel_order(self, order_id: str) -> dict:
        # Paper mode: "cancel" is always ok — no resting orders.
        return {"success": True, "canceled": [order_id]}

    async def get_orderbook_snapshot(self, token_id: int) -> dict:
        """Return the freshest orderbook snapshot, with staleness rejection.

        Phase 18.1 forensics 2026-04-28: previously this method returned
        whatever ``_fetch_orderbook`` returned without checking age. The
        hedge tick used it to read OPPOSITE-side books; for already-resolved
        markets the returned snapshot was 14+ min stale and had degenerate
        asks/bids, so the hedge logged ``hedge_skipped_no_asks`` against
        a "fresh enough to act on" book that was actually dead.

        This method now mirrors ``_simulate``'s staleness gate: snapshots
        older than ``STALE_AFTER_SECONDS`` come back as empty books so
        downstream code can detect the gap and act (skip hedge, alert,
        etc.) instead of silently consuming bad data.
        """
        book = await self._fetch_orderbook(token_id)
        ts = int(book.get("ts", 0) or 0)
        now = int(time.time())
        if ts == 0 or (now - ts) > STALE_AFTER_SECONDS:
            log.info(
                "paper.orderbook_snapshot_stale",
                token_id=str(token_id),
                book_ts=ts,
                age_s=(now - ts) if ts else None,
                source=book.get("_source"),
            )
            # Phase 18.6 W1 — preserve _source on the stale-return path
            # so downstream audit telemetry sees which tier answered (or
            # "empty" if all tiers failed). Pre-W1 this dropped _source,
            # leaving hedge_skip rows with book_source=null.
            return {
                "bids": [],
                "asks": [],
                "ts": 0,
                "_stale": True,
                "_source": book.get("_source", "empty"),
            }
        return book

    async def get_fills(self, since: int | None = None) -> list[dict]:
        return []

    # -------- orderbook read path --------

    async def _fetch_orderbook(self, token_id: int) -> dict:
        """Return the freshest orderbook for this token_id.

        Phase 18.1 in-flight 2026-04-29: CLOB direct read is now the
        primary source; Storedata fallback only triggers if CLOB errors
        and a ``pg_pool`` was injected. The 5s LRU cache wraps both —
        a single bar boundary fires at most one HTTP GET per token.

        Returns ``{bids: [{price,size}], asks: [{price,size}], ts: int}``
        — the same shape downstream simulator + controller expect.
        Empty book (``ts=0``) when neither source produced data.
        """
        now = time.time()

        # Cache hit + fresh → return.
        if token_id in self._cache:
            ts, cached = self._cache[token_id]
            if now - ts < self._ttl:
                self._cache.move_to_end(token_id)
                return cached
            del self._cache[token_id]

        # Phase 18.6 W1 — 3-tier dispatcher.
        #   Tier 1: TV-native WS BookMirror (<10ms staleness, in-memory)
        #   Tier 2: CLOB HTTP /book (~50ms RTT)
        #   Tier 3: Storedata public.orderbook_snapshots_v2 (disaster
        #           fallback, emits CRITICAL alert when it answers)
        # When self._book_mirror is None, Tier-1 is skipped (W0 band-aid
        # mode: CLOB Tier-1, Storedata Tier-2). When it IS set, Wave-1
        # 3-tier ordering applies.
        book: dict | None = None
        source: str = "empty"

        # Tier 1: WS BookMirror.
        if self._book_mirror is not None:
            ws_book = self._book_mirror.get(str(token_id))
            if ws_book is not None and (ws_book.get("asks") or ws_book.get("bids")):
                book = dict(ws_book)
                source = "ws_mirror"

        # Tier 2: CLOB HTTP.
        clob_attempted = book is None and self._http is not None
        if clob_attempted:
            clob_book = await self._fetch_clob_orderbook(token_id)
            if clob_book is not None:
                book = clob_book
                source = "clob"

        # Tier 3: Storedata DB. Alert-loud when this tier answers.
        sd_attempted = book is None and self._pool is not None
        if sd_attempted and (not (self._http is not None) or self._db_fallback_enabled):
            sd_book = await self._fetch_storedata_orderbook(token_id)
            if sd_book is not None:
                book = sd_book
                source = "storedata"
                # Phase 18.6 W1 D-04: when Storedata Tier-3 answers it
                # means BOTH WS and CLOB failed for this token. That's
                # hot-path degradation — emit critical alert. (Skipped
                # in W0 mode where mirror is None and CLOB is the
                # nominal Tier-1; the alert would be too noisy.)
                if self._book_mirror is not None and self._alert_service is not None:
                    try:
                        await self._alert_service.emit(
                            severity="critical",
                            kind="poly_book_tier3_disaster_fallback",
                            summary=(
                                f"Polymarket book Tier-3 (Storedata) answered "
                                f"for token {token_id}; WS BookMirror + CLOB "
                                f"both failed. Hot-path degraded."
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        pass

        if book is None:
            book = {"bids": [], "asks": [], "ts": 0}
            source = "empty"
        book["_source"] = source

        book_ts = int(book.get("ts", 0) or 0)
        log.info(
            "paper.book_fetched",
            token_id=str(token_id),
            source=source,
            age_s=int(now - book_ts) if book_ts else None,
            has_asks=bool(book.get("asks")),
            has_bids=bool(book.get("bids")),
        )

        # LRU insert + eviction.
        self._cache[token_id] = (now, book)
        self._cache.move_to_end(token_id)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return book

    async def _fetch_clob_orderbook(self, token_id: int) -> dict | None:
        """GET ``{clob_host}/book?token_id=...`` — public, no auth.

        Phase 18.2 V2 PAPER_DATA_SOURCE_PATCH: retries up to
        ``self._rest_retry_attempts`` times on transient HTTP/timeout
        errors with linear backoff (0.1s × (attempt+1)). Empty book
        responses (``{"error": ...}`` or no bids/asks) are NOT retried —
        the upstream signal is "this token has no liquidity right now".

        Response shape (verified 2026-04-29 against live clob.polymarket.com):
            {market, asset_id, timestamp, hash, bids[], asks[],
             min_order_size, tick_size}

        Each level is ``{price: str, size: str}``. Bids are sorted
        descending by price (best first), asks ascending (best first) —
        but we sort defensively because the contract is unstable across
        CLOB endpoint versions.

        ``ts`` on the returned dict is set to NOW (fetch time), NOT the
        CLOB-reported ``timestamp``. The 30s STALE_AFTER_SECONDS gate is
        a Storedata-specific defense; for CLOB the data is live by virtue
        of having just been fetched, regardless of how long ago a maker
        last updated the book (a quiet market still has resting orders
        that we can trade against).

        Returns None on any HTTP/JSON error after all retries exhausted —
        the caller falls back per ``_db_fallback_enabled`` policy.
        """
        if self._http is None:
            return None

        raw: Any = None
        last_exc: Exception | None = None
        # 1 initial attempt + N retries = N+1 total tries.
        for attempt in range(self._rest_retry_attempts + 1):
            try:
                resp = await self._http.get(
                    "/book",
                    params={"token_id": str(token_id)},
                    timeout=self._rest_timeout_s,
                )
                resp.raise_for_status()
                raw = resp.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_exc = exc
                if attempt < self._rest_retry_attempts:
                    # Transient — back off + retry.
                    await asyncio.sleep(
                        DEFAULT_REST_RETRY_BACKOFF_S * (attempt + 1)
                    )
                    continue
                # All retries exhausted.
                log.warning(
                    "paper.clob_orderbook_fetch_failed",
                    token_id=str(token_id),
                    attempts=attempt + 1,
                    err=str(exc),
                )
                return None

        if raw is None:
            # Defensive — should be unreachable given the loop break.
            log.warning(
                "paper.clob_book_fetch_no_response",
                token_id=str(token_id),
                last_err=str(last_exc) if last_exc else None,
            )
            return None

        # CLOB returns {"error": "..."} for unknown tokens; treat as empty.
        # Phase 18.6 W0 — diagnostic enrichment on the empty/error paths.
        # Wave 1 will route around this via WS BookMirror Tier-1; until
        # then these logs feed the Wave 1 design.
        if not isinstance(raw, dict) or "error" in raw:
            log.info(
                "paper.clob_book_unknown_token",
                token_id=str(token_id),
                err=str(raw.get("error")) if isinstance(raw, dict) else None,
                raw_keys=list(raw.keys()) if isinstance(raw, dict) else None,
                raw_preview=str(raw)[:200],
            )
            return None

        bids = _parse_levels(raw.get("bids"))
        asks = _parse_levels(raw.get("asks"))
        # Phase 18.6 W0 — log the 200-OK-empty case (CLOB returns valid
        # JSON with empty bids/asks arrays, no error key). Wave 1 design
        # input: distinguishes "thin token, real empty" from "CLOB serving
        # stale cached empty for token that has WS-visible liquidity".
        if not bids and not asks:
            log.info(
                "paper.clob_book_empty_response",
                token_id=str(token_id),
                market=raw.get("market"),
                asset_id=raw.get("asset_id"),
                timestamp=raw.get("timestamp"),
                full_response=str(raw)[:500],
            )
        # Defensive sort — best-first regardless of CLOB-side ordering.
        bids.sort(key=lambda lvl: Decimal(lvl["price"]), reverse=True)
        asks.sort(key=lambda lvl: Decimal(lvl["price"]))
        return {"bids": bids, "asks": asks, "ts": int(time.time())}

    async def _fetch_storedata_orderbook(self, token_id: int) -> dict | None:
        """Read the freshest Storedata snapshot for this token_id.

        Fallback path — used only when CLOB direct read errors. Schema
        reality (verified 2026-04-28 vs live VPS2 storedata DB): the
        table has flat per-level columns ``bid_price_0..24`` /
        ``bid_size_0..24`` / ``ask_price_0..24`` / ``ask_size_0..24``,
        NOT jsonb ``bids``/``asks``. The CLOB token_id is in the
        ``asset_id`` text column. Time is microseconds in
        ``timestamp_us``. We pull the first 10 levels — sufficient for
        $25-and-below paper walking; deeper levels matter only at
        production sizing.

        Returns None when no row exists (caller treats as empty book).
        """
        if self._pool is None:
            return None

        cols_bid = ", ".join(
            f"bid_price_{i}, bid_size_{i}" for i in range(10)
        )
        cols_ask = ", ".join(
            f"ask_price_{i}, ask_size_{i}" for i in range(10)
        )
        sql = (
            f"SELECT timestamp_us, {cols_bid}, {cols_ask} "
            "FROM public.orderbook_snapshots_v2 "
            "WHERE exchange = 'polymarket' AND asset_id = $1 "
            "ORDER BY timestamp_us DESC LIMIT 1"
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, str(token_id))

        if row is None:
            return None

        bids: list[dict] = []
        asks: list[dict] = []
        for i in range(10):
            bp = row[f"bid_price_{i}"]
            bs = row[f"bid_size_{i}"]
            if bp is not None and bs is not None and bp > 0:
                bids.append({"price": str(bp), "size": str(bs)})
            ap = row[f"ask_price_{i}"]
            asz = row[f"ask_size_{i}"]
            if ap is not None and asz is not None and ap > 0:
                asks.append({"price": str(ap), "size": str(asz)})

        ts_s = int(row["timestamp_us"]) // 1_000_000
        return {"bids": bids, "asks": asks, "ts": ts_s}

    # -------- fill simulation --------

    async def _simulate(
        self,
        *,
        token_id: int,
        qty: Decimal | None = None,
        notional_usd: Decimal | None = None,
        limit_px: Decimal,
        side: str,
        sleeve_id: str,
        intent: str,
    ) -> OrderResult:
        """Walk the book and produce an OrderResult.

        Two modes:
          - share-first (qty set): consume ``qty`` shares level-by-level.
          - USD-first (notional_usd set): consume ``notional_usd`` USD level-
            by-level; on the level that exhausts the budget, take a partial
            slice ``shares = remaining_usd / px``.

        Exactly one of ``qty`` or ``notional_usd`` is required (the public
        ``place_entry_order`` enforces this; ``place_exit_order`` always
        passes ``qty`` because exits are share-denominated).

        ``raw_response`` always carries BOTH V1 keys (``filled``, ``intended``)
        AND V2 keys (``filled_shares``, ``filled_usd``, ``intended_usd``) so
        existing parsers and V2 parsers both work.
        """
        book = await self._fetch_orderbook(token_id)
        book_ts = int(book.get("ts", 0))
        now = int(time.time())
        if book_ts == 0 or (now - book_ts) > STALE_AFTER_SECONDS:
            return OrderResult(
                status=FillStatus.REJECTED,
                intent=intent,  # type: ignore[arg-type]
                reason="STALE_ORDERBOOK",
                raw_response={"book_ts": book_ts, "now": now},
            )

        # Depth consumption — walk the far side.
        # Phase 18.1 paper resolver dependency: track weighted avg fill price
        # so audit downstream can compute realized P&L at resolution. Without
        # this, fill_price arrives at trading.events as NULL and the resolver
        # falls back to limit_px (worst-case 0.99) which under-reports profit.
        levels = book["asks"] if side == "buy" else book["bids"]
        filled = Decimal("0")     # shares consumed
        notional = Decimal("0")   # USD consumed (sum of px * shares per level)

        if notional_usd is not None:
            # ----- V2 USD-first walk -----
            remaining_usd = notional_usd
            for level in levels:
                px = Decimal(str(level.get("price", "0")))
                sz = Decimal(str(level.get("size", "0")))
                if side == "buy" and px > limit_px:
                    break
                if side == "sell" and px < limit_px:
                    break
                if px <= 0 or sz <= 0:
                    continue
                level_notional = px * sz
                if level_notional >= remaining_usd:
                    # Final partial slice — take only enough shares to spend remaining_usd.
                    shares_here = remaining_usd / px
                    filled += shares_here
                    notional += remaining_usd
                    remaining_usd = Decimal("0")
                    break
                filled += sz
                notional += level_notional
                remaining_usd -= level_notional
            # Partial when budget not fully consumed (within a $0.01 fudge).
            is_partial = remaining_usd > Decimal("0.01")
            intended_value: Decimal = notional_usd
        else:
            # ----- V1 share-first walk (unchanged behavior) -----
            assert qty is not None  # public API enforces one-of
            remaining = qty
            for level in levels:
                px = Decimal(str(level.get("price", "0")))
                sz = Decimal(str(level.get("size", "0")))
                if side == "buy" and px > limit_px:
                    break
                if side == "sell" and px < limit_px:
                    break
                take = min(remaining, sz)
                filled += take
                notional += take * px
                remaining -= take
                if remaining <= 0:
                    break
            is_partial = filled < qty
            intended_value = qty

        if filled == 0:
            return OrderResult(
                status=FillStatus.REJECTED,
                intent=intent,  # type: ignore[arg-type]
                reason="NO_LIQUIDITY_AT_LIMIT",
                raw_response={"book_ts": book_ts},
            )

        avg_price = (notional / filled) if filled > 0 else Decimal("0")

        # Both V1 (`filled`, `intended`) and V2 (`filled_shares`, `filled_usd`,
        # `intended_usd`) keys present so all downstream parsers work.
        raw = {
            "filled": str(filled),
            "intended": str(intended_value),
            "avg_price": str(avg_price),
            "filled_shares": str(filled),
            "filled_usd": str(notional),
            "intended_usd": str(notional_usd) if notional_usd is not None else None,
        }

        if is_partial:
            # CLAUDE.md inv #2: partial fills are `partial`, not filled.
            return OrderResult(
                status=FillStatus.PARTIAL,
                intent=intent,  # type: ignore[arg-type]
                order_id=f"paper-{sleeve_id}-{now}",
                raw_response=raw,
            )

        return OrderResult(
            status=FillStatus.FILLED,
            intent=intent,  # type: ignore[arg-type]
            order_id=f"paper-{sleeve_id}-{now}",
            raw_response=raw,
        )


def _parse_levels(rows: Any) -> list[dict]:
    """Coerce CLOB-shape level dicts into ``{price: str, size: str}``.

    CLOB returns ``[{price: "0.99", size: "2293"}, ...]``; defensively
    drops any row where price or size is missing/non-positive.
    """
    out: list[dict] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            px = Decimal(str(r.get("price", "0")))
            sz = Decimal(str(r.get("size", "0")))
        except Exception:  # noqa: BLE001
            continue
        if px <= 0 or sz <= 0:
            continue
        out.append({"price": str(px), "size": str(sz)})
    return out


__all__ = ["PolyPaperExecutor", "STALE_AFTER_SECONDS", "CLOB_HTTP_TIMEOUT_S"]
