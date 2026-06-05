"""Market mapping resolver — (symbol, tf, signal_ts) -> Polymarket condition_id.

Phase 15 Task 3 (D-03). Ports the regex pattern from
``scripts/spike_b/signal_scope.py`` into a reusable async function with
asyncpg pool injection.

READ-ONLY: queries Storedata's ``public.markets`` schema via the
``tradingvenue_ro`` user. NEVER writes (CLAUDE.md invariant #13).

Cache: in-memory dict keyed by ``(symbol_lower, tf, window_start_unix)``
where ``window_start_unix`` is the 5m/15m UTC-aligned boundary that
contains ``signal_ts``. TTL = ``tf_seconds + 30`` so a stale window's
cache entry expires shortly after its bar boundary passes.

Phase 18.1 cache-key fix (2026-04-28): the prior key was ``(sym, tf)``
with 1h TTL. For 5m markets that meant signals from up to 12 distinct
bar boundaries reused the same condition_id, causing fills against
already-resolved markets (operator-found via shadow run; see
SHADOW-RUN-1-FINDINGS bug investigation). Including the window start
in the key forces a fresh resolve at every boundary; the short TTL
cleans up entries shortly after they go stale.

T-15-01 mitigation: strict regex ``^(btc|eth|sol)-updown-(5m|15m)-\\d+$``
rejects any slug not matching the expected updown shape.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    import asyncpg

# Strict slug regex — symbols btc/eth/sol, tf 5m/15m, trailing unix-seconds.
SLUG_REGEX = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-\d+$")

# Cache key now includes the bar-boundary window start so each new bar
# triggers a fresh DB query for its own next-future market.
# Key: (symbol_lower, tf, window_start_unix)
# Value: (condition_id, resolve_unix, cached_at_unix_s)
#   resolve_unix = the cached market's slug-encoded resolve epoch.
#   Strategy-agent suggestion 2026-04-28: also evict on resolve_unix <= now,
#   so a stale market entry never survives past its own resolution even if
#   the TTL hasn't elapsed.
_CACHE: dict[tuple[str, str, int], tuple[str | None, int | None, float]] = {}

# TTL is per-tf so 5m and 15m get appropriately tight expiry. 30s grace
# absorbs minor clock drift between engine + signal_ts derivation.
_TTL_BY_TF: dict[str, int] = {"5m": 5 * 60 + 30, "15m": 15 * 60 + 30}

# Per-tf bar window length used to compute window_start_unix from signal_ts.
_TF_SECONDS: dict[str, int] = {"5m": 5 * 60, "15m": 15 * 60}

Tf = Literal["5m", "15m"]


def slug_matches(slug: str) -> bool:
    """Return True iff slug matches the strict updown pattern."""
    return bool(SLUG_REGEX.match(slug))


def _window_start_unix(signal_ts_unix: int, tf: str) -> int:
    """Floor signal_ts to its containing bar boundary."""
    secs = _TF_SECONDS.get(tf, 60)
    return (signal_ts_unix // secs) * secs


def _slug_resolve_unix(slug: str | None) -> int | None:
    """Extract the unix-epoch tail from an updown slug, e.g.
    'btc-updown-5m-1777419900' → 1777419900. None on parse failure.
    """
    if not slug:
        return None
    try:
        return int(slug.rsplit("-", 1)[-1])
    except (ValueError, AttributeError):
        return None


def _cache_get(
    key: tuple[str, str, int], now: float, ttl_seconds: int
) -> tuple[bool, str | None]:
    """Returns (hit, value). Hit=False means caller must query.

    Two eviction paths:
      1. TTL expired (cached_at + ttl <= now)
      2. Cached market's resolve_unix <= now (strategy-agent suggestion):
         even within TTL, a market past its resolution time is useless —
         hedge can't act, paper executor walks dead snapshots.
    """
    if key not in _CACHE:
        return False, None
    value, resolve_unix, cached_at = _CACHE[key]
    if now - cached_at >= ttl_seconds:
        del _CACHE[key]
        return False, None
    # Evict markets that have crossed their resolve epoch even if TTL is
    # still valid. Belt-and-suspenders against any future cache regression.
    if resolve_unix is not None and resolve_unix <= now:
        del _CACHE[key]
        return False, None
    return True, value


def _cache_put(
    key: tuple[str, str, int],
    value: str | None,
    resolve_unix: int | None,
    now: float,
) -> None:
    _CACHE[key] = (value, resolve_unix, now)


def _clear_cache_for_test() -> None:
    """Test hook — never call from production code."""
    _CACHE.clear()


async def resolve_condition_id(
    pool: "asyncpg.Pool",
    symbol: str,
    tf: Tf,
    signal_ts: datetime,
) -> str | None:
    """Resolve the Polymarket condition_id for the next-expiring updown
    market matching (symbol, tf) at signal_ts.

    Args:
        pool: asyncpg pool connected via tradingvenue_ro (read-only).
        symbol: "BTC" | "ETH" | "SOL" (case-insensitive).
        tf: "5m" | "15m".
        signal_ts: tz-aware UTC timestamp of the signal (bar close).

    Returns:
        condition_id string, or None if no matching active market is found.

    Cache: 1h TTL on (symbol_lower, tf). The end_ts column rotates
    quickly enough that we re-query at most every 3600s.
    """
    sym_lower = symbol.lower()
    if sym_lower not in ("btc", "eth", "sol"):
        return None
    if tf not in ("5m", "15m"):
        return None

    now = time.time()
    signal_unix = int(signal_ts.timestamp())
    win_start = _window_start_unix(signal_unix, tf)
    key = (sym_lower, tf, win_start)
    ttl = _TTL_BY_TF[tf]
    hit, cached = _cache_get(key, now, ttl)
    if hit:
        return cached

    # Read-only SQL: SELECT condition_id from non-archived polymarket markets
    # matching slug regex, with slug-encoded resolve epoch strictly forward
    # of signal_ts, nearest-forward first.
    #
    # Schema reality (verified 2026-04-28 against live VPS2 storedata DB):
    # public.markets has `archived` (bool default false), NOT `active`.
    # `resolve_at`/`expiry_at`/`close_at` columns are all NULL on Polymarket
    # UpDown rows. The only reliable resolution timestamp is the unix-epoch
    # tail of the slug itself (e.g. 'btc-updown-5m-1777419900' resolves at
    # unix 1777419900). substring(slug FROM '\d+$')::bigint extracts it.
    #
    # Use POSIX regex (~) — public.markets.slug is text.
    pattern = f"^{sym_lower}-updown-{tf}-[0-9]+$"
    sql = (
        "SELECT condition_id, slug "
        "FROM public.markets "
        "WHERE platform = 'polymarket' "
        "  AND archived = false "
        "  AND condition_id IS NOT NULL "
        "  AND slug ~ $1 "
        "  AND substring(slug FROM '\\d+$')::bigint > $2 "
        "ORDER BY substring(slug FROM '\\d+$')::bigint ASC "
        "LIMIT 1"
    )
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, pattern, signal_unix)

    condition_id: str | None = row["condition_id"] if row else None
    resolve_unix: int | None = (
        _slug_resolve_unix(row["slug"]) if row else None
    )
    _cache_put(key, condition_id, resolve_unix, now)
    return condition_id


__all__ = [
    "SLUG_REGEX",
    "resolve_condition_id",
    "slug_matches",
]
