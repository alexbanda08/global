"""PolymarketMarketDataFeed — bar-boundary REST orderbook polling.

Phase 14 Task 8. WS subscription deferred (see R-14-01 in SUMMARY).
5m/15m cadence is plenty for the Phase 15 updown strategies.

CLAUDE.md invariant #3: BarEngine must wait 3-5s past bar close before
reading. This feed enforces that delay via asyncio.sleep so consumers
don't need to re-implement the look-ahead guard.

Pitfall 3 (neg_risk) — exposed via fetch_market_info.
Pitfall 4 (tick_size mutable) — fetch_tick_size is called per-order
and NEVER cached at module import.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from backend.app.venues.polymarket.models import Market, OrderbookSnapshot

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.venues.polymarket.client import PolymarketClient

log = structlog.get_logger("backend.app.venues.polymarket.market_data")

# Seconds past bar-close before we read — CLAUDE.md inv #3.
LOOK_AHEAD_GUARD_SECONDS = 5


class PolymarketMarketDataFeed:
    """REST-only bar-boundary market-data feed for Poly V2."""

    def __init__(
        self,
        client: "PolymarketClient",
        bar_interval_seconds: int = 300,
    ) -> None:
        self.client = client
        self.bar_interval_seconds = bar_interval_seconds

    async def snapshot_at_bar_close(
        self,
        token_id: int,
        bar_close_ts: int,
    ) -> OrderbookSnapshot:
        """Wait 3-5s past bar close (CLAUDE.md inv #3), then snapshot.

        Returns OrderbookSnapshot with canonical `timestamp=bar_close_ts`
        so downstream consumers see the intended bar, not wall-clock.
        """
        await asyncio.sleep(LOOK_AHEAD_GUARD_SECONDS)
        snap = await self.client.get_orderbook_snapshot(token_id)
        # Canonicalize timestamp to bar_close so strategies see the
        # intended bar boundary (not the wall-clock fetch time).
        return OrderbookSnapshot(
            market=snap.market,
            asset_id=snap.asset_id,
            bids=snap.bids,
            asks=snap.asks,
            timestamp=bar_close_ts,
            hash=snap.hash,
        )

    async def fetch_tick_size(self, token_id: int) -> Decimal:
        """Fetch tick_size per-call — NEVER cached (Pitfall 4)."""
        clob = self.client._clob
        if clob is None:
            # Paper mode / not built — return default.
            return Decimal("0.01")
        raw = await asyncio.to_thread(clob.get_tick_size, str(token_id))
        return Decimal(str(raw))

    async def fetch_market_info(self, condition_id: str) -> Market:
        """Fetch market metadata including neg_risk flag (Pitfall 3)."""
        clob = self.client._clob
        if clob is None:
            # Paper mode — return placeholder with neg_risk=False.
            return Market(
                condition_id=condition_id,
                question_id="",
                minimum_tick_size=Decimal("0.01"),
                minimum_order_size=Decimal("5"),
                neg_risk=False,
            )
        raw = await asyncio.to_thread(clob.get_market, condition_id)
        return Market(
            condition_id=str(raw.get("condition_id", condition_id)),
            question_id=str(raw.get("question_id", "")),
            minimum_tick_size=Decimal(
                str(raw.get("minimum_tick_size", "0.01"))
            ),
            minimum_order_size=Decimal(
                str(raw.get("minimum_order_size", "5"))
            ),
            neg_risk=bool(raw.get("neg_risk", False)),
        )


__all__ = ["PolymarketMarketDataFeed", "LOOK_AHEAD_GUARD_SECONDS"]
