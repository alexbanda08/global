"""
fetch_btc_recent — Pull BTCUSDT 5m bars from Binance public API.

We need Apr 20 → Apr 24 2026 to cover:
  - Apr 22 17:30 CEST = Apr 22 15:30 UTC (earliest Polymarket window_start)
  - Apr 23 22:05 CEST = Apr 23 20:05 UTC (latest Polymarket resolve)
  - Plus 512 bars of lookback before earliest = back to ~Apr 20 20:00 UTC

Binance public klines endpoint: https://api.binance.com/api/v3/klines
No auth. Limit 1000 bars per call.

Output: append to BTCUSDT_5m_3y.csv with matching schema.
"""
from __future__ import annotations

import sys
from pathlib import Path
import time

import pandas as pd
import requests

OUT = Path("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/kronos_ft/data/BTCUSDT_5m_apr.csv")
# CEST is UTC+2. Binance returns UTC. We'll convert to match existing CSV (which has local CEST times).

START = "2026-04-20 00:00:00"  # UTC
END   = "2026-04-24 00:00:00"  # UTC


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1000):
    all_rows = []
    cur = start_ms
    while cur < end_ms:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cur,
            "endTime": end_ms,
            "limit": limit,
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        all_rows.extend(rows)
        last_ts = rows[-1][0]
        cur = last_ts + 1
        if len(rows) < limit:
            break
        time.sleep(0.15)  # polite
    return all_rows


def main():
    start_ms = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(END, tz="UTC").timestamp() * 1000)
    print(f"Fetching BTCUSDT 5m from {START} to {END} UTC")

    rows = fetch_klines("BTCUSDT", "5m", start_ms, end_ms)
    print(f"Got {len(rows)} bars")

    # Binance kline format: [openTime_ms, open, high, low, close, volume, closeTime_ms, quoteAssetVolume,
    #                        numTrades, takerBuyBaseVol, takerBuyQuoteVol, ignore]
    df = pd.DataFrame(rows, columns=[
        "openTime", "open", "high", "low", "close", "volume",
        "closeTime", "quoteAssetVolume", "numTrades",
        "takerBuyBaseVol", "takerBuyQuoteVol", "ignore",
    ])
    # Match existing schema: timestamps, open, high, low, close, volume, amount
    # Existing CSV appears to have timestamps in CEST (UTC+2). For consistency keep UTC.
    # But to match alignment with old CSV, convert to CEST as well.
    df["timestamps"] = pd.to_datetime(df["openTime"], unit="ms", utc=True).dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
    # Convert numeric fields
    for c in ["open", "high", "low", "close", "volume", "quoteAssetVolume"]:
        df[c] = df[c].astype(float)
    # "amount" in the existing CSV looks like quote volume (price * base volume in USDT)
    df["amount"] = df["quoteAssetVolume"]
    out = df[["timestamps", "open", "high", "low", "close", "volume", "amount"]].copy()
    out = out.sort_values("timestamps").reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"Wrote {len(out)} rows to {OUT}")
    print(f"Earliest: {out.timestamps.min()}")
    print(f"Latest:   {out.timestamps.max()}")


if __name__ == "__main__":
    main()
