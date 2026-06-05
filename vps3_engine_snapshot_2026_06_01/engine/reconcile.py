"""Phase 16 BACKUP-06 — boot-time EXACT-match position reconciliation.

Per RESEARCH §Q6 + ⚠ deviation #1 + #2:
- DB query MUST use `WHERE status='open'` (column `closed_at` does NOT
  exist on `trading.positions` — see migration 0002).
- AlertService is the Protocol from `backend.app.services.alert_service`;
  reconcile_or_exit accepts any conformant implementation (incl. the
  factory `build_alert_service`).
- Tolerance is ZERO. Any non-empty diff:
   1. INSERT into trading.events (kind='boot_reconcile_mismatch', critical).
   2. AlertService.emit(severity=CRITICAL, kind='boot_reconcile_mismatch').
   3. exit_fn(1) — systemd sees rc!=0 → unit `failed` → operator pages.
- Reconcile NEVER calls a kill API. Per CLAUDE.md invariant #11, code
  may only `raise_alert(severity=critical)` to request operator action.
- Empty venue_clients (paper-mode boot or pre-Phase-14/15) → pass.

REQ-ID: BACKUP-06.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import structlog

from backend.app.services.alert_service import AlertService, AlertSeverity

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Position records (frozen value types)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DBPosition:
    symbol: str
    side: str  # "long" | "short"
    qty: Decimal


@dataclass(frozen=True)
class VenuePosition:
    symbol: str
    side: str
    qty: Decimal


@dataclass(frozen=True)
class MismatchedQty:
    symbol: str
    side: str
    db_qty: Decimal
    venue_qty: Decimal


@dataclass
class PositionDiff:
    db_only: list[DBPosition] = field(default_factory=list)
    venue_only: list[VenuePosition] = field(default_factory=list)
    mismatched: list[MismatchedQty] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.db_only or self.venue_only or self.mismatched)

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_only": [
                {"symbol": p.symbol, "side": p.side, "qty": str(p.qty)}
                for p in self.db_only
            ],
            "venue_only": [
                {"symbol": p.symbol, "side": p.side, "qty": str(p.qty)}
                for p in self.venue_only
            ],
            "mismatched": [
                {
                    "symbol": m.symbol,
                    "side": m.side,
                    "db_qty": str(m.db_qty),
                    "venue_qty": str(m.venue_qty),
                }
                for m in self.mismatched
            ],
        }


# ---------------------------------------------------------------------------
# Pure diff
# ---------------------------------------------------------------------------


def compute_diff(
    *,
    db: list[DBPosition],
    venue: list[VenuePosition],
) -> PositionDiff:
    """Symmetric diff keyed by (symbol, side). Tolerance: ZERO."""
    db_idx: dict[tuple[str, str], DBPosition] = {(p.symbol, p.side): p for p in db}
    venue_idx: dict[tuple[str, str], VenuePosition] = {
        (p.symbol, p.side): p for p in venue
    }

    diff = PositionDiff()
    all_keys = set(db_idx) | set(venue_idx)
    for key in sorted(all_keys):
        d = db_idx.get(key)
        v = venue_idx.get(key)
        if d is not None and v is None:
            diff.db_only.append(d)
        elif v is not None and d is None:
            diff.venue_only.append(v)
        elif d is not None and v is not None:
            if d.qty != v.qty:
                diff.mismatched.append(
                    MismatchedQty(
                        symbol=d.symbol,
                        side=d.side,
                        db_qty=d.qty,
                        venue_qty=v.qty,
                    )
                )
    return diff


# ---------------------------------------------------------------------------
# Loaders (DB + Venue side)
# ---------------------------------------------------------------------------


# RESEARCH ⚠ deviation #1: schema lacks closed_at; open == status='open'.
# Single-venue v0.1: HL-only. When Phase 14/15 adds Poly+Kalshi, the
# `trading.positions` schema MUST grow a `venue` column (see RESEARCH OQ-2);
# until then we attribute every open row to the single registered venue.
_DB_OPEN_POSITIONS_SQL = """
SELECT symbol, side, qty
FROM trading.positions
WHERE status = 'open'
"""


_INSERT_EVENT_SQL = """
INSERT INTO trading.events (kind, data)
VALUES ($1, $2::jsonb)
"""


class _PoolLike(Protocol):
    def acquire(self) -> Any: ...


async def _load_db_positions(pool: _PoolLike) -> list[DBPosition]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(_DB_OPEN_POSITIONS_SQL)
    out: list[DBPosition] = []
    for r in rows:
        qty = r["qty"]
        if not isinstance(qty, Decimal):
            qty = Decimal(str(qty))
        out.append(DBPosition(symbol=r["symbol"], side=r["side"], qty=qty))
    return out


class _VenueClientLike(Protocol):
    async def get_user_state(self) -> Any: ...


async def _load_venue_positions(client: _VenueClientLike) -> list[VenuePosition]:
    state = await client.get_user_state()
    out: list[VenuePosition] = []
    for p in getattr(state, "positions", None) or []:
        size = getattr(p, "size", Decimal(0))
        if isinstance(size, str):
            size = Decimal(size)
        if size == 0:
            # HL flat residuals — not a real position, skip per RESEARCH §Q6 dust note.
            continue
        side = "long" if size > 0 else "short"
        symbol = getattr(p, "coin", None) or getattr(p, "symbol", "UNKNOWN")
        out.append(VenuePosition(symbol=symbol, side=side, qty=abs(size)))
    return out


async def _record_audit_row(
    pool: _PoolLike, *, kind: str, payload: dict[str, Any]
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_INSERT_EVENT_SQL, kind, json.dumps(payload))


# ---------------------------------------------------------------------------
# Public entry — reconcile_or_exit
# ---------------------------------------------------------------------------


# Default exit_fn: real systemd-exit. Tests inject a fake.
def _default_exit(code: int) -> int:
    import sys
    sys.exit(code)


async def reconcile_or_exit(
    *,
    pool: _PoolLike,
    alerts: AlertService,
    venue_clients: dict[str, _VenueClientLike],
    exit_fn: Callable[[int], Any] = _default_exit,
) -> int:
    """Run boot reconciliation; pass → return 0, mismatch → exit_fn(1).

    Returns 0 on pass; otherwise calls `exit_fn(1)` and returns 1
    (so callers and tests both see a deterministic int).
    """
    # Single-venue v0.1: load all open DB rows (no venue column yet).
    db_positions = await _load_db_positions(pool)

    # Aggregate venue-side across all registered clients.
    venue_positions: list[VenuePosition] = []
    for name, client in venue_clients.items():
        try:
            venue_positions.extend(await _load_venue_positions(client))
        except Exception as e:  # noqa: BLE001
            # A venue we can't even reach at boot is itself a critical mismatch.
            logger.error("reconcile.venue_load_failed", venue=name, err=str(e))
            await alerts.emit(
                severity=AlertSeverity.CRITICAL,
                kind="boot_reconcile_venue_unreachable",
                venue=name,
                error=str(e),
            )
            await _record_audit_row(
                pool,
                kind="boot_reconcile_venue_unreachable",
                payload={"venue": name, "error": str(e)},
            )
            exit_fn(1)
            return 1

    diff = compute_diff(db=db_positions, venue=venue_positions)

    if diff.is_empty():
        logger.info(
            "reconcile.pass",
            db_count=len(db_positions),
            venue_count=len(venue_positions),
        )
        await _record_audit_row(
            pool,
            kind="boot_reconcile_pass",
            payload={
                "db_count": len(db_positions),
                "venue_count": len(venue_positions),
                "venues": list(venue_clients),
            },
        )
        return 0

    # MISMATCH PATH — alert + audit + exit(1). NEVER calls a kill API.
    diff_payload = diff.to_dict()
    logger.error("reconcile.mismatch", diff=diff_payload)
    await _record_audit_row(
        pool,
        kind="boot_reconcile_mismatch",
        payload=diff_payload,
    )
    await alerts.emit(
        severity=AlertSeverity.CRITICAL,
        kind="boot_reconcile_mismatch",
        db_only=len(diff.db_only),
        venue_only=len(diff.venue_only),
        mismatched=len(diff.mismatched),
        venues=list(venue_clients),
    )
    exit_fn(1)
    return 1


__all__ = [
    "DBPosition",
    "MismatchedQty",
    "PositionDiff",
    "VenuePosition",
    "compute_diff",
    "reconcile_or_exit",
]
