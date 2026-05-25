"""PolymarketUpdownController — sleeve controller for binary updown sleeves
across BTC/ETH/SOL × 5m/15m (Phase 15, Task 4 + Phase 18.1, Task 2-3).

One controller instance manages all 6 (symbol, tf) slots. The BarEngine
dispatches ``on_bar_close(symbol, tf, bars)`` at each bar boundary; the
controller picks the right strategy (5m or 15m), pre-fetches Binance
closes (``_build_signal_aux``), computes the timeframe-specific sniper
threshold (``_fetch_or_compute_threshold`` — q90 on 5m / q80 on 15m,
rolling 14d, daily cache), resolves the Polymarket condition_id, and
routes a $25 entry order to either:

- ``PolyPaperExecutor.place_entry_order`` when ``mode='paper'``
- ``PolymarketClient.place_entry_order`` when ``mode='live'``

Phase 18.1 also adds the **hedge-hold** path:

- ``on_tick()`` runs every ~10s while any slot is open.
- ``_maybe_hedge(slot)`` watches Binance close vs the cached
  ``btc_close_at_ws``; if it has reverted ≥ ``REV_BP_THRESHOLD``
  basis points against the signal direction, places an OPPOSITE-side
  buy at the current ask using the SAME executor + SAME sleeve as the
  original entry (RESEARCH §3.3). Idempotent — once
  ``slot.status == 'hedged_holding'`` later ticks skip.
- 3-attempt 200ms-backoff retry on hedge order rejection (RESEARCH §7).

INVARIANTS:
- $25/slot HARD-CODED per D-04 (constructor rejects override).
- NO ``place_exit_order`` calls in routine bar-close path (D-06).
  EXCEPTION (Phase 18.2 V2 HYBRID): when ``TV_POLY_HEDGE_POLICY=HYBRID``,
  ``_try_bid_exit`` calls ``place_exit_order`` on the **on_tick** path
  (NOT bar-close) when opposite-side asks empty. This is the documented
  HYBRID branch-2 terminal state, not an exit-on-signal — bar-close path
  remains exit-free.
- Bars passed to ``strategy.signal()`` are CLOSED (CLAUDE.md #4).
- NO writes to ``engine.poly_*`` tables (CLAUDE.md #13). Audit goes to
  ``trading.events`` only.
- Stale Binance feed (>2 min lag) → skip hedge check (RESEARCH §7).
- Hedge order matches entry qty exactly (RESEARCH §3.3).
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import math
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Literal


# Phase 18.5 race fix — task-isolated bar_ctx storage. Was previously a
# plain instance attribute (``self._bar_ctx_active = bar_ctx``); when the
# master scheduler dispatched 3 symbols × N controllers concurrently via
# asyncio.gather, ALL coroutines on the same controller instance shared
# that single attribute. Late-stage audit reads (after _place_entry's
# await chain) would see a sibling task's clobber → None → momo audit
# enrichment fields silently omitted on FILLED rows.
#
# ContextVar.set() returns a Token; subsequent reads inside the same
# asyncio task see the value, but other tasks (each with its own copied
# context per asyncio.Task contract) see the parent context's value
# (None at the boundary entry). Token reset in the wrapper's finally
# block restores the prior value when the task completes.
_BAR_CTX_ACTIVE: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "_bar_ctx_active", default=None
)

import numpy as np

from backend.app.data import bars as _bars_module  # Phase 22.1 feed access
from backend.app.data.bars import fetch_close_asof, fetch_close_with_ts_asof
from backend.app.strategies.polymarket import Updown5mStrategy, Updown15mStrategy
from backend.app.venues.polymarket.gamma_client import GammaClient, MarketMetadata
from backend.app.venues.polymarket.onchain_oracle import OnchainOracle, ResolutionOutcome
from backend.app.strategies.polymarket.inverse import (
    INVERSE_BASE_MODE,
    INVERSE_KINDS,
    INVERSE_REASON,
    InverseKind,
    apply_inverse_filter,
    inverse_sleeve_id,
    is_inverse_sleeve,
)
from backend.app.services.poly_market_discovery import MarketDiscoveryUnreachableError
from backend.app.strategies.polymarket.market_mapping import resolve_condition_id

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    import asyncpg

    from backend.app.data.models import Bar
    from backend.app.services.poly_market_discovery import PolyMarketDiscovery
    from backend.app.strategies.polymarket.base import (
        PolymarketBinaryStrategy,
        SignalResult,
    )

logger = logging.getLogger(__name__)

Mode = Literal["paper", "live"]
Tf = Literal["5m", "15m"]
Symbol = Literal["BTC", "ETH", "SOL"]


class MarketNotFoundError(Exception):
    """Raised when live-mode metadata lookup fails for a condition_id.

    Phase 26-03 (D-05/D-07): live path raises rather than falling back to
    Storedata (`public.markets`). Per-call-site translation to ``return None``
    is acceptable for metadata-optional paths (e.g. ``_check_market_freshness``);
    metadata-required paths must let it propagate.
    """

# D-04: $25/slot fixed (SIZING-WK1 micro-live scale).
NOTIONAL_PER_SLOT_USD = Decimal("25")

# D-04: 6 (symbol, tf) slots — code-locked.
SUPPORTED_SYMBOLS: tuple[Symbol, ...] = ("BTC", "ETH", "SOL")
SUPPORTED_TFS: tuple[Tf, ...] = ("5m", "15m")

# Phase 18.1 D-04 constant: Binance reversal trigger (basis points). 5 bps
# was tested 3..50; captures ~82% of rev_bp=3's PnL with half the drift.
REV_BP_THRESHOLD = 5

# Sniper rolling window (RESEARCH §3.3): 14 calendar days.
SNIPER_LOOKBACK_DAYS = 14

# Cold-start floor: at fewer than 50 |ret_5m| samples in the lookback,
# the threshold is None — sniper-mode strategies fall back to NONE.
SNIPER_MIN_SAMPLES = 50

# Hedge order retry policy (RESEARCH §7).
HEDGE_RETRY_ATTEMPTS = 3
HEDGE_RETRY_BACKOFF_S = 0.2

# 2026-05-09 Fix B — bid-exit retry policy (mirrors HEDGE_RETRY for the
# WS-staleness recovery story). Pre-fix: SELL_BID was one-shot — if the
# WS book snapshot was empty at the exact rev_bp tick, SELL fell straight
# to held_no_hedge_no_exit and never retried. Post-Fix-A audit on VPS3
# showed SELL_BID firing at 4% vs HEDGE_HOLD at 61% — the gap was the
# missing retry resilience. Three attempts with 100ms backoff catches
# transient WS gaps without burning the 10s tick budget.
BID_EXIT_RETRY_ATTEMPTS = 3
BID_EXIT_RETRY_BACKOFF_S = 0.1

# Stale signal feed: skip hedge check if latest 1MIN close is older than
# this many seconds (RESEARCH §7).
STALE_BINANCE_FEED_SECONDS = 120

# Per-VPS kline feed selector. VPS2 is geo-blocked from Binance and runs an
# OKX WS ingestor (source='okx-ws'); VPS3 runs the native Binance WS
# ingestor (source='binance-spot-ws'). Both write into the same
# public.binance_klines_v2 table; the source tag is the disambiguator.
# Default is 'okx' to preserve VPS2 behavior; set TV_POLY_UPDOWN_KLINE_FEED=binance
# in /etc/tv/tradingvenue.env on hosts where Binance is reachable.
_KLINE_FEED_CONFIGS: dict[str, tuple[str, dict[str, str]]] = {
    "okx": (
        "okx-ws",
        {
            "BTC": "OKX_SPOT_BTC_USDT",
            "ETH": "OKX_SPOT_ETH_USDT",
            "SOL": "OKX_SPOT_SOL_USDT",
        },
    ),
    "binance": (
        "binance-spot-ws",
        {
            "BTC": "BINANCE_SPOT_BTC_USDT",
            "ETH": "BINANCE_SPOT_ETH_USDT",
            "SOL": "BINANCE_SPOT_SOL_USDT",
        },
    ),
}
KLINE_FEED = os.getenv("TV_POLY_UPDOWN_KLINE_FEED", "okx").lower()
if KLINE_FEED not in _KLINE_FEED_CONFIGS:
    raise ValueError(
        f"TV_POLY_UPDOWN_KLINE_FEED={KLINE_FEED!r} invalid; "
        f"expected one of {list(_KLINE_FEED_CONFIGS)}"
    )
KLINE_SOURCE, SIGNAL_SYMBOL_ID_MAP = _KLINE_FEED_CONFIGS[KLINE_FEED]

# Backward-compatible alias — internal code may still reference the old name.
BINANCE_SYMBOL_ID_MAP = SIGNAL_SYMBOL_ID_MAP

# Phase 18.2 V2: hedge exit policy selector.
#   HEDGE_HOLD (V1, default) — opposite-side ask empty → slot rides to resolution
#                              unhedged (status=held_no_hedge).
#   HYBRID     (V2)          — opposite-side ask empty → fall through to
#                              place_exit_order against own held side at bid
#                              (status=exited_at_bid). Captures alpha vs
#                              HEDGE_HOLD per V2 backtest (+0.9–2.0pp ROI on
#                              every cell).
#
# CLAUDE.md inv #6 ("NO place_exit_order in routine bar-close path") is NOT
# violated by HYBRID branch 2: the bid-exit fires on the on_tick path (Phase
# 18.1 hedge-watch loop), not on bar-close. The exit IS the documented
# terminal state for the HYBRID design.
# Phase 18.5 — extended valid set:
#   HEDGE_HOLD — V1 default. on_tick fires hedge buy on rev_bp reversal.
#   HYBRID     — V2. hedge buy first; fallback to bid-exit when opposite asks empty.
#   HOLD_ONLY  — momo HOLD policy. on_tick is a no-op; slot held to resolution.
#   SELL_BID   — momo SELL policy. on_tick fires bid-exit on rev_bp reversal
#                (skips the opposite-ask leg of HEDGE_HOLD/HYBRID; sells own bid).
_VALID_HEDGE_POLICIES = ("HEDGE_HOLD", "HYBRID", "HOLD_ONLY", "SELL_BID")
HEDGE_POLICY = os.getenv("TV_POLY_HEDGE_POLICY", "HEDGE_HOLD").upper()
if HEDGE_POLICY not in _VALID_HEDGE_POLICIES:
    raise ValueError(
        f"TV_POLY_HEDGE_POLICY={HEDGE_POLICY!r} invalid; expected one of {_VALID_HEDGE_POLICIES}"
    )

# Phase 18.5 — sleeve_id suffix per hedge_policy (momo only). Bare module-env
# HEDGE_POLICY callers (volume/sniper/v3/v4/inverse) do NOT see a suffix —
# their sleeve_ids are unchanged. The suffix maps map only matters when
# strategy_mode == "momo" so 3 controllers per (sym, tf) get distinct
# sleeve_ids in trading.events.
_HEDGE_POLICY_SUFFIX: dict[str, str] = {
    "HEDGE_HOLD": "HEDGE",
    "HYBRID":     "HYBRID",
    "HOLD_ONLY":  "HOLD",
    "SELL_BID":   "SELL",
}

# ─── V3 portfolio constants (TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md) ───────
# Per-asset tuned magnitude quantiles for V3 sniper portfolio.
# 5m only — V3 does NOT run on 15m markets (backtest §TL;DR: 15m diluted HO
# ROI from 32% → 26%). Forward-walk evidence in
# strategy_lab/reports/RESEARCH_DEEP_DIVE_2026_04_29.md.
V3_PER_ASSET_QUANTILE: dict[tuple[str, str], float] = {
    ("BTC", "5m"): 0.90,  # top 10% by |ret_5m| — same as V2 sniper baseline
    ("ETH", "5m"): 0.95,  # top  5% — TIGHTER than V2; 65% HO hit
    ("SOL", "5m"): 0.85,  # top 15% — paired with multi-horizon AND filter
}

# V3 multi-horizon AND filter applies only to specific (symbol, tf) cells.
# When True, strategy.signal() requires ret_5m, ret_15m, ret_1h to all
# share sign before firing.
V3_REQUIRE_MULTI_HORIZON: frozenset[tuple[str, str]] = frozenset({("SOL", "5m")})

# V3 spread filter: skip entry if (ask - bid) / mid >= threshold. Captures
# +2.0pp HO ROI on holdout. Tunable via TV_POLY_V3_SPREAD_FILTER_PCT (legacy
# uniform default) — kept for backward compatibility.
V3_SPREAD_FILTER_PCT = float(os.getenv("TV_POLY_V3_SPREAD_FILTER_PCT", "0.02"))


# Phase 18.3 — per-asset spread filter (Fix A from SOL_V3_FIX_SPEC_2026_05_04).
# SOL Polymarket UpDown 5m books have median spread 4-6% (min observed 2.02%
# across 184 wide_spread_skip events) — the BTC-calibrated 2% threshold blocks
# essentially every SOL signal. Per-asset thresholds restore SOL coverage
# without loosening BTC/ETH.
#
# Override priority (first match wins):
#   1. TV_POLY_V3_SPREAD_FILTER_<ASSET> env var (e.g. TV_POLY_V3_SPREAD_FILTER_SOL=0.025)
#   2. V3_SPREAD_FILTER_PCT_DEFAULT[symbol]
#   3. Legacy TV_POLY_V3_SPREAD_FILTER_PCT (V3_SPREAD_FILTER_PCT module global)
#
# This module global stays the legacy fallback so any callers of
# `V3_SPREAD_FILTER_PCT` (tests, audit dumps, future modes) keep working.
V3_SPREAD_FILTER_PCT_DEFAULT: dict[str, float] = {
    "BTC": 0.02,
    "ETH": 0.02,
    "SOL": 0.025,  # SOL median spread is 4-6%; 2.5% catches the tightest 5-10%
}


def _v3_spread_filter_for(symbol: str) -> float:
    """Per-asset spread filter, env-overridable.

    Looks up ``TV_POLY_V3_SPREAD_FILTER_<ASSET>`` env var first, then
    ``V3_SPREAD_FILTER_PCT_DEFAULT``, then the legacy uniform
    ``V3_SPREAD_FILTER_PCT`` (from ``TV_POLY_V3_SPREAD_FILTER_PCT``).

    Pure helper — exported for tests.
    """
    sym = symbol.upper()
    env_key = f"TV_POLY_V3_SPREAD_FILTER_{sym}"
    env_val = os.environ.get(env_key)
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            pass
    return V3_SPREAD_FILTER_PCT_DEFAULT.get(sym, V3_SPREAD_FILTER_PCT)


# === V3.1 / V3.2 / V4 patch config (Phase 18.2) ===
#
# V3.1, V3.2, V4 are NEW strategy variants running in parallel SHADOW mode
# alongside (untouched) v1/v2/v3 per D-11. They reuse v3's spread-filter +
# token-id-resolve + 5m-only flow via parallel branches that COPY the v3
# logic verbatim, then layer additional gates on top.
#
# Live evidence + backtest: see
# strategy_lab/reports/V3_1_PATCH_SPEC_2026_04_30.md and
# strategy_lab/reports/V3_2_DEPLOY_SPEC_2026_04_30.md.

# V3.1: per-direction asymmetric magnitude quantiles. ETH UP and SOL UP show
# 6-15pp lower hit rates than their DOWN counterparts (both 7-day backtest
# holdout AND 12h live evidence). Tighten the UP threshold to be more
# selective on those pairs. BTC stays symmetric.
V3_1_PER_ASSET_QUANTILE: dict[tuple[str, str, str], float] = {
    ("BTC", "5m", "UP"): 0.90,  # symmetric — no change
    ("BTC", "5m", "DOWN"): 0.90,
    ("ETH", "5m", "UP"): 0.97,  # tighter than V3 (was 0.95)
    ("ETH", "5m", "DOWN"): 0.95,  # unchanged
    ("SOL", "5m", "UP"): 0.92,  # tighter than V3 (was 0.85), paired with multi-h
    ("SOL", "5m", "DOWN"): 0.85,  # unchanged
}

# V3.1: live-direction allowlist. Empty / missing => both directions allowed.
# Paper mode IGNORES this (still fires both directions for ongoing eval per
# D-04). Promotion criterion: ≥55% hit on n≥30 in paper before live-allow.
V3_1_LIVE_DIRECTIONS: dict[tuple[str, str], set[str]] = {
    ("SOL", "5m"): {"DOWN"},  # SOL UP paper-only — 11% hit (n=9) live evidence
}

# V3.1: soft regime overlay. ±0.5% on 1h close-to-close return.
# UP allowed iff ret_1h >= -threshold; DOWN allowed iff ret_1h <= threshold.
# Captures the "don't fight the 1h trend" intuition without fully blocking
# counter-trend at neutral regimes.
V3_1_REGIME_THRESHOLD: float = 0.005

# V3.2: hour-of-day blocklist (UTC). Hours where ALL THREE assets show
# ≤-5pp deviation in 7-day backtest holdout (correlation with low-volume
# Asia + late-Europe sessions).
V3_2_HOUR_BLOCKLIST_UTC: set[int] = {1, 16, 22}

# V3.2: liquidity quiet regime — skip if recent 5-min Binance liq notional
# > $10k. Backtest shows alpha concentrates when 5-min liq notional is low
# (no liquidation cascade in progress). Fail-open if liq_db unreachable.
V3_2_LIQ_QUIET_THRESHOLD_USD: float = 10_000.0


# === V3.1 / V3.2 / V4 helper functions (Phase 18.2) ===
#
# Pure helpers exported for tests. All gates are env-flag-gated — when the
# corresponding feature flag is "false" (env var), the gate is a no-op
# (returns True / passes the signal). Defaults are "true" so a freshly-
# deployed binary has all gates active. Operator can flip individual gates
# off via env without redeploy.


def _v3p_flag(name: str, default: str = "true") -> bool:
    """Module-private env feature flag reader for V3-patch gates.

    Used by the v3_1_* / v3_2_* helpers below. Underscore prefix to avoid
    accidental import; tests use ``monkeypatch.setenv`` directly.
    """
    return os.environ.get(name, default).lower() == "true"


# Phase 25 Tier A — TCA cost baselines (operator-tunable env vars).
#
# The Polymarket CLOB submit response includes a `fee` field which we
# prefer when non-zero (real venue-reported fees). These env vars provide
# a fallback baseline when the venue field is 0 (typical — CLOB has no
# explicit maker/taker fee on USDC trades; gas-cost estimates land here).
#
# `predicted_*` baselines are placeholders until per-strategy edge models
# emit `predicted_edge_pp` directly on signal rows. Operator can tune to
# the portfolio's average expectation.
def _f_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


_TV_POLY_FEE_USD_PER_FILL = _f_env("TV_POLY_FEE_USD_PER_FILL", 0.50)
_TV_POLY_PREDICTED_EDGE_PP = _f_env("TV_POLY_PREDICTED_EDGE_PP", 0.0)
_TV_POLY_PREDICTED_COST_BPS = _f_env("TV_POLY_PREDICTED_COST_BPS", 0.0)


def v3_1_quantile_for(symbol: str, tf: str, direction: str) -> float | None:
    """V3.1 asymmetric per-direction quantile lookup.

    Returns the quantile for (symbol, tf, direction) from V3_1_PER_ASSET_QUANTILE,
    or None if the pair isn't configured (caller falls back to V3 base quantile).

    When ``V3_1_ASYMMETRIC_QUANTILE_ENABLED=false``, returns None unconditionally
    so callers fall back to the symmetric V3 path.

    Pure helper exported for tests.
    """
    if not _v3p_flag("V3_1_ASYMMETRIC_QUANTILE_ENABLED"):
        return None
    return V3_1_PER_ASSET_QUANTILE.get((symbol.upper(), tf, direction))


def v3_1_regime_passes(direction: str, ret_1h: float) -> bool:
    """V3.1 soft regime overlay. UP requires ret_1h >= -threshold;
    DOWN requires ret_1h <= +threshold. Either direction passes at neutral
    (|ret_1h| < threshold).

    When ``V3_1_REGIME_OVERLAY_ENABLED=false``, always returns True.

    Pure helper exported for tests.
    """
    if not _v3p_flag("V3_1_REGIME_OVERLAY_ENABLED"):
        return True
    if direction == "UP":
        return ret_1h >= -V3_1_REGIME_THRESHOLD
    if direction == "DOWN":
        return ret_1h <= V3_1_REGIME_THRESHOLD
    return True


def v3_1_live_direction_allowed(symbol: str, tf: str, direction: str, live_mode: bool) -> bool:
    """V3.1 live-direction filter. Block configured directions when live_mode
    is True. Paper mode always passes (intentional — keep paper data flowing
    for ongoing eval per D-04).

    When ``V3_1_SOL_UP_LIVE_DISABLED=false``, always returns True.

    Pure helper exported for tests.
    """
    if not _v3p_flag("V3_1_SOL_UP_LIVE_DISABLED"):
        return True
    if not live_mode:
        return True
    allowed = V3_1_LIVE_DIRECTIONS.get((symbol.upper(), tf))
    if allowed is None:
        return True
    return direction in allowed


def v3_2_hour_passes(now_unix_s: int) -> bool:
    """V3.2 hour blocklist gate. Returns False if current UTC hour is in
    V3_2_HOUR_BLOCKLIST_UTC ({1, 16, 22}).

    When ``V3_2_HOUR_BLOCK_ENABLED=false``, always returns True.

    Pure helper exported for tests.
    """
    if not _v3p_flag("V3_2_HOUR_BLOCK_ENABLED"):
        return True
    h = datetime.fromtimestamp(now_unix_s, tz=UTC).hour
    return h not in V3_2_HOUR_BLOCKLIST_UTC


def v3_2_macro_2of3_passes(symbol: str, ret_5m: float, ret_15m: float, ret_1h: float) -> bool:
    """V3.2 macro 2-of-3 alignment. At least 1 of (15m, 1h) must agree
    with 5m sign for the signal to pass. SOL is exempted — multi-horizon
    quantile selector already enforces 3-of-3 alignment so this gate would
    be redundant.

    When ``V3_2_MACRO_2OF3_ENABLED=false``, always returns True.

    Pure helper exported for tests.
    """
    if not _v3p_flag("V3_2_MACRO_2OF3_ENABLED"):
        return True
    if symbol.upper() == "SOL":
        return True
    sign5 = 1 if ret_5m > 0 else (-1 if ret_5m < 0 else 0)
    if sign5 == 0:
        return False
    agree = 0
    if (sign5 * ret_15m) > 0:
        agree += 1
    if (sign5 * ret_1h) > 0:
        agree += 1
    return agree >= 1


def v3_2_liq_quiet_passes(symbol: str, liq_db: Any) -> bool:
    """V3.2 liquidity-quiet gate. Returns False if recent 5-min liq
    notional > V3_2_LIQ_QUIET_THRESHOLD_USD.

    FAIL-OPEN: any exception from ``liq_db.recent_liq_notional`` (DB
    unreachable, timeout, ``liq_db is None``) returns True so signal
    proceeds. Don't block trading on infra hiccup.

    DEFAULT-DISABLED 2026-05-01: V3_2_LIQ_QUIET_ENABLED defaults to
    "false" since VPS3 has no working realtime liquidation feed yet
    (operator pursuing alternate path; HL collector deferred). Until
    the feed lands, this gate is a no-op (returns True). Operator
    flips env var to "true" once liq data is available.

    Pure helper exported for tests.
    """
    # Phase 18.2 default-disable until liq feed is operational.
    if not _v3p_flag("V3_2_LIQ_QUIET_ENABLED", default="false"):
        return True
    try:
        total_5m = liq_db.recent_liq_notional(symbol, lookback_sec=300)
    except Exception:  # noqa: BLE001  intentional fail-open per D-05
        return True
    return total_5m <= V3_2_LIQ_QUIET_THRESHOLD_USD


def _v3_quantile_for(symbol: str, tf: str) -> float | None:
    """V3 per-asset magnitude quantile, or None when V3 doesn't apply.

    Pure helper exported for tests.
    """
    return V3_PER_ASSET_QUANTILE.get((symbol.upper(), tf))


def _spread_pct(book: dict) -> float | None:
    """Compute ``(best_ask − best_bid) / mid`` from a CLOB book dict.

    Returns None if either side is empty / malformed / inverted (ask ≤ bid).
    Pure helper exported for tests.
    """
    if not isinstance(book, dict):
        return None
    bids = book.get("bids") or []
    asks = book.get("asks") or []
    if not bids or not asks:
        return None
    if not isinstance(bids[0], dict) or not isinstance(asks[0], dict):
        return None
    try:
        bid = Decimal(str(bids[0].get("price", "0")))
        ask = Decimal(str(asks[0].get("price", "0")))
    except (TypeError, KeyError, ValueError, InvalidOperation):
        return None
    if bid <= 0 or ask <= 0 or ask <= bid:
        return None
    mid = (bid + ask) / Decimal("2")
    if mid <= 0:
        return None
    return float((ask - bid) / mid)


class SizingOverrideForbidden(ValueError):
    """Raised when constructor is given a notional override (D-04)."""


# Phase 26.3 D-03: hard sanity cap on the live-mirror notional override.
# Operator-locked $1 ceiling — catches typo overrides (e.g. ``30`` for
# ``0.30``) at controller construction time before any signing key is
# touched. Grep-verifiable literal per Phase 26.3-01 D-03 critical
# invariant.
LIVE_MIRROR_MAX_NOTIONAL = Decimal("1.00")


@dataclass
class Slot:
    """Tracking state for one open Polymarket updown position.

    A new Slot is created on every successful entry; it lives until the
    market resolves on-chain and the resolution path emits PnL. ``status``
    transitions are atomic per slot:

    - ``open`` — entry placed, no hedge yet.
    - ``hedged_holding`` — both legs held; waiting for natural resolution.
    - ``held_no_hedge`` — reversal triggered but the opposite-side book
      was empty; rides to resolution unhedged. (RESEARCH §7)
    - ``hedge_failed_held`` — reversal triggered, hedge order rejected
      after 3 retries. Operator-alerted; rides unhedged. (RESEARCH §7)
    - ``resolved`` — terminal; PnL emitted.
    """

    sleeve_id: str
    symbol: str
    tf: str
    condition_id: str
    signal: Literal["UP", "DOWN"]
    entry_price: Decimal
    entry_qty: Decimal
    btc_close_at_ws: Decimal
    binance_symbol_id: str
    yes_token_id: int | None = None
    no_token_id: int | None = None
    hedge_other_entry_price: Decimal | None = None
    status: Literal[
        "open",
        "hedged_holding",
        "held_no_hedge",
        "hedge_failed_held",
        # Phase 18.2 V2 HYBRID terminal states:
        "exited_at_bid",  # branch 2 succeeded — sold own side at bid.
        "held_no_hedge_no_exit",  # branch 3 — both buy-opp and sell-bid failed.
        "resolved",
    ] = "open"
    # Idempotency key per RESEARCH §7: same window_start_unix can't fire twice.
    window_start_unix: int = 0
    slot_id: str = field(default="")
    # Phase 18.2 V2: cost + exit accounting fields. All None on V1 codepath
    # (HEDGE_POLICY=HEDGE_HOLD); populated by V2 HYBRID path.
    entry_cost_usd: Decimal | None = None  # USD spent on entry leg.
    hedge_qty: Decimal | None = None  # shares acquired on hedge leg.
    hedge_cost_usd: Decimal | None = None  # USD spent on hedge leg.
    exit_price: Decimal | None = None  # bid price hit on bid-exit.
    exit_shares: Decimal | None = None  # shares sold on bid-exit.
    exit_proceeds_usd: Decimal | None = None  # USD received on bid-exit.


class PolymarketUpdownController:
    """Sleeve controller for 6 Polymarket binary updown slots.

    Args:
        pool: asyncpg pool (read-only via tradingvenue_ro).
        executor: PolyPaperExecutor (mode=paper) or PolymarketClient (mode=live).
        mode: "paper" or "live".
        notional_usd: MUST be omitted or equal $25; any override raises.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        executor: Any,
        mode: Mode,
        *,
        notional_usd: Decimal | None = None,
        # Phase 18.5 — per-controller hedge_policy override. Default None
        # falls back to module-env HEDGE_POLICY (preserves all 35 existing
        # sleeves' behavior). Momo controllers explicitly pass one of
        # HOLD_ONLY / HEDGE_HOLD / SELL_BID.
        hedge_policy: Literal[
            "HEDGE_HOLD", "HYBRID", "HOLD_ONLY", "SELL_BID"
        ] | None = None,
        strategy_mode: Literal[
            "volume",
            "sniper",
            "v3",
            "v3_1",
            "v3_2",
            "v3_3",
            "v4",
            "momo",
            "inverse_volume_night",
            "inverse_sol_sniper",
            "inverse_sniper_down",
        ] = "volume",
        liq_db: Any | None = None,
        # Phase 18.6 W1 — TV-native WS BookMirror for sub/unsub at slot
        # lifecycle. None preserves W0 behavior (no mirror; executor's
        # 3-tier dispatcher falls through to CLOB then Storedata). When
        # set, _place_entry subscribes BOTH legs (yes + no) at slot open
        # so HEDGE on the opposite-side has a hot mirror at decision time;
        # _prune_resolved_slots unsubscribes at slot GC.
        book_mirror: Any | None = None,
        # Phase 26-03 (D-01/D-05/D-06) — TV-native Polymarket data sources
        # for LIVE-mode controllers. Both default None so existing
        # paper-only deployments construct unchanged; live-mode controllers
        # configured in Phase 26.3 inject populated instances. The
        # `_get_market_meta` and `_get_resolution` shims branch on
        # `self.mode == 'live'` and consult these; paper mode keeps reading
        # Storedata via the extracted helpers.
        gamma_client: GammaClient | None = None,
        oracle: OnchainOracle | None = None,
        # Phase 26.3 D-03 — live-mirror micro-sizing override. When set
        # (non-None), this controller is a LIVE MIRROR twin: it overrides
        # the D-04 $25 paper notional with the operator-supplied micro
        # amount and tags every audit row with a ``_LIVE`` sleeve_id
        # suffix (D-02). Hard sanity capped at LIVE_MIRROR_MAX_NOTIONAL
        # = $1 to catch typos like ``30`` instead of ``0.30``. When None
        # (default), controller behaves as a paper sleeve with the
        # original D-04 $25 contract preserved byte-identical.
        live_mirror_notional: Decimal | None = None,
        # Phase 27 LIVE-DISC-02 — TV-native PolyMarketDiscovery service
        # injected by engine/_preflight.py for live-mirror controllers.
        # When ``mode == "live"`` this MUST be a PolyMarketDiscovery
        # instance (ctor raises ValueError otherwise). Paper-mode keeps
        # ``discovery=None`` and continues using ``_read_storedata_market_meta``
        # for byte-identical regression invariant.
        discovery: "PolyMarketDiscovery | None" = None,
        # 2026-05-16 — per-slot allowlist for live mirrors. When set,
        # ``on_bar_close`` skips any (sym, tf) not in this frozenset BEFORE
        # any strategy lookup / signal compute / order placement.
        # Necessary because ``_spawn_live_mirrors`` dedupes by
        # (strategy_mode, hedge_policy) so one controller manages all
        # BTC/ETH/SOL × 5m/15m slots — without this filter, allowlisting
        # ``btc_15m_momo_HOLD`` would also fire SOL/ETH and 5m slots
        # (the bug observed 2026-05-15). Paper controllers default to
        # ``None`` and keep firing all 6 slots (unchanged behavior).
        slot_allowlist: "frozenset[tuple[str, str]] | None" = None,
    ) -> None:
        # Phase 26.3 D-03 — live-mirror notional override path. Validated
        # BEFORE the existing D-04 paper-only check so paper-mode callers
        # with no override still hit the original code path unchanged.
        if live_mirror_notional is not None:
            if not (Decimal("0") < live_mirror_notional <= LIVE_MIRROR_MAX_NOTIONAL):
                raise SizingOverrideForbidden(
                    f"live_mirror_notional={live_mirror_notional} outside "
                    f"(0, {LIVE_MIRROR_MAX_NOTIONAL}]"
                )
            self._is_live_mirror = True
            # Defer `self.notional_usd` assignment past the D-04 paper
            # gate (live override is incompatible with the legacy
            # notional_usd kwarg; reject the combination loudly).
            if notional_usd is not None:
                raise SizingOverrideForbidden(
                    "live_mirror_notional and notional_usd cannot both be set"
                )
        else:
            self._is_live_mirror = False
        if notional_usd is not None and notional_usd != NOTIONAL_PER_SLOT_USD:
            raise SizingOverrideForbidden(
                f"D-04: $25/slot is hard-coded; got override={notional_usd}"
            )
        if mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper'|'live', got {mode!r}")
        # Phase 18.4 — inverse modes added. Engine main.py only registers
        # them under TV_INVERSE_SLEEVES_ENABLED=true; the validation list
        # here permits explicit construction so unit tests + the gated
        # registration path can instantiate them.
        _valid_strategy_modes = (
            "volume",
            "sniper",
            "v3",
            "v3_1",
            "v3_2",
            "v3_3",
            "v4",
            "momo",
            "momo_v2",
            "inverse_volume_night",
            "inverse_sol_sniper",
            "inverse_sniper_down",
        )
        if strategy_mode not in _valid_strategy_modes:
            raise ValueError(
                f"strategy_mode must be one of {_valid_strategy_modes}, got {strategy_mode!r}"
            )

        self.pool = pool
        self.executor = executor
        self.mode: Mode = mode
        # 2026-05-16 — see kwarg docstring. Normalize to frozenset of
        # (UPPER_SYM, lower_tf) tuples so callers can pass either form.
        if slot_allowlist is not None:
            self._slot_allowlist = frozenset(
                (str(s).upper(), str(t).lower()) for s, t in slot_allowlist
            )
        else:
            self._slot_allowlist = None
        # Phase 27 LIVE-DISC-02 — TV-native discovery service consumer.
        # Defensive: live mode MUST have a discovery instance (engine/_preflight
        # injects it). Paper mode keeps discovery=None and falls through to the
        # legacy Storedata `_read_storedata_market_meta` path unchanged.
        self._discovery = discovery
        if self.mode == "live" and self._discovery is None:
            raise ValueError(
                "PolymarketUpdownController(mode='live') requires "
                "discovery=PolyMarketDiscovery instance (LIVE-DISC-02)"
            )
        # Phase 26.3 D-03 — live-mirror controllers override the $25
        # default with the validated micro-notional from the kwarg.
        # Paper controllers keep the byte-identical D-04 contract.
        self.notional_usd: Decimal = (
            live_mirror_notional
            if (self._is_live_mirror and live_mirror_notional is not None)
            else NOTIONAL_PER_SLOT_USD
        )
        # Phase 18.2 V2 + V3: which strategy mode this controller represents.
        # 'volume' (default, V1) — every signal fires.
        # 'sniper' (V2)          — only fires when |ret_5m| clears the
        #                          rolling 14d q90/q80 threshold.
        # 'v3'                   — sniper-style threshold + per-asset
        #                          quantile (BTC q90 / ETH q95 / SOL q85),
        #                          5m only, multi-horizon AND filter on
        #                          SOL, spread filter, audited under
        #                          sleeve_id `..._v3`.
        # Engine main.py iterates TV_POLY_STRATEGY_MODES and constructs
        # one controller per mode listed; modes run in parallel against
        # distinct sleeve_ids to avoid double-fill on the same market.
        #
        # Phase 18.2 V3 patches (D-11 — no-touch v3):
        # 'v3_1'                 — V3 + asymmetric per-direction quantile
        #                          (ETH/SOL UP tighter than DOWN) + soft
        #                          regime overlay (±0.5% on ret_1h) + SOL
        #                          UP live-disable (paper-only).
        # 'v3_2'                 — V3 + hour blocklist {1,16,22 UTC} +
        #                          macro 2-of-3 + liq-quiet gate
        #                          (<$10k Binance liq notional).
        # 'v4'                   — v3_1 + v3_2 stacked (per SPEC §V4 order).
        # All three reuse v3's spread-filter + 5m-only constraint via
        # parallel branches that COPY the v3 logic verbatim — v3 itself
        # is untouched.
        #
        # Phase 18.3 (SOL_V3_FIX_SPEC_2026_05_04 — V3.3 A/B sleeve):
        # 'v3_3'                 — IDENTICAL to v3_2 EXCEPT adds
        #                          multi-horizon AND filter for SOL only.
        #                          Used as A/B test against v3_2 SOL to
        #                          decide whether multi-horizon adds
        #                          quality or just culls trades. BTC/ETH
        #                          v3_3 are control samples (should match
        #                          v3_2 BTC/ETH exactly).
        self.strategy_mode: Literal[
            "volume",
            "sniper",
            "v3",
            "v3_1",
            "v3_2",
            "v3_3",
            "v4",
            "momo",
            "momo_v2",
            "inverse_volume_night",
            "inverse_sol_sniper",
            "inverse_sniper_down",
        ] = strategy_mode

        # 2026-05-20 F7 RSI filter mode (see TV_AGENT_F7_RSI_FILTER_SPEC.md).
        # Active on momo + momo_v2 — the cells F7 was validated against
        # (+$846/day shadow PnL, 0/12 cells regress). All other strategies
        # stay "off" (untested for F7). The sleeve_id construction below
        # appends ``_f7`` when this is non-"off" so post-F7 history is
        # bucketed cleanly against the pre-F7 archive snapshot.
        # Env override: ``TV_POLY_F7_FILTER_MODE`` = "off"|"basic"|"extreme"
        # forces a mode across ALL momo controllers (useful for ops).
        _f7_env = os.getenv("TV_POLY_F7_FILTER_MODE", "").strip().lower()
        if _f7_env in ("off", "basic", "extreme"):
            self._f7_filter_mode: Literal["off", "basic", "extreme"] = _f7_env  # type: ignore[assignment]
        elif strategy_mode in ("momo", "momo_v2"):
            self._f7_filter_mode = "basic"
        else:
            self._f7_filter_mode = "off"
        # Suffix appended to every sleeve_id when F7 is active. Empty
        # string when off — preserves byte-identical sleeve_ids for
        # baselines / non-momo strategies.
        self._f7_suffix: str = "_f7" if self._f7_filter_mode != "off" else ""

        # Phase 18.5 — resolve effective hedge_policy. Per-controller arg
        # wins; otherwise fall back to module env (legacy behavior). Validate
        # against the same set as the env. Momo callers explicitly pass
        # one of HOLD_ONLY/HEDGE_HOLD/SELL_BID; non-momo callers leave it
        # None and behavior matches pre-Phase-18.5 exactly.
        _effective_hp = (hedge_policy or HEDGE_POLICY).upper()
        if _effective_hp not in _VALID_HEDGE_POLICIES:
            raise ValueError(
                f"hedge_policy={_effective_hp!r} invalid; "
                f"expected one of {_VALID_HEDGE_POLICIES}"
            )
        self.hedge_policy: str = _effective_hp
        # Phase 18.2 — liq_db handle for V3.2 / V4 liq_quiet gate. Set to
        # None when the gate is disabled or LiqDB.init_pool failed in
        # tv-engine lifespan (fail-open per D-05). The v3_2_liq_quiet_passes
        # helper handles None via Exception catch (returns True =>
        # signal proceeds). The on_bar_close v3p gate stack already calls
        # getattr(self, "liq_db", None) defensively, so attribute presence
        # alone is sufficient — value can be None.
        self.liq_db: Any | None = liq_db
        # Phase 18.6 W1 — BookMirror handle for slot-lifecycle sub/unsub.
        self._book_mirror: Any | None = book_mirror
        # Phase 26-03 (D-05/D-06) — TV-native Polymarket data sources for
        # LIVE mode. Both None for paper-only deployments; live controllers
        # in Phase 26.3 inject populated instances.
        self._gamma_client: GammaClient | None = gamma_client
        self._oracle: OnchainOracle | None = oracle
        # Strategy classes only know "volume" vs "sniper". V3 is a sniper
        # variant from the strategy's perspective (threshold-gated); the
        # per-asset quantile + multi-horizon filter live in the controller
        # via _fetch_or_compute_threshold + aux building.
        _strategy_class_mode: Literal["volume", "sniper"] = (
            "sniper" if strategy_mode in ("sniper", "v3") else "volume"
        )
        # Phase 18.2 — V3 patch variants are sniper-style (threshold-gated).
        # Separate clause keeps the v3 line above byte-identical (D-11).
        # Phase 18.3 — v3_3 (V3.2 + multi-horizon for SOL) is also sniper-style.
        if strategy_mode in ("v3_1", "v3_2", "v3_3", "v4"):
            _strategy_class_mode = "sniper"
        # Phase 18.4 — Inverse sleeves wrap a base mode ("volume" or
        # "sniper") and apply a flip+filter rule. _inverse_kind drives:
        #   - _strategy_class_mode (so the underlying strategy fires
        #     with the same signal logic as the wrapped base mode)
        #   - apply_inverse_filter() call after strategy.signal() in
        #     on_bar_close (flips + applies window/symbol/direction
        #     filters)
        #   - _sleeve_id() override (fixed inverse suffix per Q4)
        #   - _maybe_hedge() no-op guard (Q5 hard-skip)
        #   - audit-row enrichment (base_signal + inverse_reason)
        # _inverse_kind is None for non-inverse modes — every inverse
        # branch in this controller checks it before doing anything,
        # so non-inverse behavior is byte-identical when this attr is
        # None.
        self._inverse_kind: InverseKind | None = (
            strategy_mode  # type: ignore[assignment]
            if strategy_mode in INVERSE_KINDS
            else None
        )
        if self._inverse_kind is not None:
            _strategy_class_mode = INVERSE_BASE_MODE[self._inverse_kind]
        # Phase 18.4 — set during on_bar_close so audit rows for inverse
        # sleeves can attach the pre-flip ``base_signal`` field. Only
        # consumed when self._inverse_kind is not None. None for
        # non-inverse controllers — never read.
        self._last_base_signal: SignalResult | None = None
        # 6-slot strategy registry: (symbol, tf) -> strategy instance.
        # V3 only uses 5m, but we keep 15m strategy instances so volume/
        # sniper modes keep working — V3-specific 15m skip is enforced
        # in on_bar_close, not here.
        self._strategies: dict[tuple[str, str], PolymarketBinaryStrategy] = {}
        # Phase 18.5 — momo controllers use MomoStrategy (gate on aux['ret_2m']
        # at t+120s phase). Strategy is timeframe-agnostic (same body for 5m
        # and 15m); the t+120s threshold is precomputed in the BarContext.
        if strategy_mode == "momo":
            from backend.app.strategies.polymarket import MomoStrategy
            for sym in SUPPORTED_SYMBOLS:
                self._strategies[(sym, "5m")] = MomoStrategy()
                self._strategies[(sym, "15m")] = MomoStrategy()
        elif strategy_mode == "momo_v2":
            # Phase 18.5+ — momo_v2 fires at t+60s on a (ws-60, ws+60)
            # ret_2m anchor. Coexists with v1 momo (both 18 sleeves run
            # side-by-side per spec §0).
            from backend.app.strategies.polymarket import MomoV2Strategy
            for sym in SUPPORTED_SYMBOLS:
                self._strategies[(sym, "5m")] = MomoV2Strategy()
                self._strategies[(sym, "15m")] = MomoV2Strategy()
        else:
            for sym in SUPPORTED_SYMBOLS:
                self._strategies[(sym, "5m")] = Updown5mStrategy(mode=_strategy_class_mode)
                self._strategies[(sym, "15m")] = Updown15mStrategy(mode=_strategy_class_mode)

        # Phase 18.1: timeframe-specific quantile threshold cache.
        # Key is (symbol, tf, day_unix) so 5m and 15m get separate cached
        # thresholds even on the same day. Value is:
        #   - float                         — single threshold (v1/v2/v3/v3_2)
        #   - tuple[float, float]           — (UP, DOWN) directional thresholds
        #                                     (v3_1/v4 asymmetric quantile)
        #   - None                          — cold start (insufficient samples)
        self._threshold_cache: dict[tuple[str, str, int], float | tuple[float, float] | None] = {}

        # Phase 18.1: open slots tracked per (symbol, tf, window_start_unix)
        # for idempotency (RESEARCH §7).
        self._slots: dict[tuple[str, str, int], Slot] = {}

        # Phase 24: per-call shared BarContext set by the master scheduler
        # before each on_bar_close invocation, cleared after. Helpers
        # (_build_signal_aux, _fetch_or_compute_threshold, cid + book
        # blocks inside _on_bar_close_impl) read this via the
        # ``_bar_ctx_active`` property below, which is backed by the
        # module-level ``_BAR_CTX_ACTIVE`` ContextVar so concurrent
        # asyncio tasks on the same controller instance don't clobber
        # each other (Phase 18.5 race fix).

    # ------------------------------------------------------------------
    # Phase 18.5 race fix — task-isolated _bar_ctx_active.
    # ------------------------------------------------------------------
    # Property keeps the existing read API (``self._bar_ctx_active``)
    # used by 8 internal sites + tests. The setter writes through to the
    # module-level ContextVar, so concurrent asyncio tasks on the same
    # controller instance get their own view (no cross-symbol clobber).

    @property
    def _bar_ctx_active(self) -> Any:
        return _BAR_CTX_ACTIVE.get()

    @_bar_ctx_active.setter
    def _bar_ctx_active(self, value: Any) -> None:
        # Token-less set; the on_bar_close wrapper uses an explicit
        # token-based set/reset for proper scoping. This setter exists
        # for legacy callers that assign directly (e.g. tests).
        _BAR_CTX_ACTIVE.set(value)

    # ------------------------------------------------------------------
    # BarEngine subscription
    # ------------------------------------------------------------------

    def slots(self) -> list[tuple[str, str]]:
        """Return the 6 (symbol, tf) slots this controller subscribes to."""
        return list(self._strategies.keys())

    def register_hl_controller(self, bar_engine: Any) -> None:
        """Subscribe to BTC/ETH/SOL × 5m/15m bar-close events.

        BarEngine integration: each (symbol, tf) slot routes its bar-close
        event into ``on_bar_close``. The exact subscription mechanism is
        BarEngine-specific (Phase 7.1).
        """
        for sym, tf in self.slots():
            bar_engine.subscribe(symbol=sym, tf=tf, handler=self.on_bar_close)

    # ------------------------------------------------------------------
    # Phase 18.1 — auxiliary signal context (Binance closes + threshold)
    # ------------------------------------------------------------------

    async def _build_signal_aux(self, symbol: str, tf: str, window_start_us: int) -> dict[str, Any]:
        """Pre-fetch Binance closes + sniper threshold for ``strategy.signal``.

        Returns a dict matching RESEARCH §3.1 schema. Never raises — on any
        DB miss / data gap, the affected key is ``None`` and the strategy
        will return ``"NONE"``.

        Args:
            symbol: TV symbol ("BTC" | "ETH" | "SOL").
            tf: Strategy timeframe ("5m" | "15m"). Determines the quantile
                used in the sniper threshold (q90 on 5m, q80 on 15m).
            window_start_us: Market window_start in microseconds (the
                strategy's prediction-window opening boundary).
        """
        sym_upper = symbol.upper()
        symbol_id = BINANCE_SYMBOL_ID_MAP.get(sym_upper)
        if symbol_id is None:
            return {
                "binance_close_at_ws": None,
                "binance_close_5m_before": None,
                "ret_5m": None,
                "abs_ret_5m_threshold": None,
            }

        ws_s = int(window_start_us) // 1_000_000

        # Phase 18.5 — momo controllers consume a different aux shape (ret_2m
        # at t+120s, q90 |ret_2m| threshold). When the strategy_mode is "momo"
        # AND the master scheduler handed us a t+120s BarContext, populate the
        # momo-specific aux from the BarContext's pre-computed fields. On any
        # other phase (including bar_close fired by accident), aux carries
        # ``bar_ctx_phase != "t_plus_120"`` and MomoStrategy returns NONE.
        _bar_ctx_pre = self._bar_ctx_active
        if self.strategy_mode == "momo":
            ctx_phase = (
                getattr(_bar_ctx_pre, "phase", "bar_close")
                if _bar_ctx_pre is not None
                else "bar_close"
            )
            if (
                _bar_ctx_pre is not None
                and ctx_phase == "t_plus_120"
                and getattr(_bar_ctx_pre, "symbol", None) == sym_upper
                and getattr(_bar_ctx_pre, "tf", None) == tf
            ):
                btc_at_ws = _bar_ctx_pre.btc_now
                btc_at_120 = _bar_ctx_pre.btc_at_t_plus_120
                ret_2m: float | None = None
                if (
                    btc_at_ws is not None
                    and btc_at_120 is not None
                    and float(btc_at_ws) > 0
                ):
                    ret_2m = math.log(float(btc_at_120) / float(btc_at_ws))
                return {
                    "bar_ctx_phase": "t_plus_120",
                    "ret_2m": ret_2m,
                    "abs_ret_2m_threshold": _bar_ctx_pre.abs_ret_2m_threshold,
                    # Useful provenance for the audit row enrichment downstream.
                    "binance_close_at_ws": btc_at_ws,
                    "binance_close_at_t_plus_120": btc_at_120,
                    # 2026-05-20 F7 RSI filter (TV_AGENT_F7_RSI_FILTER_SPEC).
                    # Always emitted; strategy reads + applies its mode.
                    "rsi_14": _bar_ctx_pre.rsi_14_for_signal,
                    "f7_filter_mode": self._f7_filter_mode,
                }
            # No t+120s BarContext (bar-close phase or missing) → empty aux,
            # strategy returns NONE, no entry.
            return {
                "bar_ctx_phase": ctx_phase,
                "ret_2m": None,
                "abs_ret_2m_threshold": None,
                "rsi_14": None,
                "f7_filter_mode": self._f7_filter_mode,
            }

        # Phase 18.5+ — momo_v2 controllers consume aux derived from the
        # t_plus_60 BarContext (anchor on (ws-60, ws+60) instead of
        # (ws, ws+120)). Mirror of the momo branch above with the v2
        # phase string + v2 anchor fields.
        if self.strategy_mode == "momo_v2":
            ctx_phase = (
                getattr(_bar_ctx_pre, "phase", "bar_close")
                if _bar_ctx_pre is not None
                else "bar_close"
            )
            if (
                _bar_ctx_pre is not None
                and ctx_phase == "t_plus_60"
                and getattr(_bar_ctx_pre, "symbol", None) == sym_upper
                and getattr(_bar_ctx_pre, "tf", None) == tf
            ):
                btc_at_ws_minus_60 = _bar_ctx_pre.btc_close_at_ws_minus_60
                btc_at_60 = _bar_ctx_pre.btc_at_t_plus_60
                # btc_at_ws populated by build_bar_context_t_plus_60
                # (BTC@ws — the bar-close anchor). Required for slot
                # construction (slot.btc_close_at_ws drives on_tick's
                # rev_bp computation in _maybe_hedge / _maybe_sell_at_bid).
                # Bug fix 2026-05-07: missing this caused ALL v2 HEDGE/
                # SELL on_tick exits to silent-skip via the
                # `if slot.btc_close_at_ws == 0: return` early-out.
                btc_at_ws = _bar_ctx_pre.btc_now
                ret_2m: float | None = None
                if (
                    btc_at_ws_minus_60 is not None
                    and btc_at_60 is not None
                    and float(btc_at_ws_minus_60) > 0
                ):
                    ret_2m = math.log(
                        float(btc_at_60) / float(btc_at_ws_minus_60)
                    )
                return {
                    "bar_ctx_phase": "t_plus_60",
                    "ret_2m": ret_2m,
                    "abs_ret_2m_threshold": _bar_ctx_pre.abs_ret_2m_threshold,
                    # Slot-construction handle: line ~2099 reads
                    # aux.get("binance_close_at_ws") and stores it as
                    # slot.btc_close_at_ws. This is the rev_bp anchor
                    # that on_tick compares against — same convention
                    # as v1 momo per spec §4e.
                    "binance_close_at_ws": btc_at_ws,
                    # Provenance for audit-row enrichment downstream.
                    "binance_close_at_ws_minus_60": btc_at_ws_minus_60,
                    "binance_close_at_t_plus_60": btc_at_60,
                    # 2026-05-20 F7 RSI filter
                    "rsi_14": _bar_ctx_pre.rsi_14_for_signal,
                    "f7_filter_mode": self._f7_filter_mode,
                }
            # No t_plus_60 BarContext (wrong phase or missing) → strategy
            # returns NONE, no entry.
            return {
                "bar_ctx_phase": ctx_phase,
                "ret_2m": None,
                "abs_ret_2m_threshold": None,
                "rsi_14": None,
                "f7_filter_mode": self._f7_filter_mode,
            }

        # Phase 24: when the master scheduler provided a shared BarContext,
        # use the cached kline closes instead of re-fetching. Eliminates the
        # cross-controller race documented in V4-SUBSET-BUG-VERDICT-2026-05-05.
        _bar_ctx = self._bar_ctx_active
        if (
            _bar_ctx is not None
            and getattr(_bar_ctx, "symbol", None) == sym_upper
            and getattr(_bar_ctx, "tf", None) == tf
        ):
            btc_now = _bar_ctx.btc_now
            btc_prior = _bar_ctx.btc_prior
        else:
            # Two 1MIN closes: at-or-before window_start, and at-or-before
            # window_start - 300s. The 300s offset is a fixed ret_5m base —
            # same for 5m and 15m markets per RESEARCH §1.
            try:
                btc_now = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s, pool=self.pool, source=KLINE_SOURCE
                )
                btc_prior = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s - 300, pool=self.pool, source=KLINE_SOURCE
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "poly_updown.binance_close_fetch_failed",
                    extra={"symbol": symbol, "tf": tf, "ws_s": ws_s},
                )
                btc_now = None
                btc_prior = None

        ret_5m: float | None = None
        if btc_now is not None and btc_prior is not None and btc_prior > 0:
            ret_5m = math.log(float(btc_now) / float(btc_prior))

        abs_ret_5m_threshold = await self._fetch_or_compute_threshold(sym_upper, tf, ws_s)

        # Phase 18.2 D-11: v3_1/v4 may return a (UP, DOWN) tuple. Unpack into
        # directional aux keys; the legacy abs_ret_5m_threshold key is set to
        # None in that case so the strategy class skips the symmetric path
        # and uses the directional keys instead. v1/v2/v3/v3_2 keep the
        # single-float behavior (untouched).
        threshold_up: float | None = None
        threshold_down: float | None = None
        legacy_threshold: float | None = None
        if isinstance(abs_ret_5m_threshold, tuple):
            threshold_up, threshold_down = abs_ret_5m_threshold
        elif abs_ret_5m_threshold is None:
            legacy_threshold = None
        else:
            legacy_threshold = float(abs_ret_5m_threshold)

        aux: dict[str, Any] = {
            "binance_close_at_ws": btc_now,
            "binance_close_5m_before": btc_prior,
            "ret_5m": ret_5m,
            "abs_ret_5m_threshold": legacy_threshold,
            "abs_ret_5m_threshold_up": threshold_up,
            "abs_ret_5m_threshold_down": threshold_down,
        }

        # V3 multi-horizon AND filter: SOL only. Strategy needs ret_15m and
        # ret_1h alongside ret_5m to gate that all three agree on direction.
        # Per V3 deploy guide §1.3: log-returns from same Binance 1MIN feed
        # at ws_s − 900s (15m) and ws_s − 3600s (1h).
        if self.strategy_mode == "v3" and (sym_upper, tf) in V3_REQUIRE_MULTI_HORIZON:
            # Phase 24: read from shared BarContext when present.
            if (
                _bar_ctx is not None
                and getattr(_bar_ctx, "symbol", None) == sym_upper
                and getattr(_bar_ctx, "tf", None) == tf
            ):
                btc_15m_prior = _bar_ctx.btc_15m_prior
                btc_1h_prior = _bar_ctx.btc_1h_prior
            else:
                try:
                    btc_15m_prior = await fetch_close_asof(
                        symbol_id, "1MIN", ws_s - 900, pool=self.pool, source=KLINE_SOURCE
                    )
                    btc_1h_prior = await fetch_close_asof(
                        symbol_id, "1MIN", ws_s - 3600, pool=self.pool, source=KLINE_SOURCE
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "poly_updown.v3_multi_horizon_fetch_failed",
                        extra={"symbol": symbol, "tf": tf, "ws_s": ws_s},
                    )
                    btc_15m_prior = None
                    btc_1h_prior = None

            ret_15m: float | None = None
            if btc_now is not None and btc_15m_prior is not None and btc_15m_prior > 0:
                ret_15m = math.log(float(btc_now) / float(btc_15m_prior))
            ret_1h: float | None = None
            if btc_now is not None and btc_1h_prior is not None and btc_1h_prior > 0:
                ret_1h = math.log(float(btc_now) / float(btc_1h_prior))

            aux["ret_15m"] = ret_15m
            aux["ret_1h"] = ret_1h
            aux["require_multi_horizon"] = True

        # Phase 18.2 D-11 — parallel multi-horizon fetch for v3_1/v3_2/v4.
        # Phase 18.3 — v3_3 joins the same fetch path (it's V3.2 + MH for SOL,
        # so it needs ret_15m/ret_1h for both macro_2of3 and the SOL MH-AND).
        # Reasons we need ret_15m / ret_1h for ALL symbols on these modes:
        #   - V3.1 regime overlay needs ret_1h (any symbol).
        #   - V3.2/V3.3 macro_2of3 needs ret_15m + ret_1h for non-SOL (SOL is
        #     skipped by the helper).
        #   - SOL multi-horizon AND filter (same as v3 above) for v3_1/v3_3/v4.
        # Idempotent w.r.t. the v3 block: if v3 already populated these keys
        # for SOL, we re-overwrite with the same values — no behavior change.
        if self.strategy_mode in ("v3_1", "v3_2", "v3_3", "v4"):
            # Phase 24: read from shared BarContext when present.
            if (
                _bar_ctx is not None
                and getattr(_bar_ctx, "symbol", None) == sym_upper
                and getattr(_bar_ctx, "tf", None) == tf
            ):
                btc_15m_prior_v3p = _bar_ctx.btc_15m_prior
                btc_1h_prior_v3p = _bar_ctx.btc_1h_prior
            else:
                try:
                    btc_15m_prior_v3p = await fetch_close_asof(
                        symbol_id, "1MIN", ws_s - 900, pool=self.pool, source=KLINE_SOURCE
                    )
                    btc_1h_prior_v3p = await fetch_close_asof(
                        symbol_id, "1MIN", ws_s - 3600, pool=self.pool, source=KLINE_SOURCE
                    )
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "poly_updown.v3p_multi_horizon_fetch_failed",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "ws_s": ws_s,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    btc_15m_prior_v3p = None
                    btc_1h_prior_v3p = None

            ret_15m_v3p: float | None = None
            if btc_now is not None and btc_15m_prior_v3p is not None and btc_15m_prior_v3p > 0:
                ret_15m_v3p = math.log(float(btc_now) / float(btc_15m_prior_v3p))
            ret_1h_v3p: float | None = None
            if btc_now is not None and btc_1h_prior_v3p is not None and btc_1h_prior_v3p > 0:
                ret_1h_v3p = math.log(float(btc_now) / float(btc_1h_prior_v3p))

            aux["ret_15m"] = ret_15m_v3p
            aux["ret_1h"] = ret_1h_v3p
            # SOL multi-horizon AND filter applies for v3_1 + v4 (same as v3).
            # v3_2 doesn't enforce multi-horizon (uses macro_2of3 instead, which
            # the helper internally skips for SOL).
            # Phase 18.3 — v3_3 IS V3.2 + multi-horizon for SOL (the A/B
            # difference). On BTC/ETH, v3_3 stays identical to v3_2 (sym not
            # in V3_REQUIRE_MULTI_HORIZON, so this branch is a no-op).
            if (
                self.strategy_mode in ("v3_1", "v3_3", "v4")
                and (sym_upper, tf) in V3_REQUIRE_MULTI_HORIZON
            ):
                aux["require_multi_horizon"] = True

        return aux

    async def _fetch_or_compute_threshold(
        self, symbol: str, tf: str, ws_s: int
    ) -> float | tuple[float, float] | None:
        """Rolling 14-day quantile of ``|ret_5m|`` for (symbol, tf).

        Quantile depends on ``self.strategy_mode``:
          - 'volume' / 'sniper' (V1/V2 baseline) — q=0.90 on 5m, q=0.80 on 15m
            (RESEARCH §3.3 + CONTEXT D-03).
          - 'v3' (per-asset tuned) — q from V3_PER_ASSET_QUANTILE lookup
            (BTC 0.90 / ETH 0.95 / SOL 0.85). Returns None for 15m in V3
            mode (V3 is 5m-only by design).
          - 'v3_2' (Phase 18.2) — reuses V3 base quantile (no asymmetry).
          - 'v3_1' / 'v4' (Phase 18.2 D-11) — direction-aware: returns
            ``tuple(thr_up, thr_down)`` computed at q from
            V3_1_PER_ASSET_QUANTILE per direction. Strategy class picks
            by direction at signal time. Returns single float when only
            one direction is configured (rare patch-config miss).

        Cache key includes ``self.strategy_mode`` so V2 sniper and V3
        thresholds don't collide when both run in parallel against the
        same (symbol, tf) day.

        Cold-start fallback: if fewer than ``SNIPER_MIN_SAMPLES`` samples
        are available in the lookback, return ``None``. The sniper-mode
        strategy will return ``"NONE"`` for that bar (and the parallel
        volume-mode sleeve still fires).
        """
        if tf not in ("5m", "15m"):
            return None
        cache_key = (symbol, tf, ws_s // 86_400)
        if cache_key in self._threshold_cache:
            return self._threshold_cache[cache_key]

        # V3: per-asset tuned quantile lookup; returns None if the cell isn't
        # in the V3 portfolio (15m or unknown symbol). V1/V2 fall back to
        # the timeframe-uniform q90/q80.
        # Phase 18.2 D-11 — v3_1/v4/v3_2 branches added BELOW the v3 branch
        # without modifying the v3 line itself.
        v3p_directional: tuple[float, float] | None = None
        if self.strategy_mode == "v3":
            v3_q = _v3_quantile_for(symbol, tf)
            if v3_q is None:
                self._threshold_cache[cache_key] = None
                return None
            quantile = v3_q
        elif self.strategy_mode in ("v3_1", "v4"):
            # Direction-aware quantile lookup. Compute BOTH UP and DOWN
            # thresholds against the same 14d sample set, store as tuple.
            # Patch-config miss for either direction => fall back to base
            # V3 single-threshold path (rare; mostly future symbols).
            q_up = v3_1_quantile_for(symbol, tf, "UP")
            q_down = v3_1_quantile_for(symbol, tf, "DOWN")
            if q_up is None and q_down is None:
                v3_q = _v3_quantile_for(symbol, tf)
                if v3_q is None:
                    self._threshold_cache[cache_key] = None
                    return None
                quantile = v3_q
            elif q_up is None or q_down is None:
                # Partial config — fall back to whichever side is set
                # (treat as symmetric on the missing side).
                quantile = q_up if q_up is not None else q_down
            else:
                # Both directions configured (the normal case for BTC/ETH/SOL).
                # Sentinel: signal to the post-fetch section below to compute
                # both quantiles and cache as tuple.
                quantile = q_up  # placeholder — used only if directional path errors
                v3p_directional = (q_up, q_down)
        elif self.strategy_mode in ("v3_2", "v3_3"):
            # V3.2 reuses V3 base quantile (no asymmetry).
            # Phase 18.3 — V3.3 uses the same quantile as V3.2 (it's V3.2 +
            # multi-horizon for SOL only; quantile path is identical).
            v3_q = _v3_quantile_for(symbol, tf)
            if v3_q is None:
                self._threshold_cache[cache_key] = None
                return None
            quantile = v3_q
        else:
            quantile = 0.90 if tf == "5m" else 0.80
        symbol_id = BINANCE_SYMBOL_ID_MAP.get(symbol)
        if symbol_id is None:
            self._threshold_cache[cache_key] = None
            return None

        # Phase 24: when master scheduler provided shared BarContext,
        # use the cached 14-day sample set (one DB fetch shared across
        # all controllers per (symbol, tf, day)) instead of re-fetching.
        _bar_ctx = self._bar_ctx_active
        samples: list[float] | tuple[float, ...]
        if (
            _bar_ctx is not None
            and getattr(_bar_ctx, "symbol", None) == symbol.upper()
            and getattr(_bar_ctx, "tf", None) == tf
            and len(getattr(_bar_ctx, "abs_ret_5m_samples", ())) > 0
        ):
            samples = _bar_ctx.abs_ret_5m_samples
        else:
            try:
                samples = await self._fetch_abs_ret_5m_history(
                    symbol_id=symbol_id,
                    tf=tf,
                    from_s=ws_s - SNIPER_LOOKBACK_DAYS * 86_400,
                    until_s=ws_s,
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "poly_updown.threshold_fetch_failed",
                    extra={"symbol": symbol, "tf": tf, "ws_s": ws_s},
                )
                self._threshold_cache[cache_key] = None
                return None

        if len(samples) < SNIPER_MIN_SAMPLES:
            self._threshold_cache[cache_key] = None
            return None

        # Phase 18.2 — directional path: compute both thresholds and cache
        # as tuple. Single-threshold path stays unchanged for v1/v2/v3/v3_2.
        if v3p_directional is not None:
            arr = np.array(samples, dtype=float)
            thr_up = float(np.quantile(arr, v3p_directional[0]))
            thr_down = float(np.quantile(arr, v3p_directional[1]))
            self._threshold_cache[cache_key] = (thr_up, thr_down)
            return (thr_up, thr_down)

        threshold = float(np.quantile(np.array(samples, dtype=float), quantile))
        self._threshold_cache[cache_key] = threshold
        return threshold

    async def _fetch_abs_ret_5m_history(
        self,
        *,
        symbol_id: str,
        tf: str,
        from_s: int,
        until_s: int,
    ) -> list[float]:
        """Pull |ret_5m| values for completed updown markets in the window.

        RESEARCH §3.3: "Pull |ret_5m| values from completed markets in the
        last 14 days for this (symbol, tf)."

        For each resolved market with an end_ts in (from_s, until_s] whose
        slug matches ``{symbol_lower}-updown-{tf}-*``, derive ret_5m at the
        market's window_start (which equals end_ts - tf_seconds for an
        updown market) and append ``abs(ret_5m)``.

        Implementation note: this is the v1 cold-start path — straightforward
        SQL + per-row asof closes. Cheap once per UTC day per (symbol, tf)
        because the daily cache key absorbs all repeats. For higher-volume
        v0.2, swap to a precomputed feature store.

        Phase 22.1 (CLAUDE.md inv #13): when TV-native feed is bound, samples
        come from in-memory rolling deque (sub-ms, no DB roundtrip). Tier-3
        SQL fallback if feed empty. Daily blackout eliminated.
        """
        # Phase 22.1: feed-first read path.
        if _bars_module._feed_native_enabled():
            tv_sym = _bars_module._SYMBOL_ID_TO_TV.get(symbol_id)
            if tv_sym is not None:
                samples = _bars_module._FEED_INSTANCE.get_ret_5m_samples(  # type: ignore[union-attr]
                    tv_sym, tf, until_s
                )
                if samples:
                    return list(samples)
                # Feed empty → fall through to SQL path (Tier-3).
                logger.warning(
                    "kline_feed.samples_empty_fallthrough",
                    symbol_id=symbol_id,
                    tf=tf,
                    until_s=until_s,
                    fn="_fetch_abs_ret_5m_history",
                )

        if self.pool is None:  # type: ignore[redundant-expr]
            return []

        sym_lower = symbol_id.split("_")[-2].lower()  # SPOT_BTC_USDT -> 'btc'
        slug_regex = f"^{sym_lower}-updown-{tf}-[0-9]+$"
        # TODO(26): not migrated to mode-routing — range scan, not a per-cid lookup
        # Phase 18.1 in-flight 2026-04-29 (VPS3 sniper-fix): the resolution
        # truth lives in `public.market_resolutions_v2.outcome`, NOT
        # `public.markets.result` (which Storedata's writer never populates
        # for Polymarket UpDown rows — verified 0/1473 with_result on VPS3).
        # The resolver uses the same source: see
        # `engine/poly_updown_resolver.py:_PENDING_RESOLUTIONS_SQL`.
        # Filtering on `outcome IN ('Up','Down')` excludes the rare
        # un-resolved/disputed cases. `recorded_at` is the resolution time;
        # since slug-epoch ≈ resolution time within seconds for UpDown
        # markets, filtering by slug epoch (cheaper) is fine.
        sql = (
            "SELECT substring(m.slug FROM '\\d+$')::bigint AS end_unix "
            "FROM public.markets m "
            "JOIN public.market_resolutions_v2 r ON r.slug = m.slug "
            "WHERE m.platform = 'polymarket' "
            "  AND m.slug ~ $1 "
            "  AND r.outcome IN ('Up', 'Down') "
            "  AND substring(m.slug FROM '\\d+$')::bigint > $2 "
            "  AND substring(m.slug FROM '\\d+$')::bigint <= $3 "
            "ORDER BY substring(m.slug FROM '\\d+$')::bigint ASC"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, slug_regex, int(from_s), int(until_s))

        # Translate window_start = end_ts - tf_seconds.
        tf_seconds = 5 * 60 if tf == "5m" else 15 * 60
        out: list[float] = []
        for r in rows:
            ws_s = int(r["end_unix"]) - tf_seconds
            try:
                btc_now = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s, pool=self.pool, source=KLINE_SOURCE
                )
                btc_prior = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s - 300, pool=self.pool, source=KLINE_SOURCE
                )
            except Exception:  # pragma: no cover - defensive
                continue
            if btc_now is None or btc_prior is None or btc_prior <= 0:
                continue
            ret = math.log(float(btc_now) / float(btc_prior))
            if math.isfinite(ret):
                out.append(abs(ret))
        return out

    async def _fetch_abs_ret_2m_history(
        self,
        *,
        symbol_id: str,
        tf: str,
        from_s: int,
        until_s: int,
    ) -> list[float]:
        """Pull |ret_2m| values for completed updown markets in the window.

        Phase 18.5 — mirrors ``_fetch_abs_ret_5m_history`` but uses the
        2-minute return measured AT the market's open boundary (i.e.
        ``log(close@(ws_s+120) / close@ws_s)``). Used to compute the
        rolling 14d q90 |ret_2m| threshold for the momo gate.

        Same SQL filters (markets JOIN market_resolutions_v2 with
        ``outcome IN ('Up','Down')``); only the per-row return derivation
        differs.

        Phase 22.1 (CLAUDE.md inv #13): feed-first read path with anchor=
        'ws_to_ws120' for v1 momo. Tier-3 SQL fallback if feed empty.
        """
        # Phase 22.1: feed-first read path (v1 momo anchor).
        if _bars_module._feed_native_enabled():
            tv_sym = _bars_module._SYMBOL_ID_TO_TV.get(symbol_id)
            if tv_sym is not None:
                samples = _bars_module._FEED_INSTANCE.get_ret_2m_samples(  # type: ignore[union-attr]
                    tv_sym, tf, until_s, anchor="ws_to_ws120"
                )
                if samples:
                    return list(samples)
                logger.warning(
                    "kline_feed.samples_empty_fallthrough",
                    symbol_id=symbol_id,
                    tf=tf,
                    until_s=until_s,
                    fn="_fetch_abs_ret_2m_history",
                )

        if self.pool is None:  # type: ignore[redundant-expr]
            return []

        sym_lower = symbol_id.split("_")[-2].lower()
        slug_regex = f"^{sym_lower}-updown-{tf}-[0-9]+$"
        # TODO(26): not migrated to mode-routing — range scan, not a per-cid lookup
        sql = (
            "SELECT substring(m.slug FROM '\\d+$')::bigint AS end_unix "
            "FROM public.markets m "
            "JOIN public.market_resolutions_v2 r ON r.slug = m.slug "
            "WHERE m.platform = 'polymarket' "
            "  AND m.slug ~ $1 "
            "  AND r.outcome IN ('Up', 'Down') "
            "  AND substring(m.slug FROM '\\d+$')::bigint > $2 "
            "  AND substring(m.slug FROM '\\d+$')::bigint <= $3 "
            "ORDER BY substring(m.slug FROM '\\d+$')::bigint ASC"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, slug_regex, int(from_s), int(until_s))

        tf_seconds = 5 * 60 if tf == "5m" else 15 * 60
        out: list[float] = []
        for r in rows:
            ws_s = int(r["end_unix"]) - tf_seconds
            try:
                close_at_ws = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s, pool=self.pool, source=KLINE_SOURCE
                )
                close_at_120 = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s + 120, pool=self.pool, source=KLINE_SOURCE
                )
            except Exception:  # pragma: no cover - defensive
                continue
            if close_at_ws is None or close_at_120 is None or close_at_ws <= 0:
                continue
            ret = math.log(float(close_at_120) / float(close_at_ws))
            if math.isfinite(ret):
                out.append(abs(ret))
        return out

    async def _fetch_abs_ret_2m_v2_history(
        self,
        *,
        symbol_id: str,
        tf: str,
        from_s: int,
        until_s: int,
    ) -> list[float]:
        """Pull |ret_2m| values for completed updown markets, v2 anchor.

        Phase 18.5+ momo_v2 — mirrors ``_fetch_abs_ret_2m_history`` but
        anchors ret_2m on (ws-60, ws+60) instead of (ws, ws+120):
        ``log(close@(ws+60) / close@(ws-60))``. Used to compute the
        rolling 14d q90 |ret_2m| threshold for the momo_v2 gate.

        Same SQL (markets JOIN market_resolutions_v2 with
        ``outcome IN ('Up','Down')``); only the per-row return derivation
        differs.

        Phase 22.1 (CLAUDE.md inv #13): feed-first read path with anchor=
        'ws_minus_60_to_ws60' for v2 momo. Tier-3 SQL fallback if feed empty.
        """
        # Phase 22.1: feed-first read path (v2 momo anchor).
        if _bars_module._feed_native_enabled():
            tv_sym = _bars_module._SYMBOL_ID_TO_TV.get(symbol_id)
            if tv_sym is not None:
                samples = _bars_module._FEED_INSTANCE.get_ret_2m_samples(  # type: ignore[union-attr]
                    tv_sym, tf, until_s, anchor="ws_minus_60_to_ws60"
                )
                if samples:
                    return list(samples)
                logger.warning(
                    "kline_feed.samples_empty_fallthrough",
                    symbol_id=symbol_id,
                    tf=tf,
                    until_s=until_s,
                    fn="_fetch_abs_ret_2m_v2_history",
                )

        if self.pool is None:  # type: ignore[redundant-expr]
            return []

        sym_lower = symbol_id.split("_")[-2].lower()
        slug_regex = f"^{sym_lower}-updown-{tf}-[0-9]+$"
        # TODO(26): not migrated to mode-routing — range scan, not a per-cid lookup
        sql = (
            "SELECT substring(m.slug FROM '\\d+$')::bigint AS end_unix "
            "FROM public.markets m "
            "JOIN public.market_resolutions_v2 r ON r.slug = m.slug "
            "WHERE m.platform = 'polymarket' "
            "  AND m.slug ~ $1 "
            "  AND r.outcome IN ('Up', 'Down') "
            "  AND substring(m.slug FROM '\\d+$')::bigint > $2 "
            "  AND substring(m.slug FROM '\\d+$')::bigint <= $3 "
            "ORDER BY substring(m.slug FROM '\\d+$')::bigint ASC"
        )
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, slug_regex, int(from_s), int(until_s))

        tf_seconds = 5 * 60 if tf == "5m" else 15 * 60
        out: list[float] = []
        for r in rows:
            ws_s = int(r["end_unix"]) - tf_seconds
            try:
                close_at_ws_minus_60 = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s - 60, pool=self.pool, source=KLINE_SOURCE
                )
                close_at_ws_plus_60 = await fetch_close_asof(
                    symbol_id, "1MIN", ws_s + 60, pool=self.pool, source=KLINE_SOURCE
                )
            except Exception:  # pragma: no cover - defensive
                continue
            if (
                close_at_ws_minus_60 is None
                or close_at_ws_plus_60 is None
                or close_at_ws_minus_60 <= 0
            ):
                continue
            ret = math.log(float(close_at_ws_plus_60) / float(close_at_ws_minus_60))
            if math.isfinite(ret):
                out.append(abs(ret))
        return out

    # ------------------------------------------------------------------
    # Main bar-close hook
    # ------------------------------------------------------------------

    async def on_bar_close(
        self,
        symbol: str,
        tf: str,
        bars: list[Bar],
        *,
        bar_ctx: Any = None,
    ) -> None:
        """Process a closed bar for one (symbol, tf) slot.

        Steps:
        1. Look up strategy by (symbol, tf).
        2. Pre-fetch Binance closes + sniper threshold via
           ``_build_signal_aux`` (Phase 18.1, Wave 2).
        3. Compute signal via ``strategy.signal(bars, None, aux=aux)``.
           Bars are assumed CLOSED.
        4. NONE -> audit + return (no order).
        5. Resolve condition_id via market_mapping.
        6. None condition -> audit reason='resolve_failed' + return.
        7. Build entry order: $25 USDC, side from signal.
        8. Call ``executor.place_entry_order(...)``.
        9. Track open Slot for hedge-hold (Wave 18.1-02 Task 3).

        NEVER calls ``place_exit_order`` in this path (D-06).

        Phase 24 — ``bar_ctx`` (``BarContext`` instance, optional kwarg):
        when provided by ``poly_updown_master_scheduler``, the controller
        skips its own kline / threshold-sample / cid / token-id / orderbook
        fetches and reads from the shared snapshot instead. Eliminates the
        multi-controller race documented in V4-SUBSET-BUG-VERDICT-2026-05-05.

        When ``bar_ctx is None`` (legacy path / direct call): all existing
        per-instance fetches happen as before — backwards-compatible.
        """
        # 2026-05-16 — per-slot allowlist gate. Live-mirror controllers
        # dedupe by (strategy_mode, hedge_policy) so a single controller
        # owns all BTC/ETH/SOL × 5m/15m slots. Without this filter,
        # allowlisting ``btc_15m_momo_HOLD`` ALSO fires SOL + ETH + 5m
        # for that policy (operator's 2026-05-15 unintended-fire bug).
        # Skip BEFORE bar_ctx setup so the early-return is cheap.
        if (
            self._slot_allowlist is not None
            and (symbol.upper(), tf.lower()) not in self._slot_allowlist
        ):
            return
        # Phase 24: stash the shared context so _build_signal_aux +
        # _fetch_or_compute_threshold can read it without changing their
        # signatures (minimal-diff threading). Phase 18.5: backed by a
        # ContextVar (token-based set/reset) so concurrent dispatches on
        # the same controller instance are task-isolated — sibling
        # symbols can't clobber each other's bar_ctx mid-await chain.
        _token = _BAR_CTX_ACTIVE.set(bar_ctx)
        try:
            await self._on_bar_close_impl(symbol, tf, bars)
        finally:
            _BAR_CTX_ACTIVE.reset(_token)

    async def _on_bar_close_impl(
        self, symbol: str, tf: str, bars: list[Bar]
    ) -> None:
        """Real on_bar_close body. Reads ``self._bar_ctx_active`` set by
        the public ``on_bar_close`` wrapper. Split out so the wrapper can
        guarantee cleanup of the per-call attribute regardless of branch.
        """
        bar_ctx = self._bar_ctx_active  # may be None (legacy path)

        key = (symbol.upper(), tf)
        strategy = self._strategies.get(key)
        if strategy is None:
            await self._audit(symbol, tf, reason="unsupported_slot", signal=None)
            return

        # V3 is 5m-only by design (15m diluted backtest HO ROI 32%→26%).
        # Silent skip on 15m boundaries — no audit row to keep the trail
        # clean when V3 runs alongside other modes.
        if self.strategy_mode == "v3" and tf != "5m":
            return
        # Phase 18.2 D-11 — parallel guard for v3_1/v3_2/v4 (also 5m-only).
        # Phase 18.3 — v3_3 inherits the 5m-only constraint (V3.2 lineage).
        if self.strategy_mode in ("v3_1", "v3_2", "v3_3", "v4") and tf != "5m":
            return

        # 2026-05-21 — per-cell disable for momo_v2 (TV_AGENT_FIX_MOMO_V2_BUGS
        # report 2026-05-21). The centered-window ret_2m formula in V2
        # mis-fires on certain (asset, tf) combos: eth_5m (0/57 DOWN accuracy
        # → 5% WR), btc_15m (0/28 UP accuracy → 18% WR), btc_5m (mild bias).
        # sol_5m + eth_15m work fine (~70% WR) and stay enabled.
        # Env: TV_POLY_MOMO_V2_DISABLED_CELLS=eth_5m,btc_15m (CSV of
        # "{asset}_{tf}" tokens, case-insensitive). Empty = no disables.
        if self.strategy_mode == "momo_v2":
            import os as _os
            _disabled_raw = _os.environ.get("TV_POLY_MOMO_V2_DISABLED_CELLS", "").strip()
            if _disabled_raw:
                _disabled_cells = frozenset(
                    s.strip().lower() for s in _disabled_raw.split(",") if s.strip()
                )
                _cell_token = f"{symbol.lower()}_{tf.lower()}"
                if _cell_token in _disabled_cells:
                    # Silent skip — no audit row. logger is stdlib logging
                    # (not structlog) in this module — keep call signature
                    # compatible: positional msg only, no kwargs.
                    logger.warning(
                        "poly_updown.momo_v2_cell_disabled cell=%s",
                        _cell_token,
                    )
                    return

        signal_ts = self._signal_ts(bars)
        window_start_us = int(signal_ts.timestamp() * 1_000_000)
        aux = await self._build_signal_aux(symbol, tf, window_start_us)

        signal: SignalResult = strategy.signal(bars, None, aux=aux)

        # Phase 18.4 — inverse mode flip + filter. Inverse sleeves wrap a
        # base mode (volume/sniper) and emit on a separate sleeve_id only
        # for windows matching the inverse rule. Outside the rule window
        # we exit silently (no audit row) per spec §1: "don't compete
        # with the original".
        # ``self._last_base_signal`` is set so subsequent _audit() calls
        # (in this on_bar_close invocation) can attach the pre-flip
        # ``base_signal`` field. Ignored when self._inverse_kind is None.
        self._last_base_signal = signal
        if self._inverse_kind is not None:
            inv_signal = apply_inverse_filter(
                kind=self._inverse_kind,
                symbol=symbol,
                tf=tf,
                base_signal=signal,
                window_start_unix=window_start_us // 1_000_000,
            )
            if inv_signal == "NONE":
                # Silent — inverse rule says "don't fire on this window".
                return
            signal = inv_signal  # type: ignore[assignment]

        if signal == "NONE":
            await self._audit(symbol, tf, reason="no_signal", signal="NONE")
            return

        # Phase 27 LIVE-DISC-02 — live mode resolves Polymarket market
        # context via TV-native PolyMarketDiscovery (CLAUDE.md inv #13).
        # Bypasses Storedata `resolve_condition_id` + `_check_market_freshness`
        # entirely on the live path: discovery has already validated
        # `accepting_orders` and `closed`. Paper mode falls through to the
        # legacy resolve-from-Storedata flow byte-identical.
        if self.mode == "live":
            _tf_sec_for_entry = 300 if tf == "5m" else 900
            # 2026-05-20 fix: bet the NEXT-future window, not the just-opened
            # CURRENT window. Mirrors the paper-path semantic in
            # market_mapping.resolve_condition_id (`slug_epoch > signal_unix`
            # → smallest strictly-future slug). Prior bug: floor(signal_ts)
            # picked the just-opened window; by the time the order filled
            # 1-2 minutes later the underlying had already moved, so the
            # Polymarket market priced ~0.95 vs the paper-path ~0.50 entry
            # — 40+ cents of edge silently leaked. Evidence: vps_ireland
            # 14:31:02 ETH live @ 0.67 vs VPS3 paper @ 0.51 on same signal.
            window_start_unix_for_entry = (
                int(signal_ts.timestamp()) // _tf_sec_for_entry + 1
            ) * _tf_sec_for_entry
            assert self._discovery is not None, (
                "live mode requires discovery; ctor should have raised"
            )
            try:
                ctx_live = self._discovery.find(
                    symbol.upper(), tf, window_start_unix_for_entry
                )
            except MarketDiscoveryUnreachableError as exc:
                # Phase 27 LIVE-DISC-05 — Gamma kill-path tripped.
                # Refuse new entry orders; existing open slots continue to
                # resolve via on-chain oracle (CLAUDE inv #11: no auto-kill).
                logger.warning(
                    "poly_updown.market_discovery_unreachable",
                    extra={
                        "symbol": symbol,
                        "tf": tf,
                        "window_start_unix": window_start_unix_for_entry,
                        "error": str(exc)[:200],
                    },
                )
                await self._audit(
                    symbol,
                    tf,
                    reason="market_discovery_unreachable",
                    signal=signal,
                )
                return
            if ctx_live is None:
                logger.warning(
                    "poly_updown.market_not_discovered_at_entry",
                    extra={
                        "symbol": symbol,
                        "tf": tf,
                        "window_start_unix": window_start_unix_for_entry,
                    },
                )
                await self._audit(
                    symbol,
                    tf,
                    reason="market_not_discovered_at_entry",
                    signal=signal,
                )
                return
            if ctx_live.closed or not ctx_live.accepting_orders:
                logger.warning(
                    "poly_updown.market_closed_at_entry",
                    extra={
                        "symbol": symbol,
                        "tf": tf,
                        "condition_id": ctx_live.condition_id,
                        "closed": ctx_live.closed,
                        "accepting_orders": ctx_live.accepting_orders,
                    },
                )
                await self._audit(
                    symbol,
                    tf,
                    reason="market_closed_at_entry",
                    signal=signal,
                    condition_id=ctx_live.condition_id,
                )
                return
            cid = ctx_live.condition_id
        else:
            # Resolve Polymarket condition for this signal timestamp.
            # Phase 24: prefer the shared BarContext.condition_id when present.
            if (
                bar_ctx is not None
                and getattr(bar_ctx, "symbol", None) == symbol.upper()
                and getattr(bar_ctx, "tf", None) == tf
                and bar_ctx.condition_id is not None
            ):
                cid = bar_ctx.condition_id
            else:
                cid = await resolve_condition_id(
                    self.pool,
                    symbol=symbol,
                    tf=tf,  # type: ignore[arg-type]
                    signal_ts=signal_ts,
                )
            if cid is None:
                logger.warning(
                    "poly_updown.resolve_failed",
                    extra={"symbol": symbol, "tf": tf, "signal_ts": signal_ts.isoformat()},
                )
                await self._audit(symbol, tf, reason="resolve_failed", signal=signal)
                return

            # Phase 18.1 forensics 2026-04-28: defense-in-depth against the
            # cache-TTL bug that mapped fills to already-resolved markets.
            # Even after market_mapping cache fix, refuse to bet on a market
            # whose slug-encoded resolve epoch is in the past, or so close
            # to "now" that we cannot reasonably observe + hedge before it
            # resolves. Audit-only skip — no order, no slot tracked.
            # Phase 27 — paper-only branch; live mode's discovery validation
            # supersedes this check.
            skip_reason = await self._check_market_freshness(cid)
            if skip_reason is not None:
                logger.warning(
                    "poly_updown.skip_stale_market",
                    extra={
                        "symbol": symbol,
                        "tf": tf,
                        "condition_id": cid,
                        "reason": skip_reason,
                    },
                )
                await self._audit(
                    symbol,
                    tf,
                    reason=skip_reason,
                    signal=signal,
                    condition_id=cid,
                )
                return

        # V3 spread filter: skip if (best_ask − best_bid) / mid ≥ 2%.
        # Per backtest §1.4: tight spreads correlate with fill quality;
        # wide-spread markets give back the magnitude edge to slippage.
        # Worth +2.0pp HO ROI on holdout. Reads the same book the executor
        # will read for sizing — 5s LRU cache absorbs the duplicate fetch.
        if self.strategy_mode == "v3":
            # Phase 24: prefer shared BarContext token_id + book snapshot
            # when present (collapses the multi-controller orderbook race).
            _ctx_match_v3 = (
                bar_ctx is not None
                and getattr(bar_ctx, "symbol", None) == symbol.upper()
                and getattr(bar_ctx, "tf", None) == tf
                and bar_ctx.condition_id == cid
            )
            if _ctx_match_v3:
                v3_token_id = (
                    bar_ctx.token_id_yes if signal == "UP" else bar_ctx.token_id_no
                )
                v3_book = (
                    bar_ctx.book_snapshot_yes if signal == "UP" else bar_ctx.book_snapshot_no
                )
                v3_spread = (
                    bar_ctx.spread_pct_yes if signal == "UP" else bar_ctx.spread_pct_no
                )
            else:
                v3_token_id = await self._resolve_token_id(cid, signal)
                if v3_token_id is None:
                    logger.warning(
                        "poly_updown.v3_token_id_lookup_failed",
                        extra={"symbol": symbol, "tf": tf, "cid": cid},
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="token_id_lookup_failed",
                        signal=signal,
                        condition_id=cid,
                    )
                    return
                try:
                    v3_book = await self.executor.get_orderbook_snapshot(v3_token_id)
                except Exception:  # pragma: no cover — defensive
                    v3_book = None
                v3_spread = _spread_pct(v3_book) if v3_book else None
            if _ctx_match_v3 and v3_token_id is None:
                # bar_ctx had cid but failed to resolve token_id earlier
                logger.warning(
                    "poly_updown.v3_token_id_lookup_failed",
                    extra={"symbol": symbol, "tf": tf, "cid": cid, "via": "bar_ctx"},
                )
                await self._audit(
                    symbol, tf, reason="token_id_lookup_failed",
                    signal=signal, condition_id=cid,
                )
                return
            # Phase 18.3 — per-asset spread filter (Fix A). SOL gets 0.025
            # default; BTC/ETH unchanged at 0.02. Env-overridable.
            v3_spread_threshold = _v3_spread_filter_for(symbol)
            if v3_spread is None or v3_spread >= v3_spread_threshold:
                logger.info(
                    "poly_updown.v3_wide_spread_skip",
                    extra={
                        "symbol": symbol,
                        "tf": tf,
                        "cid": cid,
                        "spread_pct": v3_spread,
                        "spread_threshold": v3_spread_threshold,
                    },
                )
                await self._audit(
                    symbol,
                    tf,
                    reason="wide_spread_skip",
                    signal=signal,
                    condition_id=cid,
                    spread_pct=(f"{v3_spread:.4f}" if v3_spread is not None else None),
                )
                return

        # Phase 18.2 D-11 — same spread-filter + token-id-resolve flow for
        # v3_1/v3_2/v4. Copy of the v3 block above with renamed locals.
        # Phase 18.3 — v3_3 joins the same path (V3.2 lineage).
        if self.strategy_mode in ("v3_1", "v3_2", "v3_3", "v4"):
            # Phase 24: prefer shared BarContext when present.
            _ctx_match_v3p = (
                bar_ctx is not None
                and getattr(bar_ctx, "symbol", None) == symbol.upper()
                and getattr(bar_ctx, "tf", None) == tf
                and bar_ctx.condition_id == cid
            )
            if _ctx_match_v3p:
                v3p_token_id = (
                    bar_ctx.token_id_yes if signal == "UP" else bar_ctx.token_id_no
                )
                v3p_book = (
                    bar_ctx.book_snapshot_yes if signal == "UP" else bar_ctx.book_snapshot_no
                )
                v3p_spread = (
                    bar_ctx.spread_pct_yes if signal == "UP" else bar_ctx.spread_pct_no
                )
            else:
                v3p_token_id = await self._resolve_token_id(cid, signal)
                if v3p_token_id is None:
                    logger.warning(
                        "poly_updown.v3p_token_id_lookup_failed",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "cid": cid,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="token_id_lookup_failed",
                        signal=signal,
                        condition_id=cid,
                    )
                    return
                try:
                    v3p_book = await self.executor.get_orderbook_snapshot(v3p_token_id)
                except Exception:  # pragma: no cover — defensive
                    v3p_book = None
                v3p_spread = _spread_pct(v3p_book) if v3p_book else None
            if _ctx_match_v3p and v3p_token_id is None:
                logger.warning(
                    "poly_updown.v3p_token_id_lookup_failed",
                    extra={
                        "symbol": symbol, "tf": tf, "cid": cid,
                        "strategy_mode": self.strategy_mode, "via": "bar_ctx",
                    },
                )
                await self._audit(
                    symbol, tf, reason="token_id_lookup_failed",
                    signal=signal, condition_id=cid,
                )
                return
            # Phase 18.3 — per-asset spread filter (Fix A). Same helper as
            # v3 base path; SOL=0.025, BTC/ETH=0.02 (env-overridable).
            v3p_spread_threshold = _v3_spread_filter_for(symbol)
            if v3p_spread is None or v3p_spread >= v3p_spread_threshold:
                logger.info(
                    "poly_updown.v3p_wide_spread_skip",
                    extra={
                        "symbol": symbol,
                        "tf": tf,
                        "cid": cid,
                        "spread_pct": v3p_spread,
                        "spread_threshold": v3p_spread_threshold,
                        "strategy_mode": self.strategy_mode,
                    },
                )
                await self._audit(
                    symbol,
                    tf,
                    reason="wide_spread_skip",
                    signal=signal,
                    condition_id=cid,
                    spread_pct=(f"{v3p_spread:.4f}" if v3p_spread is not None else None),
                )
                return

        # Phase 18.2 NEW gate stack — fires ONLY for v3_1/v3_2/v4. Per SPEC
        # §V4 order (cheapest checks first; SOL skips macro_2of3 internally).
        # All gates are env-flag-gated via the v3_1_*/v3_2_* helpers (a
        # disabled gate is a no-op pass).
        # Phase 18.3 — v3_3 joins the gate stack (it's V3.2 lineage + MH for
        # SOL). V3.3 runs the V3.2 gates (hour, macro_2of3, liq_quiet) but
        # NOT the V3.1 gates (regime overlay, live-direction filter).
        if self.strategy_mode in ("v3_1", "v3_2", "v3_3", "v4"):
            direction_v3p = signal if signal in ("UP", "DOWN") else None
            if direction_v3p is None:
                # Defensive: signal must be UP/DOWN by this point. NONE was
                # caught above. Anything else is an audit-only skip.
                await self._audit(
                    symbol,
                    tf,
                    reason="signal_unknown_direction",
                    signal=signal,
                    condition_id=cid,
                )
                return

            ret_1h_v3p = aux.get("ret_1h") if aux else None
            ret_5m_v3p_aux = aux.get("ret_5m") if aux else None
            ret_15m_v3p_aux = aux.get("ret_15m") if aux else None

            # V3.1 soft regime overlay (v3_1 + v4 only). Skips when ret_1h
            # is None (cold start). We check ret_1h finiteness defensively.
            if self.strategy_mode in ("v3_1", "v4"):
                if (
                    ret_1h_v3p is not None
                    and math.isfinite(float(ret_1h_v3p))
                    and not v3_1_regime_passes(direction_v3p, float(ret_1h_v3p))
                ):
                    logger.info(
                        "poly_updown.v3p_regime_blocked",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "cid": cid,
                            "direction": direction_v3p,
                            "ret_1h": ret_1h_v3p,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="regime_blocked",
                        signal=signal,
                        condition_id=cid,
                    )
                    return

            # V3.2 hour gate (v3_2 + v3_3 + v4). Phase 18.3 — v3_3 inherits.
            if self.strategy_mode in ("v3_2", "v3_3", "v4"):
                if not v3_2_hour_passes(int(signal_ts.timestamp())):
                    logger.info(
                        "poly_updown.v3p_hour_blocked",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "cid": cid,
                            "hour_utc": signal_ts.hour,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="hour_blocked",
                        signal=signal,
                        condition_id=cid,
                    )
                    return

            # V3.2 macro 2-of-3 gate (v3_2 + v3_3 + v4). Skips SOL internally
            # (v3_2_macro_2of3_passes short-circuits to True for SOL).
            # Phase 18.3 — v3_3 inherits this gate; SOL bypass is unchanged.
            # Cold-start: any of ret_5m/ret_15m/ret_1h missing → audit + skip.
            if self.strategy_mode in ("v3_2", "v3_3", "v4"):
                if ret_5m_v3p_aux is None or ret_15m_v3p_aux is None or ret_1h_v3p is None:
                    # Insufficient data to evaluate macro — skip defensively.
                    if symbol.upper() != "SOL":
                        await self._audit(
                            symbol,
                            tf,
                            reason="macro_2of3_data_missing",
                            signal=signal,
                            condition_id=cid,
                        )
                        return
                elif not v3_2_macro_2of3_passes(
                    symbol,
                    float(ret_5m_v3p_aux),
                    float(ret_15m_v3p_aux),
                    float(ret_1h_v3p),
                ):
                    logger.info(
                        "poly_updown.v3p_macro_2of3_fail",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "cid": cid,
                            "ret_5m": ret_5m_v3p_aux,
                            "ret_15m": ret_15m_v3p_aux,
                            "ret_1h": ret_1h_v3p,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="macro_2of3_fail",
                        signal=signal,
                        condition_id=cid,
                    )
                    return

            # V3.2 liq_quiet gate (v3_2 + v3_3 + v4). Fail-open per D-05.
            # Phase 18.3 — v3_3 inherits.
            if self.strategy_mode in ("v3_2", "v3_3", "v4"):
                if not v3_2_liq_quiet_passes(symbol, getattr(self, "liq_db", None)):
                    logger.info(
                        "poly_updown.v3p_liq_active_regime",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "cid": cid,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="liq_active_regime",
                        signal=signal,
                        condition_id=cid,
                    )
                    return

            # V3.1 live direction filter (v3_1 + v4 only, live mode only).
            if self.strategy_mode in ("v3_1", "v4"):
                if not v3_1_live_direction_allowed(
                    symbol, tf, direction_v3p, live_mode=(self.mode == "live")
                ):
                    logger.info(
                        "poly_updown.v3p_live_direction_blocked",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "cid": cid,
                            "direction": direction_v3p,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="live_direction_blocked",
                        signal=signal,
                        condition_id=cid,
                    )
                    return

            # Phase 18.3 — V3.3 paper-only gate. v3_3 is an A/B EXPERIMENT
            # against v3_2 (multi-horizon for SOL). Promotion to live trading
            # is gated on the 7-day decision protocol per
            # SOL_V3_FIX_SPEC_2026_05_04 §"Decision protocol"; until then
            # `V3_3_LIVE_DISABLED=true` (default) blocks live emission while
            # preserving paper-mode audit rows for analysis.
            if self.strategy_mode == "v3_3" and self.mode == "live":
                _v3_3_live_disabled = os.environ.get(
                    "V3_3_LIVE_DISABLED", "true"
                ).strip().lower() in ("1", "true", "yes")
                if _v3_3_live_disabled:
                    logger.info(
                        "poly_updown.v3_3_paper_only",
                        extra={
                            "symbol": symbol,
                            "tf": tf,
                            "cid": cid,
                            "direction": direction_v3p,
                            "strategy_mode": self.strategy_mode,
                        },
                    )
                    await self._audit(
                        symbol,
                        tf,
                        reason="v3_3_paper_only",
                        signal=signal,
                        condition_id=cid,
                    )
                    return

        # Build the entry order. UP -> buy YES, DOWN -> buy NO.
        try:
            result = await self._place_entry(
                symbol=symbol,
                tf=tf,
                condition_id=cid,
                signal=signal,
                aux=aux,
                window_start_unix=window_start_us // 1_000_000,
            )
            # Phase 18.1: _place_entry returns None when an internal guard
            # already wrote its own audit row (qty_compute_failed,
            # token_id_lookup_failed). Skip the order_placed/entry_rejected
            # audit here to avoid the double-audit bug surfaced 2026-04-28
            # (sol_5m showed both qty_compute_failed AND empty order_placed
            # rows for the same boundary, inflating fill_count_24h).
            if result is None:
                return

            # SHADOW-RUN-1 fix #3: surface FillStatus + fill metadata in audit
            # so REJECTED can be distinguished from real fills downstream
            # (paper-mode P&L parity + parity report queries).
            fs = getattr(result, "status", None)
            fill_status_str = str(fs).split(".")[-1].lower() if fs is not None else ""
            raw = getattr(result, "raw_response", None) or {}
            fill_qty_str: str | None = None
            fill_price_str: str | None = None
            # Phase 25 Tier A — surface venue-reported fee + tx_hash on the
            # audit row so TCA can compute fees_bps_avg honestly. CLOB
            # response typically has fee=0 for USDC trades; _audit falls
            # back to the operator-tunable baseline when so.
            fee_str: str | None = None
            tx_hash_str: str | None = None
            if isinstance(raw, dict):
                fill_qty_str = raw.get("filled")
                fill_price_str = raw.get("avg_price") or raw.get("price")
                fee_raw = raw.get("fee")
                fee_str = str(fee_raw) if fee_raw is not None else None
                tx_hash_str = raw.get("tx_hash") or raw.get("txHash")
            audit_reason = "entry_rejected" if "rejected" in fill_status_str else "order_placed"
            await self._audit(
                symbol,
                tf,
                reason=audit_reason,
                signal=signal,
                condition_id=cid,
                fill_status=fill_status_str or None,
                fill_qty=fill_qty_str,
                fill_price=fill_price_str,
                qty_intended=str(self.notional_usd),
                fee_usd=fee_str,
                tx_hash=tx_hash_str,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception(
                "poly_updown.entry_failed",
                extra={"symbol": symbol, "tf": tf, "cid": cid},
            )
            await self._audit(
                symbol,
                tf,
                reason="entry_exception",
                signal=signal,
                condition_id=cid,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _place_entry(
        self,
        *,
        symbol: str,
        tf: str,
        condition_id: str,
        signal: SignalResult,
        aux: dict[str, Any] | None = None,
        window_start_unix: int = 0,
    ) -> Any:
        """Route the $25 entry to paper or live executor based on mode.

        Both paper.PolyPaperExecutor and live PolymarketClient expose
        ``place_entry_order(token_id, qty, limit_px, sleeve_id, side)``.

        Resolves (condition_id, outcome) → token_id by reading the
        ``clob_token_ids`` jsonb array from ``public.markets`` for the
        condition (verified 2026-04-28 — schema has ``clob_token_ids``
        as ``[yes_token_id, no_token_id]`` matching ``outcomes=["Up", "Down"]``).

        UP signal → outcome="YES" → clob_token_ids[0].
        DOWN signal → outcome="NO" → clob_token_ids[1].

        The controller picks ``side="buy"`` always — UP/DOWN distinction
        is encoded in which outcome token the order targets.
        """
        outcome = "YES" if signal == "UP" else "NO"
        sleeve_id = self._sleeve_id(symbol, tf, outcome)

        # Resolve token_id from clob_token_ids jsonb on public.markets.
        token_id = await self._resolve_token_id(condition_id, signal)
        if token_id is None:
            logger.warning(
                "poly_updown.token_id_lookup_failed",
                extra={
                    "symbol": symbol,
                    "tf": tf,
                    "condition_id": condition_id,
                    "signal": signal,
                },
            )
            await self._audit(
                symbol,
                tf,
                reason="token_id_lookup_failed",
                signal=signal,
                condition_id=condition_id,
            )
            return None

        # Phase 18.1 forensics 2026-04-28: convert notional USD → share count
        # before placing the order. Both paper executor and live polymarket
        # CLOB SDK interpret `qty` as SHARES, not USD. Prior code passed
        # `qty=self.notional_usd` (Decimal "25") which was actually 25 SHARES
        # — at $0.50 mid that's $12.50 spent (under-betting), at $0.001 dying
        # market $0.025 spent (catastrophic under-bet). Fix: read best ask
        # from the held-side orderbook, divide notional by it, pass the
        # share count.
        qty_shares = await self._compute_qty_shares(token_id)
        if qty_shares is None:
            logger.warning(
                "poly_updown.qty_compute_failed_no_book",
                extra={
                    "symbol": symbol,
                    "tf": tf,
                    "condition_id": condition_id,
                    "signal": signal,
                },
            )
            await self._audit(
                symbol,
                tf,
                reason="qty_compute_failed",
                signal=signal,
                condition_id=condition_id,
            )
            return None

        # Sanity assertion: qty MUST be in shares per executor contract.
        # At $25 notional / $0.05 worst-acceptable best_ask = 500 shares max.
        # Anything > QTY_SANITY_MAX strongly suggests a notional-as-qty
        # regression slipped past the conversion. Hard-block rather than
        # ship a bet 1000× too big.
        assert qty_shares <= self.QTY_SANITY_MAX, (
            f"qty_shares={qty_shares} exceeds sanity max — likely notional"
            f" passed where shares expected (controller→executor contract)"
        )

        result = await self.executor.place_entry_order(
            token_id=token_id,
            qty=qty_shares,
            limit_px=Decimal("0.99"),  # take liquidity; venue caps to best-ask
            sleeve_id=sleeve_id,
            side="buy",
        )

        # SHADOW-RUN-1 fix #4: do NOT track a Slot when the executor
        # REJECTED the fill. There is no real position; tracking creates
        # a phantom slot that on_tick keeps trying to hedge against an
        # opposite book that's also empty (no_asks). Causes slot leaks +
        # spurious hedge_skipped_no_asks events. Filled / Partial slots
        # ARE tracked because they represent real exposure.
        result_status_str = str(getattr(result, "status", "")).split(".")[-1].lower()
        if "rejected" in result_status_str:
            return result

        # Phase 18.1: track the open Slot for hedge-hold. Idempotency by
        # (symbol, tf, window_start_unix) per RESEARCH §7 — duplicate
        # window_start fires (engine restart, replay) won't double-create.
        sym_upper = symbol.upper()
        slot_key = (sym_upper, tf, window_start_unix)
        if slot_key not in self._slots:
            btc_close = aux.get("binance_close_at_ws") if aux else None
            symbol_id = BINANCE_SYMBOL_ID_MAP.get(sym_upper, "")
            slot = Slot(
                sleeve_id=sleeve_id,
                symbol=sym_upper,
                tf=tf,
                condition_id=condition_id,
                signal="UP" if signal == "UP" else "DOWN",
                entry_price=Decimal("0.99"),  # placeholder; venue may improve
                entry_qty=qty_shares,  # SHARES not USD; resolver math depends on this
                btc_close_at_ws=(
                    Decimal(str(btc_close)) if btc_close is not None else Decimal("0")
                ),
                binance_symbol_id=symbol_id,
                window_start_unix=window_start_unix,
                slot_id=f"{sleeve_id}-{window_start_unix}",
            )
            # Phase 18.6 W1 — populate the entry-side token_id on the slot
            # AND subscribe to BookMirror (Tier-1 hot path).
            # Bug 3 follow-up (audit 2026-05-06): pre-W1.1 the OPPOSITE-side
            # was resolved + subscribed LAZILY at first hedge tick — but
            # the hedge-tick read happens IN THE SAME TICK as the subscribe,
            # before the WS book msg arrives (~50-200ms latency). Result:
            # 521 hedge_skip events post-W1 deploy on volume bundles, all
            # with book_ts=0. Fix: eagerly resolve BOTH yes + no token_ids
            # at slot creation and subscribe both. By the time the first
            # hedge tick fires (~10s later) the WS book is hot.
            opposite_signal: SignalResult = "DOWN" if signal == "UP" else "UP"
            try:
                opposite_token_id = await self._resolve_token_id(
                    condition_id, opposite_signal
                )
            except Exception:  # noqa: BLE001 — defensive: resolve failure shouldn't block entry
                logger.warning(
                    "poly_updown.opposite_token_resolve_failed",
                    extra={"slot": slot.slot_id, "cid": condition_id},
                )
                opposite_token_id = None
            # Populate slot legs.
            if signal == "UP":
                slot.yes_token_id = int(token_id)
                if opposite_token_id is not None:
                    slot.no_token_id = int(opposite_token_id)
            else:
                slot.no_token_id = int(token_id)
                if opposite_token_id is not None:
                    slot.yes_token_id = int(opposite_token_id)
            # Eager-subscribe BOTH legs to BookMirror. Refcounted so
            # repeat subscribes are no-ops; unsubscribe at slot GC.
            if self._book_mirror is not None:
                for tok in (token_id, opposite_token_id):
                    if tok is None:
                        continue
                    try:
                        await self._book_mirror.subscribe(str(tok))
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "poly_updown.book_mirror_subscribe_failed",
                            extra={"slot": slot.slot_id, "token_id": str(tok)},
                        )
            self._slots[slot_key] = slot

        return result

    def _sleeve_id(self, symbol: str, tf: str, outcome: str) -> str:
        # Phase 18.4 — inverse sleeves emit a fixed sleeve_id (no outcome
        # split, no per-mode infix). The ``outcome`` arg is ignored.
        # Per Q4 (single sleeve_id per inverse rule).
        if self._inverse_kind is not None:
            base = inverse_sleeve_id(kind=self._inverse_kind, symbol=symbol, tf=tf)
        # Phase 18.5 — momo controllers get a per-policy suffix
        # (HOLD/HEDGE/SELL) so the 3 controllers per (sym, tf) write
        # distinct sleeve_ids. The outcome split is preserved (analyzer
        # can still group by sym/tf/policy).
        elif self.strategy_mode == "momo":
            policy_suffix = _HEDGE_POLICY_SUFFIX[self.hedge_policy]
            # 2026-05-20 F7: `_f7` suffix when F7 RSI filter is active.
            base = (
                f"poly_updown_{symbol.lower()}_{tf}_momo_{policy_suffix}{self._f7_suffix}"
                f"_{outcome.lower()}"
            )
        # Phase 18.5+ — momo_v2 mirrors momo's per-policy naming with the
        # v2 infix so v1 and v2 sleeves are never aliased.
        elif self.strategy_mode == "momo_v2":
            policy_suffix = _HEDGE_POLICY_SUFFIX[self.hedge_policy]
            base = (
                f"poly_updown_{symbol.lower()}_{tf}_momo_v2_{policy_suffix}{self._f7_suffix}"
                f"_{outcome.lower()}"
            )
        # Phase 18.2 V2: sniper-mode controllers get a `_sniper_` infix so
        # parallel volume+sniper sleeves don't collide in trading.events.
        # Volume mode keeps the V1 format (no infix) to preserve VPS2's
        # existing audit history without breaking dashboard queries.
        elif self.strategy_mode == "sniper":
            base = f"poly_updown_{symbol.lower()}_{tf}_sniper_{outcome.lower()}"
        else:
            base = f"poly_updown_{symbol.lower()}_{tf}_{outcome.lower()}"
        # Phase 26.3 D-02 — live-mirror twins append the ``_LIVE`` suffix
        # so dashboard A/B queries can trivially distinguish live audit
        # rows from their paper sibling's. ``getattr`` is defensive in
        # case any test construction path bypasses __init__.
        if getattr(self, "_is_live_mirror", False):
            return f"{base}_LIVE"
        return base

    # Minimum slack between "now" and the market's slug-encoded resolve
    # epoch. Below this, we refuse to enter — too little time to observe
    # + potentially hedge the position. Aligned with hedge tick cadence
    # (10s) plus a small operational buffer.
    MARKET_FRESHNESS_MIN_SECONDS = 30

    # Sanity bounds for the notional/best_ask computation. A best_ask
    # outside this range strongly suggests a degenerate/dead market book
    # (tick-min on losing side, ~0.999 on winning side at resolution).
    QTY_MIN_PRICE = Decimal("0.05")  # below this, market is too one-sided
    QTY_MAX_PRICE = Decimal("0.95")  # above this, almost-resolved opposite leg

    # Hard ceiling for share count passed to executor — defends against any
    # future regression where USD is mistakenly passed as `qty`. At $25
    # notional / $0.05 (QTY_MIN_PRICE) = 500 shares; this gives 2× headroom.
    QTY_SANITY_MAX = Decimal("1000")

    async def _compute_qty_shares(self, token_id: int) -> Decimal | None:
        """Convert ``self.notional_usd`` to a share count using best_ask.

        CONTRACT: ``executor.place_entry_order`` and ``place_exit_order``
        accept ``qty`` in **SHARES**, not USD. This is non-negotiable —
        the live polymarket CLOB SDK takes share count as ``size``, and
        the paper executor walks orderbook depth in shares. The USD →
        shares conversion happens HERE at the controller boundary, in
        ONE place, so downstream code (hedge tick, exit path, smoke
        tests) all see consistent share semantics.

        Strategy-agent suggestion 2026-04-28 considered moving notional →
        shares conversion into the executor signature
        (place_entry_order(notional_usd=...)). Rejected for: (a) the live
        SDK takes shares anyway so the conversion still happens internally,
        (b) executor would need to fetch its own orderbook to compute
        best_ask — duplicating the read the controller already does for
        sizing, (c) breaks the contract for hedge fills which need to
        match the original entry's share count exactly (delta-neutral).
        Documenting the convention is the cleaner intervention.

        Live polymarket CLOB and the paper executor both walk orderbook
        in shares. To bet $25 we need ~25/best_ask shares. If the book
        is unavailable, stale, or its best_ask is outside the sanity
        window (Phase 18.1 dead-market bug), refuse the entry.
        """
        try:
            book = await self.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover — defensive
            return None
        if not book:
            return None
        # 2026-05-14 — paper executor returns a dict; live PolymarketClient
        # returns a Pydantic OrderbookSnapshot. Normalize: use .get() on
        # dicts and attribute access on the model, then read price off
        # OrderbookLevel-or-dict-or-tuple shape transparently.
        # 2026-05-15 — Phase 27 G7 burn-in bug: Pydantic OrderbookSnapshot
        # exposes asks/bids as `list[tuple[Decimal, Decimal]]` (price, size)
        # per backend/app/venues/polymarket/models.py:136-137. The previous
        # `getattr(top, "price", "0")` returned "0" for tuples → best_ask=0
        # → fails Phase 18.1 QTY_MIN_PRICE guard → silent qty_compute_failed.
        # Pre-Phase 27 the Tier-3 Storedata path returned dicts which masked
        # this; Phase 27 LIVE-DISC-03 removed Tier-3 from live → BookMirror
        # tuples now reach this code path. Fix: handle tuple shape explicitly.
        if isinstance(book, dict):
            if book.get("_stale"):
                return None
            asks = book.get("asks") or []
        else:
            # Pydantic OrderbookSnapshot — no `_stale` flag on the model.
            asks = list(getattr(book, "asks", None) or [])
        if not asks:
            return None
        top = asks[0]
        try:
            if isinstance(top, tuple):
                # OrderbookSnapshot.asks: list[tuple[Decimal, Decimal]]
                # (price, size) — index 0 is price
                best_ask = Decimal(str(top[0]))
            elif isinstance(top, dict):
                best_ask = Decimal(str(top.get("price", "0")))
            else:
                best_ask = Decimal(str(getattr(top, "price", "0")))
        except (TypeError, KeyError, IndexError):
            return None
        if best_ask < self.QTY_MIN_PRICE or best_ask > self.QTY_MAX_PRICE:
            # Degenerate book — refuse to bet rather than under/over-size.
            return None
        # 4-decimal share count matches Polymarket's tick size for sub-dollar
        # tokens; rounding HALF_DOWN avoids accidentally over-quoting.
        from decimal import ROUND_DOWN

        qty = (self.notional_usd / best_ask).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
        if qty <= 0:
            return None
        return qty

    async def _check_market_freshness(self, condition_id: str) -> str | None:
        """Reject entry if the market's resolve epoch is <30s away or already past.

        Returns:
            None if the market is safe to bet on.
            'market_already_resolved' if slug epoch < now (should never happen
              after the market_mapping cache fix; defense-in-depth).
            'market_too_close_to_resolution' if 0 <= time_to_resolve < 30s.
            None if we can't determine the slug (don't block — log + proceed
              with the prior behavior).
        """
        # Phase 26-03 Spot-4 — route slug lookup via _get_market_meta shim.
        # Paper: extracted helper reads same public.markets row; live: gamma.
        # Translate MarketNotFoundError -> None to preserve the prior
        # "don't block fill on DB miss" semantics for this metadata-optional
        # callsite (see 26-03-DISCOVERY.md Spot-4 classification).
        try:
            meta = await self._get_market_meta(condition_id)
        except MarketNotFoundError:
            return None
        except Exception:  # pragma: no cover — never block fill on DB miss
            return None
        if not meta.slug:
            return None
        slug = meta.slug
        # Slug suffix encodes resolve_unix.
        try:
            resolve_unix = int(slug.rsplit("-", 1)[-1])
        except (ValueError, AttributeError):
            return None
        now = int(datetime.now(UTC).timestamp())
        delta = resolve_unix - now
        if delta < 0:
            return "market_already_resolved"
        if delta < self.MARKET_FRESHNESS_MIN_SECONDS:
            return "market_too_close_to_resolution"
        return None

    async def _resolve_token_id(
        self,
        condition_id: str,
        signal: SignalResult,
    ) -> int | None:
        """Look up the CTF token_id for a Polymarket condition + signal side.

        Reads ``public.markets.clob_token_ids`` (jsonb array of two strings):
            [yes_token_id, no_token_id] aligned with outcomes=["Up", "Down"]

        UP signal → index 0 (Yes side). DOWN → index 1 (No side).

        Returns the token_id as an int, or None if the row doesn't exist
        or clob_token_ids is missing/malformed.
        """
        if signal not in ("UP", "DOWN"):
            return None
        # Phase 26-03 Spot-5 — route clob_token_ids lookup via _get_market_meta
        # shim. Paper: extracted helper reads same public.markets row +
        # normalizes jsonb; live: gamma.get returns already-parsed list.
        # UP/DOWN->[0]/[1] index mapping stays here per CLAUDE.md inv #13
        # (controller owns business logic; data source is interchangeable).
        try:
            meta = await self._get_market_meta(condition_id)
        except MarketNotFoundError:
            return None
        except Exception:  # pragma: no cover — never block fill on DB miss
            return None
        tokens = meta.clob_token_ids
        if not isinstance(tokens, list) or len(tokens) < 2:
            return None
        try:
            idx = 0 if signal == "UP" else 1
            return int(tokens[idx])
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Phase 26-03 — Mode-routing shims for Polymarket data (D-05/D-06)
    # ------------------------------------------------------------------
    # Two thin shims fork hot-path reads on `self.mode == 'live'`:
    #   - live → TV-native (gamma_client / oracle), NEVER touches Storedata
    #   - paper → existing Storedata SQL (extracted to private helpers)
    #
    # D-07: live path is independent of Storedata writer-health probe
    # (COL-REMOTE-02). Writer-stale alerts continue firing for operator
    # visibility but never block live fires (per inv #13, Phase 26 SC #5).

    async def _read_storedata_market_meta(
        self, condition_id: str
    ) -> MarketMetadata | None:
        """Paper-mode metadata reader — extracted from Spot-4 (line 2402) and
        Spot-5 (line 2443). Verbatim SQL preserved from 26-03-DISCOVERY.md.

        Reads slug + clob_token_ids from ``public.markets`` in a single
        per-cid lookup. Returns None on DB-miss or pool unavailability
        (matches the prior "don't block on DB miss" semantics that
        ``_check_market_freshness`` and ``_resolve_token_id`` both relied
        on at their inline call sites).

        Fields gamma provides that Storedata does NOT (``accepting_orders``,
        ``end_date_iso``) default to safe values: ``accepting_orders=True``
        (paper executor never gates on this; safe default for callers that
        do not consult it) and ``end_date_iso=None`` (slug-suffix decoding
        in ``_check_market_freshness`` is the authoritative resolve-time
        source on the paper path).
        """
        if self.pool is None:
            return None
        # SQL: union of verbatim columns from Spot-4 (slug) + Spot-5
        # (clob_token_ids). Same FROM + WHERE + LIMIT semantics.
        sql = (
            "SELECT slug, clob_token_ids "
            "FROM public.markets "
            "WHERE platform = 'polymarket' AND condition_id = $1 "
            "LIMIT 1"
        )
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, condition_id)
        if row is None:
            return None
        slug = row.get("slug")
        if not slug:
            return None
        tokens_raw = row.get("clob_token_ids")
        tokens: list[str]
        if tokens_raw is None:
            tokens = []
        else:
            # asyncpg returns jsonb as Python str (raw JSON) or as
            # list/dict depending on codec configuration — normalize.
            if isinstance(tokens_raw, str):
                import json as _json

                try:
                    parsed = _json.loads(tokens_raw)
                except (ValueError, TypeError):
                    parsed = []
            else:
                parsed = tokens_raw
            if isinstance(parsed, list):
                tokens = [str(t) for t in parsed]
            else:
                tokens = []
        return MarketMetadata(
            condition_id=condition_id,
            slug=str(slug),
            clob_token_ids=tokens,
            accepting_orders=True,  # default — paper path never gates on this
            end_date_iso=None,      # default — paper path uses slug-suffix epoch
        )

    async def _read_storedata_resolution(
        self, condition_id: str
    ) -> ResolutionOutcome:
        """Paper-mode resolution reader — per-cid lookup against
        ``public.market_resolutions_v2`` mirroring the pattern used by
        ``engine/poly_updown_resolver.py`` (UNCHANGED in Phase 26).

        Outcome literal mapping (per 26-03-DISCOVERY.md ## Outcome Literal
        Mapping, verified by Spot-1/2/3 SQL ``IN ('Up','Down')`` filter):
            'Up'   → ResolutionOutcome.UP
            'Down' → ResolutionOutcome.DOWN
            anything else (NULL, '', disputed, ...) → UNRESOLVED (defensive)

        Routes via slug because ``public.market_resolutions_v2`` joins
        ``public.markets`` on slug, not condition_id (per Spot-1 JOIN). On
        any DB miss / pool unavailability / malformed row → UNRESOLVED so
        callers stay safe.
        """
        if self.pool is None:
            return ResolutionOutcome.UNRESOLVED
        # Per-cid resolution lookup: condition_id → slug via markets, then
        # outcome via market_resolutions_v2 (mirrors resolver pattern).
        sql = (
            "SELECT r.outcome "
            "FROM public.markets m "
            "JOIN public.market_resolutions_v2 r ON r.slug = m.slug "
            "WHERE m.platform = 'polymarket' AND m.condition_id = $1 "
            "LIMIT 1"
        )
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql, condition_id)
        except Exception:  # pragma: no cover — never block fill on DB miss
            return ResolutionOutcome.UNRESOLVED
        if row is None:
            return ResolutionOutcome.UNRESOLVED
        literal = row.get("outcome")
        # Verbatim literal mapping from 26-03-DISCOVERY.md.
        if literal == "Up":
            return ResolutionOutcome.UP
        if literal == "Down":
            return ResolutionOutcome.DOWN
        return ResolutionOutcome.UNRESOLVED

    async def _get_market_meta(self, condition_id: str) -> MarketMetadata:
        """Mode-routing shim: TV-native (gamma) on live, Storedata on paper.

        D-05 / D-07: live branch NEVER falls back to Storedata. On a live
        miss, raises ``MarketNotFoundError`` — callers translate to None
        if metadata-optional, propagate if metadata-required.
        """
        if self.mode == "live":
            if self._gamma_client is None:
                raise RuntimeError(
                    "live mode requires gamma_client injection (Phase 26-03 D-05)"
                )
            meta = await self._gamma_client.get(condition_id)
            if meta is None:
                raise MarketNotFoundError(condition_id)
            return meta
        meta = await self._read_storedata_market_meta(condition_id)
        if meta is None:
            raise MarketNotFoundError(condition_id)
        return meta

    async def _get_resolution(self, condition_id: str) -> ResolutionOutcome:
        """Mode-routing shim: on-chain oracle on live, Storedata on paper.

        D-06: live branch never falls back to Storedata — failures from the
        oracle propagate. See the shim-block header comment above for the
        D-07 independence rationale.
        """
        if self.mode == "live":
            if self._oracle is None:
                raise RuntimeError(
                    "live mode requires oracle injection (Phase 26-03 D-06)"
                )
            return await self._oracle.get_resolution(condition_id)
        return await self._read_storedata_resolution(condition_id)

    @staticmethod
    def _signal_ts(bars: list[Bar]) -> datetime:
        """Return the closing timestamp of the most recent bar."""
        if not bars:
            return datetime.now(UTC)
        last = bars[-1]
        ts = getattr(last, "bar_open", None)
        return ts if isinstance(ts, datetime) else datetime.now(UTC)

    # ------------------------------------------------------------------
    # Phase 18.1 — hedge-hold tick loop
    # ------------------------------------------------------------------

    # Per-tf bar window in seconds — used to compute slot resolve_unix
    # from the cached window_start_unix. Mirrors market_mapping._TF_SECONDS.
    _TF_SECONDS_BY_LABEL = {"5m": 5 * 60, "15m": 15 * 60}

    def _slot_resolve_unix(self, slot: Slot) -> int:
        """Return the unix-epoch seconds at which slot's market resolves.

        Polymarket UpDown slug epoch encodes window END = window_start +
        tf_seconds. We store window_start_unix on the slot at fill time;
        deriving resolve_unix from there avoids an extra DB lookup.
        """
        return slot.window_start_unix + self._TF_SECONDS_BY_LABEL.get(slot.tf, 5 * 60)

    async def _prune_resolved_slots(self, now_s: int) -> int:
        """Garbage-collect in-memory slots whose markets have resolved.

        Phase 18.1 forensics 2026-04-29: Slot.status='resolved' was in the
        type literal but never set anywhere in the codebase. The paper
        resolver writes to trading.events but does NOT touch this in-memory
        dict, so slots accumulated forever. _open_slots() kept returning
        them every 10s, generating spurious hedge_skipped_no_asks events
        against dead markets (254 in 31min on VPS2 between 18:44-19:21 UTC).

        Eviction rule: any slot whose computed resolve_unix is in the past
        is removed from the dict regardless of status. The resolver
        independently pays out PnL from the trading.events audit row.

        Phase 18.6 W1 — also unsubscribe both legs (yes + no) from the
        BookMirror BEFORE deleting the slot. Refcounted, so two slots
        sharing the same token only drop the WS subscription when both
        resolve. Method became async to support the await on unsubscribe.

        Returns the count of slots pruned (for observability).
        """
        to_remove: list[tuple[str, str, int]] = []
        for key, slot in self._slots.items():
            if self._slot_resolve_unix(slot) <= now_s:
                to_remove.append(key)
        for key in to_remove:
            slot = self._slots[key]
            # Unsubscribe both legs from BookMirror (refcounted; safe if not subscribed).
            if self._book_mirror is not None:
                for tok in (slot.yes_token_id, slot.no_token_id):
                    if tok is not None:
                        try:
                            await self._book_mirror.unsubscribe(str(tok))
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "poly_updown.book_mirror_unsubscribe_failed",
                                extra={"slot": slot.slot_id, "token_id": str(tok)},
                            )
            del self._slots[key]
        if to_remove:
            logger.info(
                "poly_updown.slots_pruned",
                extra={"count": len(to_remove), "now_s": now_s},
            )
        return len(to_remove)

    def _open_slots(self) -> list[Slot]:
        """Return slots whose status is in {open, held_no_hedge}.

        ``hedged_holding``, ``hedge_failed_held`` and ``resolved`` slots
        are excluded — they need no further hedge action. Note
        ``held_no_hedge`` is included so a slot whose first hedge attempt
        hit an empty book can re-try if liquidity returns.

        Phase 18.1 belt-and-suspenders: also exclude slots whose market's
        resolve_unix has passed even if _prune_resolved_slots hasn't run
        yet. _maybe_hedge will never query opposite books for dead markets.
        """
        now_s = int(time.time())
        return [
            s
            for s in self._slots.values()
            if s.status in ("open", "held_no_hedge") and self._slot_resolve_unix(s) > now_s
        ]

    async def on_tick(self) -> None:
        """Periodic ~10s reversal check across all open slots.

        Idempotent: ``hedged_holding`` slots are filtered out by
        ``_open_slots()`` and never see a second hedge attempt.
        Resolved slots are pruned at the top of each tick so the
        in-memory dict doesn't grow unbounded over a long shadow run.

        Phase 18.5 — branches on ``self.hedge_policy``:
          * ``HEDGE_HOLD`` — V1 default. Calls ``_maybe_hedge``.
          * ``HYBRID``    — V2. ``_maybe_hedge`` (which falls into
            ``_try_bid_exit`` on opposite-asks empty).
          * ``HOLD_ONLY`` — momo HOLD. No-op; slot held to resolution.
          * ``SELL_BID``  — momo SELL. Calls ``_maybe_sell_at_bid`` —
            rev_bp check + delegate to ``_try_bid_exit``.
        """
        now_s = int(time.time())
        await self._prune_resolved_slots(now_s)
        # Phase 23 · D-26: close any open shadow_simulated entries whose
        # bar boundary has passed. Best-effort; never raises. Runs before
        # the HOLD_ONLY early-out so shadow resolution still fires for
        # the V3-portfolio HOLD_ONLY policy variant.
        try:
            shadow_sleeve_id = (
                f"poly_updown_btc_5m_{self.strategy_mode}"
            )
            await self._resolve_pending_shadow_entries(shadow_sleeve_id)
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "poly_updown.resolve_pending_shadow_entries_failed",
                exc_info=True,
            )
        if self.hedge_policy == "HOLD_ONLY":
            return  # GC + shadow resolution already done; nothing else to do.
        for slot in self._open_slots():
            try:
                if self.hedge_policy == "SELL_BID":
                    await self._maybe_sell_at_bid(slot)
                else:
                    # HEDGE_HOLD or HYBRID
                    await self._maybe_hedge(slot)
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "poly_updown.on_tick_action_failed",
                    extra={
                        "slot": slot.slot_id,
                        "hedge_policy": self.hedge_policy,
                    },
                )

    @staticmethod
    def _now_iso_utc() -> str:
        # Phase 23 D-24: ISO-8601 UTC timestamp helper for shadow audit
        # row payloads. Distinct from `datetime.now(UTC).isoformat()`
        # callers elsewhere so we can override in tests via freezegun
        # without touching the rest of the controller.
        return datetime.now(UTC).isoformat()

    async def _audit_shadow_simulated(
        self,
        slot: Slot,
        *,
        reason: str,
        entry_price: float,
        qty: float,
        signal_strength: float | None = None,
        **extra: Any,
    ) -> None:
        """Phase 23 · D-22 / D-23 / D-24 / D-25.

        Write a shadow-entry row when a rail blocks (or would-have-blocked)
        a signal that would otherwise have fired. Paired with
        ``_audit_shadow_paper_resolved`` on the next bar boundary (D-24, D-26).

        kind='shadow_simulated' (entry phase). Best-effort — pool=None or
        insert failure is logged + swallowed; mirrors the
        ``_audit_hedge_skip`` audit-must-not-mask discipline (lines 1170-1257).
        """
        if self.pool is None:
            return
        sleeve_agg_id = (
            f"poly_updown_{slot.symbol.lower()}_{slot.tf}_{self.strategy_mode}"
        )
        payload: dict[str, Any] = {
            "slot_id": slot.slot_id,
            "condition_id": slot.condition_id,
            "signal": slot.signal,
            "reason": reason,
            "mode": self.mode,
            "entry_price": float(entry_price),
            "qty": float(qty),
            "entry_ts": self._now_iso_utc(),
            "bar_close_ts": getattr(slot, "bar_close_ts", None),
        }
        if signal_strength is not None:
            payload["signal_strength"] = float(signal_strength)
        for k, v in extra.items():
            if v is not None:
                payload[k] = v
        try:
            import json
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, 'shadow_simulated', $2::jsonb)",
                    sleeve_agg_id,
                    json.dumps(payload, default=str),
                )
        except Exception:  # pragma: no cover — audit must not mask hedge logic
            logger.debug(
                "poly_updown.shadow_simulated_audit_emit_failed",
                extra={"slot": slot.slot_id, "reason": reason},
            )

    async def _audit_shadow_paper_resolved(
        self,
        slot: Slot,
        *,
        exit_price: float,
        realized_pnl_usd: float,
        bar_close_ts: str | None = None,
        **extra: Any,
    ) -> None:
        """Phase 23 · D-26 — paired exit row.

        Fires at the next bar boundary for any sleeve that emitted a
        ``shadow_simulated`` row at entry. The ``/shadow/sleeves/{id}``
        endpoint joins entries and exits via (sleeve_id, slot_id) per
        PATTERNS.md §shadow.py canonical SQL.

        kind='shadow_simulated_exit'. Best-effort.
        """
        if self.pool is None:
            return
        sleeve_agg_id = (
            f"poly_updown_{slot.symbol.lower()}_{slot.tf}_{self.strategy_mode}"
        )
        payload: dict[str, Any] = {
            "slot_id": slot.slot_id,
            "condition_id": slot.condition_id,
            "exit_price": float(exit_price),
            "realized_pnl_usd": float(realized_pnl_usd),
            "bar_close_ts": (
                bar_close_ts or getattr(slot, "bar_close_ts", None)
            ),
            "exit_ts": self._now_iso_utc(),
        }
        for k, v in extra.items():
            if v is not None:
                payload[k] = v
        try:
            import json
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, 'shadow_simulated_exit', $2::jsonb)",
                    sleeve_agg_id,
                    json.dumps(payload, default=str),
                )
        except Exception:  # pragma: no cover — audit must not mask hedge logic
            logger.debug(
                "poly_updown.shadow_simulated_exit_audit_emit_failed",
                extra={"slot": slot.slot_id},
            )

    async def _audit_shadow_counterfactual(
        self,
        slot: Slot,
        *,
        signal_strength: float,
        armed: bool = False,
        **extra: Any,
    ) -> None:
        """Phase 23 · D-23 — sleeves NOT armed live but tracked for comparison.

        Fires every signal evaluation on _sniper / _v3 sleeves when their
        bundle is unfunded OR paused (mode='shadow'). Provides the dataset
        for the ShadowPnlStrip live-vs-shadow comparison (UI-SPEC §5.13).

        kind='shadow_counterfactual'. Best-effort.
        """
        if self.pool is None:
            return
        sleeve_agg_id = (
            f"poly_updown_{slot.symbol.lower()}_{slot.tf}_{self.strategy_mode}"
        )
        payload: dict[str, Any] = {
            "slot_id": slot.slot_id,
            "condition_id": slot.condition_id,
            "signal": slot.signal,
            "signal_strength": float(signal_strength),
            "armed": bool(armed),
            "mode": self.mode,
            "ts": self._now_iso_utc(),
        }
        for k, v in extra.items():
            if v is not None:
                payload[k] = v
        try:
            import json
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, 'shadow_counterfactual', $2::jsonb)",
                    sleeve_agg_id,
                    json.dumps(payload, default=str),
                )
        except Exception:  # pragma: no cover — audit must not mask hedge logic
            logger.debug(
                "poly_updown.shadow_counterfactual_audit_emit_failed",
                extra={"slot": slot.slot_id},
            )

    async def _resolve_pending_shadow_entries(self, sleeve_id: str) -> None:
        """Phase 23 · D-26 — close shadow_simulated rows past their bar boundary.

        At each tick, page through the most-recent N unresolved
        ``shadow_simulated`` rows for ``sleeve_id`` and write a paired
        ``shadow_simulated_exit`` row using the next-bar mid (D-25). Belt-
        and-suspenders against the two-phase-write race (T-23-04-04):
        any entry whose bar boundary has passed gets retroactively closed.

        Best-effort — never raises; failure modes (pool error, executor
        error, mapping miss) all log at debug and continue.
        """
        if self.pool is None:
            return
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT e.data->>'slot_id' AS slot_id, "
                    "       (e.data->>'entry_price')::numeric AS entry_price, "
                    "       (e.data->>'qty')::numeric AS qty, "
                    "       e.data->>'bar_close_ts' AS bar_close_ts, "
                    "       e.data->>'condition_id' AS condition_id "
                    "FROM trading.events e "
                    "WHERE e.sleeve_id = $1 "
                    "  AND e.kind = 'shadow_simulated' "
                    "  AND ((e.data->>'bar_close_ts')::timestamptz IS NULL "
                    "       OR (e.data->>'bar_close_ts')::timestamptz <= now()) "
                    "  AND NOT EXISTS ( "
                    "      SELECT 1 FROM trading.events x "
                    "      WHERE x.sleeve_id = e.sleeve_id "
                    "        AND x.kind = 'shadow_simulated_exit' "
                    "        AND x.data->>'slot_id' = e.data->>'slot_id' "
                    "  ) "
                    "ORDER BY e.at DESC LIMIT 50",
                    sleeve_id,
                )
        except Exception:  # pragma: no cover — sweep must not crash the loop
            logger.debug(
                "poly_updown.shadow_resolution_sweep_query_failed",
                extra={"sleeve": sleeve_id},
            )
            return
        # sleeve_id form: poly_updown_<sym>_<tf>_<mode>
        parts = sleeve_id.split("_")
        sym_part = parts[2].upper() if len(parts) >= 4 else "BTC"
        tf_part = parts[3] if len(parts) >= 4 else "5m"
        for r in rows:
            try:
                snap = await self.executor.get_orderbook_snapshot(
                    int(r["condition_id"]) if str(r["condition_id"]).isdigit()
                    else r["condition_id"],
                )
            except Exception:  # pragma: no cover — defensive
                continue
            if not snap:
                continue
            bids = snap.get("bids") or []
            asks = snap.get("asks") or []
            if not bids or not asks:
                continue
            try:
                top_bid = Decimal(str(bids[0]["price"]))
                top_ask = Decimal(str(asks[0]["price"]))
            except (TypeError, KeyError, InvalidOperation):
                continue
            mid = (top_bid + top_ask) / Decimal("2")
            try:
                entry = Decimal(str(r["entry_price"] or 0))
                qty = Decimal(str(r["qty"] or 0))
            except (TypeError, InvalidOperation):
                continue
            realized = float((mid - entry) * qty) if entry > 0 else 0.0
            # Reuse Slot dataclass to satisfy _audit_shadow_paper_resolved
            # signature without inventing a parallel type.
            stub_slot = Slot(
                sleeve_id=sleeve_id,
                symbol=sym_part,
                tf=tf_part,
                condition_id=str(r["condition_id"] or ""),
                signal="UP",  # placeholder; exit row doesn't carry direction
                entry_price=entry if entry > 0 else Decimal("0"),
                entry_qty=qty,
                btc_close_at_ws=Decimal("0"),
                binance_symbol_id="",
                slot_id=str(r["slot_id"] or ""),
            )
            try:
                await self._audit_shadow_paper_resolved(
                    stub_slot,
                    exit_price=float(mid),
                    realized_pnl_usd=realized,
                    bar_close_ts=str(r["bar_close_ts"] or ""),
                )
            except Exception:  # pragma: no cover — defensive
                logger.debug(
                    "poly_updown.shadow_resolution_emit_failed",
                    extra={"sleeve": sleeve_id, "slot": r["slot_id"]},
                )

    async def _maybe_sell_at_bid(self, slot: Slot) -> None:
        """Phase 18.5 (momo SELL_BID policy): rev_bp check + delegate to bid-exit.

        Mirrors ``_maybe_hedge`` for the staleness + Binance close + rev_bp
        gate, then delegates to ``_try_bid_exit`` (which already implements
        the sell-at-best-bid algorithm with VEN-09 ``side='sell'`` enforcement
        for both paper and live executors). Skips the opposite-ask leg of
        HEDGE_HOLD/HYBRID entirely — sell our own held side at the bid.

        Same idempotency contract as ``_maybe_hedge``: ``_open_slots()``
        filters by ``status == 'open'`` so an already-exited slot won't be
        re-attempted.
        """
        if slot.btc_close_at_ws == 0 or slot.binance_symbol_id == "":
            return

        now_s = int(time.time())
        try:
            close_with_ts = await fetch_close_with_ts_asof(
                slot.binance_symbol_id, "1MIN", now_s,
                pool=self.pool, source=KLINE_SOURCE,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "poly_updown.btc_now_fetch_failed_sell_bid",
                extra={"slot": slot.slot_id},
            )
            return

        if close_with_ts is None:
            return
        btc_now, bar_us = close_with_ts

        bar_age_s = now_s - (bar_us // 1_000_000)
        if bar_age_s > STALE_BINANCE_FEED_SECONDS:
            await self._audit_hedge_skip(
                slot,
                reason="stale_feed",
                bar_age_s=bar_age_s,
                hedge_policy_branch="sell_bid",
            )
            return

        bps = float(
            (Decimal(btc_now) - Decimal(slot.btc_close_at_ws))
            / Decimal(slot.btc_close_at_ws)
            * Decimal(10_000)
        )

        reverted = (slot.signal == "UP" and bps <= -REV_BP_THRESHOLD) or (
            slot.signal == "DOWN" and bps >= REV_BP_THRESHOLD
        )
        if not reverted:
            return

        # Reuse the existing sell-at-bid implementation. The audit row
        # written by _try_bid_exit (or its failure path in _audit_hedge_skip)
        # carries prior_branch="sell_bid_policy" so analyses can group by
        # exit-policy variant.
        await self._try_bid_exit(slot, bps, prior_branch="sell_bid_policy")

    async def _audit_hedge_skip(
        self,
        slot: Slot,
        reason: str,
        *,
        bps: float | None = None,
        bar_age_s: int | None = None,
        book_ts: int | None = None,
        book_age_s: int | None = None,
        book_source: str | None = None,
        opposite_outcome: str | None = None,
        attempts: int | None = None,
        last_error: str | None = None,
        # Phase 18.2 V2 HYBRID extras (passed by _try_bid_exit). Generic
        # **extra catches any other branch-specific fields without
        # requiring a schema change every time we add forensic context.
        prior_branch: str | None = None,
        exit_branch: str | None = None,
        exit_status: str | None = None,
        **extra: Any,
    ) -> None:
        """Write a structured trading.events audit row for a hedge skip.

        Phase 18.1 forensics 2026-04-28: previously ``hedge_skipped_no_asks``
        and friends were bare structlog strings, so debugging required
        SSH-and-grep. Promoting to ``trading.events`` rows lets the
        dashboard surface a per-sleeve hedge_skip_count_24h and the
        operator query rate/causes via SQL.

        Phase 18.2 V2: HYBRID branch 2 (sell-own-bid) and branch 3 (both
        failed) flow through here too. The ``prior_branch``, ``exit_branch``,
        and ``exit_status`` kwargs surface why the bid-exit was attempted
        and why it failed (no_bids, sell_rejected, zero_bid, etc.).

        Best-effort — pool=None or insert failure is logged + swallowed
        to avoid masking the hedge decision itself.
        """
        if self.pool is None:
            return
        # Mirrors _audit suffix scheme: volume / sniper / v3 / momo_<policy>.
        if self.strategy_mode == "momo":
            policy_suffix = _HEDGE_POLICY_SUFFIX[self.hedge_policy]
            sleeve_agg_id = (
                f"poly_updown_{slot.symbol.lower()}_{slot.tf}_momo_{policy_suffix}{self._f7_suffix}"
            )
        elif self.strategy_mode == "momo_v2":
            policy_suffix = _HEDGE_POLICY_SUFFIX[self.hedge_policy]
            sleeve_agg_id = (
                f"poly_updown_{slot.symbol.lower()}_{slot.tf}_momo_v2_{policy_suffix}{self._f7_suffix}"
            )
        else:
            sleeve_agg_id = (
                f"poly_updown_{slot.symbol.lower()}_{slot.tf}_{self.strategy_mode}"
            )
        # Phase 26.3 D-02 — live-mirror controllers tag hedge_skip audit
        # rows with ``_LIVE`` so dashboard A/B queries match the entry/
        # exit row suffix from _sleeve_id().
        if getattr(self, "_is_live_mirror", False):
            sleeve_agg_id = f"{sleeve_agg_id}_LIVE"
        payload: dict[str, Any] = {
            "slot_id": slot.slot_id,
            "condition_id": slot.condition_id,
            "signal": slot.signal,
            "reason": reason,
            "mode": self.mode,
        }
        if bps is not None:
            payload["bps"] = bps
        if bar_age_s is not None:
            payload["bar_age_s"] = bar_age_s
        if book_ts is not None:
            payload["book_ts"] = book_ts
        if book_age_s is not None:
            payload["book_age_s"] = book_age_s
        if book_source is not None:
            payload["book_source"] = book_source
        if opposite_outcome is not None:
            payload["opposite_outcome"] = opposite_outcome
        if attempts is not None:
            payload["attempts"] = attempts
        if last_error is not None:
            payload["last_error"] = last_error
        # Phase 18.2 V2 HYBRID extras.
        if prior_branch is not None:
            payload["prior_branch"] = prior_branch
        if exit_branch is not None:
            payload["exit_branch"] = exit_branch
        if exit_status is not None:
            payload["exit_status"] = exit_status
        for k, v in extra.items():
            if v is not None:
                payload[k] = v
        try:
            import json

            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, 'poly_updown_hedge_skip', $2::jsonb)",
                    sleeve_agg_id,
                    json.dumps(payload),
                )
        except Exception:  # pragma: no cover — audit must not mask hedge logic
            logger.debug(
                "poly_updown.hedge_skip_audit_emit_failed",
                extra={"slot": slot.slot_id, "reason": reason},
            )

    async def _maybe_hedge(self, slot: Slot) -> None:
        """Detect Binance reversal ≥ REV_BP_THRESHOLD; place opposite-side hedge.

        Algorithm (RESEARCH §2 + §7):
        1. Read latest 1MIN close for slot.binance_symbol_id.
        2. If feed stale (>2 min) OR data missing → log + return.
        3. Compute bps = (btc_now - btc_at_ws) / btc_at_ws * 10_000.
        4. Reverted iff (UP & bps ≤ -REV_BP_THRESHOLD) or
                       (DOWN & bps ≥ +REV_BP_THRESHOLD).
        5. Not reverted → return; slot stays open.
        6. Otherwise: fetch opposite-token book; if asks empty → mark
           ``held_no_hedge`` and return.
        7. Place opposite-side buy at best ask, qty = entry_qty.
           Retry up to 3× with 200ms backoff on rejection.
        8. On success: ``slot.status = 'hedged_holding'``,
           ``slot.hedge_other_entry_price = other_ask_price``.

        Phase 18.4 Q5 — Inverse sleeves are paper-only shadow; HARD-skip
        hedge regardless of TV_POLY_HEDGE_POLICY env. The guard fires on
        the slot's sleeve_id naming (any sleeve_id ending ``_INV`` or
        ``_INV_NIGHT``) so it short-circuits even if a future code path
        somehow hands a non-inverse controller an inverse slot.

        Phase 26.3 D-04 — Live-mirror inverse sleeves carry the ``_LIVE``
        suffix on their slot.sleeve_id (e.g. ``..._sniper_INV_LIVE``),
        which is_inverse_sleeve() no longer matches. Short-circuit on
        the controller's ``_is_live_mirror`` flag combined with its
        ``_inverse_kind`` so live-mirror inverse twins ride to resolution
        without hedge attempt and without polluting the audit table with
        hedge_skip rows.
        """
        if getattr(self, "_is_live_mirror", False) and self._inverse_kind is not None:
            return  # D-04 silent skip: live mirror inverse, ride to resolution
        if is_inverse_sleeve(slot.sleeve_id):
            return
        if slot.btc_close_at_ws == 0 or slot.binance_symbol_id == "":
            return

        now_s = int(time.time())
        try:
            # SHADOW-RUN-1 fix #7: use bar timestamp for staleness, not
            # Decimal price-equality (which gave false positives on flat
            # OKX 1MIN windows where consecutive minutes had identical
            # prices).
            close_with_ts = await fetch_close_with_ts_asof(
                slot.binance_symbol_id, "1MIN", now_s, pool=self.pool, source=KLINE_SOURCE
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "poly_updown.btc_now_fetch_failed",
                extra={"slot": slot.slot_id},
            )
            return

        if close_with_ts is None:
            return
        btc_now, bar_us = close_with_ts

        bar_age_s = now_s - (bar_us // 1_000_000)
        if bar_age_s > STALE_BINANCE_FEED_SECONDS:
            logger.info(
                "poly_updown.hedge_check_skipped_stale_feed",
                extra={"slot": slot.slot_id, "bar_age_s": bar_age_s},
            )
            await self._audit_hedge_skip(
                slot,
                reason="stale_feed",
                bar_age_s=bar_age_s,
            )
            return

        bps = float(
            (Decimal(btc_now) - Decimal(slot.btc_close_at_ws))
            / Decimal(slot.btc_close_at_ws)
            * Decimal(10_000)
        )

        reverted = (slot.signal == "UP" and bps <= -REV_BP_THRESHOLD) or (
            slot.signal == "DOWN" and bps >= REV_BP_THRESHOLD
        )
        if not reverted:
            return

        # Determine opposite outcome side. UP slot bought YES → hedge buys NO.
        opposite_outcome = "NO" if slot.signal == "UP" else "YES"

        book = await self._fetch_opposite_book(slot, opposite_outcome)
        if not book or not book.get("asks"):
            logger.warning(
                "poly_updown.hedge_skipped_no_asks",
                extra={"slot": slot.slot_id, "side": slot.signal},
            )
            book_ts = int(book.get("ts", 0)) if book else 0
            # Phase 18.6 W0 — surface which fetch tier answered (or empty).
            # Lets §Validation queries quantify CLOB-vs-Storedata-vs-empty
            # distribution post-deploy + becomes ws_mirror once Wave 1 lands.
            book_source = book.get("_source") if book else None
            await self._audit_hedge_skip(
                slot,
                reason="no_asks",
                bps=bps,
                book_ts=book_ts,
                book_age_s=(now_s - book_ts) if book_ts else None,
                book_source=book_source,
                opposite_outcome=opposite_outcome,
            )
            # Phase 18.2 V2 HYBRID branch 2: try sell-own-bid as fallback.
            if HEDGE_POLICY == "HYBRID":
                await self._try_bid_exit(slot, bps, prior_branch="hedge_no_asks")
                return
            slot.status = "held_no_hedge"
            return

        first_ask = book["asks"][0]
        try:
            other_ask_price = Decimal(str(first_ask.get("price", "0")))
        except Exception:  # pragma: no cover - defensive
            return
        if other_ask_price <= 0:
            await self._audit_hedge_skip(
                slot,
                reason="zero_price_ask",
                bps=bps,
                opposite_outcome=opposite_outcome,
            )
            slot.status = "held_no_hedge"
            return

        # SHADOW-RUN-1 fix #5: resolve OPPOSITE-side token_id from
        # public.markets.clob_token_ids (mirror of _place_entry's pattern).
        # Phase 15 hedge path used condition_id+outcome kwargs that the
        # executor signature doesn't accept (TypeError if hedge ever fired).
        # opposite_outcome → use the inverted signal direction for the
        # token_id index (UP slot bought YES → hedge buys NO = signal DOWN).
        opposite_signal: SignalResult = "DOWN" if slot.signal == "UP" else "UP"
        opposite_token_id = await self._resolve_token_id(
            slot.condition_id,
            opposite_signal,
        )
        # Phase 18.6 W1 — lazy-subscribe opposite-side to BookMirror so
        # subsequent hedge ticks read from the in-memory mirror (<10ms)
        # instead of CLOB HTTP. Also cache on slot so _prune_resolved_slots
        # can unsubscribe at GC.
        if opposite_token_id is not None:
            if slot.signal == "UP":
                slot.no_token_id = opposite_token_id
            else:
                slot.yes_token_id = opposite_token_id
            if self._book_mirror is not None:
                try:
                    await self._book_mirror.subscribe(str(opposite_token_id))
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "poly_updown.book_mirror_opposite_subscribe_failed",
                        extra={"slot": slot.slot_id, "token_id": str(opposite_token_id)},
                    )
        if opposite_token_id is None:
            logger.warning(
                "poly_updown.hedge_token_id_lookup_failed",
                extra={
                    "slot": slot.slot_id,
                    "cid": slot.condition_id,
                    "opposite_outcome": opposite_outcome,
                },
            )
            await self._audit_hedge_skip(
                slot,
                reason="token_id_lookup_failed",
                bps=bps,
                opposite_outcome=opposite_outcome,
            )
            slot.status = "hedge_failed_held"
            return

        # Retry-with-backoff on hedge order rejection (RESEARCH §7).
        sleeve_id = self._sleeve_id(slot.symbol, slot.tf, opposite_outcome)
        last_exc: Exception | None = None
        for _attempt in range(HEDGE_RETRY_ATTEMPTS):
            try:
                result = await self.executor.place_entry_order(
                    token_id=opposite_token_id,
                    qty=slot.entry_qty,
                    limit_px=other_ask_price,
                    sleeve_id=sleeve_id,
                    side="buy",
                )
            except Exception as exc:  # pragma: no cover - retried below
                last_exc = exc
                await asyncio.sleep(HEDGE_RETRY_BACKOFF_S)
                continue

            status = getattr(result, "status", None)
            status_str = str(status).lower() if status is not None else ""
            if "rejected" in status_str:
                last_exc = RuntimeError(f"hedge order rejected: {result!r}")
                await asyncio.sleep(HEDGE_RETRY_BACKOFF_S)
                continue

            # Success path.
            slot.status = "hedged_holding"
            slot.hedge_other_entry_price = other_ask_price
            logger.info(
                "poly_updown.slot_hedged",
                extra={
                    "slot": slot.slot_id,
                    "signal": slot.signal,
                    "entry_price": str(slot.entry_price),
                    "hedge_entry_price": str(other_ask_price),
                    "bps": bps,
                },
            )
            # Phase 18.1 paper resolver dependency: write a trading.events
            # row for the hedge fill so the resolver can detect hedged
            # slots from DB alone (in-memory slot.hedge_other_entry_price
            # is restart-fragile). reason='hedge_placed' + the same
            # condition_id keys it back to the original entry. The fill
            # event_id of THIS audit row carries the hedge price.
            # publish_bar_processed=False so the dashboard's signal display
            # doesn't flip to the hedge direction (which would mislead — the
            # original momentum bet still stands; the hedge is a stop, not
            # a new directional view).
            try:
                hedge_qty_raw = (getattr(result, "raw_response", None) or {}).get("filled")
                hedge_avg_price = (getattr(result, "raw_response", None) or {}).get(
                    "avg_price"
                ) or str(other_ask_price)
                await self._audit(
                    slot.symbol,
                    slot.tf,
                    reason="hedge_placed",
                    signal=opposite_signal,
                    condition_id=slot.condition_id,
                    fill_status="filled",
                    fill_qty=str(hedge_qty_raw)
                    if hedge_qty_raw is not None
                    else str(slot.entry_qty),
                    fill_price=str(hedge_avg_price),
                    qty_intended=str(slot.entry_qty),
                    publish_bar_processed=False,
                )
            except Exception:  # pragma: no cover — audit must not mask hedge success
                logger.exception(
                    "poly_updown.hedge_audit_emit_failed",
                    extra={"slot": slot.slot_id, "cid": slot.condition_id},
                )
            return

        # All retries exhausted on opposite-side buy.
        logger.warning(
            "poly_updown.hedge_failed_held",
            extra={
                "slot": slot.slot_id,
                "attempts": HEDGE_RETRY_ATTEMPTS,
                "last_error": str(last_exc) if last_exc else None,
            },
        )
        await self._audit_hedge_skip(
            slot,
            reason="failed_held",
            bps=bps,
            opposite_outcome=opposite_outcome,
            attempts=HEDGE_RETRY_ATTEMPTS,
            last_error=str(last_exc) if last_exc else None,
        )
        # Phase 18.2 V2 HYBRID branch 2: try sell-own-bid even after the buy
        # path exhausted retries. The exit branch is independent of why the
        # opposite-side buy failed.
        if HEDGE_POLICY == "HYBRID":
            await self._try_bid_exit(slot, bps, prior_branch="hedge_retries_exhausted")
            return
        slot.status = "hedge_failed_held"

    async def _fetch_opposite_book(
        self, slot: Slot, opposite_outcome: str
    ) -> dict[str, Any] | None:
        """Fetch the opposite-side orderbook for the hot-path hedge tick.

        2026-05-09 Fix A — Phase 18.6 W1 audit (24h on VPS3 main):
            ws_mirror sourced:  618  / 1,696 hedge_skip events  ( 36%)
            CLOB REST sourced: 1,042 / 1,696 hedge_skip events  ( 61%)
            Storedata  Tier-3:  ~36 / 1,696 hedge_skip events  (  3%)

        61% of hedge decisions were silently using REST because the
        executor's 3-tier dispatcher fell through to CLOB whenever WS
        BookMirror returned None (subscribed but no snapshot received
        yet, or token not yet subscribed, or WS disconnected). REST
        for hot-path is wrong by design — by the time CLOB returns
        "no asks", the directional flow that swept the side has already
        completed, so the answer is always "empty" but stale-empty.

        Fix: read DIRECTLY from BookMirror. If WS is ready → use it
        (truthful, may be empty if liquidity genuinely gone). If WS is
        not ready → skip this tick (return ws_not_ready sentinel; the
        next 10s tick retries). NEVER touch CLOB REST on hot path.

        Fallback to executor path is preserved ONLY for:
        - Unit tests that mock ``get_orderbook_for_outcome``
        - W0 deployments where ``self._book_mirror`` is None
        """
        # Test-mode shortcut: in-memory mocks expose this method.
        get_for_outcome = getattr(self.executor, "get_orderbook_for_outcome", None)
        if get_for_outcome is not None:
            try:
                return await get_for_outcome(slot.condition_id, opposite_outcome)
            except Exception:  # pragma: no cover - defensive
                pass

        token_id = slot.no_token_id if slot.signal == "UP" else slot.yes_token_id
        if token_id is None:
            return None

        # Fix A: WS-only hot path (no REST fallback).
        if self._book_mirror is not None:
            ws_book = self._book_mirror.get(str(token_id))
            if ws_book is not None:
                ws_book["_source"] = "ws_mirror"
                return ws_book
            # WS not ready → empty book with sentinel source so audit
            # row distinguishes ws_not_ready from genuine no_asks.
            return {"bids": [], "asks": [], "ts": 0, "_source": "ws_not_ready"}

        # No book_mirror configured (W0 / tests without mirror): fall back
        # to executor's 3-tier dispatcher (legacy behaviour).
        try:
            return await self.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover - defensive
            return None

    async def _fetch_own_book(self, slot: Slot, own_outcome: str) -> dict[str, Any] | None:
        """Phase 18.2 V2 HYBRID: fetch the orderbook for the side we hold.

        Mirror of ``_fetch_opposite_book`` for branch 2 (sell-own-bid). UP
        slot bought YES → ``own_outcome='YES'`` → returns YES book; we'll
        lift the bids. Inverse for DOWN slots.

        2026-05-09 Fix A — same WS-only hot-path constraint as
        ``_fetch_opposite_book``. See its docstring for the audit-data
        evidence and rationale.
        """
        get_for_outcome = getattr(self.executor, "get_orderbook_for_outcome", None)
        if get_for_outcome is not None:
            try:
                return await get_for_outcome(slot.condition_id, own_outcome)
            except Exception:  # pragma: no cover - defensive
                pass

        token_id = slot.yes_token_id if slot.signal == "UP" else slot.no_token_id
        if token_id is None:
            return None

        # Fix A: WS-only hot path (no REST fallback).
        if self._book_mirror is not None:
            ws_book = self._book_mirror.get(str(token_id))
            if ws_book is not None:
                ws_book["_source"] = "ws_mirror"
                return ws_book
            return {"bids": [], "asks": [], "ts": 0, "_source": "ws_not_ready"}

        # No book_mirror configured: fall back to executor.
        try:
            return await self.executor.get_orderbook_snapshot(token_id)
        except Exception:  # pragma: no cover - defensive
            return None

    async def _try_bid_exit(self, slot: Slot, bps: float, prior_branch: str) -> bool:
        """Phase 18.2 V2 HYBRID branch 2: sell our held side at the bid.

        Fires when branch 1 (buy opposite ask) fails for any reason — empty
        opposite-asks book, retries exhausted, etc. Returns True iff the
        sell filled (any partial counts); slot.status set accordingly.

        On success:
            - ``slot.status = 'exited_at_bid'``
            - ``slot.exit_price`` / ``exit_shares`` / ``exit_proceeds_usd`` populated
            - audit row with ``reason='exited_at_bid'``

        On failure (no bids, sell rejected, etc.):
            - ``slot.status = 'held_no_hedge_no_exit'``
            - audit row with ``reason='hedge_and_exit_both_failed'``
        """
        own_outcome = "YES" if slot.signal == "UP" else "NO"
        own_token = slot.yes_token_id if slot.signal == "UP" else slot.no_token_id
        now_s = int(time.time())

        # Phase 18.2 production-trace fix (2026-04-29): Slot.yes/no_token_id
        # are NOT populated at entry time (controller's _place_entry never
        # sets them). The buy-opposite hedge path at line 1147 calls
        # _resolve_token_id(condition_id, signal) dynamically — mirror that
        # here so branch 2 doesn't always fall through to branch 3 with
        # ``own_token_missing`` because of an in-memory state gap.
        #
        # Critical: ALSO write the resolved token back to the slot so the
        # subsequent _fetch_own_book(slot, own_outcome) lookup sees it.
        # _fetch_own_book reads slot.yes_token_id / slot.no_token_id; if
        # those stay None we get an empty book and fall through to
        # branch 3 with exit_branch='no_bids' — which masks the real
        # alpha (own-side bids almost always exist on healthy markets).
        if own_token is None:
            try:
                # UP slot bought YES → own_token = YES token (signal stays UP).
                # DOWN slot bought NO → own_token = NO token (signal stays DOWN).
                own_token = await self._resolve_token_id(
                    slot.condition_id,
                    slot.signal,
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception(
                    "poly_updown.bid_exit_resolve_token_failed",
                    extra={"slot": slot.slot_id, "cid": slot.condition_id},
                )
                own_token = None
            # Cache on slot so subsequent lookups (_fetch_own_book + the
            # place_exit_order call below) hit the populated field.
            # Phase 18.6 W1 — also subscribe to BookMirror so subsequent
            # bid-exit reads hit the in-memory mirror (<10ms).
            if own_token is not None:
                if slot.signal == "UP":
                    slot.yes_token_id = own_token
                else:
                    slot.no_token_id = own_token
                if self._book_mirror is not None:
                    try:
                        await self._book_mirror.subscribe(str(own_token))
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "poly_updown.book_mirror_own_subscribe_failed",
                            extra={"slot": slot.slot_id, "token_id": str(own_token)},
                        )

        if own_token is None:
            slot.status = "held_no_hedge_no_exit"
            await self._audit_hedge_skip(
                slot,
                reason="hedge_and_exit_both_failed",
                bps=bps,
                prior_branch=prior_branch,
                exit_branch="own_token_missing",
            )
            return False

        # Fix B (2026-05-09): retry up to BID_EXIT_RETRY_ATTEMPTS times if
        # WS bid book is empty/not-ready at first read. Catches transient
        # WS-staleness gaps that pre-fix dropped to held_no_hedge_no_exit
        # immediately. Backoff 100ms between attempts (300ms worst case
        # vs 10s tick budget). Telemetry: if final attempt still empty,
        # the audit row carries `attempts=3` so we can quantify how often
        # the retry actually saved a SELL.
        book_own: dict[str, Any] | None = None
        last_book_source: str | None = None
        for attempt in range(1, BID_EXIT_RETRY_ATTEMPTS + 1):
            book_own = await self._fetch_own_book(slot, own_outcome)
            if book_own and book_own.get("bids"):
                break  # bid book is populated — proceed to sell
            last_book_source = (
                book_own.get("_source") if book_own else None
            )
            if attempt < BID_EXIT_RETRY_ATTEMPTS:
                logger.info(
                    "poly_updown.bid_exit_no_bids_retry",
                    extra={
                        "slot": slot.slot_id,
                        "attempt": attempt,
                        "book_source": last_book_source,
                    },
                )
                await asyncio.sleep(BID_EXIT_RETRY_BACKOFF_S)
        if not book_own or not book_own.get("bids"):
            slot.status = "held_no_hedge_no_exit"
            await self._audit_hedge_skip(
                slot,
                reason="hedge_and_exit_both_failed",
                bps=bps,
                prior_branch=prior_branch,
                exit_branch="no_bids",
                book_ts=int(book_own.get("ts", 0)) if book_own else 0,
                book_source=last_book_source,
                attempts=BID_EXIT_RETRY_ATTEMPTS,
            )
            return False

        first_bid = book_own["bids"][0]
        try:
            own_bid_price = Decimal(str(first_bid.get("price", "0")))
        except Exception:  # pragma: no cover - defensive
            slot.status = "held_no_hedge_no_exit"
            await self._audit_hedge_skip(
                slot,
                reason="hedge_and_exit_both_failed",
                bps=bps,
                prior_branch=prior_branch,
                exit_branch="bid_parse_error",
            )
            return False

        if own_bid_price <= 0:
            slot.status = "held_no_hedge_no_exit"
            await self._audit_hedge_skip(
                slot,
                reason="hedge_and_exit_both_failed",
                bps=bps,
                prior_branch=prior_branch,
                exit_branch="zero_bid",
            )
            return False

        # V2 spec §8.2 tick: 0.001 if px > 0.96 or < 0.04, else 0.01.
        # Sell limit one tick below best bid to ensure immediate cross.
        tick = (
            Decimal("0.001")
            if own_bid_price > Decimal("0.96") or own_bid_price < Decimal("0.04")
            else Decimal("0.01")
        )
        sell_limit = max(own_bid_price - tick, Decimal("0.001"))

        sleeve_id = self._sleeve_id(slot.symbol, slot.tf, own_outcome)
        try:
            exit_result = await self.executor.place_exit_order(
                token_id=own_token,
                qty=slot.entry_qty,
                limit_px=sell_limit,
                sleeve_id=sleeve_id,
            )
        except Exception as exc:
            logger.exception(
                "poly_updown.bid_exit_failed",
                extra={"slot": slot.slot_id, "err": str(exc)},
            )
            exit_result = None

        status = getattr(exit_result, "status", None)
        status_str = str(status).lower() if status is not None else ""
        if exit_result is None or "rejected" in status_str:
            slot.status = "held_no_hedge_no_exit"
            await self._audit_hedge_skip(
                slot,
                reason="hedge_and_exit_both_failed",
                bps=bps,
                prior_branch=prior_branch,
                exit_branch="sell_rejected",
                exit_status=status_str or "no_result",
            )
            return False

        # Success — capture exit fill into Slot for resolver.
        raw = getattr(exit_result, "raw_response", {}) or {}
        slot.status = "exited_at_bid"
        slot.exit_price = own_bid_price
        slot.exit_shares = Decimal(str(raw.get("filled_shares") or raw.get("filled") or "0"))
        slot.exit_proceeds_usd = Decimal(str(raw.get("filled_usd") or "0"))

        logger.info(
            "poly_updown.slot_exited_at_bid",
            extra={
                "slot": slot.slot_id,
                "signal": slot.signal,
                "bid_price": str(own_bid_price),
                "shares_sold": str(slot.exit_shares),
                "proceeds_usd": str(slot.exit_proceeds_usd),
                "bps": bps,
                "prior_branch": prior_branch,
            },
        )

        try:
            await self._audit(
                slot.symbol,
                slot.tf,
                reason="exited_at_bid",
                signal=slot.signal,
                condition_id=slot.condition_id,
                fill_status="filled",
                fill_qty=str(slot.exit_shares),
                fill_price=str(own_bid_price),
                qty_intended=str(slot.entry_qty),
                limit_px=str(sell_limit),
                publish_bar_processed=False,
            )
        except Exception:  # pragma: no cover — audit must not mask exit success
            logger.exception(
                "poly_updown.bid_exit_audit_emit_failed",
                extra={"slot": slot.slot_id, "cid": slot.condition_id},
            )
        return True

    async def _audit(
        self,
        symbol: str,
        tf: str,
        *,
        reason: str,
        signal: str | None,
        condition_id: str | None = None,
        error: str | None = None,
        fill_status: str | None = None,
        fill_qty: str | None = None,
        fill_price: str | None = None,
        qty_intended: str | None = None,
        limit_px: str | None = None,
        spread_pct: str | None = None,
        # Phase 25 Tier A — TCA fee + tx accounting.
        # `fee_usd` is the venue-reported fee string; null/empty/zero
        # falls back to the env baseline TV_POLY_FEE_USD_PER_FILL.
        # `tx_hash` lets a future receipt-fetch background task backfill
        # actual gas-cost fees by joining on tx_hash.
        fee_usd: str | None = None,
        tx_hash: str | None = None,
        publish_bar_processed: bool = True,
    ) -> None:
        """Write a trading.events audit row + publish bar_processed over WS bus.

        Best-effort — if the pool is None or insert fails, log + continue.
        Audit must NEVER mask upstream errors. NO writes to engine.poly_*
        (CLAUDE.md #13) — audit lives in trading.events only.

        V3: when ``self.strategy_mode == "v3"``, sleeve_id is suffixed with
        ``_v3`` so trading.events rows are attributable to the V3 portfolio
        separately from V1/V2 baselines. ``strategy_mode`` is also added to
        the data jsonb for downstream filtering.

        Phase 18.1 dashboard wiring: every audit also fires a ``bar_processed``
        NOTIFY so ws_terminal subscribers (the /bots dashboard) see signal +
        last-bar-at updates without polling. ``fill`` is also published when
        ``fill_status='filled'`` so the slot card can flash a fill cell.
        Both are fire-and-forget — pg_notify failures are swallowed by
        ``notify_event`` itself.
        """
        pool = self.pool
        if pool is None:
            return
        # Suffix sleeve_id by strategy_mode so V1 volume / V2 sniper / V3
        # rows are distinguishable in trading.events + on the dashboard.
        # All three modes get explicit suffixes (no bare canonical form)
        # so the dashboard can A/B/C compare cleanly.
        # Phase 18.4 — inverse sleeves use the spec-fixed naming
        # (no strategy_mode suffix, no outcome split). The sleeve_id is
        # the same for entry, hedge_skip and resolution rows so analysis
        # queries can group all events by sleeve_id without splitting.
        if self._inverse_kind is not None:
            sleeve_id = inverse_sleeve_id(kind=self._inverse_kind, symbol=symbol, tf=tf)
        elif self.strategy_mode == "momo":
            # Phase 18.5 — per-policy aggregator id so 3 momo controllers
            # write distinct rows in trading.events (one per policy).
            # 2026-05-20 F7: _f7 suffix appended when filter active.
            policy_suffix = _HEDGE_POLICY_SUFFIX[self.hedge_policy]
            sleeve_id = (
                f"poly_updown_{symbol.lower()}_{tf}_momo_{policy_suffix}{self._f7_suffix}"
            )
        elif self.strategy_mode == "momo_v2":
            # Phase 18.5+ — same per-policy split for v2; the _v2 infix
            # keeps it distinct from v1 momo audit rows.
            policy_suffix = _HEDGE_POLICY_SUFFIX[self.hedge_policy]
            sleeve_id = (
                f"poly_updown_{symbol.lower()}_{tf}_momo_v2_{policy_suffix}{self._f7_suffix}"
            )
        else:
            sleeve_id = f"poly_updown_{symbol.lower()}_{tf}_{self.strategy_mode}"
        payload: dict[str, Any] = {
            "symbol": symbol,
            "tf": tf,
            "reason": reason,
            "signal": signal,
            "mode": self.mode,
            "strategy_mode": self.strategy_mode,
        }
        # Phase 18.4 — for inverse rows, attach the pre-flip base signal
        # (so the analyzer can recover what the wrapped base sleeve
        # would have emitted) and the inverse_reason tag (so the
        # analyzer can group rows by which inverse rule fired). The
        # ``base_signal`` is None for non-on_bar_close audit paths
        # (e.g., hedge_skip), where the signal direction is already
        # implicit from slot.signal and pre-flip context isn't relevant.
        if self._inverse_kind is not None:
            payload["inverse_reason"] = INVERSE_REASON[self._inverse_kind]
            if self._last_base_signal is not None:
                payload["base_signal"] = self._last_base_signal

        # Phase 18.5 — momo audit enrichment per spec §6. Attach hedge
        # policy + entry phase + the ret_2m at signal time + bar_ctx age
        # (latency observability). Read from self._bar_ctx_active which
        # the master scheduler sets just before this dispatch path.
        if self.strategy_mode == "momo":
            payload["hedge_policy"] = self.hedge_policy
            _bctx = self._bar_ctx_active
            if _bctx is not None:
                payload["entry_phase"] = getattr(_bctx, "phase", None)
                # ret_2m_at_signal — recompute from BarContext closes (cheap).
                btc_at_ws = getattr(_bctx, "btc_now", None)
                btc_at_120 = getattr(_bctx, "btc_at_t_plus_120", None)
                if (
                    btc_at_ws is not None
                    and btc_at_120 is not None
                    and float(btc_at_ws) > 0
                ):
                    try:
                        payload["ret_2m_at_signal"] = math.log(
                            float(btc_at_120) / float(btc_at_ws)
                        )
                    except (ValueError, ZeroDivisionError):  # pragma: no cover
                        pass
                if getattr(_bctx, "abs_ret_2m_threshold", None) is not None:
                    payload["abs_ret_2m_threshold"] = (
                        _bctx.abs_ret_2m_threshold
                    )
                fetched_at = getattr(_bctx, "fetched_at", None)
                if fetched_at is not None:
                    payload["bar_ctx_age_ms"] = int(
                        (time.monotonic() - fetched_at) * 1000
                    )
        # Phase 18.5+ — momo_v2 audit enrichment. Same shape as momo v1
        # but ret_2m_at_signal is recomputed from the v2 anchor fields
        # (btc_close_at_ws_minus_60, btc_at_t_plus_60) — NOT (btc_now,
        # btc_at_t_plus_120). entry_phase will be 't_plus_60'.
        elif self.strategy_mode == "momo_v2":
            payload["hedge_policy"] = self.hedge_policy
            _bctx = self._bar_ctx_active
            if _bctx is not None:
                payload["entry_phase"] = getattr(_bctx, "phase", None)
                btc_at_ws_minus_60 = getattr(_bctx, "btc_close_at_ws_minus_60", None)
                btc_at_60 = getattr(_bctx, "btc_at_t_plus_60", None)
                if (
                    btc_at_ws_minus_60 is not None
                    and btc_at_60 is not None
                    and float(btc_at_ws_minus_60) > 0
                ):
                    try:
                        payload["ret_2m_at_signal"] = math.log(
                            float(btc_at_60) / float(btc_at_ws_minus_60)
                        )
                    except (ValueError, ZeroDivisionError):  # pragma: no cover
                        pass
                if getattr(_bctx, "abs_ret_2m_threshold", None) is not None:
                    payload["abs_ret_2m_threshold"] = (
                        _bctx.abs_ret_2m_threshold
                    )
                fetched_at = getattr(_bctx, "fetched_at", None)
                if fetched_at is not None:
                    payload["bar_ctx_age_ms"] = int(
                        (time.monotonic() - fetched_at) * 1000
                    )

        # 2026-05-20 F7 RSI filter audit enrichment (TV_AGENT_F7_RSI_FILTER_SPEC §5).
        # Attached on momo + momo_v2 rows regardless of signal outcome so the
        # operator can post-hoc audit BOTH fired and skipped (signal='NONE')
        # rows. f7_decision is "pass" when the row reached the audit path; a
        # gate-skipped fire never reaches order_placed (returns NONE upstream).
        # `_bar_ctx_active.rsi_14_for_signal` is the canonical RSI at signal
        # time; the strategy's f7_passes() consumed this same value.
        if self.strategy_mode in ("momo", "momo_v2") and self._bar_ctx_active is not None:
            _rsi = getattr(self._bar_ctx_active, "rsi_14_for_signal", None)
            if _rsi is not None and math.isfinite(_rsi):
                payload["rsi_14"] = _rsi
            payload["f7_filter_mode"] = self._f7_filter_mode
            # f7_decision is "pass" for order_placed; for no_signal rows the
            # gate may have been the cause (or the q90 threshold filtered).
            # Either way, "pass" / "skip_*" reflects the LAST gate outcome:
            # gate is reached only when |ret_2m| >= threshold (direction
            # decided), so signal=="NONE" + mode != "off" + rsi != nan
            # implies the F7 gate skipped.
            from backend.app.strategies.polymarket.f7_gate import decision_label as _f7_lbl
            _rsi_for_label = _rsi if (_rsi is not None and math.isfinite(_rsi)) else float("nan")
            payload["f7_decision"] = _f7_lbl(signal, _rsi_for_label, self._f7_filter_mode)
        if condition_id:
            payload["condition_id"] = condition_id
        if error:
            payload["error"] = error
        if fill_status is not None:
            payload["fill_status"] = fill_status
        if fill_qty is not None:
            payload["fill_qty"] = fill_qty
        if fill_price is not None:
            payload["fill_price"] = fill_price
        if qty_intended is not None:
            payload["qty_intended"] = qty_intended
        if limit_px is not None:
            payload["limit_px"] = limit_px
        if spread_pct is not None:
            payload["spread_pct"] = spread_pct
        # Phase 25 Tier A — TCA fee + edge-prediction baselines on every
        # entry/order_placed signal row. Venue fee preferred when > 0;
        # falls back to TV_POLY_FEE_USD_PER_FILL otherwise. Predicted
        # edge/cost are operator-config baselines until per-strategy
        # models emit per-signal predictions.
        if tx_hash:
            payload["tx_hash"] = tx_hash
        if fill_status == "filled":
            try:
                _venue_fee = float(fee_usd) if fee_usd else 0.0
            except (TypeError, ValueError):
                _venue_fee = 0.0
            payload["fee_usd"] = (
                _venue_fee if _venue_fee > 0 else _TV_POLY_FEE_USD_PER_FILL
            )
        if reason in ("order_placed", "entry_rejected", "no_signal", "signal"):
            payload["predicted_edge_pp"] = _TV_POLY_PREDICTED_EDGE_PP
            payload["predicted_cost_bps"] = _TV_POLY_PREDICTED_COST_BPS
        try:
            import json

            from backend.app.engine.notify import notify_event

            now_iso = datetime.now(UTC).isoformat()
            ws_signal = _signal_to_direction(signal)

            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, 'poly_updown_signal', $2::jsonb)",
                    sleeve_id,
                    json.dumps(payload),
                )
                # bar_processed: fires on every signal eval (signal+rejected+no_signal).
                # Frontend slot card subscribes by sleeve_id and updates signal+countdown.
                # Suppressed for hedge writes (publish_bar_processed=False) because a
                # hedge isn't a fresh bar evaluation — it's a reactive same-window
                # opposite-side fill. Pushing bar_processed for it would clobber the
                # original signal display on the dashboard.
                if publish_bar_processed:
                    await notify_event(
                        conn,
                        kind="bar_processed",
                        payload={
                            "sleeve_id": sleeve_id,
                            "tf": tf,
                            "bar_ts": now_iso,
                            "processed_at": now_iso,
                            "signal": ws_signal,
                        },
                    )
                # fill: fires only when executor returned a real fill. Carries
                # synthetic order_id so the WS event is uniquely keyed.
                if fill_status == "filled" and fill_qty is not None:
                    side = "long" if signal == "UP" else "short"
                    try:
                        qty_f = float(fill_qty)
                    except (TypeError, ValueError):
                        qty_f = 0.0
                    try:
                        price_f = float(fill_price) if fill_price else 0.0
                    except (TypeError, ValueError):
                        price_f = 0.0
                    await notify_event(
                        conn,
                        kind="fill",
                        payload={
                            "order_id": f"{sleeve_id}-{int(datetime.now(UTC).timestamp())}",
                            "sleeve_id": sleeve_id,
                            "ticker": symbol.upper(),
                            "side": side,
                            "qty": qty_f,
                            "price": price_f,
                            "fee": 0.0,
                            "ts": now_iso,
                        },
                    )
        except Exception:  # pragma: no cover - audit must not mask
            logger.debug(
                "poly_updown.audit_emit_failed",
                extra={"sleeve_id": sleeve_id, "reason": reason},
            )


def _signal_to_direction(signal: str | None) -> str:
    """Map controller signal vocabulary → WS bar_processed direction.

    UP → long, DOWN → short, NONE/None/anything else → flat. Matches the
    ``BarProcessedPayload.signal`` literal type in frontend/lib/ws/types.ts.
    """
    if signal == "UP":
        return "long"
    if signal == "DOWN":
        return "short"
    return "flat"


__all__ = [
    "BINANCE_SYMBOL_ID_MAP",
    "HEDGE_RETRY_ATTEMPTS",
    "HEDGE_RETRY_BACKOFF_S",
    "LIVE_MIRROR_MAX_NOTIONAL",
    "NOTIONAL_PER_SLOT_USD",
    "PolymarketUpdownController",
    "REV_BP_THRESHOLD",
    "SNIPER_LOOKBACK_DAYS",
    "SNIPER_MIN_SAMPLES",
    "STALE_BINANCE_FEED_SECONDS",
    "SUPPORTED_SYMBOLS",
    "SUPPORTED_TFS",
    "SizingOverrideForbidden",
    "Slot",
    # V3 portfolio surface
    "V3_PER_ASSET_QUANTILE",
    "V3_REQUIRE_MULTI_HORIZON",
    "V3_SPREAD_FILTER_PCT",
    # Phase 18.3 — per-asset spread filter (Fix A)
    "V3_SPREAD_FILTER_PCT_DEFAULT",
    "_v3_spread_filter_for",
    "_spread_pct",
    "_v3_quantile_for",
]
