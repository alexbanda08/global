"""Extend BTCUSDT_5m_ext.csv with fresh 5m bars from Binance public klines API.

Pulls from the existing CSV's last timestamp through 2026-05-04 23:55 UTC, appends,
de-dupes on timestamps, sorts. CSV stays in CEST-naive time to match the schema
expected by kronos_infer_polymarket.py.
"""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import requests

CSV = Path("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/kronos_ft/data/BTCUSDT_5m_ext.csv")
END_UTC = "2026-05-04 23:55:00"


def fetch_klines(symbol, interval, start_ms, end_ms, limit=1000):
    rows = []
    cur = start_ms
    while cur < end_ms:
        r = requests.get(
            "https://api.binance.com/api/v3/klines",
            params=dict(symbol=symbol, interval=interval,
                        startTime=cur, endTime=end_ms, limit=limit),
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1][0] + 1
        if len(batch) < limit:
            break
        time.sleep(0.15)
    return rows


def main():
    old = pd.read_csv(CSV)
    old["timestamps"] = pd.to_datetime(old["timestamps"])
    last_local = old["timestamps"].max()
    # Convert CEST-naive -> UTC by subtracting 2h
    last_utc = pd.Timestamp(last_local) - pd.Timedelta(hours=2)
    start_ms = int(last_utc.tz_localize("UTC").timestamp() * 1000) + 1
    end_ms = int(pd.Timestamp(END_UTC, tz="UTC").timestamp() * 1000)
    print(f"Existing CSV ends: {last_local} (CEST naive) = {last_utc} UTC")
    print(f"Fetching {pd.to_datetime(start_ms, unit='ms', utc=True)} -> {END_UTC} UTC ...")

    rows = fetch_klines("BTCUSDT", "5m", start_ms, end_ms)
    print(f"Got {len(rows)} new bars")
    if not rows:
        print("Nothing to append.")
        return

    cols = ["openTime", "open", "high", "low", "close", "volume", "closeTime",
            "quoteAssetVolume", "numTrades", "takerBuyBaseVol", "takerBuyQuoteVol", "ignore"]
    new = pd.DataFrame(rows, columns=cols)
    new["timestamps"] = (
        pd.to_datetime(new["openTime"], unit="ms", utc=True)
        .dt.tz_convert("Europe/Berlin")
        .dt.tz_localize(None)
    )
    for c in ["open", "high", "low", "close", "volume", "quoteAssetVolume"]:
        new[c] = new[c].astype(float)
    new["amount"] = new["quoteAssetVolume"]
    new = new[["timestamps", "open", "high", "low", "close", "volume", "amount"]]

    new_after = new[new["timestamps"] > last_local].copy()
    print(f"Bars strictly after existing cutoff: {len(new_after)}")

    ext = (
        pd.concat([old, new_after], ignore_index=True)
        .drop_duplicates("timestamps")
        .sort_values("timestamps")
        .reset_index(drop=True)
    )
    dt = ext["timestamps"].diff().dt.total_seconds().dropna()
    gaps = (dt != 300).sum()
    print(f"Extended CSV: {len(ext)} bars, range {ext.timestamps.min()} -> {ext.timestamps.max()}")
    print(f"Bars with non-5min gap: {gaps}")

    ext.to_csv(CSV, index=False)
    print(f"Wrote {CSV}")


if __name__ == "__main__":
    main()
