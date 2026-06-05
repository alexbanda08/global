"""
Convert the NEW cross-exchange futures CSVs -> canonical parquets (full replace).
First canonical ingest of bitget/bybit/gate/okx perp data.

Writes:
  canonical/cex_futures_klines.parquet        (OHLCV 1m/5m/15m, 4 ex x 6 syms)
  canonical/cex_futures_ticker.parquet        (mark/index/last/funding/OI, ~10M rows)
  canonical/cex_futures_trades.parquet        (taker prints)
  canonical/cex_futures_liquidations.parquet  (gate+okx combined, 'exchange' col added)
"""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RAW = ROOT / "data" / "v4" / "refresh_2026_06_01" / "raw"
CANON = ROOT / "data" / "v4" / "canonical"

def t(label):
    print(f"\n[{time.strftime('%H:%M:%S')}] {label}", flush=True)

# 1. klines
t("cex_futures_klines...")
df = pd.read_csv(RAW / "cex_futures_klines.csv.gz", compression="gzip")
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}  periods: {sorted(df.period_id.unique())}")
df.to_parquet(CANON / "cex_futures_klines.parquet", index=False)
print(f"  -> cex_futures_klines.parquet ({(CANON/'cex_futures_klines.parquet').stat().st_size//1024//1024} MB)")

# 2. ticker (big — funding/OI/mark)
t("cex_futures_ticker...")
df = pd.read_csv(RAW / "cex_futures_ticker.csv.gz", compression="gzip")
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}")
print(f"  span: {pd.to_datetime(df.time_exchange_us.min(), unit='us', utc=True)} -> {pd.to_datetime(df.time_exchange_us.max(), unit='us', utc=True)}")
df.to_parquet(CANON / "cex_futures_ticker.parquet", index=False)
print(f"  -> cex_futures_ticker.parquet ({(CANON/'cex_futures_ticker.parquet').stat().st_size//1024//1024} MB)")

# 3. trades — trade_id is mixed big-int/hash across exchanges; force string to avoid
#    pyarrow "could not convert ... to int64" on the object column.
t("cex_futures_trades...")
df = pd.read_csv(RAW / "cex_futures_trades.csv.gz", compression="gzip",
                 dtype={"trade_id": "string", "raw_symbol": "string"})
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}")
df.to_parquet(CANON / "cex_futures_trades.parquet", index=False)
print(f"  -> cex_futures_trades.parquet ({(CANON/'cex_futures_trades.parquet').stat().st_size//1024//1024} MB)")

# 4. liquidations gate + okx combined (tag exchange from filename)
t("cex_futures_liquidations (gate + okx)...")
parts = []
for ex in ["gate", "okx"]:
    f = RAW / f"{ex}_liquidations.csv.gz"
    if not f.exists():
        print(f"  {ex}: MISSING, skip"); continue
    d = pd.read_csv(f, compression="gzip")
    if len(d) == 0:
        print(f"  {ex}: 0 rows, skip"); continue
    d.insert(0, "exchange", ex)
    print(f"  {ex}: {len(d):,} rows")
    parts.append(d)
if parts:
    out = pd.concat(parts, ignore_index=True).sort_values("time_exchange_us").reset_index(drop=True)
    out.to_parquet(CANON / "cex_futures_liquidations.parquet", index=False)
    print(f"  -> cex_futures_liquidations.parquet ({len(out):,} rows, exchanges: {sorted(out.exchange.unique())})")
else:
    print("  no liquidation rows — skipping file")

print("\n=== DONE ===")
