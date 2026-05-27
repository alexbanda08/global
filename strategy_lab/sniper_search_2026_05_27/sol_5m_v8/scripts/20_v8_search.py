"""V8 SOL 5m search — Paths J, K, Q, O + V7 inherited gates.

Key rules:
- USE FULL 32.7d v3 window for eligibility (n_full). DO NOT cap at 28d.
- For sleeves that USE 28d-only gates (parent_15m, BTC/ETH regime), fires before Apr 28
  are auto-excluded by the gate mask (gate=0). That's fine; we still compute n_full on the
  full panel.
- 60/20/20 split based on AVAILABLE dates per stack (chronological).
- Report n_full, n_lockbox, wr_full, $/tr_full, $/tr_lockbox, proj_32d, proj_full, proj_honest.

Profile per V8 brief §3:
- n_lockbox ∈ [30, 2000]
- WR >= 65% (or >=55% if $/tr >= $10)
- $/tr at $25 >= $4
- Max DD at $25 <= $500
- Max loss streak <= 14
- Bootstrap p (lockbox) <= 0.05
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from itertools import combinations
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v8")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v8.parquet")
# Eligibility filters (same as V7)
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
print(f"Eligible after vwap+depth filter: {len(p)}")

p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
days_total = len(dates_sorted)
print(f"Date range: {dates_sorted[0]} -> {dates_sorted[-1]} ({days_total}d)")

# 60/20/20 split
n_train = int(round(days_total * 0.60))
n_val = int(round(days_total * 0.20))
train_end = dates_sorted[n_train]
val_end = dates_sorted[n_train + n_val]
days_train = n_train
days_val = n_val
days_lockbox = days_total - n_train - n_val
print(f"Split: train < {train_end} ({days_train}d), val < {val_end} ({days_val}d), lockbox >= {val_end} ({days_lockbox}d)")

train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()
print(f"train: {len(train)}, val: {len(val)}, lockbox: {len(lock)}")

# Window in days
def date_span(df):
    if len(df) == 0:
        return 1
    d_min = df['date'].min()
    d_max = df['date'].max()
    return (d_max - d_min).days + 1

DAYS_FULL = date_span(p)
DAYS_LOCK = date_span(lock)
DAYS_TRAIN = date_span(train)
DAYS_VAL = date_span(val)
print(f"Day spans: full={DAYS_FULL}, train={DAYS_TRAIN}, val={DAYS_VAL}, lockbox={DAYS_LOCK}")


def eval_stack(df, atoms, days_span=None):
    if len(atoms) == 0:
        sub = df
    else:
        mask = np.ones(len(df), dtype=bool)
        for a in atoms:
            mask &= (df[a].values == 1)
        sub = df[mask]
    if len(sub) == 0:
        return {'n':0,'wr':0,'dpt':0,'dd':0,'ls':0,'sum':0,'sharpe':0}
    sub = sub.sort_values('fire_us')
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0; cur = 0
    for v in pnl:
        if v < 0:
            cur += 1; ls_max = max(ls_max, cur)
        else:
            cur = 0
    sharpe = float(pnl.mean() / pnl.std() * np.sqrt(len(pnl))) if pnl.std() > 0 else 0
    return {'n': len(sub), 'wr': float(sub['won'].mean()), 'dpt': float(pnl.mean()),
            'dd': dd, 'ls': ls_max, 'sum': float(pnl.sum()), 'sharpe': sharpe}


# === Atom pool ===
DROP_ATOMS = {
    'g_depth_250_strict', 'g_depth_250_med', 'g_depth_250_loose',
    'g_book_depth_supports_25',
    'g_within_dev', 'g_dev_extreme', 'g_R1_sum', 'g_compression_loose',
    'g_q_15m_confluence',  # ~99% pass rate, junk
    'g_q_15m_dense_confluence',  # 82% pass rate
    'g_q_15m_low_wr_with', 'g_q_15m_high_wr_with',  # split panel, may be junk
}

gate_pool = []
for c in p.columns:
    if (c.startswith('g_') or c.startswith('mgf_g_')) and c not in DROP_ATOMS:
        if c.startswith('g_f7_rsi_') or 'f7_rsi_with' in c:
            continue  # exclude V6's sparse f7 (V7 lesson)
        pr = p[c].mean()
        if 0.003 <= pr <= 0.95:
            gate_pool.append(c)

# V8 anchors (must include in pair/tri search)
v8_anchors = [g for g in gate_pool if (g.startswith('g_2asset_') or g.startswith('g_3asset_') or
              g.startswith('g_tod_') or g.startswith('g_q_') or g.startswith('g_hl_'))]
v7_winners = ['g_btc_trend_30m_with', 'g_btc_trend_15m_with', 'g_btc_trend_5m_with',
              'g_btc_f7_with', 'g_btc_f7_against', 'g_btc_f7_with_loose',
              'g_hurst_reverting', 'g_hurst_trending',
              'g_cci_extreme_with',
              'g_f7_v7_overbought', 'g_f7_v7_oversold', 'g_f7_v7_with',
              'g_mfi_strong_with', 'g_mfi_with', 'g_stoch_strong_with',
              'g_tr_above_ema800', 'g_vwap_in_45_85',
              'g_parent_with_dir', 'g_parent_slope_with', 'g_parent_ranging']
v7_winners = [g for g in v7_winners if g in gate_pool]
print(f"Atom pool: {len(gate_pool)}, V8 anchors: {len(v8_anchors)}, V7 winners: {len(v7_winners)}")


# === STAGE 1: single-gate scan on TRAIN ===
print("\n=== STAGE 1: single-gate scan on train ===")
rows = []
for g in gate_pool:
    r = eval_stack(train, [g])
    if r['n'] < 50:
        continue
    rows.append({'g': g, 'n': r['n'], 'wr': r['wr'], 'dpt': r['dpt']})
seed = pd.DataFrame(rows).sort_values('wr', ascending=False)
seed.to_csv(OUT / "_single_gate_v8.csv", index=False)
print(f"Single-gate atoms n>=50: {len(seed)}")
print("Top 20 by WR:")
print(seed.head(20).to_string(index=False))
print("Top 20 by $/tr:")
print(seed.sort_values('dpt', ascending=False).head(20).to_string(index=False))

# Include V8 anchors regardless of single-gate performance (they may shine in combos)
top_wr = list(seed.head(50)['g'])
top_dpt = list(seed.sort_values('dpt', ascending=False).head(20)['g'])
seed_atoms = sorted(set(top_wr + top_dpt + v8_anchors + v7_winners))
print(f"\nSeed atoms for search: {len(seed_atoms)}")


# === STAGE 2: pair scan (focused on at least one V8 anchor) ===
print("\n=== STAGE 2: pair scan ===")
pair_rows = []
# Pairs anchored on at least one v8 anchor for J/K/Q/O paths
v8_anchor_set = set(v8_anchors)
for a, b in combinations(seed_atoms, 2):
    # require at least one V8 anchor OR pair from inherited V7 winners
    if not (a in v8_anchor_set or b in v8_anchor_set or (a in v7_winners and b in v7_winners)):
        continue
    r = eval_stack(train, [a, b])
    if r['n'] < 25 or r['wr'] < 0.58:
        continue
    pair_rows.append({'stack': '|'.join(sorted([a,b])), 'g1':a,'g2':b,
                      'n':r['n'],'wr':r['wr'],'dpt':r['dpt'],'dd':r['dd'],'ls':r['ls'],
                      'score': r['dpt'] * np.sqrt(r['n']) if r['dpt']>0 else r['wr']*0.001})
pairs = pd.DataFrame(pair_rows)
if len(pairs) > 0:
    pairs = pairs.sort_values('score', ascending=False)
    print(f"Pairs surviving: {len(pairs)}")
    print(pairs.head(20)[['stack','n','wr','dpt','dd','ls']].to_string(index=False))


# === STAGE 3: 3-stack ===
print("\n=== STAGE 3: 3-stack expansion ===")
seed3 = set()
base_pairs = pairs[pairs['dpt'] > 0.5].head(300) if len(pairs) > 0 else pd.DataFrame()
high_wr_pairs = pairs[(pairs['wr'] >= 0.62) & (pairs['n'] >= 30)].head(200) if len(pairs) > 0 else pd.DataFrame()
expand = pd.concat([base_pairs, high_wr_pairs]).drop_duplicates(subset=['stack'])
for _, r in expand.iterrows():
    for g3 in seed_atoms:
        if g3 in (r['g1'], r['g2']):
            continue
        stack = tuple(sorted([r['g1'], r['g2'], g3]))
        seed3.add(stack)
print(f"3-stack candidates: {len(seed3)}")

tri_rows = []
for stack in seed3:
    r = eval_stack(train, list(stack))
    if r['n'] < 20 or r['wr'] < 0.65:
        continue
    tri_rows.append({'stack': '|'.join(stack),
                     'g1':stack[0],'g2':stack[1],'g3':stack[2],
                     'n':r['n'],'wr':r['wr'],'dpt':r['dpt'],'dd':r['dd'],'ls':r['ls'],
                     'score': r['dpt']*np.sqrt(r['n']) if r['dpt']>0 else 0})
tris = pd.DataFrame(tri_rows)
if len(tris) > 0:
    tris = tris.sort_values('score', ascending=False)
    print(f"3-stacks surviving: {len(tris)}")
    print(tris.head(20)[['stack','n','wr','dpt','dd','ls']].to_string(index=False))


# === STAGE 4: 4-stack ===
print("\n=== STAGE 4: 4-stack greedy ===")
seed4 = set()
expand_tris = tris[(tris['n'] >= 20) & (tris['wr'] >= 0.68)].head(500) if len(tris) > 0 else pd.DataFrame()
for _, r in expand_tris.iterrows():
    for g4 in seed_atoms:
        if g4 in (r['g1'], r['g2'], r['g3']):
            continue
        stack = tuple(sorted([r['g1'], r['g2'], r['g3'], g4]))
        seed4.add(stack)
print(f"4-stack candidates: {len(seed4)}")

q4 = []
for stack in seed4:
    r = eval_stack(train, list(stack))
    if r['n'] < 15 or r['wr'] < 0.70 or r['dpt'] < 1.5:
        continue
    q4.append({'stack': '|'.join(stack), 'depth': 4,
               'n':r['n'],'wr':r['wr'],'dpt':r['dpt'],'dd':r['dd'],'ls':r['ls'],
               'score':r['dpt']*np.sqrt(r['n'])})
quads = pd.DataFrame(q4)
if len(quads) > 0:
    quads = quads.sort_values('score', ascending=False)
    print(f"4-stacks surviving: {len(quads)}")
    print(quads.head(20)[['stack','n','wr','dpt','dd','ls']].to_string(index=False))


# === STAGE 5: 5-stack ===
print("\n=== STAGE 5: 5-stack greedy ===")
seed5 = set()
expand_quads = quads.head(200) if len(quads) > 0 else pd.DataFrame()
for _, r in expand_quads.iterrows():
    stack_atoms = r['stack'].split('|')
    for g5 in seed_atoms:
        if g5 in stack_atoms:
            continue
        new_stack = tuple(sorted(stack_atoms + [g5]))
        seed5.add(new_stack)
print(f"5-stack candidates: {len(seed5)}")

q5 = []
for stack in seed5:
    r = eval_stack(train, list(stack))
    if r['n'] < 12 or r['wr'] < 0.72 or r['dpt'] < 2.5:
        continue
    q5.append({'stack': '|'.join(stack), 'depth': 5,
               'n':r['n'],'wr':r['wr'],'dpt':r['dpt'],'dd':r['dd'],'ls':r['ls'],
               'score':r['dpt']*np.sqrt(r['n'])})
quints = pd.DataFrame(q5)
if len(quints) > 0:
    quints = quints.sort_values('score', ascending=False)
    print(f"5-stacks surviving: {len(quints)}")
    print(quints.head(20)[['stack','n','wr','dpt','dd','ls']].to_string(index=False))


# === Combine all candidates ===
parts = []
if len(pairs) > 0:
    parts.append(pairs.assign(depth=2)[['stack','depth','n','wr','dpt','dd','ls','score']])
if len(tris) > 0:
    parts.append(tris.assign(depth=3)[['stack','depth','n','wr','dpt','dd','ls','score']])
if len(quads) > 0:
    parts.append(quads.assign(depth=4)[['stack','depth','n','wr','dpt','dd','ls','score']])
if len(quints) > 0:
    parts.append(quints.assign(depth=5)[['stack','depth','n','wr','dpt','dd','ls','score']])
all_cands = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
all_cands = all_cands[all_cands['dpt'] >= 1.0]
all_cands.to_csv(OUT / "_train_candidates_v8.csv", index=False)
print(f"\nTotal train candidates dpt>=1.0: {len(all_cands)}")


# === STAGE 6: validate on val + lockbox + FULL ===
print("\n=== STAGE 6: validate on val + lockbox + FULL ===")
results = []
for _, r in all_cands.iterrows():
    atoms = r['stack'].split('|')
    rv = eval_stack(val, atoms)
    rl = eval_stack(lock, atoms)
    rf = eval_stack(p, atoms)  # full panel
    if rl['n'] < 15:
        continue
    # Projection conventions
    dpt_lock = rl['dpt']
    proj_32d = dpt_lock * (rl['n'] / max(DAYS_LOCK, 1)) * 32.66
    proj_full = rf['dpt'] * (rf['n'] / max(DAYS_FULL, 1)) * 32.66
    proj_honest = min(proj_32d, proj_full)
    results.append({
        'stack': r['stack'], 'depth': r['depth'],
        'n_train': r['n'], 'wr_train': r['wr'], 'dpt_train': r['dpt'],
        'n_val': rv['n'], 'wr_val': rv['wr'], 'dpt_val': rv['dpt'],
        'n_lockbox': rl['n'], 'wr_lockbox': rl['wr'], 'dpt_lockbox': rl['dpt'],
        'dd_lockbox': rl['dd'], 'ls_lockbox': rl['ls'], 'sum_lockbox': rl['sum'], 'sharpe_lockbox': rl['sharpe'],
        'n_full': rf['n'], 'wr_full': rf['wr'], 'dpt_full': rf['dpt'], 'sum_full': rf['sum'],
        'proj_32d': proj_32d, 'proj_full': proj_full, 'proj_honest': proj_honest,
    })
res_df = pd.DataFrame(results)
if len(res_df) > 0:
    res_df = res_df.sort_values('proj_honest', ascending=False)
print(f"Validated candidates: {len(res_df)}")
res_df.to_csv(OUT / "_validated_v8.csv", index=False)


# === V8 profile pass (pre-bootstrap) ===
if len(res_df) > 0:
    final = res_df[
        (res_df['n_lockbox'] >= 30) & (res_df['n_lockbox'] <= 2000) &
        (((res_df['wr_lockbox'] >= 0.65) & (res_df['dpt_lockbox'] >= 4.0)) |
         ((res_df['wr_lockbox'] >= 0.55) & (res_df['dpt_lockbox'] >= 10.0))) &
        (res_df['dd_lockbox'] <= 500) & (res_df['ls_lockbox'] <= 14)
    ].copy()
    print(f"\n=== V8 PROFILE PASS (pre-bootstrap): {len(final)} ===")
    if len(final) > 0:
        cols = ['stack','depth','n_train','wr_train','dpt_train','n_val','wr_val','dpt_val',
                'n_lockbox','wr_lockbox','dpt_lockbox','dd_lockbox','ls_lockbox',
                'n_full','wr_full','dpt_full','proj_32d','proj_full','proj_honest']
        print(final[cols].head(40).to_string(index=False))
    final.to_csv(OUT / "_v8_profile_pass.csv", index=False)

print(f"\nElapsed: {time.time()-t0:.1f}s")
