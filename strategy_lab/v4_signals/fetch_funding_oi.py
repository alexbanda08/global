"""V4-A data fetcher — funding rate (fapi public) + open interest metrics (Vision).

Pulls 2026-04-15 → 2026-04-30 covering the Polymarket UP/DOWN window with buffer.
Outputs:
  data/v4/funding/{symbol}.parquet      — funding rate history per asset
  data/v4/oi/{symbol}.parquet           — open interest metrics per asset

Symbols: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, HYPEUSDT
Free, keyless. Binance public API only.
"""
from __future__ import annotations
import io
import os
import sys
import time
import json
import zipfile
import urllib.request
import urllib.error
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_FUNDING = ROOT / "data" / "v4" / "funding"
OUT_OI      = ROOT / "data" / "v4" / "oi"
OUT_FUNDING.mkdir(parents=True, exist_ok=True)
OUT_OI.mkdir(parents=True, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "HYPEUSDT"]
START_MS = int(pd.Timestamp("2026-04-15", tz="UTC").timestamp() * 1000)
END_MS   = int(pd.Timestamp("2026-05-01", tz="UTC").timestamp() * 1000)


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "v4-fetcher/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_funding(symbol: str) -> pd.DataFrame:
    """Binance fapi /fapi/v1/fundingRate paginated by 1000 records max."""
    rows = []
    cursor = START_MS
    while cursor < END_MS:
        url = (f"https://fapi.binance.com/fapi/v1/fundingRate"
               f"?symbol={symbol}&startTime={cursor}&endTime={END_MS}&limit=1000")
        try:
            data = json.loads(http_get(url))
        except urllib.error.HTTPError as e:
            print(f"  {symbol}: HTTP {e.code} -> {e.read()[:200]}", file=sys.stderr)
            return pd.DataFrame()
        if not data:
            break
        rows.extend(data)
        last_ts = int(data[-1]["fundingTime"])
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        time.sleep(0.1)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["fundingTime"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["markPrice"]   = df["markPrice"].astype(float)
    df = df[["fundingTime", "symbol", "fundingRate", "markPrice"]]
    return df.sort_values("fundingTime").reset_index(drop=True)


def fetch_oi_daily(symbol: str, date: str) -> pd.DataFrame:
    """Binance Vision daily metrics zip — 5min OI samples."""
    url = (f"https://data.binance.vision/data/futures/um/daily/metrics/"
           f"{symbol}/{symbol}-metrics-{date}.zip")
    try:
        zbytes = http_get(url, timeout=20)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return pd.DataFrame()
        raise
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f)
    return df


def fetch_oi_range(symbol: str) -> pd.DataFrame:
    dfs = []
    d = pd.Timestamp("2026-04-15", tz="UTC")
    end = pd.Timestamp("2026-04-30", tz="UTC")
    while d <= end:
        date_str = d.strftime("%Y-%m-%d")
        try:
            df = fetch_oi_daily(symbol, date_str)
            if not df.empty:
                dfs.append(df)
                print(f"  {symbol} OI {date_str}: {len(df)} rows")
            else:
                print(f"  {symbol} OI {date_str}: 404 (skip)")
        except Exception as e:
            print(f"  {symbol} OI {date_str}: {type(e).__name__} {e}")
        d += pd.Timedelta(days=1)
        time.sleep(0.15)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def main():
    print(f"== FUNDING via fapi.binance.com (keyless) ==")
    for sym in SYMBOLS:
        out = OUT_FUNDING / f"{sym}.parquet"
        df = fetch_funding(sym)
        if df.empty:
            print(f"  {sym}: NO DATA (likely not listed on Binance perps)")
            continue
        df.to_parquet(out)
        print(f"  {sym}: {len(df)} funding records -> {out.relative_to(ROOT)}")

    print(f"\n== OI METRICS via data.binance.vision (5min granularity) ==")
    for sym in SYMBOLS:
        out = OUT_OI / f"{sym}.parquet"
        df = fetch_oi_range(sym)
        if df.empty:
            print(f"  {sym}: NO OI DATA")
            continue
        df.to_parquet(out)
        print(f"  {sym}: {len(df)} OI rows -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
