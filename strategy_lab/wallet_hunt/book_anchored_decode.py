"""Use L25 book as ground truth to fix chain-fill price + side.

The OrderFilled event field mapping has edge cases that mis-decode prices
in 80%+ of fills. But we have local L25 books for every market the wallet
touched. For each chain log:
  1. The asset_id is correct (verified)
  2. The maker/taker addresses are correct (from topics)
  3. The fill timestamp is correct
  4. Therefore: price = book_ask if wallet was buyer, book_bid if seller
  5. Size = the makerAmount or takerAmount that corresponds to the token holder

The wallet's role is determined by which side HOLDS the token in this fill.
The CONTRACT (`0xe111180000...`) acts as the matcher and shows up on the
counterparty side when it manages the spread.

Usage:
  py -3 strategy_lab/wallet_hunt/book_anchored_decode.py --wallet 0x...
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (  # noqa: E402
    load_klines_asof, load_chainlink_asof, load_orderbook_l25_streaming,
    asof_strict,
)

CACHE = Path(__file__).resolve().parent / "cache"
SLUG_UD = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")
MATCHER = "0xe111180000d2663c0091e4f400237545b87b996b"


def _classify(slug):
    if not isinstance(slug, str): return (None, None, None)
    m = SLUG_UD.match(slug)
    if m: return (f"updown_{m.group(2)}", m.group(1).upper(), int(m.group(3)))
    return (None, None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    ap.add_argument("--max-slugs", type=int, default=120,
                    help="cap unique slugs to look up book for")
    args = ap.parse_args()
    w = args.wallet.lower()
    short = w[:10]

    enriched_p = CACHE / short / "trades_chain_enriched.parquet"
    if not enriched_p.exists():
        print(f"missing {enriched_p}")
        return 1
    trades = pd.read_parquet(enriched_p)

    cls = trades.slug.map(_classify)
    trades["mc"] = cls.map(lambda x: x[0])
    trades["asset_sym"] = cls.map(lambda x: x[1])
    trades["slot_start_s"] = cls.map(lambda x: x[2])

    ud = trades[
        trades.mc.fillna("").str.startswith("updown_")
        & trades.timestamp.notna()
    ].copy()
    print(f"=== {short}: {len(ud):,} up-down fills (any decode quality)")

    slug_counts = ud.slug.value_counts()
    top_slugs = list(slug_counts.head(args.max_slugs).index)
    sub = ud[ud.slug.isin(top_slugs)].copy()
    print(f"  focusing on {len(top_slugs)} top slugs ({len(sub)} fills)")

    by_asset = {a: set() for a in ("BTC", "ETH", "SOL")}
    for s in top_slugs:
        m = SLUG_UD.match(s)
        if m: by_asset[m.group(1).upper()].add(s)

    book_indexes = {}
    for asset_sym, slugs in by_asset.items():
        if not slugs: continue
        print(f"  loading {asset_sym} L25 ({len(slugs)} slugs)...")
        bi = load_orderbook_l25_streaming(asset_sym.lower(), slugs=slugs, subsample_1hz=True)
        book_indexes[asset_sym] = bi

    print("  loading binance + RTDS...")
    klines = {a: load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
              for a in ("BTC", "ETH", "SOL")}
    rtds = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}

    def book_at(asset_sym, slug, outcome, ts_us):
        bi = book_indexes.get(asset_sym, {})
        rec = bi.get((slug, outcome))
        if rec is None: return None
        ts_arr, ap, asz, bp, bsz = rec
        pos = int(np.searchsorted(ts_arr, ts_us, side="right")) - 1
        if pos < 0: return None
        ba = float(ap[pos][0]) if (len(ap[pos]) and np.isfinite(ap[pos][0])) else None
        bb = float(bp[pos][0]) if (len(bp[pos]) and np.isfinite(bp[pos][0])) else None
        return {
            "ask": ba, "bid": bb,
            "ask_sz": float(asz[pos][0]) if len(asz[pos]) else 0,
            "bid_sz": float(bsz[pos][0]) if len(bsz[pos]) else 0,
            "dt_us": int(ts_us - ts_arr[pos]),
        }

    # Re-decode each fill using the book as ground truth
    rows = []
    for r in sub.itertuples(index=False):
        ts_us = int(r.timestamp) * 1_000_000
        book = book_at(r.asset_sym, r.slug, r.outcome, ts_us)
        if book is None or book["ask"] is None or book["bid"] is None:
            continue

        # Wallet's role (verified): maker = posted limit, taker = took liquidity.
        # Maker fill price = the order they posted (assume at mid-ish or marketable).
        # Taker fill price = best_ask if BUY, best_bid if SELL.
        # We determine BUY/SELL by comparing the wallet's address to maker/taker:
        #   wallet=maker → posted limit, side based on order type (we don't know)
        #   wallet=taker → took liquidity, side based on which side they hit
        # Approximation: if maker_asset_id == this market's asset (huge uint),
        # maker is selling shares → taker is buying → if wallet=taker, wallet=BUY.
        maker_holds = str(r.maker_asset_id) == str(r.asset)
        taker_holds = str(r.taker_asset_id_raw) == str(r.asset)

        if r.wallet_is_maker:
            if maker_holds:
                # Maker posts SELL of this outcome
                side = "SELL"; price = book["bid"]  # if marketable taker, would hit our bid; conservative
                # Actually if maker is selling, taker is BUYING → fill at maker's ask (slightly above bid)
                price = book["ask"]
            else:
                # Maker posts BUY of this outcome
                side = "BUY"; price = book["bid"]
        elif r.wallet_is_taker:
            if maker_holds:
                # Maker sells shares, taker buys → wallet=taker bought at ask
                side = "BUY"; price = book["ask"]
            elif taker_holds:
                # Taker sells shares → wallet=taker sold at bid
                side = "SELL"; price = book["bid"]
            else:
                continue
        else:
            continue

        # Size: prefer the token-side amount
        try:
            if maker_holds:
                size = int(r.maker_amount_raw) / 1e6
            elif taker_holds:
                size = int(r.taker_amount_raw) / 1e6
            else:
                size = 0
        except Exception:
            size = 0
        if size <= 0 or not 0 < price < 1:
            continue

        # Binance + RTDS signals
        slot_start_us = int(r.slot_start_s) * 1_000_000
        end_us, prices = klines[r.asset_sym]
        px_at_slot_start = asof_strict(end_us, prices, slot_start_us)
        px_2m_pre = asof_strict(end_us, prices, slot_start_us - 120_000_000)
        ret_2m_pre = float("nan")
        if px_at_slot_start and px_2m_pre and px_at_slot_start > 0:
            ret_2m_pre = float(np.log(px_at_slot_start / px_2m_pre))
        binance_says = ("Up" if ret_2m_pre > 0 else "Down") if not np.isnan(ret_2m_pre) else None

        rows.append({
            "ts_s": int(r.timestamp),
            "slug": r.slug,
            "asset_sym": r.asset_sym,
            "mc": r.mc,
            "outcome": r.outcome,
            "side": side,
            "price": price,
            "size": size,
            "usd": size * price,
            "is_maker": bool(r.wallet_is_maker),
            "book_ask": book["ask"],
            "book_bid": book["bid"],
            "book_spread": book["ask"] - book["bid"],
            "book_dt_us": book["dt_us"],
            "offset_from_slot_start_s": int(r.timestamp) - int(r.slot_start_s),
            "ret_2m_pre": ret_2m_pre,
            "matches_binance": (binance_says == r.outcome) if binance_says else None,
            "binance_says": binance_says,
        })

    df = pd.DataFrame(rows)
    out = CACHE / short / "fills_book_decoded.parquet"
    df.to_parquet(out, index=False)
    print(f"\n  saved {len(df)} book-decoded fills -> {out}")

    if df.empty:
        return 0

    print(f"\n=== {short}: BOOK-ANCHORED DECODE ===")
    print(f"  side: {df.side.value_counts().to_dict()}")
    print(f"  maker_pct: {100*df.is_maker.mean():.1f}%")
    print(f"  price p25={df.price.quantile(0.25):.3f}  med={df.price.median():.3f}  p75={df.price.quantile(0.75):.3f}")
    print(f"  spread at fill p25={df.book_spread.quantile(0.25):.4f}  med={df.book_spread.median():.4f}  p75={df.book_spread.quantile(0.75):.4f}")
    print(f"  size shares p25={df['size'].quantile(0.25):.1f}  med={df['size'].median():.1f}  p75={df['size'].quantile(0.75):.1f}")
    print(f"  fill notional p25=${df.usd.quantile(0.25):.2f}  med=${df.usd.median():.2f}  p75=${df.usd.quantile(0.75):.2f}  total=${df.usd.sum():,.2f}")
    print(f"\n  offset from slot_start (s):")
    print(f"    p25={int(df.offset_from_slot_start_s.quantile(0.25))}  med={int(df.offset_from_slot_start_s.median())}  p75={int(df.offset_from_slot_start_s.quantile(0.75))}")
    # By 5m vs 15m
    for mc in ("updown_5m", "updown_15m"):
        s = df[df.mc == mc]
        if len(s):
            print(f"    {mc}: med={int(s.offset_from_slot_start_s.median())}s  p25={int(s.offset_from_slot_start_s.quantile(0.25))}s  p75={int(s.offset_from_slot_start_s.quantile(0.75))}s")

    print(f"\n=== Signal alignment (per outcome side picked) ===")
    valid = df[df.matches_binance.notna()]
    for side in ("BUY", "SELL"):
        s = valid[valid.side == side]
        if len(s) == 0: continue
        match_pct = 100 * s.matches_binance.mean()
        print(f"  {side}: n={len(s)}  matches_binance={match_pct:.1f}%")
    overall_match = 100 * valid.matches_binance.mean()
    print(f"  OVERALL: n={len(valid)}  matches_binance={overall_match:.1f}%")

    # Per-leg aggregates
    legs = df.groupby(["slug", "outcome"], as_index=False).agg(
        n_trades=("side", "size"),
        n_buys=("side", lambda s: (s == "BUY").sum()),
        n_sells=("side", lambda s: (s == "SELL").sum()),
        buy_sz=("size", lambda s: df.loc[s.index].loc[df.side == "BUY", "size"].sum()),
        sell_sz=("size", lambda s: df.loc[s.index].loc[df.side == "SELL", "size"].sum()),
        avg_buy_px=("price", lambda s: df.loc[s.index].loc[df.side == "BUY", "price"].mean()),
        avg_sell_px=("price", lambda s: df.loc[s.index].loc[df.side == "SELL", "price"].mean()),
        first_offset=("offset_from_slot_start_s", "min"),
        last_offset=("offset_from_slot_start_s", "max"),
    )
    legs["leftover"] = legs.buy_sz - legs.sell_sz
    legs["captured_spread"] = legs.avg_sell_px - legs.avg_buy_px
    print(f"\n=== {len(legs)} legs decoded ===")
    print(f"  pct only-BUY:  {100*(legs.n_sells==0).mean():.1f}%")
    print(f"  pct only-SELL: {100*(legs.n_buys==0).mean():.1f}%")
    print(f"  pct both:      {100*((legs.n_buys>0)&(legs.n_sells>0)).mean():.1f}%")
    both = legs[(legs.n_buys > 0) & (legs.n_sells > 0)]
    if len(both):
        print(f"  for BOTH-SIDES legs: avg captured spread = ${both.captured_spread.mean():+.4f}  "
              f"(positive = sold higher than bought)")
    print()
    print("Top 10 legs by n_trades:")
    cols = ["slug","outcome","n_trades","n_buys","n_sells",
            "avg_buy_px","avg_sell_px","buy_sz","sell_sz","leftover",
            "first_offset","last_offset","captured_spread"]
    print(legs.sort_values("n_trades", ascending=False).head(10)[cols].round(3).to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
