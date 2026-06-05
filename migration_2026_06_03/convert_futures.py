"""
Convert futures DELTA CSVs -> staging parquets in refresh_2026_06_03/cache/.
Includes bybit+bitget liquidations (now populated) and cex_futures_book (new).
"""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TAG = "2026_06_03"
RAW = ROOT / "data" / "v4" / f"refresh_{TAG}" / "raw"
CACHE = ROOT / "data" / "v4" / f"refresh_{TAG}" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

def t(label):
    print(f"\n[{time.strftime('%H:%M:%S')}] {label}", flush=True)

# 1. klines
t("cex_futures_klines...")
df = pd.read_csv(RAW / "cex_futures_klines.csv.gz", compression="gzip")
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}  periods: {sorted(df.period_id.unique())}")
df.to_parquet(CACHE / "cex_futures_klines_delta.parquet", index=False)

# 2. ticker
t("cex_futures_ticker...")
df = pd.read_csv(RAW / "cex_futures_ticker.csv.gz", compression="gzip")
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}")
print(f"  span: {pd.to_datetime(df.time_exchange_us.min(), unit='us', utc=True)} -> {pd.to_datetime(df.time_exchange_us.max(), unit='us', utc=True)}")
df.to_parquet(CACHE / "cex_futures_ticker_delta.parquet", index=False)

# 3. trades — trade_id is mixed big-int/hash across exchanges; force string
t("cex_futures_trades...")
df = pd.read_csv(RAW / "cex_futures_trades.csv.gz", compression="gzip",
                 dtype={"trade_id": "string", "raw_symbol": "string"})
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}")
df.to_parquet(CACHE / "cex_futures_trades_delta.parquet", index=False)

# 4. liquidations — gate + okx + bybit + bitget combined (tag exchange from filename)
t("cex_futures_liquidations (gate + okx + bybit + bitget)...")
parts = []
for ex in ["gate", "okx", "bybit", "bitget"]:
    f = RAW / f"{ex}_liquidations.csv.gz"
    if not f.exists():
        print(f"  {ex}: MISSING, skip"); continue
    d = pd.read_csv(f, compression="gzip", dtype={"raw_symbol": "string"} if "raw_symbol" in pd.read_csv(f, compression="gzip", nrows=1).columns else {})
    if len(d) == 0:
        print(f"  {ex}: 0 rows, skip"); continue
    if "exchange" not in d.columns:
        d.insert(0, "exchange", ex)
    print(f"  {ex}: {len(d):,} rows")
    parts.append(d)
if parts:
    out = pd.concat(parts, ignore_index=True).sort_values("time_exchange_us").reset_index(drop=True)
    print(f"  combined: {len(out):,} rows  exchanges: {sorted(out.exchange.unique())}")
    out.to_parquet(CACHE / "cex_futures_liquidations_delta.parquet", index=False)
else:
    print("  no liquidation rows — skipping file")

# 5. cex_futures_book (new canonical table — full pull)
t("cex_futures_book (new table)...")
df = pd.read_csv(RAW / "cex_futures_book.csv.gz", compression="gzip")
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}")
print(f"  span: {pd.to_datetime(df.time_exchange_us.min(), unit='us', utc=True)} -> {pd.to_datetime(df.time_exchange_us.max(), unit='us', utc=True)}")
df.to_parquet(CACHE / "cex_futures_book_full.parquet", index=False)

print("\n=== DONE ===")
for p in sorted(CACHE.glob("*.parquet")):
    print(f"  {p.name:<50s} {p.stat().st_size//1024//1024:>5d} MB")
