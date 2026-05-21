"""Per-trade settlement on the chainlink-derived outcome.

Phase 1 uses the LEGACY Polymarket fee model: 2% on the winning-leg profit
only, no fee on losses. The engine_v2 real fee curve (0.07 * p * (1-p) per
share on EVERY fill) is opt-in for later phases — see CLAUDE.md.

Inputs to `settle_legacy()` come from `book_walk_fill`:
    vwap   — average price across consumed levels
    shares — total shares acquired (capped by notional)
    usd    — total USD spent
"""

from __future__ import annotations

from ..conventions import FEE_RATE


def settle_legacy(won: bool, shares: float, usd: float, fee_rate: float = FEE_RATE) -> float:
    """Return per-trade PnL in USD.

    Win  → payout = shares * $1.00; profit = payout - usd; fee = fee_rate * profit;
           pnl = profit - fee  (fee only applied when profit > 0)
    Lose → pnl = -usd
    """
    if shares <= 0 or usd <= 0:
        return 0.0
    if not won:
        return -float(usd)
    payout = float(shares) * 1.0  # binary market: winning share pays $1
    profit = payout - float(usd)
    if profit > 0:
        profit -= fee_rate * profit
    return profit
