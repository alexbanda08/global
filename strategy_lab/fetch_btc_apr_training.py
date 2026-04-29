"""Fetch BTCUSDT 5m bars for Apr 1 - Apr 22 2026 and merge with existing training CSV."""
from __future__ import annotations
import time
from pathlib import Path
import pandas as pd
import requests

HIST_CSV = Path("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/kronos_ft/data/BTCUSDT_5m_3y.csv")
OUT_CSV  = Path("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/kronos_ft/data/BTCUSDT_5m_ext.csv")

START = "2026-04-01 00:00:00"
END   = "2026-04-22 12:00:00"  # stop at noon UTC Apr 22, about 4h before Polymarket data begins


def fetch_klines(symbol, interval, start_ms, end_ms, limit=1000):
    rows = []
    cur = start_ms
    while cur < end_ms:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params=dict(symbol=symbol, interval=interval,
                                     startTime=cur, endTime=end_ms, limit=limit),
                         timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch: break
        rows.extend(batch)
        cur = batch[-1][0] + 1
        if len(batch) < limit: break
        time.sleep(0.15)
    return rows


def main():
    start_ms = int(pd.Timestamp(START, tz="UTC").timestamp() * 1000)
    end_ms   = int(pd.Timestamp(END,   tz="UTC").timestamp() * 1000)
    print(f"Fetching Apr 1 -> Apr 22 12:00 UTC...")
    rows = fetch_klines("BTCUSDT", "5m", start_ms, end_ms)
    print(f"Got {len(rows)} new bars")

    cols = ["openTime","open","high","low","close","volume","closeTime",
            "quoteAssetVolume","numTrades","takerBuyBaseVol","takerBuyQuoteVol","ignore"]
    new = pd.DataFrame(rows, columns=cols)
    new["timestamps"] = pd.to_datetime(new["openTime"], unit="ms", utc=True).dt.tz_convert("Europe/Berlin").dt.tz_localize(None)
    for c in ["open","high","low","close","volume","quoteAssetVolume"]: new[c] = new[c].astype(float)
    new["amount"] = new["quoteAssetVolume"]
    new = new[["timestamps","open","high","low","close","volume","amount"]]

    # Load existing
    old = pd.read_csv(HIST_CSV)
    old["timestamps"] = pd.to_datetime(old["timestamps"])
    cutoff = old["timestamps"].max()
    print(f"Existing CSV ends: {cutoff}")
    new = new[new["timestamps"] > cutoff].copy()
    print(f"Bars to append after cutoff: {len(new)}")

    ext = pd.concat([old, new], ignore_index=True).sort_values("timestamps").reset_index(drop=True)
    # Sanity check for gaps
    dt = ext["timestamps"].diff().dt.total_seconds().dropna()
    gaps = (dt != 300).sum()
    print(f"Extended CSV: {len(ext)} bars, range {ext.timestamps.min()} -> {ext.timestamps.max()}")
    print(f"Bars with non-5min gap: {gaps}")

    ext.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
