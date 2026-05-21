"""
scan_canonical.py — Polymarket binary YES+NO pair-arbitrage scanner.

Strategy concept (stolen from PMXT's `BookBinaryPairArbitrageStrategy`):

If `best_ask_up + best_ask_down + 2 * taker_fee_per_share(avg_p) < $1.00`
AND there's enough visible size on both legs, buy BOTH outcomes for $1
total minus the spread. One side resolves to $1, the other to $0 →
guaranteed payoff = (1 - combined_cost) minus exit fees (none on the
losing leg — it just rots to zero).

PMXT's config defaults (from `backtests/polymarket_btc_5m_pair_arbitrage.py`):

    trade_size           = $5
    min_net_edge         = 0.0       (any positive edge after fees)
    max_total_cost       = 1.00
    max_leg_price        = 0.985
    max_spread           = 0.080     (per-leg spread cap)
    max_expected_slippage= 0.015
    min_visible_size     = 5.0       (shares per leg, top of book)
    max_entries_per_pair = 1
    hold_to_resolution   = True

## Output

Writes a per-second flagged opportunities table to `_results/pair_arb_scan.csv`
with columns:
    timestamp_us, slug, ask_up, ask_down, combined_cost,
    fee_per_share_avg, net_edge_per_share, visible_size_up, visible_size_down,
    max_filled_usd_at_top, expected_pnl_at_5usd

## Usage

```bash
py -3 strategy_lab/pair_arbitrage/scan_canonical.py --asset btc --max-slugs 200
py -3 strategy_lab/pair_arbitrage/scan_canonical.py --asset eth --report
```

The first run on BTC's 2.7 GB L25 will take ~5-10 min. Subsequent runs
filter the same source. Use --max-slugs for quick smoke tests.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (  # noqa: E402
    load_orderbook_l25_streaming,
    load_resolutions,
)
from fees import poly_taker_fee_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS  # noqa: E402


# PMXT defaults
TRADE_SIZE_USD: float = 5.0
MIN_NET_EDGE_PER_SHARE: float = 0.0
MAX_TOTAL_COST: float = 1.00
MAX_LEG_PRICE: float = 0.985
MAX_SPREAD_PER_LEG: float = 0.080
MAX_EXPECTED_SLIPPAGE: float = 0.015
MIN_VISIBLE_SIZE_SHARES: float = 5.0

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)  # 7%


def best_ask_with_size(prices: np.ndarray, sizes: np.ndarray) -> tuple[float, float]:
    """Top-of-book ask price and size. Returns (NaN, 0) if empty/invalid."""
    for p, s in zip(prices, sizes):
        try:
            p = float(p); s = float(s)
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(p) and np.isfinite(s)):
            continue
        if 0 < p < 1 and s > 0:
            return p, s
    return float("nan"), 0.0


def best_bid(prices: np.ndarray, sizes: np.ndarray) -> float:
    """Top-of-book bid price. Returns NaN if empty/invalid."""
    for p, s in zip(prices, sizes):
        try:
            p = float(p); s = float(s)
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(p) and np.isfinite(s)):
            continue
        if 0 < p < 1 and s > 0:
            return p
    return float("nan")


def scan_asset(
    asset: str,
    *,
    slugs: set | None = None,
    max_slugs: int | None = None,
    out_path: Path | None = None,
) -> pd.DataFrame:
    """Scan one asset's L25 history for pair-arb opportunities.

    Returns a DataFrame of flagged (slug, timestamp_us) pairs that pass all
    PMXT filters. Also writes to `out_path` if given.
    """
    asset_l = asset.lower()
    print(f"[{asset_l}] loading canonical resolutions...", flush=True)
    res = load_resolutions(source="upstream", assets=(asset_l.upper(),))
    if slugs is None:
        slugs = set(res["slug"].astype(str).unique())
        if max_slugs is not None:
            slugs = set(list(slugs)[:max_slugs])
    print(f"[{asset_l}] {len(slugs)} slugs to scan", flush=True)

    print(f"[{asset_l}] loading L25 books...", flush=True)
    books = load_orderbook_l25_streaming(asset_l, slugs=slugs)
    print(f"[{asset_l}] loaded {len(books)} (slug, outcome) book streams", flush=True)

    # Pair Up + Down books per slug
    by_slug: dict[str, dict[str, tuple]] = {}
    for (slug, outcome), rec in books.items():
        by_slug.setdefault(slug, {})[outcome] = rec

    rows = []
    n_slugs_scanned = 0
    for slug, outcomes in by_slug.items():
        up_rec = outcomes.get("Up")
        down_rec = outcomes.get("Down")
        if up_rec is None or down_rec is None:
            continue
        ts_up, ap_up, asz_up, bp_up, bsz_up = up_rec
        ts_dn, ap_dn, asz_dn, bp_dn, bsz_dn = down_rec

        # Align timestamps — only check seconds that have BOTH legs (1Hz subsample
        # in load_orderbook_l25_streaming so this is exact)
        common_ts, idx_up, idx_dn = np.intersect1d(ts_up, ts_dn, return_indices=True)
        if len(common_ts) == 0:
            continue

        for i in range(len(common_ts)):
            iu, idn = idx_up[i], idx_dn[i]

            # Up leg
            ask_u, sz_u = best_ask_with_size(ap_up[iu], asz_up[iu])
            bid_u = best_bid(bp_up[iu], bsz_up[iu])
            spread_u = ask_u - bid_u if (np.isfinite(ask_u) and np.isfinite(bid_u)) else float("nan")

            # Down leg
            ask_d, sz_d = best_ask_with_size(ap_dn[idn], asz_dn[idn])
            bid_d = best_bid(bp_dn[idn], bsz_dn[idn])
            spread_d = ask_d - bid_d if (np.isfinite(ask_d) and np.isfinite(bid_d)) else float("nan")

            if not (np.isfinite(ask_u) and np.isfinite(ask_d)):
                continue
            if ask_u > MAX_LEG_PRICE or ask_d > MAX_LEG_PRICE:
                continue
            if (np.isfinite(spread_u) and spread_u > MAX_SPREAD_PER_LEG):
                continue
            if (np.isfinite(spread_d) and spread_d > MAX_SPREAD_PER_LEG):
                continue
            if sz_u < MIN_VISIBLE_SIZE_SHARES or sz_d < MIN_VISIBLE_SIZE_SHARES:
                continue

            fee_u = poly_taker_fee_per_share(ask_u, FEE_RATE)
            fee_d = poly_taker_fee_per_share(ask_d, FEE_RATE)
            total_cost = ask_u + ask_d + fee_u + fee_d
            if total_cost > MAX_TOTAL_COST:
                continue

            net_edge_per_share = 1.0 - total_cost
            if net_edge_per_share < MIN_NET_EDGE_PER_SHARE:
                continue

            max_filled_usd_top = min(sz_u * ask_u, sz_d * ask_d)
            # PMXT trades $5/leg. For our flagging, also compute PnL at $5.
            shares_at_5 = TRADE_SIZE_USD / max(ask_u, ask_d)  # conservative
            shares_at_5 = min(shares_at_5, sz_u, sz_d)
            expected_pnl_at_5 = shares_at_5 * net_edge_per_share

            rows.append({
                "timestamp_us": int(common_ts[i]),
                "slug": slug,
                "ask_up": ask_u,
                "ask_down": ask_d,
                "sz_up": sz_u,
                "sz_down": sz_d,
                "spread_up": spread_u,
                "spread_down": spread_d,
                "fee_u_per_share": fee_u,
                "fee_d_per_share": fee_d,
                "total_cost": total_cost,
                "net_edge_per_share": net_edge_per_share,
                "max_filled_usd_top": max_filled_usd_top,
                "shares_at_5usd": shares_at_5,
                "expected_pnl_at_5usd": expected_pnl_at_5,
            })

        n_slugs_scanned += 1
        if n_slugs_scanned % 100 == 0:
            print(f"[{asset_l}] scanned {n_slugs_scanned}/{len(by_slug)} slugs, "
                  f"flagged {len(rows)} opportunities", flush=True)

    df = pd.DataFrame(rows)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_path, index=False)
        print(f"[{asset_l}] wrote {len(df)} rows to {out_path}")
    return df


def report(df: pd.DataFrame, asset: str) -> None:
    print(f"\n=== {asset.upper()} pair-arb scan summary ===")
    print(f"flagged opportunities: {len(df):,}")
    if df.empty:
        return
    print(f"unique slugs:          {df.slug.nunique():,}")
    print(f"net_edge p50:          {df.net_edge_per_share.median():.5f}")
    print(f"net_edge p95:          {df.net_edge_per_share.quantile(0.95):.5f}")
    print(f"max single edge:       {df.net_edge_per_share.max():.5f}")
    print(f"total expected PnL @ $5/leg: ${df.expected_pnl_at_5usd.sum():.2f}")
    print(f"  (counting all flagged seconds — naive, no per-pair dedup)")
    print()
    print("Top 10 opportunities by net edge:")
    print(df.nlargest(10, "net_edge_per_share")[
        ["slug", "ask_up", "ask_down", "total_cost", "net_edge_per_share",
         "sz_up", "sz_down", "expected_pnl_at_5usd"]
    ].to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("btc", "eth", "sol"), default="btc")
    ap.add_argument("--max-slugs", type=int, default=None,
                    help="cap slug count for smoke testing (default: all)")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: data/v4/canonical/_results/pair_arb_<asset>.csv)")
    ap.add_argument("--no-report", action="store_true",
                    help="skip the summary report")
    args = ap.parse_args()

    out_path = (Path(args.out) if args.out
                else ROOT / "data" / "v4" / "canonical" / "_results"
                     / f"pair_arb_{args.asset}.csv")

    df = scan_asset(args.asset, max_slugs=args.max_slugs, out_path=out_path)
    if not args.no_report:
        report(df, args.asset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
