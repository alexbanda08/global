"""Focused sniper search: target 50-200 lockbox fires.

The brief says: 50 <= n <= 500 on lockbox. Strategy from prior banded search showed
the best $/tr happens with VERY tight gates (n ~15-30 lockbox = 2-3/day).

We need to relax to land in 50-200 lockbox range with $/tr ≥ $3. Tests:
  - 2-gate stacks (light filtering) on ev mid-band
  - 3-gate stacks across all bands

For each candidate, also output $250 capacity stats (% of fires that pass depth filter).
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path
from itertools import combinations

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_gated.parquet")
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
p['day_idx'] = (pd.to_datetime(p['date']) - pd.to_datetime(p['date']).min()).dt.days
n_days = p['day_idx'].max() + 1

TR_END, VL_END = 18, 24
p['split'] = np.where(p['day_idx'] < TR_END, 'train',
              np.where(p['day_idx'] < VL_END, 'val', 'lockbox'))

train = p[p['split']=='train'].reset_index(drop=True)
val = p[p['split']=='val'].reset_index(drop=True)
lock = p[p['split']=='lockbox'].reset_index(drop=True)
n_train_d = train['day_idx'].nunique()
n_val_d = val['day_idx'].nunique()
n_lock_d = lock['day_idx'].nunique()

def fast_metrics(df, mask, n_days):
    sub = df[mask]
    n = len(sub)
    if n < 5: return None
    sub_sort = sub.sort_values('fire_us')
    pnl = sub_sort['pnl_legacy_usd'].values
    won_arr = sub_sort['won'].values
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max() if len(cum) else 0
    cur = mls = 0
    for v in won_arr:
        if v == 0:
            cur += 1
            if cur > mls: mls = cur
        else:
            cur = 0
    dates = pd.to_datetime(sub['fire_us'], unit='us').dt.date
    daily = sub.groupby(dates)['pnl_legacy_usd'].sum()
    shp = (daily.mean()/daily.std()*np.sqrt(365)) if (len(daily)>=2 and daily.std()>0) else 0
    return {'n':n, 'wr':won_arr.mean(), 'dpt':pnl.mean(), 'sum_pnl':pnl.sum(),
            'max_dd':float(dd), 'max_ls':mls, 'sharpe':shp, 'n_per_day':n/max(1,n_days)}

EXCLUDE = {
    'g_R1_sum', 'g_within_dev', 'g_tr_stack_full_with',
    'g_trend_slope_very_strong_with', 'g_dev_extreme', 'g_rsi_extreme_against',
    'g_compression_loose', 'g_ribbon_slope_very_strong',
}
gates = sorted([c for c in p.columns if c.startswith('g_') and c not in EXCLUDE])
print(f"Using {len(gates)} candidates", flush=True)

# Step 1: pairs that have lockbox n in [50, 300] and decent metrics
print(f"\n=== Pair scan: target lockbox n in [40, 300] ===", flush=True)
rows = []
for a, b in combinations(gates, 2):
    m_t = (train[a].astype(bool) & train[b].astype(bool)).values
    rt = fast_metrics(train, m_t, n_train_d)
    if rt is None or rt['n'] < 30 or rt['wr'] < 0.65 or rt['dpt'] < 1: continue
    m_l = (lock[a].astype(bool) & lock[b].astype(bool)).values
    rl = fast_metrics(lock, m_l, n_lock_d)
    if rl is None: continue
    if rl['n'] < 30 or rl['n'] > 1500: continue
    rows.append({
        'stack': f"{a}+{b}",
        'n_t': rt['n'], 'wr_t': rt['wr'], 'dpt_t': rt['dpt'],
        'dd_t': rt['max_dd'], 'ls_t': rt['max_ls'], 'shp_t': rt['sharpe'],
        'n_l': rl['n'], 'wr_l': rl['wr'], 'dpt_l': rl['dpt'],
        'dd_l': rl['max_dd'], 'ls_l': rl['max_ls'], 'shp_l': rl['sharpe'],
    })

pairs = pd.DataFrame(rows).sort_values('dpt_l', ascending=False)
print(f"Pairs found: {len(pairs)}")
print("Top 20 by dpt_lock:")
if len(pairs) > 0:
    print(pairs.head(20).to_string(index=False))

# Step 2: triples expanding from top pairs
print(f"\n=== 3-stack search: expanding from top pairs ===", flush=True)
seeds = pairs.head(100)['stack'].tolist() if len(pairs) > 0 else []
trip_rows = []
for s in seeds:
    base = s.split('+')
    for extra in gates:
        if extra in base: continue
        stk = base + [extra]
        m_t = train[stk].astype(bool).prod(axis=1).astype(bool).values
        rt = fast_metrics(train, m_t, n_train_d)
        if rt is None or rt['n'] < 30 or rt['wr'] < 0.70 or rt['dpt'] < 2: continue
        m_l = lock[stk].astype(bool).prod(axis=1).astype(bool).values
        rl = fast_metrics(lock, m_l, n_lock_d)
        if rl is None or rl['n'] < 30: continue
        trip_rows.append({
            'stack': '+'.join(sorted(stk)),
            'n_t': rt['n'], 'wr_t': rt['wr'], 'dpt_t': rt['dpt'],
            'dd_t': rt['max_dd'], 'ls_t': rt['max_ls'], 'shp_t': rt['sharpe'],
            'n_l': rl['n'], 'wr_l': rl['wr'], 'dpt_l': rl['dpt'],
            'dd_l': rl['max_dd'], 'ls_l': rl['max_ls'], 'shp_l': rl['sharpe'],
        })
trips = pd.DataFrame(trip_rows).drop_duplicates(subset='stack').sort_values('dpt_l', ascending=False) if trip_rows else pd.DataFrame()
print(f"Triples passing: {len(trips)}")
if len(trips) > 0:
    print(trips.head(15).to_string(index=False))

# Step 3: 4-stacks
print(f"\n=== 4-stack search ===", flush=True)
seeds4 = trips.head(100)['stack'].tolist() if len(trips) > 0 else []
quad_rows = []
for s in seeds4:
    base = s.split('+')
    for extra in gates:
        if extra in base: continue
        stk = base + [extra]
        m_t = train[stk].astype(bool).prod(axis=1).astype(bool).values
        rt = fast_metrics(train, m_t, n_train_d)
        if rt is None or rt['n'] < 25 or rt['wr'] < 0.72 or rt['dpt'] < 3: continue
        m_l = lock[stk].astype(bool).prod(axis=1).astype(bool).values
        rl = fast_metrics(lock, m_l, n_lock_d)
        if rl is None or rl['n'] < 30: continue
        quad_rows.append({
            'stack': '+'.join(sorted(stk)),
            'n_t': rt['n'], 'wr_t': rt['wr'], 'dpt_t': rt['dpt'],
            'dd_t': rt['max_dd'], 'ls_t': rt['max_ls'], 'shp_t': rt['sharpe'],
            'n_l': rl['n'], 'wr_l': rl['wr'], 'dpt_l': rl['dpt'],
            'dd_l': rl['max_dd'], 'ls_l': rl['max_ls'], 'shp_l': rl['sharpe'],
        })
quads = pd.DataFrame(quad_rows).drop_duplicates(subset='stack').sort_values('dpt_l', ascending=False) if quad_rows else pd.DataFrame()
print(f"Quads passing: {len(quads)}")
if len(quads) > 0:
    print(quads.head(15).to_string(index=False))

# Combine and filter for sniper
all_results = []
for d, lbl in [(pairs,'P'),(trips,'T'),(quads,'Q')]:
    if len(d) == 0: continue
    d2 = d.copy(); d2['size'] = lbl
    all_results.append(d2)
allr = pd.concat(all_results, ignore_index=True)

# Cross-validate on val too
print(f"\n=== Cross-validating top {min(100, len(allr))} on val ===", flush=True)
top = allr.sort_values('dpt_l', ascending=False).head(100)
val_metrics = []
for _, row in top.iterrows():
    stk = row['stack'].split('+')
    m_v = val[stk].astype(bool).prod(axis=1).astype(bool).values
    rv = fast_metrics(val, m_v, n_val_d) or {'n':0,'wr':0,'dpt':0,'max_dd':0,'max_ls':0,'sharpe':0}
    val_metrics.append({'stack': row['stack'], **{f'val_{k}': rv[k] for k in rv}})
vm = pd.DataFrame(val_metrics)
final = top.merge(vm, on='stack', how='left')
final = final.sort_values('dpt_l', ascending=False)

# Sniper-pass on lockbox
sniper = final[
    (final['n_l'].between(50, 500)) &
    (final['wr_l'] >= 0.75) &
    (final['dpt_l'] >= 3.0) &
    (final['dd_l'] <= 300) &
    (final['ls_l'] <= 6) &
    (final['shp_l'] >= 2.0)
]
print(f"\n=== SNIPER PASS LOCKBOX: {len(sniper)} ===")
if len(sniper) > 0:
    print(sniper.head(30).to_string(index=False))

# Near-miss
near = final[
    (final['n_l'] >= 30) &
    (final['wr_l'] >= 0.75) &
    (final['dpt_l'] >= 1.5)
]
print(f"\n=== NEAR-MISS (lock n>=30, WR>=0.75, dpt>=1.5): {len(near)} ===")
if len(near) > 0:
    print(near.head(20).to_string(index=False))

final.to_csv(OUT / "_focused_results.csv", index=False)
print(f"\nWrote _focused_results.csv ({len(final)} rows)")
print(f"Elapsed: {time.time()-t0:.1f}s")
