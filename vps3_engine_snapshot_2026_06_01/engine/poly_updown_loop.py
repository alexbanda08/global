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

    # Phase 34.1 — m1va gate aux. 1-MIN vol-adaptive Markov regime label
    # at ws_s. Populated by build_bar_context_t_plus_120 ONLY (the phase
    # momo v1 fires on). Sniper bar_close + momo_v2 t+60 leave this None.
    # Same encoding as markov_regime_w20_5m_va: -1=warmup, 0=Bear,
    # 1=Sideways, 2=Bull.
    markov_regime_w20_1m_va: int | None = None

    # Phase 35 — VWAP continuation aux. Populated ONLY by the late-fire
    # builder ``build_bar_context_t_plus_n`` when the engine dispatches
    # at one of the offsets {30, 60, 90, 120, 150, 180, 210, 240, 270}.
    # ``vwap_dev_bps`` = 10000 * ln(close@fire_us / vwap_15m_anchored).
    # ``vwap_15m_anchored`` is the anchored VWAP value (for audit only).
    # ``cross_asset_devs`` carries the SAME deviation computed for the
    # OTHER two crypto assets — used by the cross_full / cross_partial
    # gates in VwapContinuationStrategy.
    vwap_dev_bps: float | None = None
    vwap_15m_anchored: float | None = None
    cross_asset_devs: tuple[tuple[str, float | None], ...] | None = None

    # Phase 36 — Kelly ensemble + pre-window aux (Sleeves #1, #8, #9).
    # ``fair_edge_bp``: 10_000 * (model_prob - entry_vwap). The model_prob
    #   is ``fair_up`` for UP direction, ``1 - fair_up`` for DOWN. Strike
    #   = binance close at slot_start (chainlink approximation in shadow).
    # ``cvd_30s`` / ``cvd_60s``: Σ(2·taker_buy_quote - quote_volume) over
    #   the last 30 s / 60 s of 1s bars. Sign aligned with direction by
    #   the strategy's cvd_agree_* helper.
    # ``macd_hist``: MACD(12,26,9) histogram on 1s closes.
    # ``rvol_30_300``: short_vol(30s) / mean_vol_per_30s_in(300s).
    # ``s_now`` / ``strike``: numeric snapshots used by fair_up + audit.
    # ``entry_vwap_yes`` / ``entry_vwap_no``: best ask on the YES / NO
    #   token at the fire moment. Strategy picks the leg matching the
    #   direction; fair_edge_bp consumes the correct one.
    fair_edge_bp: float | None = None
    fair_up_value: float | None = None
    cvd_30s: float | None = None
    cvd_60s: float | None = None
    macd_hist_value: float | None = None
    rvol_30_300: float | None = None
    sigma_per_sqrt_sec_15m: float | None = None
    s_now: float | None = None
    strike: float | None = None
    entry_vwap_yes: float | None = None
    entry_vwap_no: float | None = None
    tau_s: float | None = None

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

    # --- 5. Phase 36 features + 5m Markov regime (FIX silent sleeves FIX 2) ---
    # overlay_sniper sleeves (e.g. *_sniper_fairedge500, *_sniper_m5v) fire on
    # this bar_close phase and read fair_edge_bp / cvd / macd / markov_5m off
    # this BarContext. They were ALWAYS None here (only the t_plus_n + pre_window
    # builders computed them), so the overlay gates failed every eval. Populate
    # them now. Cheap in-memory compute (no IO). Additive: the ~35 baseline
    # bar_close sleeves do not read these fields.
    from backend.app.data.bars import get_feed_instance as _get_feed_p36
    _feed_p36 = _get_feed_p36()
    _tf_seconds = 300 if tf == "5m" else 900
    _fire_us_bc = ws_s * 1_000_000
    _p36 = _compute_phase36_features(
        feed=_feed_p36, sym_upper=sym_upper, fire_us=_fire_us_bc,
        slot_start_us=ws_s * 1_000_000,
        slot_end_us=(ws_s + _tf_seconds) * 1_000_000,
        book_yes=book_yes, book_no=book_no,
    )
    _m5v_bc = _compute_m5v_regime(_feed_p36, sym_upper, ws_s)

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
        # FIX 2 — overlay_sniper gate inputs (fair_edge / cvd / macd / m5v).
        markov_regime_w20_5m_va=_m5v_bc,
        fair_edge_bp=_p36["fair_edge_bp_up"],
        fair_up_value=_p36["fair_up"],
        cvd_30s=_p36["cvd_30s"],
        cvd_60s=_p36["cvd_60s"],
        macd_hist_value=_p36["macd_hist"],
        rvol_30_300=_p36["rvol_30_300"],
        sigma_per_sqrt_sec_15m=_p36["sigma"],
        s_now=_p36["s_now"],
        strike=_p36["strike"],
        entry_vwap_yes=_p36["entry_vwap_yes"],
        entry_vwap_no=_p36["entry_vwap_no"],
        tau_s=_p36["tau_s"],
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

    # Phase 34.1 — M1V (1-MIN vol-adaptive Markov) regime label at ws_s.
    # Used by sleeve #3 (poly_updown_btc_15m_momo_hod) via the m1va gate.
    # Walks the binance feed deque: 21 most recent 1MIN closes ending at
    # ws_s + 14d of prior 1MIN log returns. Cheap (<5ms when warm).
    # NaN/None propagation: feed cold/short → _m1v_regime stays None →
    # controller coerces to -1 → markov_passes fails closed.
    _m1v_regime: int | None = None
    try:
        from backend.app.feeds.binance_market_data import (
            BinanceMarketDataFeed,
        )
        from backend.app.strategies.polymarket.markov import (
            label_regime_vol_adaptive,
        )
        # Phase 34 m1va fix 2026-05-26: read from global feed registry.
        from backend.app.data.bars import get_feed_instance as _get_feed_m1v
        _feed = _get_feed_m1v()
        if isinstance(_feed, BinanceMarketDataFeed):
            _closes_w = _feed.get_closes_window(sym_upper, ws_s, 21, "1m")
            if _closes_w is not None and len(_closes_w) == 21:
                _ret14d = _feed.get_log_returns_14d(sym_upper, ws_s, "1m")
                import numpy as _np_m1v
                _m1v_regime = int(
                    label_regime_vol_adaptive(
                        _np_m1v.asarray(_closes_w, dtype=_np_m1v.float64),
                        _np_m1v.asarray(_ret14d, dtype=_np_m1v.float64)
                        if _ret14d
                        else _np_m1v.array([], dtype=_np_m1v.float64),
                    )
                )
    except Exception:
        logger.exception(
            "bar_context_t120.m1v_compute_failed",
            symbol=sym_upper, tf=tf, ws_s=ws_s,
        )
        _m1v_regime = None  # gate fails closed

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

    # FIX 2 (silent sleeves) — 5m Markov regime for overlay_momo m5v gate
    # (e.g. shadow_poly_updown_sol_5m_momo_v1_m5v). Was hardcoded None below;
    # populate from the global binance feed. Additive (base momo ignores it).
    from backend.app.data.bars import get_feed_instance as _get_feed_m5v_t120
    _m5v_t120 = _compute_m5v_regime(_get_feed_m5v_t120(), sym_upper, ws_s)

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
        # Phase 34 — MTF2 gate aux.
        ret_15m_for_mtf=_ret_15m_mtf,
        ret_1h_for_mtf=_ret_1h_mtf,
        # FIX 2 — 5m Markov regime (was hardcoded None → m5v/m5va gates dead).
        markov_regime_w20_5m_va=_m5v_t120,
        # Phase 34.1 — m1va gate aux (sleeve #3 momo BTC 15m).
        markov_regime_w20_1m_va=_m1v_regime,
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

    # FIX 2 (silent sleeves) — Phase 36 features for overlay_momo_v2 gates
    # (fairedge500 / fairedge500_cvd30 / cvd_macd). These fire at t+60 and read
    # fair_edge_bp / cvd_30s / macd_hist off this BarContext; all were None
    # (only t_plus_n + pre_window builders computed them). Cheap in-memory.
    # Additive: base momo_v2 + the fade_momo_v2 sleeves do NOT read these
    # fields (fades gate on hod + markov only), so this leaves m5v / fade
    # behavior untouched. fire_us = ws_s + 60 (the v2 entry moment).
    from backend.app.data.bars import get_feed_instance as _get_feed_p36_t60
    _tf_seconds_t60 = 300 if tf == "5m" else 900
    _fire_us_t60 = (ws_s + 60) * 1_000_000
    _p36_t60 = _compute_phase36_features(
        feed=_get_feed_p36_t60(), sym_upper=sym_upper, fire_us=_fire_us_t60,
        slot_start_us=ws_s * 1_000_000,
        slot_end_us=(ws_s + _tf_seconds_t60) * 1_000_000,
        book_yes=book_yes, book_no=book_no,
    )

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
        # markov_5m left None here on purpose: the t+60 fade_momo_v2 sleeves
        # gate on it and are currently firing — not in scope to change.
        markov_regime_w20_5m_va=None,
        # FIX 2 — overlay_momo_v2 gate inputs (fair_edge / cvd / macd).
        fair_edge_bp=_p36_t60["fair_edge_bp_up"],
        fair_up_value=_p36_t60["fair_up"],
        cvd_30s=_p36_t60["cvd_30s"],
        cvd_60s=_p36_t60["cvd_60s"],
        macd_hist_value=_p36_t60["macd_hist"],
        rvol_30_300=_p36_t60["rvol_30_300"],
        sigma_per_sqrt_sec_15m=_p36_t60["sigma"],
        s_now=_p36_t60["s_now"],
        strike=_p36_t60["strike"],
        entry_vwap_yes=_p36_t60["entry_vwap_yes"],
        entry_vwap_no=_p36_t60["entry_vwap_no"],
        tau_s=_p36_t60["tau_s"],
    )


# ---------------------------------------------------------------------------
# Phase 36 — shared per-fire 1s feature compute (Sleeves #1, #8, #9)
# ---------------------------------------------------------------------------
def _compute_phase36_features(
    *,
    feed: Any,
    sym_upper: str,
    fire_us: int,
    slot_start_us: int,
    slot_end_us: int,
    book_yes: dict[str, Any] | None,
    book_no: dict[str, Any] | None,
    direction_for_edge: str = "UP",
) -> dict[str, Any]:
    """Return a dict of {cvd_30s, cvd_60s, macd_hist, rvol_30_300, sigma,
    s_now, strike, entry_vwap_yes, entry_vwap_no, tau_s, fair_up,
    fair_edge_bp_up, fair_edge_bp_down}.

    Strategy callers pick the leg matching their candidate direction.
    Approximations vs spec:
      - ``strike`` uses binance close at slot_start (shadow proxy for
        chainlink RTDS — actual resolution still uses onchain oracle).
      - ``entry_vwap`` uses best ask (top-of-book) rather than an L25 walk
        for $25 notional. Acceptable for shadow validation; live promotion
        would tighten this.

    Pure-ish (only reads from feed / book snapshots, no time.time()).
    """
    from backend.app.strategies.polymarket.features_1s import (
        cvd_window,
        fair_edge_bp as _fair_edge_bp,
        fair_up as _fair_up,
        macd_hist as _macd_hist,
        rvol_window,
        sigma_per_sqrt_sec_15m as _sigma_helper,
    )

    out: dict[str, Any] = {
        "cvd_30s": None,
        "cvd_60s": None,
        "macd_hist": None,
        "rvol_30_300": None,
        "sigma": None,
        "s_now": None,
        "strike": None,
        "entry_vwap_yes": None,
        "entry_vwap_no": None,
        "tau_s": None,
        "fair_up": None,
        "fair_edge_bp_up": None,
        "fair_edge_bp_down": None,
    }
    # ── 1s feed bars (vwap_store) — shared input for CVD / rvol / sigma / MACD
    bars: tuple = ()
    if feed is not None and hasattr(feed, "vwap_store"):
        bars = tuple(feed.vwap_store.bars.get(sym_upper, ()))
    if not bars:
        return out

    out["cvd_30s"] = cvd_window(bars, fire_us, 30)
    out["cvd_60s"] = cvd_window(bars, fire_us, 60)
    out["rvol_30_300"] = rvol_window(bars, fire_us, short_s=30, long_s=300)
    out["sigma"] = _sigma_helper(bars, fire_us)

    # MACD on the last ~120 of 1s closes ending at fire_us.
    macd_closes: list[float] = []
    for entry in bars:
        ts_us, close = entry[0], entry[1]
        if ts_us > fire_us:
            break
        if math.isfinite(close) and close > 0:
            macd_closes.append(float(close))
    if len(macd_closes) > 120:
        macd_closes = macd_closes[-120:]
    out["macd_hist"] = _macd_hist(macd_closes)

    # ── s_now: latest 1s close at-or-before fire_us
    for entry in reversed(bars):
        if entry[0] <= fire_us:
            out["s_now"] = float(entry[1])
            break

    # ── strike: binance close at slot_start_us (shadow proxy for chainlink)
    for entry in bars:
        if entry[0] >= slot_start_us:
            out["strike"] = float(entry[1])
            break
    if out["strike"] is None and bars:
        # fall back to closest available close
        out["strike"] = float(bars[-1][1])

    # ── entry_vwap from book best-ask (shadow approximation)
    def _best_ask(book: dict[str, Any] | None) -> float | None:
        if not book:
            return None
        asks = book.get("asks") or []
        if not asks:
            return None
        # asks[0] is best (lowest price). Each entry: [price, size] or dict.
        first = asks[0]
        if isinstance(first, (list, tuple)) and len(first) >= 1:
            try:
                return float(first[0])
            except (TypeError, ValueError):
                return None
        if isinstance(first, dict):
            try:
                return float(first.get("price"))
            except (TypeError, ValueError):
                return None
        return None

    out["entry_vwap_yes"] = _best_ask(book_yes)
    out["entry_vwap_no"] = _best_ask(book_no)

    # ── tau_s = seconds remaining to slot_end
    tau_us = max(0, slot_end_us - fire_us)
    out["tau_s"] = tau_us / 1_000_000.0 if tau_us > 0 else None

    # ── fair_up + fair_edge_bp for BOTH legs (strategy picks one)
    if (
        out["s_now"] is not None
        and out["strike"] is not None
        and out["sigma"] is not None
        and out["tau_s"] is not None
    ):
        fu = _fair_up(
            float(out["s_now"]),
            float(out["strike"]),
            float(out["sigma"]),
            float(out["tau_s"]),
        )
        out["fair_up"] = fu
        if fu is not None:
            out["fair_edge_bp_up"] = _fair_edge_bp(fu, out["entry_vwap_yes"], "UP")
            out["fair_edge_bp_down"] = _fair_edge_bp(fu, out["entry_vwap_no"], "DOWN")
    return out


def _compute_m5v_regime(feed: Any, sym_upper: str, until_s: int) -> int | None:
    """5-MIN vol-adaptive Markov regime label at ``until_s``.

    FIX (TV_AGENT_FIX_SILENT_SLEEVES FIX 2): ``markov_regime_w20_5m_va`` was
    hardcoded ``None`` in every builder, so every m5v / m5va gate read None,
    coerced to -1, and failed closed forever. This mirrors the proven inline
    M1V block but at 5m cadence (21 most recent 5MIN closes + 14d of 5MIN log
    returns). Returns -1/0/1/2 or ``None`` on warmup/error — the caller (and
    the gate) coerces ``None`` -> -1 so a cold feed still fails closed.

    Cheap in-memory read (<5ms warm); no IO. Purely additive: it can only
    ENABLE currently-dead m5v gates, never disable a firing sleeve.
    """
    try:
        from backend.app.feeds.binance_market_data import (
            BinanceMarketDataFeed as _BMDF,
        )
        from backend.app.strategies.polymarket.markov import (
            label_regime_vol_adaptive,
        )
        if not isinstance(feed, _BMDF):
            return None
        closes_w = feed.get_closes_window(sym_upper, until_s, 21, "5m")
        if closes_w is None or len(closes_w) != 21:
            return None
        ret14d = feed.get_log_returns_14d(sym_upper, until_s, "5m")
        import numpy as _np_m5v
        return int(
            label_regime_vol_adaptive(
                _np_m5v.asarray(closes_w, dtype=_np_m5v.float64),
                _np_m5v.asarray(ret14d, dtype=_np_m5v.float64)
                if ret14d
                else _np_m5v.array([], dtype=_np_m5v.float64),
            )
        )
    except Exception:
        logger.exception(
            "bar_context.m5v_compute_failed", symbol=sym_upper, until_s=until_s
        )
        return None


# ---------------------------------------------------------------------------
# Phase 35 — VWAP continuation late-fire BarContext builder
# ---------------------------------------------------------------------------
async def build_bar_context_t_plus_n(
    primary: PolymarketUpdownController,
    symbol: str,
    tf: str,
    ws_s: int,
    offset_s: int,
) -> BarContext:
    """Generic late-fire BarContext builder for VWAP continuation sleeves.

    Anchored at ``ws_s + offset_s`` (the actual fire moment). Populates:
      - vwap_dev_bps, vwap_15m_anchored (from feed.vwap_store)
      - cross_asset_devs (dev_bps for the OTHER two crypto assets)
      - rsi_14_for_signal (from existing _fetch_rsi_14 path — reuses 1m deque)
      - markov_regime_w20_1m_va (from existing M1V compute path)
      - cid + token_ids + book snapshots (for paper executor)

    Phase string is ``f"t_plus_{offset_s}"`` so VwapContinuationStrategy's
    phase gate matches only on the configured offset.
    """
    # Defer imports to avoid the cycle: poly_updown_loop -> controllers -> engine
    from datetime import UTC, datetime

    from backend.app.controllers.polymarket_updown import (
        BINANCE_SYMBOL_ID_MAP,
        _spread_pct,
    )
    from backend.app.strategies.polymarket.market_mapping import resolve_condition_id

    sym_upper = symbol.upper()
    window_start_us = ws_s * 1_000_000
    fire_us = (ws_s + offset_s) * 1_000_000
    t0 = time.monotonic()

    symbol_id = BINANCE_SYMBOL_ID_MAP.get(sym_upper)
    if symbol_id is None:
        # Unknown asset — return an empty BarContext; strategy will NONE-out.
        return BarContext(
            symbol=sym_upper, tf=tf, ws_s=ws_s,
            window_start_us=window_start_us,
            btc_now=None, btc_prior=None, btc_15m_prior=None, btc_1h_prior=None,
            abs_ret_5m_samples=(),
            condition_id=None, token_id_yes=None, token_id_no=None,
            book_snapshot_yes=None, book_snapshot_no=None,
            spread_pct_yes=None, spread_pct_no=None,
            phase=f"t_plus_{offset_s}",
        )

    # --- 1. VWAP dev_bps for THIS asset + cross-asset devs ---
    vwap_15m: float | None = None
    dev_bps: float | None = None
    cross_devs: list[tuple[str, float | None]] = []
    # Phase 35 / 36 fix 2026-05-26: controllers don't expose ``.feed``;
    # the binance feed is bound globally via bars.set_feed_instance()
    # at engine boot. Read it from there.
    from backend.app.data.bars import get_feed_instance as _get_feed
    feed = _get_feed()
    if feed is not None and hasattr(feed, "vwap_store"):
        try:
            vwap_15m = feed.vwap_store.vwap_at(sym_upper, fire_us)
            dev_bps = feed.vwap_store.dev_bps_at(sym_upper, fire_us)
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "bar_context_t_plus_n.vwap_failed",
                symbol=sym_upper, tf=tf, ws_s=ws_s, offset_s=offset_s,
            )
        for other in SUPPORTED_SYMBOLS:
            if other == sym_upper:
                continue
            try:
                cross_devs.append((other, feed.vwap_store.dev_bps_at(other, fire_us)))
            except Exception:
                cross_devs.append((other, None))
    else:
        cross_devs = [(o, None) for o in SUPPORTED_SYMBOLS if o != sym_upper]

    # --- 2. RSI(14) from 1MIN feed (same as F7 builders) ---
    async def _fetch_close(ts_offset: int) -> Decimal | None:
        ts_s = ws_s + ts_offset
        if feed is not None:
            with contextlib.suppress(Exception):
                c = feed.get_close_asof(sym_upper, ts_s)
                if c is not None:
                    return c
        return None

    async def _fetch_rsi_14() -> float:
        from backend.app.indicators.rsi import compute_rsi_14
        offsets = [-60 * i for i in range(14, -1, -1)]
        closes = await asyncio.gather(*[_fetch_close(o) for o in offsets])
        floats = [float(c) if c is not None else float("nan") for c in closes]
        return compute_rsi_14(floats)

    # --- 3. M1V regime (mirror of t_plus_120 builder) ---
    _m1v_regime: int | None = None
    try:
        from backend.app.feeds.binance_market_data import (
            BinanceMarketDataFeed as _BMDF,
        )
        from backend.app.strategies.polymarket.markov import (
            label_regime_vol_adaptive,
        )
        if isinstance(feed, _BMDF):
            _closes_w = feed.get_closes_window(sym_upper, ws_s, 21, "1m")
            if _closes_w is not None and len(_closes_w) == 21:
                _ret14d = feed.get_log_returns_14d(sym_upper, ws_s, "1m")
                import numpy as _np_m1v
                _m1v_regime = int(
                    label_regime_vol_adaptive(
                        _np_m1v.asarray(_closes_w, dtype=_np_m1v.float64),
                        _np_m1v.asarray(_ret14d, dtype=_np_m1v.float64)
                        if _ret14d
                        else _np_m1v.array([], dtype=_np_m1v.float64),
                    )
                )
    except Exception:
        logger.exception(
            "bar_context_t_plus_n.m1v_failed",
            symbol=sym_upper, tf=tf, ws_s=ws_s, offset_s=offset_s,
        )

    # --- 4. CID + token resolution + book fetches (mirror of t_plus_60) ---
    signal_ts = datetime.fromtimestamp(ws_s, tz=UTC)
    cid: str | None = None
    try:
        cid = await resolve_condition_id(
            primary.pool, symbol=sym_upper, tf=tf,  # type: ignore[arg-type]
            signal_ts=signal_ts,
        )
    except Exception:
        logger.exception(
            "bar_context_t_plus_n.cid_resolve_failed",
            symbol=sym_upper, tf=tf, ws_s=ws_s, offset_s=offset_s,
        )

    token_id_yes: int | None = None
    token_id_no: int | None = None
    if cid is not None:
        async def _safe_token(direction: str) -> int | None:
            try:
                return await primary._resolve_token_id(cid, direction)
            except Exception:  # pragma: no cover - defensive
                return None
        token_id_yes, token_id_no = await asyncio.gather(
            _safe_token("UP"), _safe_token("DOWN"),
        )

    async def _fetch_book(token_id: int | None) -> dict[str, Any] | None:
        if token_id is None:
            return None
        try:
            return await primary.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover - defensive
            return None

    book_yes, book_no, rsi_14 = await asyncio.gather(
        _fetch_book(token_id_yes),
        _fetch_book(token_id_no),
        _fetch_rsi_14(),
    )
    spread_yes = _spread_pct(book_yes) if book_yes else None
    spread_no = _spread_pct(book_no) if book_no else None

    # Phase 36 — populate 1s-derived features (CVD / MACD / rvol / fair_edge_bp).
    # Slot start = ws_s (UTC bar boundary); slot end = ws_s + tf_seconds.
    _tf_seconds = 300 if tf == "5m" else 900
    _slot_start_us = ws_s * 1_000_000
    _slot_end_us = (ws_s + _tf_seconds) * 1_000_000
    p36 = _compute_phase36_features(
        feed=feed,
        sym_upper=sym_upper,
        fire_us=fire_us,
        slot_start_us=_slot_start_us,
        slot_end_us=_slot_end_us,
        book_yes=book_yes,
        book_no=book_no,
    )
    # Strategy picks direction-specific fair_edge_bp at signal time. Stash
    # both in BarContext via a single "fair_edge_bp" field set later by
    # the strategy (we expose both legs in the audit payload for forensics).

    logger.info(
        "bar_context_t_plus_n.built",
        symbol=sym_upper, tf=tf, ws_s=ws_s, offset_s=offset_s,
        dev_bps=dev_bps, vwap_present=vwap_15m is not None,
        m1v=_m1v_regime, cid_resolved=cid is not None,
        cvd_30s=p36["cvd_30s"], macd=p36["macd_hist"], rvol=p36["rvol_30_300"],
        fair_edge_up=p36["fair_edge_bp_up"], fair_edge_dn=p36["fair_edge_bp_down"],
        total_ms=int((time.monotonic() - t0) * 1000),
    )

    return BarContext(
        symbol=sym_upper, tf=tf, ws_s=ws_s,
        window_start_us=window_start_us,
        btc_now=None, btc_prior=None, btc_15m_prior=None, btc_1h_prior=None,
        abs_ret_5m_samples=(),
        condition_id=cid,
        token_id_yes=token_id_yes, token_id_no=token_id_no,
        book_snapshot_yes=book_yes, book_snapshot_no=book_no,
        spread_pct_yes=spread_yes, spread_pct_no=spread_no,
        phase=f"t_plus_{offset_s}",
        rsi_14_for_signal=rsi_14,
        markov_regime_w20_1m_va=_m1v_regime,
        # Phase 35 — VWAP aux
        vwap_dev_bps=dev_bps,
        vwap_15m_anchored=vwap_15m,
        cross_asset_devs=tuple(cross_devs),
        # Phase 36 — 1s-derived features. Strategy reads fair_edge_bp_up
        # vs fair_edge_bp_down based on signed dev_bps direction. Store
        # both via the single ``fair_edge_bp`` BarContext field set to
        # the UP leg here; strategy flips to DOWN leg when dev_bps < 0.
        # (Simpler: stash both legs in the audit payload separately.)
        fair_edge_bp=p36["fair_edge_bp_up"],  # see strategy: flips at runtime
        fair_up_value=p36["fair_up"],
        cvd_30s=p36["cvd_30s"],
        cvd_60s=p36["cvd_60s"],
        macd_hist_value=p36["macd_hist"],
        rvol_30_300=p36["rvol_30_300"],
        sigma_per_sqrt_sec_15m=p36["sigma"],
        s_now=p36["s_now"],
        strike=p36["strike"],
        entry_vwap_yes=p36["entry_vwap_yes"],
        entry_vwap_no=p36["entry_vwap_no"],
        tau_s=p36["tau_s"],
    )


# ---------------------------------------------------------------------------
# Phase 36 — pre-window BarContext builder (Sleeves #8, #9)
# ---------------------------------------------------------------------------
async def build_bar_context_pre_window(
    primary: PolymarketUpdownController,
    symbol: str,
    tf: str,
    slot_start_unix_s: int,
    offset_s: int,
) -> BarContext:
    """BarContext at ``slot_start_unix_s - offset_s`` (offset_s > 0).

    Used by Sleeve #8 (S3, 5m, offset=60s pre) and Sleeve #9 (S4, 15m,
    offset=120s pre). The target market is the upcoming slot starting at
    ``slot_start_unix_s``; we resolve cid using signal_ts = that boundary.

    Phase string = ``f"pre_window_{offset_s}"`` so strategies' phase gates
    only match on the configured pre-window.
    """
    # Defer imports to avoid the cycle: poly_updown_loop -> controllers -> engine
    from datetime import UTC, datetime

    from backend.app.controllers.polymarket_updown import (
        BINANCE_SYMBOL_ID_MAP,
        _spread_pct,
    )
    from backend.app.strategies.polymarket.market_mapping import resolve_condition_id

    sym_upper = symbol.upper()
    fire_us = (slot_start_unix_s - offset_s) * 1_000_000
    window_start_us = slot_start_unix_s * 1_000_000
    _tf_seconds = 300 if tf == "5m" else 900
    slot_end_us = (slot_start_unix_s + _tf_seconds) * 1_000_000
    t0 = time.monotonic()

    if BINANCE_SYMBOL_ID_MAP.get(sym_upper) is None:
        return BarContext(
            symbol=sym_upper, tf=tf, ws_s=slot_start_unix_s,
            window_start_us=window_start_us,
            btc_now=None, btc_prior=None, btc_15m_prior=None, btc_1h_prior=None,
            abs_ret_5m_samples=(),
            condition_id=None, token_id_yes=None, token_id_no=None,
            book_snapshot_yes=None, book_snapshot_no=None,
            spread_pct_yes=None, spread_pct_no=None,
            phase=f"pre_window_{offset_s}",
        )

    # Phase 35 / 36 fix 2026-05-26: controllers don't expose ``.feed``;
    # the binance feed is bound globally via bars.set_feed_instance()
    # at engine boot. Read it from there.
    from backend.app.data.bars import get_feed_instance as _get_feed
    feed = _get_feed()

    # 1. Resolve cid for the UPCOMING slot
    signal_ts = datetime.fromtimestamp(slot_start_unix_s, tz=UTC)
    cid: str | None = None
    try:
        cid = await resolve_condition_id(
            primary.pool, symbol=sym_upper, tf=tf,  # type: ignore[arg-type]
            signal_ts=signal_ts,
        )
    except Exception:
        logger.exception(
            "bar_context_pre_window.cid_resolve_failed",
            symbol=sym_upper, tf=tf, slot_start_unix_s=slot_start_unix_s,
            offset_s=offset_s,
        )

    # 2. Token-id resolution
    token_id_yes: int | None = None
    token_id_no: int | None = None
    if cid is not None:
        async def _safe_token(direction: str) -> int | None:
            try:
                return await primary._resolve_token_id(cid, direction)
            except Exception:  # pragma: no cover - defensive
                return None
        token_id_yes, token_id_no = await asyncio.gather(
            _safe_token("UP"), _safe_token("DOWN"),
        )

    # 3. Book snapshots
    async def _fetch_book(token_id: int | None) -> dict[str, Any] | None:
        if token_id is None:
            return None
        try:
            return await primary.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover - defensive
            return None

    book_yes, book_no = await asyncio.gather(
        _fetch_book(token_id_yes),
        _fetch_book(token_id_no),
    )
    spread_yes = _spread_pct(book_yes) if book_yes else None
    spread_no = _spread_pct(book_no) if book_no else None

    # 4. VWAP dev_bps (anchored at fire_us — same 15m bucket as upcoming slot)
    vwap_15m: float | None = None
    dev_bps: float | None = None
    if feed is not None and hasattr(feed, "vwap_store"):
        try:
            vwap_15m = feed.vwap_store.vwap_at(sym_upper, fire_us)
            dev_bps = feed.vwap_store.dev_bps_at(sym_upper, fire_us)
        except Exception:
            pass

    # 5. Phase 36 features
    p36 = _compute_phase36_features(
        feed=feed,
        sym_upper=sym_upper,
        fire_us=fire_us,
        slot_start_us=window_start_us,
        slot_end_us=slot_end_us,
        book_yes=book_yes,
        book_no=book_no,
    )

    logger.info(
        "bar_context_pre_window.built",
        symbol=sym_upper, tf=tf, slot_start_unix_s=slot_start_unix_s,
        offset_s=offset_s,
        dev_bps=dev_bps, fair_edge_up=p36["fair_edge_bp_up"],
        fair_edge_dn=p36["fair_edge_bp_down"], cvd_60s=p36["cvd_60s"],
        cid_resolved=cid is not None,
        total_ms=int((time.monotonic() - t0) * 1000),
    )

    return BarContext(
        symbol=sym_upper, tf=tf, ws_s=slot_start_unix_s,
        window_start_us=window_start_us,
        btc_now=None, btc_prior=None, btc_15m_prior=None, btc_1h_prior=None,
        abs_ret_5m_samples=(),
        condition_id=cid,
        token_id_yes=token_id_yes, token_id_no=token_id_no,
        book_snapshot_yes=book_yes, book_snapshot_no=book_no,
        spread_pct_yes=spread_yes, spread_pct_no=spread_no,
        phase=f"pre_window_{offset_s}",
        vwap_dev_bps=dev_bps,
        vwap_15m_anchored=vwap_15m,
        fair_edge_bp=p36["fair_edge_bp_up"],
        fair_up_value=p36["fair_up"],
        cvd_30s=p36["cvd_30s"],
        cvd_60s=p36["cvd_60s"],
        macd_hist_value=p36["macd_hist"],
        rvol_30_300=p36["rvol_30_300"],
        sigma_per_sqrt_sec_15m=p36["sigma"],
        s_now=p36["s_now"],
        strike=p36["strike"],
        entry_vwap_yes=p36["entry_vwap_yes"],
        entry_vwap_no=p36["entry_vwap_no"],
        tau_s=p36["tau_s"],
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
        if getattr(c, "strategy_mode", None) not in (
            "momo", "momo_v2", "vwap_continuation",
            "vwap_kelly_ensemble", "vwap_kelly_fe1000",
            "prewindow_s3", "prewindow_s4_15m",
            "fade_momo_v2", "overlay_momo", "overlay_momo_v2",
        )
    ]
    # Phase 36b — fade/overlay modes piggyback on their base's boundary:
    #   fade_sniper, overlay_sniper → bar_close (above bucket).
    #   overlay_momo                → t+120 (with momo).
    #   fade_momo_v2, overlay_momo_v2 → t+60 (with momo_v2).
    momo_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) in ("momo", "overlay_momo")
    ]
    momo_v2_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) in (
            "momo_v2", "fade_momo_v2", "overlay_momo_v2",
        )
    ]
    # Phase 35 — VWAP continuation controllers, grouped by (tf, offset_s) so
    # the scheduler can fire one builder per (tf, offset, sym) tuple instead
    # of running build_bar_context_t_plus_n nine times per slot.
    vwap_cont_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) == "vwap_continuation"
    ]
    # Phase 36 — Kelly ensemble Sleeve #1 dispatched at t+120s on 5m slots
    # (offset can sweep higher but spec ships at 120). Pre-window Sleeves
    # #8/#9 dispatched at slot_start - 60/120 (BEFORE the slot opens).
    kelly_ensemble_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None)
        in ("vwap_kelly_ensemble", "vwap_kelly_fe1000")
    ]
    prewindow_s3_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) == "prewindow_s3"
    ]
    prewindow_s4_controllers = [
        c for c in all_controllers
        if getattr(c, "strategy_mode", None) == "prewindow_s4_15m"
    ]
    # Per-(tf, pre_offset_s) dedupe map for pre-window sleeves.
    prewindow_last_slot_fired: dict[tuple[str, int], int] = {
        ("5m", 60): 0,
        ("15m", 120): 0,
    }
    # Dedupe for kelly ensemble at t+120 (5m only initially).
    kelly_last_ws_fired_5m: int = 0
    vwap_by_tf_offset: dict[tuple[str, int], list[Any]] = {}
    for _vc in vwap_cont_controllers:
        _tf = getattr(_vc, "vwap_tf", "5m")
        _off = int(getattr(_vc, "vwap_offset_s", 60))
        vwap_by_tf_offset.setdefault((_tf, _off), []).append(_vc)
    # Per (tf, offset) dedupe map. Keyed on ws_s so a single (tf, offset)
    # cell fires at most once per slot regardless of poll cadence.
    vwap_last_ws_fired: dict[tuple[str, int], int] = {
        key: 0 for key in vwap_by_tf_offset
    }

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

        # Phase 35 — VWAP late-fire boundary helper. Generic over offset_s.
        # Only dispatches to vwap_continuation controllers configured for
        # this (tf, offset_s) cell, so a sleeve at offset=240 doesn't fire
        # at offset=60 (its strategy.signal would NONE-out anyway via the
        # phase gate, but skipping the BarContext build saves ~30ms/slot).
        async def _fire_t_plus_n_boundary(
            tf: str, ws_s: int, offset_s: int
        ) -> None:
            ctrls = vwap_by_tf_offset.get((tf, offset_s), [])
            if not ctrls:
                return
            # Only build for symbols that actually have a registered
            # controller (each VWAP sleeve targets ONE asset via
            # slot_allowlist; building all 3 symbols is waste).
            wanted_syms = {
                str(getattr(c, "vwap_asset", "BTC")).upper() for c in ctrls
            }
            t0_ = time.monotonic()
            ctx_results = await asyncio.gather(
                *[
                    build_bar_context_t_plus_n(primary, sym, tf, ws_s, offset_s)
                    for sym in wanted_syms
                ],
                return_exceptions=True,
            )
            ctxs: dict[str, Any] = {}
            for sym, res in zip(wanted_syms, ctx_results):
                if isinstance(res, BaseException):
                    logger.exception(
                        "poly_updown_master_scheduler.t_plus_n_bar_context_build_failed",
                        symbol=sym, tf=tf, ws_s=ws_s, offset_s=offset_s, exc_info=res,
                    )
                else:
                    ctxs[sym] = res
            t_built = time.monotonic()

            async def _dispatch_one(sym: str, ctx: Any, ctrl: Any) -> None:
                try:
                    await ctrl.on_bar_close(sym, tf, [], bar_ctx=ctx)
                except Exception:
                    logger.exception(
                        "poly_updown_master_scheduler.t_plus_n_on_bar_close.error",
                        symbol=sym, tf=tf, offset_s=offset_s,
                        audit_sleeve_id=getattr(ctrl, "_audit_sleeve_id_override", None),
                    )

            tasks = [
                _dispatch_one(sym, ctx, ctrl)
                for sym, ctx in ctxs.items()
                for ctrl in ctrls
                if str(getattr(ctrl, "vwap_asset", "BTC")).upper() == sym
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=False)
            t_done = time.monotonic()

            logger.info(
                "poly_updown_master_scheduler.t_plus_n_boundary_fired",
                tf=tf, ws_s=ws_s, offset_s=offset_s,
                n_controllers=len(ctrls),
                build_ms=int((t_built - t0_) * 1000),
                dispatch_ms=int((t_done - t_built) * 1000),
                total_ms=int((t_done - t0_) * 1000),
            )

        # Phase 36 — Kelly ensemble fire helper. Reuses t+120 BarContext
        # builder (Sleeve #1 fires at offset_s = 120 on 5m).
        async def _fire_kelly_ensemble_boundary(ws_s: int) -> None:
            ctrls = kelly_ensemble_controllers
            if not ctrls:
                return
            t0_ = time.monotonic()
            ctx_results = await asyncio.gather(
                *[
                    build_bar_context_t_plus_n(primary, sym, "5m", ws_s, 120)
                    for sym in SUPPORTED_SYMBOLS
                ],
                return_exceptions=True,
            )
            ctxs: dict[str, Any] = {}
            for sym, res in zip(SUPPORTED_SYMBOLS, ctx_results):
                if isinstance(res, BaseException):
                    logger.exception(
                        "poly_updown_master_scheduler.kelly_bar_context_build_failed",
                        symbol=sym, ws_s=ws_s, exc_info=res,
                    )
                else:
                    ctxs[sym] = res
            t_built = time.monotonic()

            async def _dispatch_one(sym: str, ctx: Any, ctrl: Any) -> None:
                try:
                    await ctrl.on_bar_close(sym, "5m", [], bar_ctx=ctx)
                except Exception:
                    logger.exception(
                        "poly_updown_master_scheduler.kelly_on_bar_close.error",
                        symbol=sym,
                        audit_sleeve_id=getattr(ctrl, "_audit_sleeve_id_override", None),
                    )

            tasks = [
                _dispatch_one(sym, ctx, ctrl)
                for sym, ctx in ctxs.items()
                for ctrl in ctrls
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=False)
            t_done = time.monotonic()
            logger.info(
                "poly_updown_master_scheduler.kelly_t120_fired",
                ws_s=ws_s, n_controllers=len(ctrls),
                build_ms=int((t_built - t0_) * 1000),
                dispatch_ms=int((t_done - t_built) * 1000),
                total_ms=int((t_done - t0_) * 1000),
            )

        # Phase 36 — pre-window fire helper (Sleeves #8 + #9). Fires at
        # (next_slot_start - offset). Each controller sees phase=
        # ``f"pre_window_{offset_s}"`` and its strategy gates on that.
        async def _fire_pre_window_boundary(
            tf: str, next_slot_start_s: int, offset_s: int
        ) -> None:
            if tf == "5m" and offset_s == 60:
                ctrls = prewindow_s3_controllers
            elif tf == "15m" and offset_s == 120:
                ctrls = prewindow_s4_controllers
            else:
                ctrls = []
            if not ctrls:
                return
            t0_ = time.monotonic()
            ctx_results = await asyncio.gather(
                *[
                    build_bar_context_pre_window(
                        primary, sym, tf, next_slot_start_s, offset_s
                    )
                    for sym in SUPPORTED_SYMBOLS
                ],
                return_exceptions=True,
            )
            ctxs: dict[str, Any] = {}
            for sym, res in zip(SUPPORTED_SYMBOLS, ctx_results):
                if isinstance(res, BaseException):
                    logger.exception(
                        "poly_updown_master_scheduler.prewindow_bar_context_build_failed",
                        symbol=sym, tf=tf, next_slot_start_s=next_slot_start_s,
                        offset_s=offset_s, exc_info=res,
                    )
                else:
                    ctxs[sym] = res
            t_built = time.monotonic()

            async def _dispatch_one(sym: str, ctx: Any, ctrl: Any) -> None:
                try:
                    await ctrl.on_bar_close(sym, tf, [], bar_ctx=ctx)
                except Exception:
                    logger.exception(
                        "poly_updown_master_scheduler.prewindow_on_bar_close.error",
                        symbol=sym, tf=tf, offset_s=offset_s,
                        audit_sleeve_id=getattr(ctrl, "_audit_sleeve_id_override", None),
                    )

            tasks = [
                _dispatch_one(sym, ctx, ctrl)
                for sym, ctx in ctxs.items()
                for ctrl in ctrls
            ]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=False)
            t_done = time.monotonic()
            logger.info(
                "poly_updown_master_scheduler.prewindow_fired",
                tf=tf, next_slot_start_s=next_slot_start_s, offset_s=offset_s,
                n_controllers=len(ctrls),
                build_ms=int((t_built - t0_) * 1000),
                dispatch_ms=int((t_done - t_built) * 1000),
                total_ms=int((t_done - t0_) * 1000),
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

        # Phase 35 — VWAP continuation late-fire boundaries. For each
        # registered (tf, offset_s) cell, check if (now - (ws_s + offset_s))
        # is inside the dispatch window and dedupe on ws_s. Same pattern as
        # the t60/t120 dedupe above.
        if vwap_by_tf_offset:
            for (vtf, voff), _ctrls in vwap_by_tf_offset.items():
                _tf_seconds = TF_5M_SECONDS if vtf == "5m" else TF_15M_SECONDS
                _ws_for_off = ((now_unix - voff) // _tf_seconds) * _tf_seconds
                _target = _ws_for_off + voff
                if (
                    _ws_for_off > vwap_last_ws_fired[(vtf, voff)]
                    and 0 <= (now_unix - _target) < tick_seconds + 5
                ):
                    await _fire_t_plus_n_boundary(vtf, _ws_for_off, voff)
                    vwap_last_ws_fired[(vtf, voff)] = _ws_for_off

        # Phase 36 — Kelly ensemble t+120 firing on 5m slots. Dedupe by ws_s.
        if kelly_ensemble_controllers:
            ws_5m_k = ((now_unix - 120) // TF_5M_SECONDS) * TF_5M_SECONDS
            target_5m_k = ws_5m_k + 120
            if (
                ws_5m_k > kelly_last_ws_fired_5m
                and 0 <= (now_unix - target_5m_k) < tick_seconds + 5
            ):
                await _fire_kelly_ensemble_boundary(ws_5m_k)
                kelly_last_ws_fired_5m = ws_5m_k

        # Phase 36 — pre-window dispatches. S3 (5m, -60s) + S4 (15m, -120s).
        # The "next slot_start" is the boundary STRICTLY AHEAD of now_unix.
        if prewindow_s3_controllers:
            next_5m = ((now_unix + TF_5M_SECONDS) // TF_5M_SECONDS) * TF_5M_SECONDS
            target_pre_5m = next_5m - 60
            if (
                next_5m > prewindow_last_slot_fired[("5m", 60)]
                and 0 <= (now_unix - target_pre_5m) < tick_seconds + 5
            ):
                await _fire_pre_window_boundary("5m", next_5m, 60)
                prewindow_last_slot_fired[("5m", 60)] = next_5m
        if prewindow_s4_controllers:
            next_15m = ((now_unix + TF_15M_SECONDS) // TF_15M_SECONDS) * TF_15M_SECONDS
            target_pre_15m = next_15m - 120
            if (
                next_15m > prewindow_last_slot_fired[("15m", 120)]
                and 0 <= (now_unix - target_pre_15m) < tick_seconds + 5
            ):
                await _fire_pre_window_boundary("15m", next_15m, 120)
                prewindow_last_slot_fired[("15m", 120)] = next_15m

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
