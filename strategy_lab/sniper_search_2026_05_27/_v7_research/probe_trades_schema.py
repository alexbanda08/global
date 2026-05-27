"""Probe trades_polymarket via pyarrow streaming."""
import pyarrow.parquet as pq
import pyarrow.dataset as ds

p = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trades_polymarket/btc.parquet"
md = pq.read_metadata(p)
print(f"=== trades_polymarket/btc.parquet ===")
print(f"  rows: {md.num_rows:,}")
print(f"  row groups: {md.num_row_groups}")
schema = pq.read_schema(p)
print(f"  schema: {schema}")
print()

# small sample
dset = ds.dataset(p)
sample = dset.head(5)
print(sample.to_pandas())
