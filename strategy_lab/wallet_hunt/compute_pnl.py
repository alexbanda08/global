"""Compute realized PnL per wallet using book-decoded fills + canonical winners.

For each leg (slug, outcome):
  cash_realized = (sell_sz × avg_sell_px) - (buy_sz × avg_buy_px)
  leftover_value = leftover_shares × (1 if leg_won else 0)
  leftover_cost  = avg_buy_px × leftover_shares  (already paid for, sunk)
  net_pnl = cash_realized + leftover_value - leftover_cost_already_in_cash
          = cash_realized + leftover_shares × (won ? 1 : 0) − leftover_shares × avg_buy_px

  Real Polymarket fees on every fill (engine_v2 model):
    entry_fee = buy_sz × 0.07 × avg_buy_px × (1 - avg_buy_px)
    exit_fee  = sell_sz × 0.07 × avg_sell_px × (1 - avg_sell_px)
  Maker fills credit 20% of the fee back (rebate).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions  # noqa: E402
from fees import poly_taker_fee_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS, CRYPTO_MAKER_REBATE_SHARE  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
WALLETS = [
    "0xeebde7a0",
    "0xce25e214",
    "0x89b5cdaa",
    "0xcfb103c3",
    "0x04b6d7e9",
]


def compute_wallet_pnl(short: str, winners: dict) -> dict:
    p = CACHE / short / "fills_book_decoded.parquet"
    if not p.exists():
        return {"short": short, "error": "no fills_book_decoded.parquet"}
    fills = pd.read_parquet(p)
    if fills.empty:
        return {"short": short, "error": "empty"}

    # Per-leg aggregation
    grp = fills.groupby(["slug", "outcome"], as_index=False)
    legs = grp.agg(
        n=("side", "size"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        buy_sz=("size", lambda s: fills.loc[s.index].loc[fills.side == "BUY", "size"].sum()),
        sell_sz=("size", lambda s: fills.loc[s.index].loc[fills.side == "SELL", "size"].sum()),
        avg_buy_px=("price", lambda s: fills.loc[s.index].loc[fills.side == "BUY", "price"].mean()),
        avg_sell_px=("price", lambda s: fills.loc[s.index].loc[fills.side == "SELL", "price"].mean()),
        buy_maker_sz=("size", lambda s: fills.loc[s.index].loc[(fills.side == "BUY") & fills.is_maker, "size"].sum()),
        sell_maker_sz=("size", lambda s: fills.loc[s.index].loc[(fills.side == "SELL") & fills.is_maker, "size"].sum()),
        mc=("mc", "first"),
        mkt_asset=("asset_sym", "first"),
        slot_start_s=("ts_s", "min"),
    )
    legs["leftover"] = legs.buy_sz - legs.sell_sz
    legs["cash_realized"] = legs.sell_sz.fillna(0) * legs.avg_sell_px.fillna(0) - \
                            legs.buy_sz.fillna(0) * legs.avg_buy_px.fillna(0)

    # Winner lookup via condition_id stored in lookup. We have slug only here.
    # Use the canonical resolutions table to find winner per slug.
    legs["winner"] = legs.slug.map(winners)
    legs["resolved"] = legs.winner.notna()
    legs["won"] = legs.resolved & (legs.winner == legs.outcome)

    # Net PnL with realized cash + leftover settlement
    # If leftover > 0 (net long): cash_realized + leftover × (won ? 1 : 0)
    # If leftover < 0 (net short): we have a short position — settles at -1 if won, 0 if lost
    #     But for binary outcomes the "short" is created by minting (CTF split) — modeled as
    #     paying $1 per pair and selling both, net cash + leftover liability
    # Simplification: cash_realized + max(leftover, 0) × payoff − min(leftover, 0) × (1 if our outcome won)
    # Actually for now: PnL = cash_realized + leftover × (1 if won else 0) − max(leftover, 0) × avg_buy_px
    # (this treats positive leftover as held shares, negative leftover as "we got cash from selling pairs we minted")
    def leg_pnl(r):
        if not r.resolved:
            return None
        cash = r.cash_realized
        if r.leftover > 0:
            # Net long, treat as buying at avg_buy_px
            settle = r.leftover * (1.0 if r.won else 0.0)
            cost = r.leftover * (r.avg_buy_px if not np.isnan(r.avg_buy_px) else 0)
            return cash + settle - cost
        elif r.leftover < 0:
            # Net short — assume minted pairs ($1 cost each), need to deliver this side at settlement
            # If our side WON, we owe $1 per share. If lost, we owe $0.
            return cash + r.leftover * (1.0 if r.won else 0.0)
        else:
            return cash

    legs["pnl_gross"] = legs.apply(leg_pnl, axis=1)

    # Fees (Polymarket curve), with maker rebate for the maker-side portion
    def leg_fees(r):
        fee_in = 0.0; fee_out = 0.0
        if r.buy_sz > 0 and not pd.isna(r.avg_buy_px):
            base = r.buy_sz * poly_taker_fee_per_share(r.avg_buy_px, FEE_RATE)
            # Maker share gets 80% off (rebate 20%)
            maker_share = (r.buy_maker_sz / r.buy_sz) if r.buy_sz > 0 else 0
            fee_in = base * (1 - maker_share * CRYPTO_MAKER_REBATE_SHARE)
        if r.sell_sz > 0 and not pd.isna(r.avg_sell_px):
            base = r.sell_sz * poly_taker_fee_per_share(r.avg_sell_px, FEE_RATE)
            maker_share = (r.sell_maker_sz / r.sell_sz) if r.sell_sz > 0 else 0
            fee_out = base * (1 - maker_share * CRYPTO_MAKER_REBATE_SHARE)
        return fee_in + fee_out

    legs["fees"] = legs.apply(leg_fees, axis=1)
    legs["pnl_net"] = legs.pnl_gross - legs.fees

    legs.to_parquet(CACHE / short / "legs_pnl.parquet", index=False)

    # Aggregate
    resolved = legs[legs.resolved]
    return {
        "short": short,
        "n_legs": len(legs),
        "n_resolved": len(resolved),
        "won_pct": round(100 * resolved.won.mean(), 1) if len(resolved) else None,
        "total_volume_usd": round(legs.cash_realized.abs().sum() + legs.buy_sz.fillna(0).sum(), 0),
        "fees_total": round(legs.fees.sum(), 2),
        "pnl_gross_resolved": round(resolved.pnl_gross.sum(), 2),
        "pnl_net_resolved": round(resolved.pnl_net.sum(), 2),
        "pnl_net_per_leg": round(resolved.pnl_net.mean(), 4) if len(resolved) else 0,
        "best_subgroup": None,
    }


def main():
    print("Loading canonical resolutions (winners)...")
    canon = load_resolutions(source="upstream", with_clob_winner=True,
                              assets=["BTC", "ETH", "SOL"], timeframes=["5m", "15m"])
    win_col = "clob_winner" if "clob_winner" in canon.columns else "outcome"
    if win_col == "clob_winner":
        canon[win_col] = canon[win_col].fillna(canon["outcome"])
    winners = canon.set_index("slug")[win_col].to_dict()
    print(f"  loaded {len(winners):,} resolved markets")

    rows = []
    for short in WALLETS:
        r = compute_wallet_pnl(short, winners)
        rows.append(r)
        print(f"  {short}: {r}")

    df = pd.DataFrame(rows)
    df.to_csv(CACHE / "_pnl_summary.csv", index=False)
    print(f"\n=== PnL SUMMARY (1-day chain window, real Poly fees, maker rebates) ===")
    print(df.to_string(index=False))
    print(f"\nsaved -> cache/_pnl_summary.csv")


if __name__ == "__main__":
    main()
