"""Anchored 15m VWAP cache for the VWAP continuation strategy (Phase 35).

Per ``strategy_lab/reports/TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`` §3.2:

Maintains a per-asset rolling 16-min deque of 1s ``(ts_us, close, vol)`` tuples
and exposes the volume-weighted average price ANCHORED at the start of the
current 15-minute UTC bucket. The bucket boundary is on 900-second multiples
of the unix epoch (00:00, 00:15, 00:30, ...).

INVARIANT: anchored VWAP resets exactly at each 15m boundary. The deque keeps
16 minutes of history so that a fire at offset 900s into a new bucket still
has the previous bucket's tail bars available for forensic queries (none of
the read APIs cross-bucket, but the buffer makes it cheap to add that later).

CLAUDE.md inv #4: pure helpers — push() and the read APIs are O(window_size),
no IO, no time.time(). The CALLER (BinanceMarketDataFeed kline handler) is
responsible for the wall-clock timestamps via Binance's kline close_time.
"""
from __future__ import annotations

import math
from collections import deque

__all__ = ["Vwap15mStore"]


class Vwap15mStore:
    """Per-asset rolling 1s deque + anchored 15m VWAP / deviation queries.

    Args:
        max_bars: deque maxlen per asset. Default 960 = 16 minutes of 1s bars.
            Slightly more than one full 15m bucket so warmup straddling a
            boundary always has data.
    """

    _BUCKET_US = 900 * 1_000_000  # 15 minutes in microseconds

    def __init__(self, max_bars: int = 960) -> None:
        self.bars: dict[str, deque] = {}
        self.max_bars = max_bars

    def push(
        self,
        asset: str,
        ts_us: int,
        close: float,
        vol: float,
        taker_buy_quote: float = 0.0,
        quote_volume: float = 0.0,
    ) -> None:
        """Append one 1s bar. Caller MUST pass bar-close timestamps in
        microseconds (Binance ``k.T`` field). Bars MUST arrive in roughly
        chronological order — we don't sort here.

        ``taker_buy_quote`` (binance ``k.Q``) + ``quote_volume`` (``k.q``)
        are stored for Phase 36 CVD compute. Both default to 0 so callers
        outside the Phase 35 1s path (tests, legacy fixtures) don't break.
        """
        d = self.bars.get(asset)
        if d is None:
            d = deque(maxlen=self.max_bars)
            self.bars[asset] = d
        d.append((
            int(ts_us),
            float(close),
            float(vol),
            float(taker_buy_quote),
            float(quote_volume),
        ))

    def vwap_at(self, asset: str, anchor_us: int) -> float | None:
        """Anchored VWAP since the start of the 15m UTC bucket containing
        ``anchor_us``. Returns None when the bucket has zero summed volume
        OR no bars exist for ``asset``.

        Walks the deque oldest→newest skipping bars before the bucket start
        and breaking once we cross ``anchor_us``. O(900) walk per call.
        """
        d = self.bars.get(asset)
        if not d:
            return None
        bucket_start_us = (anchor_us // self._BUCKET_US) * self._BUCKET_US
        cum_px_vol = 0.0
        cum_vol = 0.0
        for entry in d:
            ts_us, close, vol = entry[0], entry[1], entry[2]
            if ts_us < bucket_start_us:
                continue
            if ts_us > anchor_us:
                break
            cum_px_vol += close * vol
            cum_vol += vol
        if cum_vol <= 0:
            return None
        return cum_px_vol / cum_vol

    def dev_bps_at(self, asset: str, anchor_us: int) -> float | None:
        """Deviation of the latest 1s close (at-or-before ``anchor_us``) from
        the anchored VWAP, expressed in basis points.

        ``dev_bps = 10000 * ln(close_now / vwap_15m_anchored)``

        Returns None when VWAP is None, no close found, or close <= 0.
        Positive = price above VWAP (UP direction). Negative = price below
        VWAP (DOWN direction). The strategy reads sign + magnitude.
        """
        d = self.bars.get(asset)
        if not d:
            return None
        close_now: float | None = None
        for entry in reversed(d):
            ts_us, close = entry[0], entry[1]
            if ts_us <= anchor_us:
                close_now = close
                break
        if close_now is None or close_now <= 0:
            return None
        vwap = self.vwap_at(asset, anchor_us)
        if vwap is None or vwap <= 0:
            return None
        return 10000.0 * math.log(close_now / vwap)
