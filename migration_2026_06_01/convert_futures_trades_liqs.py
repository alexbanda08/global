"""Finish futures convert: trades (force trade_id=str) + liquidations. klines+ticker already done."""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RAW = ROOT / "data" / "v4" / "refresh_2026_06_01" / "raw"
CANON = ROOT / "data" / "v4" / "canonical"

def t(label): print(f"\n[{time.strftime('%H:%M:%S')}] {label}", flush=True)

# trades — trade_id is mixed (big numeric ids + possibly hashes) -> force string
t("cex_futures_trades (trade_id as str)...")
df = pd.read_csv(RAW / "cex_futures_trades.csv.gz", compression="gzip",
                 dtype={"trade_id": "string", "raw_symbol": "string"})
print(f"  {len(df):,} rows  exchanges: {sorted(df.exchange.unique())}")
print(f"  span: {pd.to_datetime(df.time_exchange_us.min(), unit='us', utc=True)} -> {pd.to_datetime(df.time_exchange_us.max(), unit='us', utc=True)}")
df.to_parquet(CANON / "cex_futures_trades.parquet", index=False)
print(f"  -> cex_futures_trades.parquet ({(CANON/'cex_futures_trades.parquet').stat().st_size//1024//1024} MB)")

# liquidations gate + okx combined
t("cex_futures_liquidations (gate + okx)...")
parts = []
for ex in ["gate", "okx"]:
    f = RAW / f"{ex}_liquidations.csv.gz"
    if not f.exists():
        print(f"  {ex}: MISSING, skip"); continue
    d = pd.read_csv(f, compression="gzip", dtype={"raw_symbol": "string"})
    if len(d) == 0:
        print(f"  {ex}: 0 rows, skip"); continue
    d.insert(0, "exchange", ex)
    print(f"  {ex}: {len(d):,} rows")
    parts.append(d)
if parts:
    out = pd.concat(parts, ignore_index=True).sort_values("time_exchange_us").reset_index(drop=True)
    out.to_parquet(CANON / "cex_futures_liquidations.parquet", index=False)
    print(f"  -> cex_futures_liquidations.parquet ({len(out):,} rows, exchanges: {sorted(out.exchange.unique())})")

print("\n=== DONE ===")
