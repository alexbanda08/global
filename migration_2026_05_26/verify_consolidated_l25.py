"""Verify consolidated L25 parquets — row counts, time spans, schema sanity, sample read."""
from pathlib import Path
import pyarrow.parquet as pq
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT = ROOT / "data" / "v4" / "canonical" / "orderbook_l25"

def fmt(ts):
    return pd.to_datetime(int(ts), unit="us", utc=True).strftime("%Y-%m-%d %H:%M:%S")

for asset in ["sol", "eth", "btc"]:
    p = OUT / f"{asset}.parquet"
    if not p.exists():
        print(f"{asset}: MISSING")
        continue
    pf = pq.ParquetFile(str(p))
    md = pf.metadata
    sz = p.stat().st_size / 1024 / 1024

    # Read just timestamp_us col to get min/max + slug count
    df = pd.read_parquet(p, columns=["timestamp_us", "slug", "outcome"])
    print(f"\n{asset.upper()}: {p.name}")
    print(f"  size: {sz:,.0f} MB  rows: {md.num_rows:,}  row_groups: {md.num_row_groups}")
    print(f"  window: {fmt(df.timestamp_us.min())}  ->  {fmt(df.timestamp_us.max())}")
    print(f"  unique (slug, outcome) keys: {df.groupby(['slug','outcome']).ngroups:,}")
    print(f"  unique slugs: {df.slug.nunique():,}")
    print(f"  outcomes: {sorted(df.outcome.unique().tolist())}")
    # Spot-check: row group sizes
    rg_sizes = [pf.metadata.row_group(i).num_rows for i in range(min(5, md.num_row_groups))]
    print(f"  first 5 row group sizes: {rg_sizes}")
    # Read the LAST row group as a sanity check (no truncation)
    last_rg = pf.read_row_group(md.num_row_groups - 1, columns=["timestamp_us"])
    print(f"  last row group: {last_rg.num_rows} rows, max ts = {fmt(last_rg.column('timestamp_us').to_pylist()[-1])}")
