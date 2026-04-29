"""
book_walk.py — orderbook-realistic fill simulator for Polymarket CLOB.

Polymarket sizes are in SHARES (number of YES/NO contracts).
USD spent at level i (buying) = price_i * size_i.

book_walk_fill(prices, sizes, notional_usd, side='buy') walks the book
from level 0, accumulating fills until notional is met or book exhausts.
Returns (vwap_price, filled_shares, filled_usd, hit_levels, underfilled).
"""
from __future__ import annotations
from typing import Sequence
import math

EPSILON = 1e-9


def book_walk_fill(
    prices: Sequence[float],
    sizes: Sequence[float],
    notional_usd: float,
    side: str = "buy",
) -> tuple[float, float, float, int, bool]:
    """Walk the book from level 0 and fill up to notional_usd.

    For 'buy' side, prices/sizes should be ASK levels (ascending price).
    For 'sell' side, prices/sizes should be BID levels (descending price).

    Returns:
        vwap_price       — average fill price across all consumed levels
        filled_shares    — total shares acquired (or sold)
        filled_usd       — total USD spent (or received)
        hit_levels       — number of levels touched
        underfilled      — True if book ran out before notional was met
    """
    if notional_usd <= 0:
        return (0.0, 0.0, 0.0, 0, False)

    remaining_usd = float(notional_usd)
    total_usd = 0.0
    total_shares = 0.0
    hit = 0

    for p, s in zip(prices, sizes):
        if p is None or s is None:
            break
        try:
            p = float(p); s = float(s)
        except (TypeError, ValueError):
            break
        if not (math.isfinite(p) and math.isfinite(s)) or s <= 0:
            break
        if p <= 0 or p >= 1:
            # Defensive: Polymarket prices are strictly in (0,1)
            break
        hit += 1
        level_usd_max = p * s
        if level_usd_max >= remaining_usd - EPSILON:
            shares_here = remaining_usd / p
            total_shares += shares_here
            total_usd += remaining_usd
            remaining_usd = 0.0
            break
        # consume entire level
        total_shares += s
        total_usd += level_usd_max
        remaining_usd -= level_usd_max

    underfilled = remaining_usd > EPSILON
    if total_shares <= EPSILON:
        return (0.0, 0.0, 0.0, hit, True)
    vwap = total_usd / total_shares
    return (vwap, total_shares, total_usd, hit, underfilled)


# Smoke test
if __name__ == "__main__":
    # Top-of-book: 100 shares @ $0.50, then 50 @ $0.51, then 200 @ $0.52
    p = [0.50, 0.51, 0.52, 0.53, 0.54]
    s = [100,  50,   200,  500,  1000]

    # $1 stake — fits at top
    print("$1 stake:", book_walk_fill(p, s, 1.0))
    # $25 stake — fits at top (top has $50)
    print("$25 stake:", book_walk_fill(p, s, 25.0))
    # $100 stake — eats top + part of L1
    print("$100 stake:", book_walk_fill(p, s, 100.0))
    # $1000 stake — eats top + L1 + most of L2
    print("$1000 stake:", book_walk_fill(p, s, 1000.0))
    # $100k stake — exhausts book
    print("$100k stake:", book_walk_fill(p, s, 100_000.0))
