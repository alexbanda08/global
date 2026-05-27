"""Print parquet schemas for each L25 source to verify compatibility."""
from pathlib import Path
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
DATA = ROOT / "data" / "v4"

SOURCES = [
    ("refresh_2026_05_16/cache_pre",  "_orderbook_L25_pre_apr22.parquet"),
    ("refresh_2026_05_06/cache",      "_orderbook_L25.parquet"),
    ("refresh_2026_05_16/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_19/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_21/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_25/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_26/cache",      "_orderbook_L25_topoff.parquet"),
]

for subdir, suffix in SOURCES:
    p = DATA / subdir.split("/")[0] / subdir.split("/")[1] / f"btc{suffix}"
    if not p.exists():
        continue
    schema = pq.ParquetFile(str(p)).schema_arrow
    names = [f.name for f in schema]
    print(f"\n{subdir} ({len(names)} cols):")
    print(f"  first 12: {names[:12]}")
    print(f"  last 4: {names[-4:]}")
    print(f"  has local_timestamp_us: {'local_timestamp_us' in names}")
    print(f"  has exchange: {'exchange' in names}")
    print(f"  has asset_id: {'asset_id' in names}")
    print(f"  ask_price_0 type: {next((f.type for f in schema if f.name=='ask_price_0'), 'MISSING')}")
    print(f"  outcome type: {next((f.type for f in schema if f.name=='outcome'), 'MISSING')}")
