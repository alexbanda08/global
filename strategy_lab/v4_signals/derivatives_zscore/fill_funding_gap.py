"""Backfill the recent-funding gap from Binance fapi REST.

Vision only publishes funding rate as MONTHLY archives (not daily). This means the
current month is always missing until the month closes. This script reads each
existing funding parquet, finds its max calc_time, fetches everything from there to
now via fapi.binance.com, and appends.

Idempotent: rerun any time to refresh.
"""
from __future__ import annotations
import json
import time
import urllib.request
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data" / "v4" / "derivatives_zscore" / "funding"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def http_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "fund-gap/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_rest(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Pages 1000 at a time; calc_time format matches Vision (ms int)."""
    rows = []
    cur = start_ms
    while cur < end_ms:
        url = (f"https://fapi.binance.com/fapi/v1/fundingRate"
               f"?symbol={symbol}&startTime={cur}&endTime={end_ms}&limit=1000")
        try:
            data = http_json(url)
        except Exception as e:
            print(f"  {symbol}: {e}; backing off")
            time.sleep(2)
            continue
        if not data:
            break
        rows.extend(data)
        last = int(data[-1]["fundingTime"])
        if last <= cur:
            break
        cur = last + 1
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "calc_time": pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True),
        "funding_interval_hours": 8,
        "last_funding_rate": df["fundingRate"].astype(float),
    })
    return out


def main():
    for sym in SYMBOLS:
        p = BASE / f"{sym}.parquet"
        if not p.exists():
            print(f"[{sym}] no existing parquet, skipping")
            continue
        old = pd.read_parquet(p)
        last_ts = old["calc_time"].max()
        # +1 ms past the last known tick
        start_ms = int(last_ts.timestamp() * 1000) + 1
        end_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
        if start_ms >= end_ms:
            print(f"[{sym}] already up to date ({last_ts})")
            continue
        print(f"[{sym}] gap fetch {pd.to_datetime(start_ms, unit='ms', utc=True)} → now ({(end_ms - start_ms)/3.6e6:.0f}h)")
        new = fetch_rest(sym, start_ms, end_ms)
        if new.empty:
            print(f"  no new rows")
            continue
        merged = (
            pd.concat([old, new], ignore_index=True)
              .drop_duplicates(subset=["calc_time"])
              .sort_values("calc_time")
              .reset_index(drop=True)
        )
        merged.to_parquet(p)
        print(f"  added {len(new)} rows; total now {len(merged)}; last {merged['calc_time'].iloc[-1]}")


if __name__ == "__main__":
    main()
