"""Polymarket orderbook microstructure metrics (Phase 28 — polyrec-inspired).

Pure functions over BookMirror snapshot dicts. NO I/O — caller passes the
snapshot in and gets a metrics dict back. Five metrics frozen by CONTEXT D-03:
  microprice, imbalance_L5, slope, eat_flow, spread_bps.

Per CLAUDE inv #13: pure compute on TV-native BookMirror data (Phase 18.6/26.3).
NO Storedata reads. NO new WS connections. NO strategy consumption (D-07
defers wiring into entry/sizing logic to a future phase).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from pydantic import BaseModel


class BookHealthSnapshot(BaseModel):
    """Five metrics for one token's book at a point in time."""

    microprice: float  # mid-like, sized-weighted
    imbalance_l5: float  # in [-1, 1]; positive = buy pressure
    slope: float  # signed depth-weighted price gradient
    eat_flow: float  # rolling sum of top-of-book trade size (last 30s)
    spread_bps: float  # (ask - bid) / mid * 1e4
    best_bid: float
    best_ask: float
    bid_depth_l5: float  # sum of size at top 5 bid levels
    ask_depth_l5: float  # sum of size at top 5 ask levels
    as_of_ms: int  # snapshot timestamp passthrough


def _to_decimal(s: str | float | int) -> Decimal:
    return Decimal(str(s))


def compute_microprice(bids: list[dict], asks: list[dict]) -> float | None:
    """Size-weighted mid. Returns None if either side is empty or denom is zero.

    Formula (CONTEXT D-03):
        microprice = (best_bid_px * best_ask_size + best_ask_px * best_bid_size)
                     / (best_bid_size + best_ask_size)

    Mathematically bounded by [best_bid, best_ask] when best_bid <= best_ask
    and both sizes are non-negative.
    """
    if not bids or not asks:
        return None
    bb_px = _to_decimal(bids[0]["price"])
    bb_sz = _to_decimal(bids[0]["size"])
    ba_px = _to_decimal(asks[0]["price"])
    ba_sz = _to_decimal(asks[0]["size"])
    denom = bb_sz + ba_sz
    if denom == 0:
        return None
    return float((bb_px * ba_sz + ba_px * bb_sz) / denom)


def compute_imbalance_l5(bids: list[dict], asks: list[dict]) -> float | None:
    """L5 size imbalance. Returns None if either side is empty or total is zero.

    Formula (CONTEXT D-03):
        imbalance_L5 = (sum bid_size[0..4] - sum ask_size[0..4])
                       / (sum bid_size[0..4] + sum ask_size[0..4])

    Bounded by [-1.0, 1.0] for any non-empty book with non-negative sizes.
    """
    if not bids or not asks:
        return None
    bid_sz = sum((_to_decimal(b["size"]) for b in bids[:5]), Decimal("0"))
    ask_sz = sum((_to_decimal(a["size"]) for a in asks[:5]), Decimal("0"))
    total = bid_sz + ask_sz
    if total == 0:
        return None
    return float((bid_sz - ask_sz) / total)


def compute_slope(bids: list[dict], asks: list[dict]) -> float | None:
    """Signed depth-weighted price gradient across L5.

    Implementation (Claude's discretion per CONTEXT D-03): simple
    Delta-price/Delta-depth. For each side, compute
    (last_level_price - best_price) / sum(size); signed so positive slope
    means asks rise faster than bids fall (sell-side pressure).

    Returns net_slope = ask_slope - bid_slope. None if either side has <2 levels
    or zero depth.
    """
    if len(bids) < 2 or len(asks) < 2:
        return None
    bid_levels = bids[:5]
    ask_levels = asks[:5]
    bid_depth = sum((_to_decimal(b["size"]) for b in bid_levels), Decimal("0"))
    ask_depth = sum((_to_decimal(a["size"]) for a in ask_levels), Decimal("0"))
    if bid_depth == 0 or ask_depth == 0:
        return None
    bid_slope = (
        _to_decimal(bid_levels[0]["price"]) - _to_decimal(bid_levels[-1]["price"])
    ) / bid_depth
    ask_slope = (
        _to_decimal(ask_levels[-1]["price"]) - _to_decimal(ask_levels[0]["price"])
    ) / ask_depth
    return float(ask_slope - bid_slope)


def compute_eat_flow(
    trades: Iterable[tuple[int, float]],
    *,
    now_ms: int,
    window_s: int = 30,
) -> float:
    """Rolling sum of trade sizes in the last ``window_s`` seconds.

    Args:
        trades: iterable of (ts_ms, size) tuples — caller supplies a deque
                bounded by maxlen ~= window_s * expected-tps.
        now_ms: current time in ms (injectable for tests).
        window_s: rolling window in seconds (default 30 per CONTEXT D-03).

    Pure function — no I/O. The deque ownership lives in the endpoint layer.
    """
    cutoff_ms = now_ms - (window_s * 1000)
    return float(sum(size for ts_ms, size in trades if ts_ms >= cutoff_ms))


def compute_spread_bps(bids: list[dict], asks: list[dict]) -> float | None:
    """Top-of-book spread in basis points.

    Formula (CONTEXT D-03):
        spread_bps = (best_ask - best_bid) / mid * 10_000
        mid = (best_ask + best_bid) / 2

    Returns None if either side is empty or mid is zero. For a non-crossed
    book (best_ask >= best_bid) the return value is non-negative.
    """
    if not bids or not asks:
        return None
    bb = _to_decimal(bids[0]["price"])
    ba = _to_decimal(asks[0]["price"])
    mid = (bb + ba) / Decimal("2")
    if mid == 0:
        return None
    return float((ba - bb) / mid * Decimal("10000"))


def compute_book_health(
    snapshot: dict | None,
    *,
    trades: Iterable[tuple[int, float]] | None = None,
    now_ms: int | None = None,
) -> BookHealthSnapshot | None:
    """Aggregate all 5 metrics from a BookMirror snapshot.

    Returns None when:
      - snapshot is None (token not subscribed)
      - either side is empty (no liquidity)
      - microprice/imbalance/spread degenerate

    Args:
        snapshot: BookMirror.get(token_id) return shape; ``None`` allowed.
        trades: rolling deque/list of (ts_ms, size) for eat_flow; if None,
            eat_flow=0.0.
        now_ms: current time in ms; if None, falls back to snapshot["ts"].
    """
    if snapshot is None:
        return None
    bids = snapshot.get("bids") or []
    asks = snapshot.get("asks") or []
    if not bids or not asks:
        return None
    mp = compute_microprice(bids, asks)
    imb = compute_imbalance_l5(bids, asks)
    spr = compute_spread_bps(bids, asks)
    slp = compute_slope(bids, asks)
    if mp is None or imb is None or spr is None:
        return None
    eat = 0.0
    if trades is not None:
        eat = compute_eat_flow(
            trades,
            now_ms=now_ms if now_ms is not None else int(snapshot.get("ts", 0)),
        )
    bid_depth_l5 = float(
        sum((_to_decimal(b["size"]) for b in bids[:5]), Decimal("0"))
    )
    ask_depth_l5 = float(
        sum((_to_decimal(a["size"]) for a in asks[:5]), Decimal("0"))
    )
    # 2026-05-20 — book_mirror.py writes ``snapshot["ts"]`` in
    # **seconds** (``int(time.time())`` at book_mirror.py:466/513). The
    # ``as_of_ms`` field name + frontend staleness check
    # (``now_ms - as_of_ms > 5000``) require **milliseconds**, so convert
    # here. Without × 1000 the stale flag latches True forever
    # (diff ≈ 1.78e12). Flipping book_mirror.py to ms would ripple to 5
    # other consumers (controllers/polymarket_updown.py, client.py,
    # paper.py × 3 sites, plus tests), so the unit conversion is
    # localised at this single boundary.
    as_of_seconds = int(snapshot.get("ts", 0))
    return BookHealthSnapshot(
        microprice=mp,
        imbalance_l5=imb,
        slope=slp if slp is not None else 0.0,
        eat_flow=eat,
        spread_bps=spr,
        best_bid=float(_to_decimal(bids[0]["price"])),
        best_ask=float(_to_decimal(asks[0]["price"])),
        bid_depth_l5=bid_depth_l5,
        ask_depth_l5=ask_depth_l5,
        as_of_ms=as_of_seconds * 1000,
    )


__all__ = [
    "BookHealthSnapshot",
    "compute_microprice",
    "compute_imbalance_l5",
    "compute_slope",
    "compute_eat_flow",
    "compute_spread_bps",
    "compute_book_health",
]
