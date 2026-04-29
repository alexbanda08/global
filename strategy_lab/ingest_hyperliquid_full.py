"""
Full Hyperliquid ingest — grab ALL available data.

Strategy:
  - For 4h: walk through 1-month windows from 2023-04-01 to present.
    Accumulate every non-empty response. Captures both the April 2023
    pre-launch chunk and the continuous Jan 2024+ chunk.
  - For 1d: single call (5000 daily ≈ 13.7 years coverage well exceeds
    available history of ~5.5 years).
  - Funding: already paginated by hour.

Saves:
  data/hyperliquid/parquet/<COIN>/4h.parquet
  data/hyperliquid/parquet/<COIN>/1d.parquet
"""
from __future__ import annotations
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
KLINE_DIR = REPO / "data" / "hyperliquid" / "parquet"
KLINE_DIR.mkdir(parents=True, exist_ok=True)

API_URL = "https://api.hyperliquid.xyz/info"
COINS = ["BTC", "ETH", "AVAX", "SOL", "LINK"]


def post_info(body: dict, retries: int = 3, timeout: int = 30):
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


def fetch_window(coin: str, interval: str, start_ms: int, end_ms: int):
    body = {"type": "candleSnapshot",
            "req": {"coin": coin, "interval": interval,
                    "startTime": start_ms, "endTime": end_ms}}
    try:
        return post_info(body) or []
    except Exception:
        return []


def fetch_all_4h(coin: str) -> pd.DataFrame:
    """Walk in 30-day windows from 2023-04-01 to now."""
    rows = []
    cursor = datetime(2023, 4, 1, tzinfo=timezone.utc)
    end = datetime.now(timezone.utc)
    step = timedelta(days=30)
    seen_t: set[int] = set()
    while cursor < end:
        chunk_end = min(cursor + step, end)
        s_ms = int(cursor.timestamp() * 1000)
        e_ms = int(chunk_end.timestamp() * 1000)
        data = fetch_window(coin, "4h", s_ms, e_ms)
        new_in_chunk = 0
        for row in data:
            if int(row["t"]) not in seen_t:
                seen_t.add(int(row["t"]))
                rows.append(row)
                new_in_chunk += 1
        cursor = chunk_end
        time.sleep(0.15)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
    df = df[["timestamp","open","high","low","close","volume"]]
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp")
    return df


def fetch_all_1d(coin: str) -> pd.DataFrame:
    """Single call covers full daily history (5000 days ~= 13 years)."""
    s_ms = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    e_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    data = fetch_window(coin, "1d", s_ms, e_ms)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.rename(columns={"o":"open","h":"high","l":"low","c":"close","v":"volume"})
    df = df[["timestamp","open","high","low","close","volume"]]
    for c in ["open","high","low","close","volume"]:
        df[c] = df[c].astype(float)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").set_index("timestamp")
    return df


def main():
    summary = []
    for coin in COINS:
        out_dir = KLINE_DIR / coin
        out_dir.mkdir(parents=True, exist_ok=True)

        # 4h — full pagination
        df_4h = fetch_all_4h(coin)
        path_4h = out_dir / "4h.parquet"
        if len(df_4h):
            df_4h.to_parquet(path_4h)
            summary.append((coin, "4h", len(df_4h),
                            df_4h.index.min(), df_4h.index.max()))

        # 1d — single call
        df_1d = fetch_all_1d(coin)
        path_1d = out_dir / "1d.parquet"
        if len(df_1d):
            df_1d.to_parquet(path_1d)
            summary.append((coin, "1d", len(df_1d),
                            df_1d.index.min(), df_1d.index.max()))
        time.sleep(0.2)

    # Print one-line summary
    print(f"{'coin':6s} {'tf':4s} {'bars':>6s}  {'first':<25s} {'last':<25s}")
    for c, tf, n, f, l in summary:
        print(f"{c:6s} {tf:4s} {n:>6d}  {str(f):25s} {str(l):25s}")

if __name__ == "__main__":
    main()
