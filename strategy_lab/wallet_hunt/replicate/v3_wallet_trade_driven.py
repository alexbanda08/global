"""V3 wallet simulator — TRADE-DRIVEN fills.

The previous v3_wallet_inventory_simulator booked fill cash at the ask price
at POST time, which is wrong: real makers cancel + repost as the book moves,
so the cash they actually receive equals the trade price at FILL time.

This simulator iterates the trades parquet directly. For each (slug, outcome)
taker BUY:
  - If we have inventory of that side: sell min(remaining_inv, trade_size, our_post_size) at trade_price
  - Cash += sold_shares × trade_price
  - Rebate += sold_shares × maker_rebate(trade_price)
  - Inventory -= sold_shares
  - Skip trades where trade_price < min_fill_price (we wouldn't have posted that low)

Min fill price gate: only sell when sum_asks_recent > 1.005 (matches v2 entry).
At each trade, we check the most recent L25 book snapshot — if sum_asks > 1.005
at that moment, sell; otherwise we wouldn't have an active order.

This model better matches wallet behavior:
  - Active limit always at current best ask (we re-post on every L25 update)
  - Cash equals trade price (not post-time price)
  - Rebate based on actual fill price
  - Inventory cap via pre-mint pairs
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


CLOB_MIN_ORDER_SHARES = 5.0  # Polymarket CLOB minimum order size per side


def simulate_slug_trade_driven(
    slug: str, outcome: str,
    trades_up: pd.DataFrame, trades_dn: pd.DataFrame,
    ops: pd.DataFrame,
    pre_mint_pairs: float, post_size: float = CLOB_MIN_ORDER_SHARES,
    min_sum_asks: float = 1.005,
    queue_aware: bool = False,
    min_post_shares: float = CLOB_MIN_ORDER_SHARES,
) -> dict:
    """One slug simulation, iterating the trades parquet directly.

    For queue awareness, divide fill share by N_makers_at_price (= visible
    queue_size / our_post_size approx).
    """
    inv_up = pre_mint_pairs
    inv_dn = pre_mint_pairs
    mint_cost = pre_mint_pairs * 1.0
    cash = 0.0
    rebates = 0.0
    fills_up = 0
    fills_dn = 0
    shares_sold_up = 0.0
    shares_sold_dn = 0.0

    # Build a sorted timeline of (ts, sum_asks, ask_up, ask_dn, size_up, size_dn) from ops
    # for quick lookup of "what was sum_asks recently" at each trade ts
    op_arr = ops.sort_values("ts").reset_index(drop=True)
    op_ts = op_arr.ts.values.astype(np.int64)
    op_au = op_arr.ask_up.values.astype(np.float64)
    op_ad = op_arr.ask_dn.values.astype(np.float64)
    op_su = op_arr.size_up.values.astype(np.float64)
    op_sd = op_arr.size_dn.values.astype(np.float64)

    def recent_book(ts_us: int):
        """Find most recent op (ts ≤ ts_us) within last 30s."""
        idx = np.searchsorted(op_ts, ts_us, side="right") - 1
        if idx < 0:
            return None
        if ts_us - op_ts[idx] > 30_000_000:
            return None
        return op_au[idx], op_ad[idx], op_su[idx], op_sd[idx]

    def process_trade(side: str, ts: int, price: float, size: float):
        nonlocal inv_up, inv_dn, cash, rebates, fills_up, fills_dn, shares_sold_up, shares_sold_dn
        book = recent_book(ts)
        if book is None:
            return
        au, ad, su, sd = book
        if (au + ad) < min_sum_asks:
            return
        # Our maker SELL at the side's ask
        our_ask = au if side == "Up" else ad
        # Trade price must be >= our_ask for our order to fill
        if price < our_ask:
            return
        # Queue cap: our share of trade volume = our_post_size / (our_post_size + visible_queue)
        visible_queue = su if side == "Up" else sd
        if queue_aware and visible_queue > 0:
            our_share = post_size / (post_size + visible_queue)
        else:
            our_share = 1.0
        our_fill = min(size * our_share, post_size)
        if side == "Up":
            # CLOB minimum: if we can't post 5+ shares, our order isn't on the book
            if inv_up < min_post_shares:
                return
            our_fill = min(our_fill, inv_up)
            if our_fill <= 0:
                return
            cash += our_fill * price
            rebates += our_fill * poly_maker_rebate_per_share(price, FEE_RATE)
            inv_up -= our_fill
            fills_up += 1
            shares_sold_up += our_fill
        else:
            if inv_dn < min_post_shares:
                return
            our_fill = min(our_fill, inv_dn)
            if our_fill <= 0:
                return
            cash += our_fill * price
            rebates += our_fill * poly_maker_rebate_per_share(price, FEE_RATE)
            inv_dn -= our_fill
            fills_dn += 1
            shares_sold_dn += our_fill

    # Merge trades sorted by ts, interleave Up and Down
    parts = []
    if trades_up is not None and len(trades_up):
        for r in trades_up.itertuples(index=False):
            parts.append(("Up", int(r.timestamp_us), float(r.price), float(r.size), r.side))
    if trades_dn is not None and len(trades_dn):
        for r in trades_dn.itertuples(index=False):
            parts.append(("Down", int(r.timestamp_us), float(r.price), float(r.size), r.side))
    parts.sort(key=lambda x: x[1])
    for side, ts, price, size, taker_side in parts:
        if str(taker_side).lower() != "buy":
            continue
        if inv_up <= 0 and inv_dn <= 0:
            break
        process_trade(side, ts, price, size)

    redeem_up = inv_up * (1.0 if outcome == "Up" else 0.0)
    redeem_dn = inv_dn * (1.0 if outcome == "Down" else 0.0)
    redeem = redeem_up + redeem_dn

    slug_pnl = cash + rebates + redeem - mint_cost
    return {
        "slug": slug, "outcome": outcome,
        "pre_mint": pre_mint_pairs, "mint_cost": mint_cost,
        "fills_up": fills_up, "fills_dn": fills_dn,
        "shares_sold_up": shares_sold_up, "shares_sold_dn": shares_sold_dn,
        "inv_remaining_up": inv_up, "inv_remaining_dn": inv_dn,
        "cash": cash, "rebates": rebates, "redeem": redeem,
        "slug_pnl": slug_pnl,
        "avg_fill_px_up": (cash * (shares_sold_up/(shares_sold_up+shares_sold_dn))) / shares_sold_up if shares_sold_up > 0 else float("nan"),
    }


def run_cell(cell: str, n_slugs: int = 50, pre_mint: float = 50.0,
             post_size: float = 5.0, min_sum_asks: float = 1.005,
             queue_aware: bool = False):
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
    print(f"[{cell}] {len(picked)} slugs, {len(op):,} ops", flush=True)

    trades = pd.read_parquet(tr_path, columns=["timestamp_us","slug","outcome","price","size","side"])
    trades = trades[trades.slug.isin(picked)].reset_index(drop=True)
    print(f"[{cell}] {len(trades):,} trades", flush=True)

    rows = []
    for slug in picked:
        sub_op = op[op.slug == slug]
        if len(sub_op) == 0:
            continue
        outcome = sub_op.outcome.iloc[0]
        t_up = trades[(trades.slug == slug) & (trades.outcome == "Up")]
        t_dn = trades[(trades.slug == slug) & (trades.outcome == "Down")]
        rows.append(simulate_slug_trade_driven(
            slug, outcome, t_up, t_dn, sub_op,
            pre_mint_pairs=pre_mint, post_size=post_size,
            min_sum_asks=min_sum_asks, queue_aware=queue_aware,
        ))
    sg = pd.DataFrame(rows)

    qa_tag = "queue" if queue_aware else "opt"
    print(f"\n=== {cell} TRADE-DRIVEN (pre_mint={pre_mint}, post_size={post_size}, min_sum={min_sum_asks}, {qa_tag}) ===")
    print(f"n_slugs={len(sg)}, pct_positive={(sg.slug_pnl > 0).mean()*100:.1f}%")
    print(f"Slug PnL: mean ${sg.slug_pnl.mean():+.3f} | median ${sg.slug_pnl.median():+.3f} | total ${sg.slug_pnl.sum():+.2f}")
    print(f"Shares sold: up avg {sg.shares_sold_up.mean():.1f}, dn avg {sg.shares_sold_dn.mean():.1f}")
    print(f"Inv remaining: up avg {sg.inv_remaining_up.mean():.1f}, dn avg {sg.inv_remaining_dn.mean():.1f}")
    print(f"Cash: ${sg.cash.mean():+.2f}/slug | Rebates: ${sg.rebates.mean():+.4f}/slug | Redeem: ${sg.redeem.mean():+.2f}/slug | Cost: $-{sg.mint_cost.mean():.2f}/slug")

    n_slugs_universe = res.slug.nunique()
    proj = sg.slug_pnl.mean() * n_slugs_universe / 21.0
    print(f"\n  Projection: ${proj:+,.2f}/day across {n_slugs_universe:,} 21d slugs at this scale")

    out_dir = R / f"mint_and_sell_v3_trade_driven_{cell}_2026_05_16"
    out_dir.mkdir(exist_ok=True)
    sg.to_parquet(out_dir / f"slug_pnl_pm{int(pre_mint)}_ps{int(post_size)}_sum{int(min_sum_asks*1000)}_{qa_tag}.parquet", index=False)
    return sg


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cell", default="sol_15m")
    ap.add_argument("--n-slugs", type=int, default=50)
    ap.add_argument("--pre-mint", type=float, default=50.0)
    ap.add_argument("--post-size", type=float, default=5.0)
    ap.add_argument("--min-sum-asks", type=float, default=1.005)
    ap.add_argument("--queue-aware", action="store_true")
    args = ap.parse_args()
    run_cell(args.cell, args.n_slugs, args.pre_mint, args.post_size,
             args.min_sum_asks, args.queue_aware)
