"""Equity-snapshot helpers (Phase 10, Task 2 · 10-CONTEXT D-04).

Reads + writes for the ``engine.equity_snapshots`` table:

* ``snapshot_equity(pool, scope, at, equity_usd)`` — compute ATH
  (running max) + dd_pct + window_24h_low for the scope; insert one row.
* ``load_snapshots_24h(pool, scope, now)`` — SELECT last 24h (scoped).
* ``load_latest_snapshot(pool, scope)`` — SELECT most-recent snapshot.

All are async + pool-backed. The BarEngine calls ``snapshot_equity`` at
every 4h bar boundary (and the portfolio aggregate once per wake);
rails read via ``load_snapshots_24h`` and pass the result into the
pure-function rail checkers.

Windows-harness note: these helpers require a real Postgres pool. Unit
tests run against a mocked pool; full integration verification is
skip-marked and deferred to the Postgres fixture lane.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from backend.app.engine.models import EquitySnapshot
from backend.app.engine.notify import notify_event

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    import asyncpg


async def snapshot_equity(
    pool: asyncpg.Pool,
    *,
    scope: str,
    at: datetime,
    equity_usd: Decimal,
) -> EquitySnapshot:
    """Insert one ``engine.equity_snapshots`` row with computed ATH + DD.

    Algorithm:

    1. Load the previous ATH for ``scope`` (``MAX(ath_usd)`` across all
       prior rows for this scope). If none exists, seed ATH = equity.
    2. New ATH = ``max(previous_ath, equity_usd)``.
    3. ``dd_pct = (new_ath - equity) / new_ath * 100`` (0 when ath = 0).
    4. ``window_24h_low = MIN(equity_usd)`` across the last 24h for
       this scope (including the new row's own equity).
    5. Atomic INSERT inside a transaction.
    """
    async with pool.acquire() as conn, conn.transaction():
        prev = await conn.fetchrow(
            "SELECT MAX(ath_usd) AS ath FROM engine.equity_snapshots "
            "WHERE scope = $1",
            scope,
        )
        prev_ath: Decimal | None = None
        if prev is not None and prev["ath"] is not None:
            prev_ath = Decimal(str(prev["ath"]))

        new_ath = equity_usd if prev_ath is None else max(prev_ath, equity_usd)
        dd_pct = (
            (new_ath - equity_usd) / new_ath * Decimal("100")
            if new_ath > 0
            else Decimal("0")
        )

        # window_24h_low — include the new snapshot's equity (incoming row).
        row = await conn.fetchrow(
            "SELECT MIN(equity_usd) AS lo FROM engine.equity_snapshots "
            "WHERE scope = $1 AND at >= $2",
            scope,
            at - timedelta(hours=24),
        )
        prior_low: Decimal | None = None
        if row is not None and row["lo"] is not None:
            prior_low = Decimal(str(row["lo"]))
        window_low = (
            equity_usd if prior_low is None else min(prior_low, equity_usd)
        )

        inserted = await conn.fetchrow(
            "INSERT INTO engine.equity_snapshots "
            "(at, scope, equity_usd, ath_usd, dd_pct, window_24h_low) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "RETURNING snapshot_id, at, scope, equity_usd, ath_usd, dd_pct, "
            "window_24h_low",
            at,
            scope,
            equity_usd,
            new_ath,
            dd_pct,
            window_low,
        )

    assert inserted is not None  # INSERT ... RETURNING never returns NULL row

    # Phase 17.1 Plan 02 — emit pg_notify(kind="pnl_snapshot") AFTER the
    # transaction commits (above ``async with`` block has exited). NOTIFY is
    # best-effort; failure here is logged but never propagated.
    async with pool.acquire() as notify_conn:
        await notify_event(
            notify_conn,
            kind="pnl_snapshot",
            payload={
                "id": str(inserted["snapshot_id"]),
                "_table": "engine.equity_snapshots",
                "scope": str(inserted["scope"]),
                "equity_usd": str(inserted["equity_usd"]),
                "ath_usd": str(inserted["ath_usd"]),
                "dd_pct": str(inserted["dd_pct"]),
            },
        )

    return EquitySnapshot(
        snapshot_id=UUID(str(inserted["snapshot_id"]))
        if not isinstance(inserted["snapshot_id"], UUID)
        else inserted["snapshot_id"],
        at=inserted["at"],
        scope=inserted["scope"],
        equity_usd=Decimal(str(inserted["equity_usd"])),
        ath_usd=Decimal(str(inserted["ath_usd"])),
        dd_pct=Decimal(str(inserted["dd_pct"])),
        window_24h_low=(
            Decimal(str(inserted["window_24h_low"]))
            if inserted["window_24h_low"] is not None
            else None
        ),
    )


async def load_snapshots_24h(
    pool: asyncpg.Pool,
    *,
    scope: str,
    now: datetime,
) -> list[EquitySnapshot]:
    """Return the last 24h of snapshots for ``scope``, oldest-first."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT snapshot_id, at, scope, equity_usd, ath_usd, dd_pct, "
            "window_24h_low FROM engine.equity_snapshots "
            "WHERE scope = $1 AND at >= $2 ORDER BY at ASC",
            scope,
            now - timedelta(hours=24),
        )
    return [_row_to_snapshot(r) for r in rows]


async def load_latest_snapshot(
    pool: asyncpg.Pool,
    *,
    scope: str,
) -> EquitySnapshot | None:
    """Return the most-recent snapshot for ``scope`` or None if absent."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT snapshot_id, at, scope, equity_usd, ath_usd, dd_pct, "
            "window_24h_low FROM engine.equity_snapshots "
            "WHERE scope = $1 ORDER BY at DESC LIMIT 1",
            scope,
        )
    return _row_to_snapshot(row) if row is not None else None


def _row_to_snapshot(row: dict) -> EquitySnapshot:
    """Convert a raw asyncpg record into an ``EquitySnapshot``."""
    return EquitySnapshot(
        snapshot_id=row["snapshot_id"],
        at=row["at"],
        scope=row["scope"],
        equity_usd=Decimal(str(row["equity_usd"])),
        ath_usd=Decimal(str(row["ath_usd"])),
        dd_pct=Decimal(str(row["dd_pct"])),
        window_24h_low=(
            Decimal(str(row["window_24h_low"]))
            if row["window_24h_low"] is not None
            else None
        ),
    )


__all__ = [
    "load_latest_snapshot",
    "load_snapshots_24h",
    "snapshot_equity",
]
