"""Combinatorial v2: focus on entry_vwap bands where sniper $/tr is achievable.

Strategy: split panel into ev bands and search per-band.
  - band_mid: ev in [0.30, 0.70]  -- need WR >= 0.65 for dpt >= 3
  - band_fav: ev in [0.60, 0.85]  -- need WR >= 0.80 for dpt >= 3
  - band_dog: ev in [0.20, 0.40]  -- need WR >= 0.50 for dpt >= 3

Per band: greedy combinatorial sweep, validate on val + lockbox.
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
print(f"Panel: {len(p)} rows, {n_days} days", flush=True)

# 3-way split: 18 train / 6 val / lockbox (rest)
TR_END = 18
VL_END = 24
p['split'] = np.where(p['day_idx'] < TR_END, 'train',
              np.where(p['day_idx'] < VL_END, 'val', 'lockbox'))

train = p[p['split']=='train'].reset_index(drop=True)
val = p[p['split']=='val'].reset_index(drop=True)
lock = p[p['split']=='lockbox'].reset_index(drop=True)

n_train_d = train['day_idx'].nunique()
n_val_d = val['day_idx'].nunique()
n_lock_d = lock['day_idx'].nunique()
print(f"Days: train={n_train_d}, val={n_val_d}, lock={n_lock_d}")

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
    # Loss streak
    cur = mls = 0
    for v in won_arr:
        if v == 0:
            cur += 1
            if cur > mls: mls = cur
        else:
            cur = 0
    # daily sharpe
    dates = pd.to_datetime(sub['fire_us'], unit='us').dt.date
    daily = sub.groupby(dates)['pnl_legacy_usd'].sum()
    shp = (daily.mean()/daily.std()*np.sqrt(365)) if (len(daily)>=2 and daily.std()>0) else 0
    return {'n':n, 'wr':won_arr.mean(), 'dpt':pnl.mean(), 'sum_pnl':pnl.sum(),
            'max_dd':float(dd), 'max_ls':mls, 'sharpe':shp, 'n_per_day':n/max(1,n_days)}

# Candidate gates (exclude ev-direct gates from search since we're partitioning by ev band)
EXCLUDE = {
    'g_R1_sum', 'g_within_dev', 'g_tr_stack_full_with',
    'g_trend_slope_very_strong_with', 'g_dev_extreme', 'g_rsi_extreme_against',
    'g_compression_loose', 'g_ribbon_slope_very_strong',
    'g_ev_le_30','g_ev_le_40','g_ev_le_50','g_ev_le_60','g_ev_le_70',
    'g_ev_ge_30','g_ev_in_30_60','g_ev_in_20_50','g_ev_in_40_70',
    'g_underdog','g_favorite','g_strong_underdog','g_strong_favorite',
}

gates = sorted([c for c in p.columns if c.startswith('g_') and c not in EXCLUDE])
print(f"Using {len(gates)} candidate gates", flush=True)

# Define ev bands
BANDS = {
    'narrow_mid':  (0.35, 0.65),  # ev band where lift is most impactful
    'mid_wide':    (0.30, 0.70),
    'mid':         (0.40, 0.60),
    'fav':         (0.55, 0.85),
    'fav_tight':   (0.60, 0.80),
    'dog':         (0.20, 0.45),
    'dog_tight':   (0.25, 0.40),
    'all':         (0.0, 1.0),
}

ALL_RESULTS = []
for band_name, (lo, hi) in BANDS.items():
    print(f"\n=== Band {band_name}: ev in [{lo}, {hi}] ===", flush=True)
    train_b = train[(train['entry_vwap']>=lo) & (train['entry_vwap']<=hi)].reset_index(drop=True)
    val_b = val[(val['entry_vwap']>=lo) & (val['entry_vwap']<=hi)].reset_index(drop=True)
    lock_b = lock[(lock['entry_vwap']>=lo) & (lock['entry_vwap']<=hi)].reset_index(drop=True)
    print(f"  train_n={len(train_b)} (WR {train_b['won'].mean():.3f}, dpt {train_b['pnl_legacy_usd'].mean():.2f})", flush=True)
    print(f"  val_n={len(val_b)}, lock_n={len(lock_b)}", flush=True)
    if len(train_b) < 100: continue

    # Single gate scan on this band
    r1 = []
    for g in gates:
        m = train_b[g].fillna(0).astype(bool).values
        r = fast_metrics(train_b, m, n_train_d)
        if r is None or r['n'] < 20: continue
        r['stack'] = g
        r1.append(r)
    r1 = pd.DataFrame(r1).sort_values('dpt', ascending=False) if r1 else pd.DataFrame()
    if len(r1) == 0: continue

    # Pick seeds: top by dpt + top by WR
    seeds = list(set(
        r1.sort_values('dpt', ascending=False).head(15)['stack'].tolist() +
        r1.sort_values('wr', ascending=False).head(15)['stack'].tolist() +
        r1[(r1['n']>=50) & (r1['wr']>=0.65)].head(20)['stack'].tolist()
    ))
    if len(seeds) < 2: continue

    # Pair search
    r2 = []
    for a, b in combinations(seeds, 2):
        m = (train_b[a].astype(bool) & train_b[b].astype(bool)).values
        r = fast_metrics(train_b, m, n_train_d)
        if r is None or r['n'] < 20 or r['wr'] < 0.55: continue
        r['stack'] = f"{a}+{b}"; r2.append(r)
    r2 = pd.DataFrame(r2).sort_values('dpt', ascending=False) if r2 else pd.DataFrame()

    # 3-stacks (greedy from top pairs)
    r3 = []
    if len(r2) > 0:
        seeds3 = r2.head(40)['stack'].tolist()
        for s in seeds3:
            base = s.split('+')
            for extra in seeds:
                if extra in base: continue
                stk = base + [extra]
                m = train_b[stk].astype(bool).prod(axis=1).astype(bool).values
                r = fast_metrics(train_b, m, n_train_d)
                if r is None or r['n'] < 15 or r['wr'] < 0.60 or r['dpt'] < 0: continue
                r['stack'] = '+'.join(sorted(stk)); r3.append(r)
        r3 = (pd.DataFrame(r3).drop_duplicates(subset='stack').sort_values('dpt', ascending=False)
              if r3 else pd.DataFrame())

    # 4-stacks
    r4 = []
    if len(r3) > 0:
        seeds4 = r3.head(50)['stack'].tolist()
        for s in seeds4:
            base = s.split('+')
            for extra in seeds:
                if extra in base: continue
                stk = base + [extra]
                m = train_b[stk].astype(bool).prod(axis=1).astype(bool).values
                r = fast_metrics(train_b, m, n_train_d)
                if r is None or r['n'] < 10 or r['wr'] < 0.70 or r['dpt'] < 1: continue
                r['stack'] = '+'.join(sorted(stk)); r4.append(r)
        r4 = (pd.DataFrame(r4).drop_duplicates(subset='stack').sort_values('dpt', ascending=False)
              if r4 else pd.DataFrame())

    # 5-stacks
    r5 = []
    if len(r4) > 0:
        seeds5 = r4.head(50)['stack'].tolist()
        for s in seeds5:
            base = s.split('+')
            for extra in seeds:
                if extra in base: continue
                stk = base + [extra]
                m = train_b[stk].astype(bool).prod(axis=1).astype(bool).values
                r = fast_metrics(train_b, m, n_train_d)
                if r is None or r['n'] < 10 or r['wr'] < 0.75 or r['dpt'] < 2: continue
                r['stack'] = '+'.join(sorted(stk)); r5.append(r)
        r5 = (pd.DataFrame(r5).drop_duplicates(subset='stack').sort_values('dpt', ascending=False)
              if r5 else pd.DataFrame())

    # 6-stacks
    r6 = []
    if len(r5) > 0:
        seeds6 = r5.head(50)['stack'].tolist()
        for s in seeds6:
            base = s.split('+')
            for extra in seeds:
                if extra in base: continue
                stk = base + [extra]
                m = train_b[stk].astype(bool).prod(axis=1).astype(bool).values
                r = fast_metrics(train_b, m, n_train_d)
                if r is None or r['n'] < 5 or r['wr'] < 0.75 or r['dpt'] < 2: continue
                r['stack'] = '+'.join(sorted(stk)); r6.append(r)
        r6 = (pd.DataFrame(r6).drop_duplicates(subset='stack').sort_values('dpt', ascending=False)
              if r6 else pd.DataFrame())

    print(f"  R1={len(r1)}, R2={len(r2)}, R3={len(r3)}, R4={len(r4)}, R5={len(r5)}, R6={len(r6)}", flush=True)

    # Score and pick top from this band
    all_r = []
    for d, label in [(r1,'R1'),(r2,'R2'),(r3,'R3'),(r4,'R4'),(r5,'R5'),(r6,'R6')]:
        if len(d) == 0: continue
        d2 = d.copy()
        d2['size'] = label
        d2['band'] = band_name
        d2['band_lo'] = lo
        d2['band_hi'] = hi
        all_r.append(d2)
    if not all_r: continue
    band_r = pd.concat(all_r, ignore_index=True)
    # sniper score
    band_r['score'] = (
        np.clip(band_r['wr'] - 0.50, 0, 0.5) * 4 +
        np.clip(band_r['dpt'], 0, 10) * 0.8 -
        np.clip(band_r['max_dd'] - 200, 0, 1000) / 100 -
        np.maximum(band_r['max_ls'] - 5, 0) * 0.5
    )
    band_r = band_r.sort_values('score', ascending=False)

    # Pick top 25 from this band for validation
    cand = band_r.head(50)
    val_rows = []
    for _, row in cand.iterrows():
        stk = row['stack'].split('+')
        if not all(s in train_b.columns for s in stk): continue
        m_val = (val_b[stk].astype(bool).prod(axis=1).astype(bool).values if len(val_b)>0 else np.zeros(0, dtype=bool))
        m_lock = (lock_b[stk].astype(bool).prod(axis=1).astype(bool).values if len(lock_b)>0 else np.zeros(0, dtype=bool))
        rv = fast_metrics(val_b, m_val, n_val_d) if m_val.any() else None
        rl = fast_metrics(lock_b, m_lock, n_lock_d) if m_lock.any() else None
        def _safe(r, k, dv=0):
            return r[k] if r else dv
        val_rows.append({
            'band': band_name, 'band_lo': lo, 'band_hi': hi,
            'stack': row['stack'], 'size': row['size'],
            'n_train': row['n'], 'wr_train': row['wr'], 'dpt_train': row['dpt'], 'sum_train': row['sum_pnl'],
            'dd_train': row['max_dd'], 'ls_train': row['max_ls'], 'shp_train': row['sharpe'],
            'n_val': _safe(rv,'n'), 'wr_val': _safe(rv,'wr'), 'dpt_val': _safe(rv,'dpt'),
            'sum_val': _safe(rv,'sum_pnl'), 'dd_val': _safe(rv,'max_dd'), 'ls_val': _safe(rv,'max_ls'),
            'shp_val': _safe(rv,'sharpe'),
            'n_lock': _safe(rl,'n'), 'wr_lock': _safe(rl,'wr'), 'dpt_lock': _safe(rl,'dpt'),
            'sum_lock': _safe(rl,'sum_pnl'), 'dd_lock': _safe(rl,'max_dd'), 'ls_lock': _safe(rl,'max_ls'),
            'shp_lock': _safe(rl,'sharpe'), 'np_d_lock': _safe(rl,'n_per_day'),
        })
    ALL_RESULTS.extend(val_rows)

allvt = pd.DataFrame(ALL_RESULTS)
allvt.to_csv(OUT / "_combinatorial_lockbox_v2.csv", index=False)
print(f"\n=== TOTAL: {len(allvt)} validated candidates across all bands ===")

# Filter to sniper-passing on lockbox
sniper_pass = allvt[(allvt['n_lock'].between(50, 500)) &
                    (allvt['wr_lock'] >= 0.75) &
                    (allvt['dpt_lock'] >= 3.0) &
                    (allvt['dd_lock'] <= 300) &
                    (allvt['ls_lock'] <= 6) &
                    (allvt['shp_lock'] >= 2.0)]
print(f"\nLockbox-passing sniper candidates: {len(sniper_pass)}")
if len(sniper_pass) > 0:
    print(sniper_pass.sort_values('dpt_lock', ascending=False).head(20)[
        ['band','stack','n_train','wr_train','dpt_train','n_lock','wr_lock','dpt_lock','dd_lock','ls_lock','shp_lock']
    ].to_string(index=False))

# Near-misses on lockbox
near_miss = allvt[(allvt['n_lock'] >= 10) & (allvt['wr_lock'] >= 0.65) & (allvt['dpt_lock'] >= 1.0)]
print(f"\nNear-misses (n>=10, WR>=0.65, dpt>=1.0): {len(near_miss)}")
if len(near_miss) > 0:
    print(near_miss.sort_values('dpt_lock', ascending=False).head(20)[
        ['band','stack','n_train','wr_train','dpt_train','n_lock','wr_lock','dpt_lock','dd_lock','ls_lock','shp_lock']
    ].to_string(index=False))

print(f"\nElapsed: {time.time()-t0:.1f}s")
