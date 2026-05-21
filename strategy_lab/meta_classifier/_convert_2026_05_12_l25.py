"""Convert VPS3 L25 gz CSVs from refresh_2026_05_12 → cache parquets."""
import os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

REFRESH = Path("data/v4/refresh_2026_05_12")
SRC_DIR = REFRESH / "vps3_l25_pull"
DST_DIR = REFRESH / "cache"
DST_DIR.mkdir(parents=True, exist_ok=True)

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
    src = SRC_DIR / f"{asset}_l25_full.csv.gz"
    # naming matches build.py expectation for delta cache
    dst = DST_DIR / f"{asset}_orderbook_L25_delta.parquet"
    if not src.exists():
        print(f"  SKIP {asset}: {src} not present")
        continue
    print(f"\n=== {asset.upper()} ===")
    print(f"  src: {src} ({src.stat().st_size / 1e6:.0f} MB gz)")

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
