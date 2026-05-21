"""Deep-dive on a single wallet's trading behavior — strategy fingerprinting.

Per market:
  - timeline of BUY/SELL with timestamps and prices
  - net position over time
  - inferred profit/loss per market
  - average hold time

Across markets:
  - is the bot a market-maker (alternating BUY/SELL similar size at tight spread)?
  - is it a momentum taker (clusters of BUY or SELL after a price move)?
  - is it a mean-reverter (BUY at dips, SELL at peaks)?
  - what's the per-market WR + PnL distribution?
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent / "cache"


def classify_slug(slug):
    if not isinstance(slug, str):
        return ("unknown", None, None)
    m = re.match(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$", slug)
    if m:
        return (f"updown_{m.group(2)}", m.group(1).upper(), int(m.group(3)))
    return ("other", None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    args = ap.parse_args()
    short = args.wallet.lower()[:10]
    trades = pd.read_parquet(CACHE / f"{short}_trades.parquet")
    cls = trades.slug.map(classify_slug)
    trades["market_class"] = cls.map(lambda x: x[0])
    trades["mkt_asset"] = cls.map(lambda x: x[1])
    trades["slot_start_s"] = cls.map(lambda x: x[2])

    # Per-market per-side aggregates
    ud = trades[trades.market_class.str.startswith("updown_") & trades.slot_start_s.notna()].copy()
    ud["slot_start_s"] = ud.slot_start_s.astype("int64")
    ud["window_s"] = ud.market_class.map({"updown_5m": 300, "updown_15m": 900})
    ud["offset_s"] = ud.timestamp.astype("int64") - ud.slot_start_s
    ud["usd_notional"] = ud["size"] * ud["price"]
    ud["signed_size"] = np.where(ud.side == "BUY", ud["size"], -ud["size"])
    ud["signed_usd"]  = np.where(ud.side == "BUY", -ud.usd_notional, ud.usd_notional)
    # ^ negative cash flow when BUYing (we spend), positive when SELLing

    # Per (condition, asset/outcome) — to separate Up vs Down legs within same market
    grp_cols = ["conditionId", "outcome", "slug", "market_class", "mkt_asset", "slot_start_s"]
    per_leg = ud.groupby(grp_cols, as_index=False).agg(
        n_trades=("side", "size"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        buy_shares=("size", lambda s: ud.loc[s.index].loc[ud.side == "BUY", "size"].sum()),
        sell_shares=("size", lambda s: ud.loc[s.index].loc[ud.side == "SELL", "size"].sum()),
        net_shares=("signed_size", "sum"),
        net_cash=("signed_usd", "sum"),
        avg_buy_px=("price", lambda s: ud.loc[s.index].loc[ud.side == "BUY", "price"].mean()),
        avg_sell_px=("price", lambda s: ud.loc[s.index].loc[ud.side == "SELL", "price"].mean()),
        first_ts=("timestamp", "min"),
        last_ts=("timestamp", "max"),
        first_offset=("offset_s", "min"),
        last_offset=("offset_s", "max"),
    )
    per_leg["hold_span_s"] = per_leg.last_ts - per_leg.first_ts
    per_leg["leftover_shares"] = per_leg.net_shares   # >0 = still holding longs, <0 = short

    # Realized PnL (closed portion) = sells_usd - buys_usd_on_matched_shares
    # Approximation: matched_shares = min(buy_shares, sell_shares).
    # realized = (avg_sell_px - avg_buy_px) * matched_shares
    per_leg["matched_shares"] = per_leg[["buy_shares", "sell_shares"]].min(axis=1)
    per_leg["realized_pnl"] = (per_leg.avg_sell_px - per_leg.avg_buy_px) * per_leg.matched_shares
    per_leg = per_leg.fillna({"realized_pnl": 0})

    print(f"=== {len(per_leg)} (market, outcome) legs traded ===\n")
    print("=== PER-MARKET BEHAVIOR (top 12 by trade count) ===")
    show = per_leg.sort_values("n_trades", ascending=False).head(12)
    print(show[["slug", "outcome", "n_trades", "n_buys", "n_sells",
                "buy_shares", "sell_shares", "avg_buy_px", "avg_sell_px",
                "leftover_shares", "realized_pnl", "first_offset", "last_offset"]]
          .round(3).to_string(index=False))
    print()

    # Identify strategies by behavior:
    # (A) Pure market-maker: n_buys ≈ n_sells, similar shares, avg_sell > avg_buy
    # (B) Directional taker: only buys (or only sells), leftover_shares ≠ 0
    # (C) Liquidity providing late-favorite: avg_buy_px > 0.85, holds to resolution
    mm_mask = (per_leg.n_buys > 0) & (per_leg.n_sells > 0)
    mm = per_leg[mm_mask]
    only_buy = per_leg[(per_leg.n_buys > 0) & (per_leg.n_sells == 0)]
    only_sell = per_leg[(per_leg.n_buys == 0) & (per_leg.n_sells > 0)]
    print(f"=== Strategy classification ===")
    print(f"  market-making (both sides):  {len(mm)} legs ({100*len(mm)/len(per_leg):.1f}%)")
    print(f"  only-buy directional:        {len(only_buy)} legs ({100*len(only_buy)/len(per_leg):.1f}%)")
    print(f"  only-sell directional:       {len(only_sell)} legs ({100*len(only_sell)/len(per_leg):.1f}%)")
    print()
    if len(mm):
        print(f"  MM avg_buy_px mean:   {mm.avg_buy_px.mean():.4f}")
        print(f"  MM avg_sell_px mean:  {mm.avg_sell_px.mean():.4f}")
        print(f"  MM avg spread captured: {(mm.avg_sell_px - mm.avg_buy_px).mean():.4f}")
        print(f"  MM realized PnL total: ${mm.realized_pnl.sum():.2f}  mean ${mm.realized_pnl.mean():.4f}")
        print(f"  MM positive legs:     {(mm.realized_pnl > 0).sum()}/{len(mm)}")
    print()
    if len(only_buy):
        print(f"  Only-BUY avg_px:      {only_buy.avg_buy_px.mean():.4f}")
        print(f"  Only-BUY leftover total $ (held to resolution): "
              f"${only_buy.eval('avg_buy_px * leftover_shares').sum():.2f}")
    print()

    # Within-market timing — pick the most-traded market for a microscope view
    top = show.iloc[0]
    print(f"=== Microscope: most-traded leg ({top.slug} / {top.outcome}, n={top.n_trades}) ===")
    one = ud[(ud.conditionId == top.conditionId) & (ud.outcome == top.outcome)].sort_values("timestamp")
    one_show = one[["timestamp", "offset_s", "side", "size", "price"]].copy()
    one_show["cumulative_shares"] = one.signed_size.cumsum().values
    one_show["cumulative_cash"]  = one.signed_usd.cumsum().values
    print(one_show.head(30).round(3).to_string(index=False))
    print("...")
    print(one_show.tail(5).round(3).to_string(index=False))
    print()

    # Inter-trade gap analysis
    one["gap_s"] = one.timestamp.diff()
    print(f"  inter-trade gap stats: mean={one.gap_s.mean():.1f}s  median={one.gap_s.median():.1f}s  "
          f"p95={one.gap_s.quantile(0.95):.1f}s")
    print()

    # 5m vs 15m comparison
    print("=== 5m vs 15m breakdown ===")
    for tf in ("updown_5m", "updown_15m"):
        sub = per_leg[per_leg.market_class == tf]
        if not len(sub):
            continue
        print(f"  {tf}: {len(sub)} legs, avg trades/leg={sub.n_trades.mean():.1f}")
        print(f"      realized PnL total ${sub.realized_pnl.sum():.2f}, leftover @ avg_buy ${sub.eval('avg_buy_px * leftover_shares').sum():.2f}")

    # Save per-leg summary
    per_leg.to_parquet(CACHE / f"{short}_per_leg.parquet", index=False)
    print(f"\n--> per-leg summary saved: {CACHE / f'{short}_per_leg.parquet'}")


if __name__ == "__main__":
    main()
