"""Convert VPS2 L25 CSV pulls (May 6-8) to parquet matching the cache schema.

Source: data/v4/shadow_trades_2026_05_08/vps2_l25_{btc,eth,sol}.csv
Target: data/v4/refresh_2026_05_09/cache/{asset}_orderbook_L25_delta.parquet

The existing momo_full_universe_validation.load_l25_for_asset() already looks for
the *_L25_delta.parquet files in REFRESH_NEW/cache. Schema columns required:
  timestamp_us, slug, market_id, outcome, ask_price_0..24, ask_size_0..24,
  bid_price_0..24, bid_size_0..24
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
    src = Path(f"data/v4/shadow_trades_2026_05_08/vps2_l25_{asset}.csv")
    dst = OUT_DIR / f"{asset}_orderbook_L25_delta.parquet"
    print(f"\n=== {asset.upper()} ===")
    print(f"  src: {src} ({src.stat().st_size / 1e6:.0f} MB)")

    writer = None
    n_total = 0
    for chunk in pd.read_csv(src, usecols=KEEP_COLS, dtype=DTYPES, chunksize=200_000):
        # Sort by (market_id, outcome, timestamp_us) per-chunk to match cache layout
        chunk = chunk.sort_values(["market_id", "outcome", "timestamp_us"])
        table = pa.Table.from_pandas(chunk[KEEP_COLS], preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(dst, table.schema, compression="zstd")
        writer.write_table(table)
        n_total += len(chunk)
        print(f"    +{len(chunk):,} rows (cumulative {n_total:,})")
    if writer is not None:
        writer.close()
    print(f"  dst: {dst} ({dst.stat().st_size / 1e6:.0f} MB)  rows={n_total:,}")
