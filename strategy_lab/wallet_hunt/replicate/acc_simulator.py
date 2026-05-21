"""ACC (Accumulator) backtest simulator — mirror of v3 mint-and-sell.

Logic:
  - At each L25 tick where conditions hold, post limit BID Up at best_bid_up
    and BID Down at best_bid_dn (size = CLOB-min 5 shares).
  - For each taker SELL trade in the trades parquet:
      → if trade.price <= our_bid AND we have an active bid on that side:
        we get filled (subject to queue position approximation)
        cash_spent += fill_size × fill_price
        rebates += fill_size × maker_rebate(fill_price)
        inv += fill_size
  - Whenever min(inv_up, inv_dn) >= merge_threshold:
        pairs = min(inv_up, inv_dn)
        cash_recovered += pairs × $1.00     (NegRiskAdapter relay returns $1/pair)
        inv_up -= pairs
        inv_dn -= pairs
  - At slug end (offset ~336s mark):
        Force merge of any remaining paired
  - At slug resolution:
        Redeem leftover single-side: cash_recovered += leftover × $1 if winning
        (losing side worth $0)

Slug PnL = cash_recovered + rebates - cash_spent

We validate vs the wallet 0x04b6d7e9 by running on the EXACT 196 slugs they
were active on and comparing per-slug PnL.
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

FEE_RATE = bps_to_rate(DEFAULT_CRYPTO_FEE_BPS)
CLOB_MIN_ORDER = 5.0
NEGRISK_ADAPTER = "0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0"


def simulate_slug_acc(
    slug: str, outcome: str,
    trades_up: pd.DataFrame, trades_dn: pd.DataFrame,
    ops: pd.DataFrame,
    post_size: float = CLOB_MIN_ORDER,
    min_bid_price: float = 0.05,
    max_bid_price: float = 0.95,
    max_sum_bids: float = 1.00,
    merge_threshold: float = 5.0,
    stop_post_offset_s: float = 270.0,
    merge_offset_s: float = 336.0,
    slot_start_us: int = 0,
    queue_aware: bool = False,
) -> dict:
    """Simulate ACC strategy on one slug.

    Returns slug-level summary.
    """
    inv_up = 0.0
    inv_dn = 0.0
    cash_spent = 0.0
    cash_recovered = 0.0
    rebates = 0.0
    fills_up = 0
    fills_dn = 0
    merges = 0
    pairs_merged = 0

    # Build sorted timeline of (ts, best_bid_up, best_bid_dn, bid_size_up, bid_size_dn) from ops
    op_arr = ops.sort_values("ts").reset_index(drop=True)
    op_ts = op_arr.ts.values.astype(np.int64)
    op_bu = op_arr.bid_up.values.astype(np.float64)
    op_bd = op_arr.bid_dn.values.astype(np.float64)

    # NOTE: ops parquet has 'size_up'/'size_dn' which are AT BEST ASK
    # For BIDS we'd want bid_size_up/dn but they're not in the v2 opportunities parquet
    # Approximation: use the visible ask size as a proxy for visible bid size
    op_su = op_arr.size_up.values.astype(np.float64)
    op_sd = op_arr.size_dn.values.astype(np.float64)

    def recent_book(ts_us: int):
        """Find most recent op tick at or before ts_us, within last 30s."""
        idx = np.searchsorted(op_ts, ts_us, side="right") - 1
        if idx < 0:
            return None
        if ts_us - op_ts[idx] > 30_000_000:
            return None
        return op_bu[idx], op_bd[idx], op_su[idx], op_sd[idx]

    def process_taker_sell(side: str, ts: int, price: float, size: float):
        """A taker just SOLD at `price`. If our bid on this side >= price, we fill."""
        nonlocal inv_up, inv_dn, cash_spent, rebates, fills_up, fills_dn
        # Check elapsed time since slot_start
        if slot_start_us > 0:
            offset_s = (ts - slot_start_us) / 1_000_000
            if offset_s > stop_post_offset_s:
                return  # Stop posting in last 30s before slug closes

        book = recent_book(ts)
        if book is None:
            return
        bu, bd, su, sd = book
        our_bid = bu if side == "Up" else bd
        sum_bids = bu + bd

        # Entry filters
        if our_bid < min_bid_price or our_bid > max_bid_price:
            return
        if sum_bids > max_sum_bids:
            return
        # Trade must have hit our price or higher (we're at top of book or close)
        if price > our_bid + 0.001:
            return  # Trade went off at higher price — we're not at top of queue

        # Queue position: our share of trade volume
        visible_queue = su if side == "Up" else sd
        if queue_aware and visible_queue > 0:
            our_share = post_size / (post_size + visible_queue)
        else:
            our_share = 1.0
        our_fill = min(size * our_share, post_size)
        if our_fill <= 0:
            return

        if side == "Up":
            inv_up += our_fill
            fills_up += 1
        else:
            inv_dn += our_fill
            fills_dn += 1
        cash_spent += our_fill * price
        rebates += our_fill * poly_maker_rebate_per_share(price, FEE_RATE)

    # Sort all trades by ts, interleave Up/Down
    parts = []
    if trades_up is not None and len(trades_up):
        for r in trades_up.itertuples(index=False):
            parts.append(("Up", int(r.timestamp_us), float(r.price), float(r.size), r.side))
    if trades_dn is not None and len(trades_dn):
        for r in trades_dn.itertuples(index=False):
            parts.append(("Down", int(r.timestamp_us), float(r.price), float(r.size), r.side))
    parts.sort(key=lambda x: x[1])

    last_merge_check_ts = 0
    for side, ts, price, size, taker_side in parts:
        if str(taker_side).lower() != "sell":
            continue  # Only taker SELLs hit our BIDs
        process_taker_sell(side, ts, price, size)

        # Periodically check for merge opportunity
        if (ts - last_merge_check_ts) > 10_000_000:  # every 10s
            pairs_now = int(min(inv_up, inv_dn))
            if pairs_now >= merge_threshold:
                cash_recovered += pairs_now * 1.0
                inv_up -= pairs_now
                inv_dn -= pairs_now
                pairs_merged += pairs_now
                merges += 1
            last_merge_check_ts = ts

    # Final merge at end of slug (force merge any remaining paired inventory)
    final_pairs = int(min(inv_up, inv_dn))
    if final_pairs > 0:
        cash_recovered += final_pairs * 1.0
        inv_up -= final_pairs
        inv_dn -= final_pairs
        pairs_merged += final_pairs
        merges += 1

    # Settlement: redeem any leftover single-side
    redeem_up = inv_up * (1.0 if outcome == "Up" else 0.0)
    redeem_dn = inv_dn * (1.0 if outcome == "Down" else 0.0)
    redeem = redeem_up + redeem_dn

    slug_pnl = cash_recovered + rebates + redeem - cash_spent

    return {
        "slug": slug, "outcome": outcome,
        "fills_up": fills_up, "fills_dn": fills_dn,
        "shares_acquired_up": float(inv_up + (pairs_merged if outcome != "Up" else 0)) if False else 0,
        "cash_spent": cash_spent, "cash_recovered": cash_recovered,
        "rebates": rebates, "redeem": redeem,
        "merges": merges, "pairs_merged": pairs_merged,
        "leftover_up": inv_up, "leftover_dn": inv_dn,
        "slug_pnl": slug_pnl,
        "avg_buy_price": (cash_spent / max(fills_up + fills_dn, 1) / max(post_size, 1)) if (fills_up + fills_dn) > 0 else float("nan"),
    }


def run_cell(cell: str, n_slugs: int = 50, post_size: float = CLOB_MIN_ORDER,
             merge_threshold: float = 5.0, queue_aware: bool = False,
             slug_rank: tuple = (50, 150)):
    asset = cell.split("_")[0]
    R = ROOT / "data" / "v4" / "canonical" / "_results"
    op = pd.read_parquet(R / f"mint_and_sell_v2_{cell}_2026_05_16" / "opportunities.parquet")
    res = load_resolutions(assets=[asset.upper()], timeframes=[cell.split("_")[1]])[["slug","outcome"]].drop_duplicates(subset="slug")
    op = op.merge(res, on="slug", how="inner")

    tr_path = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset}.parquet"
    tr_slugs = set(pd.read_parquet(tr_path, columns=["slug"])["slug"].unique())
    op = op[op.slug.isin(tr_slugs)].reset_index(drop=True)

    counts = op.groupby("slug").size().sort_values(ascending=False)
    picked = counts.iloc[slug_rank[0]:slug_rank[1]].index.tolist()
    op = op[op.slug.isin(picked)].reset_index(drop=True)
    print(f"[{cell}] {len(picked)} slugs (rank {slug_rank}), {len(op):,} L25 ticks", flush=True)

    trades = pd.read_parquet(tr_path, columns=["timestamp_us","slug","outcome","price","size","side"])
    trades = trades[trades.slug.isin(picked)].reset_index(drop=True)
    print(f"[{cell}] {len(trades):,} trades on these slugs", flush=True)

    rows = []
    for slug in picked:
        sub_op = op[op.slug == slug]
        if len(sub_op) == 0:
            continue
        outcome = sub_op.outcome.iloc[0]
        t_up = trades[(trades.slug == slug) & (trades.outcome == "Up")]
        t_dn = trades[(trades.slug == slug) & (trades.outcome == "Down")]

        # Derive slot_start_us from slug name (suffix is slot_start in seconds)
        slot_start_s = int(slug.rsplit("-", 1)[1])
        slot_start_us = slot_start_s * 1_000_000

        rows.append(simulate_slug_acc(
            slug, outcome, t_up, t_dn, sub_op,
            post_size=post_size,
            merge_threshold=merge_threshold,
            slot_start_us=slot_start_us,
            queue_aware=queue_aware,
        ))
    sg = pd.DataFrame(rows)

    print(f"\n=== {cell} ACC SIM (post={post_size}, merge_thr={merge_threshold}, queue_aware={queue_aware}) ===")
    print(f"n_slugs={len(sg)}, pct_positive={(sg.slug_pnl > 0).mean()*100:.1f}%")
    print(f"Slug PnL: mean ${sg.slug_pnl.mean():+.3f} | median ${sg.slug_pnl.median():+.3f} | total ${sg.slug_pnl.sum():+.2f}")
    print(f"Fills: median up {sg.fills_up.median():.0f}, dn {sg.fills_dn.median():.0f}")
    print(f"Cash spent: median ${sg.cash_spent.median():.2f} | Cash recovered: median ${sg.cash_recovered.median():.2f}")
    print(f"Pairs merged: median {sg.pairs_merged.median():.0f} | Merges: median {sg.merges.median():.0f}")
    print(f"Leftover Up: median {sg.leftover_up.median():.1f}, Down: median {sg.leftover_dn.median():.1f}")
    print(f"Redeem income: median ${sg.redeem.median():.2f}")

    # Edge per pair-rotation
    if sg.pairs_merged.sum() > 0:
        edge_per_pair = sg.slug_pnl.sum() / sg.pairs_merged.sum()
        print(f"\n  Edge per pair-merged: ${edge_per_pair:+.4f}")
        print(f"  Total pairs merged: {sg.pairs_merged.sum():.0f}")

    # Daily projection
    n_slugs_universe = res.slug.nunique()
    proj = sg.slug_pnl.mean() * n_slugs_universe / 21.0
    print(f"\n  Projection: ${proj:+,.2f}/day on {n_slugs_universe:,} 21d slugs at this scale")

    out_dir = R / f"acc_sim_{cell}_2026_05_18"
    out_dir.mkdir(exist_ok=True)
    sg.to_parquet(out_dir / f"slug_pnl_ps{int(post_size)}_mt{int(merge_threshold)}.parquet", index=False)
    return sg


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="btc_5m")
    ap.add_argument("--n-slugs", type=int, default=100)
    ap.add_argument("--post-size", type=float, default=5.0)
    ap.add_argument("--merge-threshold", type=float, default=5.0)
    ap.add_argument("--queue-aware", action="store_true")
    ap.add_argument("--slug-rank-from", type=int, default=50)
    ap.add_argument("--slug-rank-to", type=int, default=150)
    args = ap.parse_args()
    run_cell(args.cell, args.n_slugs, args.post_size, args.merge_threshold,
             args.queue_aware, slug_rank=(args.slug_rank_from, args.slug_rank_to))
