import pandas as pd, glob, os
def ts(x): return pd.to_datetime(int(x), unit="us", utc=True)
r=pd.read_parquet(r"D:\bmoney_hf\staging\resolutions.parquet")
print(f"resolutions: {len(r):,}  window {ts(r.slot_start_us.min())} -> {ts(r.slot_start_us.max())}")
print(f"  by ticker x tf: {r.groupby(['ticker','timeframe']).size().to_dict()}")
print(f"  outcome split: {r.outcome.value_counts().to_dict()}")
print("L25 staging:")
for f in sorted(glob.glob(r"D:\bmoney_hf\staging\*_l25.parquet")):
    d=pd.read_parquet(f, columns=["timestamp_us","slug","outcome"])
    print(f"  {os.path.basename(f):<14} {len(d):>9,} rows  {ts(d.timestamp_us.min())} -> {ts(d.timestamp_us.max())}  outcomes={d.outcome.value_counts().to_dict()}  slugs={d.slug.nunique()}")
