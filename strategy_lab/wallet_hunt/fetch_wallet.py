"""Fetch all trades + positions for a Polymarket wallet via data-api.

Pages through `/trades?user=<wallet>` until exhausted, saves to parquet.
Also dumps positions + portfolio value.

Usage:
    py -3 strategy_lab/wallet_hunt/fetch_wallet.py --wallet 0xeebde7a0...
"""
from __future__ import annotations
import argparse
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

DATA_API = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "cache"
OUT.mkdir(parents=True, exist_ok=True)


def get(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_trades(wallet: str, page_size: int = 500,
                  sleep_s: float = 0.1, max_pages: int | None = None) -> pd.DataFrame:
    """Page through /trades via offset until empty."""
    rows: list[dict] = []
    offset = 0
    page = 0
    while True:
        url = f"{DATA_API}/trades?user={wallet}&limit={page_size}&offset={offset}"
        try:
            batch = get(url)
        except Exception as e:
            print(f"  ERROR at offset={offset}: {e}")
            break
        if not batch:
            break
        rows.extend(batch)
        page += 1
        print(f"  page {page}: +{len(batch)} (cum {len(rows)})", flush=True)
        if len(batch) < page_size:
            break
        offset += page_size
        if max_pages and page >= max_pages:
            print(f"  hit max_pages={max_pages}, stopping")
            break
        time.sleep(sleep_s)
    return pd.DataFrame(rows)


def fetch_positions(wallet: str) -> pd.DataFrame:
    data = get(f"{DATA_API}/positions?user={wallet}")
    return pd.DataFrame(data) if data else pd.DataFrame()


def fetch_value(wallet: str) -> dict:
    data = get(f"{DATA_API}/value?user={wallet}")
    if isinstance(data, list) and data:
        return data[0]
    return data if isinstance(data, dict) else {}


def fetch_activity(wallet: str, page_size: int = 500,
                    sleep_s: float = 0.1, max_pages: int | None = None) -> pd.DataFrame:
    rows: list[dict] = []
    offset = 0
    page = 0
    while True:
        url = f"{DATA_API}/activity?user={wallet}&limit={page_size}&offset={offset}"
        try:
            batch = get(url)
        except Exception as e:
            print(f"  ERROR at offset={offset}: {e}")
            break
        if not batch:
            break
        rows.extend(batch)
        page += 1
        print(f"  activity page {page}: +{len(batch)} (cum {len(rows)})", flush=True)
        if len(batch) < page_size:
            break
        offset += page_size
        if max_pages and page >= max_pages:
            break
        time.sleep(sleep_s)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", required=True)
    ap.add_argument("--page-size", type=int, default=500)
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--skip-activity", action="store_true")
    args = ap.parse_args()

    w = args.wallet.lower()
    short = w[:10]
    print(f"=== Fetching wallet {w}")
    print(f"=== Output dir: {OUT}")

    print("\n[1] trades...")
    trades = fetch_trades(w, page_size=args.page_size, max_pages=args.max_pages)
    p = OUT / f"{short}_trades.parquet"
    trades.to_parquet(p, index=False)
    print(f"  -> {len(trades):,} trades  ({p})")
    if len(trades):
        ts = pd.to_datetime(trades["timestamp"], unit="s", utc=True)
        print(f"  range: {ts.min()} → {ts.max()}")

    print("\n[2] positions (current open)...")
    pos = fetch_positions(w)
    p = OUT / f"{short}_positions.parquet"
    if len(pos):
        pos.to_parquet(p, index=False)
    print(f"  -> {len(pos)} open positions")

    print("\n[3] portfolio value...")
    val = fetch_value(w)
    print(f"  current value: ${float(val.get('value', 0)):,.2f}")
    with open(OUT / f"{short}_value.json", "w") as f:
        json.dump(val, f, default=str)

    if not args.skip_activity:
        print("\n[4] activity log (mints, splits, merges, redemptions)...")
        act = fetch_activity(w, page_size=args.page_size, max_pages=args.max_pages)
        p = OUT / f"{short}_activity.parquet"
        if len(act):
            act.to_parquet(p, index=False)
        print(f"  -> {len(act)} activity rows")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
