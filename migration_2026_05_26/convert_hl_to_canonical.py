"""Convert HL klines + HL liquidations full pulls to canonical parquets."""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
HL = ROOT / "data" / "v4" / "canonical" / "hyperliquid"

def t(label):
    print(f"\n[{time.strftime('%H:%M:%S')}] {label}", flush=True)

# 1. klines
t("HL klines ...")
src = HL / "hyperliquid_klines.csv.gz"
dst = HL / "klines.parquet"
t0 = time.time()
df = pd.read_csv(src, compression="gzip")
print(f"  rows: {len(df):,}  ({time.time()-t0:.1f}s)")
print(f"  cols: {list(df.columns)}")
print(f"  unique symbols: {df.symbol_id.nunique()}  unique periods: {sorted(df.period_id.unique())}")
print(f"  ts window: {pd.to_datetime(df.time_period_start_us.min(), unit='us', utc=True)}  ->  {pd.to_datetime(df.time_period_start_us.max(), unit='us', utc=True)}")
df = df.sort_values(["symbol_id","period_id","time_period_start_us"]).reset_index(drop=True)
df.to_parquet(dst, index=False, compression="snappy")
sz = dst.stat().st_size / 1024 / 1024
print(f"  -> {dst.name} ({sz:.1f} MB)")

# 2. liquidations
t("HL liquidations ...")
src = HL / "hyperliquid_liquidations.csv.gz"
dst = HL / "liquidations.parquet"
t0 = time.time()
df = pd.read_csv(src, compression="gzip")
print(f"  rows: {len(df):,}  ({time.time()-t0:.1f}s)")
print(f"  cols: {list(df.columns)}")
print(f"  unique coins: {df.coin.nunique()}  top10: {df.coin.value_counts().head(10).to_dict()}")
print(f"  ts window: {pd.to_datetime(df.time_exchange_us.min(), unit='us', utc=True)}  ->  {pd.to_datetime(df.time_exchange_us.max(), unit='us', utc=True)}")
df = df.sort_values("time_exchange_us").reset_index(drop=True)
df.to_parquet(dst, index=False, compression="snappy")
sz = dst.stat().st_size / 1024 / 1024
print(f"  -> {dst.name} ({sz:.1f} MB)")

# Clean up the raw .gz files (kept only briefly for the scp step)
print("\n=== DONE ===")
for p in sorted(HL.glob("*.parquet")):
    print(f"  {p.name:<25s} {p.stat().st_size//1024//1024:>6d} MB")
