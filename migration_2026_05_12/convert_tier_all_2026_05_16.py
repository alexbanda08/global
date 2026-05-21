"""Convert all Tier 1+2+3 backfill CSVs to parquet, place in canonical structure.

Input CSVs (under data/v4/refresh_2026_05_16/):
  cache_v2_full/{btc,eth,sol}_l25_pre_apr22.csv.gz   -- L25 Apr 18-22 from VPS2
  cache_v2_full/okx_klines_full.csv.gz                 -- VPS2 OKX klines
  cache_v2_full/hl_klines_full.csv.gz                  -- VPS2 hyperliquid klines
  cache_v3_full/binance_1sec_full.csv.gz               -- VPS3 binance 1SEC (live+archive)
  cache_v3_full/binance_vision_full.csv.gz             -- VPS3 binance-vision archive 1MIN+
  cache_v3_full/{btc,eth,sol}_trades_full.csv.gz       -- VPS3 polymarket trades Apr22 -> now
  cache_v3_full/hl_trades_30d.csv.gz                   -- VPS3 hyperliquid trades 30d
  cache_v3_full/hl_liquidations_30d.csv.gz             -- VPS3 hyperliquid liquidations 30d
  cache_v3_full/trading_events_30d.csv.gz              -- VPS3 trading.events 30d

Outputs:
  refresh_2026_05_16/cache_pre/{asset}_orderbook_L25_pre_apr22.parquet
  data/v4/canonical/klines_1s.parquet                  -- binance 1SEC (new)
  data/v4/canonical/binance_vision_klines.parquet      -- vision archive (long history)
  data/v4/canonical/okx_klines.parquet                 -- OKX klines (new)
  data/v4/canonical/hyperliquid_klines.parquet         -- HL klines (new)
  data/v4/canonical/trades_polymarket/{asset}.parquet  -- REPLACES stale trades (current)
  data/v4/canonical/hyperliquid_trades_30d.parquet     -- new
  data/v4/canonical/hyperliquid_liquidations_30d.parquet -- new
  data/v4/canonical/trading_events_30d.parquet         -- replaces 14d version
"""
from __future__ import annotations

import gzip
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
V2_SRC = ROOT / "data/v4/refresh_2026_05_16/cache_v2_full"
V3_SRC = ROOT / "data/v4/refresh_2026_05_16/cache_v3_full"
CANON = ROOT / "data/v4/canonical"
PRE_CACHE = ROOT / "data/v4/refresh_2026_05_16/cache_pre"
PRE_CACHE.mkdir(parents=True, exist_ok=True)
(CANON / "trades_polymarket").mkdir(parents=True, exist_ok=True)

LEVELS = 25
L25_TARGET = (
    ["timestamp_us", "slug", "market_id", "outcome"]
    + [f"ask_price_{i}" for i in range(LEVELS)]
    + [f"ask_size_{i}"  for i in range(LEVELS)]
    + [f"bid_price_{i}" for i in range(LEVELS)]
    + [f"bid_size_{i}"  for i in range(LEVELS)]
)

def _stream_csv_to_parquet(src: Path, dst: Path, schema: pa.Schema,
                            include_cols: list[str] | None = None,
                            column_types: dict | None = None,
                            block_size_mb: int = 64) -> tuple[int, int, int]:
    """Stream gzipped CSV through pyarrow to parquet. Returns (rows, min_ts, max_ts).
    min_ts/max_ts in microseconds from first matching int64 timestamp_us column."""
    convert_opts = pacsv.ConvertOptions(
        include_columns=include_cols,
        column_types=column_types or {},
    )
    read_opts = pacsv.ReadOptions(block_size=block_size_mb << 20)
    writer = pq.ParquetWriter(dst, schema, compression="snappy")
    n = 0
    min_ts = None; max_ts = None
    with gzip.open(src, "rb") as gz:
        reader = pacsv.open_csv(gz, read_options=read_opts, convert_options=convert_opts)
        for batch in reader:
            tbl = pa.Table.from_batches([batch]).select(schema.names)
            for b in tbl.to_batches():
                writer.write_batch(b)
                n += b.num_rows
                # capture min/max for any int64 ts-like column
                for ts_col in ("timestamp_us", "time_period_start_us", "time_exchange_us"):
                    if ts_col in b.schema.names:
                        arr = b.column(ts_col).to_numpy()
                        if arr.size:
                            mn, mx = int(arr.min()), int(arr.max())
                            min_ts = mn if min_ts is None else min(min_ts, mn)
                            max_ts = mx if max_ts is None else max(max_ts, mx)
                        break
    writer.close()
    return n, min_ts, max_ts


def build_l25_schema() -> pa.Schema:
    fields = [pa.field("timestamp_us", pa.int64()),
              pa.field("slug", pa.string()),
              pa.field("market_id", pa.string()),
              pa.field("outcome", pa.string())]
    for prefix in ("ask_price", "ask_size", "bid_price", "bid_size"):
        for i in range(LEVELS):
            fields.append(pa.field(f"{prefix}_{i}", pa.float32()))
    return pa.schema(fields)


def convert_l25_pre(asset: str):
    src = V2_SRC / f"{asset}_l25_pre_apr22.csv.gz"
    dst = PRE_CACHE / f"{asset}_orderbook_L25_pre_apr22.parquet"
    print(f"\n[L25-pre {asset}] {src.name} -> {dst.name}")
    schema = build_l25_schema()
    col_types = {"timestamp_us": pa.int64(), "slug": pa.string(),
                 "market_id": pa.string(), "outcome": pa.string(),
                 **{f"{p}_{i}": pa.float32()
                    for p in ("ask_price","ask_size","bid_price","bid_size") for i in range(LEVELS)}}
    n, mn, mx = _stream_csv_to_parquet(src, dst, schema, include_cols=L25_TARGET, column_types=col_types)
    import pandas as pd
    print(f"  rows: {n:,}  ts: {pd.Timestamp(mn, unit='us', tz='UTC')} -> {pd.Timestamp(mx, unit='us', tz='UTC')}  size: {dst.stat().st_size/1e6:.1f} MB")


def convert_klines_kind(label: str, src: Path, dst: Path):
    """klines CSVs share the same schema."""
    print(f"\n[{label}] {src.name} -> {dst.name}")
    schema = pa.schema([
        pa.field("symbol_id", pa.string()),
        pa.field("period_id", pa.string()),
        pa.field("source", pa.string()),
        pa.field("time_period_start_us", pa.int64()),
        pa.field("time_period_end_us", pa.int64()),
        pa.field("price_open", pa.float64()),
        pa.field("price_high", pa.float64()),
        pa.field("price_low", pa.float64()),
        pa.field("price_close", pa.float64()),
        pa.field("volume_traded", pa.float64()),
        pa.field("trades_count", pa.int64()),
        pa.field("quote_volume", pa.float64()),
    ])
    col_types = {f.name: f.type for f in schema}
    n, mn, mx = _stream_csv_to_parquet(src, dst, schema, include_cols=schema.names, column_types=col_types)
    import pandas as pd
    print(f"  rows: {n:,}  ts: {pd.Timestamp(mn, unit='us', tz='UTC')} -> {pd.Timestamp(mx, unit='us', tz='UTC')}  size: {dst.stat().st_size/1e6:.1f} MB")


def convert_hl_klines(src: Path, dst: Path):
    """HL klines may have different columns. Use a more flexible read."""
    print(f"\n[HL klines] {src.name} -> {dst.name}")
    # Read header first to learn columns
    import gzip as _gz
    with _gz.open(src, "rt") as f:
        header = f.readline().strip().split(",")
    print(f"  header cols: {header}")
    # Build schema dynamically with sensible types
    fields = []
    for c in header:
        if c.endswith("_us"):
            fields.append(pa.field(c, pa.int64()))
        elif c in ("price_open", "price_high", "price_low", "price_close",
                   "volume_traded", "quote_volume"):
            fields.append(pa.field(c, pa.float64()))
        elif c == "trades_count":
            fields.append(pa.field(c, pa.int64()))
        else:
            fields.append(pa.field(c, pa.string()))
    schema = pa.schema(fields)
    col_types = {f.name: f.type for f in fields}
    n, mn, mx = _stream_csv_to_parquet(src, dst, schema, include_cols=schema.names, column_types=col_types)
    import pandas as pd
    print(f"  rows: {n:,}  ts: {pd.Timestamp(mn, unit='us', tz='UTC')} -> {pd.Timestamp(mx, unit='us', tz='UTC')}  size: {dst.stat().st_size/1e6:.1f} MB")


def convert_polymarket_trades(asset: str):
    src = V3_SRC / f"{asset}_trades_full.csv.gz"
    dst = CANON / "trades_polymarket" / f"{asset}.parquet"
    print(f"\n[trades {asset}] {src.name} -> {dst.name}")
    # Read header to discover columns
    import gzip as _gz
    with _gz.open(src, "rt") as f:
        header = f.readline().strip().split(",")
    fields = []
    for c in header:
        if c.endswith("_us"):
            fields.append(pa.field(c, pa.int64()))
        elif c in ("price", "size"):
            fields.append(pa.field(c, pa.float64()))
        else:
            fields.append(pa.field(c, pa.string()))
    schema = pa.schema(fields)
    col_types = {f.name: f.type for f in fields}
    n, mn, mx = _stream_csv_to_parquet(src, dst, schema, include_cols=schema.names, column_types=col_types, block_size_mb=128)
    import pandas as pd
    print(f"  rows: {n:,}  ts: {pd.Timestamp(mn, unit='us', tz='UTC')} -> {pd.Timestamp(mx, unit='us', tz='UTC')}  size: {dst.stat().st_size/1e6:.1f} MB")


def convert_simple(label: str, src: Path, dst: Path, ts_col_hint: str | None = None):
    """For HL trades/liquidations + trading.events. Infer schema from header."""
    print(f"\n[{label}] {src.name} -> {dst.name}")
    import gzip as _gz
    with _gz.open(src, "rt") as f:
        header = f.readline().strip().split(",")
    print(f"  header cols ({len(header)}): {header[:8]}{'...' if len(header)>8 else ''}")
    fields = []
    for c in header:
        if c.endswith("_us") or c in ("block_number", "block_time_us", "tid", "oid"):
            fields.append(pa.field(c, pa.int64()))
        elif c in ("price","size","mark_price","start_position","closed_pnl","fee"):
            fields.append(pa.field(c, pa.float64()))
        elif c in ("crossed",):
            # Postgres bools come as 't'/'f' — pyarrow can't auto-cast; keep as string
            fields.append(pa.field(c, pa.string()))
        elif c == "data":
            # trading.events.data is JSON; keep as string
            fields.append(pa.field(c, pa.string()))
        else:
            fields.append(pa.field(c, pa.string()))
    schema = pa.schema(fields)
    col_types = {f.name: f.type for f in fields}
    n, mn, mx = _stream_csv_to_parquet(src, dst, schema, include_cols=schema.names, column_types=col_types, block_size_mb=128)
    import pandas as pd
    if mn is not None:
        print(f"  rows: {n:,}  ts: {pd.Timestamp(mn, unit='us', tz='UTC')} -> {pd.Timestamp(mx, unit='us', tz='UTC')}  size: {dst.stat().st_size/1e6:.1f} MB")
    else:
        print(f"  rows: {n:,}  size: {dst.stat().st_size/1e6:.1f} MB")


def main():
    # --- L25 Apr 18-22 from VPS2 ---
    for a in ("btc", "eth", "sol"):
        convert_l25_pre(a)

    # --- Klines ---
    convert_klines_kind("OKX klines",      V2_SRC / "okx_klines_full.csv.gz",      CANON / "okx_klines.parquet")
    convert_klines_kind("binance 1SEC",    V3_SRC / "binance_1sec_full.csv.gz",    CANON / "klines_1s.parquet")
    convert_klines_kind("binance-vision",  V3_SRC / "binance_vision_full.csv.gz",  CANON / "binance_vision_klines.parquet")
    convert_hl_klines(V2_SRC / "hl_klines_full.csv.gz", CANON / "hyperliquid_klines.parquet")

    # --- Polymarket trades (replaces stale May 6 cache) ---
    for a in ("btc", "eth", "sol"):
        convert_polymarket_trades(a)

    # --- Hyperliquid trades + liquidations ---
    convert_simple("HL trades 30d",     V3_SRC / "hl_trades_30d.csv.gz",       CANON / "hyperliquid_trades_30d.parquet")
    convert_simple("HL liqs 30d",       V3_SRC / "hl_liquidations_30d.csv.gz", CANON / "hyperliquid_liquidations_30d.parquet")

    # --- trading.events 30d ---
    convert_simple("trading.events 30d", V3_SRC / "trading_events_30d.csv.gz", CANON / "trading_events_30d.parquet")

    print("\n=== ALL DONE ===")


if __name__ == "__main__":
    main()
