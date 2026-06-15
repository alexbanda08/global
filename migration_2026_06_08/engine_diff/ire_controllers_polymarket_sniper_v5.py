"""Phase 35-12 Task 1 — PolymarketSniperV5Controller.

Per-sleeve eval for the 16 sniper-v5 sleeves (Plan 35-11). Composes:

- 7 panels (TradersReality, RangeFilter, Microprice, Regime, Sms, VolHurst,
  DailyVwap) via panel dict at construction.
- BookMirror for L25 reads + sparse-book event tracking.
- AsyncJsonlShadowLogger for §7 event emission (eval / placed / resolved).
- Settings for notional + sparse-book threshold + (future) latency budget.
- Optional read_pool for sleeve 01's S6 precondition lookup.
- Optional AlertService for sleeve 06 WR<80% CRITICAL alert.

CLAUDE.md invariants honored:

- inv #4: gates are pure functions evaluated BEFORE placement; controller
  only orchestrates the call sequence.
- inv #11+#12: sniper-v5 is paper-only. Placement is a synthetic L25
  walk via ``_simulate_l25_walk`` — no engine writes, no tier mutation,
  no strategy enable/disable. Verified by the source-grep test in
  ``backend/tests/controllers/test_polymarket_sniper_v5.py``.
- inv #13: panels + BookMirror are the only data sources. No Storedata
  reads here; the optional S6 precondition lookup hits trading.events
  via the read_pool (TV-owned schema) — also no public.* read.

Eval flow per direction:

    1. If sleeve_id ∈ _auto_suspended (sleeve 06 WR-monitor hit) → skip.
    2. If sleeve.s6_precondition AND not _check_s6_fired → skip.
    3. Build L25 snapshot from book_mirror for {up,dn} token.
    4. Compute spread = same-token (ask0 - bid0) via _sniper_spread
       (TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — NOT the old cross-token
       abs(up_vwap - (1 - dn_vwap)) formula). If > spread_filter →
       skip with skip_reason="spread_bidask_too_wide_<spread:.4f>_>_<filter:.4f>"
       AND DO NOT call any gate.
    5. Iterate sleeve.gates in declaration order; first gate that returns
       False sets skip_reason="<gate_name>=False" but ALL gates still run
       so gates_evaluated has every name.
    6. If all gates passed → check sparse-book filter (book_event_count
       deque); if <25 events in last 60s → skip
       "sparse_book_under_25_events_60s".
    7. Else → simulate L25 walk → set fill_vwap, fill_shares, placed_size_usd.
    8. Emit §7 shadow_log event ("sleeve_fire_placed" if all pass,
       "sleeve_fire_eval" otherwise).

Sleeve 06 WR monitor (spec §10.2):
    Track first 30 sleeve-06 resolutions in _sleeve_06_resolutions. On the
    30th, compute WR = wins / 30. If WR < 0.80, emit CRITICAL alert and add
    SLEEVE_06_ID to _auto_suspended. Subsequent eval_sleeve_fire short-
    circuits at step 1 above.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Final

import structlog

from backend.app.data.bars import get_feed_instance
from backend.app.strategies.polymarket.sniper_v5_live_gate import (
    check_sniper_v5_live,
)
from backend.app.strategies.polymarket.sniper_v5_sleeves import (
    GateRef,
    SniperV5Sleeve,
)
from backend.app.strategies.polymarket.sniper_v5_thresholds import (
    DEPTH_MEDIAN_USD,
)

logger = structlog.get_logger("backend.app.controllers.polymarket_sniper_v5")


# fast_taker (TV_AGENT_SPEC_FAST_TAKER_SHADOW_AB_2026_05_29) — the oracle-lag
# directional-taker A/B sleeves live in the sniper-v5 tuple but carry their own
# id prefix + fill/settle semantics (legacy_2pct fee, merge-mimic book).
_FAST_TAKER_PREFIX: Final[str] = "poly_fast_taker_"
# FAST_TAKER_LAGV2 (2026-05-29) — a SEPARATE directional-taker family. It shares
# the poly_fast_taker_ id stem but is NOT the A/B merge-mimic family: it uses the
# 0.07 winner-only fee + plain chainlink resolution + a binance-reversal stop (no
# merge, no legacy_2pct). So it must be EXCLUDED from _is_fast_taker, which routes
# the A/B family to _resolve_fast_taker (legacy_2pct).
_FAST_TAKER_LAGV2_PREFIX: Final[str] = "poly_fast_taker_lagv2_"

# Live promotion (TV_AGENT_SPEC 2026-06-01) — hard cap on the per-fire REAL
# notional for an allowlisted sniper-v5 sleeve. Mirrors the live-mirror
# LIVE_MIRROR_MAX_NOTIONAL=$1 discipline; sized with headroom over the $1.50
# stake. ANY requested live notional is clamped to this before placement.
SNIPER_V5_LIVE_MAX_NOTIONAL: Final[Decimal] = Decimal("2.00")
# Marketable-limit price for the live taker buy: 0.99 takes liquidity and the
# venue caps it to the best ask (same as the momo live-mirror entry + the
# shadow L25-walk taker assumption). Operator-confirmed: entry identical to
# Kalshi-live + Poly-shadow.
_SNIPER_V5_LIVE_LIMIT_PX: Final[Decimal] = Decimal("0.99")
# Marketable-limit price for the live taker SELL on a SCALP_EXIT exit
# (TV_AGENT_SPEC_SCALP_LIVE_2026_06_05). A FAK sell fills against the HIGHEST
# bids first (price-time priority), so a low floor (0.01) just lets the tiny
# probe position fully clear against the best available bids — the mirror of the
# 0.99 buy limit. The exit DECISION (TP/stop/deadline) is already made before we
# submit; the floor only bounds how deep the FAK is allowed to walk.
_SNIPER_V5_LIVE_SELL_LIMIT_PX: Final[Decimal] = Decimal("0.01")


def _is_fast_taker_lagv2(sleeve: SniperV5Sleeve) -> bool:
    return sleeve.sleeve_id.startswith(_FAST_TAKER_LAGV2_PREFIX)


def _is_fast_taker(sleeve: SniperV5Sleeve) -> bool:
    return (
        sleeve.sleeve_id.startswith(_FAST_TAKER_PREFIX)
        and not _is_fast_taker_lagv2(sleeve)
    )


# ---------------------------------------------------------------------
# fast_taker fire signal — INTRA-WINDOW BINANCE RETURN
# (TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01)
# ---------------------------------------------------------------------
#
# BUG: every poly_fast_taker sleeve (both the A/B `g_oracle_lag_bps_ge` family
# AND the LAGV2 `g_oracle_lag_with` family) fired UP on ~100% of slots / 0 DOWN
# → coin-flip WR. Root cause: both gates pick the side by sign(price_delta_bps)
# where the controller fed the OracleLagSnapshot's feed-vs-chainlink-oracle
# basis ((binance − oracle)/oracle). On the live box that sits persistently
# positive → always-UP. The BACKTESTED signal is the binance INTRA-WINDOW
# return (px@fire / px@slot_open − 1), which swings ± symmetrically → ~50/50
# UP/DOWN, 68% WR.
#
# FIX (spec Option 2): feed the binance return through the SAME field both
# gates already read (`oracle_lag.price_delta_bps`). One controller change
# fixes all 8 sleeves with NO gate-code or sleeve-roster edits. The snapshot
# class below is a drop-in for OracleLagSnapshot for that single field + stale.
@dataclass(frozen=True, slots=True)
class _BinanceLagSnapshot:
    """Drop-in for OracleLagSnapshot consumed by ``g_oracle_lag_with`` /
    ``g_oracle_lag_bps_ge`` / ``g_cross_asset_lag_confluence``.

    ``price_delta_bps`` is the INTRA-WINDOW BINANCE RETURN
    ``(px@fire / px@slot_open − 1) × 1e4`` — the backtested fast_taker signal,
    NOT the feed-vs-oracle basis. ``stale`` is always False (the binance 1s
    feed drives staleness independently; a missing read returns None instead).
    """

    price_delta_bps: float
    stale: bool = False


def _binance_close_at(asset: str, ts_us: int) -> float | None:
    """Binance 1s close at-or-before ``ts_us`` from the engine's in-memory
    vwap_store (the TV-native binance feed; CLAUDE.md inv #13). None when the
    feed/store is unbound or holds no bar ≤ ts_us → caller treats as no-signal
    → graceful skip (matches every other gate's missing-data contract).
    """
    feed = get_feed_instance()
    store = getattr(feed, "vwap_store", None) if feed is not None else None
    if store is None:
        return None
    return store.close_at(asset, ts_us)


def _binance_lag_snapshot(
    asset: str, slot_start_us: int, fire_us: int,
) -> _BinanceLagSnapshot | None:
    """Intra-window binance-return snapshot for the fast_taker families.

    ``delta_bps = (px_fire / px_open − 1) × 1e4`` where ``px_open`` = binance 1s
    close at ``slot_start_us`` and ``px_fire`` = binance 1s close at ``fire_us``.
    Returns None when either price is unreadable (graceful skip — both gates
    fail on a None snapshot). Sign is symmetric ± → fires UP and DOWN.
    """
    px_open = _binance_close_at(asset, slot_start_us)
    px_fire = _binance_close_at(asset, fire_us)
    if not px_open or not px_fire or px_open <= 0:
        return None
    return _BinanceLagSnapshot(
        price_delta_bps=(px_fire / px_open - 1.0) * 1e4,
    )


# ---------------------------------------------------------------------
# Shared dataclasses (also imported by the loop in Plan 35-12 Task 2)
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SlotInfo:
    """Per-slot context for sniper-v5 eval/resolution dispatch."""

    slug: str                  # e.g. "btc-updown-5m-1779815400"
    asset: str                 # "BTC" | "ETH" | "SOL"
    tf: str                    # "5m" | "15m"
    slot_start_us: int         # window_start unix * 1e6
    ws_s: int                  # window_start unix (seconds)
    condition_id: str          # on-chain condition_id (for OnchainOracle.get_resolution)
    token_id_up: str           # YES (UP) token CLOB id
    token_id_dn: str           # NO  (DOWN) token CLOB id


@dataclass(slots=True)
class L25BookSnapshot:
    """L25-derived per-direction VWAP/depth snapshot used for spread + placement.

    V5+V6+V7+V8 spread-filter fix (2026-05-27): adds ``up_ask0``, ``up_bid0``,
    ``dn_ask0``, ``dn_bid0`` top-of-book fields. The spread metric is now the
    same-token bid-ask on the direction's side (matching backtest
    ``engine_v2.fill_at_book``); see ``_sniper_spread.compute_spread``. The
    prior cross-token arb metric (``abs(up_vwap - (1 - dn_vwap))``) blocked
    100 % of fires on thin-inside books and is preserved only in the JSONL
    audit row as ``cross_spread_old`` for historical comparison.

    TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27: adds ``up_book_source``,
    ``dn_book_source`` so the dashboard + post-mortems can see which tier
    (ws_mirror / clob / storedata / empty) answered each side. Aligns the
    sniper-v5 JSONL row with the canonical momo ``paper.book_fetched``
    telemetry shape.
    """

    up_vwap: float | None = None
    dn_vwap: float | None = None
    up_depth_usd: float = 0.0
    dn_depth_usd: float = 0.0
    # V5+V6+V7+V8 fix (2026-05-27) — top-of-book for same-token bid-ask spread.
    up_ask0: float | None = None
    up_bid0: float | None = None
    dn_ask0: float | None = None
    dn_bid0: float | None = None
    # TV_FIX_UNIFY_BOOK_READ_PATH (2026-05-27) — tier that answered each side.
    # Values: "ws_mirror" | "clob" | "storedata" | "empty".
    up_book_source: str = "empty"
    dn_book_source: str = "empty"


@dataclass(slots=True)
class FireResult:
    """Per-direction eval outcome (one or two per sleeve fire)."""

    direction: str                         # "UP" | "DOWN"
    all_gates_passed: bool = False
    eval_only: bool = True
    gates_evaluated: dict[str, bool] = field(default_factory=dict)
    skip_reason: str | None = None
    l25_book_snapshot: L25BookSnapshot | None = None
    fill_vwap: float | None = None
    fill_shares: float | None = None
    placed_size_usd: float | None = None
    fill_latency_ms: float | None = None
    # Synthetic-fill marker (TV_FIX_SYNTHETIC_FILLS_2026_05_27): one of
    # ``"l25_walk"`` (real walk on populated asks) or ``"synthetic"`` (book
    # empty / unwalkable → vwap=0.5 placeholder). Dashboard MUST exclude
    # ``synthetic`` rows from primary WR/PnL — they couldn't fill in live.
    #
    # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 supersedes the synthetic path —
    # under the unified primitive the controller skips empty-tier fires
    # entirely (skip_reason="empty_book_all_tiers_failed") instead of placing
    # a synthetic. ``fill_method`` is preserved for the audit trail on rows
    # logged before this fix landed.
    fill_method: str | None = None
    # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — tier that answered the fill
    # walk on the direction's side. One of "ws_mirror" | "clob" |
    # "storedata" | "empty" | None (None when not placed).
    book_source: str | None = None
    # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — populated at resolution time
    # from outcome == direction. The dashboard's prior derived-on-read path
    # still works as a fallback when ``won`` is None on legacy rows.
    won: bool | None = None
    offset_s: int = 0
    # HEDGE_LATE exit policy (SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE_2026_05_27).
    # exit_type is set at resolution: "hold_to_resolve" (normal oracle path,
    # incl. all HOLD sleeves) or "hedge_late_cut" (early underwater cut).
    # hedge_sell_vwap is the realized sell vwap when cut early; None otherwise.
    exit_type: str | None = None
    hedge_sell_vwap: float | None = None
    # fast_taker (TV_AGENT_SPEC_FAST_TAKER_SHADOW_AB_2026_05_29) — populated
    # only on poly_fast_taker_* fires. ``oracle_lag_bps`` is the fire-time
    # binance-vs-chainlink staleness (signed); merge_* carry the FIFO matched-
    # pair recycle that THIS fire triggered (Config A merge_mimic only).
    oracle_lag_bps: float | None = None
    merge_pairs: float | None = None
    merge_collateral: float | None = None
    # FAST_TAKER_LAGV2 (2026-05-29) — entry_delta_bps is the signed
    # price_delta_bps captured at fill (the basis the reversal stop measures
    # against); reversal_bps_at_exit is how far binance had reversed when a
    # LAG_REVERSAL_STOP cut fired (None unless cut early).
    entry_delta_bps: float | None = None
    reversal_bps_at_exit: float | None = None
    # TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — gate vs fill book-source
    # consistency marker. Gate decisions (spread + depth) read the per-side
    # ``L25BookSnapshot`` tier (``up_book_source`` / ``dn_book_source``),
    # while the fill walks a SEPARATELY-fetched 3-tier book a few awaits
    # later. While the WS mirror is hot+populated they always agree; if the
    # mirror is None / a token is empty the fill can fall through to a
    # different tier (e.g. CLOB) than the one the gate trusted → the gate
    # decision and the fill price come from different books/instants. This
    # is None when no fill was placed (eval-only / skipped), True when the
    # gate-time and fill-time tiers differed (latent risk — observable in
    # the audit row + a ``book_source_mismatch`` warning), False when they
    # matched. Deeper "one snapshot per fire for both gates AND fill"
    # unification is DEFERRED (would change the gate/fill data plumbing and
    # the live happy path).
    book_source_mismatch: bool | None = None


@dataclass(slots=True)
class _FastTakerSlugBook:
    """Per-(sleeve_id, slug) inventory for Config-A merge_mimic accounting.

    Ports MakerFillSimulator's _observe_merge/_observe_redeem/settle_slug
    semantics into the sniper-v5 controller (the maker sim is hard-coupled to
    the maker-strategy protocol, so we reuse the *logic*, not the object):

    - Each qualifying oracle-lag fire is a TAKE → append (vwap, shares) FIFO to
      the leading side + add ``vwap*shares`` to ``cash_spent``.
    - Whenever ``min(up_shares, dn_shares) >= 1`` we FIFO-merge the matched
      pairs: pop ``pairs`` shares from BOTH sides and credit ``$1*pairs`` to
      ``cash_recovered`` (gasless on crypto up-down → gas=0, NOT the legacy
      0.05). This recycles collateral exactly like eebde7a0.
    - At slot resolution the directional residual redeems: winning side pays
      ``$1*shares`` minus the 2%-on-winning-profit fee (legacy_2pct); the losing
      residual is worthless ($0, cost already in cash_spent).

    ``settled`` makes resolution idempotent — the loop schedules one
    ``_resolve_at_slot_end`` per placed fire, but a merge_mimic slug settles its
    aggregate book exactly ONCE.
    """

    up: deque[tuple[float, float]] = field(default_factory=deque)   # (vwap, shares) FIFO
    dn: deque[tuple[float, float]] = field(default_factory=deque)
    cash_spent: float = 0.0
    cash_recovered: float = 0.0
    merge_pairs_total: float = 0.0
    n_fires: int = 0
    settled: bool = False

    def _side(self, direction: str) -> deque[tuple[float, float]]:
        return self.up if direction == "UP" else self.dn

    def shares(self, direction: str) -> float:
        return sum(s for _v, s in self._side(direction))

    def add_take(self, direction: str, vwap: float, shares: float) -> None:
        self._side(direction).append((vwap, shares))
        self.cash_spent += vwap * shares
        self.n_fires += 1

    def merge_matched(self) -> tuple[float, float]:
        """FIFO-merge the matched-pair overlap. Returns (pairs, collateral_freed).

        Merges the full ``min(up, dn)`` whenever it is >= 1 share (the spec's
        ">= 1 share → MERGE" trigger). Credits ``$1 * pairs`` (gas 0).
        """
        pairs = min(self.shares("UP"), self.shares("DOWN"))
        if pairs < 1.0:
            return 0.0, 0.0
        self._pop_shares(self.up, pairs)
        self._pop_shares(self.dn, pairs)
        self.cash_recovered += pairs       # $1/pair, gasless
        self.merge_pairs_total += pairs
        return pairs, pairs

    @staticmethod
    def _pop_shares(dq: deque[tuple[float, float]], qty: float) -> None:
        remaining = qty
        while remaining > 1e-9 and dq:
            vwap, shares = dq[0]
            if shares <= remaining + 1e-9:
                dq.popleft()
                remaining -= shares
            else:
                dq[0] = (vwap, shares - remaining)
                remaining = 0.0

    def residual_profit(self, direction: str) -> float:
        """sum((1 - vwap) * shares) over residual entries of ``direction``."""
        return sum((1.0 - v) * s for v, s in self._side(direction))


# ---------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------


_BOOK_EVENT_WINDOW_S = 60.0
# fast_taker resolution fee (legacy_2pct): 2% of winning profit only; losers
# untaxed; no per-fill taker fee (crypto up-down feeRate ~= 0).
_FAST_TAKER_WIN_FEE = 0.02


class PolymarketSniperV5Controller:
    """Per-sleeve fire orchestrator for the 16 sniper-v5 paper sleeves."""

    SLEEVE_06_ID: Final[str] = "poly_sniper_v5_sol_5m_depth_up_hod_session"
    SLEEVE_06_MONITOR_N: Final[int] = 30
    SLEEVE_06_MIN_WR: Final[float] = 0.80

    def __init__(
        self,
        *,
        panels: dict[str, Any],
        book_mirror: Any,
        shadow_logger: Any,
        settings: Any,
        read_pool: Any | None = None,
        write_pool: Any | None = None,
        alert_service: Any | None = None,
        book_snapshot_fn: Any | None = None,
        v9_data_store: Any | None = None,
        live_executor: Any | None = None,
        live_enabled: bool = False,
        live_allowlist: str = "",
        live_notional_usd: Decimal = Decimal("1.50"),
        shadow_allowlist: str = "",
        shadow_notional_usd: Decimal = Decimal("1.0"),
    ) -> None:
        self._panels = panels
        # ``book_mirror`` is kept for SYNCHRONOUS gate-dispatch only — gates
        # like ``g_imb5_strong_with`` / ``g_depth_250_strict`` /
        # ``g_entry_vwap_in_band`` / ``g_liq_shock_against`` are pure-sync
        # functions that read the L25 book at gate-eval time. They CANNOT
        # await an async primitive.
        #
        # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — ALL fill / snapshot reads
        # done by the controller ITSELF (``_simulate_l25_walk``,
        # ``_compute_l25_vwap_and_depth``, ``_top_of_book``) now route
        # through ``book_snapshot_fn`` which is the canonical 3-tier
        # WS→CLOB→Storedata dispatcher (``paper.get_orderbook_snapshot``
        # bound method). This eliminates the synthetic 0.5-vwap placeholder
        # path and aligns sniper-v5 with the production momo controller.
        #
        # ``book_snapshot_fn`` is keyword-only + Optional for backward
        # compatibility with existing tests that pass a ``book_mirror``
        # only. When None, the controller falls back to a thin async
        # adapter over ``book_mirror.get`` that returns the same dict
        # shape ({asks, bids, ts, _source: "ws_mirror"}). Production
        # engine wiring MUST pass ``book_snapshot_fn=paper.get_orderbook_snapshot``.
        self._book_mirror = book_mirror
        self._book_snapshot_fn = book_snapshot_fn
        self._logger = shadow_logger
        self._settings = settings
        self._read_pool = read_pool
        # Phase 35.2 (2026-05-27): write_pool enables parallel audit-row write
        # to ``trading.events`` so the dashboard fire counts (which query
        # kind='poly_updown_signal' + kind='poly_updown_resolution') populate
        # alongside the JSONL log. Defaults to None — JSONL-only mode for
        # tests + when DB is unavailable.
        self._write_pool = write_pool
        self._alert_service = alert_service
        # V9 (SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md §2.5) — pre-loaded
        # Polymarket trades + HL liquidation parquets used by the B1/B2/B3/A2
        # gates. Optional: when None, V9 gates degrade to "no fire" (defensive
        # design — engine boots fine without V9 data; sleeves stay silent
        # until operator runs the canonical parquet pipeline on this VPS).
        self._v9_data_store = v9_data_store
        # Per-token book-event timestamp deque (sparse-book filter §6).
        # Each entry is the ts_us of one on_book_update call.
        self._book_event_count: dict[str, deque[int]] = {}
        # Sleeve 06 WR monitor — first 30 resolution outcomes only.
        self._sleeve_06_resolutions: list[tuple[int, bool]] = []
        # Process-local auto-suspend set (sleeve 06 if WR<80% over first 30).
        self._auto_suspended: set[str] = set()
        # fast_taker — per-(sleeve_id, slug) one-shot guard (Config B fires once
        # per slug on the first qualifying early offset) + merge_mimic inventory
        # books (Config A). Process-local; pruned by ``prune_stale_slot_state``
        # (TV_FIX_SPRINT_2026_06_02 controllers-2) once a slug's slot_end passes.
        self._one_shot_fired: set[tuple[str, str]] = set()
        self._ft_books: dict[tuple[str, str], _FastTakerSlugBook] = {}
        # SCALP_EXIT (TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02) — per-(sleeve,
        # slug) guard so a slug's position is scalp-exited (sold) exactly once,
        # and the loop doesn't fall back to hold-resolution after a real exit.
        self._scalp_exited: set[tuple[str, str]] = set()
        # SCALP MAKER EXIT (TV_AGENT_SPEC_SCALP_MAKER_EXIT_2026_06_06) — per-slug
        # state for a resting maker SELL: {(sleeve_id, slug): {posted, maker_price,
        # order_id, maker_shares}}. Poly 15m posts a maker offer on entry and
        # taker-crosses the remainder at +60; the dict tracks the order across the
        # poll window so the deadline knows what (if anything) still needs selling.
        self._scalp_maker_orders: dict[tuple[str, str], dict] = {}
        # TV_FIX_SPRINT_2026_06_02 (controllers-5 / strategies-2) — strong refs
        # to in-flight audit-write tasks. asyncio holds only a WEAK ref to a
        # running task, so a fire-and-forget task whose return value is
        # discarded can be GC'd mid-INSERT, silently dropping a trading.events
        # audit/resolution row. Retaining the Task here (+ discard on done)
        # keeps it alive until the coroutine completes.
        self._audit_tasks: set[asyncio.Task[None]] = set()
        # Live promotion (TV_AGENT_SPEC 2026-06-01). When ``live_executor`` is
        # None (the default everywhere except the Ireland live box), the
        # controller is byte-identical to its paper self — every fire routes
        # through the synthetic L25 walk. When set, a fire on an allowlisted
        # sleeve places a REAL Polymarket order instead. Fail-closed.
        self._live_executor = live_executor
        self._live_enabled = bool(live_enabled)
        self._live_allowlist = live_allowlist or ""
        self._live_notional_usd = min(
            Decimal(str(live_notional_usd)), SNIPER_V5_LIVE_MAX_NOTIONAL
        )
        # Shadow/paper sleeves run on the live-only box at this notional
        # (PAPER fills, no real orders) for pre-live A/B. Empty allowlist →
        # no shadow sleeves (default everywhere but where explicitly set).
        self._shadow_allowlist = frozenset(
            s.strip() for s in (shadow_allowlist or "").split(",") if s.strip()
        )
        self._shadow_notional_usd = Decimal(str(shadow_notional_usd))
        # TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — the live path's
        # ``_place_live_order`` reports an opaque ``"live"`` book_source on the
        # FireResult, but it sizes off an INNER 3-tier walk whose real tier we
        # need to compare against the gate-time tier. Stash that inner tier here
        # so the caller can run the gate-vs-fill source-consistency check
        # without changing ``_place_live_order``'s public return shape. Reset to
        # None on every live attempt; fires are evaluated sequentially per
        # controller (one ``for direction`` loop, no gather) so there is no
        # cross-fire race on this transient field.
        self._last_live_walk_source: str | None = None

    # ------------------------------------------------------------------
    # Book event tracking (BookMirror callback target)
    # ------------------------------------------------------------------

    def on_book_update(self, token_id: str, book: dict[str, Any]) -> None:
        """BookMirror.register_callback target.

        - Updates the microprice panel (if wired) with the latest L25 book.
        - Stamps the book event time into the per-token deque for the
          sparse-book filter at fire time.
        """
        mp_panel = self._panels.get("microprice")
        if mp_panel is not None:
            try:
                mp_panel.on_book_update(token_id, book)
            except Exception:  # noqa: BLE001 — panel exceptions never bubble
                logger.warning(
                    "poly_sniper_v5.microprice_panel_on_book_update_failed",
                    token_id=token_id,
                )
        dq = self._book_event_count.setdefault(token_id, deque(maxlen=200))
        dq.append(int(time.time() * 1_000_000))

    # ------------------------------------------------------------------
    # Slot-state GC (TV_FIX_SPRINT_2026_06_02 controllers-2)
    # ------------------------------------------------------------------

    @staticmethod
    def _slug_slot_end_us(slug: str) -> int | None:
        """Parse ``(slot_start_unix, tf)`` from a slug → slot_end in micros.

        Slug shape is ``"<asset>-updown-<tf>-<slot_start_unix>"`` e.g.
        ``"btc-updown-5m-1779815400"``. Returns ``slot_end_us`` (start +
        window) or ``None`` when the slug doesn't parse (be conservative —
        an unparseable slug is NEVER pruned so we can't drop a live key).
        """
        parts = slug.rsplit("-", 2)
        if len(parts) != 3:
            return None
        _, tf, start_str = parts
        try:
            start_s = int(start_str)
        except (TypeError, ValueError):
            return None
        if start_s <= 0:
            return None
        # Window seconds: 5m → 300, 15m → 900; default to the larger 15m
        # window for any unknown tf so we only ever prune well-aged keys.
        window_s = 300 if tf == "5m" else 900
        return (start_s + window_s) * 1_000_000

    def prune_stale_slot_state(
        self, now_us: int | None = None, *, grace_s: int = 600,
    ) -> int:
        """Drop per-slug state whose slot_end + grace is in the past.

        The sniper-v5 controller is a process-lifetime singleton in a 24/7
        engine. ``_one_shot_fired`` / ``_ft_books`` gain one entry per
        (sleeve, slug) slot window and ``_book_event_count`` one entry per
        token_id, and nothing evicts them — an unbounded leak over the
        weeks-long uptime (controllers-2). This mirrors
        ``polymarket_updown._prune_resolved_slots``: parse the trailing unix
        ts from the slug, drop keys whose slot_end + ``grace_s`` (resolution
        buffer headroom) has passed. Token_id keys in ``_book_event_count``
        carry no slug, so we evict those whose newest book event is older
        than the grace window (no fresh activity ⇒ the slot resolved).

        Returns the number of entries evicted (for observability / tests).
        Defensive: never raises; an unparseable slug is left resident.
        """
        if now_us is None:
            now_us = int(time.time() * 1_000_000)
        grace_us = int(grace_s) * 1_000_000
        evicted = 0

        # _one_shot_fired / _ft_books are keyed by (sleeve_id, slug).
        stale_one_shot = {
            key for key in self._one_shot_fired
            if (end := self._slug_slot_end_us(key[1])) is not None
            and now_us - end > grace_us
        }
        for key in stale_one_shot:
            self._one_shot_fired.discard(key)
        evicted += len(stale_one_shot)

        stale_books = [
            key for key in self._ft_books
            if (end := self._slug_slot_end_us(key[1])) is not None
            and now_us - end > grace_us
        ]
        for key in stale_books:
            self._ft_books.pop(key, None)
        evicted += len(stale_books)

        # _book_event_count is keyed by token_id (no slug) — evict by recency:
        # drop any token whose most-recent book event is older than the grace
        # window (the underlying BookMirror has unsubscribed; no new events
        # will ever land for a resolved slot's tokens).
        cutoff_us = now_us - grace_us
        stale_tokens = [
            tok for tok, dq in self._book_event_count.items()
            if not dq or dq[-1] < cutoff_us
        ]
        for tok in stale_tokens:
            self._book_event_count.pop(tok, None)
        evicted += len(stale_tokens)

        return evicted

    def _is_live_fire(self, sleeve: SniperV5Sleeve) -> bool:
        """True iff this sleeve should place a REAL order on this fire.

        Requires a wired live executor AND the fail-closed live gate
        (enabled + allowlisted). Everything else stays paper.
        """
        if self._live_executor is None:
            return False
        ok, _ = check_sniper_v5_live(
            self._live_enabled, self._live_allowlist, sleeve.sleeve_id,
        )
        return ok

    # ------------------------------------------------------------------
    # Per-sleeve eval
    # ------------------------------------------------------------------

    async def eval_sleeve_fire(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        offset_s: int,
        fire_us: int,
    ) -> list[FireResult]:
        """Per-direction eval + (if all-pass) L25 simulation + shadow-log emit.

        Returns one FireResult per direction tried (1 for UP/DOWN-only
        sleeves, 2 for BOTH).
        """
        results: list[FireResult] = []
        directions = self._directions_for(sleeve.direction)

        # Step 1 — auto-suspend short-circuit (sleeve 06 WR<80% hit).
        if sleeve.sleeve_id in self._auto_suspended:
            for direction in directions:
                fr = FireResult(
                    direction=direction,
                    all_gates_passed=False,
                    eval_only=True,
                    gates_evaluated={},
                    skip_reason="auto_suspended_wr_below_80",
                    offset_s=offset_s,
                )
                event = self._build_event(sleeve, slot, fire_us, offset_s, fr)
                self._logger.log(event)
                self._write_audit_row(
                    sleeve.sleeve_id, "poly_updown_signal", event,
                )
                results.append(fr)
            return results

        # Step 1b — fast_taker one-shot guard. Config B (one_shot_per_slug)
        # fires ONCE per slug on the first qualifying early offset; later
        # offsets for the same slug are suppressed (no rows). Config A
        # (merge_mimic, one_shot_per_slug=False) and every existing sniper-v5
        # sleeve are unaffected — the field defaults False so the 78-sleeve
        # roster keeps firing every offset.
        ft = _is_fast_taker(sleeve)
        # Live sleeves are one-shot-per-slug too (one real $1.50 entry per
        # slot) — defends against any double-eval for the same (sleeve, slug).
        _live_sleeve = self._is_live_fire(sleeve)
        if (
            (sleeve.one_shot_per_slug or _live_sleeve)
            and (sleeve.sleeve_id, slot.slug) in self._one_shot_fired
        ):
            return results

        # oracle-lag snapshot(s) — computed ONCE per fire (binance vs chainlink
        # staleness). Fed to the oracle-lag gates via _build_gate_kwargs AND
        # logged. Covers the A/B fast_taker (g_oracle_lag_bps_ge) AND the LAGV2
        # family (g_oracle_lag_with + cross-asset confluence). Computed for ANY
        # sleeve carrying an oracle-lag gate (no longer ft-gated).
        gate_names = [gr.name for gr in sleeve.gates]
        needs_oracle = any(
            n.startswith(("g_oracle_lag_bps_ge", "g_oracle_lag_with"))
            for n in gate_names
        )
        needs_confluence = any(
            n.startswith("g_cross_asset_lag_confluence") for n in gate_names
        )
        # TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01 — the fast_taker fire signal is
        # the INTRA-WINDOW BINANCE RETURN (px@fire / px@slot_open − 1), the
        # backtested signal, NOT the feed-vs-chainlink-oracle basis the prior
        # compute_oracle_lag fed (which sat persistently positive → always-UP).
        # Both g_oracle_lag_with (LAGV2) and g_oracle_lag_bps_ge (A/B) read
        # ``oracle_lag.price_delta_bps``, so threading the binance return through
        # the same field fixes all 8 sleeves with no gate/sleeve edits.
        ft_oracle_lag: Any = None
        ft_oracle_lag_other: Any = None
        if needs_oracle or needs_confluence:
            try:
                ft_oracle_lag = _binance_lag_snapshot(
                    sleeve.asset, slot.slot_start_us, fire_us,
                )
            except Exception:  # noqa: BLE001 — never block the fire eval
                ft_oracle_lag = None
        if needs_confluence:
            other_asset = (
                "ETH" if sleeve.asset == "BTC"
                else "BTC" if sleeve.asset == "ETH"
                else None
            )
            if other_asset is not None:
                try:
                    ft_oracle_lag_other = _binance_lag_snapshot(
                        other_asset, slot.slot_start_us, fire_us,
                    )
                except Exception:  # noqa: BLE001
                    ft_oracle_lag_other = None
        ft_bps = (
            float(ft_oracle_lag.price_delta_bps)
            if ft_oracle_lag is not None
            else None
        )

        for direction in directions:
            # Step 2 — sleeve 01 S6 precondition.
            if sleeve.s6_precondition and not await self._check_s6_fired(
                slot.slug, slot.ws_s
            ):
                fr = FireResult(
                    direction=direction,
                    all_gates_passed=False,
                    eval_only=True,
                    gates_evaluated={"s6_precondition": False},
                    skip_reason="s6_precondition_failed",
                    offset_s=offset_s,
                )
                event = self._build_event(sleeve, slot, fire_us, offset_s, fr)
                self._logger.log(event)
                self._write_audit_row(
                    sleeve.sleeve_id, "poly_updown_signal", event,
                )
                results.append(fr)
                continue

            # Step 3 — L25 snapshot (needed for spread + placement).
            # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — snapshot build is
            # async now (routes through paper.get_orderbook_snapshot).
            l25_snap = await self._build_l25_snapshot(slot)

            # Step 4 — spread filter (spec §0).
            # V5+V6+V7+V8 fix (2026-05-27): same-token bid-ask via
            # _sniper_spread.compute_spread; pass direction for the
            # side-being-bought selection.
            spread = self._compute_spread(l25_snap, direction)
            sf = float(sleeve.spread_filter)
            if spread is not None and spread > sf:
                fr = FireResult(
                    direction=direction,
                    all_gates_passed=False,
                    eval_only=True,
                    gates_evaluated={},
                    skip_reason=f"spread_bidask_too_wide_{spread:.4f}_>_{sf:.4f}",
                    l25_book_snapshot=l25_snap,
                    offset_s=offset_s,
                    oracle_lag_bps=ft_bps,
                )
                event = self._build_event(sleeve, slot, fire_us, offset_s, fr)
                self._logger.log(event)
                self._write_audit_row(
                    sleeve.sleeve_id, "poly_updown_signal", event,
                )
                results.append(fr)
                continue

            # Step 5 — run all gates (uniform signature). No try/except
            # fallback — TypeError from a gate is a planner bug per
            # CONTEXT.md WARNING 8, MUST bubble up loudly.
            gates_evaluated: dict[str, bool] = {}
            all_pass = True
            for gate_ref in sleeve.gates:
                runtime_kwargs = self._build_gate_kwargs(
                    gate_ref, sleeve, slot,
                    oracle_lag=ft_oracle_lag,
                    oracle_lag_other=ft_oracle_lag_other,
                )
                static_kwargs = gate_ref.bound_kwargs()
                ok = bool(gate_ref.gate(
                    direction, fire_us, **runtime_kwargs, **static_kwargs,
                ))
                gates_evaluated[gate_ref.name] = ok
                if not ok:
                    all_pass = False

            fr = FireResult(
                direction=direction,
                all_gates_passed=all_pass,
                eval_only=not all_pass,
                gates_evaluated=gates_evaluated,
                skip_reason=None if all_pass else self._first_failing_gate(
                    gates_evaluated
                ),
                l25_book_snapshot=l25_snap,
                offset_s=offset_s,
                oracle_lag_bps=ft_bps,
            )

            # Step 6+7 — sparse-book + L25 walk placement on all-pass.
            if all_pass:
                token_id = (slot.token_id_up if direction == "UP"
                            else slot.token_id_dn)
                if not self._book_dense_enough(token_id, fire_us):
                    fr = replace(
                        fr,
                        all_gates_passed=False,
                        eval_only=True,
                        skip_reason="sparse_book_under_25_events_60s",
                    )
                elif _live_sleeve:
                    # LIVE — place a REAL marketable-taker Polymarket order for
                    # the allowlisted sleeve ($1.50, hard-capped). Fail-closed:
                    # any reject / empty book / exception SKIPS the fire with a
                    # distinct skip_reason (NO synthetic fallback on a live box)
                    # and emits a critical alert inside _place_live_order.
                    # Per-sleeve live-stake override ($1 scalp probe, 2026-06-05);
                    # hard-clamped to the live max so an override can never raise
                    # the cap. None → shared global live stake (existing sleeves).
                    _ln_ovr = getattr(sleeve, "live_notional_usd_override", None)
                    live_notional = float(
                        min(Decimal(str(_ln_ovr)), SNIPER_V5_LIVE_MAX_NOTIONAL)
                        if _ln_ovr is not None
                        else self._live_notional_usd
                    )
                    live_result = await self._place_live_order(
                        token_id, live_notional, sleeve, slot,
                    )
                    if isinstance(live_result, str):
                        # V10 entry-band: out-of-band → intentional skip (NOT an
                        # exec failure), logged as an eval row with the reason.
                        fr = replace(
                            fr,
                            all_gates_passed=False,
                            eval_only=True,
                            skip_reason=live_result,
                            book_source="live",
                        )
                    elif live_result is None:
                        fr = replace(
                            fr,
                            all_gates_passed=False,
                            eval_only=True,
                            skip_reason="live_exec_failed",
                            book_source="live",
                        )
                    else:
                        fill_vwap, fill_shares, book_source = live_result
                        # TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — the live
                        # fill reports an opaque "live" book_source; compare the
                        # gate-time tier against the INNER sizing-walk tier
                        # (captured by _place_live_order) to surface gate/fill
                        # book drift. Observability only — never changes the
                        # live fill (Ireland real money).
                        bsm_live = self._record_book_source_consistency(
                            sleeve_id=sleeve.sleeve_id,
                            slug=slot.slug,
                            direction=direction,
                            gate_source=self._gate_book_source(
                                l25_snap, direction,
                            ),
                            fill_source=(
                                self._last_live_walk_source or "empty"
                            ),
                        )
                        fr = replace(
                            fr,
                            fill_vwap=fill_vwap,
                            fill_shares=fill_shares,
                            placed_size_usd=live_notional,
                            fill_latency_ms=0.0,
                            fill_method="live",
                            book_source=book_source,
                            entry_delta_bps=ft_bps,
                            book_source_mismatch=bsm_live,
                        )
                        # one real entry per slot.
                        self._one_shot_fired.add(
                            (sleeve.sleeve_id, slot.slug)
                        )
                else:
                    # Shadow-allowlist sleeves (paper on the live box) use the
                    # shadow notional; everything else uses the per-sleeve
                    # override or the default paper notional.
                    if sleeve.sleeve_id in self._shadow_allowlist:
                        notional = self._shadow_notional_usd
                    else:
                        notional = (
                            sleeve.notional_usd_override
                            if sleeve.notional_usd_override is not None
                            else self._settings.tv_poly_sniper_v5_notional_usd
                        )
                    # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — _simulate_l25_walk
                    # is async + returns None when ALL tiers (WS/CLOB/Storedata)
                    # came back empty or stale. SUPERSEDES the prior synthetic
                    # 0.5-vwap/10-share placeholder path. On None we skip the
                    # fire with a distinct skip_reason so the dashboard can
                    # count empty-tier blackouts without polluting WR/PnL.
                    walk_result = await self._simulate_l25_walk(
                        token_id, float(notional),
                    )
                    if walk_result is None:
                        fr = replace(
                            fr,
                            all_gates_passed=False,
                            eval_only=True,
                            skip_reason="empty_book_all_tiers_failed",
                            book_source="empty",
                        )
                    elif sleeve.entry_band is not None and not (
                        sleeve.entry_band[0] <= walk_result[0] < sleeve.entry_band[1]
                    ):
                        # V10 entry-band gate — paper fire skipped out-of-band.
                        fr = replace(
                            fr,
                            all_gates_passed=False,
                            eval_only=True,
                            skip_reason=(
                                f"entry_vwap_out_of_band_{walk_result[0]:.4f}"
                            ),
                            book_source=walk_result[3],
                        )
                    else:
                        fill_vwap, fill_shares, latency_ms, book_source = walk_result
                        # TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — gate gates
                        # read the gate-time L25 snapshot tier; the fill walked a
                        # separately-fetched book (``book_source``). Record
                        # whether they came from the SAME tier so gate/fill book
                        # drift (e.g. gate saw ws_mirror, fill fell through to
                        # clob) is observable. Pure observability — never alters
                        # the paper fill.
                        bsm_paper = self._record_book_source_consistency(
                            sleeve_id=sleeve.sleeve_id,
                            slug=slot.slug,
                            direction=direction,
                            gate_source=self._gate_book_source(
                                l25_snap, direction,
                            ),
                            fill_source=book_source,
                        )
                        # TV_FIX_SPRINT_2026_06_02 (strategies-3) — on a thin
                        # book the L25 walk acquires fewer shares than the full
                        # stake would buy, so the actually-spent notional
                        # (vwap*shares) is below the requested ``notional``.
                        # Record the SPENT notional (not the full stake) so
                        # placed_size_usd, fill_shares and the resolution PnL
                        # (1-vwap)*shares stay internally consistent (inv #2 —
                        # partial-fill consistency). On a full fill this equals
                        # ``float(notional)`` (within float epsilon), so the
                        # happy path is unchanged.
                        spent_usd = fill_vwap * fill_shares
                        placed_usd = min(float(notional), spent_usd)
                        fr = replace(
                            fr,
                            fill_vwap=fill_vwap,
                            fill_shares=fill_shares,
                            placed_size_usd=placed_usd,
                            fill_latency_ms=latency_ms,
                            fill_method="l25_walk",  # legacy field; always real walk post-fix
                            book_source=book_source,
                            # LAGV2: capture the entry basis for the reversal stop.
                            entry_delta_bps=ft_bps,
                            book_source_mismatch=bsm_paper,
                        )
                        # one-shot mark — FIELD-gated (not ft-gated) so the LAGV2
                        # family (excluded from _is_fast_taker) also dedups per
                        # (sleeve, slug) after its first qualifying fire.
                        if sleeve.one_shot_per_slug:
                            self._one_shot_fired.add(
                                (sleeve.sleeve_id, slot.slug)
                            )
                        # fast_taker A/B post-placement: merge-mimic inventory
                        # book + FIFO matched-pair merge (Config A). The
                        # directional residual holds to resolution; settlement
                        # happens in book_event_for_resolution.
                        if ft:
                            if sleeve.merge_mimic:
                                book = self._ft_books.setdefault(
                                    (sleeve.sleeve_id, slot.slug),
                                    _FastTakerSlugBook(),
                                )
                                book.add_take(direction, fill_vwap, fill_shares)
                                pairs, collat = book.merge_matched()
                                if pairs > 0:
                                    fr = replace(
                                        fr,
                                        merge_pairs=pairs,
                                        merge_collateral=collat,
                                    )

            # Step 8 — shadow-log emit + parallel trading.events write.
            _is_live = fr.fill_method == "live"
            event = self._build_event(
                sleeve, slot, fire_us, offset_s, fr, live=_is_live,
            )
            self._logger.log(event)
            self._write_audit_row(
                event["sleeve_id"], "poly_updown_signal", event,
            )
            results.append(fr)

        return results

    # ------------------------------------------------------------------
    # Resolution path
    # ------------------------------------------------------------------

    async def book_event_for_resolution(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fr: FireResult,
        slot_end_us: int,
        outcome: str | None,
    ) -> None:
        """Compute PnL + emit §7 sleeve_fire_resolved + sleeve 06 monitor hook."""
        # fast_taker sleeves settle on the legacy_2pct fee model (merge-mimic
        # aggregate book for Config A; per-fire for Config B) — NOT the 0.07
        # curve used by the rest of the sniper-v5 roster.
        if _is_fast_taker(sleeve):
            await self._resolve_fast_taker(
                sleeve, slot, fr, slot_end_us, outcome,
            )
            return
        if fr.fill_vwap is None or fr.fill_shares is None or outcome is None:
            return
        vwap = fr.fill_vwap
        shares = fr.fill_shares
        won = (
            (outcome == "Up" and fr.direction == "UP")
            or (outcome == "Down" and fr.direction == "DOWN")
        )
        # Winner-only Polymarket fee (operator-confirmed 2026-05-28):
        #   fee/share = 0.07 * vwap * (1 - vwap)  → charged ONLY on a WIN.
        #   net win = profit - fee = (1-vwap)*shares*(1 - 0.07*vwap)
        #   loss leg untaxed (no fee on losers).
        if won:
            pnl = (1.0 - vwap) * shares * (1.0 - 0.07 * vwap)
        else:
            pnl = -vwap * shares
        # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — populate ``won`` on the
        # FireResult BEFORE emit so the JSONL row carries it directly
        # (dashboard no longer has to derive from outcome / direction).
        fr.won = won
        # HEDGE_LATE A/B: normal oracle resolution is the "hold_to_resolve"
        # exit. (The hedge-cut path sets "hedge_late_cut" in maybe_hedge_late_cut
        # and never reaches here for that fire.)
        if fr.exit_type is None:
            fr.exit_type = "hold_to_resolve"
        _is_live = fr.fill_method == "live"
        event = self._build_event(
            sleeve, slot, slot_end_us, fr.offset_s, fr,
            event_type="sleeve_fire_resolved",
            outcome=outcome, pnl_usd=pnl, live=_is_live,
        )
        # TV_FIX_DOUBLE_RESOLUTION_2026_06_02 — stamp fill_event_id so the
        # generic on-chain resolver's dedup guard suppresses its duplicate row.
        await self._stamp_fill_event_id(event)
        self._logger.log(event)
        self._write_audit_row(
            event["sleeve_id"], "poly_updown_resolution", event,
        )
        # Sleeve 06 WR monitor hook (spec §10.2).
        if sleeve.sleeve_id == self.SLEEVE_06_ID:
            await self._check_sleeve_06_monitor(slot_end_us, won)

    async def _resolve_fast_taker(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fr: FireResult,
        slot_end_us: int,
        outcome: str | None,
    ) -> None:
        """fast_taker resolution (legacy_2pct fee: 2%-on-winning-profit only).

        Config A (``merge_mimic``): settle the aggregate per-slug book exactly
        ONCE — redeem the directional residual on the winning side at $1/share
        minus the 2% profit fee, hold the loser residual at $0, and emit a
        single ``sleeve_fire_resolved`` row carrying the merge + residual stats.
        Idempotent via ``book.settled`` (the loop schedules one resolution per
        placed fire, but the slug settles once).

        Config B (no merge): settle THIS single fire — won →
        ``shares*(1-vwap)*0.98``; lost → ``-shares*vwap``.

        Outcome truth is chainlink (``outcome`` from poly_updown_resolver), not
        the binance close.
        """
        if outcome is None:
            return
        winner = (
            "UP" if outcome == "Up"
            else "DOWN" if outcome == "Down"
            else None
        )

        if sleeve.merge_mimic:
            key = (sleeve.sleeve_id, slot.slug)
            book = self._ft_books.get(key)
            if book is None or book.settled:
                return
            book.settled = True
            res_up = book.shares("UP")
            res_dn = book.shares("DOWN")
            win_profit = book.residual_profit(winner) if winner else 0.0
            win_residual = book.shares(winner) if winner else 0.0
            fee = _FAST_TAKER_WIN_FEE * max(0.0, win_profit)
            book.cash_recovered += win_residual    # $1/winning-residual-share
            pnl = book.cash_recovered - book.cash_spent - fee
            # Net inventory tilt (pre-redeem) names the row's direction + won.
            net_side = "UP" if res_up >= res_dn else "DOWN"
            fr.direction = net_side
            fr.won = winner is not None and net_side == winner
            fr.merge_pairs = book.merge_pairs_total
            fr.merge_collateral = book.merge_pairs_total
            if fr.exit_type is None:
                fr.exit_type = "hold_to_resolve"
            event = self._build_event(
                sleeve, slot, slot_end_us, fr.offset_s, fr,
                event_type="sleeve_fire_resolved",
                outcome=outcome, pnl_usd=pnl,
                ft_extra={
                    "residual_up": res_up,
                    "residual_down": res_dn,
                    "merge_pairs_total": book.merge_pairs_total,
                    "cash_spent": book.cash_spent,
                    "cash_recovered": book.cash_recovered,
                    "win_fee": fee,
                    "n_fires": book.n_fires,
                },
            )
            # TV_FIX_DOUBLE_RESOLUTION_2026_06_02 — stamp fill_event_id.
            await self._stamp_fill_event_id(event)
            self._logger.log(event)
            self._write_audit_row(
                sleeve.sleeve_id, "poly_updown_resolution", event,
            )
            return

        # Config B — per-fire settle.
        if fr.fill_vwap is None or fr.fill_shares is None:
            return
        vwap = fr.fill_vwap
        shares = fr.fill_shares
        won = winner is not None and fr.direction == winner
        if won:
            pnl = (1.0 - vwap) * shares * (1.0 - _FAST_TAKER_WIN_FEE)
        else:
            pnl = -vwap * shares
        fr.won = won
        if fr.exit_type is None:
            fr.exit_type = "hold_to_resolve"
        event = self._build_event(
            sleeve, slot, slot_end_us, fr.offset_s, fr,
            event_type="sleeve_fire_resolved",
            outcome=outcome, pnl_usd=pnl,
        )
        # TV_FIX_DOUBLE_RESOLUTION_2026_06_02 — stamp fill_event_id.
        await self._stamp_fill_event_id(event)
        self._logger.log(event)
        self._write_audit_row(
            sleeve.sleeve_id, "poly_updown_resolution", event,
        )

    async def maybe_hedge_late_cut(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fr: FireResult,
    ) -> bool:
        """HEDGE_LATE: cut a deep-underwater position ~60s before slot_end.

        SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE_2026_05_27.md §3/§4d.

        Reads the HELD side's bid book via the canonical 3-tier primitive,
        walks bids for ``fill_shares`` to get a realistic sell vwap, and if
        that vwap is below ``fill_vwap × hedge_late_loss_ratio`` realizes the
        partial loss now (emits a ``sleeve_fire_resolved`` row, exit_type=
        ``hedge_late_cut``) and returns True. Returns False to fall through
        to the normal HOLD-to-resolve path (book unreadable / no bids /
        position healthy).
        """
        if fr.fill_vwap is None or fr.fill_shares is None:
            return False
        token_id = slot.token_id_dn if fr.direction == "DOWN" else slot.token_id_up
        try:
            book = await self._fetch_book_via_snapshot_fn(token_id)
        except Exception:  # noqa: BLE001 — can't read book → HOLD to resolve
            return False
        bids = book.get("bids") or []
        if not bids:
            return False  # no bids to sell into → HOLD to resolve
        sell_vwap = self._walk_bids_for_shares(bids, fr.fill_shares)
        if sell_vwap is None:
            return False
        if sell_vwap >= fr.fill_vwap * float(sleeve.hedge_late_loss_ratio):
            return False  # position healthy → HOLD to resolve
        # Deep underwater → realize the partial loss now.
        # Legacy fee model (spec §3): loss leg untaxed; 2% only on profit.
        pnl = (sell_vwap - fr.fill_vwap) * fr.fill_shares
        pnl = pnl if pnl <= 0 else pnl * 0.98
        fr.exit_type = "hedge_late_cut"
        fr.hedge_sell_vwap = sell_vwap
        slot_end_us = slot.slot_start_us + (
            300 if slot.tf == "5m" else 900
        ) * 1_000_000
        event = self._build_event(
            sleeve, slot, slot_end_us, fr.offset_s, fr,
            event_type="sleeve_fire_resolved",
            outcome=None, pnl_usd=pnl,
        )
        # TV_FIX_DOUBLE_RESOLUTION_2026_06_02 — stamp fill_event_id.
        await self._stamp_fill_event_id(event)
        self._logger.log(event)
        self._write_audit_row(
            sleeve.sleeve_id, "poly_updown_resolution", event,
        )
        logger.info(
            "sniper_v5.hedge_late_cut",
            sleeve_id=sleeve.sleeve_id, slug=slot.slug,
            fill_vwap=fr.fill_vwap, sell_vwap=sell_vwap, pnl_usd=pnl,
        )
        return True

    async def maybe_reversal_stop(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fr: FireResult,
    ) -> bool:
        """LAG_REVERSAL_STOP: cut early iff binance has REVERSED >=
        ``reversal_stop_bps`` against the entry direction since fill.

        Recomputes the current oracle-lag delta and measures how far it moved
        back through the entry basis. On a qualifying reversal, sells the held
        side at the L25 bid (0.07 winner-only fee on a profitable sale) and
        emits a ``sleeve_fire_resolved`` row (exit_type="lag_reversal_cut").
        Returns True when cut; False to fall through to slot-end resolution.

        Signal-driven ONLY — there is NO price-floor stop (backtest: floor stops
        realize recoverable noise dips and gut $/tr).
        """
        if (
            fr.fill_vwap is None
            or fr.fill_shares is None
            or fr.entry_delta_bps is None
        ):
            return False
        # TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01 — measure the reversal on the SAME
        # intra-window binance-return basis as the entry signal (entry_delta_bps
        # now holds that return), NOT the feed-vs-oracle basis. "binance reversed
        # ≥ reversal_stop_bps against entry since slot open."
        try:
            snap = _binance_lag_snapshot(
                sleeve.asset, slot.slot_start_us,
                int(time.time() * 1_000_000),
            )
        except Exception:  # noqa: BLE001 — can't read feed → HOLD to resolve
            snap = None
        if snap is None:
            return False
        moved = float(snap.price_delta_bps)
        # entry UP wanted binance up since slot open; a reversal pulls the return
        # back below the entry basis. entry DOWN is the mirror.
        if fr.direction == "UP":
            reversed_bps = fr.entry_delta_bps - moved
        else:
            reversed_bps = moved - fr.entry_delta_bps
        if reversed_bps < float(sleeve.reversal_stop_bps):
            return False
        token_id = slot.token_id_dn if fr.direction == "DOWN" else slot.token_id_up
        try:
            book = await self._fetch_book_via_snapshot_fn(token_id)
        except Exception:  # noqa: BLE001 — can't read book → HOLD to resolve
            return False
        bids = book.get("bids") or []
        if not bids:
            return False  # no bids to sell into → HOLD to resolve
        sell_vwap = self._walk_bids_for_shares(bids, fr.fill_shares)
        if sell_vwap is None:
            return False
        # 0.07 winner-only curve on the sale (spec §5); loss leg untaxed.
        pnl = (sell_vwap - fr.fill_vwap) * fr.fill_shares
        pnl = pnl if pnl <= 0 else pnl * (1.0 - 0.07 * sell_vwap)
        fr.exit_type = "lag_reversal_cut"
        fr.hedge_sell_vwap = sell_vwap
        fr.reversal_bps_at_exit = reversed_bps
        slot_end_us = slot.slot_start_us + (
            300 if slot.tf == "5m" else 900
        ) * 1_000_000
        event = self._build_event(
            sleeve, slot, slot_end_us, fr.offset_s, fr,
            event_type="sleeve_fire_resolved",
            outcome=None, pnl_usd=pnl,
        )
        # TV_FIX_DOUBLE_RESOLUTION_2026_06_02 — stamp fill_event_id.
        await self._stamp_fill_event_id(event)
        self._logger.log(event)
        self._write_audit_row(
            sleeve.sleeve_id, "poly_updown_resolution", event,
        )
        logger.info(
            "sniper_v5.lag_reversal_cut",
            sleeve_id=sleeve.sleeve_id, slug=slot.slug,
            entry_delta_bps=fr.entry_delta_bps, reversed_bps=reversed_bps,
            fill_vwap=fr.fill_vwap, sell_vwap=sell_vwap, pnl_usd=pnl,
        )
        return True

    async def maybe_scalp_exit(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fr: FireResult,
        *,
        mode: str,
    ) -> bool:
        """SCALP_EXIT (TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02) — sell the held
        side ON THE BOOK mid-window instead of holding to chainlink resolution.

        ``mode="poll"``: exit iff best_bid >= ``scalp_tp_bid`` (TP) OR best_bid <=
        ``fill_vwap - scalp_stop_delta`` (stop). Returns False to keep polling.
        ``mode="deadline"``: time exit at fire_us + ``scalp_exit_offset_s`` — sell
        at the bid. Returns False ONLY when the book is empty (caller then falls
        back to hold-to-resolution and logs the empty-book risk case).

        On a real exit: walk the bid for the full position, compute the
        round-trip PnL (buy fee $0 taker; sell fee logged — $0 proxy until the
        live taker-sell fee is verified, graduation gate §7.2), and emit a
        ``kind='poly_updown_scalp_exit'`` row (event_type='sleeve_scalp_exit').
        This kind is DISTINCT from ``poly_updown_resolution`` so the scalp PnL
        never double-counts in the main WR/PnL aggregations (spec §6). SHADOW
        only — the scalp sleeves are paper.
        """
        if fr.fill_vwap is None or fr.fill_shares is None:
            return False
        key = (sleeve.sleeve_id, slot.slug)
        if key in self._scalp_exited:
            return True  # already exited this slug
        token_id = slot.token_id_dn if fr.direction == "DOWN" else slot.token_id_up
        try:
            book = await self._fetch_book_via_snapshot_fn(token_id)
        except Exception:  # noqa: BLE001 — can't read book → keep/hold
            return False
        bids = book.get("bids") or []
        if not bids:
            return False  # empty book — poll: wait; deadline: fall back to hold
        try:
            best_bid = float(bids[0]["price"])
        except (KeyError, TypeError, ValueError, IndexError):
            return False
        if mode == "poll":
            # SCALP_EXIT_CONFIG_BY_TF_2026_06_06: the taker-TP@scalp_tp_bid (0.65)
            # leaks edge → OFF by default. The stop@(fill_vwap-scalp_stop_delta)
            # is protective +EV → stays ON. getattr defaults keep boxes whose
            # dataclass predates the flags correct (TP off, stop on).
            tp_on = bool(getattr(sleeve, "scalp_tp_enabled", False))
            stop_on = bool(getattr(sleeve, "scalp_stop_enabled", True))
            if tp_on and best_bid >= float(sleeve.scalp_tp_bid):
                trigger = "tp065"
            elif stop_on and best_bid <= fr.fill_vwap - float(sleeve.scalp_stop_delta):
                trigger = "stop"
            else:
                return False
        else:  # deadline → time exit
            trigger = "time60"
        # LIVE (Ireland real money): place a REAL FAK sell of the held shares.
        # SHADOW/paper: synthetic L25 bid-walk (unchanged). On a live non-fill we
        # do NOT fabricate a cut — return False so the position holds to
        # on-chain resolution (the redeemer settles it). Fail-safe.
        live = self._is_live_fire(sleeve)
        if live:
            sold = await self._place_live_scalp_sell(
                sleeve, slot, fr, token_id, best_bid, trigger,
            )
            if sold is None:
                return False  # live sell failed/empty → HOLD to resolution
            sell_vwap, exit_shares = sold
        else:
            sell_vwap = self._walk_bids_for_shares(bids, fr.fill_shares)
            if sell_vwap is None:
                return False
            exit_shares = fr.fill_shares
        sell_leg_fee = 0.0  # offline proxy $0; LOG it (gate §7.2 verifies live)
        pnl = (sell_vwap - fr.fill_vwap) * exit_shares - sell_leg_fee
        exit_depth = 0.0
        for lvl in bids[:25]:
            try:
                exit_depth += float(lvl["price"]) * float(lvl["size"])
            except (KeyError, TypeError, ValueError):
                continue
        self._scalp_exited.add(key)
        fr.exit_type = f"scalp_{trigger}"
        fr.hedge_sell_vwap = sell_vwap
        tf_s = 300 if slot.tf == "5m" else 900
        slot_end_us = slot.slot_start_us + tf_s * 1_000_000
        event = self._build_event(
            sleeve, slot, slot_end_us, fr.offset_s, fr,
            event_type="sleeve_scalp_exit", outcome=None, pnl_usd=pnl,
            live=live,
        )
        event["scalp_exit"] = {
            "entry_vwap": fr.fill_vwap,
            "exit_vwap": sell_vwap,
            "exit_trigger": trigger,
            # 2026-06-03 — the TP / stop LEVELS so the trade card can show
            # entry · TP · SL for every scalp round-trip (not just the exit).
            "tp_bid": float(sleeve.scalp_tp_bid),
            "stop_bid": fr.fill_vwap - float(sleeve.scalp_stop_delta),
            "sell_leg_fee_charged": sell_leg_fee,
            "exit_book_depth": exit_depth,
            "delta_bps": fr.oracle_lag_bps,
            # SHARES actually sold (live: REAL exit fill; shadow: full entry).
            "shares": exit_shares,
            "scalp_pnl_usd": pnl,
            "side": fr.direction,
            "best_bid_at_exit": best_bid,
            "live": live,
        }
        self._logger.log(event)
        # Live exit rows carry the ``_LIVE`` sleeve_id (set by _build_event) so
        # they join the live portfolio/header filter; shadow rows stay bare.
        self._write_audit_row(
            event["sleeve_id"], "poly_updown_scalp_exit", event,
        )
        logger.info(
            "sniper_v5.scalp_exit",
            sleeve_id=event["sleeve_id"], slug=slot.slug, trigger=trigger,
            entry_vwap=fr.fill_vwap, exit_vwap=sell_vwap,
            shares=exit_shares, pnl_usd=pnl, live=live,
        )
        return True

    async def _place_live_scalp_sell(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fr: FireResult,
        token_id: str,
        best_bid: float,
        trigger: str,
        qty: Decimal | None = None,
    ) -> tuple[float, float] | None:
        """Place a REAL FAK sell of the held scalp position (Ireland live).

        ``qty`` overrides the sold size (the maker-exit taker fallback sells only
        the unfilled remainder, not the full entry); defaults to ``fr.fill_shares``.

        Returns ``(sell_vwap, sold_shares)`` from the VENUE-CONFIRMED exit fill,
        or ``None`` (fail-safe) when the executor is missing / the sell does not
        confirm a real fill / any exception. ``None`` → the caller HOLDS the
        position to on-chain resolution (the redeemer settles it); we NEVER
        fabricate a cut off an unconfirmed sell (inv #1/#2 discipline, mirrors
        the Kalshi maybe_hedge_late_cut live path).

        The UserFillMirror is already watching this market (subscribed at the
        live ENTRY), so the client's 3-tier reconcile (WS → REST → fail-closed)
        covers a CLOB read-timeout on the sell exactly as it does on the buy.
        """
        if self._live_executor is None or fr.fill_shares is None:
            return None
        sell_qty = qty if qty is not None else Decimal(str(fr.fill_shares))
        if sell_qty <= 0:
            return None
        live_sleeve_id = f"{sleeve.sleeve_id}_LIVE"
        try:
            result = await self._live_executor.place_exit_order(
                token_id=int(token_id),
                qty=sell_qty,
                limit_px=_SNIPER_V5_LIVE_SELL_LIMIT_PX,
                sleeve_id=live_sleeve_id,
                side="sell",
            )
        except Exception as exc:  # noqa: BLE001 — fail-safe: HOLD to resolution
            logger.exception(
                "poly_sniper_v5.live_scalp_sell_failed",
                sleeve_id=live_sleeve_id, slug=slot.slug, token_id=token_id,
                trigger=trigger,
            )
            await self._emit_live_alert(
                live_sleeve_id, slot.slug,
                reason=f"scalp_sell_exc: {exc!r}"[:160],
            )
            return None
        status_str = str(getattr(result, "status", "")).split(".")[-1].lower()
        if not any(s in status_str for s in ("filled", "partial")):
            logger.warning(
                "poly_sniper_v5.live_scalp_sell_not_filled",
                sleeve_id=live_sleeve_id, slug=slot.slug, status=status_str,
                reason=str(getattr(result, "reason", "") or ""), trigger=trigger,
            )
            await self._emit_live_alert(
                live_sleeve_id, slot.slug,
                reason=f"scalp_sell_not_filled: {status_str}",
            )
            return None
        raw = getattr(result, "raw_response", None) or {}
        try:
            _fs = raw.get("filled_shares") or raw.get("filled")
            sold_shares = float(_fs) if _fs else 0.0
        except (TypeError, ValueError):
            sold_shares = 0.0
        try:
            sell_vwap = (
                float(raw.get("avg_price")) if raw.get("avg_price") else None
            )
        except (TypeError, ValueError):
            sell_vwap = None
        if sold_shares <= 0 or sell_vwap is None:
            logger.warning(
                "poly_sniper_v5.live_scalp_sell_ack_without_fill",
                sleeve_id=live_sleeve_id, slug=slot.slug,
                sold_shares=sold_shares, avg_price=sell_vwap, trigger=trigger,
            )
            await self._emit_live_alert(
                live_sleeve_id, slot.slug,
                reason="scalp_sell_ack_without_fill",
            )
            return None
        logger.info(
            "poly_sniper_v5.live_scalp_sell_fill",
            sleeve_id=live_sleeve_id, slug=slot.slug, trigger=trigger,
            sell_vwap=sell_vwap, sold_shares=sold_shares,
            entry_shares=fr.fill_shares,
            order_id=str(getattr(result, "order_id", "") or ""),
        )
        return sell_vwap, sold_shares

    # ------------------------------------------------------------------ #
    # SCALP MAKER EXIT (TV_AGENT_SPEC_SCALP_MAKER_EXIT_2026_06_06)        #
    # Poly 15m only: rest a maker SELL on entry, keep the protective stop, #
    # taker-cross the unfilled remainder at +60. SHADOW simulates the      #
    # maker fill from the book; LIVE posts a real GTC order + reconciles   #
    # the filled qty from the held balance. Kalshi never uses this.        #
    # ------------------------------------------------------------------ #
    async def scalp_maker_post(
        self, sleeve: SniperV5Sleeve, slot: SlotInfo, fr: FireResult
    ) -> None:
        """Post the resting maker SELL at the start of a maker-mode scalp window.

        ``maker_fixed`` rests at ``scalp_maker_tp`` (0.60 = validated 15m target);
        ``maker_peg`` rests at the current best ask. SHADOW records a virtual
        order (no venue call). LIVE posts a real GTC maker SELL and tracks its id
        so the deadline can cancel the remainder. Fail-safe: a failed/absent post
        just leaves the position to the taker fallback at +60.
        """
        if fr.fill_vwap is None or fr.fill_shares is None:
            return
        key = (sleeve.sleeve_id, slot.slug)
        if key in self._scalp_maker_orders or key in self._scalp_exited:
            return
        token_id = slot.token_id_dn if fr.direction == "DOWN" else slot.token_id_up
        mode = str(getattr(sleeve, "scalp_exit_mode", "taker"))
        maker_price = float(getattr(sleeve, "scalp_maker_tp", 0.60))
        if mode == "maker_peg":
            try:
                book = await self._fetch_book_via_snapshot_fn(token_id)
                asks = book.get("asks") or []
                if asks:
                    maker_price = float(asks[0]["price"])
            except Exception:  # noqa: BLE001 — fall back to the fixed target
                pass
        state: dict = {"maker_price": maker_price, "order_id": None, "mode": mode}
        if self._is_live_fire(sleeve) and self._live_executor is not None:
            try:
                result = await self._live_executor.place_maker_sell(
                    token_id=int(token_id),
                    qty=Decimal(str(fr.fill_shares)),
                    limit_px=Decimal(str(round(maker_price, 4))),
                    sleeve_id=f"{sleeve.sleeve_id}_LIVE",
                )
                state["order_id"] = (
                    str(getattr(result, "order_id", "") or "") or None
                )
            except Exception as exc:  # noqa: BLE001 — taker fallback at +60
                logger.warning(
                    "poly_sniper_v5.scalp_maker_post_failed",
                    sleeve_id=f"{sleeve.sleeve_id}_LIVE", slug=slot.slug,
                    error=str(exc),
                )
        self._scalp_maker_orders[key] = state

    async def _scalp_maker_live_filled(
        self, token_id: str, total_shares: float
    ) -> float | None:
        """LIVE: how many shares of the resting maker SELL have filled =
        ``total − current conditional balance``. None when the read fails (the
        caller then conservatively assumes nothing maker-filled and sells all)."""
        if self._live_executor is None:
            return None
        try:
            bal = await self._live_executor.conditional_balance(int(token_id))
            return max(0.0, total_shares - float(bal))
        except Exception:  # noqa: BLE001
            return None

    async def maybe_scalp_maker_exit(
        self, sleeve: SniperV5Sleeve, slot: SlotInfo, fr: FireResult, *, mode: str
    ) -> bool:
        """Maker-mode scalp exit poll/deadline. Returns True when fully resolved.

        poll: (1) maker offer lifted → maker exit (fee 0 + rebate); (2) else the
        protective stop trips → cancel + taker-sell all; else keep polling.
        deadline: cancel any resting maker order + taker-sell the remainder
        (``time60``; a partial maker fill yields a part-maker / part-taker row).
        """
        if fr.fill_vwap is None or fr.fill_shares is None:
            return False
        key = (sleeve.sleeve_id, slot.slug)
        if key in self._scalp_exited:
            return True
        state = self._scalp_maker_orders.get(key) or {}
        token_id = slot.token_id_dn if fr.direction == "DOWN" else slot.token_id_up
        try:
            book = await self._fetch_book_via_snapshot_fn(token_id)
        except Exception:  # noqa: BLE001 — can't read book → hold/keep
            return False
        bids = book.get("bids") or []
        best_bid: float | None = None
        if bids:
            try:
                best_bid = float(bids[0]["price"])
            except (KeyError, TypeError, ValueError, IndexError):
                best_bid = None
        maker_price = float(
            state.get("maker_price", getattr(sleeve, "scalp_maker_tp", 0.60))
        )
        stop_on = bool(getattr(sleeve, "scalp_stop_enabled", True))
        stop_px = fr.fill_vwap - float(sleeve.scalp_stop_delta)
        live = self._is_live_fire(sleeve)

        if mode == "poll":
            total = float(fr.fill_shares)
            # 1. maker offer lifted (full fill)?
            if live:
                mf = await self._scalp_maker_live_filled(token_id, total)
                if mf is not None and mf >= total - 1e-6:
                    return self._emit_maker_scalp_exit(
                        sleeve, slot, fr, bids=bids, trigger="maker_lift",
                        maker_shares=mf, maker_vwap=maker_price,
                        taker_shares=0.0, taker_vwap=None,
                        best_bid=best_bid, live=True,
                    )
            elif best_bid is not None and best_bid >= maker_price:
                return self._emit_maker_scalp_exit(
                    sleeve, slot, fr, bids=bids, trigger="maker_lift",
                    maker_shares=total, maker_vwap=maker_price,
                    taker_shares=0.0, taker_vwap=None,
                    best_bid=best_bid, live=False,
                )
            # 2. protective stop?
            if stop_on and best_bid is not None and best_bid <= stop_px:
                return await self._scalp_maker_taker_remainder(
                    sleeve, slot, fr, state, token_id, bids, best_bid,
                    trigger="stop", live=live,
                )
            return False
        # deadline → cancel resting maker + taker-sell whatever's left.
        return await self._scalp_maker_taker_remainder(
            sleeve, slot, fr, state, token_id, bids, best_bid,
            trigger="time60", live=live,
        )

    async def _scalp_maker_taker_remainder(
        self, sleeve, slot, fr, state, token_id, bids, best_bid, *, trigger, live
    ) -> bool:
        """Stop / deadline path: cancel the resting maker, then taker-sell the
        unfilled remainder. LIVE attributes the maker-filled portion from the
        held balance (oversell-safe — place_exit_order re-checks balance)."""
        key = (sleeve.sleeve_id, slot.slug)
        if key in self._scalp_exited:
            return True
        total = float(fr.fill_shares)
        maker_vwap = float(
            state.get("maker_price", getattr(sleeve, "scalp_maker_tp", 0.60))
        )
        maker_shares = 0.0
        taker_shares = 0.0
        taker_vwap: float | None = None
        if live:
            oid = state.get("order_id")
            if oid and self._live_executor is not None:
                # best-effort cancel; the balance-checked taker sell guards oversell
                with contextlib.suppress(Exception):
                    await self._live_executor.cancel_order(oid)
            mf = await self._scalp_maker_live_filled(token_id, total)
            maker_shares = mf if mf is not None else 0.0
            remaining = max(0.0, total - maker_shares)
            if remaining <= 1e-6:
                return self._emit_maker_scalp_exit(
                    sleeve, slot, fr, bids=bids, trigger="maker_lift",
                    maker_shares=maker_shares, maker_vwap=maker_vwap,
                    taker_shares=0.0, taker_vwap=None, best_bid=best_bid, live=True,
                )
            sold = await self._place_live_scalp_sell(
                sleeve, slot, fr, token_id, best_bid or 0.0, trigger,
                qty=Decimal(str(round(remaining, 6))),
            )
            if sold is None:
                # taker leg failed → record any confirmed maker fill, hold the rest.
                if maker_shares > 1e-6:
                    return self._emit_maker_scalp_exit(
                        sleeve, slot, fr, bids=bids, trigger="maker_lift",
                        maker_shares=maker_shares, maker_vwap=maker_vwap,
                        taker_shares=0.0, taker_vwap=None,
                        best_bid=best_bid, live=True,
                    )
                return False  # nothing sold → hold to resolution (redeemer settles)
            taker_vwap, taker_shares = sold
        else:
            sv = self._walk_bids_for_shares(bids, total)
            if sv is None:
                return False
            taker_shares = total
            taker_vwap = sv
        return self._emit_maker_scalp_exit(
            sleeve, slot, fr, bids=bids, trigger=trigger,
            maker_shares=maker_shares, maker_vwap=maker_vwap,
            taker_shares=taker_shares, taker_vwap=taker_vwap,
            best_bid=best_bid, live=live,
        )

    def _emit_maker_scalp_exit(
        self, sleeve, slot, fr, *, bids, trigger,
        maker_shares, maker_vwap, taker_shares, taker_vwap, best_bid, live,
    ) -> bool:
        """Build + log + audit a maker-mode scalp exit row, mark exited once."""
        key = (sleeve.sleeve_id, slot.slug)
        if key in self._scalp_exited:
            return True
        entry = float(fr.fill_vwap)
        maker_shares = max(0.0, float(maker_shares))
        taker_shares = max(0.0, float(taker_shares))
        total_shares = maker_shares + taker_shares
        # Maker rebate (the maker upside the A/B measures): a share of the fee
        # curve credited back on maker-filled size. Taker fee modelled $0 (matches
        # the existing taker scalp convention; offline re-baseline applies 0.07).
        rebate_share = float(getattr(sleeve, "scalp_maker_rebate_share", 0.20))
        rebate = (
            rebate_share * 0.07 * maker_vwap * (1.0 - maker_vwap) * maker_shares
            if maker_shares > 0
            else 0.0
        )
        pnl = (maker_vwap - entry) * maker_shares + rebate
        if taker_shares > 0 and taker_vwap is not None:
            pnl += (taker_vwap - entry) * taker_shares
        fill_rate = (maker_shares / total_shares) if total_shares > 0 else 0.0
        blended = (
            (maker_vwap * maker_shares + (taker_vwap or 0.0) * taker_shares)
            / total_shares
            if total_shares > 0
            else maker_vwap
        )
        self._scalp_exited.add(key)
        self._scalp_maker_orders.pop(key, None)
        fr.exit_type = f"scalp_{trigger}"
        fr.hedge_sell_vwap = blended
        tf_s = 300 if slot.tf == "5m" else 900
        slot_end_us = slot.slot_start_us + tf_s * 1_000_000
        event = self._build_event(
            sleeve, slot, slot_end_us, fr.offset_s, fr,
            event_type="sleeve_scalp_exit", outcome=None, pnl_usd=pnl, live=live,
        )
        event["scalp_exit"] = {
            "entry_vwap": entry,
            "exit_vwap": blended,
            "exit_trigger": trigger,
            "exit_mode": str(getattr(sleeve, "scalp_exit_mode", "taker")),
            "maker_shares": maker_shares,
            "maker_vwap": maker_vwap if maker_shares > 0 else None,
            "taker_shares": taker_shares,
            "taker_vwap": taker_vwap,
            "maker_fill_rate": fill_rate,
            "rebate_usd": rebate,
            "shares": total_shares,
            "scalp_pnl_usd": pnl,
            "side": fr.direction,
            "best_bid_at_exit": best_bid,
            "delta_bps": fr.oracle_lag_bps,
            "live": live,
        }
        self._logger.log(event)
        self._write_audit_row(
            event["sleeve_id"], "poly_updown_scalp_exit", event,
        )
        logger.info(
            "poly_sniper_v5.scalp_maker_exit",
            sleeve_id=event["sleeve_id"], slug=slot.slug, trigger=trigger,
            exit_mode=event["scalp_exit"]["exit_mode"],
            maker_shares=maker_shares, taker_shares=taker_shares,
            maker_fill_rate=fill_rate, pnl_usd=pnl, live=live,
        )
        return True

    async def record_scalp_counterfactual(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fr: FireResult,
        outcome: str | None,
    ) -> None:
        """At slot_end, log what HOLD-to-resolution would have paid for a
        scalp-exited fire (monitoring only — the A/B vs the realized scalp PnL).

        Emits ``kind='poly_updown_scalp_exit'`` / event_type='scalp_hold_counterfactual'
        — NOT a resolution row, so it never affects any WR/PnL aggregation.
        """
        if outcome is None or fr.fill_vwap is None or fr.fill_shares is None:
            return
        won = (
            (outcome == "Up" and fr.direction == "UP")
            or (outcome == "Down" and fr.direction == "DOWN")
        )
        vwap, shares = fr.fill_vwap, fr.fill_shares
        hold_pnl = (
            (1.0 - vwap) * shares * (1.0 - 0.07 * vwap) if won else -vwap * shares
        )
        tf_s = 300 if slot.tf == "5m" else 900
        slot_end_us = slot.slot_start_us + tf_s * 1_000_000
        event = self._build_event(
            sleeve, slot, slot_end_us, fr.offset_s, fr,
            event_type="scalp_hold_counterfactual", outcome=outcome,
            pnl_usd=None,
        )
        event["scalp_hold_counterfactual"] = {
            "hold_pnl_usd": hold_pnl,
            "won": won,
            "entry_vwap": vwap,
            "shares": shares,
            "side": fr.direction,
        }
        self._logger.log(event)
        self._write_audit_row(
            sleeve.sleeve_id, "poly_updown_scalp_exit", event,
        )

    @staticmethod
    def _walk_bids_for_shares(
        bids: list[dict[str, Any]], shares: float,
    ) -> float | None:
        """Size-weighted sell vwap from walking the bid book for ``shares``.

        Walks best-bid-first (``bids[0]`` is the highest bid). Stops once
        ``shares`` are filled; if the book is thinner than ``shares`` it
        returns the vwap over whatever liquidity exists (a thin book is
        itself a bearish tell). Returns None when no usable bid exists.
        """
        if shares is None or shares <= 0:
            return None
        got_shares = 0.0
        got_notional = 0.0
        for lvl in bids[:25]:
            try:
                price = float(lvl["price"])
                size = float(lvl["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if price <= 0 or size <= 0:
                continue
            remaining = shares - got_shares
            take = size if size < remaining else remaining
            got_shares += take
            got_notional += take * price
            if got_shares >= shares:
                break
        if got_shares <= 0:
            return None
        return got_notional / got_shares

    async def _check_sleeve_06_monitor(self, fire_us: int, won: bool) -> None:
        """First-30-fires WR<80% auto-suspend per spec §10.2."""
        if len(self._sleeve_06_resolutions) >= self.SLEEVE_06_MONITOR_N:
            return  # already evaluated
        self._sleeve_06_resolutions.append((fire_us, won))
        if len(self._sleeve_06_resolutions) == self.SLEEVE_06_MONITOR_N:
            wins = sum(1 for _, w in self._sleeve_06_resolutions if w)
            wr = wins / self.SLEEVE_06_MONITOR_N
            if wr < self.SLEEVE_06_MIN_WR:
                if self._alert_service is not None:
                    try:
                        await self._alert_service.emit(
                            severity="CRITICAL",
                            kind="poly_sniper_v5_sleeve_06_wr_below_80",
                            sleeve_id=self.SLEEVE_06_ID,
                            wr=wr,
                            wins=wins,
                            losses=self.SLEEVE_06_MONITOR_N - wins,
                            n_evaluated=self.SLEEVE_06_MONITOR_N,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "poly_sniper_v5.sleeve_06_monitor.alert_emit_failed"
                        )
                self._auto_suspended.add(self.SLEEVE_06_ID)
                logger.warning(
                    "poly_sniper_v5.sleeve_06_auto_suspended",
                    wr=wr, wins=wins, threshold=self.SLEEVE_06_MIN_WR,
                )

    # ------------------------------------------------------------------
    # Audit row writer (Phase 35.2) — parallel write to trading.events
    # ------------------------------------------------------------------

    def _write_audit_row(
        self, sleeve_id: str, kind: str, payload: dict[str, Any],
    ) -> None:
        """Fire-and-forget parallel write to ``trading.events``.

        Dashboard fire-count queries filter on ``kind='poly_updown_signal'``
        (per-fire eval rows) and ``kind='poly_updown_resolution'`` (slot-end
        outcome rows). Sniper-v5 reuses those kinds so cards populate via
        the SAME backend query infrastructure used by poly_updown / momo
        / sniper / v3 sleeves — zero dashboard code change.

        Defensive: NEVER raises. DB write failures get a warning log but
        cannot break the fire eval path or the JSONL emit. ``write_pool``
        is optional (None in tests + when DB is unavailable).

        Fire-and-forget via ``asyncio.create_task`` so DB latency doesn't
        block ``eval_sleeve_fire`` or ``book_event_for_resolution``.
        """
        if self._write_pool is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (sync test context) — silently skip.
            return
        # TV_FIX_SPRINT_2026_06_02 (controllers-5 / strategies-2) — retain a
        # strong reference to the task so it cannot be garbage-collected before
        # the INSERT completes, then drop it on completion to bound the set.
        task = loop.create_task(
            self._write_audit_row_inner(sleeve_id, kind, payload),
            name=f"sniper_v5.audit.{sleeve_id}.{kind}",
        )
        self._audit_tasks.add(task)
        task.add_done_callback(self._audit_tasks.discard)

    async def _write_audit_row_inner(
        self, sleeve_id: str, kind: str, payload: dict[str, Any],
    ) -> None:
        try:
            async with self._write_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO trading.events (at, sleeve_id, kind, data) "
                    "VALUES (now(), $1, $2, $3::jsonb)",
                    sleeve_id, kind, json.dumps(payload, default=str),
                )
        except Exception as exc:  # noqa: BLE001 — audit must never mask flow
            logger.warning(
                "poly_sniper_v5.audit_row_write_failed",
                sleeve_id=sleeve_id, kind=kind, error=str(exc),
            )

    # ------------------------------------------------------------------
    # Helpers (private)
    # ------------------------------------------------------------------

    @staticmethod
    def _directions_for(direction: str) -> tuple[str, ...]:
        if direction == "BOTH":
            return ("UP", "DOWN")
        if direction == "UP":
            return ("UP",)
        if direction == "DOWN":
            return ("DOWN",)
        return ()

    @staticmethod
    def _first_failing_gate(gates_evaluated: dict[str, bool]) -> str | None:
        for name, ok in gates_evaluated.items():
            if not ok:
                return f"{name}=False"
        return None

    async def _fetch_book_via_snapshot_fn(self, token_id: str) -> dict:
        """Canonical 3-tier book read (TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27).

        Routes through ``self._book_snapshot_fn`` (bound to
        ``paper.get_orderbook_snapshot`` in production) which provides
        WS → CLOB → Storedata fallback identical to the production momo
        controller. Returns the same book dict shape regardless of which
        tier answered, with ``_source ∈ {"ws_mirror","clob","storedata","empty"}``
        and an optional ``_stale: True`` flag when the tier's book is too
        old to act on.

        When ``self._book_snapshot_fn`` is None (test-only path that
        passes only ``book_mirror``), this adapter synthesizes the dict
        from the synchronous in-memory mirror so existing test fixtures
        still work. Production engine wiring always supplies
        ``book_snapshot_fn``; tests that exercise the empty-tier skip
        path can pass a stub.
        """
        if self._book_snapshot_fn is not None:
            try:
                return await self._book_snapshot_fn(int(token_id))
            except Exception as exc:  # noqa: BLE001 — degrade to empty
                logger.exception(
                    "sniper_v5.book_fetch_failed",
                    token_id=token_id, error=str(exc),
                )
                return {"asks": [], "bids": [], "ts": 0, "_source": "empty"}
        # Legacy fallback — synchronous book_mirror only.
        if self._book_mirror is None:
            return {"asks": [], "bids": [], "ts": 0, "_source": "empty"}
        book = self._book_mirror.get(token_id)
        if not book:
            return {"asks": [], "bids": [], "ts": 0, "_source": "empty"}
        out = dict(book)
        # Test-time shim: tag tier as ws_mirror when shape came from the
        # in-memory mirror. Tests that want to inject empty / clob / etc.
        # should pass a ``book_snapshot_fn`` stub directly.
        out.setdefault("_source", "ws_mirror")
        return out

    async def _build_l25_snapshot(self, slot: SlotInfo) -> L25BookSnapshot:
        """Compute per-side L25 VWAP + total notional + top-of-book + book_source.

        V5+V6+V7+V8 fix (2026-05-27): also extracts the top-of-book
        ``ask0`` / ``bid0`` for the same-token bid-ask spread filter
        (matches backtest ``engine_v2.fill_at_book``).

        TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27: routes through the
        canonical 3-tier book primitive via ``_fetch_book_via_snapshot_fn``
        and propagates ``up_book_source`` / ``dn_book_source`` into the
        snapshot for audit trail.
        """
        up_book = await self._fetch_book_via_snapshot_fn(slot.token_id_up)
        dn_book = await self._fetch_book_via_snapshot_fn(slot.token_id_dn)
        up_vwap, up_depth = self._compute_l25_vwap_and_depth(up_book)
        dn_vwap, dn_depth = self._compute_l25_vwap_and_depth(dn_book)
        up_ask0, up_bid0 = self._top_of_book(up_book)
        dn_ask0, dn_bid0 = self._top_of_book(dn_book)
        up_src = str(up_book.get("_source") or "empty")
        dn_src = str(dn_book.get("_source") or "empty")
        # Treat stale books as ``empty`` for the snapshot source field so
        # downstream gates don't trust degenerate data.
        if up_book.get("_stale"):
            up_src = "empty"
        if dn_book.get("_stale"):
            dn_src = "empty"
        return L25BookSnapshot(
            up_vwap=up_vwap, dn_vwap=dn_vwap,
            up_depth_usd=up_depth, dn_depth_usd=dn_depth,
            up_ask0=up_ask0, up_bid0=up_bid0,
            dn_ask0=dn_ask0, dn_bid0=dn_bid0,
            up_book_source=up_src, dn_book_source=dn_src,
        )

    @staticmethod
    def _top_of_book(
        book: dict[str, Any] | None,
    ) -> tuple[float | None, float | None]:
        """Return ``(ask0, bid0)`` from a BookMirror snapshot dict.

        Polymarket order book shape (per ``_compute_l25_vwap_and_depth``):
        ``{"asks": [{"price": "0.42", "size": "100.0"}, ...],
           "bids": [{"price": "0.41", "size": "200.0"}, ...]}``.

        Asks are conventionally sorted ascending (best at index 0); bids
        descending (best at index 0). Returns ``(None, None)`` on missing
        book / empty side / non-numeric prices.
        """
        if not book:
            return None, None
        asks = book.get("asks") or []
        bids = book.get("bids") or []
        ask0: float | None = None
        bid0: float | None = None
        if asks:
            try:
                ask0 = float(asks[0]["price"])
            except (KeyError, TypeError, ValueError):
                ask0 = None
        if bids:
            try:
                bid0 = float(bids[0]["price"])
            except (KeyError, TypeError, ValueError):
                bid0 = None
        return ask0, bid0

    @staticmethod
    def _compute_l25_vwap_and_depth(
        book: dict[str, Any] | None,
    ) -> tuple[float | None, float]:
        """Sum-weighted VWAP over top 25 asks + total notional (USD)."""
        if not book:
            return None, 0.0
        asks = book.get("asks") or []
        total_notional = 0.0
        total_shares = 0.0
        for lvl in asks[:25]:
            try:
                price = float(lvl["price"])
                size = float(lvl["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if price <= 0 or size <= 0:
                continue
            total_notional += price * size
            total_shares += size
        if total_shares <= 0:
            return None, 0.0
        return total_notional / total_shares, total_notional

    @staticmethod
    def _compute_spread(
        snap: L25BookSnapshot, direction: str,
    ) -> float | None:
        """Spread = same-token best-ask minus best-bid on the side being bought.

        Delegates to ``_sniper_spread.compute_spread`` — the shared utility
        that ALL future sniper controllers (V6/V7/V8/V9...) MUST use to
        keep the live filter in lockstep with backtest
        ``engine_v2.fill_at_book`` (line 234).

        History (2026-05-27 fix): the prior body returned
        ``abs(up_vwap - (1 - dn_vwap))`` (cross-token arb proxy). On thin
        inside books that metric exceeded every sleeve's ``spread_filter``,
        so 1,184 evals → 0 placements. The same-token bid-ask form below
        matches the backtest assumption and produces the expected
        30-50 % placement rate.

        Returns ``None`` if either ask0 or bid0 is missing on the chosen
        side (same semantics as backtest where they'd be NaN — fire
        proceeds; downstream depth gates handle missing books).
        """
        from backend.app.controllers._sniper_spread import compute_spread
        return compute_spread(snap, direction)

    def _book_dense_enough(self, token_id: str, fire_us: int) -> bool:
        """Returns True if ≥ N book events landed in last 60s.

        Note: ``fire_us`` is the schedule-time anchor but the actual call
        is wall-clock at-or-slightly-after fire_us. We anchor the 60s
        window against the latest of (fire_us, now()) so live-fire reads
        the most recent 60s of book activity, and offline replay reads
        the 60s window ending at fire_us.
        """
        threshold = int(
            getattr(self._settings, "tv_poly_sniper_v5_fill_min_book_events_60s", 25)
        )
        dq = self._book_event_count.get(token_id)
        if not dq:
            return False
        anchor_us = max(fire_us, int(time.time() * 1_000_000))
        cutoff_us = anchor_us - int(_BOOK_EVENT_WINDOW_S * 1_000_000)
        count = sum(1 for ts in dq if ts >= cutoff_us)
        return count >= threshold

    @staticmethod
    def _gate_book_source(
        snap: L25BookSnapshot | None, direction: str,
    ) -> str:
        """TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — gate-time book tier.

        The spread + depth gates evaluate against the per-side
        ``L25BookSnapshot`` built at gate time. Return the tier that answered
        the side actually being bought (UP → ``up_book_source``, DOWN →
        ``dn_book_source``); ``"empty"`` when the snapshot is missing.
        """
        if snap is None:
            return "empty"
        src = snap.up_book_source if direction == "UP" else snap.dn_book_source
        return str(src or "empty")

    def _record_book_source_consistency(
        self,
        *,
        sleeve_id: str,
        slug: str,
        direction: str,
        gate_source: str,
        fill_source: str,
    ) -> bool:
        """TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — observe gate/fill drift.

        Gate decisions and the fill price come from two SEPARATELY-fetched
        books (the gate-time ``L25BookSnapshot`` vs the fill-time L25 walk),
        taken a few awaits apart. They agree while the WS mirror is hot +
        populated, but if the mirror is None / a token is empty the fill can
        fall through to a different tier than the gate trusted — the gate and
        the fill then price off different books/instants. This does NOT change
        the fill (conservative observability fix per the audit): it only LOGS a
        ``book_source_mismatch`` warning + returns a bool the caller stamps on
        the FireResult / audit row so the latent risk is visible. The deeper
        single-snapshot unification stays DEFERRED.

        Empty / unknown sides are not flagged: a skipped (no-fill) fire never
        reaches here, and an ``"empty"`` placeholder is not a tier disagreement
        worth paging on. Mismatch == both sides resolved to a concrete, but
        DIFFERENT, tier.
        """
        gs = str(gate_source or "empty")
        fs = str(fill_source or "empty")
        mismatch = gs != fs and gs != "empty" and fs != "empty"
        if mismatch:
            logger.warning(
                "poly_sniper_v5.book_source_mismatch",
                sleeve_id=sleeve_id,
                slug=slug,
                direction=direction,
                gate_book_source=gs,
                fill_book_source=fs,
            )
        return mismatch

    async def _simulate_l25_walk(
        self, token_id: str, notional_usd: float,
    ) -> tuple[float, float, float, str] | None:
        """Simulate a buy-side L25 walk via the canonical 3-tier book primitive.

        Returns ``(vwap, shares, latency_ms, book_source)`` on success, or
        ``None`` when NO tier produced a tradeable book (caller MUST skip
        the fire with ``skip_reason='empty_book_all_tiers_failed'``).

        TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 supersedes the prior
        synthetic-fill behavior. Previously this method returned a
        ``(0.5, notional/0.5, 0.0, "synthetic")`` placeholder when the
        WS mirror was empty — that "fill" cannot be reproduced in live
        trading (you can't buy on an empty book) and polluted shadow
        stats with fictional wins.

        ``book_source`` is one of:
          * ``"ws_mirror"`` — Tier-1 WS BookMirror answered (~10ms latency)
          * ``"clob"``      — Tier-2 CLOB REST fallback (~50ms)
          * ``"storedata"`` — Tier-3 Storedata DB fallback (paged alert)
        """
        book = await self._fetch_book_via_snapshot_fn(token_id)
        book_source = str(book.get("_source") or "empty")
        if book_source == "empty" or book.get("_stale"):
            return None
        asks = book.get("asks") or []
        if not asks:
            return None
        spent_usd = 0.0
        spent_shares = 0.0
        for lvl in asks[:25]:
            try:
                price = float(lvl["price"])
                size = float(lvl["size"])
            except (KeyError, TypeError, ValueError):
                continue
            if price <= 0 or size <= 0:
                continue
            lvl_notional = price * size
            remaining = notional_usd - spent_usd
            if lvl_notional >= remaining:
                shares_here = remaining / price
                spent_usd += shares_here * price
                spent_shares += shares_here
                break
            else:
                spent_usd += lvl_notional
                spent_shares += size
        if spent_shares <= 0:
            return None
        vwap = spent_usd / spent_shares
        return vwap, spent_shares, 0.0, book_source

    async def _place_live_order(
        self,
        token_id: str,
        notional_usd: float,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
    ) -> tuple[float, float, str] | str | None:
        """Place a REAL marketable-taker buy on ``token_id`` for the
        allowlisted live sleeve. Returns ``(fill_vwap, fill_shares, "live")``
        on a real fill; ``None`` (fail-closed) on empty book / reject / any
        exception (caller → skip ``live_exec_failed``, NO synthetic fallback);
        or a ``str`` skip_reason when the V10 entry-band gate blocks the fire
        (caller → skip that reason, NOT an exec failure).

        Sizing: walk the live L25 book for ``notional_usd`` to derive the
        share count, then submit a ``limit_px=0.99`` buy (venue caps to best
        ask — same taker entry as the shadow L25 walk + Kalshi live). PnL is
        computed from the REAL fill at resolution; the position is held to
        on-chain resolution and redeemed by ``poly_redeemer``.
        """
        # 1. Derive share count from the real book (also our empty-book guard).
        # TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — reset + capture the inner
        # sizing-walk tier so the caller can compare gate-time vs fill-time book
        # source on the live path (the public return still reports "live").
        self._last_live_walk_source = None
        walk = await self._simulate_l25_walk(token_id, notional_usd)
        if walk is None:
            return None
        est_vwap, est_shares, _, _live_walk_src = walk
        self._last_live_walk_source = _live_walk_src
        if est_shares <= 0:
            return None
        # V10 entry-band gate — skip the fire (BEFORE placing any real order)
        # when the bet-side entry vwap is outside the band. Returns a skip
        # reason string (distinct from the None exec-failure path).
        band = sleeve.entry_band
        if band is not None and not (band[0] <= est_vwap < band[1]):
            return f"entry_vwap_out_of_band_{est_vwap:.4f}"
        live_sleeve_id = f"{sleeve.sleeve_id}_LIVE"
        # 2026-06-05 — ensure the authenticated user-fill WS (UserFillMirror) is
        # watching THIS market before we fire, so the Tier-1 reconcile can confirm
        # a fill in sub-second if the CLOB POST read-times-out. Best-effort: any
        # failure is swallowed (the reconcile's REST tier is the safety net).
        try:
            _ufm = getattr(self._live_executor, "_user_fill_mirror", None)
            _cid = getattr(slot, "condition_id", None)
            if _ufm is not None and _cid:
                await _ufm.subscribe(str(_cid))
        except Exception:  # noqa: BLE001
            pass
        try:
            result = await self._live_executor.place_entry_order(
                token_id=int(token_id),
                qty=Decimal(str(est_shares)),
                limit_px=_SNIPER_V5_LIVE_LIMIT_PX,
                sleeve_id=live_sleeve_id,
                side="buy",
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed on any exec error
            logger.exception(
                "poly_sniper_v5.live_order_failed",
                sleeve_id=live_sleeve_id, slug=slot.slug, token_id=token_id,
            )
            await self._emit_live_alert(
                live_sleeve_id, slot.slug, reason=f"exception: {exc!r}"[:160],
            )
            return None
        status_str = str(getattr(result, "status", "")).split(".")[-1].lower()
        # TV_FIX_LIVE_FILL_ACCOUNTING_2026_06_02 (Bug A) — book a position ONLY
        # off a venue-CONFIRMED fill, never off the bare order ACK.
        #
        # 1. Accept ONLY filled / partial. A Polymarket CLOB post_order can ack
        #    success:true with status ∈ {live, delayed, unmatched} → these map to
        #    FillStatus.PENDING and carry NO fill detail. `live` = resting on the
        #    book (ZERO filled); `delayed` = in the 1s match window (not yet
        #    matched). Booking either records a phantom position. PENDING is now
        #    fail-closed (skip + alert), NOT an accepted fill.
        if not any(s in status_str for s in ("filled", "partial")):
            logger.warning(
                "poly_sniper_v5.live_order_not_filled",
                sleeve_id=live_sleeve_id, slug=slot.slug, status=status_str,
                reason=str(getattr(result, "reason", "") or ""),
            )
            await self._emit_live_alert(
                live_sleeve_id, slot.slug,
                reason=f"not_filled: {status_str}",
            )
            return None
        # 2. Require a REAL venue fill amount. Do NOT fall back to the L25-walk
        #    estimate (`est_vwap`/`est_shares` are valid ONLY as the sizing input
        #    that derived `qty` above — never as the booked fill). When the ack
        #    omits avg_price/filled_shares we cannot prove the order filled →
        #    fail-closed (skip + alert), book NOTHING (no synthetic/estimate).
        raw = getattr(result, "raw_response", None) or {}
        try:
            _fs = raw.get("filled_shares") or raw.get("filled")
            real_shares = float(_fs) if _fs else 0.0
        except (TypeError, ValueError):
            real_shares = 0.0
        try:
            real_vwap = float(raw.get("avg_price")) if raw.get("avg_price") else None
        except (TypeError, ValueError):
            real_vwap = None
        if real_shares <= 0 or real_vwap is None:
            logger.warning(
                "poly_sniper_v5.live_ack_without_fill",
                sleeve_id=live_sleeve_id, slug=slot.slug, status=status_str,
                filled_shares=real_shares, avg_price=real_vwap,
            )
            await self._emit_live_alert(
                live_sleeve_id, slot.slug, reason="ack_without_fill",
            )
            return None
        logger.info(
            "poly_sniper_v5.live_fill",
            sleeve_id=live_sleeve_id, slug=slot.slug,
            fill_vwap=real_vwap, fill_shares=real_shares,
            order_id=str(getattr(result, "order_id", "") or ""),
            notional_usd=notional_usd,
        )
        return real_vwap, real_shares, "live"

    async def _emit_live_alert(
        self, sleeve_id: str, slug: str, *, reason: str,
    ) -> None:
        """Fire-and-forget CRITICAL alert on a live-execution failure."""
        if self._alert_service is None:
            return
        try:
            await self._alert_service.emit(
                severity="CRITICAL",
                kind="poly_sniper_v5_live_exec_failed",
                sleeve_id=sleeve_id, slug=slug, reason=reason,
            )
        except Exception:  # noqa: BLE001 — alert failure never blocks flow
            logger.exception("poly_sniper_v5.live_alert_emit_failed")

    def _build_gate_kwargs(
        self, gate_ref: GateRef, sleeve: SniperV5Sleeve, slot: SlotInfo,
        *, oracle_lag: Any = None, oracle_lag_other: Any = None,
    ) -> dict[str, Any]:
        """Route runtime kwargs to a gate based on the gate's name family.

        Routing is name-keyed so the controller stays decoupled from gate
        internals — adding a new gate family is one tuple-membership check
        away.

        ``oracle_lag`` is the precomputed fast_taker OracleLagSnapshot (or None)
        for the current fire — passed straight to g_oracle_lag_bps_ge.
        """
        name = gate_ref.name
        # fast_taker oracle-lag gate — the snapshot is computed once per fire in
        # eval_sleeve_fire and threaded through (avoids a per-direction recompute
        # + keeps the gate pure).
        if name.startswith("g_oracle_lag_bps_ge"):
            return {"oracle_lag": oracle_lag}
        # FAST_TAKER_LAGV2 gate family (2026-05-29).
        if name.startswith("g_oracle_lag_with"):
            return {"oracle_lag": oracle_lag}
        if name.startswith("g_cross_asset_lag_confluence"):
            return {"oracle_lag_other": oracle_lag_other}
        if name.startswith("g_not_us_close_hours"):
            return {}
        if name.startswith("g_top_depth_ge_median"):
            return {
                "book_mirror": self._book_mirror,
                "token_id_up": slot.token_id_up,
                "token_id_dn": slot.token_id_dn,
                "asset": sleeve.asset,
                "tf": sleeve.tf,
                "depth_median_usd": DEPTH_MEDIAN_USD,
            }
        # Stack-stack-stack chain — match shortest non-overlapping prefix.
        if name.startswith(("g_trend_slope_with",
                            "g_trend_slope_strong_with",
                            "g_regime_stack_with")):
            return {"regime_panel": self._panels.get("regime")}
        if name.startswith((
            "g_mp_skew_with",
            "g_mp_skew_strong_with",
            "g_mp_no_extreme",
            "g_mp_no_extreme_100",
        )):
            return {
                "slug": slot.slug,
                "microprice_panel": self._panels.get("microprice"),
            }
        if name.startswith(("g_rf_aged", "g_rf_fresh",
                            "g_rf_strict_align", "g_rf_with")):
            return {"rf_panel": self._panels.get("range_filter")}
        if name.startswith((
            "g_tr_above_ema50",
            "g_tr_above_ema200",
            "g_tr_above_ema800",
            "g_tr_above_cloud",
            "g_tr_above_pp",
            "g_tr_stack_full_with",
            "g_tr_stack_with",
            "g_tr_partial_stack_with",
            "g_tr_within_adr",
            "g_tr_in_active_session",
            "g_ribbon_agrees",
            "g_ribbon_slope_with",
            "g_near_pivot",
            "g_tight_ribbon",
        )):
            return {"tr_panel": self._panels.get("traders_reality")}
        if name.startswith(("g_sms_liq_reclaim_with",
                            "g_sms_no_liquidity_above")):
            return {"sms_panel": self._panels.get("sms")}
        if name.startswith("g_vol_high"):
            return {"vol_hurst_panel": self._panels.get("vol_hurst")}
        if name.startswith(("g_above_1h_dailyvwap_with",
                            "above_1h_dailyvwap")):
            return {"daily_vwap_panel": self._panels.get("daily_vwap")}
        if name.startswith(("g_book_depth_supports_250",
                            "g_depth_250_strict")):
            return {
                "slug": slot.slug,
                "book_mirror": self._book_mirror,
                "token_id_up": slot.token_id_up,
                "token_id_dn": slot.token_id_dn,
            }
        if name.startswith("g_offset_early"):
            return {"slot_start_us": slot.slot_start_us}

        # -------------------------------------------------------------
        # V6 / V7 / V8 extension routes (2026-05-27)
        # -------------------------------------------------------------

        # TA indicators (CCI / MFI / BB / Stoch) — read ta_indicators_1s
        if name.startswith((
            "g_cci_strong_with", "g_cci_extreme_with", "g_cci_with",
            "g_mfi_with", "g_mfi_strong_with",
            "g_bb_pos_with",
            "g_stoch_with",
        )):
            return {"ta_indicators": self._panels.get("ta_indicators")}

        # Hawkes
        if name.startswith("g_hawkes_imb_loose_with"):
            return {"hawkes_panel": self._panels.get("hawkes")}

        # Hurst regime (vol_hurst + microprice) — most specific first
        if name.startswith("g_hurst_mp_trend_with"):
            return {
                "slug": slot.slug,
                "vol_hurst_panel": self._panels.get("vol_hurst"),
                "microprice_panel": self._panels.get("microprice"),
            }
        # Hurst with regime overlay
        if name.startswith(("g_hurst_regime_with", "g_hurst_trend_with")):
            return {
                "vol_hurst_panel": self._panels.get("vol_hurst"),
                "regime_panel": self._panels.get("regime"),
            }
        # Plain Hurst (trending / reverting)
        if name.startswith(("g_hurst_trending", "g_hurst_reverting")):
            return {"vol_hurst_panel": self._panels.get("vol_hurst")}

        # F7 v7 RSI (asset-bound variants + cross-asset BTC)
        if name.startswith((
            "g_f7_v7_overbought", "g_f7_v7_oversold", "g_f7_v7_with",
            "g_btc_f7_with", "g_btc_f7_against",
            "g_f7_rsi_with",
        )):
            return {"f7_v7_panel": self._panels.get("f7_v7")}

        # TOD UTC hour buckets (no panel — fire_us only)
        if name.startswith((
            "g_tod_asia_morning", "g_tod_european_morning",
            "g_tod_us_open", "g_tod_us_afternoon",
            "g_tod_us_evening", "g_tod_europe_us_window",
            "g_hod_european_morning",
        )):
            return {}

        # Offset window 60..240
        if name.startswith("g_off_60_240"):
            return {"slot_start_us": slot.slot_start_us}

        # Pre-window trend slope (ws_s anchor)
        if name.startswith("g_pw_trend_slope_with"):
            return {
                "slot_start_us": slot.slot_start_us,
                "window_s": 300 if sleeve.tf == "5m" else 900,
                "regime_panel": self._panels.get("regime"),
            }

        # Entry-VWAP band filters (book_walk_vwap at fire_us)
        if name.startswith((
            "g_entry_vwap_in_band", "g_entry_vwap_in_30_70",
            "g_vwap_in_45_85", "g_vwap_in_55_80",
            "g_vwap_premium",
        )):
            return {
                "slug": slot.slug,
                "book_mirror": self._book_mirror,
                "token_id_up": slot.token_id_up,
                "token_id_dn": slot.token_id_dn,
            }

        # Microprice variant (150bps ceiling)
        if name.startswith("g_mp_no_extreme_150"):
            return {
                "slug": slot.slug,
                "microprice_panel": self._panels.get("microprice"),
            }

        # Parent-15m regime / Path Q (regime_panel only)
        if name.startswith((
            "g_parent_15m_regime_with",
            "g_parent_15m_slope_with",
            "g_parent_15m_not_ranging",
            "g_parent15m_ranging",
            "g_q_prev15m_agrees",
        )):
            return {"regime_panel": self._panels.get("regime")}

        # regime_ranging_at_ws (regime_panel + ws_s anchor)
        if name.startswith("g_regime_ranging_at_ws"):
            return {
                "slot_start_us": slot.slot_start_us,
                "window_s": 300 if sleeve.tf == "5m" else 900,
                "regime_panel": self._panels.get("regime"),
            }

        # Pre-window cross-asset (BTC/SOL 15m at ws_s)
        if name.startswith((
            "g_pw_btc_15m_trend_with", "g_pw_sol_15m_trend_with",
        )):
            return {
                "slot_start_us": slot.slot_start_us,
                "window_s": 300 if sleeve.tf == "5m" else 900,
                "regime_panel": self._panels.get("regime"),
            }

        # 1h grandparent (regime_panel)
        if name.startswith((
            "g_grandparent_trend_with",
            "g_grandparent_1h_slope_strong_with",
        )):
            return {"regime_panel": self._panels.get("regime")}

        # 1h Range Filter
        if name.startswith("g_1h_rf_with"):
            return {"range_filter_1h": self._panels.get("range_filter_1h")}

        # Confluence — 3-asset combined (regime + range_filter both needed)
        if name.startswith("g_3asset_combined_unanimity"):
            return {
                "regime_panel": self._panels.get("regime"),
                "range_filter_panel": self._panels.get("range_filter"),
            }

        # 3-source RF unanimity (range_filter_panel only)
        if name.startswith("g_xa_3source_trend_with"):
            return {"range_filter_panel": self._panels.get("range_filter")}

        # Confluence — 2-asset / pairwise (regime_panel only)
        if name.startswith((
            "g_2asset_btc_eth_with", "g_2asset_either_trending_with",
            "g_btc_sol_confluence_5m_with", "g_2a_btc_sol_trend_with",
            "g_btc_eth_confluence_5m_with",
            "g_xa_unanimity_5m_with",
            "g_btc_eth_divergence",
            "g_J_btc_eth_vol_both_low",
        )):
            return {"regime_panel": self._panels.get("regime")}

        # Cross-asset feature gates (regime_panel only)
        if name.startswith((
            "g_btc_trend_30m_with", "g_sol_trend_slope_with",
            "g_BTC_slope_with", "g_BTC_slope_strong_with",
            "g_BTC_adx_strong", "g_ETH_adx_strong",
            "g_BTC_vol_low", "g_ETH_vol_low",
            "g_L_ETH_grandparent_adx_strong",
        )):
            return {"regime_panel": self._panels.get("regime")}

        # BTC tr_stack (traders_reality)
        if name.startswith("g_BTC_tr_stack"):
            return {"tr_panel": self._panels.get("traders_reality")}

        # DI agrees (regime_panel)
        if name.startswith("g_di_agrees"):
            return {"regime_panel": self._panels.get("regime")}

        # Liquidity shock + Imb5 (book_mirror + slug + tokens)
        if name.startswith((
            "g_liq_shock_against", "g_imb5_strong_with",
        )):
            return {
                "slug": slot.slug,
                "book_mirror": self._book_mirror,
                "token_id_up": slot.token_id_up,
                "token_id_dn": slot.token_id_dn,
            }

        # Slot-end OFI (slug + slot_end_us)
        if name.startswith("g_slot_end_ofi_with"):
            tf_seconds = 300 if sleeve.tf == "5m" else 900
            return {
                "slug": slot.slug,
                "slot_end_us": slot.slot_start_us + tf_seconds * 1_000_000,
            }

        # Vol contracting (regime_panel + vol_hurst_panel)
        if name.startswith("g_vol_contracting"):
            return {
                "regime_panel": self._panels.get("regime"),
                "vol_hurst_panel": self._panels.get("vol_hurst"),
            }

        # =================================================================
        # V9 gates — Polymarket flow (B1/B2/B3) + HL cascade (A2)
        # SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md §2.5
        # =================================================================
        # B1/B2/B2-NOT/B3 — asset-specific Polymarket trades DataFrame.
        # asset_trades resolves to None when V9DataStore isn't loaded (e.g.
        # pandas/pyarrow missing on this VPS, or canonical parquets not yet
        # written) — gates fall through to defensive False.
        if name.startswith((
            "g_b1_poly_flow_aligned",
            "g_b2_poly_flow_contrarian",
            "g_b2_poly_flow_NOT_opposing",
            "g_b3_poly_flow_abs",
        )):
            asset_key = sleeve.asset.lower()
            asset_trades = (
                self._v9_data_store.get_asset_trades(asset_key)
                if self._v9_data_store is not None
                else None
            )
            return {
                "slug": slot.slug,
                "asset_trades": asset_trades,
            }
        # A2 — pre-filtered HL liquidation short-cascade proxy.
        if name.startswith("g_a2_hl_short_cascade"):
            hl_proxy = (
                self._v9_data_store.get_hl_short_proxy()
                if self._v9_data_store is not None
                else None
            )
            return {
                "hl_short_proxy": hl_proxy,
            }

        # g_dir_up / g_dir_down / g_hod_us_afternoon / g_pass / unknown:
        # no extra kwargs.
        return {}

    def _build_event(
        self,
        sleeve: SniperV5Sleeve,
        slot: SlotInfo,
        fire_us: int,
        offset_s: int,
        fr: FireResult,
        *,
        event_type: str | None = None,
        outcome: str | None = None,
        pnl_usd: float | None = None,
        ft_extra: dict[str, Any] | None = None,
        live: bool = False,
    ) -> dict[str, Any]:
        """Build a §7-schema event dict for the AsyncJsonlShadowLogger.

        For poly_fast_taker_* sleeves a ``fast_taker`` block is appended
        (spec §6): oracle_lag_bps, side, offset, vwap/shares/notional, merge
        pairs/collateral, fee model; resolution rows also carry ``ft_extra``
        (residual_up/down, cash_spent/recovered, win_fee, n_fires). ask0/bid0/
        spread live in the existing ``l25_book_snapshot`` block.
        """
        if event_type is None:
            event_type = (
                "sleeve_fire_placed"
                if fr.all_gates_passed and fr.fill_vwap is not None
                else "sleeve_fire_eval"
            )
        # Spec §7 schema — every event MUST include all of these fields.
        # `intended_size_usd` is the notional WE intended to place (per-sleeve
        # override or settings default), independent of whether placement
        # actually happened. `resolution_source` is always "chainlink".
        intended_size_usd = float(
            sleeve.notional_usd_override
            if sleeve.notional_usd_override is not None
            else self._settings.tv_poly_sniper_v5_notional_usd
        )
        # Live fires (real Polymarket orders) get the ``_LIVE`` sleeve_id
        # suffix + ``mode='live'`` so they (a) are distinguishable from the
        # paper roster and (b) are picked up by the Ireland live-only
        # portfolio/header filter (``data->>'mode' = 'live'``). Paper fires
        # omit ``mode`` entirely — byte-identical to the existing shape.
        event_sleeve_id = f"{sleeve.sleeve_id}_LIVE" if live else sleeve.sleeve_id
        event: dict[str, Any] = {
            "event_type": event_type,
            "sleeve_id": event_sleeve_id,
            "asset": sleeve.asset,
            "tf": sleeve.tf,
            "direction": fr.direction,
            "slug": slot.slug,
            "condition_id": slot.condition_id,
            "slot_start_us": slot.slot_start_us,
            "ws_s": slot.ws_s,
            "fire_offset_s": offset_s,
            "fire_us": fire_us,
            "all_gates_passed": fr.all_gates_passed,
            "gates_evaluated": dict(fr.gates_evaluated),
            "skip_reason": fr.skip_reason,
            "intended_size_usd": intended_size_usd,
            "placed_size_usd": fr.placed_size_usd,  # None when not placed
            "fill_vwap": fr.fill_vwap,              # None when not placed
            "fill_shares": fr.fill_shares,          # None when not placed
            "fill_latency_ms": fr.fill_latency_ms,  # None when not placed
            "fill_method": fr.fill_method,          # "l25_walk" | "synthetic" | None
            # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — tier that answered
            # the fill walk (or "empty" when all tiers failed and the fire
            # was skipped). Aligns sniper-v5 JSONL with momo's
            # ``paper.book_fetched`` telemetry shape.
            "book_source": fr.book_source,
            # TV_FIX_BOOKMIRROR_2026_06_02 (bookfill-3) — True when the
            # gate-time book tier and the fill-time book tier differed
            # (latent risk: gate decision + fill price off different
            # books/instants); False when they matched; None on eval-only
            # / skipped fires. Co-emitted with the ``book_source_mismatch``
            # warning so post-mortems can quantify the drift.
            "book_source_mismatch": fr.book_source_mismatch,
            # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — populated on
            # ``sleeve_fire_resolved`` rows; None otherwise. Dashboard
            # consumes directly instead of deriving from outcome/direction.
            "won": fr.won,
            "outcome": outcome,                      # None until resolved
            "pnl_usd": pnl_usd,                      # None until resolved
            "resolution_source": "chainlink",        # spec §7 — always
            # HEDGE_LATE A/B (SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE_2026_05_27):
            # exit_type ∈ {None (pre-resolve), "hold_to_resolve", "hedge_late_cut"};
            # hedge_sell_vwap populated only on a hedge_late_cut row.
            "exit_type": fr.exit_type,
            "hedge_sell_vwap": fr.hedge_sell_vwap,
        }
        if live:
            event["mode"] = "live"
        # Dashboard open-position wiring: a placed fire emits the SAME
        # ``order_placed`` shape the momo/Kalshi live path writes
        # (reason / fill_status / fill_price / fill_qty / signal) so the
        # batch-stats ``last_fill`` query picks it up and the card shows the
        # held position between fire and resolution. Without these keys the
        # query (``reason='order_placed' AND fill_status='filled'``) drops the
        # sniper-v5 rows → position_open never lights up. Applies to BOTH
        # paper (→ stats.position_open) and live (→ live_breakdown via mode).
        if event_type == "sleeve_fire_placed" and fr.fill_vwap is not None:
            event["reason"] = "order_placed"
            event["fill_status"] = "filled"
            event["fill_price"] = fr.fill_vwap
            event["fill_qty"] = fr.fill_shares
            event["signal"] = fr.direction
            # 2026-06-06 — durable entry_strike for the card (HOLD fix). 1m binance
            # close at window-start; box-independent (1m deque always on, vs the 1s
            # vwap_store which needs TV_POLY_VWAP_CONT_ENABLED). slot.ws_s is the
            # authoritative window start (seconds). Never raises into the fire path.
            try:
                from backend.app.data.bars import get_feed_instance as _gfi
                _feed = _gfi()
                _strk = (
                    _feed.get_close_asof(sleeve.asset, int(slot.ws_s))
                    if (_feed is not None and slot.ws_s is not None)
                    else None
                )
                event["entry_strike"] = float(_strk) if _strk is not None else None
            except Exception:  # noqa: BLE001 — audit must never break a fire
                event["entry_strike"] = None
        if fr.l25_book_snapshot is not None:
            snap = fr.l25_book_snapshot
            # V5+V6+V7+V8 fix (2026-05-27): include top-of-book + the
            # prior cross-token-arb metric as ``cross_spread_old`` so any
            # backfill / post-mortem can compare "what would the old
            # filter have done" against the new bid-ask filter.
            cross_old: float | None
            if snap.up_vwap is not None and snap.dn_vwap is not None:
                cross_old = abs(snap.up_vwap - (1.0 - snap.dn_vwap))
            else:
                cross_old = None
            event["l25_book_snapshot"] = {
                "up_vwap": snap.up_vwap,
                "dn_vwap": snap.dn_vwap,
                "up_depth_usd": snap.up_depth_usd,
                "dn_depth_usd": snap.dn_depth_usd,
                "up_ask0": snap.up_ask0,
                "up_bid0": snap.up_bid0,
                "dn_ask0": snap.dn_ask0,
                "dn_bid0": snap.dn_bid0,
                "cross_spread_old": cross_old,
                # TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27 — per-side tier
                # that answered. "empty" when all 3 tiers failed for
                # that side.
                "up_book_source": snap.up_book_source,
                "dn_book_source": snap.dn_book_source,
            }
        else:
            event["l25_book_snapshot"] = None
        # fast_taker block (spec §6) — only on poly_fast_taker_* rows.
        if _is_fast_taker(sleeve):
            ft_block: dict[str, Any] = {
                # TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01 — oracle_lag_bps now
                # carries the INTRA-WINDOW BINANCE RETURN (px@fire/px@open − 1),
                # the backtested signal, NOT the feed-vs-oracle basis. Same value
                # echoed as ret_bps_binance so the field name is honest; sign ==
                # fired direction on every fire (the #1 acceptance check).
                "oracle_lag_bps": fr.oracle_lag_bps,
                "ret_bps_binance": fr.oracle_lag_bps,
                "side": fr.direction,
                "offset_s": offset_s,
                "vwap": fr.fill_vwap,
                "shares": fr.fill_shares,
                "notional": fr.placed_size_usd,
                "merge_mimic": sleeve.merge_mimic,
                "one_shot_per_slug": sleeve.one_shot_per_slug,
                "merge_pairs": fr.merge_pairs,
                "merge_collateral": fr.merge_collateral,
                "fee_model": "legacy_2pct",
            }
            if ft_extra:
                ft_block.update(ft_extra)
            event["fast_taker"] = ft_block
        # FAST_TAKER_LAGV2 block (2026-05-29) — directional oracle-lag taker.
        # 0.07 winner-only fee + chainlink resolution + binance-reversal stop.
        if _is_fast_taker_lagv2(sleeve):
            event["fast_taker_lagv2"] = {
                # TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01 — the signal value at fill
                # is the INTRA-WINDOW BINANCE RETURN (sign == fired direction,
                # auditable per AC-2). ``binance_lag_bps`` is the honest field
                # name; ``price_delta_bps`` kept for back-compat with the prior
                # row shape. entry_delta_bps is the entry basis the reversal stop
                # measures against; both are the binance return now.
                "binance_lag_bps": fr.oracle_lag_bps,
                "price_delta_bps": fr.oracle_lag_bps,
                "entry_delta_bps": fr.entry_delta_bps,
                "slot_start_us": slot.slot_start_us,
                "reversal_bps_at_exit": fr.reversal_bps_at_exit,
                "side": fr.direction,
                "offset_s": offset_s,
                "vwap": fr.fill_vwap,
                "shares": fr.fill_shares,
                "notional": fr.placed_size_usd,
                "fee_model": "poly_taker_curve_0.07",
            }
        return event

    async def _check_s6_fired(self, slug: str, ws_s: int) -> bool:
        """Sleeve 01 precondition — did the production BTC-5m sniper fire this slot?

        Spec §4 sleeve 01 (BTC_5M_TS_MPSKEW_S6_0_60): fire only when the
        production "S6 spike trigger" — the BTC 5m production sniper sleeve
        ``poly_updown_btc_5m_sniper_hod`` — has actually PLACED an order in
        this slot's 5m window. Matching rules (verified against live VPS3
        ``trading.events`` 2026-05-29):
            - ``sleeve_id`` is a top-level COLUMN, not a ``data`` key.
            - production rows log ``reason`` ∈ {no_signal, gate_hod_skip,
              order_placed, hedge_placed}; only ``order_placed`` is a real fire.
            - production order_placed rows do NOT carry ``slug``/``ws_s`` in
              ``data`` (only ``condition_id``), so the slot window is matched
              on the event timestamp ``at ∈ [ws_s, ws_s + 300)``.
        Returns False when:
            - read_pool is None (test env or pool disabled)
            - any DB error (defensive — never bubble)
            - the production sniper has not placed in this window yet
        """
        if self._read_pool is None:
            return False
        try:
            async with self._read_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT 1
                    FROM trading.events
                    WHERE kind = 'poly_updown_signal'
                      AND sleeve_id = 'poly_updown_btc_5m_sniper_hod'
                      AND data->>'reason' = 'order_placed'
                      AND at >= to_timestamp($1::double precision)
                      AND at <  to_timestamp($1::double precision + 300)
                    LIMIT 1
                    """,
                    ws_s,
                )
                return row is not None
        except Exception:  # noqa: BLE001 — DB outage doesn't bubble
            logger.warning("poly_sniper_v5.s6_check_failed", slug=slug, ws_s=ws_s)
            return False

    async def _lookup_entry_event_id(
        self, sleeve_id: str, condition_id: str | None,
    ) -> str | None:
        """Look up the ENTRY ``poly_updown_signal`` row's ``event_id`` (UUID).

        TV_FIX_DOUBLE_RESOLUTION_2026_06_02 — Option 2b source fix. Stamping
        ``fill_event_id = <entry event_id>`` onto the resolution payload makes
        the generic on-chain resolver's dedup guard
        (``engine/poly_updown_resolver.py`` ``_PENDING_RESOLUTIONS_SQL`` —
        ``NOT EXISTS (... r2.data->>'fill_event_id' = e.event_id::text)``)
        match, so the resolver SKIPS the sniper-v5 ``_LIVE`` fill instead of
        writing a duplicate ``poly_updown_resolution`` row ~60s later. A correct
        value also lets ``api/positions.py`` close the position via its
        ``r.data->>'fill_event_id' = f.event_id::text`` LEFT JOIN.

        Returns the entry row's ``event_id`` as TEXT (the UUID string) so the
        stored value shape matches B's guard predicate + ``positions.py`` join
        exactly. ``sleeve_id`` MUST be the value written to the entry row's
        top-level ``sleeve_id`` COLUMN (i.e. the ``_LIVE``-suffixed id for live
        fires — ``event["sleeve_id"]``), because B joins ``r2.sleeve_id =
        e.sleeve_id`` on that column.

        FAIL-SAFE (non-negotiable): this NEVER raises, NEVER blocks, NEVER
        delays resolution. On no pool / no match / any DB error it logs a
        warning and returns None; the caller then OMITS ``fill_event_id`` and
        writes the resolution normally — worst case is today's behavior (B
        writes a dup, the read-path dedup catches it). Resolution of a real
        live position must ALWAYS proceed.
        """
        if self._read_pool is None:
            return None
        if not condition_id:
            return None
        try:
            async with self._read_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT event_id
                    FROM trading.events
                    WHERE kind = 'poly_updown_signal'
                      AND sleeve_id = $1
                      AND data->>'condition_id' = $2
                      AND data->>'reason' = 'order_placed'
                      AND data->>'fill_status' = 'filled'
                    ORDER BY at DESC
                    LIMIT 1
                    """,
                    sleeve_id, condition_id,
                )
        except Exception as exc:  # noqa: BLE001 — never block resolution
            logger.warning(
                "sniper_v5.fill_event_id_lookup_miss",
                sleeve_id=sleeve_id, condition_id=condition_id,
                reason="db_error", error=str(exc),
            )
            return None
        if row is None or row["event_id"] is None:
            logger.warning(
                "sniper_v5.fill_event_id_lookup_miss",
                sleeve_id=sleeve_id, condition_id=condition_id,
                reason="no_entry_row",
            )
            return None
        return str(row["event_id"])

    async def _stamp_fill_event_id(self, event: dict[str, Any]) -> None:
        """Stamp ``event['fill_event_id']`` from the matching entry row.

        TV_FIX_DOUBLE_RESOLUTION_2026_06_02 — call on every
        ``poly_updown_resolution`` payload BEFORE the write. Looks up the entry
        signal's ``event_id`` keyed on the resolution row's own
        ``sleeve_id``/``condition_id`` (same column values the entry row
        carries). FAIL-SAFE: on a None lookup the key is OMITTED entirely (NOT
        set to None) so the payload byte-shape is unchanged on the miss path and
        the resolver guard simply doesn't match (falls back to today's dedup).
        """
        entry_event_id = await self._lookup_entry_event_id(
            event.get("sleeve_id"), event.get("condition_id"),
        )
        if entry_event_id is not None:
            event["fill_event_id"] = entry_event_id


__all__ = [
    "FireResult",
    "L25BookSnapshot",
    "PolymarketSniperV5Controller",
    "SlotInfo",
]
