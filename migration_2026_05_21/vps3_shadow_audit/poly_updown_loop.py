"""Polymarket Updown scheduler — wires PolymarketUpdownController into tv-engine.

Phase 18.1 follow-up: Phase 15 shipped the controller class but never wired
it into ``backend/app/engine/main.py``'s TaskGroup, so the strategy code was
inert on VPS deploy. This module closes that gap.

The scheduler does two things on each ``tick_seconds`` (default 10s) cycle:

1. **on_tick()** — drives the hedge-hold reversal check across all open
   slots (RESEARCH §2 + Wave 18.1-02 Task 3).
2. **on_bar_close(symbol, tf, bars=[])** — fires once per (symbol, tf) at
   each 5MIN/15MIN UTC-aligned boundary. Empty ``bars`` is fine: the
   controller falls back to ``datetime.now(UTC)`` for the signal timestamp,
   and the strategy only consumes ``aux["ret_5m"]`` (pre-fetched from
   public.binance_klines_v2 inside the controller — independent of the
   ``bars`` list).

Idempotency: each boundary fires at most once per (symbol, tf) per
``last_*_fired_unix`` epoch via the floor-division key — restart-safe in
the sense that a process restart that lands within the same boundary
window won't double-fire (the same controller instance also keys its
``_slots`` map by ``(symbol, tf, window_start_unix)`` per RESEARCH §7).

Phase 24 (2026-05-05): added ``poly_updown_master_scheduler`` — a single
scheduler that builds a shared ``BarContext`` per (symbol, tf, ws_s)
ONCE and dispatches all registered strategy_mode controllers against
the same kline closes + threshold samples + CLOB orderbook snapshot.
Eliminates the multi-controller race documented in
``.planning/V4-SUBSET-BUG-VERDICT-2026-05-05.md`` (V4 ⊆ V3 violations
on ETH/SOL caused by independent staggered orderbook fetches).

The legacy ``poly_updown_scheduler`` stays as the rollback path — gated
via ``TV_POLY_USE_MASTER_SCHEDULER`` env in ``engine/main.py``.
"""
from __future__ import annotations

import asyncio
import contextlib
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from backend.app.controllers.polymarket_updown import (
        PolymarketUpdownController,
    )

logger = structlog.get_logger("backend.app.engine.poly_updown_loop")

SUPPORTED_SYMBOLS = ("BTC", "ETH", "SOL")
TF_5M_SECONDS = 300
TF_15M_SECONDS = 900


# ---------------------------------------------------------------------------
# Phase 24 — BarContext + master scheduler
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarContext:
    """Shared per-(symbol, tf, ws_s) snapshot consumed by all controllers.

    Built ONCE per bar boundary by ``build_bar_context`` and passed via
    ``on_bar_close(..., bar_ctx=ctx)`` to each registered strategy_mode
    controller. Eliminates the race where N controllers each fetched
    their own kline closes + threshold samples + CLOB orderbook
    snapshot in a 1-10s staggered window.

    All fields are populated by the primary controller's pool/executor;
    siblings read but never write.

    Field None semantics: a None value means the corresponding fetch
    failed or the data wasn't applicable (e.g. ``token_id_no=None``
    when condition_id resolution failed). Controllers must handle None
    the same way they handle their own failed fetches in legacy mode.

    Phase 18.5 (momo): ``phase`` discriminates the dispatch event.
    - ``"bar_close"`` (default) — original Phase 24 dispatch at the 5m/15m
      UTC-aligned boundary. ``btc_at_t_plus_120`` / ``ret_2m`` /
      ``abs_ret_2m_threshold`` stay None (momo strategies see
      ``bar_ctx_phase != "t_plus_120"`` and return NONE).
    - ``"t_plus_120"`` — built by ``build_bar_context_t_plus_120`` at
      ``ws_s + 120s`` of an active market. CLOB books are FRESHLY fetched
      (the bar-close books from 120s earlier are stale). ``btc_now``
      remains BTC@ws_s (the market's open boundary), and the new field
      ``btc_at_t_plus_120`` carries BTC@(ws_s+120). Sniper threshold
      samples are ``abs_ret_2m_samples`` instead of ``abs_ret_5m_samples``.
    - ``"t_plus_60"`` (Phase 18.5+ momo_v2) — built by
      ``build_bar_context_t_plus_60`` at ``ws_s + 60s`` of an active
      market. ret_2m is anchored on (ws-60, ws+60) instead of (ws, ws+120):
      ``btc_close_at_ws_minus_60`` carries BTC@(ws_s-60) and
      ``btc_at_t_plus_60`` carries BTC@(ws_s+60). Threshold samples
      pulled on-demand from the TV-native feed's rolling deque
      (Phase 22.1; CLAUDE.md inv #13). Coexists with v1 momo (both run
      side-by-side; spec §0).
    """

    symbol: str
    tf: str
    ws_s: int
    window_start_us: int

    # Kline closes (signal-asset 1MIN bars from Binance/OKX feed)
    btc_now: Decimal | None
    btc_prior: Decimal | None        # ws_s - 300 (5m return base)
    btc_15m_prior: Decimal | None    # ws_s - 900 (V3 multi-horizon + V3.1 regime)
    btc_1h_prior: Decimal | None     # ws_s - 3600 (V3 multi-horizon + V3.1 regime)

    # 14-day rolling sample for sniper-mode threshold compute
    abs_ret_5m_samples: tuple[float, ...]

    # Polymarket condition + token resolution
    condition_id: str | None
    token_id_yes: int | None         # YES side (UP signal)
    token_id_no: int | None          # NO side (DOWN signal)

    # CLOB /book snapshots — fetched ONCE per direction, shared across all modes
    book_snapshot_yes: dict[str, Any] | None
    book_snapshot_no: dict[str, Any] | None

    # Pre-computed spread per direction (None when book is missing/malformed)
    spread_pct_yes: float | None
    spread_pct_no: float | None

    # Phase 18.5 — Momo (t+120s) extension. All four fields are None on
    # bar-close BarContexts; populated by build_bar_context_t_plus_120.
    # phase=="t_plus_120" is the controller-side gate for momo dispatch.
    phase: str = "bar_close"
    btc_at_t_plus_120: Decimal | None = None  # BTC at (ws_s + 120s)
    abs_ret_2m_samples: tuple[float, ...] = ()
    # Optional pre-computed |ret_2m| q90 threshold. The controller can
    # compute on-the-fly from abs_ret_2m_samples instead; this field
    # exists for parity with the threshold cache in non-momo modes.
    abs_ret_2m_threshold: float | None = None

    # Phase 18.5+ — momo_v2 (t+60s) extension. Anchored on (ws-60, ws+60)
    # instead of v1's (ws, ws+120). Both fields are None on bar-close and
    # t_plus_120 BarContexts; populated by build_bar_context_t_plus_60.
    # phase=="t_plus_60" is the controller-side gate for momo_v2 dispatch.
    btc_close_at_ws_minus_60: Decimal | None = None  # BTC at (ws_s - 60s)
    btc_at_t_plus_60: Decimal | None = None          # BTC at (ws_s + 60s)

    # 2026-05-20 F7 RSI filter (see TV_AGENT_F7_RSI_FILTER_SPEC.md):
    # Wilder RSI(14) on 1MIN binance closes ending at-or-before ws_s.
    # Populated by t_plus_120 + t_plus_60 builders (the only phases where
    # momo/momo_v2 fires). NaN means warmup or fetch gap; F7 gate skips
    # the fire in that case.
    rsi_14_for_signal: float | None = None

    # Phase 34 — shadow gated sleeve aux. Populated by the t_plus_60 +
    # t_plus_120 builders (only when at least one shadow sleeve in this
    # cell carries an mtf2 or m5va gate). NaN/None means "fetch failed"
    # — gates treat NaN as a skip per spec §2.2/§2.3.
    # ret_15m_for_mtf  = log(close@ws_s / close@(ws_s - 900s))
    # ret_1h_for_mtf   = log(close@ws_s / close@(ws_s - 3600s))
    # markov_regime    = -1 (warmup) / 0 (Bear) / 1 (Sideways) / 2 (Bull)
    ret_15m_for_mtf: float | None = None
    ret_1h_for_mtf: float | None = None
    markov_regime_w20_5m_va: int | None = None

    # Provenance — controllers report (now - fetched_at) as bar_ctx_age_ms
    # in their order_placed audit rows for latency monitoring (target <50ms p95).
    fetched_at: float = field(default_factory=time.monotonic)


# Phase 22.1: the three module-level _SAMPLES_CACHE / _RET_2M_SAMPLES_CACHE /
# _RET_2M_V2_SAMPLES_CACHE dicts have been DELETED. Per CLAUDE.md inv #13,
# the canonical sample source is the TV-native rolling deque inside
# BinanceMarketDataFeed. The controller's _fetch_abs_ret_*_history methods
# now read from feed.get_ret_5m_samples / get_ret_2m_samples directly, which
# walk the in-memory deque on every call (<1ms). q90 threshold is computed
# on-demand by callers via numpy quantile. No aggregate caching anywhere.
#
# Eliminates the 380s/day cold-start blackout that the daily-keyed caches
# created at every UTC midnight rollover. Verified empirically 00:00:50 ->
# 00:06:01 silence on 2026-05-07.


async def build_bar_context(
    primary: PolymarketUpdownController,
    symbol: str,
    tf: str,
    ws_s: int,
) -> BarContext:
    """Compute the shared BarContext for one (symbol, tf, ws_s) boundary.

    Uses ``primary.pool`` + ``primary.executor`` for all DB + CLOB fetches.
    Fetches run in parallel via ``asyncio.gather`` to minimize wall time
    (~max single-op latency, dominated by CLOB /book ~200-500ms).

    Designed to NEVER raise — any individual fetch failure populates the
    corresponding field with None and lets each controller decide how
    to handle missing data (matching legacy per-controller behavior).
    """
    # Defer imports to avoid the cycle: poly_updown_loop -> controllers -> engine
    from backend.app.controllers.polymarket_updown import (
        BINANCE_SYMBOL_ID_MAP,
        KLINE_SOURCE,
        SNIPER_LOOKBACK_DAYS,
        _spread_pct,
    )
    from backend.app.data.bars import fetch_close_asof
    from backend.app.strategies.polymarket.market_mapping import resolve_condition_id

    sym_upper = symbol.upper()
    symbol_id = BINANCE_SYMBOL_ID_MAP.get(sym_upper)
    window_start_us = int(ws_s) * 1_000_000

    # Signal timestamp for cid resolution — uses ws_s as canonical bar close
    from datetime import UTC, datetime
    signal_ts = datetime.fromtimestamp(ws_s, tz=UTC)

    # --- 1. Parallel kline + sample fetches ---
    async def _fetch_close(ts_offset: int) -> Decimal | None:
        if symbol_id is None:
            return None
        try:
            return await fetch_close_asof(
                symbol_id, "1MIN", ws_s + ts_offset,
                pool=primary.pool, source=KLINE_SOURCE,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context.kline_fetch_failed",
                             symbol=symbol, tf=tf, ts_offset=ts_offset)
            return None

    async def _fetch_samples() -> tuple[float, ...]:
        if symbol_id is None:
            return ()
        # Phase 22.1: no caching here. _fetch_abs_ret_5m_history is feed-
        # backed (CLAUDE.md inv #13), reads from in-memory rolling deque
        # via numpy walk in <1ms. The dropped daily cache eliminated the
        # 380s/day UTC-rollover blackout.
        try:
            from_s = ws_s - SNIPER_LOOKBACK_DAYS * 86_400
            samples_list = await primary._fetch_abs_ret_5m_history(
                symbol_id=symbol_id, tf=tf, from_s=from_s, until_s=ws_s,
            )
            return tuple(samples_list)
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context.samples_fetch_failed",
                             symbol=symbol, tf=tf)
            return ()

    async def _resolve_cid() -> str | None:
        try:
            return await resolve_condition_id(
                primary.pool, symbol=symbol, tf=tf,  # type: ignore[arg-type]
                signal_ts=signal_ts,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context.cid_resolve_failed",
                             symbol=symbol, tf=tf)
            return None

    _t_phase1 = time.monotonic()
    _task_timings: dict[str, float] = {}

    async def _timed(name: str, coro: Any) -> Any:
        t0 = time.monotonic()
        try:
            return await coro
        finally:
            _task_timings[name] = (time.monotonic() - t0) * 1000

    btc_now, btc_prior, btc_15m_prior, btc_1h_prior, samples, cid = await asyncio.gather(
        _timed("kline_now", _fetch_close(0)),
        _timed("kline_5m", _fetch_close(-300)),
        _timed("kline_15m", _fetch_close(-900)),
        _timed("kline_1h", _fetch_close(-3600)),
        _timed("samples", _fetch_samples()),
        _timed("cid", _resolve_cid()),
    )
    _t_phase2 = time.monotonic()
    logger.info(
        "bar_context.phase1_breakdown",
        symbol=symbol, tf=tf, ws_s=ws_s,
        kline_now_ms=int(_task_timings.get("kline_now", 0)),
        kline_5m_ms=int(_task_timings.get("kline_5m", 0)),
        kline_15m_ms=int(_task_timings.get("kline_15m", 0)),
        kline_1h_ms=int(_task_timings.get("kline_1h", 0)),
        samples_ms=int(_task_timings.get("samples", 0)),
        cid_ms=int(_task_timings.get("cid", 0)),
    )

    # --- 2. Token-id resolution (parallel — both UP and DOWN at once) ---
    token_id_yes: int | None = None
    token_id_no: int | None = None
    if cid is not None:
        async def _safe_token(direction: str) -> int | None:
            try:
                return await primary._resolve_token_id(cid, direction)
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    f"bar_context.token_id_{direction.lower()}_failed",
                    symbol=symbol, tf=tf, cid=cid,
                )
                return None
        token_id_yes, token_id_no = await asyncio.gather(
            _safe_token("UP"), _safe_token("DOWN"),
        )
    _t_phase3 = time.monotonic()

    # --- 3. Parallel CLOB /book fetches (one per direction) ---
    async def _fetch_book(token_id: int | None) -> dict[str, Any] | None:
        if token_id is None:
            return None
        try:
            return await primary.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context.book_fetch_failed",
                             symbol=symbol, tf=tf, token_id=token_id)
            return None

    book_yes, book_no = await asyncio.gather(
        _fetch_book(token_id_yes),
        _fetch_book(token_id_no),
    )
    _t_phase4 = time.monotonic()

    # --- 4. Pre-compute spreads (cheap CPU op; saves N controllers from re-doing) ---
    spread_yes = _spread_pct(book_yes) if book_yes else None
    spread_no = _spread_pct(book_no) if book_no else None

    # Per-symbol timing breakdown for performance debugging.
    logger.info(
        "bar_context.timings",
        symbol=symbol, tf=tf, ws_s=ws_s,
        phase1_ms=int((_t_phase2 - _t_phase1) * 1000),
        phase2_ms=int((_t_phase3 - _t_phase2) * 1000),
        phase3_ms=int((_t_phase4 - _t_phase3) * 1000),
        cid_resolved=cid is not None,
        n_samples=len(samples),
    )

    return BarContext(
        symbol=sym_upper,
        tf=tf,
        ws_s=ws_s,
        window_start_us=window_start_us,
        btc_now=btc_now,
        btc_prior=btc_prior,
        btc_15m_prior=btc_15m_prior,
        btc_1h_prior=btc_1h_prior,
        abs_ret_5m_samples=samples,
        condition_id=cid,
        token_id_yes=token_id_yes,
        token_id_no=token_id_no,
        book_snapshot_yes=book_yes,
        book_snapshot_no=book_no,
        spread_pct_yes=spread_yes,
        spread_pct_no=spread_no,
    )


# ---------------------------------------------------------------------------
# Phase 18.5 — t+120s BarContext (momo dispatch)
# ---------------------------------------------------------------------------


async def build_bar_context_t_plus_120(
    primary: PolymarketUpdownController,
    symbol: str,
    tf: str,
    ws_s: int,
) -> BarContext:
    """Build a momo-phase BarContext at ``ws_s + 120s`` of an active market.

    Different from ``build_bar_context`` (which fires at the bar-close
    boundary) in three ways:

    1. ``btc_at_t_plus_120`` is fetched fresh — needed to compute
       ``ret_2m = log(close@(ws_s+120) / close@ws_s)``.
    2. ``book_snapshot_yes/no`` are FRESHLY re-fetched. The bar-close
       books from 120s earlier are stale.
    3. ``abs_ret_2m_samples`` carries the |ret_2m| 14d rolling history;
       ``abs_ret_2m_threshold`` is the q90 of those samples (precomputed
       so all 3 momo controllers read the same value).

    Reuses ``primary``'s pool + executor + token-resolver helpers (same
    pattern as the bar-close builder). cid + token_ids are the same as
    they were at ws_s (the market opened at ws_s and is still active),
    so we still call ``resolve_condition_id(signal_ts=ws_s)``.

    Designed to NEVER raise — fetch failures yield None values; the
    momo strategy returns NONE on missing data.
    """
    from datetime import UTC, datetime

    from backend.app.controllers.polymarket_updown import (
        BINANCE_SYMBOL_ID_MAP,
        KLINE_SOURCE,
        SNIPER_LOOKBACK_DAYS,
        _spread_pct,
    )
    from backend.app.data.bars import fetch_close_asof
    from backend.app.strategies.polymarket.market_mapping import resolve_condition_id

    sym_upper = symbol.upper()
    symbol_id = BINANCE_SYMBOL_ID_MAP.get(sym_upper)
    window_start_us = int(ws_s) * 1_000_000
    signal_ts = datetime.fromtimestamp(ws_s, tz=UTC)
    t0 = time.monotonic()

    # --- 1. Parallel kline + ret_2m samples + cid resolution ---
    async def _fetch_close(ts_offset: int) -> Decimal | None:
        if symbol_id is None:
            return None
        try:
            return await fetch_close_asof(
                symbol_id, "1MIN", ws_s + ts_offset,
                pool=primary.pool, source=KLINE_SOURCE,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t120.kline_fetch_failed",
                             symbol=symbol, tf=tf, ts_offset=ts_offset)
            return None

    async def _fetch_ret_2m_samples() -> tuple[float, ...]:
        if symbol_id is None:
            return ()
        # Phase 22.1: no caching. Feed-backed _fetch_abs_ret_2m_history
        # walks rolling deque via numpy quantile in <1ms.
        try:
            from_s = ws_s - SNIPER_LOOKBACK_DAYS * 86_400
            samples_list = await primary._fetch_abs_ret_2m_history(
                symbol_id=symbol_id, tf=tf, from_s=from_s, until_s=ws_s,
            )
            return tuple(samples_list)
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t120.samples_fetch_failed",
                             symbol=symbol, tf=tf)
            return ()

    async def _resolve_cid() -> str | None:
        try:
            return await resolve_condition_id(
                primary.pool, symbol=symbol, tf=tf,  # type: ignore[arg-type]
                signal_ts=signal_ts,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t120.cid_resolve_failed",
                             symbol=symbol, tf=tf)
            return None

    # F7 RSI: fetch 15 closes (offsets 0..-840s) ending at ws_s.
    # Per TV_AGENT_F7_RSI_FILTER_SPEC §2. Failed closes leave NaN slots →
    # compute_rsi_14 returns NaN → F7 gate skips the fire.
    async def _fetch_rsi_14() -> float:
        from backend.app.indicators.rsi import compute_rsi_14
        offsets = [-60 * i for i in range(14, -1, -1)]  # -840..0 chronological
        closes = await asyncio.gather(*[_fetch_close(o) for o in offsets])
        floats = [float(c) if c is not None else float("nan") for c in closes]
        return compute_rsi_14(floats)

    # Phase 34 — MTF2 gate companion fetches. Anchored at ws_s (same as
    # signal time) — ret_15m / ret_1h log returns over 900s / 3600s
    # lookbacks. Cheap (2 extra binance-ws close lookups, in-memory deque
    # walk). Populated unconditionally so shadow controllers can read
    # them on every t+120 boundary regardless of which sub-gate stack they
    # use; baseline controllers (gate_stack=()) just ignore the fields.
    btc_at_ws, btc_at_120, btc_at_minus_900, btc_at_minus_3600, ret_2m_samples, cid, rsi_14 = await asyncio.gather(
        _fetch_close(0),       # btc_now = BTC@ws_s (unchanged)
        _fetch_close(120),     # btc_at_t_plus_120 = BTC@(ws_s + 120)
        _fetch_close(-900),    # MTF2: 15m lookback
        _fetch_close(-3600),   # MTF2: 1h lookback
        _fetch_ret_2m_samples(),
        _resolve_cid(),
        _fetch_rsi_14(),
    )

    # Compute MTF returns inline. NaN propagation: when either close is
    # missing/zero, the corresponding ret is NaN and the mtf2 gate fails
    # closed (per spec §2.2).
    _ret_15m_mtf: float | None = None
    _ret_1h_mtf: float | None = None
    if btc_at_ws is not None and btc_at_minus_900 is not None and float(btc_at_minus_900) > 0:
        _ret_15m_mtf = math.log(float(btc_at_ws) / float(btc_at_minus_900))
    if btc_at_ws is not None and btc_at_minus_3600 is not None and float(btc_at_minus_3600) > 0:
        _ret_1h_mtf = math.log(float(btc_at_ws) / float(btc_at_minus_3600))

    # --- 2. Compute q90 threshold inline (cheap; saves controller from re-doing) ---
    abs_ret_2m_threshold: float | None = None
    if len(ret_2m_samples) >= 50:  # SNIPER_MIN_SAMPLES
        # numpy import is local to keep top-level imports clean.
        import numpy as _np
        abs_ret_2m_threshold = float(_np.quantile(ret_2m_samples, 0.90))

    # --- 3. Token-id resolution (parallel UP + DOWN) ---
    token_id_yes: int | None = None
    token_id_no: int | None = None
    if cid is not None:
        async def _safe_token(direction: str) -> int | None:
            try:
                return await primary._resolve_token_id(cid, direction)
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    f"bar_context_t120.token_id_{direction.lower()}_failed",
                    symbol=symbol, tf=tf, cid=cid,
                )
                return None
        token_id_yes, token_id_no = await asyncio.gather(
            _safe_token("UP"), _safe_token("DOWN"),
        )

    # --- 4. FRESH CLOB book fetches (the bar-close books are 120s stale) ---
    async def _fetch_book(token_id: int | None) -> dict[str, Any] | None:
        if token_id is None:
            return None
        try:
            return await primary.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t120.book_fetch_failed",
                             symbol=symbol, tf=tf, token_id=token_id)
            return None

    book_yes, book_no = await asyncio.gather(
        _fetch_book(token_id_yes),
        _fetch_book(token_id_no),
    )

    spread_yes = _spread_pct(book_yes) if book_yes else None
    spread_no = _spread_pct(book_no) if book_no else None

    logger.info(
        "bar_context_t120.built",
        symbol=symbol, tf=tf, ws_s=ws_s,
        n_samples=len(ret_2m_samples),
        thr_present=abs_ret_2m_threshold is not None,
        cid_resolved=cid is not None,
        total_ms=int((time.monotonic() - t0) * 1000),
    )

    return BarContext(
        symbol=sym_upper,
        tf=tf,
        ws_s=ws_s,
        window_start_us=window_start_us,
        btc_now=btc_at_ws,
        btc_prior=None,         # not used in momo path
        btc_15m_prior=None,     # not used in momo path
        btc_1h_prior=None,      # not used in momo path
        abs_ret_5m_samples=(),  # momo doesn't use the 5m samples
        condition_id=cid,
        token_id_yes=token_id_yes,
        token_id_no=token_id_no,
        book_snapshot_yes=book_yes,
        book_snapshot_no=book_no,
        spread_pct_yes=spread_yes,
        spread_pct_no=spread_no,
        # Phase 18.5 momo fields
        phase="t_plus_120",
        btc_at_t_plus_120=btc_at_120,
        abs_ret_2m_samples=ret_2m_samples,
        abs_ret_2m_threshold=abs_ret_2m_threshold,
        # 2026-05-20 F7 RSI filter
        rsi_14_for_signal=rsi_14,
        # Phase 34 — MTF2 gate aux. Markov regime computed lazily by the
        # controller's gate block (with per-(sym, ws_s) cache) — too costly
        # to fetch 14d of 5MIN closes here every boundary.
        ret_15m_for_mtf=_ret_15m_mtf,
        ret_1h_for_mtf=_ret_1h_mtf,
        markov_regime_w20_5m_va=None,
    )


# ---------------------------------------------------------------------------
# Phase 18.5+ — t+60s BarContext (momo_v2 dispatch)
# ---------------------------------------------------------------------------


async def build_bar_context_t_plus_60(
    primary: PolymarketUpdownController,
    symbol: str,
    tf: str,
    ws_s: int,
) -> BarContext:
    """Build a momo_v2-phase BarContext at ``ws_s + 60s`` of an active market.

    Mirror of :func:`build_bar_context_t_plus_120` with two key deltas:

    1. ret_2m anchor is (ws_s - 60, ws_s + 60) instead of (ws_s, ws_s + 120).
       Two new fields populated:
         - ``btc_close_at_ws_minus_60`` = BTC@(ws_s - 60)  (strike anchor)
         - ``btc_at_t_plus_60``         = BTC@(ws_s + 60)
    2. Threshold samples come from ``_fetch_abs_ret_2m_v2_history``
       which feed-first reads ``feed.get_ret_2m_samples(anchor=
       'ws_minus_60_to_ws60')`` from the TV-native rolling deque
       (Phase 22.1; CLAUDE.md inv #13). Tier-3 SQL fallback if feed
       empty.

    Reuses ``primary``'s pool + executor + token-resolver helpers (same
    pattern as the t+120 builder). cid + token_ids are computed against
    ``signal_ts=ws_s`` — the market's open boundary, identical to v1.

    Designed to NEVER raise — fetch failures yield None values; the
    momo_v2 strategy returns NONE on missing data.
    """
    from datetime import UTC, datetime

    from backend.app.controllers.polymarket_updown import (
        BINANCE_SYMBOL_ID_MAP,
        KLINE_SOURCE,
        SNIPER_LOOKBACK_DAYS,
        _spread_pct,
    )
    from backend.app.data.bars import fetch_close_asof
    from backend.app.strategies.polymarket.market_mapping import resolve_condition_id

    sym_upper = symbol.upper()
    symbol_id = BINANCE_SYMBOL_ID_MAP.get(sym_upper)
    window_start_us = int(ws_s) * 1_000_000
    signal_ts = datetime.fromtimestamp(ws_s, tz=UTC)
    t0 = time.monotonic()

    # --- 1. Parallel kline + ret_2m_v2 samples + cid resolution ---
    async def _fetch_close(ts_offset: int) -> Decimal | None:
        if symbol_id is None:
            return None
        try:
            return await fetch_close_asof(
                symbol_id, "1MIN", ws_s + ts_offset,
                pool=primary.pool, source=KLINE_SOURCE,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t60.kline_fetch_failed",
                             symbol=symbol, tf=tf, ts_offset=ts_offset)
            return None

    async def _fetch_ret_2m_v2_samples() -> tuple[float, ...]:
        if symbol_id is None:
            return ()
        # Phase 22.1: no caching. Feed-backed _fetch_abs_ret_2m_v2_history
        # walks rolling deque (anchor='ws_minus_60_to_ws60') in <1ms.
        try:
            from_s = ws_s - SNIPER_LOOKBACK_DAYS * 86_400
            samples_list = await primary._fetch_abs_ret_2m_v2_history(
                symbol_id=symbol_id, tf=tf, from_s=from_s, until_s=ws_s,
            )
            return tuple(samples_list)
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t60.samples_fetch_failed",
                             symbol=symbol, tf=tf)
            return ()

    async def _resolve_cid() -> str | None:
        try:
            return await resolve_condition_id(
                primary.pool, symbol=symbol, tf=tf,  # type: ignore[arg-type]
                signal_ts=signal_ts,
            )
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t60.cid_resolve_failed",
                             symbol=symbol, tf=tf)
            return None

    # 2026-05-20 F7 RSI: fetch 15 closes (offsets -840..0) ending at ws_s.
    async def _fetch_rsi_14() -> float:
        from backend.app.indicators.rsi import compute_rsi_14
        offsets = [-60 * i for i in range(14, -1, -1)]
        closes = await asyncio.gather(*[_fetch_close(o) for o in offsets])
        floats = [float(c) if c is not None else float("nan") for c in closes]
        return compute_rsi_14(floats)

    # Bug fix 2026-05-07: also fetch BTC@ws (the bar-close anchor) so
    # slot.btc_close_at_ws gets populated correctly. on_tick's
    # _maybe_hedge / _maybe_sell_at_bid early-return when
    # slot.btc_close_at_ws == 0, which silently disabled all v2
    # HEDGE/SELL exits. Per spec §4e, rev_bp anchor is BTC@ws, NOT the
    # ws-60 strike — same as v1 momo so on_tick code is identical.
    # Phase 34 — MTF2 gate companion fetches. Same anchors as t_plus_120 builder.
    btc_at_ws, btc_at_ws_minus_60, btc_at_60, btc_at_minus_900_v2, btc_at_minus_3600_v2, ret_2m_v2_samples, cid, rsi_14 = await asyncio.gather(
        _fetch_close(0),       # btc_now = BTC@ws_s (rev_bp anchor for on_tick)
        _fetch_close(-60),     # btc_close_at_ws_minus_60 = BTC@(ws_s - 60)  (strike)
        _fetch_close(60),      # btc_at_t_plus_60         = BTC@(ws_s + 60)
        _fetch_close(-900),    # MTF2: 15m lookback
        _fetch_close(-3600),   # MTF2: 1h lookback
        _fetch_ret_2m_v2_samples(),
        _resolve_cid(),
        _fetch_rsi_14(),
    )

    _ret_15m_mtf_v2: float | None = None
    _ret_1h_mtf_v2: float | None = None
    if btc_at_ws is not None and btc_at_minus_900_v2 is not None and float(btc_at_minus_900_v2) > 0:
        _ret_15m_mtf_v2 = math.log(float(btc_at_ws) / float(btc_at_minus_900_v2))
    if btc_at_ws is not None and btc_at_minus_3600_v2 is not None and float(btc_at_minus_3600_v2) > 0:
        _ret_1h_mtf_v2 = math.log(float(btc_at_ws) / float(btc_at_minus_3600_v2))

    # --- 2. Compute q90 threshold inline (cheap; saves controller from re-doing) ---
    abs_ret_2m_threshold: float | None = None
    if len(ret_2m_v2_samples) >= 50:  # SNIPER_MIN_SAMPLES
        import numpy as _np
        abs_ret_2m_threshold = float(_np.quantile(ret_2m_v2_samples, 0.90))

    # --- 3. Token-id resolution (parallel UP + DOWN) ---
    token_id_yes: int | None = None
    token_id_no: int | None = None
    if cid is not None:
        async def _safe_token(direction: str) -> int | None:
            try:
                return await primary._resolve_token_id(cid, direction)
            except Exception:  # pragma: no cover — defensive
                logger.exception(
                    f"bar_context_t60.token_id_{direction.lower()}_failed",
                    symbol=symbol, tf=tf, cid=cid,
                )
                return None
        token_id_yes, token_id_no = await asyncio.gather(
            _safe_token("UP"), _safe_token("DOWN"),
        )

    # --- 4. FRESH CLOB book fetches (entry happens at t+60; books must be fresh) ---
    async def _fetch_book(token_id: int | None) -> dict[str, Any] | None:
        if token_id is None:
            return None
        try:
            return await primary.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover — defensive
            logger.exception("bar_context_t60.book_fetch_failed",
                             symbol=symbol, tf=tf, token_id=token_id)
            return None

    book_yes, book_no = await asyncio.gather(
        _fetch_book(token_id_yes),
        _fetch_book(token_id_no),
    )

    spread_yes = _spread_pct(book_yes) if book_yes else None
    spread_no = _spread_pct(book_no) if book_no else None

    logger.info(
        "bar_context_t60.built",
        symbol=symbol, tf=tf, ws_s=ws_s,
        n_samples=len(ret_2m_v2_samples),
        thr_present=abs_ret_2m_threshold is not None,
        cid_resolved=cid is not None,
        total_ms=int((time.monotonic() - t0) * 1000),
    )

    return BarContext(
        symbol=sym_upper,
        tf=tf,
        ws_s=ws_s,
        window_start_us=window_start_us,
        # btc_now = BTC@ws — populated so slot.btc_close_at_ws gets
        # set correctly downstream (rev_bp anchor for on_tick exits).
        # Strategy still reads btc_close_at_ws_minus_60 / btc_at_t_plus_60
        # for the ret_2m signal computation; this is purely for
        # downstream slot construction.
        btc_now=btc_at_ws,
        btc_prior=None,
        btc_15m_prior=None,
        btc_1h_prior=None,
        abs_ret_5m_samples=(),  # v2 doesn't use 5m samples
        condition_id=cid,
        token_id_yes=token_id_yes,
        token_id_no=token_id_no,
        book_snapshot_yes=book_yes,
        book_snapshot_no=book_no,
        spread_pct_yes=spread_yes,
        spread_pct_no=spread_no,
        # Phase 18.5+ momo_v2 fields
        phase="t_plus_60",
        btc_at_t_plus_120=None,            # v1 field — stays None for v2
        abs_ret_2m_samples=ret_2m_v2_samples,
        abs_ret_2m_threshold=abs_ret_2m_threshold,
        btc_close_at_ws_minus_60=btc_at_ws_minus_60,
        btc_at_t_plus_60=btc_at_60,
        # 2026-05-20 F7 RSI filter
        rsi_14_for_signal=rsi_14,
        # Phase 34 — MTF2 gate aux.
        ret_15m_for_mtf=_ret_15m_mtf_v2,
        ret_1h_for_mtf=_ret_1h_mtf_v2,
        markov_regime_w20_5m_va=None,
    )


async def poly_updown_scheduler(
    controller: PolymarketUpdownController,
    stop: asyncio.Event,
    *,
    tick_seconds: int = 10,
) -> None:
    """Run the Polymarket Updown scheduler until ``stop`` is set.

    Args:
        controller: A constructed ``PolymarketUpdownController`` with its
            executor and pool injected.
        stop: ``asyncio.Event`` that triggers graceful shutdown.
        tick_seconds: Cadence of the on_tick + boundary-check loop. Default
            10s matches RESEARCH §2.

    Never raises: per-iteration exceptions are caught, logged, and the loop
    continues. SIGTERM is handled via ``stop`` being set by the parent.
    """
    last_5m_fired_unix = 0
    last_15m_fired_unix = 0

    logger.info(
        "poly_updown_scheduler.starting",
        tick_seconds=tick_seconds,
        symbols=list(SUPPORTED_SYMBOLS),
    )

    while not stop.is_set():
        now_unix = int(time.time())

        # --- on_tick: hedge-hold reversal check across open slots ---
        try:
            await controller.on_tick()
        except Exception:
            logger.exception("poly_updown_scheduler.on_tick.error")

        # --- 5MIN boundary firing ---
        boundary_5m = (now_unix // TF_5M_SECONDS) * TF_5M_SECONDS
        if (
            boundary_5m > last_5m_fired_unix
            and (now_unix - boundary_5m) < tick_seconds + 5
        ):
            for sym in SUPPORTED_SYMBOLS:
                try:
                    await controller.on_bar_close(sym, "5m", [])
                except Exception:
                    logger.exception(
                        "poly_updown_scheduler.on_bar_close.error",
                        symbol=sym,
                        tf="5m",
                    )
            last_5m_fired_unix = boundary_5m
            logger.info(
                "poly_updown_scheduler.boundary_fired",
                tf="5m",
                boundary_unix=boundary_5m,
            )

        # --- 15MIN boundary firing ---
        boundary_15m = (now_unix // TF_15M_SECONDS) * TF_15M_SECONDS
        if (
            boundary_15m > last_15m_fired_unix
            and (now_unix - boundary_15m) < tick_seconds + 5
        ):
            for sym in SUPPORTED_SYMBOLS:
                try:
                    await controller.on_bar_close(sym, "15m", [])
                except Exception:
                    logger.exception(
                        "poly_updown_scheduler.on_bar_close.error",
                        symbol=sym,
                        tf="15m",
                    )
            last_15m_fired_unix = boundary_15m
            logger.info(
                "poly_updown_scheduler.boundary_fired",
                tf="15m",
                boundary_unix=boundary_15m,
            )

        # Sleep until next tick OR stop signal — whichever first.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=tick_seconds)

    logger.info("poly_updown_scheduler.stopped")


async def poly_updown_master_scheduler(
    primary: PolymarketUpdownController,
    siblings: list[PolymarketUpdownController],
    stop: asyncio.Event,
    *,
    tick_seconds: int = 10,
) -> None:
    """Single scheduler driving N parallel mode controllers off ONE shared
    snapshot per (symbol, tf, ws_s) bar boundary. Phase 24 fix for the
    multi-controller race documented in V4-SUBSET-BUG-VERDICT-2026-05-05.md.

    Sequence per boundary:
      1. on_tick: each controller's hedge-hold check (per-instance state — no
         shared context needed; runs sequentially across [primary, *siblings])
      2. For each symbol: build_bar_context ONCE, then dispatch on_bar_close
         to [primary, *siblings] sequentially with bar_ctx=ctx kwarg.

    Args:
        primary: The first registered controller. Its pool + executor are used
            to fetch the shared BarContext fields. Typical choice: the lowest-
            ordinal mode (e.g. 'volume' or 'sniper') — any base mode is fine
            since the shared fetches don't depend on strategy_mode.
        siblings: Remaining registered controllers (other strategy modes).
            Order doesn't matter — each gets the same bar_ctx.
        stop: asyncio.Event for graceful shutdown.
        tick_seconds: 10s — same cadence as legacy ``poly_updown_scheduler``.

    Per-mode exception isolation: each ``on_tick`` and ``on_bar_close`` call
    is wrapped in try/except so one mode raising doesn't block the others.

    Race window collapses from 1-10s (legacy: N independent fetches scheduled
    on N separate tasks) to <50ms (master: one fetch + N synchronous
    dispatches against the same snapshot).
    """
    last_5m_fired_unix = 0
    last_15m_fired_unix = 0
    # Phase 18.5 — separate dedupe keys for the t+120s momo boundaries.
    # Keyed by the underlying ws_s (the market boundary 120s ago), NOT by
    # the trigger time (ws_s + 120). On restart these reset to 0 — at most
    # one missed momo fire per restart per active boundary, identical
    # data-loss tolerance to bar-close boundaries.
    last_5m_t120_ws_fired = 0
    last_15m_t120_ws_fired = 0
    # Phase 18.5+ — separate dedupe keys for the t+60s momo_v2 boundaries.
    # Same shape as t120: keyed by ws_s, reset on restart.
    last_5m_t60_ws_fired = 0
    last_15m_t60_ws_fired = 0
    all_controllers = [primary, *siblings]
    # Phase 18.5 — partition controllers by phase. momo fires ONLY on the
    # t+120s phase; momo_v2 fires ONLY on the t+60s phase; all other
    # modes fire ONLY on bar-close. This avoids writing useless NONE
    # audit rows per 5m boundary for momo/momo_v2 controllers (their
    # signal returns NONE on the wrong phase, but the audit emit happens
    # upstream of strategy.signal).
    bar_close_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) not in ("momo", "momo_v2")
    ]
    momo_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) == "momo"
    ]
    momo_v2_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) == "momo_v2"
    ]

    logger.info(
        "poly_updown_master_scheduler.starting",
        tick_seconds=tick_seconds,
        n_controllers=len(all_controllers),
        n_bar_close=len(bar_close_controllers),
        n_momo=len(momo_controllers),
        n_momo_v2=len(momo_v2_controllers),
        primary_mode=getattr(primary, "strategy_mode", "unknown"),
        sibling_modes=[
            getattr(c, "strategy_mode", "unknown") for c in siblings
        ],
        symbols=list(SUPPORTED_SYMBOLS),
    )

    while not stop.is_set():
        now_unix = int(time.time())

        # --- on_tick: per-controller hedge-hold check (independent state) ---
        for ctrl in all_controllers:
            try:
                await ctrl.on_tick()
            except Exception:
                logger.exception(
                    "poly_updown_master_scheduler.on_tick.error",
                    strategy_mode=getattr(ctrl, "strategy_mode", "unknown"),
                )

        # --- Boundary firing helper — shared between 5m + 15m paths ---
        async def _fire_boundary(tf: str, boundary_unix: int) -> None:
            """Fire one bar boundary across all symbols + all controllers.

            Phase 24.1 latency optimization: BarContext per symbol is built
            in parallel via asyncio.gather; controller dispatch ALSO runs
            in parallel within each symbol (each controller has its own
            _threshold_cache + _slots — no shared mutable state, so
            parallel dispatch is safe and matches the original per-mode
            scheduler's parallelism while preserving the shared snapshot).
            """
            t0 = time.monotonic()
            # Build bar_ctx for all 3 symbols concurrently.
            ctx_results = await asyncio.gather(
                *[
                    build_bar_context(primary, sym, tf, boundary_unix)
                    for sym in SUPPORTED_SYMBOLS
                ],
                return_exceptions=True,
            )
            ctxs: dict[str, Any] = {}
            for sym, res in zip(SUPPORTED_SYMBOLS, ctx_results):
                if isinstance(res, BaseException):
                    logger.exception(
                        "poly_updown_master_scheduler.bar_context_build_failed",
                        symbol=sym, tf=tf, boundary_unix=boundary_unix,
                        exc_info=res,
                    )
                else:
                    ctxs[sym] = res
            t_built = time.monotonic()

            # Dispatch all (symbol, controller) pairs concurrently.
            # Phase 18.5: only bar_close_controllers fire here; momo
            # controllers fire on the t+120s boundary path below.
            async def _dispatch_one(sym: str, ctx: Any, ctrl: Any) -> None:
                try:
                    await ctrl.on_bar_close(sym, tf, [], bar_ctx=ctx)
                except Exception:
                    logger.exception(
                        "poly_updown_master_scheduler.on_bar_close.error",
                        symbol=sym, tf=tf,
                        strategy_mode=getattr(ctrl, "strategy_mode", "unknown"),
                    )

            tasks = [
                _dispatch_one(sym, ctx, ctrl)
                for sym, ctx in ctxs.items()
                for ctrl in bar_close_controllers
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=False)
            t_done = time.monotonic()

            logger.info(
                "poly_updown_master_scheduler.boundary_fired",
                tf=tf, boundary_unix=boundary_unix,
                n_controllers=len(bar_close_controllers),
                build_ms=int((t_built - t0) * 1000),
                dispatch_ms=int((t_done - t_built) * 1000),
                total_ms=int((t_done - t0) * 1000),
            )

        # Phase 18.5 — t+120s boundary helper (parallel to _fire_boundary
        # but uses the t+120s BarContext builder + dispatches ONLY to
        # momo controllers).
        async def _fire_t_plus_120_boundary(tf: str, ws_s: int) -> None:
            if not momo_controllers:
                return
            t0 = time.monotonic()
            ctx_results = await asyncio.gather(
                *[
                    build_bar_context_t_plus_120(primary, sym, tf, ws_s)
                    for sym in SUPPORTED_SYMBOLS
                ],
                return_exceptions=True,
            )
            ctxs: dict[str, Any] = {}
            for sym, res in zip(SUPPORTED_SYMBOLS, ctx_results):
                if isinstance(res, BaseException):
                    logger.exception(
                        "poly_updown_master_scheduler.t120_bar_context_build_failed",
                        symbol=sym, tf=tf, ws_s=ws_s, exc_info=res,
                    )
                else:
                    ctxs[sym] = res
            t_built = time.monotonic()

            async def _dispatch_one(sym: str, ctx: Any, ctrl: Any) -> None:
                try:
                    await ctrl.on_bar_close(sym, tf, [], bar_ctx=ctx)
                except Exception:
                    logger.exception(
                        "poly_updown_master_scheduler.t120_on_bar_close.error",
                        symbol=sym, tf=tf,
                        strategy_mode=getattr(ctrl, "strategy_mode", "unknown"),
                    )

            tasks = [
                _dispatch_one(sym, ctx, ctrl)
                for sym, ctx in ctxs.items()
                for ctrl in momo_controllers
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=False)
            t_done = time.monotonic()

            logger.info(
                "poly_updown_master_scheduler.t120_boundary_fired",
                tf=tf, ws_s=ws_s,
                n_momo_controllers=len(momo_controllers),
                build_ms=int((t_built - t0) * 1000),
                dispatch_ms=int((t_done - t_built) * 1000),
                total_ms=int((t_done - t0) * 1000),
            )

        # Phase 18.5+ — t+60s boundary helper for momo_v2. Mirror of the
        # t+120 helper but uses build_bar_context_t_plus_60 + dispatches
        # ONLY to momo_v2 controllers.
        async def _fire_t_plus_60_boundary(tf: str, ws_s: int) -> None:
            if not momo_v2_controllers:
                return
            t0 = time.monotonic()
            ctx_results = await asyncio.gather(
                *[
                    build_bar_context_t_plus_60(primary, sym, tf, ws_s)
                    for sym in SUPPORTED_SYMBOLS
                ],
                return_exceptions=True,
            )
            ctxs: dict[str, Any] = {}
            for sym, res in zip(SUPPORTED_SYMBOLS, ctx_results):
                if isinstance(res, BaseException):
                    logger.exception(
                        "poly_updown_master_scheduler.t60_bar_context_build_failed",
                        symbol=sym, tf=tf, ws_s=ws_s, exc_info=res,
                    )
                else:
                    ctxs[sym] = res
            t_built = time.monotonic()

            async def _dispatch_one(sym: str, ctx: Any, ctrl: Any) -> None:
                try:
                    await ctrl.on_bar_close(sym, tf, [], bar_ctx=ctx)
                except Exception:
                    logger.exception(
                        "poly_updown_master_scheduler.t60_on_bar_close.error",
                        symbol=sym, tf=tf,
                        strategy_mode=getattr(ctrl, "strategy_mode", "unknown"),
                    )

            tasks = [
                _dispatch_one(sym, ctx, ctrl)
                for sym, ctx in ctxs.items()
                for ctrl in momo_v2_controllers
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=False)
            t_done = time.monotonic()

            logger.info(
                "poly_updown_master_scheduler.t60_boundary_fired",
                tf=tf, ws_s=ws_s,
                n_momo_v2_controllers=len(momo_v2_controllers),
                build_ms=int((t_built - t0) * 1000),
                dispatch_ms=int((t_done - t_built) * 1000),
                total_ms=int((t_done - t0) * 1000),
            )

        # --- 5MIN boundary firing ---
        boundary_5m = (now_unix // TF_5M_SECONDS) * TF_5M_SECONDS
        if (
            boundary_5m > last_5m_fired_unix
            and (now_unix - boundary_5m) < tick_seconds + 5
        ):
            await _fire_boundary("5m", boundary_5m)
            last_5m_fired_unix = boundary_5m

        # --- 15MIN boundary firing ---
        boundary_15m = (now_unix // TF_15M_SECONDS) * TF_15M_SECONDS
        if (
            boundary_15m > last_15m_fired_unix
            and (now_unix - boundary_15m) < tick_seconds + 5
        ):
            await _fire_boundary("15m", boundary_15m)
            last_15m_fired_unix = boundary_15m

        # --- Phase 18.5 t+120s boundary firing ---
        # 5m markets: ws_s = floor((now_unix - 120) / 300) * 300; trigger
        # at ws_s + 120, dedupe on ws_s. Skipped entirely if no momo
        # controllers registered.
        if momo_controllers:
            ws_5m = ((now_unix - 120) // TF_5M_SECONDS) * TF_5M_SECONDS
            target_5m = ws_5m + 120
            if (
                ws_5m > last_5m_t120_ws_fired
                and 0 <= (now_unix - target_5m) < tick_seconds + 5
            ):
                await _fire_t_plus_120_boundary("5m", ws_5m)
                last_5m_t120_ws_fired = ws_5m

            ws_15m = ((now_unix - 120) // TF_15M_SECONDS) * TF_15M_SECONDS
            target_15m = ws_15m + 120
            if (
                ws_15m > last_15m_t120_ws_fired
                and 0 <= (now_unix - target_15m) < tick_seconds + 5
            ):
                await _fire_t_plus_120_boundary("15m", ws_15m)
                last_15m_t120_ws_fired = ws_15m

        # --- Phase 18.5+ t+60s boundary firing (momo_v2) ---
        # 5m markets: ws_s = floor((now_unix - 60) / 300) * 300; trigger
        # at ws_s + 60, dedupe on ws_s. Skipped entirely if no momo_v2
        # controllers registered. Same dedupe window shape as t120.
        if momo_v2_controllers:
            ws_5m_v2 = ((now_unix - 60) // TF_5M_SECONDS) * TF_5M_SECONDS
            target_5m_v2 = ws_5m_v2 + 60
            if (
                ws_5m_v2 > last_5m_t60_ws_fired
                and 0 <= (now_unix - target_5m_v2) < tick_seconds + 5
            ):
                await _fire_t_plus_60_boundary("5m", ws_5m_v2)
                last_5m_t60_ws_fired = ws_5m_v2

            ws_15m_v2 = ((now_unix - 60) // TF_15M_SECONDS) * TF_15M_SECONDS
            target_15m_v2 = ws_15m_v2 + 60
            if (
                ws_15m_v2 > last_15m_t60_ws_fired
                and 0 <= (now_unix - target_15m_v2) < tick_seconds + 5
            ):
                await _fire_t_plus_60_boundary("15m", ws_15m_v2)
                last_15m_t60_ws_fired = ws_15m_v2

        # Sleep until next tick OR stop signal — whichever first.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=tick_seconds)

    logger.info(
        "poly_updown_master_scheduler.stopped",
        n_controllers=len(all_controllers),
    )


__all__ = [
    "BarContext",
    "SUPPORTED_SYMBOLS",
    "TF_5M_SECONDS",
    "TF_15M_SECONDS",
    "build_bar_context",
    "build_bar_context_t_plus_60",
    "build_bar_context_t_plus_120",
    "poly_updown_master_scheduler",
    "poly_updown_scheduler",
]
