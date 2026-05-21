"""Quick check: does our LOCAL delta parquet (post-May-6) have the same row counts
as VPS3 storedata for recent slugs?

VPS3 reference (from psql):
  btc-updown-5m-1778909700 Up:   6925, Down: 6924, span 9751s
  btc-updown-5m-1778915700 Up:   6499, Down: 6499, span 10893s
  btc-updown-5m-1778916000 Up:   5863, Down: 5861, span 10706s
"""
import pyarrow.parquet as pq
import pyarrow.compute as pc
import pyarrow as pa
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
DELTA = ROOT / "data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet"

SLUGS = ["btc-updown-5m-1778909700",
         "btc-updown-5m-1778915700",
         "btc-updown-5m-1778916000"]

VPS3 = {
    "btc-updown-5m-1778909700": {"Up": 6925, "Down": 6924},
    "btc-updown-5m-1778915700": {"Up": 6499, "Down": 6499},
    "btc-updown-5m-1778916000": {"Up": 5863, "Down": 5861},
}

pf = pq.ParquetFile(str(DELTA))
print(f"Delta file: {pf.metadata.num_rows:,} rows, {pf.metadata.num_row_groups} row groups")

# Read just slug/outcome/timestamp_us across all row groups, filter to target slugs
slugs_arr = pa.array(SLUGS)
counts = {}
ts_ranges = {}
for rg_idx in range(pf.metadata.num_row_groups):
    rg = pf.read_row_group(rg_idx, columns=["slug", "outcome", "timestamp_us"])
    mask = pc.is_in(rg.column("slug"), value_set=slugs_arr)
    if pc.sum(mask).as_py() == 0:
        continue
    rg = rg.filter(mask)
    df = rg.to_pandas()
    for (sl, oc), grp in df.groupby(["slug", "outcome"]):
        key = (sl, oc)
        counts[key] = counts.get(key, 0) + len(grp)
        t0, t1 = int(grp["timestamp_us"].min()), int(grp["timestamp_us"].max())
        if key in ts_ranges:
            t0_old, t1_old = ts_ranges[key]
            ts_ranges[key] = (min(t0_old, t0), max(t1_old, t1))
        else:
            ts_ranges[key] = (t0, t1)

print("\n=== LOCAL vs VPS3 ===")
print(f"{'slug':<28} {'outcome':<6} {'local_n':>8} {'vps3_n':>8} {'diff':>6} {'local_span_s':>14}")
for sl in SLUGS:
    for oc in ("Up", "Down"):
        key = (sl, oc)
        local_n = counts.get(key, 0)
        vps3_n = VPS3[sl][oc]
        diff = local_n - vps3_n
        if key in ts_ranges:
            t0, t1 = ts_ranges[key]
            span = (t1 - t0) / 1e6
        else:
            span = 0
        marker = "OK" if abs(diff) <= 5 else "MISMATCH"
        print(f"{sl:<28} {oc:<6} {local_n:>8,} {vps3_n:>8,} {diff:>+6} {span:>14.1f}  {marker}")
