import os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pyarrow.parquet as pq
import pyarrow.dataset as ds

P = r"data/v4/canonical/klines_1s.parquet"
pf = pq.ParquetFile(P)
print("schema:")
print(pf.schema_arrow)
print("num_rows:", pf.metadata.num_rows)
# peek a few rows
b = next(pf.iter_batches(batch_size=5))
import pandas as pd
print(b.to_pandas().to_dict('records'))
