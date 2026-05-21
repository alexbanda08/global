"""Realized fill probability checker for mint-and-sell.

When we post a limit SELL at best_ask=$X on the Up side, we want to know:
how often does an impatient taker come in AND lift our offer within
FILL_WAIT_SECONDS?

Proxy: after posting at price X, check if the best_bid on Up reaches X
within FILL_WAIT_SECONDS. If bid >= our ask, a marketable BUY would have
crossed our quote → filled. Same logic for Down side.

For mint-and-sell we need BOTH sides to fill. Joint fill probability = the
fraction of opportunities where both Up AND Down posts get filled within
the wait window.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_orderbook_l25_streaming  # noqa: E402

FILL_WAIT_SECONDS = 60


def check_fill_window(ts_arr, bp_arr, target_price: float,
                       start_us: int, wait_seconds: int) -> bool:
    """Did best_bid reach target_price within wait_seconds of start_us?"""
    target_us = start_us + wait_seconds * 1_000_000
    mask = (ts_arr >= start_us) & (ts_arr <= target_us)
    if not mask.any():
        return False
    idx = np.where(mask)[0]
    for i in idx:
        bb = float(bp_arr[i][0]) if (len(bp_arr[i]) and np.isfinite(bp_arr[i][0])) else float("nan")
        if np.isfinite(bb) and bb >= target_price:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("BTC", "ETH", "SOL"), default="BTC")
    ap.add_argument("--timeframe", choices=("5m", "15m"), default="15m")
    ap.add_argument("--wait-seconds", type=int, default=FILL_WAIT_SECONDS)
    ap.add_argument("--sample", type=int, default=2000,
                    help="check first N opportunities only (full scan is slow)")
    args = ap.parse_args()

    opps_p = ROOT / "data" / "v4" / "canonical" / "_results" / \
             f"mint_and_sell_{args.asset.lower()}_{args.timeframe}_2026_05_16" / \
             "opportunities.parquet"
    if not opps_p.exists():
        print(f"missing {opps_p}; run mint_and_sell_scan.py first")
        return 1
    ops = pd.read_parquet(opps_p)
    print(f"loaded {len(ops):,} opportunities for {args.asset} {args.timeframe}")
    ops_sample = ops.head(args.sample).copy()
    print(f"checking fill prob on first {len(ops_sample):,} (wait={args.wait_seconds}s)")

    slugs = sorted(ops_sample.slug.unique())
    print(f"loading L25 books for {len(slugs)} slugs...")
    bi = load_orderbook_l25_streaming(args.asset.lower(), slugs=set(slugs), subsample_1hz=True)

    up_fills = []; dn_fills = []; both_fills = []
    for i, r in enumerate(ops_sample.itertuples(index=False)):
        slug = r.slug
        target_up = float(r.ask_up); target_dn = float(r.ask_dn)
        start_us = int(r.ts)
        up_rec = bi.get((slug, "Up"))
        dn_rec = bi.get((slug, "Down"))
        if up_rec is None or dn_rec is None:
            up_fills.append(False); dn_fills.append(False); both_fills.append(False)
            continue
        ts_up, ap_up, asz_up, bp_up, bsz_up = up_rec
        ts_dn, ap_dn, asz_dn, bp_dn, bsz_dn = dn_rec
        # Filled = best_bid on that side reaches our ask within wait window
        u = check_fill_window(ts_up, bp_up, target_up, start_us, args.wait_seconds)
        d = check_fill_window(ts_dn, bp_dn, target_dn, start_us, args.wait_seconds)
        up_fills.append(u); dn_fills.append(d); both_fills.append(u and d)
        if (i + 1) % 500 == 0:
            print(f"  {i+1}/{len(ops_sample)}: up_fill={np.mean(up_fills)*100:.1f}% dn_fill={np.mean(dn_fills)*100:.1f}% both={np.mean(both_fills)*100:.1f}%", flush=True)

    ops_sample["up_filled"] = up_fills
    ops_sample["dn_filled"] = dn_fills
    ops_sample["both_filled"] = both_fills
    out_p = opps_p.parent / "fill_probability.parquet"
    ops_sample.to_parquet(out_p, index=False)

    print(f"\n=== FILL PROBABILITY (wait={args.wait_seconds}s) ===")
    print(f"  sample size: {len(ops_sample):,}")
    print(f"  Up side filled:    {sum(up_fills):>5} ({100*np.mean(up_fills):.1f}%)")
    print(f"  Down side filled:  {sum(dn_fills):>5} ({100*np.mean(dn_fills):.1f}%)")
    print(f"  BOTH sides filled: {sum(both_fills):>5} ({100*np.mean(both_fills):.1f}%)")
    print()
    print(f"  → realized PnL = posted PnL × {np.mean(both_fills):.4f}")
    posted_pnl = ops_sample.pnl_at_posted.sum()
    realized_pnl = posted_pnl * np.mean(both_fills)
    print(f"  posted PnL on sample:   ${posted_pnl:>10,.2f}")
    print(f"  realized PnL estimated: ${realized_pnl:>10,.2f}")

    # By edge bucket: do higher-edge opportunities have higher fill prob?
    ops_sample["edge_bucket"] = pd.cut(
        ops_sample.net_edge_per_share,
        bins=[0, 0.005, 0.01, 0.02, 0.05, 1.0],
        labels=["0-0.5¢", "0.5-1¢", "1-2¢", "2-5¢", ">5¢"],
    )
    print(f"\n  Fill prob by edge bucket:")
    grouped = ops_sample.groupby("edge_bucket", observed=True).agg(
        n=("both_filled", "size"),
        both_pct=("both_filled", "mean"),
        up_pct=("up_filled", "mean"),
        dn_pct=("dn_filled", "mean"),
    )
    grouped["both_pct"] *= 100; grouped["up_pct"] *= 100; grouped["dn_pct"] *= 100
    print(grouped.round(1).to_string())


if __name__ == "__main__":
    main()
