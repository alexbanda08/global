import sys, pyarrow.parquet as pq, pyarrow.dataset as ds, pyarrow.compute as pc
sys.path.insert(0, r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical")

# ---- BBO schema + one-slug slice stats (use sol, smaller) ----
bbo = r"D:/global_data/canonical_bbo/sol.parquet"
sch = pq.read_schema(bbo)
print("BBO SCHEMA:\n", sch, "\n")

import load
# pick one 15m slug from resolutions_hf
res = load.load_resolutions_hf()
print("res cols:", list(res.columns))
solr = res[(res.get('asset','').astype(str).str.lower()=='sol') if 'asset' in res.columns else slice(None)]
print("res sample slugs:")
# find any sol 15m slug present in BBO
import pyarrow as pa
d = ds.dataset(bbo)
# sample distinct slugs cheaply: read 200k rows of slug,timeframe
tbl = d.head(200000, columns=['slug','timeframe'])
import pandas as pd
df0 = tbl.to_pandas()
print("timeframes seen:", df0['timeframe'].value_counts().to_dict())
slug = df0[df0.timeframe=='15m']['slug'].iloc[0] if (df0.timeframe=='15m').any() else df0['slug'].iloc[0]
print("PICK SLUG:", slug)

# full slice for that slug
flt = pc.field('slug')==slug
sub = d.to_table(filter=flt).to_pandas()
print("rows for slug:", len(sub))
print("outcomes(tokens):", sub['outcome'].value_counts().to_dict())
for c in ['best_bid_size','best_ask_size']:
    z = (sub[c]==0).mean()
    print(f"  {c}: zero-rate={z:.3f}, nonzero-min={sub[sub[c]>0][c].min() if (sub[c]>0).any() else 'NA'}")
print("ts span (s):", (sub.timestamp_us.max()-sub.timestamp_us.min())/1e6)
print("median dt between events (ms):", sub.sort_values('timestamp_us').timestamp_us.diff().median()/1000)
print(sub.head(4).to_string())

# ---- trades schema ----
tr = r"D:/global_data/canonical_bbo_trades/sol.parquet"
print("\nTRADES SCHEMA:\n", pq.read_schema(tr))
tdf = load.load_trades_hf('sol', bbo=True)
print("trade cols:", list(tdf.columns))
print(tdf.head(3).to_string())
