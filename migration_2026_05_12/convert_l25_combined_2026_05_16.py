"""Stream-convert + merge L25 gap (May 6 14 -> May 10 14) + main (May 10 14 -> May 17)
into one parquet per asset. Writes batches incrementally to avoid OOM on BTC's 12M rows.

Output: data/v4/refresh_2026_05_16/cache/{asset}_orderbook_L25_delta.parquet
"""
from __future__ import annotations

import gzip
import io
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
SRC_DIR = ROOT / "data/v4/refresh_2026_05_16/cache_v2"
DST_DIR = ROOT / "data/v4/refresh_2026_05_16/cache"
DST_DIR.mkdir(parents=True, exist_ok=True)

LEVELS = 25
TARGET_COLS = (
    ["timestamp_us", "slug", "market_id", "outcome"]
    + [f"ask_price_{i}"  for i in range(LEVELS)]
    + [f"ask_size_{i}"   for i in range(LEVELS)]
    + [f"bid_price_{i}"  for i in range(LEVELS)]
    + [f"bid_size_{i}"   for i in range(LEVELS)]
)

# Build target schema: float32 for prices/sizes
def build_schema() -> pa.Schema:
    fields = [
        pa.field("timestamp_us", pa.int64()),
        pa.field("slug", pa.string()),
        pa.field("market_id", pa.string()),
        pa.field("outcome", pa.string()),
    ]
    for i in range(LEVELS):
        fields.append(pa.field(f"ask_price_{i}", pa.float32()))
    for i in range(LEVELS):
        fields.append(pa.field(f"ask_size_{i}", pa.float32()))
    for i in range(LEVELS):
        fields.append(pa.field(f"bid_price_{i}", pa.float32()))
    for i in range(LEVELS):
        fields.append(pa.field(f"bid_size_{i}", pa.float32()))
    return pa.schema(fields)


def stream_batches(p: Path, schema: pa.Schema):
    """Yield RecordBatches from a gzipped CSV, projected to target schema."""
    with gzip.open(p, "rb") as gz:
        # pyarrow can read from a file-like object; we wrap gz in a buffered reader
        reader = pacsv.open_csv(
            gz,
            read_options=pacsv.ReadOptions(block_size=64 << 20),  # 64 MB blocks
            convert_options=pacsv.ConvertOptions(
                include_columns=TARGET_COLS,
                column_types={
                    "timestamp_us": pa.int64(),
                    "slug": pa.string(),
                    "market_id": pa.string(),
                    "outcome": pa.string(),
                    **{f"{p}_{i}": pa.float32() for p in ("ask_price","ask_size","bid_price","bid_size") for i in range(LEVELS)},
                },
            ),
        )
        for batch in reader:
            # reorder to TARGET_COLS
            tbl = pa.Table.from_batches([batch]).select(TARGET_COLS)
            for b in tbl.to_batches():
                yield b


def convert(asset: str) -> None:
    gap = SRC_DIR / f"{asset}_l25_gap.csv.gz"
    main = SRC_DIR / f"{asset}_l25_main.csv.gz"
    dst = DST_DIR / f"{asset}_orderbook_L25_delta.parquet"
    print(f"\n[{asset}] {gap.name} + {main.name} -> {dst.name}")
    print(f"  gap_gz: {gap.stat().st_size / 1e6:.1f} MB  main_gz: {main.stat().st_size / 1e6:.1f} MB")

    schema = build_schema()
    writer = pq.ParquetWriter(dst, schema, compression="snappy")
    total = 0
    min_ts = None; max_ts = None
    slug_outcome_set = set()
    try:
        for src in (gap, main):
            print(f"  streaming {src.name}...")
            for batch in stream_batches(src, schema):
                writer.write_batch(batch)
                total += batch.num_rows
                ts_arr = batch.column("timestamp_us").to_numpy()
                if ts_arr.size:
                    mn = int(ts_arr.min()); mx = int(ts_arr.max())
                    min_ts = mn if min_ts is None else min(min_ts, mn)
                    max_ts = mx if max_ts is None else max(max_ts, mx)
                slugs = batch.column("slug").to_pylist()
                outs = batch.column("outcome").to_pylist()
                for s, o in zip(slugs, outs):
                    slug_outcome_set.add((s, o))
                if total % 1_000_000 < batch.num_rows:
                    print(f"    ... {total:,} rows")
    finally:
        writer.close()

    import pandas as pd
    print(f"  total: {total:,} rows")
    print(f"  ts range: {pd.Timestamp(min_ts, unit='us', tz='UTC')} -> {pd.Timestamp(max_ts, unit='us', tz='UTC')}")
    print(f"  unique (slug, outcome): {len(slug_outcome_set):,}")
    print(f"  -> wrote {dst.name} ({dst.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    for asset in ("btc", "eth", "sol"):
        convert(asset)
    print("\nDone.")
