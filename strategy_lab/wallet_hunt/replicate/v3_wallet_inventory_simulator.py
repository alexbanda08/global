"""V3 wallet-style simulator — pre-mint once per slug, share inventory across fires.

The V2 simulator treats each fire as an independent mint + sell pair, which
inflates total mint cost by N× and creates a per-fire held-side selection
bias that doesn't exist in the wallet model.

Wallet model (per pickup §Q4 and chain decode of 0x89b5cdaa: 1 mint TX → 1500 sells):

  1. At slug start, MINT pre_mint_pairs once → pre_mint_pairs Up + pre_mint_pairs Down tokens
     Cost: pre_mint_pairs × $1.00
  2. For each L25 opportunity tick where conditions hold:
       a. Post limit SELL of min(post_size, remaining_up) Up at ask_up
       b. Post limit SELL of min(post_size, remaining_dn) Down at ask_dn
       c. Detect fills via trade-tape detector (in [ts, ts+60s])
       d. Decrement inventory on fill, accumulate cash + rebates
  3. At slug end (ws_s + window_s), remaining inventory redeems:
       - If outcome=Up: remaining_up × $1, remaining_dn × $0
       - Else: vice versa
  4. Slug PnL = cash + rebates + redemption - mint_cost

Critical differences from per-fire model:
  - Mint cost is bounded by pre_mint_pairs, not n_fires × notional
  - "Held side" selection bias only applies to slug-end leftover, not per fire
  - Capital efficiency much higher (one mint serves all fires)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions  # noqa: E402
from fees import poly_maker_rebate_per_share, bps_to_rate, DEFAULT_CRYPTO_FEE_BPS  # noqa: E402
from fill_detector_tradetape import (  # noqa: E402
    load_trades_for_asset, index_trades_by_key, detect_fill, estimate_queue_ahead,
)

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)


def simulate_slug_wallet(
    slug: str, outcome: str, ops: pd.DataFrame,
    tidx_up, tidx_dn,
    pre_mint_pairs: float = 50.0,
    post_size: float = 5.0,
    detector: str = "opt",
) -> dict:
    """Wallet-style simulation for one slug.

    Returns slug-level summary dict.
    """
    inv_up = pre_mint_pairs
    inv_dn = pre_mint_pairs
    mint_cost = pre_mint_pairs * 1.0
    cash = 0.0
    rebates = 0.0

    n_post_up = 0
    n_post_dn = 0
    n_fill_up = 0
    n_fill_dn = 0
    fill_vol_up = 0.0
    fill_vol_dn = 0.0
    last_fill_us = -1

    for r in ops.itertuples(index=False):
        if inv_up <= 0 and inv_dn <= 0:
            break  # ran out of inventory
        ts = int(r.ts)
        # Skip if this fire is within previous fill_window (avoid double-counting volume)
        if last_fill_us > 0 and ts < last_fill_us:
            continue

        size_up = min(post_size, inv_up)
        size_dn = min(post_size, inv_dn)
        q_up = estimate_queue_ahead(r.size_up)
        q_dn = estimate_queue_ahead(r.size_dn)

        # Detect fills (taker buys lifting our ask in [ts, ts+60s])
        if size_up > 0 and tidx_up is not None:
            fu = detect_fill(tidx_up, r.ask_up, ts, size_up, q_up)
            if (detector == "opt" and fu.optimistic_filled) or (detector == "q" and fu.queue_aware_filled):
                # Fill: maker sells up to size_up shares at r.ask_up
                # Optimistic: fill our full size_up
                fill_shares = min(size_up, inv_up)
                cash += fill_shares * r.ask_up
                rebates += fill_shares * poly_maker_rebate_per_share(r.ask_up, FEE_RATE)
                inv_up -= fill_shares
                fill_vol_up += fill_shares
                n_fill_up += 1
                last_fill_us = max(last_fill_us, fu.first_fill_us)
            n_post_up += 1

        if size_dn > 0 and tidx_dn is not None:
            fd = detect_fill(tidx_dn, r.ask_dn, ts, size_dn, q_dn)
            if (detector == "opt" and fd.optimistic_filled) or (detector == "q" and fd.queue_aware_filled):
                fill_shares = min(size_dn, inv_dn)
                cash += fill_shares * r.ask_dn
                rebates += fill_shares * poly_maker_rebate_per_share(r.ask_dn, FEE_RATE)
                inv_dn -= fill_shares
                fill_vol_dn += fill_shares
                n_fill_dn += 1
                last_fill_us = max(last_fill_us, fd.first_fill_us)
            n_post_dn += 1

    # Slug end: redeem remaining inventory at outcome
    redeem_up = inv_up * (1.0 if outcome == "Up" else 0.0)
    redeem_dn = inv_dn * (1.0 if outcome == "Down" else 0.0)
    redeem = redeem_up + redeem_dn

    slug_pnl = cash + rebates + redeem - mint_cost
    return {
        "slug": slug, "outcome": outcome,
        "pre_mint_pairs": pre_mint_pairs, "mint_cost": mint_cost,
        "n_post_up": n_post_up, "n_post_dn": n_post_dn,
        "n_fill_up": n_fill_up, "n_fill_dn": n_fill_dn,
        "fill_vol_up": fill_vol_up, "fill_vol_dn": fill_vol_dn,
        "remaining_up": inv_up, "remaining_dn": inv_dn,
        "cash": cash, "rebates": rebates, "redeem": redeem,
        "slug_pnl": slug_pnl,
    }


def run_cell(cell: str, n_slugs: int = 50,
             pre_mint_pairs: float = 50.0, post_size: float = 5.0,
             detector: str = "opt"):
    asset = cell.split("_")[0]
    R = ROOT / "data" / "v4" / "canonical" / "_results"
    op = pd.read_parquet(R / f"mint_and_sell_v2_{cell}_2026_05_16" / "opportunities.parquet")
    res = load_resolutions(assets=[asset.upper()], timeframes=[cell.split("_")[1]])[["slug","outcome"]].drop_duplicates(subset="slug")
    op = op.merge(res, on="slug", how="inner")

    tr_path = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset.lower()}.parquet"
    tr_slugs = set(pd.read_parquet(tr_path, columns=["slug"])["slug"].unique())
    op = op[op.slug.isin(tr_slugs)].reset_index(drop=True)

    counts = op.groupby("slug").size().sort_values(ascending=False)
    picked = counts.head(n_slugs).index.tolist()
    op = op[op.slug.isin(picked)].reset_index(drop=True)
    print(f"[{cell}] {len(picked)} slugs picked, {len(op):,} ops total", flush=True)

    trades = load_trades_for_asset(asset)
    trades = trades[trades.slug.isin(picked)].reset_index(drop=True)
    tidx = index_trades_by_key(trades)
    del trades

    rows = []
    for slug in picked:
        sub = op[op.slug == slug].sort_values("ts").reset_index(drop=True)
        outcome = sub.outcome.iloc[0]
        tup = tidx.get((slug, "Up"))
        tdn = tidx.get((slug, "Down"))
        rows.append(simulate_slug_wallet(
            slug, outcome, sub, tup, tdn,
            pre_mint_pairs=pre_mint_pairs, post_size=post_size, detector=detector,
        ))
    sg = pd.DataFrame(rows)

    print(f"\n=== {cell} WALLET-MODEL (pre_mint={pre_mint_pairs}, post_size={post_size}, detector={detector}) ===")
    print(f"n_slugs={len(sg)}")
    print(f"Slug PnL distribution:")
    print(sg.slug_pnl.describe().to_string())
    print()
    print(f"Aggregate: total ${sg.slug_pnl.sum():+,.2f}, mean ${sg.slug_pnl.mean():+.2f}/slug")
    print(f"Pct positive slugs: {(sg.slug_pnl > 0).mean()*100:.1f}%")
    print()
    print(f"Fill stats per slug:")
    print(f"  Avg posts up: {sg.n_post_up.mean():.0f}, fills up: {sg.n_fill_up.mean():.1f} (fill rate {sg.n_fill_up.sum()/max(sg.n_post_up.sum(),1)*100:.1f}%)")
    print(f"  Avg posts dn: {sg.n_post_dn.mean():.0f}, fills dn: {sg.n_fill_dn.mean():.1f} (fill rate {sg.n_fill_dn.sum()/max(sg.n_post_dn.sum(),1)*100:.1f}%)")
    print(f"  Avg fill vol up: {sg.fill_vol_up.mean():.1f} shares ({sg.fill_vol_up.mean()/pre_mint_pairs*100:.1f}% of pre-mint)")
    print(f"  Avg fill vol dn: {sg.fill_vol_dn.mean():.1f} shares ({sg.fill_vol_dn.mean()/pre_mint_pairs*100:.1f}% of pre-mint)")
    print(f"  Avg remaining Up: {sg.remaining_up.mean():.1f}, Down: {sg.remaining_dn.mean():.1f}")
    print()
    print(f"Decomposition (averaged across slugs):")
    print(f"  Cash from fills: ${sg.cash.mean():+.2f}")
    print(f"  Rebates:         ${sg.rebates.mean():+.4f}")
    print(f"  Redemption:      ${sg.redeem.mean():+.2f}")
    print(f"  Mint cost:       ${-sg.mint_cost.mean():+.2f}")

    # Extrapolate
    n_slugs_universe = res.slug.nunique()
    proj_per_day = sg.slug_pnl.mean() * n_slugs_universe / 21.0
    print(f"\n  Projection at this pre-mint size: ${proj_per_day:+,.2f}/day across {n_slugs_universe:,} slugs in 21d window")

    out_dir = R / f"mint_and_sell_v3_wallet_{cell}_2026_05_16"
    out_dir.mkdir(exist_ok=True)
    sg.to_parquet(out_dir / f"slug_pnl_pm{int(pre_mint_pairs)}_ps{int(post_size)}_{detector}.parquet", index=False)
    print(f"  → wrote slug_pnl_pm{int(pre_mint_pairs)}_ps{int(post_size)}_{detector}.parquet")
    return sg


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="sol_15m")
    ap.add_argument("--n-slugs", type=int, default=50)
    ap.add_argument("--pre-mint", type=float, default=50.0)
    ap.add_argument("--post-size", type=float, default=5.0)
    ap.add_argument("--detector", default="opt", choices=("opt", "q"))
    args = ap.parse_args()
    run_cell(args.cell, args.n_slugs, args.pre_mint, args.post_size, args.detector)
