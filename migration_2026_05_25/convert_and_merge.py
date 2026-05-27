"""
Convert 2026-05-20 -> 2026-05-25 delta CSVs to parquet.

Output:
  data/v4/refresh_2026_05_25/cache/
    {btc,eth,sol}_orderbook_L25_delta.parquet
    {btc,eth,sol}_trades_delta.parquet
    binance_klines_1min_delta.parquet
    binance_klines_1sec_delta.parquet
    oracle_prices_delta.parquet
    market_resolutions_full.parquet
    trading_events_30d.parquet
    hyperliquid_klines_delta.parquet
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TAG = "2026_05_25"
RAW = ROOT / "data" / "v4" / f"refresh_{TAG}" / "raw"
CACHE = ROOT / "data" / "v4" / f"refresh_{TAG}" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

def t(label):
    print(f"\n[{time.strftime('%H:%M:%S')}] {label}", flush=True)

# --- 1. L25 orderbooks ---
t("Converting L25 orderbooks (BTC/ETH/SOL)...")
for asset in ["btc", "eth", "sol"]:
    src = RAW / f"{asset}_orderbook_L25_delta_{TAG}.csv.gz"
    dst = CACHE / f"{asset}_orderbook_L25_delta.parquet"
    if dst.exists():
        print(f"  {asset}: EXISTS, skip"); continue
    t0 = time.time()
    df = pd.read_csv(src, compression="gzip")
    print(f"  {asset}: {len(df):,} rows in {time.time()-t0:.1f}s")
    for col in df.columns:
        if col.startswith(("ask_price","bid_price","ask_size","bid_size")):
            df[col] = df[col].astype("float32")
    df.to_parquet(dst, index=False, compression="snappy")
    print(f"  wrote {dst.name} ({dst.stat().st_size//1024//1024} MB)")

# --- 2. Klines 1MIN ---
t("Converting binance klines 1MIN...")
src = RAW / f"binance_klines_delta_{TAG}.csv.gz"
dst = CACHE / "binance_klines_1min_delta.parquet"
df = pd.read_csv(src, compression="gzip")
print(f"  1MIN rows: {len(df):,}")
print(f"  cols: {list(df.columns)}")
print(f"  source x period: {df.groupby(['source','period_id']).size().to_dict()}")
df.to_parquet(dst, index=False)

# --- 3. Klines 1SEC ---
t("Converting binance klines 1SEC...")
src = RAW / f"binance_klines_1sec_delta_{TAG}.csv.gz"
dst = CACHE / "binance_klines_1sec_delta.parquet"
df = pd.read_csv(src, compression="gzip")
print(f"  1SEC rows: {len(df):,}")
df.to_parquet(dst, index=False)

# --- 4. Oracle prices ---
t("Converting oracle prices (chainlink RTDS)...")
src = RAW / f"oracle_prices_delta_{TAG}.csv.gz"
dst = CACHE / "oracle_prices_delta.parquet"
df = pd.read_csv(src, compression="gzip")
print(f"  oracle rows: {len(df):,}, sources: {df.source.unique() if 'source' in df.columns else 'N/A'}")
df.to_parquet(dst, index=False)

# --- 5. Trades polymarket ---
t("Converting polymarket trades (BTC/ETH/SOL)...")
for asset in ["btc", "eth", "sol"]:
    src = RAW / f"{asset}_trades_delta_{TAG}.csv.gz"
    dst = CACHE / f"{asset}_trades_delta.parquet"
    df = pd.read_csv(src, compression="gzip")
    print(f"  {asset}: {len(df):,} rows")
    df.to_parquet(dst, index=False)

# --- 6. Market resolutions (full pull) ---
t("Converting market resolutions...")
src = RAW / f"market_resolutions_full_{TAG}.csv.gz"
dst = CACHE / "market_resolutions_full.parquet"
df = pd.read_csv(src, compression="gzip")
print(f"  resolutions rows: {len(df):,}")
print(f"  cols: {list(df.columns)}")
df.to_parquet(dst, index=False)

# --- 7. Trading events (full 30d rolling) ---
t("Converting trading.events 30d...")
src = RAW / "trading_events_30d.csv.gz"
dst = CACHE / "trading_events_30d.parquet"
df = pd.read_csv(src, compression="gzip")
print(f"  events rows: {len(df):,}")
df.to_parquet(dst, index=False)

# --- 8. Hyperliquid klines + trades + liqs ---
# (Earlier sessions treated HL trades as "schema mismatch" — actually was a
# pull-script column-name bug, fixed in pull_delta_vps3_2026_05_25.sh on
# 2026-05-25. binance_metrics_v2 stays excluded — VPS3 is geoblocked for
# binance futures.)
t("Converting Hyperliquid klines/trades/liqs...")
for label, raw_name, parquet_name, skip_if_empty in [
    ("klines", "hyperliquid_klines_v2_delta", "hyperliquid_klines_delta", False),
    ("trades", "hyperliquid_trades_v2_delta", "hyperliquid_trades_delta",  True),
    ("liqs",   "hyperliquid_liquidations_v2_delta", "hyperliquid_liquidations_delta", True),
]:
    src = RAW / f"{raw_name}_{TAG}.csv.gz"
    dst = CACHE / f"{parquet_name}.parquet"
    if not src.exists():
        print(f"  HL {label}: {src.name} MISSING — skip")
        continue
    # Files <500 bytes are failed-COPY empty placeholders (just CSV header or nothing).
    if skip_if_empty and src.stat().st_size < 500:
        print(f"  HL {label}: src is empty placeholder ({src.stat().st_size}B), skipping")
        continue
    try:
        df = pd.read_csv(src, compression="gzip")
        print(f"  HL {label}: {len(df):,} rows")
        df.to_parquet(dst, index=False)
    except pd.errors.EmptyDataError:
        print(f"  HL {label}: empty data, skipping")

print("\n=== Conversion done ===")
print(f"Cache contents:")
for f in sorted(CACHE.glob("*.parquet")):
    print(f"  {f.name:<45s} {f.stat().st_size//1024//1024:>5d} MB")
