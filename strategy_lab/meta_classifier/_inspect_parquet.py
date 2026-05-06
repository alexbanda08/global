"""Inspect cache parquet schema + sample rows for one known slug."""
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CACHE = ROOT / "data/v4/refresh_2026_05_06/cache"

pf = pq.ParquetFile(CACHE / "btc_orderbook_L25.parquet")
print("schema names (all 109):")
for i, n in enumerate(pf.schema_arrow.names):
    print(f"  {i:>3}  {n}")
print(f"\ntotal rows: {pf.metadata.num_rows:,}")
print(f"row groups: {pf.metadata.num_row_groups}")

# Read first row group, filter to one slug, look at outcomes
print("\n=== Sample for one BTC slug ===")
target_slug = "btc-updown-5m-1778073000"
chunks = []
for batch in pf.iter_batches(batch_size=500_000, columns=["timestamp_us","slug","outcome","asset_id","bid_price_0","ask_price_0","bid_size_0","ask_size_0","exchange"]):
    df = batch.to_pandas()
    f = df[df.slug == target_slug]
    if len(f):
        chunks.append(f)
    if sum(len(c) for c in chunks) > 5000:
        break
if chunks:
    s = pd.concat(chunks).reset_index(drop=True)
    print(f"rows for {target_slug}: {len(s)}")
    print("distinct outcome values:", s.outcome.value_counts().to_dict())
    print("\nfirst 3 rows per outcome:")
    for oc in s.outcome.unique():
        print(f"\n--- outcome={oc} ---")
        sub = s[s.outcome == oc].head(3)
        print(sub[["timestamp_us","outcome","asset_id","bid_price_0","ask_price_0","bid_size_0","ask_size_0"]].to_string(index=False))
    print("\nlast 3 rows per outcome (near settlement):")
    for oc in s.outcome.unique():
        print(f"\n--- outcome={oc} ---")
        sub = s[s.outcome == oc].tail(3)
        print(sub[["timestamp_us","outcome","asset_id","bid_price_0","ask_price_0"]].to_string(index=False))
else:
    print(f"no rows for {target_slug}")
