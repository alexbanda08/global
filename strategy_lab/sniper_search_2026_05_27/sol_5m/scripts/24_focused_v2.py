"""More focused sniper search: incorporate full-window validation + offset/HoD splits.

Goal: find stacks where ALL 3 windows (train, val, lockbox) pass sniper or near-sniper criteria.
Per candidate, also produce a per-offset breakdown.

For SOL specifically, aim to find 2-3 high-conviction stacks even with smaller n_lock.
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

TR_END, VL_END = 18, 24
p['split'] = np.where(p['day_idx'] < TR_END, 'train',
              np.where(p['day_idx'] < VL_END, 'val', 'lockbox'))
train = p[p['split']=='train'].reset_index(drop=True)
val = p[p['split']=='val'].reset_index(drop=True)
lock = p[p['split']=='lockbox'].reset_index(drop=True)
n_train_d = train['day_idx'].nunique()
n_val_d = val['day_idx'].nunique()
n_lock_d = lock['day_idx'].nunique()
print(f"Days train={n_train_d}, val={n_val_d}, lock={n_lock_d}")

def fast_metrics(df, mask, n_days):
    sub = df[mask]
    n = len(sub)
    if n < 3: return None
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
        else: cur = 0
    dates = pd.to_datetime(sub['fire_us'], unit='us').dt.date
    daily = sub.groupby(dates)['pnl_legacy_usd'].sum()
    shp = (daily.mean()/daily.std()*np.sqrt(365)) if (len(daily)>=2 and daily.std()>0) else 0
    return {'n':n, 'wr':won_arr.mean(), 'dpt':pnl.mean(), 'sum_pnl':pnl.sum(),
            'max_dd':float(dd), 'max_ls':mls, 'sharpe':shp, 'n_per_day':n/max(1,n_days)}

EXCLUDE = {
    'g_R1_sum', 'g_within_dev', 'g_tr_stack_full_with',
    'g_trend_slope_very_strong_with', 'g_dev_extreme', 'g_rsi_extreme_against',
    'g_compression_loose', 'g_ribbon_slope_very_strong',
    'g_offset_mid_early','g_offset_mid','g_offset_mid_late',  # collinear w/ early/late
}
gates = sorted([c for c in p.columns if c.startswith('g_') and c not in EXCLUDE])

# 1) Single-gate scan for ALL three splits — find atoms that lift WR consistently
print(f"\n=== Single gate scan: must improve dpt on ALL 3 splits ===", flush=True)
solid_atoms = []
for g in gates:
    rt = fast_metrics(train, train[g].astype(bool).values, n_train_d)
    rv = fast_metrics(val, val[g].astype(bool).values, n_val_d)
    rl = fast_metrics(lock, lock[g].astype(bool).values, n_lock_d)
    if not all([rt, rv, rl]): continue
    if rt['wr'] < 0.50 or rv['wr'] < 0.50 or rl['wr'] < 0.50: continue
    if rt['n'] < 30 or rv['n'] < 10 or rl['n'] < 20: continue
    # Relaxed: must have positive dpt on at least 2 of 3 splits
    pos_count = (rt['dpt']>=0) + (rv['dpt']>=0) + (rl['dpt']>=0)
    if pos_count < 2: continue
    solid_atoms.append({
        'gate': g,
        'n_t': rt['n'], 'wr_t': rt['wr'], 'dpt_t': rt['dpt'],
        'n_v': rv['n'], 'wr_v': rv['wr'], 'dpt_v': rv['dpt'],
        'n_l': rl['n'], 'wr_l': rl['wr'], 'dpt_l': rl['dpt'],
    })
sa = pd.DataFrame(solid_atoms).sort_values('dpt_l', ascending=False) if solid_atoms else pd.DataFrame()
print(f"Solid atoms passing all 3 (WR>=0.55, dpt+): {len(sa)}")
if len(sa) > 0:
    print(sa.head(30).to_string(index=False))

# 2) Build candidates from solid atoms only
seeds = sa['gate'].tolist()
print(f"\nUsing {len(seeds)} solid atoms as seed pool", flush=True)

# Pair search across ALL solid atoms
print(f"\n=== Pairs ===", flush=True)
pair_rows = []
for a, b in combinations(seeds, 2):
    m_t = (train[a].astype(bool) & train[b].astype(bool)).values
    rt = fast_metrics(train, m_t, n_train_d)
    if not rt or rt['n'] < 30 or rt['wr'] < 0.65 or rt['dpt'] < 1: continue
    m_v = (val[a].astype(bool) & val[b].astype(bool)).values
    rv = fast_metrics(val, m_v, n_val_d)
    if not rv or rv['wr'] < 0.55: continue
    m_l = (lock[a].astype(bool) & lock[b].astype(bool)).values
    rl = fast_metrics(lock, m_l, n_lock_d)
    if not rl or rl['n'] < 20 or rl['wr'] < 0.65 or rl['dpt'] < 1: continue
    pair_rows.append({
        'stack': f"{a}+{b}",
        **{f'{k}_t': v for k, v in rt.items()},
        **{f'{k}_v': v for k, v in rv.items()},
        **{f'{k}_l': v for k, v in rl.items()},
    })
pairs = pd.DataFrame(pair_rows).sort_values('dpt_l', ascending=False) if pair_rows else pd.DataFrame()
print(f"Solid pairs: {len(pairs)}")
if len(pairs) > 0:
    print(pairs.head(20)[['stack','n_t','wr_t','dpt_t','n_v','wr_v','dpt_v','n_l','wr_l','dpt_l','max_dd_l','max_ls_l','sharpe_l']].to_string(index=False))

# Triples from top pairs
print(f"\n=== Triples ===", flush=True)
seed_pairs = pairs.head(60)['stack'].tolist() if len(pairs) > 0 else []
trip_rows = []
for s in seed_pairs:
    base = s.split('+')
    for extra in seeds:
        if extra in base: continue
        stk = base + [extra]
        m_t = train[stk].astype(bool).prod(axis=1).astype(bool).values
        rt = fast_metrics(train, m_t, n_train_d)
        if not rt or rt['n'] < 25 or rt['wr'] < 0.70 or rt['dpt'] < 2: continue
        m_v = val[stk].astype(bool).prod(axis=1).astype(bool).values
        rv = fast_metrics(val, m_v, n_val_d)
        if not rv or rv['wr'] < 0.60: continue
        m_l = lock[stk].astype(bool).prod(axis=1).astype(bool).values
        rl = fast_metrics(lock, m_l, n_lock_d)
        if not rl or rl['n'] < 15 or rl['wr'] < 0.70 or rl['dpt'] < 2: continue
        trip_rows.append({
            'stack': '+'.join(sorted(stk)),
            **{f'{k}_t': v for k, v in rt.items()},
            **{f'{k}_v': v for k, v in rv.items()},
            **{f'{k}_l': v for k, v in rl.items()},
        })
trips = pd.DataFrame(trip_rows).drop_duplicates(subset='stack').sort_values('dpt_l', ascending=False) if trip_rows else pd.DataFrame()
print(f"Solid triples: {len(trips)}")
if len(trips) > 0:
    print(trips.head(20)[['stack','n_t','wr_t','dpt_t','n_v','wr_v','dpt_v','n_l','wr_l','dpt_l','max_dd_l','max_ls_l','sharpe_l']].to_string(index=False))

# 4-stacks
print(f"\n=== 4-stacks ===", flush=True)
seed4 = trips.head(60)['stack'].tolist() if len(trips) > 0 else []
quad_rows = []
for s in seed4:
    base = s.split('+')
    for extra in seeds:
        if extra in base: continue
        stk = base + [extra]
        m_t = train[stk].astype(bool).prod(axis=1).astype(bool).values
        rt = fast_metrics(train, m_t, n_train_d)
        if not rt or rt['n'] < 20 or rt['wr'] < 0.72 or rt['dpt'] < 3: continue
        m_v = val[stk].astype(bool).prod(axis=1).astype(bool).values
        rv = fast_metrics(val, m_v, n_val_d)
        if not rv or rv['wr'] < 0.65: continue
        m_l = lock[stk].astype(bool).prod(axis=1).astype(bool).values
        rl = fast_metrics(lock, m_l, n_lock_d)
        if not rl or rl['n'] < 15 or rl['wr'] < 0.75 or rl['dpt'] < 3: continue
        quad_rows.append({
            'stack': '+'.join(sorted(stk)),
            **{f'{k}_t': v for k, v in rt.items()},
            **{f'{k}_v': v for k, v in rv.items()},
            **{f'{k}_l': v for k, v in rl.items()},
        })
quads = pd.DataFrame(quad_rows).drop_duplicates(subset='stack').sort_values('dpt_l', ascending=False) if quad_rows else pd.DataFrame()
print(f"Solid quads: {len(quads)}")
if len(quads) > 0:
    print(quads.head(20)[['stack','n_t','wr_t','dpt_t','n_v','wr_v','dpt_v','n_l','wr_l','dpt_l','max_dd_l','max_ls_l','sharpe_l']].to_string(index=False))

# Combine
all_results = []
for d, lbl in [(pairs,'P'),(trips,'T'),(quads,'Q')]:
    if len(d) == 0: continue
    d2 = d.copy(); d2['size'] = lbl
    all_results.append(d2)
final = pd.concat(all_results, ignore_index=True) if all_results else pd.DataFrame()
final.to_csv(OUT / "_focused_v2_results.csv", index=False)
print(f"\nWrote {len(final)} candidates to _focused_v2_results.csv")
print(f"Elapsed: {time.time()-t0:.1f}s")
