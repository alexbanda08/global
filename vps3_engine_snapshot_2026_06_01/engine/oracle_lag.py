"""Oracle-lag compute module — pure-function join of Chainlink + strategy feed.

Phase 28 Plan 01 (Polymarket sleeve dashboard polyrec-inspired observability).

Purpose
-------
Joins (Chainlink BTC/USD price + ts) with (strategy-feed price + ts) into a
single ``OracleLagSnapshot`` consumed by the Wave 2 ``/sleeves/{id}/oracle-lag``
endpoint and the ``OracleLagTile`` frontend.

For Polymarket UpDown BTC sleeves (the only Phase 28 in-scope sleeve family),
feed source = Binance via ``polymarket_rtds.get_binance_price()``. ETH/SOL
UpDown sleeves (if added) would extend the dispatch table; out of scope for
Phase 28.

Decisions referenced (see ``.planning/phases/28-.../28-CONTEXT.md``)
-------------------------------------------------------------------
- D-01: oracle-lag is the highest-value addition — Chainlink BTC/USD is the
  resolver for Polymarket UpDown markets, so lead/lag is the single most
  predictive pre-resolution signal.
- D-02: reuse existing TV-native plumbing — read from
  ``backend.app.services.polymarket_rtds`` only; NO new external WS
  connections, NO new RPC calls, NO Storedata reads.

Invariants honored
------------------
CLAUDE invariant #13 (TV-native data infra): this module imports ONLY stdlib
and ``polymarket_rtds`` + Pydantic. No ``httpx``, ``asyncpg``, ``web3``, or
``storedata`` access. Pure function: same inputs → same outputs.

v1 limitations
--------------
- ``feed_ts`` is approximated as ``now_s`` because the in-memory Binance
  accessor in ``polymarket_rtds`` does not currently expose a per-tick
  timestamp. Future revisions should plumb a real ``feed_ts`` from the
  Binance/OKX WS ingestor so ``lag_ms`` captures true feed-vs-oracle skew.
- ``stale`` is driven by ``chainlink_age_s`` only. Feed staleness assumes the
  Binance WS connection is healthy; supervised independently via
  ``polymarket_rtds.is_connected()``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from backend.app.services import polymarket_rtds

__all__ = ["OracleLagSnapshot", "compute_oracle_lag"]


# Stale threshold per CONTEXT specifics — either oracle_age_s OR feed_age_s
# above this value marks the snapshot stale and the tile greys out.
_STALE_THRESHOLD_S: float = 5.0


class OracleLagSnapshot(BaseModel):
    """Single point-in-time join of Chainlink oracle + strategy feed.

    Returned by ``compute_oracle_lag``. JSON-serialized as the body of
    ``GET /sleeves/{sleeve_id}/oracle-lag`` in Wave 2.

    Fields
    ------
    oracle_price: Chainlink price for the symbol, ``Decimal`` for precision.
    oracle_ts:    UTC datetime corresponding to the Chainlink push (now -
                  chainlink_age_s).
    feed_price:   Strategy-feed price (Binance for v1).
    feed_ts:      UTC datetime of the feed read (approximated as now in v1 —
                  see module docstring "v1 limitations").
    lag_ms:       Signed feed_ts - oracle_ts in milliseconds. Positive when
                  the feed is ahead of the oracle (typical).
    price_delta_bps: Signed (feed - oracle) / oracle * 10_000.
    stale:        True when either side is older than 5.0s.
    feed_source:  Identifier string for the feed used — "binance" in v1.
    """

    model_config = ConfigDict(frozen=True)

    oracle_price: Decimal
    oracle_ts: datetime
    feed_price: Decimal
    feed_ts: datetime
    lag_ms: int
    price_delta_bps: float
    stale: bool
    feed_source: str


def compute_oracle_lag(
    sym: str,
    sleeve_id: str,
    *,
    now_s: float | None = None,
) -> OracleLagSnapshot | None:
    """Compute oracle-vs-feed lag snapshot for a Polymarket sleeve.

    For Polymarket UpDown BTC sleeves (the only Phase 28 in-scope sleeve
    family), feed source = Binance via ``polymarket_rtds.get_binance_price()``.
    ETH/SOL UpDown sleeves (if added) would extend the dispatch table; out of
    scope for Phase 28.

    See module docstring for the rationale (D-01 + D-02 in
    ``.planning/phases/28-.../28-CONTEXT.md``).

    Parameters
    ----------
    sym:
        Upper-case coin code, e.g. ``"BTC"``. Forwarded to the
        ``polymarket_rtds`` accessors.
    sleeve_id:
        Sleeve identifier (unused in v1 — feed dispatch is Binance-only — but
        kept in the signature so callers can pass it now and the future
        ETH/SOL dispatch can route per-sleeve without an API break).
    now_s:
        Optional injection of ``time.time()`` for deterministic tests.

    Returns
    -------
    ``OracleLagSnapshot`` when all inputs are healthy, else ``None`` if any of:
      - Chainlink price missing for the symbol
      - Chainlink age unavailable for the symbol
      - Binance price missing for the symbol
      - Binance price ``<= 0`` (guard against div-by-zero)

    The caller (Wave 2 endpoint) translates ``None`` into a 503 response.
    """
    # Reference sleeve_id so static-analysis doesn't flag the unused param.
    # ETH/SOL dispatch will key off it in a future phase.
    _ = sleeve_id

    if now_s is None:
        now_s = time.time()

    coin = sym.upper()

    oracle_price_f = polymarket_rtds.get_chainlink_price(coin)
    oracle_age_s = polymarket_rtds.get_chainlink_age_s(coin)
    if oracle_price_f is None or oracle_age_s is None:
        return None

    feed_price_f = polymarket_rtds.get_binance_price(coin)
    if feed_price_f is None or feed_price_f <= 0:
        return None

    # Decimal arithmetic for the bps calc — float drift on small deltas at
    # 65k price magnitudes burns precision quickly.
    oracle_price = Decimal(str(oracle_price_f))
    feed_price = Decimal(str(feed_price_f))

    oracle_ts = datetime.fromtimestamp(now_s - oracle_age_s, tz=UTC)
    # v1 limitation: feed_ts approximated as now — see module docstring.
    feed_ts = datetime.fromtimestamp(now_s, tz=UTC)

    lag_ms = int((feed_ts - oracle_ts).total_seconds() * 1000)

    price_delta_bps = float(
        (feed_price - oracle_price) / oracle_price * Decimal(10_000)
    )

    stale = oracle_age_s > _STALE_THRESHOLD_S

    return OracleLagSnapshot(
        oracle_price=oracle_price,
        oracle_ts=oracle_ts,
        feed_price=feed_price,
        feed_ts=feed_ts,
        lag_ms=lag_ms,
        price_delta_bps=price_delta_bps,
        stale=stale,
        feed_source="binance",
    )
