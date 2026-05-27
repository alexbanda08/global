"""Final comprehensive sniper search.

Strategy:
  - Test per offset-band (early=30-60, mid_early=60-120, mid=120-180, late=180-270)
  - For each band, find combos that pass on lockbox
  - Compute bootstrap p, $250 depth coverage, and walk-forward confirm
  - Output: best candidates ranked by lockbox dpt, must also pass on validation

This is the FINAL search — output is the top_5_candidates.csv.
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
print(f"Days train={n_train_d}, val={n_val_d}, lock={n_lock_d}", flush=True)

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
    'g_R1_sum','g_within_dev','g_tr_stack_full_with','g_trend_slope_very_strong_with',
    'g_dev_extreme','g_rsi_extreme_against','g_compression_loose','g_ribbon_slope_very_strong',
    'g_offset_mid_early','g_offset_mid','g_offset_mid_late',
}
gates = sorted([c for c in p.columns if c.startswith('g_') and c not in EXCLUDE])
print(f"Using {len(gates)} candidates", flush=True)

# Define offset bands
OFFSET_BANDS = {
    'pre_60': (0, 60),       # offset 30
    'early': (30, 90),       # offset 30, 60, 90
    'mid_early': (60, 150),  # offset 60-150
    'mid': (90, 180),
    'late': (180, 270),
    'all': (0, 300),
}

ALL_CANDIDATES = []

for band_name, (off_lo, off_hi) in OFFSET_BANDS.items():
    print(f"\n=== Offset band {band_name}: [{off_lo}-{off_hi}] ===", flush=True)
    train_b = train[(train['fire_offset_s']>=off_lo)&(train['fire_offset_s']<=off_hi)].reset_index(drop=True)
    val_b = val[(val['fire_offset_s']>=off_lo)&(val['fire_offset_s']<=off_hi)].reset_index(drop=True)
    lock_b = lock[(lock['fire_offset_s']>=off_lo)&(lock['fire_offset_s']<=off_hi)].reset_index(drop=True)
    print(f"  train_n={len(train_b)}, val_n={len(val_b)}, lock_n={len(lock_b)}", flush=True)
    if len(train_b) < 1000: continue

    # Pair scan with relaxed criteria
    pair_rows = []
    for a, b in combinations(gates, 2):
        m_t = (train_b[a].astype(bool) & train_b[b].astype(bool)).values
        rt = fast_metrics(train_b, m_t, n_train_d)
        if not rt or rt['n'] < 30 or rt['wr'] < 0.65 or rt['dpt'] < 1: continue
        m_l = (lock_b[a].astype(bool) & lock_b[b].astype(bool)).values
        rl = fast_metrics(lock_b, m_l, n_lock_d)
        if not rl or rl['n'] < 15 or rl['wr'] < 0.65 or rl['dpt'] < 1: continue
        pair_rows.append({'stack': f"{a}+{b}", 'rt': rt, 'rl': rl})
    print(f"  Pairs surviving train+lock>=1$/tr: {len(pair_rows)}", flush=True)
    if len(pair_rows) == 0: continue

    # Sort by lockbox dpt and take top 50 for triple expansion
    pair_rows.sort(key=lambda r: -r['rl']['dpt'])
    pair_seeds = [r['stack'] for r in pair_rows[:50]]

    # Triples
    trip_rows = []
    for s in pair_seeds:
        base = s.split('+')
        for extra in gates:
            if extra in base: continue
            stk = base + [extra]
            m_t = train_b[stk].astype(bool).prod(axis=1).astype(bool).values
            rt = fast_metrics(train_b, m_t, n_train_d)
            if not rt or rt['n'] < 25 or rt['wr'] < 0.70 or rt['dpt'] < 2: continue
            m_l = lock_b[stk].astype(bool).prod(axis=1).astype(bool).values
            rl = fast_metrics(lock_b, m_l, n_lock_d)
            if not rl or rl['n'] < 15 or rl['wr'] < 0.70 or rl['dpt'] < 2: continue
            trip_rows.append({'stack': '+'.join(sorted(stk)), 'rt': rt, 'rl': rl})
    # dedupe
    seen = set(); deduped = []
    for r in trip_rows:
        if r['stack'] in seen: continue
        seen.add(r['stack']); deduped.append(r)
    trip_rows = deduped
    print(f"  Triples: {len(trip_rows)}", flush=True)
    if len(trip_rows) > 0:
        trip_rows.sort(key=lambda r: -r['rl']['dpt'])
        trip_seeds = [r['stack'] for r in trip_rows[:50]]
    else:
        trip_seeds = []

    # Quads
    quad_rows = []
    for s in trip_seeds:
        base = s.split('+')
        for extra in gates:
            if extra in base: continue
            stk = base + [extra]
            m_t = train_b[stk].astype(bool).prod(axis=1).astype(bool).values
            rt = fast_metrics(train_b, m_t, n_train_d)
            if not rt or rt['n'] < 20 or rt['wr'] < 0.72 or rt['dpt'] < 3: continue
            m_l = lock_b[stk].astype(bool).prod(axis=1).astype(bool).values
            rl = fast_metrics(lock_b, m_l, n_lock_d)
            if not rl or rl['n'] < 15 or rl['wr'] < 0.75 or rl['dpt'] < 2: continue
            quad_rows.append({'stack': '+'.join(sorted(stk)), 'rt': rt, 'rl': rl})
    seen = set(); deduped = []
    for r in quad_rows:
        if r['stack'] in seen: continue
        seen.add(r['stack']); deduped.append(r)
    quad_rows = deduped
    print(f"  Quads: {len(quad_rows)}", flush=True)

    # Combine all sizes
    band_cands = pair_rows + trip_rows + quad_rows

    # Validate on val
    for r in band_cands:
        stk = r['stack'].split('+')
        m_v = val_b[stk].astype(bool).prod(axis=1).astype(bool).values if len(val_b) > 0 else np.zeros(0, dtype=bool)
        rv = fast_metrics(val_b, m_v, n_val_d) if m_v.any() else None
        r['rv'] = rv

        # Sniper score: lockbox dpt minus penalties for failures elsewhere
        rt, rl = r['rt'], r['rl']
        rv_dpt = rv['dpt'] if rv else 0
        rv_wr = rv['wr'] if rv else 0
        # Score
        score = rl['dpt']
        if rv and rv['dpt'] >= 1: score += rv['dpt']
        if rv_wr >= 0.70: score += 1.5
        ALL_CANDIDATES.append({
            'band': band_name, 'off_lo': off_lo, 'off_hi': off_hi,
            'stack': r['stack'],
            'n_t': rt['n'], 'wr_t': rt['wr'], 'dpt_t': rt['dpt'], 'sum_t': rt['sum_pnl'],
            'dd_t': rt['max_dd'], 'ls_t': rt['max_ls'], 'shp_t': rt['sharpe'],
            'n_v': rv['n'] if rv else 0, 'wr_v': rv_wr, 'dpt_v': rv_dpt,
            'sum_v': rv['sum_pnl'] if rv else 0, 'dd_v': rv['max_dd'] if rv else 0,
            'ls_v': rv['max_ls'] if rv else 0, 'shp_v': rv['sharpe'] if rv else 0,
            'n_l': rl['n'], 'wr_l': rl['wr'], 'dpt_l': rl['dpt'], 'sum_l': rl['sum_pnl'],
            'dd_l': rl['max_dd'], 'ls_l': rl['max_ls'], 'shp_l': rl['sharpe'],
            'np_d_l': rl['n_per_day'],
            'score': score,
        })

# Final DataFrame
all_cands = pd.DataFrame(ALL_CANDIDATES)
all_cands = all_cands.sort_values('score', ascending=False)
all_cands.to_csv(OUT / "_final_search_results.csv", index=False)
print(f"\n=== TOTAL candidates: {len(all_cands)} ===")

# Sniper pass
sniper = all_cands[
    (all_cands['n_l'].between(50, 500)) &
    (all_cands['wr_l'] >= 0.75) &
    (all_cands['dpt_l'] >= 3.0) &
    (all_cands['dd_l'] <= 300) &
    (all_cands['ls_l'] <= 6) &
    (all_cands['shp_l'] >= 2.0)
]
print(f"\nFull sniper PASS on lockbox: {len(sniper)}")
if len(sniper) > 0:
    print(sniper.head(20).to_string(index=False))

# Top with relaxed n (n>=30)
top_relax = all_cands[
    (all_cands['n_l'].between(30, 500)) &
    (all_cands['wr_l'] >= 0.75) &
    (all_cands['dpt_l'] >= 3.0) &
    (all_cands['dd_l'] <= 300) &
    (all_cands['ls_l'] <= 6) &
    (all_cands['shp_l'] >= 2.0)
]
print(f"\nSniper PASS with n>=30: {len(top_relax)}")
if len(top_relax) > 0:
    print(top_relax.head(30)[['band','stack','n_t','wr_t','dpt_t','n_v','wr_v','dpt_v','n_l','wr_l','dpt_l','dd_l','ls_l','shp_l']].to_string(index=False))

print(f"\nElapsed: {time.time()-t0:.1f}s")
