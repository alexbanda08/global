"""
Ingest Hyperliquid OHLCV + funding history from the official API.

Endpoints:
  POST https://api.hyperliquid.xyz/info
  body: {"type":"candleSnapshot", "req":{"coin":"BTC","interval":"4h","startTime":<ms>,"endTime":<ms>}}
  body: {"type":"fundingHistory",  "coin":"BTC", "startTime":<ms>}

Limits: candleSnapshot returns up to 5000 candles per call. We paginate by
walking forward in time chunks. Hyperliquid API: April 2023 is earliest data.

Output:
  data/hyperliquid/parquet/<COIN>/4h.parquet   (same schema as Binance parquets)
  data/hyperliquid/funding/<COIN>_funding.parquet
"""
from __future__ import annotations
import time, json
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data" / "hyperliquid"
KLINE_DIR = DATA_DIR / "parquet"
FUNDING_DIR = DATA_DIR / "funding"
KLINE_DIR.mkdir(parents=True, exist_ok=True)
FUNDING_DIR.mkdir(parents=True, exist_ok=True)

API_URL = "https://api.hyperliquid.xyz/info"
COINS = ["BTC", "ETH", "AVAX", "SOL", "LINK"]

# 4h bars in ms; HL uses standard intervals: 1m,5m,15m,1h,4h,1d
INTERVAL = "4h"
INTERVAL_MS = 4 * 60 * 60 * 1000  # 14_400_000

# History window
START_MS = int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS   = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

# Per-page candle limit
MAX_CANDLES_PER_CALL = 5000
WINDOW_MS = MAX_CANDLES_PER_CALL * INTERVAL_MS  # 5000 * 4h = 833 days


def post_info(body: dict, retries: int = 3, timeout: int = 30) -> dict | list:
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(API_URL, json=body, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(1.5 ** attempt)
    raise last_err


def fetch_candles_paged(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows = []
    cursor = start_ms
    page = 0
    while cursor < end_ms:
        chunk_end = min(cursor + WINDOW_MS, end_ms)
        body = {"type": "candleSnapshot",
                "req": {"coin": coin, "interval": INTERVAL,
                        "startTime": cursor, "endTime": chunk_end}}
        try:
            data = post_info(body)
        except Exception as e:
            print(f"  page {page} ERR: {type(e).__name__}: {e}")
            cursor = chunk_end
            continue
        if not data:
            print(f"  page {page} empty (cursor={datetime.fromtimestamp(cursor/1000, timezone.utc):%Y-%m-%d})")
            cursor = chunk_end
            continue
        rows.extend(data)
        last_t = int(data[-1]["t"])
        page += 1
        if last_t <= cursor:
            cursor = chunk_end  # prevent infinite loop
        else:
            cursor = last_t + INTERVAL_MS
        time.sleep(0.25)  # rate-limit polite
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # HL fields: t (open ms), T (close ms), s, i, o, c, h, l, v, n
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
    df = df[["timestamp","open","high","low","close","volume"]]
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp")
    return df


def fetch_funding_paged(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Hyperliquid funding rate history. Hourly. Same 5000-row paging."""
    rows = []
    cursor = start_ms
    page = 0
    while cursor < end_ms:
        body = {"type": "fundingHistory", "coin": coin,
                "startTime": cursor, "endTime": min(cursor + 5000*60*60*1000, end_ms)}
        try:
            data = post_info(body)
        except Exception as e:
            print(f"  funding page {page} ERR: {type(e).__name__}: {e}")
            cursor += 5000 * 60 * 60 * 1000
            continue
        if not data:
            cursor += 5000 * 60 * 60 * 1000
            continue
        rows.extend(data)
        last_t = int(data[-1]["time"])
        page += 1
        cursor = last_t + 60 * 60 * 1000  # hourly
        time.sleep(0.25)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["premium"] = df["premium"].astype(float) if "premium" in df.columns else 0.0
    df = df[["timestamp","fundingRate","premium"]]
    df = df.drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp")
    return df


def main():
    print(f"Hyperliquid ingest — {INTERVAL} klines + funding for {COINS}")
    print(f"Window: {datetime.fromtimestamp(START_MS/1000, timezone.utc):%Y-%m-%d} -> "
          f"{datetime.fromtimestamp(END_MS/1000, timezone.utc):%Y-%m-%d}")

    for coin in COINS:
        print(f"\n=== {coin} ===")
        # Klines
        out_dir = KLINE_DIR / coin
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{INTERVAL}.parquet"
        if out_path.exists():
            existing = pd.read_parquet(out_path)
            last = int(existing.index.max().timestamp() * 1000)
            print(f"  klines exist ({len(existing)} bars; last={existing.index.max()}); "
                  f"appending from {datetime.fromtimestamp(last/1000, timezone.utc):%Y-%m-%d}")
            new = fetch_candles_paged(coin, last + INTERVAL_MS, END_MS)
            if len(new):
                df = pd.concat([existing, new]).drop_duplicates().sort_index()
            else:
                df = existing
        else:
            df = fetch_candles_paged(coin, START_MS, END_MS)
        if len(df):
            df.to_parquet(out_path)
            print(f"  klines: {len(df)} bars  range={df.index.min()} -> {df.index.max()}")
            print(f"  saved -> {out_path}")
        else:
            print(f"  ! no klines fetched for {coin}")

        # Funding
        f_path = FUNDING_DIR / f"{coin}_funding.parquet"
        if f_path.exists():
            print(f"  funding exists, skipping (delete to refetch)")
        else:
            df_f = fetch_funding_paged(coin, START_MS, END_MS)
            if len(df_f):
                df_f.to_parquet(f_path)
                print(f"  funding: {len(df_f)} hourly rows; "
                      f"avg rate = {df_f['fundingRate'].mean()*100:.4f}%/hr  "
                      f"range = {df_f.index.min()} -> {df_f.index.max()}")
                print(f"  saved -> {f_path}")
            else:
                print(f"  ! no funding fetched for {coin}")

    print("\nDone.")

if __name__ == "__main__":
    main()
