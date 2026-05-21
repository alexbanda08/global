"""Compare wallet-fire conditions to our scanner conditions.

The question: our backtest shows all 6 cells losing money at $200 notional,
yet 4 wallets we decoded make $281–$344k/day. Why?

Hypotheses to test against fires_decoded.parquet for each wallet:
  H1. Wallets fire at LOWER sum_asks (~$1.005-1.015) than our scanner's
      effective $1.035 threshold (the maker-fee bug)
  H2. Wallets fire on MORE BALANCED markets (own_ask ≈ opp_ask, both near $0.50)
      whereas our scanner gets pulled toward asymmetric high-edge fires
  H3. When wallets hold a leg (sell-and-redeem), they hold the CHEAP side
      (low cost basis after sell), which makes their held_win_rate of even
      ~20-30% still positive-EV
  H4. Pure mint-and-sell wallets get their PnL almost entirely from BOTH-leg fires;
      sell-and-redeem wallets get it from holding cheap side after selling expensive

For each wallet, compute:
  - sum_asks distribution at fire (compare to scanner's $1.035+ filter)
  - own_ask / opp_ask distribution (asymmetry profile)
  - Per-slug fire-leg count → classify event as PURE-BOTH-SOLD or HYBRID-ONE-SOLD
  - For HYBRID events: held_side = opposite(wallet_side); held_won = (outcome == held_side)
  - Empirical EV per fire under their actual conditions
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))
from fees import poly_maker_rebate_per_share, poly_taker_fee_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)

WALLETS = {
    "0xeebde7a0": "$344k/day — mostly pure-MS (65% both-sides per handoff)",
    "0x04b6d7e9": "$212k/day — mostly hybrid (74% only-SELL per handoff)",
    "0x89b5cdaa": "$10k/day — pure hybrid (100% only-SELL per handoff)",
    "0xf7f0b0b1": "$281/day — small scale",
}


def analyze_wallet(short: str, label: str) -> dict:
    cache = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / short
    fires_p = cache / "fires_decoded.parquet"
    if not fires_p.exists():
        print(f"  SKIP {short}: no fires_decoded.parquet")
        return None
    fires = pd.read_parquet(fires_p)
    print(f"\n=== {short}  {label}")
    print(f"  total fires loaded: {len(fires):,}")

    # Clean: drop fires where own_ask or opp_ask missing
    f = fires.dropna(subset=["own_ask", "opp_ask", "outcome", "wallet_side"]).copy()
    print(f"  with own_ask + opp_ask + outcome: {len(f):,}")
    if len(f) == 0:
        return None

    f["sum_asks"] = f.own_ask.astype(float) + f.opp_ask.astype(float)
    f["edge_per_share"] = f.sum_asks - 1.0

    # sum_asks distribution at fire
    print(f"\n  sum_asks distribution at fire:")
    print(f"    median = {f.sum_asks.median():.4f}")
    print(f"    p25    = {f.sum_asks.quantile(0.25):.4f}")
    print(f"    p75    = {f.sum_asks.quantile(0.75):.4f}")
    print(f"    p10    = {f.sum_asks.quantile(0.10):.4f}")
    print(f"    p90    = {f.sum_asks.quantile(0.90):.4f}")
    print(f"    %sum<$1.005:  {100*(f.sum_asks < 1.005).mean():.1f}%")
    print(f"    %sum [1.005,1.020]: {100*((f.sum_asks >= 1.005) & (f.sum_asks <= 1.020)).mean():.1f}%")
    print(f"    %sum [1.020,1.035]: {100*((f.sum_asks > 1.020) & (f.sum_asks <= 1.035)).mean():.1f}%")
    print(f"    %sum >1.035 (our scanner gate): {100*(f.sum_asks > 1.035).mean():.1f}%")

    # own_ask asymmetry
    print(f"\n  own_ask distribution:")
    print(f"    median own_ask = {f.own_ask.median():.4f}")
    print(f"    median |own - 0.5| = {(f.own_ask - 0.5).abs().median():.4f}  (lower=more balanced)")

    # Group fires by SLUG — each slug is a unique 5m or 15m market window,
    # so all fires on a slug are part of the same mint-and-sell event.
    # If wallet sold BOTH sides on a slug → PURE both-sold
    # If wallet sold ONLY one side → HYBRID (held opposite)
    grp = f.groupby("slug").agg(
        n_legs=("wallet_side", "count"),
        sides=("wallet_side", lambda x: tuple(sorted(set(x)))),
        n_unique_sides=("wallet_side", "nunique"),
        first_ts=("ts_us", "min"),
        outcome=("outcome", "first"),
        wallet_side_first=("wallet_side", "first"),
        own_ask_mean=("own_ask", "mean"),
        opp_ask_mean=("opp_ask", "mean"),
        sum_asks_mean=("sum_asks", "mean"),
    ).reset_index()

    n_total = len(grp)
    pure = grp[grp.n_unique_sides == 2]
    only_up = grp[(grp.n_unique_sides == 1) & (grp.wallet_side_first == "Up")]
    only_dn = grp[(grp.n_unique_sides == 1) & (grp.wallet_side_first == "Down")]
    n_pure = len(pure); n_only_up = len(only_up); n_only_dn = len(only_dn)

    print(f"\n  event classification (slug+60s-bucket):")
    print(f"    total events:     {n_total:,}")
    print(f"    PURE both-sold:   {n_pure:,} ({100*n_pure/n_total:.1f}%)")
    print(f"    HYBRID only-Up:   {n_only_up:,} ({100*n_only_up/n_total:.1f}%) — held Down")
    print(f"    HYBRID only-Dn:   {n_only_dn:,} ({100*n_only_dn/n_total:.1f}%) — held Up")

    # held_win_rate for HYBRID events
    hybrid = pd.concat([only_up, only_dn], ignore_index=True)
    hybrid["held_side"] = hybrid.wallet_side_first.map(lambda s: "Down" if s == "Up" else "Up")
    hybrid["held_won"] = hybrid.held_side == hybrid.outcome
    if len(hybrid):
        hwr = hybrid.held_won.mean()
        print(f"\n  HYBRID events held-side outcome (n={len(hybrid):,}):")
        print(f"    held_win_rate = {hwr*100:.1f}%")
        # Held side cost basis = 1 - own_ask (we minted at $1, sold own side at own_ask)
        hybrid["cost_basis_held"] = 1.0 - hybrid.own_ask_mean
        print(f"    median cost basis on held leg: ${hybrid.cost_basis_held.median():.4f}")
        print(f"    p25 cost basis: ${hybrid.cost_basis_held.quantile(0.25):.4f}")
        print(f"    p75 cost basis: ${hybrid.cost_basis_held.quantile(0.75):.4f}")

        # Per-share EV on HYBRID events at observed held_WR
        # ev_per_share = own_ask + held_WR × $1 - $1 = own_ask - 1 + held_WR
        hybrid["ev_per_share"] = hybrid.own_ask_mean + hwr - 1.0
        print(f"    mean per-share EV (using empirical held_WR): ${hybrid.ev_per_share.mean():.4f}")
        # At $200 notional → $200 shares
        print(f"    → at $200 notional: ${hybrid.ev_per_share.mean() * 200:.2f}/event mean")
    else:
        hwr = float("nan")

    # PURE events PnL: sum_asks - 1 + 2x maker rebate (both legs filled)
    if len(pure):
        pure["pnl_per_share"] = (
            pure.own_ask_mean + pure.opp_ask_mean - 1.0
            + pure.own_ask_mean.apply(lambda p: poly_maker_rebate_per_share(p, FEE_RATE))
            + pure.opp_ask_mean.apply(lambda p: poly_maker_rebate_per_share(p, FEE_RATE))
        )
        print(f"\n  PURE both-sold events PnL (n={len(pure):,}):")
        print(f"    mean per-share = ${pure.pnl_per_share.mean():.4f}")
        print(f"    → at $200 notional: ${pure.pnl_per_share.mean() * 200:.2f}/event mean")

    # Aggregate: estimate wallet's blended PnL/event
    pure_pnl = pure.pnl_per_share.mean() * 200 if len(pure) else 0
    hybrid_pnl = hybrid.ev_per_share.mean() * 200 if len(hybrid) else 0
    blended = (n_pure * pure_pnl + len(hybrid) * hybrid_pnl) / max(n_total, 1)
    print(f"\n  BLENDED per-event PnL (at $200 notional, weighted): ${blended:.4f}")
    # Wallet sample span
    span_s = (f.ts_us.max() - f.ts_us.min()) / 1_000_000
    span_d = span_s / 86400
    events_per_day = n_total / max(span_d, 0.1)
    print(f"  fire span: {span_d:.2f} days  →  {events_per_day:.1f} events/day")
    print(f"  → projected $/day @ $200 notional: ${blended * events_per_day:.2f}")

    return dict(
        wallet=short, n_total_events=n_total, pct_pure=100 * n_pure / n_total,
        pct_hybrid=100 * (len(hybrid)) / n_total,
        held_wr=hwr, sum_asks_median=float(f.sum_asks.median()),
        pure_pnl_per_event=pure_pnl, hybrid_pnl_per_event=hybrid_pnl,
        blended_pnl_per_event=blended, events_per_day=events_per_day,
        projected_dollars_per_day=blended * events_per_day,
    )


def main():
    rows = []
    for short, label in WALLETS.items():
        r = analyze_wallet(short, label)
        if r is not None:
            rows.append(r)
    print("\n\n=========== SUMMARY ===========")
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))

    print("\n\n=== vs our scanner ===")
    print("Our scanner fires at sum_asks > $1.035 effectively (maker-fee bug subtracts phantom fees).")
    print("Scanner sample shows BOTH=33-48%, HYBRID held_WR=17-29%, all 6 cells negative.")
    print("Compare each wallet's row above.")


if __name__ == "__main__":
    main()
