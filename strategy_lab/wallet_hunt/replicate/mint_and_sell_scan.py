"""Mint-and-sell strategy replicator (target: 0x04b6d7e9, 0x89b5cdaa wallets).

Strategy:
  For each Polymarket up-down market, scan each 1Hz snapshot. When the sum of
  best asks across Up + Down exceeds $1 + fees:
    - Call CTF.splitPosition(N) → pay N USDC, receive N Up + N Down tokens
    - Post limit SELL at best_ask on the Up side
    - Post limit SELL at best_ask on the Down side
  When both fills (impatient takers hit our ask):
    profit = N × (avg_ask_up + avg_ask_down - 1) - fees + maker_rebates

Backtest assumptions:
  - We post AT best_ask (just under it to ensure priority); fill prob = ?
  - Fill probability: 1.0 if ask sum stays > $1 for ≥30s after posting
    (impatient takers will eventually consume the ask)
  - If ask sum drops below $1 before fill, we cancel + lose nothing
  - Maker rebate: 20% of fee_per_share × shares

Outputs:
  data/v4/canonical/_results/mint_and_sell_<date>/opportunities.parquet
  data/v4/canonical/_results/mint_and_sell_<date>/pnl_summary.csv
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from fees import (  # noqa: E402
    poly_taker_fee_per_share, bps_to_rate,
    DEFAULT_CRYPTO_FEE_BPS, CRYPTO_MAKER_REBATE_SHARE,
)

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)  # 0.07 for crypto

# Strategy parameters (matching observed wallet behavior)
MINT_NOTIONAL_USD = 25.0     # mint $25 worth of pairs per opportunity
MIN_NET_EDGE_PER_SHARE = 0.0  # require sum_asks > $1 + 2×fee × p × (1-p)
MIN_VISIBLE_DEPTH_SHARES = 5.0
MAX_SPREAD_PER_LEG = 0.10
FILL_WAIT_SECONDS = 30        # how long we wait for fills before cancelling


def scan_market(slug: str, books_up, books_down, fee_rate: float = FEE_RATE,
                  notional: float = MINT_NOTIONAL_USD) -> dict | None:
    """Scan one (slug, Up+Down) pair for mint-and-sell opportunities.

    Returns dict of aggregate metrics OR None if no opportunities.
    """
    if books_up is None or books_down is None:
        return None
    ts_up, ap_up, asz_up, bp_up, bsz_up = books_up
    ts_dn, ap_dn, asz_dn, bp_dn, bsz_dn = books_down
    if len(ts_up) == 0 or len(ts_dn) == 0:
        return None

    # Align on common seconds
    common_ts, idx_up, idx_dn = np.intersect1d(ts_up, ts_dn, return_indices=True)
    if len(common_ts) == 0:
        return None

    opportunities = []
    pnls = []
    last_fire_idx = -999

    for i in range(len(common_ts)):
        iu, idn = idx_up[i], idx_dn[i]

        # Top of book Up
        try:
            au0 = float(ap_up[iu][0]); su0 = float(asz_up[iu][0])
            bu0 = float(bp_up[iu][0]); szbu0 = float(bsz_up[iu][0])
            ad0 = float(ap_dn[idn][0]); sd0 = float(asz_dn[idn][0])
            bd0 = float(bp_dn[idn][0]); szbd0 = float(bsz_dn[idn][0])
        except (IndexError, TypeError, ValueError):
            continue
        if not (np.isfinite(au0) and np.isfinite(ad0)
                and 0 < au0 < 1 and 0 < ad0 < 1):
            continue
        # Filters
        if su0 < MIN_VISIBLE_DEPTH_SHARES or sd0 < MIN_VISIBLE_DEPTH_SHARES:
            continue
        if np.isfinite(bu0) and np.isfinite(bd0):
            if (au0 - bu0) > MAX_SPREAD_PER_LEG or (ad0 - bd0) > MAX_SPREAD_PER_LEG:
                continue

        # Edge math: sum of asks - fees > $1
        fee_u = poly_taker_fee_per_share(au0, fee_rate) * (1 - CRYPTO_MAKER_REBATE_SHARE)
        fee_d = poly_taker_fee_per_share(ad0, fee_rate) * (1 - CRYPTO_MAKER_REBATE_SHARE)
        # We pay maker rebates back, so effective fee per share is fee × (1 - rebate_share)
        # since we're the MAKER posting the limit sell
        net_edge = (au0 + ad0) - 1.0 - fee_u - fee_d
        if net_edge < MIN_NET_EDGE_PER_SHARE:
            continue

        # Cooldown: don't double-fire on same opportunity (skip if just fired)
        if i - last_fire_idx < 10:
            continue

        # Simulate: mint $notional pairs, post sells at au0 and ad0
        n_pairs = notional / 1.0  # mint cost = $1 per pair
        # Will both fills go through?
        # Heuristic: check next N seconds. If best_ask on each side STAYS ≥
        # our posted price for FILL_WAIT_SECONDS, assume filled.
        # Conservative: only count as filled if a taker would have hit.
        # Simpler proxy: fill probability = 1 if best_bid on opposite side
        # comes within 1 tick within FILL_WAIT_SECONDS (someone willing to pay)
        # For backtest v1: assume 100% fill probability when posted (optimistic)
        # We'll refine later.

        # Realized profit at posted prices
        gross = n_pairs * (au0 + ad0) - n_pairs * 1.0  # cash received - mint cost
        fees_paid = n_pairs * (fee_u + fee_d)
        pnl = gross - fees_paid

        opportunities.append({
            "slug": slug,
            "ts": int(common_ts[i]),
            "ask_up": au0, "ask_dn": ad0,
            "size_up": su0, "size_dn": sd0,
            "bid_up": bu0, "bid_dn": bd0,
            "sum_asks": au0 + ad0,
            "net_edge_per_share": net_edge,
            "n_pairs": n_pairs,
            "pnl_at_posted": pnl,
        })
        pnls.append(pnl)
        last_fire_idx = i

    if not opportunities:
        return None
    return {
        "slug": slug,
        "n_opportunities": len(opportunities),
        "total_pnl_at_posted": sum(pnls),
        "mean_pnl_per_op": sum(pnls) / len(pnls),
        "first_ts": opportunities[0]["ts"],
        "last_ts": opportunities[-1]["ts"],
        "opportunities": opportunities,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("BTC", "ETH", "SOL"), default="BTC")
    ap.add_argument("--max-slugs", type=int, default=None)
    ap.add_argument("--timeframe", choices=("5m", "15m"), default=None,
                    help="Filter to a specific timeframe (default: both)")
    ap.add_argument("--out-suffix", default=None)
    args = ap.parse_args()

    suffix = args.out_suffix or f"{args.asset.lower()}_{args.timeframe or 'both'}_{datetime.now(timezone.utc).strftime('%Y_%m_%d')}"
    OUT = ROOT / "data" / "v4" / "canonical" / "_results" / f"mint_and_sell_{suffix}"
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"=== Output: {OUT}")
    print(f"=== Asset: {args.asset}  TF: {args.timeframe or 'both'}")
    print(f"=== Strategy: mint $25 + post 2 sells when ask_up + ask_dn > $1 + fees")

    # Load resolutions universe
    tfs = [args.timeframe] if args.timeframe else ["5m", "15m"]
    print(f"\n[1] loading canonical resolutions...")
    res = load_resolutions(assets=[args.asset], timeframes=tfs)
    if args.max_slugs:
        res = res.head(args.max_slugs)
    slugs = sorted(res.slug.astype(str).unique())
    print(f"    {len(slugs)} slugs in universe")

    # Load L25 books (one streaming call covers all slugs of one asset)
    print(f"[2] loading L25 books for {len(slugs)} slugs...")
    books_idx = load_orderbook_l25_streaming(args.asset.lower(), slugs=set(slugs),
                                                subsample_1hz=True)
    print(f"    {len(books_idx)} (slug, outcome) streams loaded")

    # Pair Up + Down per slug
    print(f"[3] scanning...")
    all_ops = []
    all_summaries = []
    for j, slug in enumerate(slugs):
        up = books_idx.get((slug, "Up"))
        dn = books_idx.get((slug, "Down"))
        if up is None or dn is None:
            continue
        result = scan_market(slug, up, dn)
        if result is None:
            continue
        all_summaries.append({
            k: v for k, v in result.items() if k != "opportunities"
        })
        all_ops.extend(result["opportunities"])
        if (j + 1) % 200 == 0:
            print(f"    scanned {j+1}/{len(slugs)}: cum_opportunities={len(all_ops)}", flush=True)

    # Save
    ops_df = pd.DataFrame(all_ops)
    sum_df = pd.DataFrame(all_summaries)
    ops_df.to_parquet(OUT / "opportunities.parquet", index=False)
    sum_df.to_csv(OUT / "summary.csv", index=False)

    # Headline stats
    print(f"\n=== Results ===")
    print(f"  markets with opportunities: {len(sum_df)} / {len(slugs)}")
    print(f"  total opportunities: {len(ops_df):,}")
    if not ops_df.empty:
        print(f"  total PnL at posted: ${ops_df.pnl_at_posted.sum():,.2f}")
        print(f"  mean PnL/op:         ${ops_df.pnl_at_posted.mean():.4f}")
        print(f"  median PnL/op:       ${ops_df.pnl_at_posted.median():.4f}")
        print(f"  max PnL/op:          ${ops_df.pnl_at_posted.max():.2f}")
        print(f"  PnL by edge bucket:")
        ops_df["edge_bucket"] = pd.cut(
            ops_df.net_edge_per_share,
            bins=[0, 0.005, 0.01, 0.02, 0.05, 1.0],
            labels=["0-0.5¢", "0.5-1¢", "1-2¢", "2-5¢", ">5¢"],
        )
        bucket_summary = ops_df.groupby("edge_bucket", observed=True).agg(
            n=("pnl_at_posted", "size"),
            total_pnl=("pnl_at_posted", "sum"),
            mean_pnl=("pnl_at_posted", "mean"),
        )
        print(bucket_summary.round(2).to_string())

        # Time-distribution — L25 timestamps are in microseconds (UTC us)
        print(f"\n  Daily PnL (top 10 days):")
        ops_df["day"] = pd.to_datetime(ops_df.ts, unit="us", utc=True).dt.date
        daily = ops_df.groupby("day").agg(
            n=("pnl_at_posted", "size"),
            pnl=("pnl_at_posted", "sum"),
        ).sort_values("pnl", ascending=False)
        print(daily.head(10).round(2).to_string())

    print(f"\nDone. Outputs in {OUT}")


if __name__ == "__main__":
    main()
