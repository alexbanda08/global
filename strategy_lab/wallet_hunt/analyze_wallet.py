"""Initial analysis of a Polymarket wallet's trade book.

Output: console report + CSVs/parquets to wallet_hunt/cache/.
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


SLUG_RE_UPDOWN_5M  = re.compile(r"^(btc|eth|sol)-updown-5m-(\d+)$")
SLUG_RE_UPDOWN_15M = re.compile(r"^(btc|eth|sol)-updown-15m-(\d+)$")
SLUG_RE_LONG       = re.compile(r"^(bitcoin|ethereum|solana)-up-or-down")


def classify_slug(slug: str) -> tuple[str, str | None, int | None]:
    """Return (market_class, asset, slot_start_s)."""
    if not isinstance(slug, str):
        return ("unknown", None, None)
    m = SLUG_RE_UPDOWN_5M.match(slug)
    if m:
        return (f"updown_5m", m.group(1).upper(), int(m.group(2)))
    m = SLUG_RE_UPDOWN_15M.match(slug)
    if m:
        return (f"updown_15m", m.group(1).upper(), int(m.group(2)))
    if SLUG_RE_LONG.match(slug):
        return ("updown_long_form", None, None)
    return ("other", None, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    args = ap.parse_args()
    w = args.wallet.lower()
    short = w[:10]
    cache = Path(__file__).resolve().parent / "cache"

    trades = pd.read_parquet(cache / f"{short}_trades.parquet")
    print(f"=== Wallet {w}")
    print(f"=== Trade window: {pd.to_datetime(trades.timestamp.min(), unit='s', utc=True)} → "
          f"{pd.to_datetime(trades.timestamp.max(), unit='s', utc=True)}")
    span_min = (trades.timestamp.max() - trades.timestamp.min()) / 60.0
    print(f"=== Span: {span_min:.1f} min ({span_min/60:.1f} h)")
    print(f"=== Trades: {len(trades):,}")
    print(f"=== Trades / minute: {len(trades) / span_min:.2f}")
    print(f"=== Columns: {list(trades.columns)}")
    print()

    # Classify markets
    cls = trades.slug.map(classify_slug)
    trades["market_class"] = cls.map(lambda x: x[0])
    trades["mkt_asset"]    = cls.map(lambda x: x[1])
    trades["slot_start_s"] = cls.map(lambda x: x[2])

    print("=== Market class distribution ===")
    print(trades.market_class.value_counts().to_string())
    print()
    print("=== By asset (up-down markets) ===")
    print(trades[trades.market_class.str.startswith("updown_")]
                .groupby(["market_class", "mkt_asset"]).size().to_string())
    print()

    print("=== Side distribution (BUY/SELL) ===")
    print(trades.side.value_counts().to_string())
    print()

    print("=== Size distribution (shares) ===")
    print(trades["size"].describe().round(2).to_string())
    print()

    print("=== Price distribution (fill price) ===")
    print(trades["price"].describe().round(4).to_string())
    print()

    # Compute usd notional per trade
    trades["usd_notional"] = trades["size"] * trades["price"]
    print("=== USD notional per trade ===")
    print(trades.usd_notional.describe().round(2).to_string())
    print()

    # Pick out updown 5m/15m for deep dive
    ud = trades[trades.market_class.str.startswith("updown_") & trades.slot_start_s.notna()].copy()
    if len(ud):
        ud["slot_start_s"] = ud.slot_start_s.astype("int64")
        # Map timeframe to window seconds
        ud["window_s"] = ud.market_class.map({"updown_5m": 300, "updown_15m": 900})
        # ws_s convention (matches our canonical)
        ud["ws_s"] = ud.slot_start_s - ud.window_s
        # production fire time
        ud["fire_us"] = (ud.ws_s + 120) * 1_000_000
        # offset of THIS trade from slot start
        ud["trade_ts_s"] = ud.timestamp.astype("int64")
        ud["offset_from_slot_start_s"] = ud.trade_ts_s - ud.slot_start_s
        ud["offset_from_ws_s"]         = ud.trade_ts_s - ud.ws_s
        ud["offset_from_fire_s"]       = ud.trade_ts_s - (ud.ws_s + 120)

        print("=== UPDOWN: timing of trades relative to slot_start (seconds) ===")
        print("    negative = trade BEFORE slot_start (which is window-end for our markets)")
        print(ud.offset_from_slot_start_s.describe().round(1).to_string())
        print()
        print("=== UPDOWN: offset from production fire (ws_s + 120) ===")
        print(ud.offset_from_fire_s.describe().round(1).to_string())
        print()

        # Histogram bucketed
        bucket = pd.cut(ud.offset_from_slot_start_s,
                         bins=[-1000,-900,-720,-540,-360,-300,-240,-180,-120,-60,0,60,120,300,1000],
                         right=False)
        print("=== Offset-from-slot-start distribution (bucketed) ===")
        print(bucket.value_counts().sort_index().to_string())
        print()

        # Side per up-down market — do they BUY both sides? Only one?
        side_per_market = ud.groupby(["conditionId", "side"]).size().unstack(fill_value=0)
        side_per_market["both_sides"] = (side_per_market.get("BUY", 0) > 0) & (side_per_market.get("SELL", 0) > 0)
        print(f"=== UPDOWN: markets traded ===")
        print(f"    unique conditionIds: {ud.conditionId.nunique()}")
        if "SELL" in side_per_market.columns:
            print(f"    markets with only BUYS: {(side_per_market.get('SELL', 0) == 0).sum()}")
            print(f"    markets with only SELLS: {(side_per_market.get('BUY', 0) == 0).sum()}")
            print(f"    markets with BOTH:       {side_per_market.both_sides.sum()}")
        print()

        # Outcome side (Up vs Down — encoded in `asset` token_id, but `title` mentions)
        # The `outcome` field if present
        if "outcome" in ud.columns:
            print("=== UPDOWN: outcome side picked (Up/Down) ===")
            print(ud.outcome.value_counts().to_string())
            print()
        else:
            print("(no `outcome` column — would need to join CLOB tokens to map asset→Up/Down)")
            print()

        # Save updown-only slice
        ud.to_parquet(cache / f"{short}_updown_trades.parquet", index=False)

    # Positions
    pos_p = cache / f"{short}_positions.parquet"
    if pos_p.exists():
        pos = pd.read_parquet(pos_p)
        print(f"=== Open positions: {len(pos)} ===")
        for c in ("currentValue", "initialValue", "cashPnl", "percentPnl"):
            if c in pos.columns:
                v = pd.to_numeric(pos[c], errors="coerce")
                print(f"   {c}: total=${v.sum():.2f}  mean=${v.mean():.4f}")
        print()
        print(pos[["title", "size", "avgPrice", "currentValue", "cashPnl", "percentPnl"]]
              .head(10).to_string(index=False))

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
