"""Phase 30 — Maker-arb sleeve API endpoints.

GET /maker/sleeves               → list of 6 day-1 maker-arb sleeves
GET /maker/sleeves/{id}/state    → single-sleeve state row

Data source: CSV files under ``settings.tv_poly_maker_log_dir`` written by
``AsyncShadowLogger`` (Plan 30-08). The endpoint scans the per-strategy
CSV file for today (UTC date) and aggregates rows by sleeve cell to
produce a current-state snapshot.

NOT a hot-path source: per D-02, the hot path is the CSV-write loop in
``poly_maker_loop`` (Plan 30-10) writing ``trading.events`` is explicitly
avoided. This endpoint is operator-facing only.

Threat model (30-12a-PLAN.md):
  T-30-12 — authorization: every route ``Depends(require_operator_cookie)``.
  T-30-12 — path traversal: ``_parse_sleeve_id`` validates startswith
            ``_ALLOWED_PREFIXES`` + ``isalnum()`` on asset / tf tokens
            so ``..``/``/`` cannot escape ``log_dir``.

CLAUDE.md invariants honored:
  * #10 secrets-never-in-logs: structlog at module top; no kwargs carry
    any privkey / signature / DB DSN material — the CSV contains only
    public market data + local ACC-M-style order IDs.
  * #13 TV-native data: reads only from TV-owned CSV files; no Storedata
    ``public.*`` access; no new external connections.
"""
from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.app.api.auth import require_operator_cookie
from backend.app.core.config import get_settings

log = structlog.get_logger(__name__)

router = APIRouter(tags=["maker"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_ALLOWED_PREFIXES: Final[tuple[str, ...]] = (
    "poly_acc_m_",
    "poly_acc_h_",
    "poly_mas_",
    "poly_acc_pc_",
    "poly_pat_shadow_",
)

#: Valid asset tokens — used by ``_parse_sleeve_id`` as the second-stage
#: gate after the prefix + isalnum() checks.
_ALLOWED_ASSETS: Final[frozenset[str]] = frozenset({"btc", "eth", "sol"})

#: Valid timeframe tokens.
_ALLOWED_TFS: Final[frozenset[str]] = frozenset({"5m", "15m"})


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class MakerSleeveStateRow(BaseModel):
    """One row in the GET /maker/sleeves response."""

    sleeve_id: str
    strategy: Literal["acc_m", "acc_h", "mas", "acc_pc", "pat_shadow"]
    cell: str  # "btc_15m" / "btc_5m" / "eth_5m" / "eth_15m" / "sol_5m" / ...
    state: Literal["IDLE", "POSTING", "PAIRED", "MERGING", "RESOLVED"]
    n_open_orders: int
    paired_inv: float
    sum_bids: float
    sum_asks: float
    n_fills: int
    n_cancels: int
    n_merges: int
    pnl_so_far: float
    last_decision_ts_us: int | None
    csv_path: str


# ---------------------------------------------------------------------------
# Drawer response schemas (Plan 30-12b — D-11 layer 2)
# ---------------------------------------------------------------------------


#: Action types treated as order-timeline events (Plan 30-12b /orders).
_ORDER_EVENT_ACTIONS: Final[frozenset[str]] = frozenset(
    {"POST_BID", "POST_ASK", "CANCEL", "TAKE", "MERGE", "MINT", "REDEEM"}
)

#: Cap the /orders response to the most recent N events.
_MAX_ORDER_EVENTS: Final[int] = 100

#: Cap the /inventory response to the most recent N points.
_MAX_INVENTORY_POINTS: Final[int] = 200


class MakerOrderEvent(BaseModel):
    """One event in the GET /maker/sleeves/{id}/orders response."""

    ts_us: int
    action: Literal[
        "POST_BID", "POST_ASK", "CANCEL", "TAKE", "MERGE", "MINT", "REDEEM"
    ]
    side: Literal["up", "dn"] | None
    price: float | None
    size: float | None
    order_id: str | None
    trigger_reason: str


class MakerInventoryPoint(BaseModel):
    """One sample in the GET /maker/sleeves/{id}/inventory response.

    Inventory snapshots are sourced from CSV rows where both ``inv_up`` and
    ``inv_dn`` columns are populated — that is, rows the AsyncShadowLogger
    enriched with a ``SlugState`` snapshot (Plan 30-08 contract).
    """

    ts_us: int
    inv_up: float
    inv_dn: float


#: MERGE_TRIGGER_PAIRS — per Plan 30-03 (ACC-M) every MERGE disposes of 5
#: paired-position-pairs. Used in edge_per_pair_realized normalization
#: (Plan 30-12c MakerMicrostructureMetrics formula).
_MERGE_TRIGGER_PAIRS: Final[int] = 5

#: Microstructure window — sample-windowed metrics use this rolling window.
#: Default 1 hour; metrics return 0.0 if no rows fall inside it.
_MICROSTRUCTURE_WINDOW_S: Final[int] = 3600


class MakerMicrostructureMetrics(BaseModel):
    """Plan 30-12c MakerMicrostructureTile response.

    Distinct from Phase 28's ``BookHealthSnapshot`` — this tile is fed by
    the CSV summary written by ``AsyncShadowLogger`` (Plan 30-08), not by
    a live BookMirror snapshot. The 4 metrics below capture the arb-maker
    flavour of microstructure (paired-inventory churn + bid fill_rate +
    realized rebate-net-fee per pair + merge cadence) over a rolling 1h
    window.

    Aggregation formula (Plan 30-12c §interfaces):
      * ``paired_inv_churn``        = ``sum(|inv_up[i] - inv_up[i-1]|) / n_inv_rows``
                                       over rows in last ``_MICROSTRUCTURE_WINDOW_S``
                                       that carry ``inv_up``. 0.0 if < 2 inv rows.
      * ``fill_rate``               = ``n_fills / max(1, n_posts)``;
                                       ``n_posts`` counts POST_BID + POST_ASK rows,
                                       ``n_fills`` counts the subset with
                                       ``fill_simulated=1``.
      * ``edge_per_pair_realized``  = ``(rebates_sum - taker_fees_sum)
                                          / max(1, n_merges * _MERGE_TRIGGER_PAIRS)``
                                       — net cashflow per paired-pair-of-trades.
                                       Pre-first-merge falls back to gross
                                       cashflow (denom 1).
      * ``n_merges_per_hr``         = ``n_merges / max(0.01, elapsed_hr)``;
                                       elapsed_hr clipped to 1.0 once the window
                                       has been fully covered, otherwise the rate
                                       is projected forward.
      * ``last_ts_us``              = max ``ts_us`` over rows in window;
                                       ``None`` if no rows at all.
    """

    sleeve_id: str
    paired_inv_churn: float
    fill_rate: float
    edge_per_pair_realized: float
    n_merges_per_hr: float
    last_ts_us: int | None


class MakerArbStats(BaseModel):
    """GET /maker/sleeves/{id}/arb-stats aggregate row.

    Aggregation formula (Plan 30-12b):
      * ``sum_bids``                  = sum(notional) over POST_BID rows
                                         with ``fill_simulated=1``
      * ``sum_asks``                  = sum(notional) over POST_ASK rows
                                         with ``fill_simulated=1``
      * ``rebates_received``          = sum(rebates) over all rows
      * ``taker_fees_paid``           = sum(taker_fees) over all rows
      * ``n_merges``                  = count of MERGE rows
      * ``edge_per_pair_realized``    = (rebates - fees) / max(1, n_merges)
                                         (i.e. realized net edge per merged
                                         pair; max(1,...) avoids div-by-zero
                                         pre-first-merge)
      * ``pnl_so_far``                = sum(cash_received - cash_spent
                                            + rebates - taker_fees)
                                         (matches /state pnl_so_far)
    """

    sum_bids: float
    sum_asks: float
    edge_per_pair_realized: float
    n_merges: int
    rebates_received: float
    taker_fees_paid: float
    pnl_so_far: float


# ---------------------------------------------------------------------------
# Helpers (pure functions — safe to unit-test directly)
# ---------------------------------------------------------------------------


def _parse_sleeve_id(sleeve_id: str) -> tuple[str, str, str]:
    """Decompose a maker-arb sleeve_id → (strategy, asset, tf).

    Canonical forms (mirroring _maker_arb_sleeve_id in sleeve_manifest.py):
      * ``poly_acc_m_btc_15m_shadow`` → ("acc_m", "btc", "15m")
      * ``poly_acc_h_btc_5m_shadow``  → ("acc_h", "btc", "5m")
      * ``poly_mas_eth_5m_shadow``    → ("mas",   "eth", "5m")

    Raises ``ValueError`` on any of:
      * unknown prefix (not in ``_ALLOWED_PREFIXES``)
      * unparseable token layout
      * non-alphanumeric asset or tf token (path-traversal guard)
      * asset ∉ ``_ALLOWED_ASSETS``
      * tf ∉ ``_ALLOWED_TFS``

    T-30-12 mitigation: even if a caller bypasses the prefix-startswith
    check (e.g. ``poly_acc_m_..._15m_shadow`` where ``...`` is the asset
    token), ``isalnum()`` rejects ``..`` because ``"...".isalnum()`` is
    ``False``. Combined with the asset-allowlist, this is defense-in-depth.
    """
    if not sleeve_id.startswith(_ALLOWED_PREFIXES):
        raise ValueError(f"not a maker-arb sleeve: {sleeve_id}")

    parts = sleeve_id.split("_")
    # poly_acc_m_btc_15m_shadow      → parts = ['poly','acc','m','btc','15m','shadow']
    # poly_acc_h_btc_5m_shadow       → parts = ['poly','acc','h','btc','5m','shadow']
    # poly_acc_pc_btc_15m_shadow     → parts = ['poly','acc','pc','btc','15m','shadow']  (Phase 31)
    # poly_mas_eth_5m_shadow         → parts = ['poly','mas','eth','5m','shadow']
    # poly_pat_shadow_btc_5m_shadow  → parts = ['poly','pat','shadow','btc','5m','shadow']  (Phase 31)
    if (
        len(parts) >= 6
        and parts[0] == "poly"
        and parts[1] == "pat"
        and parts[2] == "shadow"
    ):
        # PAT-SHADOW (Phase 31) — two-token strategy code "pat_shadow".
        strategy = "pat_shadow"
        asset = parts[3]
        tf = parts[4]
    elif len(parts) >= 6 and parts[0] == "poly" and parts[1] == "acc":
        # ACC-M / ACC-H / ACC-PC — strategy code = f"acc_{parts[2]}".
        strategy = f"acc_{parts[2]}"
        asset = parts[3]
        tf = parts[4]
    elif len(parts) >= 5 and parts[0] == "poly" and parts[1] == "mas":
        strategy = "mas"
        asset = parts[2]
        tf = parts[3]
    else:
        raise ValueError(f"unparseable sleeve_id: {sleeve_id}")

    # Path-traversal + injection guards.
    if not asset.isalnum():
        raise ValueError(
            f"non-alphanumeric asset token in sleeve_id: {sleeve_id}"
        )
    if not tf.isalnum():
        raise ValueError(
            f"non-alphanumeric tf token in sleeve_id: {sleeve_id}"
        )
    if asset not in _ALLOWED_ASSETS:
        raise ValueError(
            f"unknown asset {asset!r} in sleeve_id: {sleeve_id}"
        )
    if tf not in _ALLOWED_TFS:
        raise ValueError(
            f"unknown tf {tf!r} in sleeve_id: {sleeve_id}"
        )
    return strategy, asset, tf


def _strategy_to_csv_code(strategy: str) -> str:
    """Map a strategy literal → the lowercased filename code used by
    AsyncShadowLogger.

    Plan 30-11 instantiates loggers with codes ``ACC-M`` / ``ACC-H`` / ``MAS``
    (see sleeve_manifest extension docs). Phase 31 added ``ACC-PC`` and
    ``PAT-SHADOW``. shadow_log writes ``{code.lower()}_{date}.csv`` so files
    land as:
      * acc-m_2026-05-19.csv
      * acc-h_2026-05-19.csv
      * mas_2026-05-19.csv
      * acc-pc_2026-05-19.csv       (Phase 31)
      * pat-shadow_2026-05-19.csv   (Phase 31)
    """
    if strategy == "acc_m":
        return "acc-m"
    if strategy == "acc_h":
        return "acc-h"
    if strategy == "mas":
        return "mas"
    if strategy == "acc_pc":
        return "acc-pc"
    if strategy == "pat_shadow":
        return "pat-shadow"
    raise ValueError(f"unknown strategy: {strategy}")


def _safe_float(s: str) -> float:
    """Parse a CSV cell as float; empty → 0.0; non-numeric → 0.0."""
    if not s:
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _safe_int_ts(s: str) -> int | None:
    """Parse a ts_us cell as int; empty / bad → None."""
    if not s:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _idle_row(
    sleeve_id: str,
    strategy: str,
    cell: str,
    csv_path: Path,
) -> MakerSleeveStateRow:
    """Default IDLE row when no CSV data exists for this sleeve yet."""
    return MakerSleeveStateRow(
        sleeve_id=sleeve_id,
        strategy=strategy,  # type: ignore[arg-type]
        cell=cell,
        state="IDLE",
        n_open_orders=0,
        paired_inv=0.0,
        sum_bids=0.0,
        sum_asks=0.0,
        n_fills=0,
        n_cancels=0,
        n_merges=0,
        pnl_so_far=0.0,
        last_decision_ts_us=None,
        csv_path=str(csv_path),
    )


def _compute_state_row(
    sleeve_id: str,
    log_dir: Path,
) -> MakerSleeveStateRow:
    """Build a MakerSleeveStateRow by scanning ``log_dir`` for today's CSV.

    Aggregation rules (per Plan 30-12a §interfaces — corrected 2026-05-20):
      * ``n_open_orders``  = count(POST_BID|POST_ASK with fill_simulated=0)
                              − count(CANCEL)
      * ``n_fills``        = count(rows with fill_simulated=1)
      * ``n_cancels``      = count(CANCEL)
      * ``n_merges``       = count(MERGE)
      * ``pnl_so_far``     = sum over slugs of latest(cash_received - cash_spent
                              + rebates - taker_fees). Slug cash columns are
                              CUMULATIVE per-slug snapshots from SlugState
                              (shadow_log.py:286-292), NOT per-row deltas —
                              naive sum would inflate by N rows per slug.
      * ``paired_inv``     = min(inv_up, inv_dn) from the last row carrying
                              both columns (each row's slug_state snapshot)
      * ``state``          = derived from the LAST action:
                              POST_BID/POST_ASK → POSTING
                              CANCEL            → POSTING
                              MERGE             → MERGING
                              REDEEM            → RESOLVED
                              MINT              → POSTING (MAS active)
                              TAKE              → POSTING
                              (none)            → IDLE
                              (with PAIRED override when min(inv) ≥ 5)
      * ``last_decision_ts_us`` = max(ts_us) over the filtered rows.

    CSV file may be missing (engine just booted) — returns IDLE row in
    that case, NOT raising.
    """
    strategy, asset, tf = _parse_sleeve_id(sleeve_id)
    cell = f"{asset}_{tf}"
    csv_code = _strategy_to_csv_code(strategy)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    csv_path = log_dir / f"{csv_code}_{date_str}.csv"

    if not csv_path.exists():
        return _idle_row(sleeve_id, strategy, cell, csv_path)

    try:
        with csv_path.open("r", newline="") as fh:
            reader = csv.DictReader(fh)
            rows_for_cell = [
                r
                for r in reader
                if (r.get("asset") or "").lower() == asset
                and (r.get("tf") or "") == tf
            ]
    except OSError as exc:
        log.warning(
            "maker_sleeves.csv_read_failed",
            path=str(csv_path),
            error=str(exc),
        )
        return _idle_row(sleeve_id, strategy, cell, csv_path)

    if not rows_for_cell:
        return _idle_row(sleeve_id, strategy, cell, csv_path)

    n_post = 0
    n_cancels = 0
    n_merges = 0
    n_fills = 0
    inv_up = 0.0
    inv_dn = 0.0
    last_ts_us: int | None = None
    last_action = ""
    last_inv_row_ts: int = -1

    # Group latest cash-snapshot row per slug. cash_spent / cash_received /
    # rebates / taker_fees are CUMULATIVE per-slug snapshots (see
    # shadow_log.py:286-292). Summing every row inflates by N — the day's
    # PnL is the sum across slugs of each slug's FINAL snapshot.
    latest_cash_row_per_slug: dict[str, tuple[int, dict[str, str]]] = {}

    # Bug 9: track which slugs have been REDEEMed. Post-REDEEM, the winner
    # side's inv is decremented to 0 (cash_received credited) but the loser
    # side's residual is left untouched in slug_state. The pre-fix MTM blindly
    # marked that residual at $0.50/share — phantom unrealized "profit" on
    # provably worthless shares. MAS RESOLVED slugs with winner=UP showed
    # ~$15/slug phantom; ×32 RESOLVED slugs = $485 false profit operator
    # flagged. Same over-mark inflates the loser-residual on ACC-M/H/PC slugs.
    redeem_fired_per_slug: set[str] = set()

    for r in rows_for_cell:
        action = r.get("action", "")
        if action in ("POST_BID", "POST_ASK"):
            n_post += 1
        elif action == "CANCEL":
            n_cancels += 1
        elif action == "MERGE":
            n_merges += 1
        elif action == "REDEEM":
            slug_for_redeem = r.get("slug") or ""
            if slug_for_redeem:
                redeem_fired_per_slug.add(slug_for_redeem)
        if (r.get("fill_simulated") or "0") == "1":
            n_fills += 1

        # Track latest ts + state context
        ts_us = _safe_int_ts(r.get("ts_us") or "")
        if ts_us is not None and (last_ts_us is None or ts_us > last_ts_us):
            last_ts_us = ts_us
            last_action = action

        # Track the latest inv_up / inv_dn from any row that carries them.
        # SlugState columns may be empty for early rows; only update when
        # both are present.
        row_inv_up_str = r.get("inv_up") or ""
        row_inv_dn_str = r.get("inv_dn") or ""
        if row_inv_up_str and row_inv_dn_str:
            row_ts = ts_us if ts_us is not None else 0
            if row_ts >= last_inv_row_ts:
                inv_up = _safe_float(row_inv_up_str)
                inv_dn = _safe_float(row_inv_dn_str)
                last_inv_row_ts = row_ts

        # Latest cash snapshot per slug: only consider rows that carry
        # cumulative state columns (skip rows where SlugState was None).
        slug = r.get("slug") or ""
        if slug and (r.get("cash_spent") or r.get("cash_received")):
            row_ts = ts_us if ts_us is not None else 0
            existing = latest_cash_row_per_slug.get(slug)
            if existing is None or row_ts >= existing[0]:
                latest_cash_row_per_slug[slug] = (row_ts, r)

    # PnL = realized cashflows + MARK-TO-MARKET on unredeemed inventory.
    #
    # Pre-fix: only counted realized cash (cash_received - cash_spent + rebates
    # - taker_fees). This showed MAS at -$30 right after a mint even though
    # the freshly-minted 30 UP + 30 DN shares are GUARANTEED $30 on redemption
    # (one of the two sides resolves to $1). Operator's complaint: "we entered
    # with 30 usd and had all the 30 loss" — that's the dashboard hiding the
    # inventory value, not a real loss.
    #
    # Binary outcome math (CTF protocol):
    #   - paired N shares (min(inv_up, inv_dn) = N): GUARANTEED N * $1 at
    #     resolution — whichever side wins pays $1/share, the loser worth $0,
    #     so each pair = exactly $1.
    #   - unpaired residual delta = |inv_up - inv_dn|: 50/50 expectation, mark
    #     conservatively at $0.50/share (could be $1 or $0).
    #
    # This formula gives meaningful unrealized PnL immediately after mint or
    # accumulation. Once REDEEM fires the inventory clears + cash_received
    # absorbs the value, so the formula stays correct through resolution.
    pnl_so_far = 0.0
    for slug_id, (_slug_ts, slug_row) in latest_cash_row_per_slug.items():
        slug_inv_up = _safe_float(slug_row.get("inv_up") or "")
        slug_inv_dn = _safe_float(slug_row.get("inv_dn") or "")
        paired = min(slug_inv_up, slug_inv_dn)
        residual = abs(slug_inv_up - slug_inv_dn)
        # Bug 9: post-REDEEM residual is the LOSER side (winner already
        # decremented by _observe_redeem). Loser shares are provably $0 — do
        # NOT mark at $0.50. Paired stays $1 in case a slug somehow holds
        # paired inv post-redeem (shouldn't happen — winner inv would be 0 —
        # but defensive). Pre-resolution (no REDEEM row yet): keep 50/50
        # expectation since we don't know which side wins.
        if slug_id in redeem_fired_per_slug:
            mark_to_market = paired * 1.0
        else:
            mark_to_market = paired * 1.0 + residual * 0.5
        pnl_so_far += (
            _safe_float(slug_row.get("cash_received") or "")
            - _safe_float(slug_row.get("cash_spent") or "")
            + _safe_float(slug_row.get("rebates") or "")
            - _safe_float(slug_row.get("taker_fees") or "")
            + mark_to_market
        )

    n_open_orders = max(0, n_post - n_cancels)
    paired_inv = min(inv_up, inv_dn)

    # State machine: derive from last_action, with PAIRED override when
    # both sides carry ≥5 paired inventory (the ACC-M merge trigger).
    state: Literal["IDLE", "POSTING", "PAIRED", "MERGING", "RESOLVED"]
    if last_action == "MERGE":
        state = "MERGING"
    elif last_action == "REDEEM":
        state = "RESOLVED"
    elif last_action in ("POST_BID", "POST_ASK", "CANCEL", "MINT", "TAKE"):
        state = "POSTING"
    else:
        state = "IDLE"
    if state == "POSTING" and paired_inv >= 5.0:
        state = "PAIRED"

    return MakerSleeveStateRow(
        sleeve_id=sleeve_id,
        strategy=strategy,  # type: ignore[arg-type]
        cell=cell,
        state=state,
        n_open_orders=n_open_orders,
        paired_inv=paired_inv,
        sum_bids=0.0,  # populated by Plan 30-12b drawer/tile, not by CSV
        sum_asks=0.0,
        n_fills=n_fills,
        n_cancels=n_cancels,
        n_merges=n_merges,
        pnl_so_far=pnl_so_far,
        last_decision_ts_us=last_ts_us,
        csv_path=str(csv_path),
    )


def _day1_sleeve_ids() -> list[str]:
    """Build the day-1 sleeve_ids from settings cell maps.

    Phase 30 D-05 day-1 set (ACC-M / ACC-H / MAS) extended in Phase 31 with
    ACC-PC and PAT-SHADOW (per TV_AGENT_CHANGES_2026_05_19.md §6). Cell maps
    drive the count, so this stays in sync with what the engine spawns as
    long as the engine reads the same ``tv_poly_maker_*_cells`` settings.
    """
    settings = get_settings()
    out: list[str] = []
    for code, raw_cells in (
        ("acc_m", settings.tv_poly_maker_acc_m_cells),
        ("acc_h", settings.tv_poly_maker_acc_h_cells),
        ("mas", settings.tv_poly_maker_mas_cells),
        ("acc_pc", settings.tv_poly_maker_acc_pc_cells),
        ("pat_shadow", settings.tv_poly_maker_pat_shadow_cells),
    ):
        for raw in (raw_cells or "").split(","):
            cell = raw.strip().lower()
            if not cell:
                continue
            parts = cell.split("_")
            if len(parts) != 2:
                continue
            asset, tf = parts
            if asset not in _ALLOWED_ASSETS or tf not in _ALLOWED_TFS:
                continue
            sid = f"poly_{code}_{asset}_{tf}_shadow"
            out.append(sid)
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/maker/sleeves",
    response_model=list[MakerSleeveStateRow],
)
async def list_maker_sleeves(
    _: None = Depends(require_operator_cookie),
) -> list[MakerSleeveStateRow]:
    """List all day-1 maker-arb sleeves with current CSV-derived state.

    Returns 503 if ``settings.tv_poly_maker_log_dir`` does not exist —
    typically the engine hasn't started yet or the disk path is misconfigured.
    """
    settings = get_settings()
    log_dir = Path(settings.tv_poly_maker_log_dir)
    if not log_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="maker logs unavailable (engine may be disabled)",
        )
    return [_compute_state_row(sid, log_dir) for sid in _day1_sleeve_ids()]


@router.get(
    "/maker/sleeves/{sleeve_id}/state",
    response_model=MakerSleeveStateRow,
)
async def get_maker_sleeve_state(
    sleeve_id: str,
    _: None = Depends(require_operator_cookie),
) -> MakerSleeveStateRow:
    """Single-sleeve state row.

    * 404 when ``sleeve_id`` is not a maker-arb sleeve (prefix or token
      validation fails — covers path-traversal injection T-30-12).
    * 503 when the maker log directory is missing.
    * 200 otherwise.
    """
    try:
        _parse_sleeve_id(sleeve_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{sleeve_id} is not a maker-arb sleeve",
        ) from exc

    settings = get_settings()
    log_dir = Path(settings.tv_poly_maker_log_dir)
    if not log_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="maker logs unavailable (engine may be disabled)",
        )
    return _compute_state_row(sleeve_id, log_dir)


# ---------------------------------------------------------------------------
# Plan 30-12b — drawer helpers + routes
# ---------------------------------------------------------------------------


def _read_rows_for_cell(
    sleeve_id: str,
    log_dir: Path,
) -> list[dict[str, str]]:
    """Read today's CSV rows matching this sleeve's (asset, tf) cell.

    Returns ``[]`` when the CSV is absent OR no rows match the cell.
    Raises nothing on read failure — logs a warning and returns ``[]``
    (the drawer endpoints should never 5xx because of disk IO).
    """
    strategy, asset, tf = _parse_sleeve_id(sleeve_id)
    csv_code = _strategy_to_csv_code(strategy)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    csv_path = log_dir / f"{csv_code}_{date_str}.csv"

    if not csv_path.exists():
        return []
    try:
        with csv_path.open("r", newline="") as fh:
            reader = csv.DictReader(fh)
            return [
                dict(r)
                for r in reader
                if (r.get("asset") or "").lower() == asset
                and (r.get("tf") or "") == tf
            ]
    except OSError as exc:
        log.warning(
            "maker_sleeves.csv_read_failed",
            path=str(csv_path),
            error=str(exc),
        )
        return []


def _normalize_side(s: str | None) -> Literal["up", "dn"] | None:
    """Map a raw CSV side cell → 'up' / 'dn' / None."""
    if not s:
        return None
    sl = s.lower()
    if sl == "up":
        return "up"
    if sl == "dn":
        return "dn"
    return None


def _safe_int(s: str) -> int:
    if not s:
        return 0
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


@router.get(
    "/maker/sleeves/{sleeve_id}/orders",
    response_model=list[MakerOrderEvent],
)
async def get_maker_orders(
    sleeve_id: str,
    _: None = Depends(require_operator_cookie),
) -> list[MakerOrderEvent]:
    """Last ``_MAX_ORDER_EVENTS`` order timeline events for the sleeve.

    Filters to action ∈ ``_ORDER_EVENT_ACTIONS`` (POST_BID/POST_ASK/CANCEL/
    TAKE/MERGE/MINT/REDEEM). Internal/unknown actions (e.g. HEARTBEAT,
    DEBUG) are excluded so the operator sees only timeline-relevant rows.

    Sort: descending by ``ts_us`` (most recent first) — the drawer's
    scroll-list semantic.

    * 404 when ``sleeve_id`` is not a maker-arb sleeve.
    * 200 with ``[]`` when no CSV / no matching rows (NOT 503).
    """
    try:
        _parse_sleeve_id(sleeve_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{sleeve_id} is not a maker-arb sleeve",
        ) from exc

    settings = get_settings()
    log_dir = Path(settings.tv_poly_maker_log_dir)
    if not log_dir.exists():
        return []

    rows = _read_rows_for_cell(sleeve_id, log_dir)
    events: list[MakerOrderEvent] = []
    for r in rows:
        action = r.get("action", "")
        if action not in _ORDER_EVENT_ACTIONS:
            continue
        ts_us = _safe_int_ts(r.get("ts_us") or "")
        if ts_us is None:
            continue
        events.append(
            MakerOrderEvent(
                ts_us=ts_us,
                action=action,  # type: ignore[arg-type]
                side=_normalize_side(r.get("side") or ""),
                price=_safe_float(r.get("price") or "") or None,
                size=_safe_float(r.get("size") or "") or None,
                order_id=(r.get("order_id") or None),
                trigger_reason=r.get("trigger_reason") or "",
            )
        )
    # Sort desc by ts_us; cap at _MAX_ORDER_EVENTS.
    events.sort(key=lambda e: e.ts_us, reverse=True)
    return events[:_MAX_ORDER_EVENTS]


@router.get(
    "/maker/sleeves/{sleeve_id}/inventory",
    response_model=list[MakerInventoryPoint],
)
async def get_maker_inventory(
    sleeve_id: str,
    _: None = Depends(require_operator_cookie),
) -> list[MakerInventoryPoint]:
    """Last ``_MAX_INVENTORY_POINTS`` (ts_us, inv_up, inv_dn) samples.

    Sort: ascending by ``ts_us`` so the chart's x-axis is monotonic.
    Only rows that carry BOTH ``inv_up`` AND ``inv_dn`` cells are
    included — early CSV rows may be empty (Plan 30-08 contract:
    SlugState columns are populated only when the dispatcher provides one).

    * 404 when ``sleeve_id`` is not a maker-arb sleeve.
    * 200 with ``[]`` when no CSV / no matching rows (NOT 503).
    """
    try:
        _parse_sleeve_id(sleeve_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{sleeve_id} is not a maker-arb sleeve",
        ) from exc

    settings = get_settings()
    log_dir = Path(settings.tv_poly_maker_log_dir)
    if not log_dir.exists():
        return []

    rows = _read_rows_for_cell(sleeve_id, log_dir)
    points: list[MakerInventoryPoint] = []
    for r in rows:
        inv_up_s = r.get("inv_up") or ""
        inv_dn_s = r.get("inv_dn") or ""
        if not inv_up_s or not inv_dn_s:
            continue
        ts_us = _safe_int_ts(r.get("ts_us") or "")
        if ts_us is None:
            continue
        points.append(
            MakerInventoryPoint(
                ts_us=ts_us,
                inv_up=_safe_float(inv_up_s),
                inv_dn=_safe_float(inv_dn_s),
            )
        )
    points.sort(key=lambda p: p.ts_us)
    # Cap at _MAX_INVENTORY_POINTS — keep the most recent N (the tail).
    if len(points) > _MAX_INVENTORY_POINTS:
        points = points[-_MAX_INVENTORY_POINTS:]
    return points


@router.get(
    "/maker/sleeves/{sleeve_id}/arb-stats",
    response_model=MakerArbStats,
)
async def get_maker_arb_stats(
    sleeve_id: str,
    _: None = Depends(require_operator_cookie),
) -> MakerArbStats:
    """Aggregate arbitrage stats for today's rows on this cell.

    See ``MakerArbStats`` docstring for the exact aggregation formula.

    * 404 when ``sleeve_id`` is not a maker-arb sleeve.
    * 200 with all-zeros body when no CSV / no rows (NOT 503).
    """
    try:
        _parse_sleeve_id(sleeve_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{sleeve_id} is not a maker-arb sleeve",
        ) from exc

    settings = get_settings()
    log_dir = Path(settings.tv_poly_maker_log_dir)
    if not log_dir.exists():
        return MakerArbStats(
            sum_bids=0.0,
            sum_asks=0.0,
            edge_per_pair_realized=0.0,
            n_merges=0,
            rebates_received=0.0,
            taker_fees_paid=0.0,
            pnl_so_far=0.0,
        )

    rows = _read_rows_for_cell(sleeve_id, log_dir)
    sum_bids = 0.0
    sum_asks = 0.0
    n_merges = 0

    # Group latest cash-snapshot row per slug. cash_spent / cash_received /
    # rebates / taker_fees are CUMULATIVE per-slug snapshots — sum across
    # SLUGS, not across rows. See _compute_state_row docstring.
    latest_cash_row_per_slug: dict[str, tuple[int, dict[str, str]]] = {}

    for r in rows:
        action = r.get("action", "")
        filled = (r.get("fill_simulated") or "0") == "1"
        # sum_bids / sum_asks: bid + ask notionals for FILLED orders
        if filled and action in ("POST_BID", "POST_ASK"):
            price = _safe_float(r.get("price") or "")
            size = _safe_float(r.get("size") or "")
            notional = price * size
            if action == "POST_BID":
                sum_bids += notional
            else:
                sum_asks += notional

        if action == "MERGE":
            n_merges += 1

        slug = r.get("slug") or ""
        if slug and (r.get("cash_spent") or r.get("cash_received")):
            row_ts = _safe_int_ts(r.get("ts_us") or "") or 0
            existing = latest_cash_row_per_slug.get(slug)
            if existing is None or row_ts >= existing[0]:
                latest_cash_row_per_slug[slug] = (row_ts, r)

    # Sum cumulative cashflows + mark-to-market across slugs from latest
    # snapshot per slug. See _compute_state_row docstring for the mark
    # rationale (paired*$1 + residual*$0.50).
    rebates = 0.0
    taker_fees = 0.0
    pnl = 0.0
    for _slug_ts, slug_row in latest_cash_row_per_slug.values():
        slug_rebates = _safe_float(slug_row.get("rebates") or "")
        slug_taker = _safe_float(slug_row.get("taker_fees") or "")
        slug_inv_up = _safe_float(slug_row.get("inv_up") or "")
        slug_inv_dn = _safe_float(slug_row.get("inv_dn") or "")
        paired = min(slug_inv_up, slug_inv_dn)
        residual = abs(slug_inv_up - slug_inv_dn)
        mark_to_market = paired * 1.0 + residual * 0.5
        rebates += slug_rebates
        taker_fees += slug_taker
        pnl += (
            _safe_float(slug_row.get("cash_received") or "")
            - _safe_float(slug_row.get("cash_spent") or "")
            + slug_rebates
            - slug_taker
            + mark_to_market
        )

    # edge_per_pair_realized = (rebates - fees) / max(1, n_merges)
    edge = (rebates - taker_fees) / max(1, n_merges)

    return MakerArbStats(
        sum_bids=sum_bids,
        sum_asks=sum_asks,
        edge_per_pair_realized=edge,
        n_merges=n_merges,
        rebates_received=rebates,
        taker_fees_paid=taker_fees,
        pnl_so_far=pnl,
    )


# ---------------------------------------------------------------------------
# Plan 30-12c — microstructure tile compute + endpoint (D-11 layer 3)
# ---------------------------------------------------------------------------


def _compute_microstructure(
    sleeve_id: str,
    rows: list[dict[str, str]],
    *,
    now_us: int,
) -> MakerMicrostructureMetrics:
    """Compute the 4 microstructure metrics from rows already cell-filtered.

    Caller is responsible for path-traversal validation + cell filtering
    (use ``_read_rows_for_cell``). Returns all-zeros metrics + ``last_ts_us=None``
    when ``rows`` is empty.

    Aggregation scope: ALL rows (today's CSV; ``AsyncShadowLogger`` rolls
    files at UTC-midnight so today's CSV is already the "tail"). The
    ``_MICROSTRUCTURE_WINDOW_S`` budget governs the per-hour normalisation
    of ``n_merges_per_hr`` (cap elapsed_hr at 1.0 once a full window has
    elapsed; otherwise project forward from actual elapsed time).

    See ``MakerMicrostructureMetrics`` docstring for the exact formulas.
    """
    if not rows:
        return MakerMicrostructureMetrics(
            sleeve_id=sleeve_id,
            paired_inv_churn=0.0,
            fill_rate=0.0,
            edge_per_pair_realized=0.0,
            n_merges_per_hr=0.0,
            last_ts_us=None,
        )

    n_posts = 0
    n_fills = 0
    n_merges = 0
    first_ts_us: int | None = None
    last_ts_us: int | None = None
    inv_up_series: list[float] = []  # ascending by ts_us — for delta sum

    # Cumulative per-slug snapshot tracking — rebates / taker_fees are
    # cumulative SlugState fields, sum across slugs from latest snapshot.
    latest_cash_row_per_slug: dict[str, tuple[int, dict[str, str]]] = {}

    # Pre-sort by ts_us so inv_up_series captures actual time-ordered
    # deltas rather than file-order (CSV is append-only so usually already
    # sorted, but a defensive sort costs O(n log n) on the bounded file).
    sorted_rows = sorted(
        rows,
        key=lambda r: _safe_int_ts(r.get("ts_us") or "") or 0,
    )

    for r in sorted_rows:
        ts_us = _safe_int_ts(r.get("ts_us") or "")
        if ts_us is None:
            continue

        if first_ts_us is None:
            first_ts_us = ts_us
        last_ts_us = ts_us

        action = r.get("action", "")
        if action in ("POST_BID", "POST_ASK"):
            n_posts += 1
            if (r.get("fill_simulated") or "0") == "1":
                n_fills += 1
        elif action == "MERGE":
            n_merges += 1

        slug = r.get("slug") or ""
        if slug and (r.get("rebates") or r.get("taker_fees")):
            existing = latest_cash_row_per_slug.get(slug)
            if existing is None or ts_us >= existing[0]:
                latest_cash_row_per_slug[slug] = (ts_us, r)

        inv_up_s = r.get("inv_up") or ""
        if inv_up_s:
            inv_up_series.append(_safe_float(inv_up_s))

    rebates_sum = 0.0
    taker_fees_sum = 0.0
    for _slug_ts, slug_row in latest_cash_row_per_slug.values():
        rebates_sum += _safe_float(slug_row.get("rebates") or "")
        taker_fees_sum += _safe_float(slug_row.get("taker_fees") or "")

    # No usable ts rows → return zeros + None last_ts.
    if last_ts_us is None:
        return MakerMicrostructureMetrics(
            sleeve_id=sleeve_id,
            paired_inv_churn=0.0,
            fill_rate=0.0,
            edge_per_pair_realized=0.0,
            n_merges_per_hr=0.0,
            last_ts_us=None,
        )

    # paired_inv_churn = sum(|inv_up[i] - inv_up[i-1]|) / n_inv_rows.
    paired_inv_churn = 0.0
    if len(inv_up_series) >= 2:
        deltas_abs_sum = sum(
            abs(inv_up_series[i] - inv_up_series[i - 1])
            for i in range(1, len(inv_up_series))
        )
        paired_inv_churn = deltas_abs_sum / float(len(inv_up_series))

    # fill_rate = n_fills / max(1, n_posts).
    fill_rate = n_fills / max(1, n_posts)

    # edge_per_pair_realized = (rebates - fees) / max(1, n_merges * 5).
    edge_per_pair_realized = (rebates_sum - taker_fees_sum) / max(
        1, n_merges * _MERGE_TRIGGER_PAIRS
    )

    # n_merges_per_hr — project per-hour from elapsed time. Cap elapsed_hr
    # at 1.0 once a full window has elapsed; otherwise normalise by actual
    # elapsed_hr (with a 0.01 floor for near-instant or far-past data).
    elapsed_s = max(1e-3, (now_us - (first_ts_us or now_us)) / 1_000_000.0)
    elapsed_hr = min(1.0, elapsed_s / 3600.0)
    n_merges_per_hr = float(n_merges) / max(0.01, elapsed_hr)

    return MakerMicrostructureMetrics(
        sleeve_id=sleeve_id,
        paired_inv_churn=paired_inv_churn,
        fill_rate=fill_rate,
        edge_per_pair_realized=edge_per_pair_realized,
        n_merges_per_hr=n_merges_per_hr,
        last_ts_us=last_ts_us,
    )


@router.get(
    "/maker/sleeves/{sleeve_id}/microstructure",
    response_model=MakerMicrostructureMetrics,
)
async def get_maker_microstructure(
    sleeve_id: str,
    _: None = Depends(require_operator_cookie),
) -> MakerMicrostructureMetrics:
    """Maker-arb microstructure metrics for the sleeve's current cell.

    Computes 4 metrics over a rolling ``_MICROSTRUCTURE_WINDOW_S`` (1h):
    paired_inv_churn, fill_rate, edge_per_pair_realized, n_merges_per_hr.

    * 404 when ``sleeve_id`` is not a maker-arb sleeve (parse failure).
    * 200 with all-zeros body when no CSV / no rows (NOT 503 — drawer-tile
      semantic: missing data renders 'AWAITING SHADOW DATA').
    """
    try:
        _parse_sleeve_id(sleeve_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{sleeve_id} is not a maker-arb sleeve",
        ) from exc

    settings = get_settings()
    log_dir = Path(settings.tv_poly_maker_log_dir)
    now_us = int(datetime.now(UTC).timestamp() * 1_000_000)

    if not log_dir.exists():
        return MakerMicrostructureMetrics(
            sleeve_id=sleeve_id,
            paired_inv_churn=0.0,
            fill_rate=0.0,
            edge_per_pair_realized=0.0,
            n_merges_per_hr=0.0,
            last_ts_us=None,
        )

    rows = _read_rows_for_cell(sleeve_id, log_dir)
    return _compute_microstructure(sleeve_id, rows, now_us=now_us)


__all__ = [
    "MakerArbStats",
    "MakerInventoryPoint",
    "MakerMicrostructureMetrics",
    "MakerOrderEvent",
    "MakerSleeveStateRow",
    "_compute_microstructure",
    "_compute_state_row",
    "_day1_sleeve_ids",
    "_parse_sleeve_id",
    "router",
]
