"""Compute g_book_depth_supports_250 for ALL SOL 5m fires.

For each fire, walk the ask side at fire_us and check:
  - $250 fully fillable (not underfilled)
  - slippage from $25 to $250 ≤ 300 bps (tolerant — SOL inherently sloppy)

Saves: _depth_capacity_250.parquet (slug, fire_us, direction, shares_250, slip_bps_250,
                                      underfilled_250, vwap_25, vwap_250)
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path
sys.path.insert(0, 'data/v4/canonical')
sys.path.insert(0, 'strategy_lab')
from load import load_orderbook_l25_streaming
from book_walk import book_walk_fill

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m.parquet")
print(f"Panel: {len(p)} rows; {p['slug'].nunique()} unique slugs", flush=True)

# Process slugs in batches of ~500 to avoid loading whole 575MB SOL file at once each iteration
slugs_all = p['slug'].unique()
BATCH = 500
results_list = []

for start in range(0, len(slugs_all), BATCH):
    batch_slugs = slugs_all[start:start+BATCH]
    sub = p[p['slug'].isin(batch_slugs)][['slug','fire_us','direction']].copy()
    if len(sub) == 0: continue
    t_b = time.time()
    books = load_orderbook_l25_streaming(asset='sol', slugs=set(batch_slugs))
    t_load = time.time() - t_b

    rows = []
    for _, r in sub.iterrows():
        side = 'Up' if r['direction']=='UP' else 'Down'
        key = (r['slug'], side)
        if key not in books:
            rows.append((np.nan, np.nan, np.nan, np.nan, np.nan))
            continue
        ts, ap, asz, bp, bsz = books[key]
        idx = np.searchsorted(ts, r['fire_us'], side='right') - 1
        if idx < 0:
            rows.append((np.nan, np.nan, np.nan, np.nan, np.nan))
            continue
        asks = ap[idx]; sizes = asz[idx]
        vwap25, sh25, _, _, u25 = book_walk_fill(asks, sizes, 25)
        vwap250, sh250, _, _, u250 = book_walk_fill(asks, sizes, 250)
        slip = (vwap250 - vwap25) * 10000 if vwap25 > 0 else np.nan
        rows.append((vwap25, vwap250, sh250, slip, int(u250)))

    arr = np.array(rows, dtype=object)
    sub['vwap_25'] = arr[:, 0].astype(float)
    sub['vwap_250'] = arr[:, 1].astype(float)
    sub['shares_250'] = arr[:, 2].astype(float)
    sub['slip_bps_250'] = arr[:, 3].astype(float)
    sub['underfilled_250'] = arr[:, 4].astype(float)
    results_list.append(sub)
    pct = (start + BATCH) / len(slugs_all) * 100
    print(f"  batch {start//BATCH+1}/{(len(slugs_all)+BATCH-1)//BATCH}: {len(sub)} rows; load {t_load:.1f}s; cum {(time.time()-t0)/60:.1f}min; {pct:.0f}%", flush=True)

depth = pd.concat(results_list, ignore_index=True)
print(f"\nTotal depth rows: {len(depth)}", flush=True)
print(f"Underfill rate @ $250: {depth['underfilled_250'].mean()*100:.1f}%")
print(f"Mean slip: {depth['slip_bps_250'].mean():.0f} bps")
print(f"% slip <= 200 bps: {(depth['slip_bps_250']<=200).mean()*100:.1f}%")
print(f"% slip <= 100 bps: {(depth['slip_bps_250']<=100).mean()*100:.1f}%")
print(f"% slip <= 300 bps AND fully filled: {((depth['slip_bps_250']<=300) & (depth['underfilled_250']==0)).mean()*100:.1f}%")

depth.to_parquet(OUT / "_depth_capacity_250.parquet", index=False, compression='zstd')
print(f"\nWrote _depth_capacity_250.parquet ({os.path.getsize(OUT/'_depth_capacity_250.parquet')/1024/1024:.1f} MB)")
print(f"Elapsed: {(time.time()-t0)/60:.1f}min")
