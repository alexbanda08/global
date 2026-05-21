"""Fetch trades + positions + activity for a LIST of wallets.

Wraps fetch_wallet.py logic but pages by `end_time` to extract more history.
Stores per-wallet under cache/<short>/.
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
CACHE = Path(__file__).resolve().parent / "cache"


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_paged(endpoint: str, wallet: str, page_size: int = 500,
                  max_pages: int = 50, sleep_s: float = 0.1,
                  user_param: str = "user") -> list:
    """Page through any /endpoint?<param>=<wallet> via offset until 3500 cap, then end_time."""
    rows = []
    offset = 0
    page = 0
    while page < max_pages:
        url = f"{DATA_API}/{endpoint}?{user_param}={wallet}&limit={page_size}&offset={offset}"
        try:
            batch = get(url)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise
        if not batch:
            break
        rows.extend(batch)
        page += 1
        if len(batch) < page_size:
            break
        offset += page_size
        time.sleep(sleep_s)
    # Continue past 3500 via end_time
    if rows and len(rows) >= 3000:
        end_ts = min(int(r["timestamp"]) for r in rows if r.get("timestamp"))
        seen = set()
        for r in rows:
            seen.add((r.get("transactionHash"), r.get("asset"), r.get("timestamp")))
        while page < max_pages * 2:
            url = f"{DATA_API}/{endpoint}?{user_param}={wallet}&limit={page_size}&offset=0&end_time={end_ts}"
            try:
                batch = get(url)
            except Exception:
                break
            if not batch:
                break
            new = []
            for r in batch:
                k = (r.get("transactionHash"), r.get("asset"), r.get("timestamp"))
                if k in seen:
                    continue
                seen.add(k); new.append(r)
            if not new:
                end_ts -= 1
                page += 1
                if page % 5 == 0:
                    print(f"      {endpoint}: all-dupes loop, ts={end_ts}", flush=True)
                continue
            rows.extend(new)
            page += 1
            end_ts = min(int(r["timestamp"]) for r in new)
            if len(batch) < page_size:
                break
            time.sleep(sleep_s)
    return rows


def fetch_one(wallet: str):
    w = wallet.lower()
    short = w[:10]
    odir = CACHE / short
    odir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {w} → {odir}/")

    # Try user= first; fall back to proxyWallet= if empty (some wallets are Safes, not EOAs)
    user_param = "user"
    print(f"  [trades]  (user param)")
    trades = fetch_paged("trades", w, page_size=500, max_pages=20, user_param="user")
    if not trades:
        print(f"  [trades]  (proxyWallet param)")
        trades = fetch_paged("trades", w, page_size=500, max_pages=20, user_param="proxyWallet")
        user_param = "proxyWallet"
    if trades:
        df = pd.DataFrame(trades).drop_duplicates(
            subset=["transactionHash", "asset"], keep="first"
        ) if "transactionHash" in trades[0] else pd.DataFrame(trades)
        df.to_parquet(odir / "trades.parquet", index=False)
        ts = pd.to_datetime(df.timestamp.astype("int64"), unit="s", utc=True)
        print(f"    -> {len(df):,} trades (param={user_param}), {ts.min()} → {ts.max()} "
              f"(span {(ts.max()-ts.min()).total_seconds()/3600:.1f}h)")
    else:
        print(f"    -> 0 trades both params")

    print(f"  [positions]")
    pos = get(f"{DATA_API}/positions?{user_param}={w}")
    if pos:
        pd.DataFrame(pos).to_parquet(odir / "positions.parquet", index=False)
        print(f"    -> {len(pos)} positions")

    print(f"  [value]")
    val = get(f"{DATA_API}/value?{user_param}={w}")
    if isinstance(val, list) and val:
        val = val[0]
    if isinstance(val, dict):
        v = float(val.get("value", 0))
        with open(odir / "value.json", "w") as f:
            json.dump(val, f, default=str)
        print(f"    -> portfolio ${v:,.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallets", nargs="+", required=True,
                     help="One or more 0x addresses")
    args = ap.parse_args()
    for w in args.wallets:
        try:
            fetch_one(w)
        except Exception as e:
            print(f"  ERROR fetching {w}: {e}")
            import traceback; traceback.print_exc()
    print("\nDone.")


if __name__ == "__main__":
    main()
