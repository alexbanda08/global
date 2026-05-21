"""Convert VPS3 L25 gzipped CSV pulls (May 5-9) to delta parquets matching cache schema.

Source: data/v4/refresh_2026_05_09/vps3_l25_pull/{btc,eth,sol}_l25_full.csv.gz
Target: data/v4/refresh_2026_05_09/cache/{asset}_orderbook_L25_delta.parquet (overwrites stale VPS2 conversion)

Source has SELECT o.* columns: timestamp_us, local_timestamp_us, exchange, market_id, slug, asset_id,
outcome, bid_price_0..24, bid_size_0..24, ask_price_0..24, ask_size_0..24
We keep only what load_l25_for_asset reads.
"""
import os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

OUT_DIR = Path("data/v4/refresh_2026_05_09/cache")
OUT_DIR.mkdir(parents=True, exist_ok=True)

LEVELS = 25
COLS_AP = [f"ask_price_{i}" for i in range(LEVELS)]
COLS_AS = [f"ask_size_{i}" for i in range(LEVELS)]
COLS_BP = [f"bid_price_{i}" for i in range(LEVELS)]
COLS_BS = [f"bid_size_{i}" for i in range(LEVELS)]
KEEP_COLS = ["timestamp_us", "slug", "market_id", "outcome"] + COLS_AP + COLS_AS + COLS_BP + COLS_BS

DTYPES = {"timestamp_us": "int64", "slug": "string", "market_id": "string", "outcome": "string"}
for c in COLS_AP + COLS_AS + COLS_BP + COLS_BS:
    DTYPES[c] = "float32"

for asset in ("btc", "eth", "sol"):
    src = Path(f"data/v4/refresh_2026_05_09/vps3_l25_pull/{asset}_l25_full.csv.gz")
    dst = OUT_DIR / f"{asset}_orderbook_L25_delta.parquet"
    print(f"\n=== {asset.upper()} ===")
    print(f"  src: {src} ({src.stat().st_size / 1e6:.0f} MB gz)")

    # Stream-read gzip CSV in chunks. Per-chunk: select KEEP_COLS, sort, write.
    writer = None
    n_total = 0
    for chunk in pd.read_csv(src, usecols=KEEP_COLS, dtype=DTYPES, chunksize=200_000, compression="gzip"):
        chunk = chunk.sort_values(["market_id", "outcome", "timestamp_us"])
        table = pa.Table.from_pandas(chunk[KEEP_COLS], preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(dst, table.schema, compression="zstd")
        writer.write_table(table)
        n_total += len(chunk)
        if n_total % 1_000_000 < 200_000:
            print(f"    {n_total:,} rows...")
    if writer is not None:
        writer.close()
    print(f"  dst: {dst} ({dst.stat().st_size / 1e6:.0f} MB)  rows={n_total:,}")
