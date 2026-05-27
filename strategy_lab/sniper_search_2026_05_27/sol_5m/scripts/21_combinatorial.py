"""Greedy combinatorial gate search under SNIPER constraints.

Constraints: 50 <= n <= 500 on lockbox, WR >= 0.75, $/tr >= 3, max DD <= $300,
max loss streak <= 6, sharpe >= 2.0.

3-way split:
  train: first 18d
  val: next 6d
  lockbox: last 4d

Strategy:
  - Round 1: take top-30 single gates by $/tr lift
  - Round 2: pairs from those 30 (435 combos)
  - Round 3: greedy expand winning pairs by adding one more atom; keep top-K
  - Round 4: same expand to 4-stacks; pick top-K

Score function on TRAIN:
  score = (wr - 0.75)*0 + min(dpt - 3, 5) / 5 - max(dd - 300, 0)/300 - max(ls - 6, 0)
  (must have all constraints passed first)

Output: _combinatorial_results.csv, _combinatorial_lockbox.csv
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
print(f"Panel: {len(p)} rows, date range {p['date'].min()} to {p['date'].max()}, {p['day_idx'].max()+1} days", flush=True)

# 3-way split: 18 train / 6 val / 4 lockbox (need 28d effective)
# Total = 33 days; if all panels: take 28 days (apr 28 - may 25)
# But for max coverage, use what we have. Split chronologically.
n_days = p['day_idx'].max() + 1
# Use intersection 28d if regime present, else full
# We'll do: train = first 18d, val = next 6d, lockbox = last n_days-24 days
split_train_end = 18
split_val_end = 24

p['split'] = np.where(p['day_idx'] < split_train_end, 'train',
              np.where(p['day_idx'] < split_val_end, 'val', 'lockbox'))
print(f"Split sizes:")
print(p.groupby('split').size())
print(f"Split daily WR:")
print(p.groupby('split')['won'].mean())

train = p[p['split'] == 'train'].reset_index(drop=True)
val = p[p['split'] == 'val'].reset_index(drop=True)
lock = p[p['split'] == 'lockbox'].reset_index(drop=True)

# Define gate set for search (exclude redundant ones)
EXCLUDE = {
    'g_R1_sum', 'g_within_dev', 'g_tr_stack_full_with',  # duplicate g_tr_stack_with
    'g_trend_slope_very_strong_with',  # same as strong
    'g_dev_extreme',  # 0 firings
    'g_rsi_extreme_against',  # negative gate
    'g_compression_loose',  # tiny
    'g_ribbon_slope_very_strong',  # tiny (<1%)
}
gates = sorted([c for c in p.columns if c.startswith('g_') and c not in EXCLUDE])
print(f"\nUsing {len(gates)} candidate gates", flush=True)

# --- Helper: compute metrics for a gate combo ---
def metrics(df, gate_cols, n_days, label='train'):
    """Returns (n, wr, dpt, sum_pnl, max_dd, max_loss_streak, sharpe)."""
    if len(gate_cols) == 0:
        mask = np.ones(len(df), dtype=bool)
    else:
        mask = df[gate_cols].fillna(0).astype(int).prod(axis=1).astype(bool)
    sub = df[mask]
    n = len(sub)
    if n < 5:
        return n, 0, 0, 0, 0, 0, 0
    wr = sub['won'].mean()
    pnl = sub['pnl_legacy_usd']
    dpt = pnl.mean()
    sum_pnl = pnl.sum()
    # Order by fire_us
    sub_sorted = sub.sort_values('fire_us')
    pnl_arr = sub_sorted['pnl_legacy_usd'].values
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_dd = dd.max() if len(dd) else 0
    # Loss streak
    won_arr = sub_sorted['won'].values
    losses = (won_arr == 0).astype(int)
    if len(losses) == 0:
        max_ls = 0
    else:
        groups = np.zeros_like(losses)
        cur = 0
        for i, v in enumerate(losses):
            cur = cur + 1 if v else 0
            groups[i] = cur
        max_ls = int(groups.max())
    # Sharpe: daily aggregation
    sub_sorted['day_idx'] = (pd.to_datetime(sub_sorted['fire_us'], unit='us').dt.date - pd.to_datetime(sub_sorted['fire_us'], unit='us').dt.date.min()).apply(lambda x: x.days)
    daily = sub_sorted.groupby('day_idx')['pnl_legacy_usd'].sum()
    if len(daily) >= 2 and daily.std() > 0:
        sharpe = (daily.mean() / daily.std()) * np.sqrt(365)
    else:
        sharpe = 0
    return n, wr, dpt, sum_pnl, max_dd, max_ls, sharpe

def fast_metrics(df, gates_mask, n_train_days):
    """Cached version: gates_mask is boolean."""
    sub = df[gates_mask]
    n = len(sub)
    if n < 5:
        return None
    won_mean = sub['won'].mean()
    pnl_arr = sub.sort_values('fire_us')['pnl_legacy_usd'].values
    if len(pnl_arr) == 0:
        return None
    cum = np.cumsum(pnl_arr)
    peak = np.maximum.accumulate(cum)
    dd_max = (peak - cum).max()
    # Loss streak
    won_arr = sub.sort_values('fire_us')['won'].values
    cur = max_ls = 0
    for v in won_arr:
        if v == 0:
            cur += 1
            if cur > max_ls: max_ls = cur
        else:
            cur = 0
    # daily PnL for sharpe
    dates = pd.to_datetime(sub['fire_us'], unit='us').dt.date
    daily = sub.groupby(dates)['pnl_legacy_usd'].sum()
    sharpe = (daily.mean() / daily.std() * np.sqrt(365)) if (len(daily) >= 2 and daily.std() > 0) else 0
    return {
        'n': n, 'wr': won_mean, 'dpt': pnl_arr.mean(), 'sum_pnl': pnl_arr.sum(),
        'max_dd': float(dd_max), 'max_ls': max_ls, 'sharpe': sharpe,
        'n_per_day': n / max(1, n_train_days),
    }

n_train_d = (pd.to_datetime(train['fire_us'], unit='us').dt.date.max() - pd.to_datetime(train['fire_us'], unit='us').dt.date.min()).days + 1
n_val_d = (pd.to_datetime(val['fire_us'], unit='us').dt.date.max() - pd.to_datetime(val['fire_us'], unit='us').dt.date.min()).days + 1
n_lock_d = (pd.to_datetime(lock['fire_us'], unit='us').dt.date.max() - pd.to_datetime(lock['fire_us'], unit='us').dt.date.min()).days + 1
print(f"\nDays: train={n_train_d}, val={n_val_d}, lock={n_lock_d}")

# --- Round 1: single gates ---
print("\n=== ROUND 1: single gates on TRAIN ===", flush=True)
round1 = []
for g in gates:
    m = train[g].fillna(0).astype(bool).values
    r = fast_metrics(train, m, n_train_d)
    if r is None or r['n'] < 20: continue
    r['stack'] = g
    round1.append(r)

r1 = pd.DataFrame(round1).sort_values('dpt', ascending=False)
print(r1.head(20).to_string(index=False))

# Take top 25 single gates by dpt + WR composite
r1['score'] = (r1['wr'] - 0.5) * 5 + np.minimum(r1['dpt'], 5) + np.log1p(r1['n'])
top_singles = r1.sort_values('score', ascending=False).head(25)['stack'].tolist()
# Also include high-WR but small-N to find sniper hits
extra = r1[(r1['wr'] >= 0.65) & (r1['n'] >= 50)].sort_values('wr', ascending=False).head(15)['stack'].tolist()
seed_pool = list(set(top_singles + extra))
print(f"\nSeed pool size: {len(seed_pool)}")
print(seed_pool)

# --- Round 2: pairs from seed pool ---
print("\n=== ROUND 2: pairs ===", flush=True)
round2 = []
n_pairs = len(seed_pool) * (len(seed_pool)-1) // 2
print(f"Testing {n_pairs} pairs...")
for i, (a, b) in enumerate(combinations(seed_pool, 2)):
    m = (train[a].fillna(0).astype(bool) & train[b].fillna(0).astype(bool)).values
    r = fast_metrics(train, m, n_train_d)
    if r is None: continue
    if r['n'] < 50 / (33/18): continue  # train should have at least 27 fires
    if r['wr'] < 0.65: continue
    r['stack'] = f"{a}+{b}"
    round2.append(r)

r2 = pd.DataFrame(round2).sort_values('dpt', ascending=False) if round2 else pd.DataFrame()
print(f"  pairs passing initial filter: {len(r2)}")
if len(r2) > 0:
    print(r2.head(15).to_string(index=False))

# --- Round 3: greedy expand to triples & quads ---
print("\n=== ROUND 3: greedy expand to 3-4 stacks ===", flush=True)
seeds3 = r2.head(30)['stack'].tolist() if len(r2) > 0 else []
round3 = []
for seed in seeds3:
    base_atoms = seed.split('+')
    for extra in seed_pool:
        if extra in base_atoms: continue
        stk = base_atoms + [extra]
        m = train[stk].fillna(0).astype(bool).prod(axis=1).astype(bool).values
        r = fast_metrics(train, m, n_train_d)
        if r is None: continue
        if r['n'] < 30: continue
        if r['wr'] < 0.70: continue
        r['stack'] = '+'.join(sorted(stk))
        round3.append(r)
r3 = pd.DataFrame(round3).drop_duplicates(subset='stack').sort_values('dpt', ascending=False) if round3 else pd.DataFrame()
print(f"  3-stacks passing: {len(r3)}")
if len(r3) > 0:
    print(r3.head(15).to_string(index=False))

# Quads
print("\n=== ROUND 4: 4-stacks ===", flush=True)
seeds4 = r3.head(50)['stack'].tolist() if len(r3) > 0 else []
round4 = []
for seed in seeds4:
    base_atoms = seed.split('+')
    for extra in seed_pool:
        if extra in base_atoms: continue
        stk = base_atoms + [extra]
        m = train[stk].fillna(0).astype(bool).prod(axis=1).astype(bool).values
        r = fast_metrics(train, m, n_train_d)
        if r is None: continue
        if r['n'] < 25: continue
        if r['wr'] < 0.72: continue
        r['stack'] = '+'.join(sorted(stk))
        round4.append(r)
r4 = pd.DataFrame(round4).drop_duplicates(subset='stack').sort_values('dpt', ascending=False) if round4 else pd.DataFrame()
print(f"  4-stacks: {len(r4)}")
if len(r4) > 0:
    print(r4.head(15).to_string(index=False))

# Quints
print("\n=== ROUND 5: 5-stacks ===", flush=True)
seeds5 = r4.head(50)['stack'].tolist() if len(r4) > 0 else []
round5 = []
for seed in seeds5:
    base_atoms = seed.split('+')
    for extra in seed_pool:
        if extra in base_atoms: continue
        stk = base_atoms + [extra]
        m = train[stk].fillna(0).astype(bool).prod(axis=1).astype(bool).values
        r = fast_metrics(train, m, n_train_d)
        if r is None: continue
        if r['n'] < 20: continue
        if r['wr'] < 0.75: continue
        r['stack'] = '+'.join(sorted(stk))
        round5.append(r)
r5 = pd.DataFrame(round5).drop_duplicates(subset='stack').sort_values('dpt', ascending=False) if round5 else pd.DataFrame()
print(f"  5-stacks: {len(r5)}")
if len(r5) > 0:
    print(r5.head(20).to_string(index=False))

# --- Combine all and rank ---
all_results = []
for size, df in [('R1', r1), ('R2', r2), ('R3', r3), ('R4', r4), ('R5', r5)]:
    if len(df) == 0: continue
    df2 = df.copy()
    df2['stack_size'] = size
    all_results.append(df2)
allr = pd.concat(all_results, ignore_index=True) if all_results else pd.DataFrame()
allr['score'] = (
    np.clip(allr['wr'] - 0.5, 0, 0.5) * 10 +
    np.clip(allr['dpt'], -5, 8) -
    np.clip(allr['max_dd'] - 300, 0, 1000) / 100 -
    np.clip(allr['max_ls'] - 6, 0, 30)
)
allr.to_csv(OUT / "_combinatorial_train.csv", index=False)
print(f"\nWrote _combinatorial_train.csv ({len(allr)} candidates)")

# --- Validate on val + lockbox ---
print("\n=== Validating top 50 on VAL + LOCKBOX ===", flush=True)
top50 = allr.sort_values('score', ascending=False).head(50)
val_rows = []
for _, row in top50.iterrows():
    stk = row['stack'].split('+')
    if not all(s in p.columns for s in stk):
        continue
    m_val = val[stk].fillna(0).astype(bool).prod(axis=1).astype(bool).values
    m_lock = lock[stk].fillna(0).astype(bool).prod(axis=1).astype(bool).values
    rv = fast_metrics(val, m_val, n_val_d) or {'n':0,'wr':0,'dpt':0,'max_dd':0,'max_ls':0,'sharpe':0,'sum_pnl':0,'n_per_day':0}
    rl = fast_metrics(lock, m_lock, n_lock_d) or {'n':0,'wr':0,'dpt':0,'max_dd':0,'max_ls':0,'sharpe':0,'sum_pnl':0,'n_per_day':0}
    val_rows.append({
        'stack': row['stack'], 'size': row['stack_size'],
        'n_train': row['n'], 'wr_train': row['wr'], 'dpt_train': row['dpt'],
        'sum_train': row['sum_pnl'], 'dd_train': row['max_dd'], 'ls_train': row['max_ls'],
        'shp_train': row['sharpe'],
        'n_val': rv['n'], 'wr_val': rv['wr'], 'dpt_val': rv['dpt'], 'sum_val': rv['sum_pnl'],
        'dd_val': rv['max_dd'], 'ls_val': rv['max_ls'], 'shp_val': rv['sharpe'],
        'n_lock': rl['n'], 'wr_lock': rl['wr'], 'dpt_lock': rl['dpt'], 'sum_lock': rl['sum_pnl'],
        'dd_lock': rl['max_dd'], 'ls_lock': rl['max_ls'], 'shp_lock': rl['sharpe'],
        'np_d_lock': rl['n_per_day'],
    })
vt = pd.DataFrame(val_rows)
vt = vt.sort_values('dpt_lock', ascending=False)
vt.to_csv(OUT / "_combinatorial_lockbox.csv", index=False)
print(vt[['stack','n_train','wr_train','dpt_train','n_val','wr_val','dpt_val','n_lock','wr_lock','dpt_lock','dd_lock','ls_lock','shp_lock']].head(20).to_string(index=False))

print(f"\nElapsed: {time.time()-t0:.1f}s")
