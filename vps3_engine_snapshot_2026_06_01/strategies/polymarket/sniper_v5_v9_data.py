"""V9 in-memory trade buffer (TV-native, 2026-05-29).

Replaces the old Storedata-parquet path. A dedicated ``TradeMirror`` (CLOB
``trades`` WS) pushes every ``TradePrint`` here via ``on_trade_print``; the
sniper-v5 B1/B2/B3 gates read ``get_asset_trades(asset)`` synchronously at fire
time. Nothing is persisted — Storedata keeps the long-tail archive (CLAUDE.md
inv #13: TV owns its own LIVE data; this is the realtime hot path).

A2 ``hl_short_proxy`` returns None until the Binance-futures liquidation feed
lands (see design doc "Out of scope").
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from backend.app.strategies.polymarket.maker.types import TradePrint

logger = structlog.get_logger(__name__)

_ASSETS = ("btc", "eth", "sol")
#: Hard cap per asset (defensive; TTL is the primary bound).
_MAX_PRINTS_PER_ASSET = 50_000


@dataclass
class V9DataStore:
    """In-memory rolling per-asset trade buffer for V9 flow gates."""

    ttl_s: int = 1800
    # A2 cascade proxy source — TV-native CEX liquidation feed (OKX/Bybit/
    # Gate/Bitget), replacing the frozen HL hl-s3-fills source. None until
    # wired in the engine lifespan (gate then degrades to no-fire).
    cex_liq_feed: Any = None
    liq_window_s: int = 600
    # Which liquidation-order side is the bullish "short cascade" (forced buys
    # closing shorts). Per the feed's "order side on the book" convention this
    # is "buy". Flip to "sell" if shadow outcome-validation shows it inverted.
    short_liq_side: str = "buy"
    _buf: dict[str, deque] = field(default_factory=lambda: defaultdict(
        lambda: deque(maxlen=_MAX_PRINTS_PER_ASSET)
    ))
    _df_cache: dict[str, Any] = field(default_factory=dict)
    _dirty: dict[str, bool] = field(default_factory=lambda: defaultdict(lambda: True))
    n_prints: int = 0

    def on_trade_print(self, tp: "TradePrint") -> None:
        """Append one trade print. Routed to its asset by slug prefix."""
        slug = tp.slug
        asset = slug.split("-", 1)[0].lower()
        if asset not in _ASSETS:
            return
        outcome = "Up" if tp.side == "up" else "Down"
        try:
            size = float(tp.size)
        except (TypeError, ValueError):
            return
        self._buf[asset].append((int(tp.ts_us), slug, outcome, tp.aggressor, size))
        self._dirty[asset] = True
        self.n_prints += 1

    def get_asset_trades(self, asset: str) -> Any:
        """DataFrame (timestamp_us, slug, outcome, side, size) of prints within
        ``ttl_s`` of the newest buffered print. Empty df when no prints."""
        import pandas as pd  # noqa: PLC0415

        key = asset.lower()
        dq = self._buf.get(key)
        cols = ["timestamp_us", "slug", "outcome", "side", "size"]
        if not dq:
            return pd.DataFrame(columns=cols)
        newest = dq[-1][0]
        cutoff = newest - self.ttl_s * 1_000_000
        while dq and dq[0][0] < cutoff:
            dq.popleft()
            self._dirty[key] = True
        if self._dirty.get(key, True) or key not in self._df_cache:
            self._df_cache[key] = pd.DataFrame(list(dq), columns=cols)
            self._dirty[key] = False
        return self._df_cache[key]

    def get_hl_short_proxy(self) -> Any:
        """Short-liquidation cascade proxy for the A2 gate, built from the CEX
        liquidation feed. Columns: ``coin``, ``time_exchange_us`` (µs),
        ``notional`` — the schema the A2 gate filters (coin==asset_coin) and
        sums over its window. Filtered to short liquidations (``short_liq_side``,
        forced buys). Returns None when no feed is wired (gate → no fire);
        empty DataFrame when the window holds no short-liqs."""
        feed = self.cex_liq_feed
        if feed is None:
            return None
        import time  # noqa: PLC0415

        import pandas as pd  # noqa: PLC0415

        cols = ["coin", "time_exchange_us", "notional"]
        cutoff_ms = time.time() * 1000.0 - self.liq_window_s * 1000.0
        rows = []
        for e in feed.since(cutoff_ms):
            if e.side != self.short_liq_side:
                continue
            sym = e.symbol
            coin = sym.split("_PERP_")[-1].split("_")[0] if "_PERP_" in sym else sym
            rows.append((coin, int(e.ts_ms) * 1000, float(e.notional_usd)))
        return pd.DataFrame(rows, columns=cols)


__all__ = ["V9DataStore"]
