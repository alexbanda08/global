import os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pyarrow.parquet as pq
import numpy as np
import pandas as pd

res = pq.read_table(r"data/v4/canonical/resolutions_hf.parquet").to_pandas()
res['start_s'] = (res['slot_start_us']//1_000_000).astype('int64')

# sample BTC + ETH bmoney slugs (Feb21-Mar24 window). bmoney btc/eth
bm = res[(res['source']=='bmoney1321-real') & (res['ticker'].isin(['BTC','ETH']))].copy()
print("bmoney btc/eth rows:", len(bm), "by tf:", bm.groupby(['ticker','timeframe']).size().to_dict())

rng = np.random.default_rng(42)
samples = {}
for tk in ['BTC','ETH']:
    sub = bm[bm['ticker']==tk]
    take = sub.sample(min(200,len(sub)), random_state=1)
    samples[tk] = take
    print(tk, "sampled", len(take))

# build slug -> slot_start_s map
slug_start = {}
for tk in ['BTC','ETH']:
    for _,r in samples[tk].iterrows():
        slug_start[r['slug']] = r['start_s']

want_slugs = set(slug_start.keys())
print("total sampled slugs:", len(want_slugs))

# scan each coin file collecting per-slug set of second-buckets present
def scan(coin_file, want):
    pf = pq.ParquetFile(coin_file)
    secs = {s:set() for s in want}
    for rg in range(pf.num_row_groups):
        tbl = pf.read_row_group(rg, columns=['timestamp_us','slug'])
        df = tbl.to_pandas()
        df = df[df['slug'].isin(want)]
        if len(df)==0: continue
        df['s'] = (df['timestamp_us']//1_000_000).astype('int64')
        for slug, g in df.groupby('slug'):
            secs[slug].update(g['s'].unique().tolist())
    return secs

import time
for tk,fn in [('BTC','data/v4/canonical/orderbook_l25_backfill/btc.parquet'),
              ('ETH','data/v4/canonical/orderbook_l25_backfill/eth.parquet')]:
    want = set(samples[tk]['slug'])
    t0=time.time()
    secs = scan(fn, want)
    # coverage at start_s + {5,30,60}; also book_start offset
    cov5=cov30=cov60=anybook=0; offs=[]
    for slug in want:
        st = slug_start[slug]
        present = secs[slug]
        if present:
            anybook+=1
            offs.append(min(present)-st)
        if (st+5) in present: cov5+=1
        if (st+30) in present: cov30+=1
        if (st+60) in present: cov60+=1
    n=len(want)
    offs=np.array(offs)
    print(f"\n=== {tk} n={n} (scan {time.time()-t0:.0f}s) ===")
    print(f"  any-book slugs: {anybook}/{n} ({anybook/n*100:.0f}%)")
    print(f"  book-start offset (min_book_s - slot_start_s): median={np.median(offs):.0f}s mean={offs.mean():.0f}s p10={np.percentile(offs,10):.0f} p90={np.percentile(offs,90):.0f} min={offs.min():.0f} max={offs.max():.0f}")
    print(f"  COVERAGE at slot_start+5s : {cov5}/{n} = {cov5/n*100:.1f}%")
    print(f"  COVERAGE at slot_start+30s: {cov30}/{n} = {cov30/n*100:.1f}%")
    print(f"  COVERAGE at slot_start+60s: {cov60}/{n} = {cov60/n*100:.1f}%")
    # also coverage at book-relative: min_book + 5 (i.e. re-anchored)
    cov_reanchor5=sum(1 for slug in want if secs[slug] and (min(secs[slug])+5) in secs[slug])
    print(f"  COVERAGE at book_start+5s (re-anchored): {cov_reanchor5}/{n} = {cov_reanchor5/n*100:.1f}%")
