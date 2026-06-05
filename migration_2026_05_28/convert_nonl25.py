"""Convert non-L25 delta CSVs to parquet for refresh_2026_05_28/cache/."""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TAG = "2026_05_28"
RAW = ROOT / "data" / "v4" / f"refresh_{TAG}" / "raw"
CACHE = ROOT / "data" / "v4" / f"refresh_{TAG}" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

def t(label):
    print(f"\n[{time.strftime('%H:%M:%S')}] {label}", flush=True)

t("binance 1MIN/5MIN/15MIN...")
src = RAW / f"binance_klines_delta_{TAG}.csv.gz"
df = pd.read_csv(src, compression="gzip")
print(f"  {len(df):,} rows  src x period: {df.groupby(['source','period_id']).size().to_dict()}")
df.to_parquet(CACHE / "binance_klines_1min_delta.parquet", index=False)

t("binance 1SEC...")
src = RAW / f"binance_klines_1sec_delta_{TAG}.csv.gz"
df = pd.read_csv(src, compression="gzip")
print(f"  {len(df):,} rows")
df.to_parquet(CACHE / "binance_klines_1sec_delta.parquet", index=False)

t("oracle (chainlink RTDS)...")
src = RAW / f"oracle_prices_delta_{TAG}.csv.gz"
df = pd.read_csv(src, compression="gzip")
print(f"  {len(df):,} rows  sources: {df.source.unique() if 'source' in df.columns else 'N/A'}")
df.to_parquet(CACHE / "oracle_prices_delta.parquet", index=False)

t("polymarket trades (BTC/ETH/SOL)...")
for asset in ["btc","eth","sol"]:
    src = RAW / f"{asset}_trades_delta_{TAG}.csv.gz"
    df = pd.read_csv(src, compression="gzip")
    print(f"  {asset}: {len(df):,} rows")
    df.to_parquet(CACHE / f"{asset}_trades_delta.parquet", index=False)

t("market_resolutions FULL...")
src = RAW / f"market_resolutions_full_{TAG}.csv.gz"
df = pd.read_csv(src, compression="gzip")
print(f"  {len(df):,} rows")
df.to_parquet(CACHE / "market_resolutions_full.parquet", index=False)

t("trading.events 30d...")
src = RAW / "trading_events_30d.csv.gz"
df = pd.read_csv(src, compression="gzip")
print(f"  {len(df):,} rows")
df.to_parquet(CACHE / "trading_events_30d.parquet", index=False)

t("Hyperliquid klines/trades/liqs deltas...")
for label, raw_name, parquet_name in [
    ("klines", "hyperliquid_klines_v2_delta", "hyperliquid_klines_delta"),
    ("trades", "hyperliquid_trades_v2_delta", "hyperliquid_trades_delta"),
    ("liqs",   "hyperliquid_liquidations_v2_delta", "hyperliquid_liquidations_delta"),
]:
    src = RAW / f"{raw_name}_{TAG}.csv.gz"
    if not src.exists() or src.stat().st_size < 500:
        print(f"  HL {label}: missing or empty placeholder, skip"); continue
    df = pd.read_csv(src, compression="gzip")
    print(f"  HL {label}: {len(df):,} rows")
    df.to_parquet(CACHE / f"{parquet_name}.parquet", index=False)

print("\n=== DONE ===")
for p in sorted(CACHE.glob("*.parquet")):
    print(f"  {p.name:<45s} {p.stat().st_size//1024//1024:>5d} MB")
