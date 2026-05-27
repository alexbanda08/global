"""Verify spread fix hypothesis on blocked V5 fires.

For each blocked sleeve_fire_eval (skip_reason starts 'spread_too_wide_'), pull canonical L25
book snapshot AT or just before fire_us for the BUY-SIDE token and compute same-token
ask0 - bid0. Compare against live cross-token spread. Filter: 0.02 BTC/ETH, 0.025 SOL.
"""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import load_orderbook_l25_streaming
import numpy as np
import pandas as pd

SAMPLE_PATH = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_spread_sample.json"
OUT_PATH = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_spread_verify_results.csv"
FILTER = {'BTC': 0.02, 'ETH': 0.02, 'SOL': 0.025}

with open(SAMPLE_PATH, 'r') as f:
    sample = json.load(f)
print(f"Loaded sample: {len(sample)} fires")

# Group by asset for batched loads
by_asset = {}
for r in sample:
    by_asset.setdefault(r['asset'], []).append(r)

results = []
for asset, rows in by_asset.items():
    asset_l = asset.lower()
    slugs = sorted({r['slug'] for r in rows})
    fire_us_list = [r['fire_us'] for r in rows]
    min_t = min(fire_us_list) - 60_000_000
    max_t = max(fire_us_list) + 5_000_000
    print(f"\n=== {asset}: {len(rows)} fires, {len(slugs)} slugs")
    print(f"   Loading L25 stream (native 10Hz)...")
    books = load_orderbook_l25_streaming(
        asset_l,
        slugs=set(slugs),
        subsample_1hz=False,
        min_ts_us=min_t,
        max_ts_us=max_t,
    )
    print(f"   Loaded {len(books)} (slug, outcome) keys")

    for r in rows:
        side = r['direction']  # 'UP' or 'DOWN'
        key = (r['slug'], side)
        rec = books.get(key)
        if rec is None:
            results.append({**r, 'note': 'no_book_for_outcome', 'bidask_spread_new': None,
                            'cross_spread_live': None, 'would_pass_new': None, 'ask0': None, 'bid0': None})
            continue
        ts_arr, ap, asz, bp, bsz = rec
        # Search rightmost ts <= fire_us
        idx = np.searchsorted(ts_arr, r['fire_us'], side='right') - 1
        if idx < 0:
            results.append({**r, 'note': 'no_snapshot_before_fire', 'bidask_spread_new': None,
                            'cross_spread_live': None, 'would_pass_new': None, 'ask0': None, 'bid0': None})
            continue
        snap_ts = int(ts_arr[idx])
        age_s = (r['fire_us'] - snap_ts) / 1e6
        if age_s > 60:  # too stale
            results.append({**r, 'note': f'stale_{age_s:.1f}s', 'bidask_spread_new': None,
                            'cross_spread_live': None, 'would_pass_new': None, 'ask0': None, 'bid0': None})
            continue
        ask0 = float(ap[idx, 0]) if not np.isnan(ap[idx, 0]) else None
        bid0 = float(bp[idx, 0]) if not np.isnan(bp[idx, 0]) else None
        if ask0 is None or bid0 is None:
            results.append({**r, 'note': 'nan_top_level', 'bidask_spread_new': None,
                            'cross_spread_live': None, 'would_pass_new': None, 'ask0': ask0, 'bid0': bid0})
            continue
        spread_new = ask0 - bid0
        f = FILTER[asset]
        pass_new = spread_new <= f
        # Parse old spread from skip_reason like "spread_too_wide_0.3185_>_0.0200"
        try:
            old_spread = float(r['skip_reason'].split('_')[3])
        except Exception:
            old_spread = None
        results.append({**r, 'ask0': ask0, 'bid0': bid0,
                        'bidask_spread_new': spread_new,
                        'cross_spread_live': old_spread,
                        'filter': f, 'would_pass_new': bool(pass_new),
                        'snap_ts_us': snap_ts, 'age_s': age_s, 'note': 'ok'})

df = pd.DataFrame(results)
df.to_csv(OUT_PATH, index=False)
print(f"\nWrote {OUT_PATH}")

# Summary
print("\n=== SUMMARY ===")
print(f"Total sampled: {len(df)}")
print(f"Notes: {df['note'].value_counts().to_dict()}")
for asset in ['BTC','ETH','SOL']:
    sub = df[df['asset']==asset]
    valid = sub[sub['note']=='ok']
    if len(valid)==0:
        print(f"  {asset}: no valid snapshots")
        continue
    pass_n = int(valid['would_pass_new'].sum())
    print(f"  {asset}: sample={len(sub)} valid_snap={len(valid)} would_pass_new={pass_n} ({100*pass_n/len(valid):.1f}%)")
    print(f"     bidask median={valid['bidask_spread_new'].median():.4f} mean={valid['bidask_spread_new'].mean():.4f} max={valid['bidask_spread_new'].max():.4f}")
    print(f"     cross   median={valid['cross_spread_live'].median():.4f} mean={valid['cross_spread_live'].mean():.4f}")
overall_valid = df[df['note']=='ok']
ov_pass = int(overall_valid['would_pass_new'].sum())
print(f"\nOVERALL: would_pass_new = {ov_pass}/{len(overall_valid)} = {100*ov_pass/max(len(overall_valid),1):.1f}%")
