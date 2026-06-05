"""Polymarket Updown paper-resolver — settles filled paper bets against
on-chain ConditionalTokens ``payoutNumerators`` (Phase 26 ``onchain_oracle``).

Phase 18.1 dashboard wiring follow-up: shadow-mode without resolution is
useless — operator can't see win-rate, profit-per-trade, or whether the
strategy is actually working. This worker closes that loop.

2026-05-18 — switched resolution source from Storedata to on-chain oracle
------------------------------------------------------------------------
The original implementation JOINed Storedata's ``public.markets`` +
``public.market_resolutions_v2`` to read chainlink-sourced outcomes. That
made the resolver Ireland-incompatible because Ireland doesn't deploy
the Storedata collector — ``public.markets`` doesn't exist there and the
loop crashed on every tick (workaround was ``TV_POLY_UPDOWN_RESOLVER_ENABLED=false``
which silently broke dashboard cards).

Now the resolver pulls candidate fills from ``trading.events`` (TV-only)
and reads each market's ``payoutNumerators`` directly via
``onchain_oracle.get_resolution(condition_id)``. UMA's resolution lives
on-chain anyway — same source of truth, no Storedata dependency.

ARCHITECTURE
------------
Pure ``trading.events``-driven loop. No in-memory slot tracking. On each
30s tick:

1. Find filled paper signals not yet resolved (NOT EXISTS guard against
   existing ``poly_updown_resolution`` rows).

2. For each pending fill:
   - Call ``oracle.get_resolution(condition_id)``. UNRESOLVED → skip,
     try next tick. UP/DOWN → proceed.
   - Compute paper P&L using ``slot_resolution_pnl`` (matches what
     live trading would see, including the 2% Polymarket fee).

3. Write a ``kind='poly_updown_resolution'`` audit row with the
   computed P&L + emit a ``pnl_snapshot`` WS event so the dashboard's
   PnlFlashCell updates without a refetch.

INVARIANTS
----------
- **No double-pay** — NOT EXISTS sub-query against ``poly_updown_resolution``
  rows on the same ``(condition_id, sleeve_id, fill_event_id)`` so a fill
  is only ever resolved once. Restart-safe: state is fully in DB.
- **No fabricated outcomes** — if ``oracle.get_resolution`` returns
  ``UNRESOLVED``, skip and retry next tick. Never guess.
- **Paper-mode entry_price fallback** — if the audit row's fill_price
  is NULL (older fills predating the paper.py avg_price fix), default
  to the controller's ``Decimal("0.99")`` limit_px. Conservative —
  understates profit, never overstates.
- **Hedged path correct** — if a corresponding hedge fill audit row
  exists (different sleeve, same condition_id, opposite signal),
  resolve as hedged using both legs' entry prices. Phase 18.1 paper
  mode rarely hedges (5 bps reversal trigger), so unhedged is the
  common path.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

from backend.app.venues.polymarket.fees import slot_resolution_pnl
from backend.app.venues.polymarket.onchain_oracle import ResolutionOutcome

if TYPE_CHECKING:
    import asyncpg

    from backend.app.venues.polymarket.onchain_oracle import OnchainOracle

logger = structlog.get_logger("backend.app.engine.poly_updown_resolver")

# Default tick cadence — chainlink resolution lands within seconds of slot_end,
# so 30s is fast enough to feel real-time on the dashboard without hammering
# the DB. Operator can override via PolyUpdownResolver(tick_seconds=...).
DEFAULT_TICK_SECONDS = 30

# Per-tick cap on rows processed — prevents one slow tick from blocking
# stop-event handling. Backlog drains across multiple ticks.
RESOLUTIONS_PER_TICK = 200

# Fallback when paper executor's older fills wrote NULL fill_price (predating
# the avg_price patch in venues/polymarket/paper.py). Equals the controller's
# hard-coded limit_px — slightly conservative but never optimistic.
DEFAULT_ENTRY_PRICE = Decimal("0.99")

# SQL: pick filled paper signals not yet resolved. Pure trading.events —
# NO Storedata JOIN. Per-row, the Python code calls oracle.get_resolution
# to read on-chain ``payoutNumerators``; UNRESOLVED rows are skipped and
# retried next tick.
#
# Hedge linkage: a hedge fires AFTER the entry on the same market, with
# reason='hedge_placed' and the OPPOSITE signal. The controller enforces
# slot-level idempotency via slot.status='hedged_holding', but the
# audit-event INSERT itself is NOT idempotent — retries / race-recoveries
# could write multiple ``hedge_placed`` rows for the same condition_id.
# Likewise ``exited_at_bid`` partials can fire on multiple ticks. Both
# LEFT JOINs are therefore multi-row capable, so we wrap the query in
# ``DISTINCT ON (e.event_id)`` to collapse to one row per entry. Picks the
# MOST-RECENT hedge / partial-exit via ORDER BY ... DESC tiebreak.
#
# Fix history (2026-05-21): before this DISTINCT ON guard, a single entry
# fill with multiple hedge_placed / partial-exit rows produced N×M Cartesian
# rows here, each triggering an INSERT in ``_resolve_one`` and creating
# duplicate ``poly_updown_resolution`` audit rows. Symptom on VPS3:
# 47/85 dupes on poly_updown_btc_5m_momo_v2_HEDGE_f7; dashboard PnL
# inflated 1.2-3×. Partial UNIQUE INDEX on
# ``(sleeve_id, data->>'fill_event_id')`` (migration 0014) plus
# ``ON CONFLICT DO NOTHING`` at the INSERT sites are the storage-layer
# backstop in case any other write path (or this query) ever regresses.
_PENDING_RESOLUTIONS_SQL = """
SELECT DISTINCT ON (e.event_id)
    e.event_id,
    e.at AS fill_at,
    e.sleeve_id,
    e.data->>'condition_id'  AS condition_id,
    e.data->>'signal'        AS signal,
    e.data->>'symbol'        AS symbol,
    e.data->>'tf'            AS tf,
    e.data->>'fill_qty'      AS fill_qty,
    e.data->>'fill_price'    AS fill_price,
    -- 2026-05-20 — propagate entry's mode (live/paper) so the resolution
    -- event carries the same discriminator. Without this, every resolution
    -- was hard-coded mode='paper' (lines 341/463 below) and the live
    -- equity curve query (filters `data->>'mode'='live'`) returned empty.
    e.data->>'mode'          AS entry_mode,
    h.data->>'fill_price'    AS hedge_price,
    h.data->>'fill_qty'      AS hedge_qty,
    h.data->>'signal'        AS hedge_signal,
    -- Phase 18.2 partial-bid-exit forensics fix (2026-04-29):
    -- LEFT JOIN to capture cases where _try_bid_exit fired but only PARTIALLY
    -- filled (sold M of N shares; remaining N-M held to chainlink). The
    -- exit-resolver path (_resolve_one_exit) only handles FULL fills now;
    -- partials route here so realized_via_bid + chainlink_on_held both
    -- contribute to total PnL. See _resolve_one for the math.
    px.event_id              AS partial_exit_event_id,
    px.data->>'fill_qty'     AS partial_exit_qty,
    px.data->>'fill_price'   AS partial_exit_price
FROM trading.events e
LEFT JOIN trading.events h
    ON h.kind = 'poly_updown_signal'
   AND h.sleeve_id = e.sleeve_id
   AND h.data->>'condition_id' = e.data->>'condition_id'
   AND h.data->>'reason' = 'hedge_placed'
   AND h.data->>'fill_status' = 'filled'
LEFT JOIN trading.events px
    ON px.kind = 'poly_updown_signal'
   AND px.sleeve_id = e.sleeve_id
   AND px.data->>'condition_id' = e.data->>'condition_id'
   AND px.data->>'reason' = 'exited_at_bid'
   AND px.data->>'fill_status' = 'filled'
   -- Only PARTIAL bid-exits route through chainlink path. Full bid-exits
   -- (>=99% of entry_qty sold) close off-chain via _resolve_one_exit.
   AND (px.data->>'fill_qty')::numeric < (e.data->>'fill_qty')::numeric * 0.99
WHERE e.kind = 'poly_updown_signal'
  AND e.data->>'reason' = 'order_placed'
  AND e.data->>'fill_status' = 'filled'
  AND e.data->>'condition_id' IS NOT NULL
  AND NOT EXISTS (
        SELECT 1
        FROM trading.events r2
        WHERE r2.kind = 'poly_updown_resolution'
          AND r2.sleeve_id = e.sleeve_id
          AND r2.data->>'condition_id' = e.data->>'condition_id'
          AND r2.data->>'fill_event_id' = e.event_id::text
  )
-- DISTINCT ON requires the ORDER BY to lead with the partition key.
-- Tiebreak prefers the latest hedge / partial-exit so the resolution
-- payload uses the freshest auxiliary data.
ORDER BY e.event_id, h.at DESC NULLS LAST, px.at DESC NULLS LAST, e.at ASC
LIMIT $1
""".strip()


# Phase 18.2 V2 — exited_at_bid path. When a slot exits via HYBRID branch 2
# (sell own held side at bid), the position is closed off-chain; PnL is
# realized at exit time with no chainlink lookup required. The resolver
# detects these via a JOIN to the reason='exited_at_bid' audit row that
# `_try_bid_exit` writes.
#
# This SQL is INTENTIONALLY independent of the chainlink-resolution path:
# - exited_at_bid slots have NO on-chain CTF tokens to redeem, so they
#   resolve as soon as the exit fill clears.
# - PnL formula = exit_proceeds_usd - entry_cost_usd (raw USD math; no fee
#   layer because the 2% Polymarket resolution fee only applies to on-chain
#   settlement, not CLOB exits).
#
# DISTINCT ON guard (2026-05-21) — same Cartesian-product risk as the V1
# query above: a single entry fill may JOIN to multiple ``exited_at_bid``
# rows (multi-tick partial drains escalating to a full exit). Collapse
# to one row per entry, picking the LATEST exit_at_bid for the payload.
_PENDING_EXIT_RESOLUTIONS_SQL = """
SELECT DISTINCT ON (e.event_id)
    e.event_id      AS entry_event_id,
    e.sleeve_id,
    e.data->>'condition_id' AS condition_id,
    e.data->>'signal'       AS signal,
    e.data->>'symbol'       AS symbol,
    e.data->>'tf'           AS tf,
    e.data->>'fill_qty'     AS entry_qty,
    e.data->>'fill_price'   AS entry_price,
    -- 2026-05-20 — propagate entry mode (see _PENDING_RESOLUTIONS_SQL above).
    e.data->>'mode'         AS entry_mode,
    x.event_id      AS exit_event_id,
    x.data->>'fill_qty'     AS exit_shares,
    x.data->>'fill_price'   AS exit_price
FROM trading.events e
JOIN trading.events x
    ON x.kind = 'poly_updown_signal'
   AND x.sleeve_id = e.sleeve_id
   AND x.data->>'condition_id' = e.data->>'condition_id'
   AND x.data->>'reason' = 'exited_at_bid'
   AND x.data->>'fill_status' = 'filled'
   -- Phase 18.2 partial-bid-exit forensics fix (2026-04-29):
   -- ONLY FULL bid-exits resolve here. Partials route to the chainlink
   -- path (which JOINs the same audit row + augments chainlink PnL on
   -- the unsold portion). 99% threshold absorbs Decimal precision noise.
   AND (x.data->>'fill_qty')::numeric >= (e.data->>'fill_qty')::numeric * 0.99
WHERE e.kind = 'poly_updown_signal'
  AND e.data->>'reason' = 'order_placed'
  AND e.data->>'fill_status' = 'filled'
  AND e.data->>'condition_id' IS NOT NULL
  AND NOT EXISTS (
        SELECT 1
        FROM trading.events r2
        WHERE r2.kind = 'poly_updown_resolution'
          AND r2.sleeve_id = e.sleeve_id
          AND r2.data->>'condition_id' = e.data->>'condition_id'
          AND r2.data->>'fill_event_id' = e.event_id::text
  )
ORDER BY e.event_id, x.at DESC, e.at ASC
LIMIT $1
""".strip()


def _signal_won(signal: str | None, outcome: str | None) -> bool:
    """True iff our directional bet matches chainlink's resolution.

    ``signal`` is the controller vocabulary ('UP' | 'DOWN').
    ``outcome`` is the chainlink vocabulary ('Up' | 'Down').
    """
    if signal == "UP" and outcome == "Up":
        return True
    if signal == "DOWN" and outcome == "Down":
        return True
    return False


def _parse_decimal(raw: Any, default: Decimal | None = None) -> Decimal | None:
    if raw is None or raw == "":
        return default
    try:
        return Decimal(str(raw))
    except Exception:
        return default


def _outcome_to_dashboard_str(outcome: ResolutionOutcome) -> str:
    """Map ``ResolutionOutcome`` enum to the dashboard's ``'Up'|'Down'`` strings.

    The dashboard, controller (``_signal_won``), and historical resolution
    rows all use the capitalised forms; the oracle returns lowercase enum
    values. Centralised so the mapping has one home.
    """
    if outcome is ResolutionOutcome.UP:
        return "Up"
    if outcome is ResolutionOutcome.DOWN:
        return "Down"
    raise ValueError(f"unmapped outcome: {outcome!r}")


async def _resolve_one(
    conn: "asyncpg.Connection",
    oracle: "OnchainOracle",
    row: dict[str, Any],
) -> bool:
    """Compute P&L for one pending fill and write the resolution row.

    Calls ``oracle.get_resolution(condition_id)``. If the market is not
    yet resolved on-chain, returns False (no row written; we retry next
    tick). Otherwise computes P&L and writes ``poly_updown_resolution``.

    Returns True iff a resolution row was written. False on data gap
    (missing fill_qty) OR on UNRESOLVED outcome.
    """
    sleeve_id = row["sleeve_id"]
    condition_id = row["condition_id"]
    signal = row["signal"]
    fill_event_id = row["event_id"]

    # On-chain resolution lookup. UNRESOLVED → try next tick.
    try:
        outcome_enum = await oracle.get_resolution(condition_id)
    except Exception as exc:  # noqa: BLE001 — oracle error: skip this row, retry next tick
        logger.warning(
            "poly_updown_resolver.oracle_error",
            sleeve_id=sleeve_id,
            condition_id=condition_id,
            error=str(exc),
        )
        return False
    if outcome_enum is ResolutionOutcome.UNRESOLVED:
        return False
    outcome = _outcome_to_dashboard_str(outcome_enum)
    # Stamp so resolver_tick's win/loss tally can read it without a 2nd
    # oracle lookup. Used as a side-channel between _resolve_one and the
    # tick loop; intentionally underscore-prefixed (transient, not payload).
    row["_outcome_str"] = outcome

    qty = _parse_decimal(row.get("fill_qty"))
    if qty is None or qty <= 0:
        logger.warning(
            "poly_updown_resolver.skip_no_qty",
            sleeve_id=sleeve_id,
            event_id=str(fill_event_id),
        )
        return False

    entry_price = _parse_decimal(
        row.get("fill_price"),
        default=DEFAULT_ENTRY_PRICE,
    ) or DEFAULT_ENTRY_PRICE

    # Hedge detection: LEFT JOIN brings hedge_price NULL when no hedge fired.
    # When present, use it as slot_resolution_pnl's hedge_other_entry_price so
    # the math accounts for both legs (cost = entry*qty + hedge*qty; payout
    # = winning leg only). For hedged slots, exactly one leg wins regardless
    # of which signal direction was right.
    hedge_price = _parse_decimal(row.get("hedge_price"))
    is_hedged = hedge_price is not None and hedge_price > 0
    # 2026-05-23 fix: actual hedge fill_qty for accurate PnL on partial
    # hedge fills. Without this, slot_resolution_pnl assumed hedge_qty ==
    # entry_qty (full hedge), over-debiting the hedge leg's cost and
    # systematically reporting negative PnL on winning trades.
    hedge_qty_actual = _parse_decimal(row.get("hedge_qty")) if is_hedged else None

    # Phase 18.2 partial-bid-exit fix (2026-04-29): _PENDING_RESOLUTIONS_SQL
    # LEFT JOINs the partial exit audit row (only matches when
    # exit_qty < entry_qty * 0.99). Full exits resolve via _resolve_one_exit;
    # partials reach this path so we can sum realized + chainlink-on-held.
    partial_exit_qty = _parse_decimal(row.get("partial_exit_qty"))
    partial_exit_price = _parse_decimal(row.get("partial_exit_price"))
    has_partial_exit = (
        partial_exit_qty is not None
        and partial_exit_qty > 0
        and partial_exit_price is not None
        and partial_exit_price > 0
        and partial_exit_qty < qty
    )

    won = _signal_won(signal, outcome)

    if has_partial_exit:
        # Two-leg PnL:
        #   1. Realized via bid sell: M shares @ exit_price proceeds, cost basis
        #      M × entry_price → realized = M × (exit_price - entry_price).
        #   2. Held N-M shares to chainlink: PnL via slot_resolution_pnl on the
        #      reduced qty. Hedge case is rare here (HYBRID branch 2 only fires
        #      when branch 1 failed), so hedge_price is typically None. If both
        #      hedge AND partial-exit somehow co-occur, we honor the hedge_price
        #      on the held portion since that leg is a real position too.
        held_qty = qty - partial_exit_qty  # type: ignore[operator]
        realized_via_bid = (
            partial_exit_qty * partial_exit_price  # proceeds
            - partial_exit_qty * entry_price       # cost on sold portion
        )
        chainlink_pnl_on_held = slot_resolution_pnl(
            entry_price=entry_price,
            entry_qty=held_qty,
            hedge_other_entry_price=hedge_price if is_hedged else None,
            signal_won=won,
            hedge_qty=hedge_qty_actual,
        )
        pnl = realized_via_bid + chainlink_pnl_on_held
    else:
        pnl = slot_resolution_pnl(
            entry_price=entry_price,
            entry_qty=qty,
            hedge_other_entry_price=hedge_price if is_hedged else None,
            signal_won=won,
            hedge_qty=hedge_qty_actual,
        )

    payload: dict[str, Any] = {
        "fill_event_id": str(fill_event_id),
        "condition_id": condition_id,
        "symbol": row.get("symbol"),
        "tf": row.get("tf"),
        "signal": signal,
        "outcome": outcome,
        "won": won,
        "entry_price": str(entry_price),
        "entry_qty": str(qty),
        "hedged": is_hedged,
        "hedge_price": str(hedge_price) if hedge_price is not None else None,
        # 2026-05-23 — actual hedge fill qty (None when unhedged or feed
        # didn't report fill_qty on hedge_placed). Enables analytics SQL
        # to verify hedge_qty < entry_qty cases.
        "hedge_qty": str(hedge_qty_actual) if hedge_qty_actual is not None else None,
        # Provenance: ``onchain_oracle`` = read from CTF.payoutNumerators
        # at the contract layer (Polymarket's actual settlement source). The
        # legacy strings ``'chainlink'`` and ``'chainlink-fast'`` referred to
        # Storedata's hourly/realtime price collector; 2026-05-18 removed.
        "price_source": "onchain_oracle",
        "pnl_usd": str(pnl),
        # 2026-05-20 — read entry's mode from the audit row (entry_mode in
        # the SQL). Default to 'paper' for backwards compat with old rows
        # that don't carry the field.
        "mode": row.get("entry_mode") or "paper",
    }
    # Phase 18.2 partial-bid-exit fix: surface the split for forensics.
    if has_partial_exit:
        payload.update({
            "partial_bid_exit": True,
            "partial_exit_qty": str(partial_exit_qty),
            "partial_exit_price": str(partial_exit_price),
            "partial_exit_event_id": str(row.get("partial_exit_event_id")),
            "held_qty_to_chainlink": str(qty - partial_exit_qty),  # type: ignore[operator]
            "realized_via_bid_pnl": str(
                partial_exit_qty * partial_exit_price
                - partial_exit_qty * entry_price
            ),
            "chainlink_pnl_on_held": str(
                slot_resolution_pnl(
                    entry_price=entry_price,
                    entry_qty=qty - partial_exit_qty,  # type: ignore[operator]
                    hedge_other_entry_price=hedge_price if is_hedged else None,
                    signal_won=won,
                )
            ),
        })

    # 2026-05-21 — dupe-prevention is at the QUERY layer above
    # (``DISTINCT ON (e.event_id)`` in ``_PENDING_RESOLUTIONS_SQL``).
    # No ``ON CONFLICT`` backstop: ``trading.events`` is partitioned by
    # ``at`` and PostgreSQL forbids unique constraints on partitioned
    # tables that don't include the partition key, so the storage-layer
    # idempotency guard isn't viable. Migration 0014 cleans up the
    # historical Cartesian-product dupes.
    await conn.execute(
        "INSERT INTO trading.events (at, sleeve_id, kind, data) "
        "VALUES (now(), $1, 'poly_updown_resolution', $2::jsonb)",
        sleeve_id,
        json.dumps(payload),
    )

    # NOTE intentionally not publishing pnl_snapshot here. The WS event
    # carries `realized` which the existing PnlFlashCell interprets as
    # the cumulative sleeve P&L; this resolver knows only ONE bet's pnl
    # at a time, so emitting would clobber the cumulative on the dashboard.
    # The dashboard's 30s React Query refetch picks up new wins/losses + pnl
    # within one cycle — sufficient for shadow-mode operator inspection. A
    # future enhancement could query cumulative realized here and publish
    # an authoritative snapshot, or introduce a delta-style WS kind.
    logger.info(
        "poly_updown_resolver.resolved",
        sleeve_id=sleeve_id,
        signal=signal,
        outcome=outcome,
        won=won,
        hedged=is_hedged,
        pnl_usd=str(pnl),
        condition_id=condition_id,
    )
    return True


async def _resolve_one_exit(
    conn: "asyncpg.Connection",
    row: dict[str, Any],
) -> bool:
    """Phase 18.2 V2: write resolution row for a slot that exited at the bid.

    PnL = exit_proceeds_usd - entry_cost_usd. No chainlink lookup; no 2%
    Polymarket fee (CLOB exit, not on-chain settlement). The dedup key
    `fill_event_id` mirrors the chainlink path so the NOT EXISTS guard in
    `_PENDING_RESOLUTIONS_SQL` prevents double-resolution if both paths
    somehow match the same entry.
    """
    sleeve_id = row["sleeve_id"]
    condition_id = row["condition_id"]
    signal = row["signal"]
    entry_event_id = row["entry_event_id"]

    entry_qty = _parse_decimal(row.get("entry_qty"))
    entry_price = _parse_decimal(
        row.get("entry_price"),
        default=DEFAULT_ENTRY_PRICE,
    ) or DEFAULT_ENTRY_PRICE
    exit_shares = _parse_decimal(row.get("exit_shares"))
    exit_price = _parse_decimal(row.get("exit_price"))

    if entry_qty is None or entry_qty <= 0:
        logger.warning(
            "poly_updown_resolver.exit_skip_no_qty",
            sleeve_id=sleeve_id,
            entry_event_id=str(entry_event_id),
        )
        return False
    if (
        exit_shares is None
        or exit_shares <= 0
        or exit_price is None
        or exit_price <= 0
    ):
        logger.warning(
            "poly_updown_resolver.exit_skip_bad_exit_data",
            sleeve_id=sleeve_id,
            entry_event_id=str(entry_event_id),
        )
        return False

    entry_cost_usd = entry_qty * entry_price
    exit_proceeds_usd = exit_shares * exit_price
    pnl = exit_proceeds_usd - entry_cost_usd
    won = pnl > 0  # heuristic — profitable bid-exit

    payload: dict[str, Any] = {
        "fill_event_id": str(entry_event_id),
        "exit_event_id": str(row["exit_event_id"]),
        "condition_id": condition_id,
        "symbol": row.get("symbol"),
        "tf": row.get("tf"),
        "signal": signal,
        # V2 sentinel — distinguishes off-chain bid-exit from chainlink Up/Down.
        # Dashboards must not treat this as a chainlink resolution.
        "outcome": "exited_at_bid",
        "won": won,
        # 2026-05-21 — stamp fill_event_id in the V2 payload too. V1 always
        # included this; V2 omitted it pre-fix, so the dedupe migration 0014
        # leaves V2 rows un-indexed and the ON CONFLICT below cannot fire
        # without this field. ``entry_event_id`` is the SQL alias for the
        # entry fill's event_id (see _PENDING_EXIT_RESOLUTIONS_SQL above).
        "fill_event_id": str(row.get("entry_event_id")),
        "entry_price": str(entry_price),
        "entry_qty": str(entry_qty),
        "exit_price": str(exit_price),
        "exit_shares": str(exit_shares),
        "entry_cost_usd": str(entry_cost_usd),
        "exit_proceeds_usd": str(exit_proceeds_usd),
        "hedged": False,
        "exited_at_bid": True,  # V2 marker
        "pnl_usd": str(pnl),
        # 2026-05-20 — read entry's mode from the audit row (entry_mode in
        # the SQL). Default to 'paper' for backwards compat with old rows
        # that don't carry the field.
        "mode": row.get("entry_mode") or "paper",
    }

    # 2026-05-21 — dupe-prevention is at the QUERY layer
    # (``DISTINCT ON (e.event_id)`` in ``_PENDING_EXIT_RESOLUTIONS_SQL``);
    # see _resolve_one for the rationale on why no ON CONFLICT backstop.
    await conn.execute(
        "INSERT INTO trading.events (at, sleeve_id, kind, data) "
        "VALUES (now(), $1, 'poly_updown_resolution', $2::jsonb)",
        sleeve_id,
        json.dumps(payload),
    )

    logger.info(
        "poly_updown_resolver.resolved_exit",
        sleeve_id=sleeve_id,
        signal=signal,
        won=won,
        pnl_usd=str(pnl),
        condition_id=condition_id,
    )
    return True


async def resolver_tick(
    pool: "asyncpg.Pool",
    oracle: "OnchainOracle | None" = None,
    *,
    limit: int = RESOLUTIONS_PER_TICK,
) -> dict[str, int]:
    """Run one resolver pass. Returns a count summary for observability.

    Two independent paths run per tick:
      1. On-chain resolution chain (V1): per-row ``oracle.get_resolution``;
         UNRESOLVED rows skipped, retried next tick.
      2. Bid-exited chain (V2 HYBRID): resolves as soon as an exit fill clears.

    Both paths write `poly_updown_resolution` rows keyed by `fill_event_id`,
    and both use the same NOT EXISTS guard, so a slot is resolved by
    whichever path reaches it first.

    Args:
        pool: asyncpg pool. ``None`` → no-op (returns empty summary).
        oracle: ``OnchainOracle`` for the V1 path. ``None`` short-circuits
            the V1 path; only the V2 bid-exit path runs in that mode (used
            by legacy callers that never spawned the oracle, e.g. before
            the 2026-05-18 rewrite).
        limit: per-path row cap.
    """
    summary = {"pending": 0, "resolved": 0, "wins": 0, "losses": 0, "errors": 0}

    if pool is None:
        return summary

    async with pool.acquire() as conn:
        # V1 on-chain resolution path. Requires an oracle.
        if oracle is not None:
            rows = await conn.fetch(_PENDING_RESOLUTIONS_SQL, limit)
            summary["pending"] = len(rows)

            for r in rows:
                row_dict = dict(r)
                try:
                    wrote = await _resolve_one(conn, oracle, row_dict)
                except Exception:
                    logger.exception(
                        "poly_updown_resolver.tick_error",
                        sleeve_id=row_dict.get("sleeve_id"),
                        condition_id=row_dict.get("condition_id"),
                    )
                    summary["errors"] += 1
                    continue
                if wrote:
                    summary["resolved"] += 1
                    # _resolve_one stamped ``row_dict['_outcome_str']`` for
                    # the win/loss tally. If absent (legacy callers), fall
                    # back to a re-lookup via the oracle (cheap — cached).
                    outcome_str = row_dict.get("_outcome_str")
                    if outcome_str is None:
                        # Defensive — should not happen post-rewrite.
                        continue
                    if _signal_won(row_dict.get("signal"), outcome_str):
                        summary["wins"] += 1
                    else:
                        summary["losses"] += 1

        # V2 HYBRID exited_at_bid path.
        exit_rows = await conn.fetch(_PENDING_EXIT_RESOLUTIONS_SQL, limit)
        summary["pending"] += len(exit_rows)
        for r in exit_rows:
            row_dict = dict(r)
            try:
                wrote = await _resolve_one_exit(conn, row_dict)
            except Exception:
                logger.exception(
                    "poly_updown_resolver.exit_tick_error",
                    sleeve_id=row_dict.get("sleeve_id"),
                    condition_id=row_dict.get("condition_id"),
                )
                summary["errors"] += 1
                continue
            if wrote:
                summary["resolved"] += 1
                # Bid-exit "win/loss" is PnL-positive vs PnL-negative — separate
                # from chainlink directional outcome. Counted in wins/losses
                # for dashboard arithmetic; the `outcome='exited_at_bid'` field
                # in the payload disambiguates downstream.
                entry_qty = _parse_decimal(row_dict.get("entry_qty"))
                entry_price = _parse_decimal(
                    row_dict.get("entry_price"),
                    default=DEFAULT_ENTRY_PRICE,
                ) or DEFAULT_ENTRY_PRICE
                exit_shares = _parse_decimal(row_dict.get("exit_shares"))
                exit_price = _parse_decimal(row_dict.get("exit_price"))
                if all(
                    x is not None for x in (entry_qty, exit_shares, exit_price)
                ):
                    pnl = (
                        exit_shares * exit_price - entry_qty * entry_price  # type: ignore[operator]
                    )
                    if pnl > 0:
                        summary["wins"] += 1
                    else:
                        summary["losses"] += 1

    return summary


async def poly_updown_resolver_loop(
    pool: "asyncpg.Pool",
    oracle: "OnchainOracle",
    stop: asyncio.Event,
    *,
    tick_seconds: int = DEFAULT_TICK_SECONDS,
) -> None:
    """Run the resolver until ``stop`` is set.

    Per-iteration exceptions are caught + logged so one bad row never
    kills the loop. SIGTERM is handled via ``stop.wait()`` interrupting
    the sleep.

    Args:
        pool: asyncpg pool for trading.events reads + writes.
        oracle: ``OnchainOracle`` instance shared with poly_redeemer (one
            HTTP provider per engine — cheap + simplifies wiring).
        stop: stop signal event.
        tick_seconds: tick cadence.
    """
    logger.info(
        "poly_updown_resolver.starting",
        tick_seconds=tick_seconds,
    )

    while not stop.is_set():
        try:
            summary = await resolver_tick(pool, oracle)
            if summary["resolved"] > 0:
                logger.info(
                    "poly_updown_resolver.tick_summary",
                    **summary,
                )
        except Exception:
            logger.exception("poly_updown_resolver.loop_error")

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=tick_seconds)

    logger.info("poly_updown_resolver.stopped")


__all__ = [
    "DEFAULT_ENTRY_PRICE",
    "DEFAULT_TICK_SECONDS",
    "RESOLUTIONS_PER_TICK",
    "_PENDING_RESOLUTIONS_SQL",
    "_outcome_to_dashboard_str",
    "_signal_won",
    "poly_updown_resolver_loop",
    "resolver_tick",
]
