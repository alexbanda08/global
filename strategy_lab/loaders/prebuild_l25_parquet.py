"""prebuild_l25_parquet — one-time conversion of gzipped raw L25 CSV → parquet
for fast random-access loading.

Why: pandas chunked CSV-gz read of 28M-row BTC file takes 10-20 min. Parquet read
with row-group filtering takes seconds. Run this once after each VPS pull.

Output (per asset):
    data/v4/refresh_2026_05_06/cache/{asset}_orderbook_L25.parquet
    data/v4/refresh_2026_05_06/cache/{asset}_trades.parquet

Subsequent loaders should pyarrow-read these and filter via
    pq.read_table('...parquet', filters=[('slug','in', slug_list)])

Usage:
    py -X utf8 -m strategy_lab.loaders.prebuild_l25_parquet              # all assets
    py -X utf8 -m strategy_lab.loaders.prebuild_l25_parquet --asset sol  # one asset
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06"
CACHE_DIR = DATA_DIR / "cache"
ASSETS = ("btc", "eth", "sol")


def _orderbook_dtypes() -> dict:
    LEVELS = 25
    d: dict = {
        "timestamp_us": "int64",
        "local_timestamp_us": "Int64",
        "exchange": "category",
        "market_id": "string",
        "slug": "string",  # NB: keep string not category — easier for parquet
        "asset_id": "string",
        "outcome": "category",
        "outcome_id": "int8",
        "source": "category",
    }
    for i in range(LEVELS):
        d[f"bid_price_{i}"] = "float32"
        d[f"bid_size_{i}"] = "float32"
        d[f"ask_price_{i}"] = "float32"
        d[f"ask_size_{i}"] = "float32"
    return d


def _trades_dtypes() -> dict:
    return {
        "timestamp_us": "int64",
        "local_timestamp_us": "Int64",
        "exchange": "category",
        "market_id": "string",
        "slug": "string",
        "asset_id": "string",
        "outcome": "category",
        "price": "float32",
        "size": "float32",
        "side": "category",
        "trade_id": "string",
        "origin_asset_id": "string",
        "outcome_id": "int8",
        "source": "category",
    }


def convert_orderbook(asset: str, chunksize: int = 250_000) -> Path:
    """Stream {asset}_orderbook_raw_L25.csv.gz → {asset}_orderbook_L25.parquet.

    Uses pyarrow ParquetWriter to append chunks without holding entire DataFrame
    in memory (avoids the OOM that pandas concat hits on BTC).
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    src = DATA_DIR / f"{asset}_orderbook_raw_L25.csv.gz"
    dst = CACHE_DIR / f"{asset}_orderbook_L25.parquet"
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    print(f"[{asset}] {src.name} → {dst.name}")
    t0 = time.time()
    n_chunks = 0
    n_rows = 0
    writer: pq.ParquetWriter | None = None
    schema: pa.Schema | None = None

    dtypes = _orderbook_dtypes()
    reader = pd.read_csv(src, chunksize=chunksize, dtype=dtypes, engine="c")

    for chunk in reader:
        n_chunks += 1
        n_rows += len(chunk)
        # Sort within chunk by (slug, outcome_id, timestamp_us) to help row-group locality
        chunk = chunk.sort_values(
            ["slug", "outcome_id", "timestamp_us"], kind="mergesort"
        )
        table = pa.Table.from_pandas(chunk, preserve_index=False)
        if writer is None:
            schema = table.schema
            writer = pq.ParquetWriter(
                dst, schema, compression="snappy", use_dictionary=True
            )
        else:
            # Cast to original schema if dtypes drifted (categorical re-codes etc)
            try:
                table = table.cast(schema)
            except Exception:
                pass
        writer.write_table(table)
        if n_chunks % 10 == 0:
            elapsed = time.time() - t0
            print(f"  [{asset}] {n_chunks} chunks  {n_rows:,} rows  {elapsed:.0f}s "
                  f"({n_rows/elapsed/1000:.0f}k rows/sec)")

    if writer is not None:
        writer.close()

    elapsed = time.time() - t0
    print(f"[{asset}] DONE: {n_rows:,} rows in {elapsed:.0f}s — "
          f"{dst.stat().st_size / 1024 / 1024:.0f} MB parquet")
    return dst


def convert_trades(asset: str, chunksize: int = 500_000) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    src = DATA_DIR / f"{asset}_trades_raw.csv.gz"
    dst = CACHE_DIR / f"{asset}_trades.parquet"
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise FileNotFoundError(f"source not found: {src}")

    print(f"[{asset}] {src.name} → {dst.name}")
    t0 = time.time()
    n_chunks = 0
    n_rows = 0
    writer: pq.ParquetWriter | None = None
    schema: pa.Schema | None = None

    dtypes = _trades_dtypes()
    reader = pd.read_csv(src, chunksize=chunksize, dtype=dtypes, engine="c")
    for chunk in reader:
        n_chunks += 1
        n_rows += len(chunk)
        chunk = chunk.sort_values(
            ["slug", "outcome_id", "timestamp_us"], kind="mergesort"
        )
        table = pa.Table.from_pandas(chunk, preserve_index=False)
        if writer is None:
            schema = table.schema
            writer = pq.ParquetWriter(
                dst, schema, compression="snappy", use_dictionary=True
            )
        else:
            try:
                table = table.cast(schema)
            except Exception:
                pass
        writer.write_table(table)
        if n_chunks % 10 == 0:
            elapsed = time.time() - t0
            print(f"  [{asset}] {n_chunks} chunks  {n_rows:,} rows  {elapsed:.0f}s "
                  f"({n_rows/elapsed/1000:.0f}k rows/sec)")

    if writer is not None:
        writer.close()

    elapsed = time.time() - t0
    print(f"[{asset}] DONE: {n_rows:,} rows in {elapsed:.0f}s — "
          f"{dst.stat().st_size / 1024 / 1024:.0f} MB parquet")
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("all",) + ASSETS, default="all")
    ap.add_argument("--skip-trades", action="store_true",
                    help="Convert orderbook only (skip trades)")
    args = ap.parse_args()

    targets = ASSETS if args.asset == "all" else (args.asset,)
    for a in targets:
        convert_orderbook(a)
        if not args.skip_trades:
            convert_trades(a)


if __name__ == "__main__":
    main()
