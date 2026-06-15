import os
import pyarrow.parquet as pq
import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
p = os.path.join(ROOT, r"data\v4\canonical\_results\dirscan_eth_5m.parquet")
f = pq.ParquetFile(p)
cols = f.schema.names
print("dirscan_eth_5m rows:", f.metadata.num_rows)
print("ALL COLUMNS:")
for c in cols:
    print("  ", c)
df = pd.read_parquet(p).head(3)
print("\nsample rows (key cols):")
keys = [c for c in ["fire_us", "ws_s", "direction", "outcome", "won", "entry_vwap",
                    "fill_vwap", "offset_s", "ema50", "tr_above_ema50", "hurst",
                    "hurst_300s", "grandparent", "liquidity_up", "liquidity_dn"] if c in cols]
print(df[keys].to_string() if keys else "(none of the key cols present)")
