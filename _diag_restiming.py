import os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pyarrow.parquet as pq
import numpy as np
import pandas as pd

P = r"data/v4/canonical/resolutions_hf.parquet"
df = pq.read_table(P).to_pandas()
print("cols:", list(df.columns))
print("rows:", len(df))
print("sources:", df['source'].value_counts().to_dict() if 'source' in df else "NO source col")
print("price_source:", df['price_source'].value_counts().to_dict() if 'price_source' in df else "NO ps col")
print("timeframe:", df['timeframe'].value_counts().to_dict())
print("ticker head:", df['ticker'].value_counts().head(10).to_dict())
print("sample rows:")
for r in df.head(3).to_dict('records'):
    print(r)

# slug suffix vs slot_start
def suffix(s):
    try: return int(s.rsplit('-',1)[1])
    except: return -1
df['suffix'] = df['slug'].map(suffix)
df['suffix_us'] = df['suffix'].astype('int64')*1_000_000
df['off_start'] = (df['slot_start_us'] - df['suffix_us'])/1e6  # slot_start - suffix
print("\n=== slot_start_us - suffix*1e6 (seconds) ===")
print("overall describe:")
print(df['off_start'].describe())
print("value_counts:", df['off_start'].round().value_counts().head(10).to_dict())

# window length
df['winlen'] = (df['slot_end_us']-df['slot_start_us'])/1e6
print("\nwindow len by tf:")
print(df.groupby('timeframe')['winlen'].describe())
