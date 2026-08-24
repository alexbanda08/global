"""
R6 — bootstrap HL 4h klines + funding for the coins the breadth portfolio needs
but the store does not have yet (ADA, BNB, DOGE, XRP, SUI).

The existing store holds BTC/ETH/SOL/AVAX/LINK. R4 validated the STF and VP families
across a 10-coin universe, so the shadow needs the other five to actually run that
portfolio. HL API retention starts ~2024-03 (probed in _r0), so that is the effective
start; we ask from 2024-01 and take whatever it serves.

Idempotent: skips a coin that already has a 4h parquet unless --force.
"""
from __future__ import annotations
import sys, argparse
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from strategy_lab.ingest_hyperliquid import (
    fetch_candles_paged, fetch_funding_paged, KLINE_DIR, FUNDING_DIR, INTERVAL,
)

NEW_COINS = ["ADA", "BNB", "DOGE", "XRP", "SUI"]
START = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--coins", default=",".join(NEW_COINS))
    args = ap.parse_args()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    for coin in [c.strip().upper() for c in args.coins.split(",") if c.strip()]:
        kp = KLINE_DIR / coin / f"{INTERVAL}.parquet"
        fp = FUNDING_DIR / f"{coin}_funding.parquet"

        if kp.exists() and not args.force:
            d = pd.read_parquet(kp)
            print(f"{coin:5s} klines EXISTS n={len(d)} {d.index.min():%Y-%m-%d} -> {d.index.max():%Y-%m-%d} (skip)")
        else:
            df = fetch_candles_paged(coin, START, now_ms)
            if len(df):
                kp.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(kp)
                print(f"{coin:5s} klines  n={len(df):5d} {df.index.min():%Y-%m-%d} -> {df.index.max():%Y-%m-%d}"
                      f"  zero-vol={int((df.volume==0).sum())}")
            else:
                print(f"{coin:5s} klines  EMPTY — HL does not serve this coin/interval")
                continue

        if fp.exists() and not args.force:
            f = pd.read_parquet(fp)
            print(f"{coin:5s} funding EXISTS n={len(f)} -> {f.index.max():%Y-%m-%d} (skip)")
        else:
            fd = fetch_funding_paged(coin, START, now_ms)
            if len(fd):
                fd.to_parquet(fp)
                print(f"{coin:5s} funding n={len(fd):6d} {fd.index.min():%Y-%m-%d} -> {fd.index.max():%Y-%m-%d}")
            else:
                print(f"{coin:5s} funding EMPTY")


if __name__ == "__main__":
    main()
