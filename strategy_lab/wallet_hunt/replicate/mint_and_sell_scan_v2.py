"""Mint-and-sell scanner v2 — wallet-calibrated.

Fixes vs v1 (`mint_and_sell_scan.py`):
  1. **Maker fee model corrected** (handoff §1): treat rebate as INCOME
     instead of subtracting it as a phantom fee. Wallets fire at
     sum_asks~$1.010 which the buggy v1 filters out as "negative edge".
  2. **Entry threshold lowered** to `sum_asks ≥ 1.005` (default), matching
     the 85% mode observed across 4 decoded wallets.
  3. **Cooldown is configurable** — wallets re-quote 30-170× per slug.
     v1's hardcoded 10s cooldown caps fires at ~3/slug. Default v2 = 1s
     (every L25 snapshot when conditions hold).
  4. **Notional configurable** — wallets size each fire at $3-6 median.
     v2 default $2.5 per fire.

Edge math (per pair-share at $1.010, sum_asks):
    gross    = (sum_asks − 1)                          = +$0.010
    rebate   = 2 × rebate_share × fee_rate × p × (1-p) = +$0.007 (at p≈0.5)
    NET edge = gross + rebate                          = +$0.017 per pair-share
    → at $2.5 notional = +$0.0425 per BOTH-fill event

Output: opportunities.parquet with the SAME schema as v1, plus
`rebate_income_per_pair`, `gross_pnl_at_posted_with_rebate`.
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
    poly_maker_rebate_per_share, bps_to_rate,
    DEFAULT_CRYPTO_FEE_BPS, CRYPTO_MAKER_REBATE_SHARE,
)

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)  # 0.07


def scan_market(slug: str, books_up, books_down,
                  fee_rate: float, notional: float,
                  min_sum_asks: float, cooldown_snaps: int,
                  min_visible_depth: float, max_spread_per_leg: float) -> dict | None:
    if books_up is None or books_down is None:
        return None
    ts_up, ap_up, asz_up, bp_up, bsz_up = books_up
    ts_dn, ap_dn, asz_dn, bp_dn, bsz_dn = books_down
    if len(ts_up) == 0 or len(ts_dn) == 0:
        return None
    common_ts, idx_up, idx_dn = np.intersect1d(ts_up, ts_dn, return_indices=True)
    if len(common_ts) == 0:
        return None

    opportunities = []
    last_fire_idx = -10**9

    for i in range(len(common_ts)):
        iu, idn = idx_up[i], idx_dn[i]
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
        if su0 < min_visible_depth or sd0 < min_visible_depth:
            continue
        if np.isfinite(bu0) and np.isfinite(bd0):
            if (au0 - bu0) > max_spread_per_leg or (ad0 - bd0) > max_spread_per_leg:
                continue

        sum_asks = au0 + ad0
        if sum_asks < min_sum_asks:
            continue
        if i - last_fire_idx < cooldown_snaps:
            continue

        # CORRECTED edge math: rebate is INCOME, not cost
        gross_per_share = sum_asks - 1.0
        rebate_per_pair = (
            poly_maker_rebate_per_share(au0, fee_rate, CRYPTO_MAKER_REBATE_SHARE)
            + poly_maker_rebate_per_share(ad0, fee_rate, CRYPTO_MAKER_REBATE_SHARE)
        )
        net_edge_per_pair = gross_per_share + rebate_per_pair  # both income at limit posts

        n_pairs = notional / 1.0  # $1/pair mint cost
        gross_pnl_with_rebate = n_pairs * net_edge_per_pair

        opportunities.append({
            "slug": slug,
            "ts": int(common_ts[i]),
            "ask_up": au0, "ask_dn": ad0,
            "size_up": su0, "size_dn": sd0,
            "bid_up": bu0, "bid_dn": bd0,
            "sum_asks": sum_asks,
            "net_edge_per_share": gross_per_share,  # legacy field name
            "rebate_income_per_pair": rebate_per_pair,
            "net_edge_per_pair_with_rebate": net_edge_per_pair,
            "n_pairs": n_pairs,
            "pnl_at_posted": gross_pnl_with_rebate,  # IF both fill
        })
        last_fire_idx = i

    if not opportunities:
        return None
    return {
        "slug": slug,
        "n_opportunities": len(opportunities),
        "first_ts": opportunities[0]["ts"],
        "last_ts": opportunities[-1]["ts"],
        "opportunities": opportunities,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("BTC", "ETH", "SOL", "ALL"), default="BTC")
    ap.add_argument("--timeframe", choices=("5m", "15m", "ALL"), default="ALL")
    ap.add_argument("--notional", type=float, default=2.5)
    ap.add_argument("--min-sum-asks", type=float, default=1.005)
    ap.add_argument("--cooldown-snaps", type=int, default=1,
                    help="snapshots to skip after firing (default 1 = every snapshot)")
    ap.add_argument("--min-visible-depth", type=float, default=2.5,
                    help="min shares visible at best_ask to fire (sized to notional/avg_ask)")
    ap.add_argument("--max-spread-per-leg", type=float, default=0.10)
    ap.add_argument("--max-slugs", type=int, default=None)
    ap.add_argument("--out-tag", default="v2")
    args = ap.parse_args()

    assets = ["BTC", "ETH", "SOL"] if args.asset == "ALL" else [args.asset]
    tfs = ["5m", "15m"] if args.timeframe == "ALL" else [args.timeframe]

    for asset in assets:
        for tf in tfs:
            cell = f"{asset.lower()}_{tf}"
            suffix = f"{args.out_tag}_{cell}_{datetime.now(timezone.utc).strftime('%Y_%m_%d')}"
            OUT = ROOT / "data" / "v4" / "canonical" / "_results" / f"mint_and_sell_{suffix}"
            OUT.mkdir(parents=True, exist_ok=True)
            print(f"\n========== {cell} ==========")
            print(f"  out: {OUT}")
            print(f"  notional=${args.notional:.2f}  min_sum_asks={args.min_sum_asks:.4f}  cooldown={args.cooldown_snaps}s")

            res = load_resolutions(assets=[asset], timeframes=[tf])
            if args.max_slugs:
                res = res.head(args.max_slugs)
            slugs = sorted(res.slug.astype(str).unique())
            print(f"  {len(slugs)} slugs in universe")

            print(f"  loading L25 books...")
            books_idx = load_orderbook_l25_streaming(asset.lower(), slugs=set(slugs),
                                                       subsample_1hz=True)
            print(f"  {len(books_idx)} streams loaded")

            all_ops = []
            for j, slug in enumerate(slugs):
                up = books_idx.get((slug, "Up"))
                dn = books_idx.get((slug, "Down"))
                if up is None or dn is None:
                    continue
                result = scan_market(slug, up, dn,
                                       fee_rate=FEE_RATE, notional=args.notional,
                                       min_sum_asks=args.min_sum_asks,
                                       cooldown_snaps=args.cooldown_snaps,
                                       min_visible_depth=args.min_visible_depth,
                                       max_spread_per_leg=args.max_spread_per_leg)
                if result is None:
                    continue
                all_ops.extend(result["opportunities"])
                if (j + 1) % 200 == 0:
                    print(f"    {j+1}/{len(slugs)}: cum_ops={len(all_ops):,}", flush=True)

            ops_df = pd.DataFrame(all_ops)
            if ops_df.empty:
                print(f"  no opportunities found")
                continue
            ops_df.to_parquet(OUT / "opportunities.parquet", index=False)

            n = len(ops_df)
            n_slugs_active = ops_df.slug.nunique()
            print(f"\n  ---")
            print(f"  total opportunities:  {n:,}")
            print(f"  active slugs:         {n_slugs_active:,} / {len(slugs)}")
            print(f"  opportunities/slug:   {n/max(n_slugs_active,1):.1f} avg")
            print(f"  total gross PnL (IF both fill on every fire): ${ops_df.pnl_at_posted.sum():,.2f}")
            print(f"  mean PnL/op (BOTH-fill):  ${ops_df.pnl_at_posted.mean():.4f}")
            print(f"  sum_asks distribution: median={ops_df.sum_asks.median():.4f}  p25={ops_df.sum_asks.quantile(0.25):.4f}  p75={ops_df.sum_asks.quantile(0.75):.4f}")


if __name__ == "__main__":
    main()
