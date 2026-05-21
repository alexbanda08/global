"""Inspect wallet fire sizing — shares per fill, notional per fill, fires per slug.

Tests hypothesis: wallets re-quote many small fires per slug to compound
BOTH-fills while keeping partial-fill drag small.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

for w in ["0xeebde7a0", "0x04b6d7e9", "0x89b5cdaa", "0xf7f0b0b1"]:
    p = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / w / "fires_decoded.parquet"
    if not p.exists():
        continue
    f = pd.read_parquet(p)
    if "shares" not in f.columns:
        continue
    print(f"=== {w}")
    s = f.shares.dropna().astype(float)
    print(f"  n_fires: {len(s):,}")
    print(f"  shares per fill  median={s.median():.2f}  p25={s.quantile(0.25):.2f}  p75={s.quantile(0.75):.2f}  p95={s.quantile(0.95):.2f}  max={s.max():.2f}")

    own = f.own_ask.astype(float).fillna(0.5)
    notional = (s * own).dropna()
    print(f"  notional usd per fill")
    print(f"    median=${notional.median():.2f}  p25=${notional.quantile(0.25):.2f}  p75=${notional.quantile(0.75):.2f}  p95=${notional.quantile(0.95):.2f}")

    total_usd = notional.sum()
    span_d = (f.ts_us.max() - f.ts_us.min()) / 1e6 / 86400
    print(f"  TOTAL sold-side notional in sample: ${total_usd:,.0f} over {span_d:.3f}d -> ${total_usd/max(span_d,0.001):,.0f}/day sold")
    print(f"  unique slugs: {f.slug.nunique()}  fires per slug avg: {len(f)/f.slug.nunique():.1f}")
    # Now estimate per-share PnL economics
    # At sum_asks=1.010, edge per share = $0.010 + 2 * 0.20 * 0.07 * 0.5 * 0.5 = $0.017
    # But each FILL only gets ONE side's rebate, not both
    # So per-share edge for ONE fill at $0.51 = 0.51 - 0 (mint cost amortized) ... hmm
    # Actually per FILL, the wallet earned: shares * (own_ask + maker_rebate)
    # The mint cost was amortized over a whole mint event (Up + Down sides)
    # If they mint N pairs and split into k fills per side, each fill = N/k shares
    # Aggregate PnL per N-pair mint event (both sides fully sold):
    #   PnL = N*(own_ask + opp_ask - 1) + N*(rebate_own + rebate_opp)
    # At $1.010 with $200 N: ~$3.40
    # At median sum_asks per fill = own_ask + opp_ask seen above
    # We can estimate aggregate sold-side gross income
    gross_income = (s * (own + 0.20 * 0.07 * own * (1 - own))).sum()
    # Subtract estimated mint cost (only count once per slug — assume each slug = 1 mint event)
    # Actually mint cost depends on n_pairs minted per slug. If both sides sold equally...
    # Just compare sold revenue vs mint cost
    print(f"  gross sold-side revenue (after rebate income): ${gross_income:,.0f}")
    print()
