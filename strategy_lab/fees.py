"""
fees.py — Polymarket fee curve + maker rebate model.

THE FORMULA
-----------

    fee = C × feeRate × p × (1 − p)

where:
    C       = number of shares traded
    p       = fill price in [0, 1] (implied probability)
    feeRate = per-market constant (basis-points / 10_000 → fractional rate)

The fee is NOT a flat 7%. The number 0.07 is the `feeRate` for crypto
up-down markets — the actual fee paid per share is `0.07 × p × (1 − p)`,
which peaks at p = 0.5 (effective rate 1.75% of share value) and goes to
zero at p = 0 or p = 1.

WORKED EXAMPLES (crypto, feeRate = 0.07)
----------------------------------------

    p = 0.50, C = 20 shares:    fee = 20 × 0.07 × 0.50 × 0.50 = $0.350
    p = 0.85, C = 20 shares:    fee = 20 × 0.07 × 0.85 × 0.15 = $0.179
    p = 0.95, C = 20 shares:    fee = 20 × 0.07 × 0.95 × 0.05 = $0.067
    p = 0.10, C = 20 shares:    fee = 20 × 0.07 × 0.10 × 0.90 = $0.126

PER-MARKET feeRate
------------------

Polymarket sets feeRate per market via Gamma's `feeSchedule.rate`
(basis-points). Observed values:

    Crypto up-down (BTC/ETH/SOL):    700 bps  →  feeRate = 0.07
    Legacy crypto:                    70 bps  →  feeRate = 0.007
    Non-crypto fee-enabled buckets:  300/400/500 bps → 0.03/0.04/0.05
    Small-cat:                        30/40/50 bps  → 0.003/0.004/0.005

Always look up feeRate from the market's metadata when running on a
non-crypto-up-down universe. Use `feerate_for_market_bps(bps)` as the
conversion helper.

MAKER REBATE (LIMIT FILLS ONLY)
-------------------------------

Makers DO NOT pay a fee — they RECEIVE a rebate equal to a fraction of
the equivalent taker fee:

    maker_rebate = C × feeRate × p × (1 − p) × rebate_share

with `rebate_share = 0.20` for crypto and `0.25` for other fee-enabled
markets. The rebate is INCOME on every limit fill (modeled here as a
negative commission so it adds to PnL).

LEGACY MODEL (DEPRECATED — DO NOT USE)
--------------------------------------

Older `strategy_lab/polymarket_*.py`, `data/v4/canonical/_*.py`, and
`cyclops/conventions.py` files apply the legacy "2% on profit only,
winning leg" approximation (`FEE_RATE = 0.02`). That model is WRONG on
three axes:

    1. wrong rate (real is `feeRate × p × (1 − p)`, NOT flat 2%)
    2. wrong sides (real charges on every fill, not just the winner)
    3. wrong direction (it ignores maker rebates entirely)

Any file using `FEE_RATE = 0.02` produces results that materially
diverge from real Polymarket settlements. Treat their PnL numbers as
historical artifacts only — re-run via `engine_v2.fill_at_book` or the
helpers in this module before quoting any PnL forward.

References
----------
- Polymarket docs: https://docs.polymarket.com/#fees
- Source: prediction_market_extensions/adapters/polymarket/fee_model.py
- Handoff: strategy_lab/reports/EXTERNAL_REPO_COMPARISON_evan_kolberg_pmxt_2026_05_12.md
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Polymarket fee schedule constants (Gamma `feeSchedule.rate` basis-points)
# ---------------------------------------------------------------------------

#: Crypto up-down markets (BTC/ETH/SOL 5m/15m). The default.
DEFAULT_CRYPTO_FEE_BPS: int = 700           # 0.07 as a fractional rate

#: Legacy crypto markets that occasionally show feeSchedule.rate = 70 bps.
LEGACY_CRYPTO_FEE_BPS: int = 70             # 0.007

#: Non-crypto fee-enabled market basis-point buckets observed in Gamma.
OTHER_FEE_ENABLED_BPS: tuple[int, ...] = (30, 40, 50, 300, 400, 500)

#: Maker rebate share — fraction of equivalent taker fee credited back.
CRYPTO_MAKER_REBATE_SHARE: float = 0.20
OTHER_FEE_ENABLED_MAKER_REBATE_SHARE: float = 0.25

#: Asset → category map (used to pick rebate share).
ASSET_CATEGORY: dict[str, str] = {
    "BTC": "crypto",
    "ETH": "crypto",
    "SOL": "crypto",
}


def bps_to_rate(bps: float) -> float:
    """Basis points → fractional rate.

    >>> bps_to_rate(700)
    0.07
    >>> bps_to_rate(70)
    0.007
    >>> bps_to_rate(300)
    0.03
    """
    return float(bps) / 10_000.0


def feerate_for_market_bps(bps: int) -> float:
    """Convert a Gamma `feeSchedule.rate` (bps) to a fractional `feeRate`.

    Convenience for code that pulls market metadata from Gamma. Just
    `bps / 10_000`, with a sanity check on the observed buckets.
    """
    if bps not in {DEFAULT_CRYPTO_FEE_BPS, LEGACY_CRYPTO_FEE_BPS} | set(OTHER_FEE_ENABLED_BPS) | {0}:
        # Unknown bucket — log but don't crash. Convert anyway.
        pass
    return bps_to_rate(bps)


# ---------------------------------------------------------------------------
# Per-fill fee — the canonical formula  fee = C × feeRate × p × (1 − p)
# ---------------------------------------------------------------------------

def poly_fee_per_share(
    price: float,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
) -> float:
    """Per-share fee at fill price `price`.

    Implements the canonical Polymarket formula PER SHARE:

        fee_per_share = feeRate × p × (1 − p)

    The price is clipped to [0, 1]. Returns USD per share. Multiply by
    `shares` (the C in the formula) to get the total fee for the fill —
    or use `poly_fee_usd(price, shares, fee_rate)` directly.

    >>> round(poly_fee_per_share(0.50), 6)
    0.0175
    >>> round(poly_fee_per_share(0.85), 6)
    0.008925
    >>> poly_fee_per_share(1.0)
    0.0
    >>> poly_fee_per_share(0.0)
    0.0
    """
    p = max(0.0, min(1.0, float(price)))
    rate = max(0.0, float(fee_rate))
    return rate * p * (1.0 - p)


def poly_fee_usd(
    price: float,
    shares: float,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
) -> float:
    """Total fee in USD for a fill of `shares` at `price`.

    Implements the canonical formula:

        fee = C × feeRate × p × (1 − p)

    where C = shares, p = price, feeRate = market's fractional rate.

    >>> round(poly_fee_usd(0.50, 20), 4)
    0.35
    >>> round(poly_fee_usd(0.85, 20), 4)
    0.1785
    """
    return float(shares) * poly_fee_per_share(price, fee_rate)


# ---------------------------------------------------------------------------
# Backwards-compatible aliases (taker-side language). The fee paid on a
# TAKER fill equals `poly_fee_usd(...)`. Makers do NOT pay — see rebate
# functions below.
# ---------------------------------------------------------------------------

def poly_taker_fee_per_share(
    price: float,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
) -> float:
    """Per-share fee a TAKER pays. Equals `poly_fee_per_share`."""
    return poly_fee_per_share(price, fee_rate)


def poly_taker_fee_usd(
    price: float,
    shares: float,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
) -> float:
    """Total fee a TAKER pays. Equals `poly_fee_usd`."""
    return poly_fee_usd(price, shares, fee_rate)


# ---------------------------------------------------------------------------
# Maker rebate — credit (INCOME) on every LIMIT fill
# ---------------------------------------------------------------------------

def poly_maker_rebate_per_share(
    price: float,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
    rebate_share: float = CRYPTO_MAKER_REBATE_SHARE,
) -> float:
    """Per-share maker rebate (INCOME) at fill price `price`.

        rebate_per_share = rebate_share × feeRate × p × (1 − p)

    For crypto: rebate_share = 0.20, so the maker receives 20% of what
    the equivalent taker would pay. Makers themselves pay $0 in fees;
    this rebate is pure income on every limit fill.

    >>> round(poly_maker_rebate_per_share(0.85), 6)
    0.001785
    """
    return rebate_share * poly_fee_per_share(price, fee_rate)


def poly_maker_rebate_usd(
    price: float,
    shares: float,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
    rebate_share: float = CRYPTO_MAKER_REBATE_SHARE,
) -> float:
    """Total maker rebate (INCOME, USD) for a LIMIT fill of `shares` at `price`.

        rebate = C × feeRate × p × (1 − p) × rebate_share
    """
    return float(shares) * poly_maker_rebate_per_share(price, fee_rate, rebate_share)


# ---------------------------------------------------------------------------
# Trade economics — what does a 1-share long position cost / pay out?
# ---------------------------------------------------------------------------

def long_payoff_after_fees(
    entry_price: float,
    won: bool,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
) -> float:
    """Per-share P&L holding 1 share of a binary outcome to resolution.

    Entry fee charged at entry. If `won`, settles at $1.00 (no exit fee
    on settlement). If lost, settles at $0.00.

        PnL = settlement − entry_price − poly_fee_per_share(entry_price)

    >>> round(long_payoff_after_fees(0.65, won=True), 4)
    0.3341
    >>> round(long_payoff_after_fees(0.65, won=False), 4)
    -0.6659
    """
    fee = poly_fee_per_share(entry_price, fee_rate)
    payout = 1.0 if won else 0.0
    return payout - float(entry_price) - fee


def breakeven_hit_rate(
    entry_price: float,
    fee_rate: float = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS),
) -> float:
    """Hit rate needed for zero EV at fill price `entry_price`.

        EV = hit × (1 − p − fee(p)) + (1 − hit) × (−p − fee(p)) = 0
        →   hit = p + fee(p)

    >>> round(breakeven_hit_rate(0.69), 4)
    0.7050
    >>> round(breakeven_hit_rate(0.50), 4)
    0.5175
    """
    p = max(0.0, min(1.0, float(entry_price)))
    return p + poly_fee_per_share(p, fee_rate)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    rate = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
    print(f"Polymarket crypto feeRate: {rate} ({DEFAULT_CRYPTO_FEE_BPS} bps)")
    print(f"Formula: fee = C × feeRate × p × (1 − p)")
    print(f"{'p':>5} {'fee/share':>11} {'effective % at p':>17} {'fee on 20 shares':>17}")
    for p in (0.10, 0.30, 0.50, 0.65, 0.69, 0.85, 0.95):
        f = poly_fee_per_share(p)
        eff_pct = (f / max(p, 1e-9)) * 100  # fee as % of share value
        print(f"{p:5.2f} {f:11.5f} {eff_pct:16.3f}% {poly_fee_usd(p, 20):16.4f}")
