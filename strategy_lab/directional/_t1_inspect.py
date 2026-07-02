"""T1 inspector v2 — memory-safe: schema + first-batch sample + streamed ts range."""
import sys, os
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from load import load_resolutions, CANON

p = CANON / "trades_polymarket" / "btc.parquet"
print("file:", p, "exists", p.exists(), "size_MB", round(os.path.getsize(p)/1e6,1))
sch = pq.read_schema(p)
print("COLS:", sch.names)
pf = pq.ParquetFile(p)
print("num_row_groups", pf.num_row_groups, "num_rows", pf.metadata.num_rows)
# first batch sample
b = next(pf.iter_batches(batch_size=2000))
df = b.to_pandas()
print("sample rows:\n", df.head(4).to_string())
for key in ["slug","outcome","side","price","size","token","asset","time","ts"]:
    cols = [c for c in df.columns if key in c.lower()]
    if cols:
        print(f"  {key!r} -> {cols}; sample {list(pd.Series(df[cols[0]]).dropna().unique()[:5])}")
# streamed ts range over a single ts-like column (pick the best candidate)
ts_col = None
for c in sch.names:
    if c.lower() in ("timestamp_us","ts_us","time_us","ts_ms","timestamp_ms","match_time_ms","timestamp"):
        ts_col = c; break
if ts_col is None:
    ts_col = next((c for c in sch.names if "time" in c.lower() or c.lower().endswith("_us") or c.lower().endswith("_ms")), None)
print("ts_col chosen:", ts_col)
if ts_col:
    mn, mx = None, None
    for bt in pf.iter_batches(columns=[ts_col], batch_size=1_000_000):
        v = pd.to_numeric(bt.to_pandas()[ts_col], errors="coerce").to_numpy()
        v = v[np.isfinite(v)]
        if len(v):
            mn = v.min() if mn is None else min(mn, v.min())
            mx = v.max() if mx is None else max(mx, v.max())
    unit = "us" if mx>1e15 else ("ms" if mx>1e12 else "s")
    div = {"us":1e6,"ms":1e3,"s":1}[unit]
    print(f"ts range ({unit}): {pd.to_datetime(mn/div, unit='s')} -> {pd.to_datetime(mx/div, unit='s')}")

res = load_resolutions(assets=["BTC"])
print("\nRES btc tf:", res.timeframe.value_counts().to_dict(), "slot_start_us range:",
      pd.to_datetime(int(res.slot_start_us.min())/1e6, unit='s'), "->", pd.to_datetime(int(res.slot_start_us.max())/1e6, unit='s'))
print("res slug sample:", list(res.slug.head(3)))
