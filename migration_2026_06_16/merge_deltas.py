"""Merge pulled delta CSVs -> canonical/orderbook_deltas/{asset}.parquet (ZSTD).
First run = create; subsequent = append + dedup. Dedup key = hash if present else
(slug,timestamp_us,asset_id,side,price,size). Forward-only stream; keep it simple until volume
forces a streaming rewrite (deltas can hit ~100M rows/day at full crypto scope — 15m-only is lighter)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RAW = ROOT / "data" / "v4" / "refresh_2026_06_16" / "raw"
OUT = ROOT / "data" / "v4" / "canonical" / "orderbook_deltas"
OUT.mkdir(parents=True, exist_ok=True)
KEEP = ["timestamp_us","local_timestamp_us","market_id","slug","asset_id","outcome","outcome_id","side","price","size","hash","source"]

def merge(asset: str):
    gz = RAW / f"{asset}_orderbook_deltas.csv.gz"
    if not gz.exists():
        print(f"  {asset}: no delta gz, skip"); return
    d = pd.read_csv(gz, compression="gzip")
    for c in ("price","size"): d[c] = d[c].astype("float32")
    d["timestamp_us"] = d["timestamp_us"].astype("int64")
    dst = OUT / f"{asset}.parquet"
    if dst.exists():
        old = pd.read_parquet(dst)
        before = len(old)
        d = pd.concat([old, d], ignore_index=True)
    else:
        before = 0
    key = ["hash"] if d["hash"].notna().all() else ["slug","timestamp_us","asset_id","side","price","size"]
    d = d.drop_duplicates(key).sort_values(["slug","outcome","timestamp_us"]).reset_index(drop=True)
    d[KEEP].to_parquet(dst, index=False, compression="zstd")
    print(f"  {asset}: {before:,} -> {len(d):,} rows  ({dst.stat().st_size//1024//1024} MB)  dedup-key={key}")

for a in ["btc","eth","sol"]:
    merge(a)
print("=== deltas merged -> canonical/orderbook_deltas/ ===")
