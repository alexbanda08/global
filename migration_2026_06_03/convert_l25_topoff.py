"""Convert L25 top-off CSVs to parquet for refresh_2026_06_03/cache/."""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RAW = ROOT / "data" / "v4" / "refresh_2026_06_03" / "raw"
CACHE = ROOT / "data" / "v4" / "refresh_2026_06_03" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
TAG = "2026_06_03_topoff"

for asset in ["btc", "eth", "sol"]:
    src = RAW / f"{asset}_orderbook_L25_{TAG}.csv.gz"
    dst = CACHE / f"{asset}_orderbook_L25_topoff.parquet"
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
print("\nDone.")
