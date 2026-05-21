"""Convert L25 CSV.gz from VPS3 to parquet matching existing delta schema.

Source schema (109 cols):
  timestamp_us, local_timestamp_us, exchange, market_id, slug, asset_id, outcome,
  bid_price_0, bid_size_0, ..., bid_price_24, bid_size_24,
  ask_price_0, ask_size_0, ..., ask_price_24, ask_size_24,
  outcome_id, source

Target schema (104 cols, matching refresh_2026_05_12/cache/*_orderbook_L25_delta.parquet):
  timestamp_us, slug, market_id, outcome,
  ask_price_0..24, ask_size_0..24, bid_price_0..24, bid_size_0..24

Drops: local_timestamp_us, exchange, asset_id, outcome_id, source.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
SRC_DIR = ROOT / "data/v4/refresh_2026_05_16/cache"

LEVELS = 25
TARGET_COLS = (
    ["timestamp_us", "slug", "market_id", "outcome"]
    + [f"ask_price_{i}"  for i in range(LEVELS)]
    + [f"ask_size_{i}"   for i in range(LEVELS)]
    + [f"bid_price_{i}"  for i in range(LEVELS)]
    + [f"bid_size_{i}"   for i in range(LEVELS)]
)


def convert(asset: str) -> None:
    src = SRC_DIR / f"{asset}_l25_delta_2026_05_16.csv.gz"
    dst = SRC_DIR / f"{asset}_orderbook_L25_delta.parquet"
    print(f"\n[{asset}] {src.name} -> {dst.name}")
    print(f"  src size: {src.stat().st_size / 1e6:.1f} MB gz")

    # Stream-read CSV with chunked pandas (memory-bound for BTC's ~2 GB CSV)
    chunks = []
    n_total = 0
    for chunk in pd.read_csv(src, chunksize=200_000, dtype={
        "timestamp_us": "int64",
        "market_id": "string",
        "slug": "string",
        "outcome": "string",
    }):
        sub = chunk[TARGET_COLS]
        chunks.append(sub)
        n_total += len(sub)
        if n_total % 500_000 == 0 or n_total == len(sub):
            print(f"  ... {n_total:,} rows")
    df = pd.concat(chunks, ignore_index=True)
    del chunks
    print(f"  total: {len(df):,} rows × {len(df.columns)} cols")
    print(f"  ts range: {pd.Timestamp(df.timestamp_us.min(), unit='us', tz='UTC')} -> "
          f"{pd.Timestamp(df.timestamp_us.max(), unit='us', tz='UTC')}")
    print(f"  unique (slug,outcome): {df[['slug','outcome']].drop_duplicates().shape[0]:,}")

    # Cast price/size columns to float32 to match expected layout (smaller, matches build.py)
    for c in TARGET_COLS:
        if c.startswith(("ask_price", "ask_size", "bid_price", "bid_size")):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float32")

    df.to_parquet(dst, index=False, compression="snappy")
    print(f"  -> wrote {dst.name} ({dst.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    for asset in ("btc", "eth", "sol"):
        convert(asset)
    print("\nDone.")
