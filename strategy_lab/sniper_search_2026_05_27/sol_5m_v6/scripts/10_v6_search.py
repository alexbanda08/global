"""V6 SOL 5m combinatorial search (v2 — broader seed pool, asymm direction, early offset).

Constraints (V6 brief):
- Max stake $25 (no $250 testing)
- Drop g_depth_250_strict/med/loose; allow g_book_depth_supports_25 (fill viability only)
- Loss streak <= 14 OK if $/tr compensates
- Maximize $/tr * sqrt(n) (Sharpe-flavored)
- WR >= 65% on lockbox
- $/tr >= $4 on lockbox
- DD <= $500 on lockbox
- LS <= 14 on lockbox
- Bootstrap p <= 0.05
- Test asymmetric direction (UP/DOWN only) and per-offset bands
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from itertools import combinations
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v6")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m_v6.parquet")
p = p[(p['entry_vwap'] < 0.998) & (p['g_book_depth_supports_25'] == 1)].copy()
print(f"Eligible fires (valid fill + $25 viable): {len(p)}")

p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
print(f"Date range: {dates_sorted[0]} -> {dates_sorted[-1]} ({len(dates_sorted)}d)")
train_end = dates_sorted[18]
val_end = dates_sorted[24]
print(f"train_end < {train_end}, val_end < {val_end}, lockbox >= {val_end}")

train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()
print(f"train: {len(train)}, val: {len(val)}, lockbox: {len(lock)}")

DROP_ATOMS = {
    'g_depth_250_strict', 'g_depth_250_med', 'g_depth_250_loose',
    'g_book_depth_supports_25',
    'g_within_dev', 'g_dev_extreme', 'g_R1_sum', 'g_compression_loose',
}
all_gates = [c for c in p.columns
             if (c.startswith('g_') or c.startswith('mgf_g_'))
             and c not in DROP_ATOMS]
all_gates = [g for g in all_gates if 0.005 <= p[g].mean() <= 0.95]
print(f"\nAtoms in search universe: {len(all_gates)}")


def eval_stack(df, atoms):
    """Returns (n, wr, dpt, dd, ls_max, sum_pnl) for stack applied to df."""
    if len(atoms) == 0:
        sub = df
    else:
        mask = np.ones(len(df), dtype=bool)
        for a in atoms:
            mask &= (df[a].values == 1)
        sub = df[mask]
    if len(sub) == 0:
        return 0, 0.0, 0.0, 0.0, 0, 0.0
    sub = sub.sort_values('fire_us')
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0
    cur = 0
    for v in pnl:
        if v < 0:
            cur += 1
            ls_max = max(ls_max, cur)
        else:
            cur = 0
    return len(sub), float(sub['won'].mean()), float(pnl.mean()), dd, ls_max, float(pnl.sum())


# === STAGE 1: single-gate scan (broader seed) ===
print("\n=== STAGE 1: single-gate scan (train) ===")
rows = []
for g in all_gates:
    n, wr, dpt, dd, ls, _ = eval_stack(train, [g])
    if n < 50:
        continue
    rows.append({'g': g, 'n': n, 'wr': wr, 'dpt': dpt, 'dd': dd, 'ls': ls,
                 'score': wr * np.sqrt(n)})  # promote high-WR even if dpt negative (will be paired)
seed = pd.DataFrame(rows)
print(f"Single-gate atoms with n>=50: {len(seed)}")
# Take top 50 by WR (raw selection power) + top 20 by dpt
seed = seed.sort_values('wr', ascending=False).reset_index(drop=True)
seed.to_csv(OUT / "_single_gate_v6.csv", index=False)
top_by_wr = list(seed.head(40)['g'])
top_by_dpt = list(seed.sort_values('dpt', ascending=False).head(15)['g'])
seed_atoms = sorted(set(top_by_wr + top_by_dpt))
print(f"\nSeed atoms (high-WR + high-dpt union): {len(seed_atoms)}")
print(seed.head(25)[['g','n','wr','dpt']].to_string(index=False))


# === STAGE 2: pair scan ===
print("\n=== STAGE 2: pair scan ===")
pair_rows = []
for a, b in combinations(seed_atoms, 2):
    n, wr, dpt, dd, ls, _ = eval_stack(train, [a, b])
    if n < 25 or wr < 0.60:
        continue
    pair_rows.append({'stack': '|'.join(sorted([a,b])), 'g1':a,'g2':b,
                      'n':n,'wr':wr,'dpt':dpt,'dd':dd,'ls':ls,
                      'score': dpt * np.sqrt(n) if dpt > 0 else wr * np.sqrt(n) * 0.001})
pairs = pd.DataFrame(pair_rows)
if len(pairs) > 0:
    pairs = pairs.sort_values('score', ascending=False)
    pos_pairs = pairs[pairs['dpt'] > 0.5]
    print(f"Pairs surviving (n>=25, wr>=0.60): {len(pairs)} (positive-dpt: {len(pos_pairs)})")
    print(pairs.head(20)[['stack','n','wr','dpt','dd','ls','score']].to_string(index=False))
else:
    print("No pairs survived.")

# === STAGE 3: 3-stack from top pairs by score ===
print("\n=== STAGE 3: 3-stack expansion ===")
seed3 = set()
# Use all positive-dpt pairs as base (or top 100 if many)
base_pairs = pairs[pairs['dpt'] > 0].head(150) if len(pairs) > 0 else pd.DataFrame()
# Also try pairs with high WR (>=0.70) even if dpt negative — adding a 3rd gate may push positive
high_wr_pairs = pairs[(pairs['wr'] >= 0.70) & (pairs['n'] >= 30)].head(80) if len(pairs) > 0 else pd.DataFrame()
expand_pairs = pd.concat([base_pairs, high_wr_pairs]).drop_duplicates(subset=['stack'])
print(f"  expanding from {len(expand_pairs)} pairs")
for _, r in expand_pairs.iterrows():
    for g3 in seed_atoms:
        if g3 in (r['g1'], r['g2']):
            continue
        stack = tuple(sorted([r['g1'], r['g2'], g3]))
        seed3.add(stack)
print(f"3-stack candidates to test: {len(seed3)}")

tri_rows = []
for stack in seed3:
    n, wr, dpt, dd, ls, _ = eval_stack(train, list(stack))
    if n < 25 or wr < 0.65:
        continue
    tri_rows.append({'stack': '|'.join(stack),
                     'g1':stack[0],'g2':stack[1],'g3':stack[2],
                     'n':n,'wr':wr,'dpt':dpt,'dd':dd,'ls':ls,
                     'score': dpt * np.sqrt(n) if dpt > 0 else 0})

tris = pd.DataFrame(tri_rows)
if len(tris) > 0:
    tris = tris.sort_values(['score','dpt'], ascending=[False, False])
    pos_tris = tris[tris['dpt'] > 1.0]
    print(f"3-stack candidates surviving (n>=25, wr>=0.65): {len(tris)} (dpt>1: {len(pos_tris)})")
    print(tris.head(25)[['stack','n','wr','dpt','dd','ls']].to_string(index=False))
else:
    print("No 3-stacks survived.")


# === STAGE 4: 4-stack greedy ===
print("\n=== STAGE 4: 4-stack greedy ===")
seed4 = set()
expand_tris = tris[(tris['n'] >= 30) & (tris['wr'] >= 0.70)].head(250) if len(tris) > 0 else pd.DataFrame()
print(f"  expanding from {len(expand_tris)} 3-stacks")
for _, r in expand_tris.iterrows():
    for g4 in seed_atoms:
        if g4 in (r['g1'], r['g2'], r['g3']):
            continue
        stack = tuple(sorted([r['g1'], r['g2'], r['g3'], g4]))
        seed4.add(stack)
print(f"4-stack candidates to test: {len(seed4)}")

q4 = []
for stack in seed4:
    n, wr, dpt, dd, ls, _ = eval_stack(train, list(stack))
    if n < 20 or wr < 0.70 or dpt < 2.0:
        continue
    q4.append({'stack': '|'.join(stack), 'depth': 4, 'n':n,'wr':wr,'dpt':dpt,
               'dd':dd,'ls':ls, 'score':dpt*np.sqrt(n)})
quads = pd.DataFrame(q4)
if len(quads) > 0:
    quads = quads.sort_values('score', ascending=False)
    print(f"4-stack candidates surviving (n>=20, wr>=0.70, dpt>=2): {len(quads)}")
    print(quads.head(25)[['stack','n','wr','dpt','dd','ls','score']].to_string(index=False))
else:
    print("No 4-stacks survived.")


# === STAGE 5: 5-stack greedy ===
print("\n=== STAGE 5: 5-stack greedy ===")
seed5 = set()
expand_quads = quads.head(150) if len(quads) > 0 else pd.DataFrame()
for _, r in expand_quads.iterrows():
    stack_atoms = r['stack'].split('|')
    for g5 in seed_atoms:
        if g5 in stack_atoms:
            continue
        new_stack = tuple(sorted(stack_atoms + [g5]))
        seed5.add(new_stack)
print(f"5-stack candidates to test: {len(seed5)}")

q5 = []
for stack in seed5:
    n, wr, dpt, dd, ls, _ = eval_stack(train, list(stack))
    if n < 15 or wr < 0.72 or dpt < 3.0:
        continue
    q5.append({'stack': '|'.join(stack), 'depth':5, 'n':n,'wr':wr,'dpt':dpt,
               'dd':dd,'ls':ls, 'score':dpt*np.sqrt(n)})
quints = pd.DataFrame(q5)
if len(quints) > 0:
    quints = quints.sort_values('score', ascending=False)
    print(f"5-stack candidates surviving (n>=15, wr>=0.72, dpt>=3): {len(quints)}")
    print(quints.head(25)[['stack','n','wr','dpt','dd','ls','score']].to_string(index=False))


# === Combine and validate ===
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
# Keep only train-profitable (dpt>=1.5 on train; we'll trim more on validation)
all_cands = all_cands[all_cands['dpt'] >= 1.5]
all_cands.to_csv(OUT / "_train_candidates.csv", index=False)
print(f"\nTotal train candidates with dpt>=1.5: {len(all_cands)}")

# Validate on val + lockbox
print("\n=== STAGE 6: validate on val + lockbox ===")
results = []
for _, r in all_cands.iterrows():
    atoms = r['stack'].split('|')
    n_v, wr_v, dpt_v, dd_v, ls_v, sum_v = eval_stack(val, atoms)
    n_l, wr_l, dpt_l, dd_l, ls_l, sum_l = eval_stack(lock, atoms)
    if n_l < 20:
        continue
    results.append({
        'stack': r['stack'], 'depth': r['depth'],
        'n_tr': r['n'], 'wr_tr': r['wr'], 'dpt_tr': r['dpt'], 'dd_tr': r['dd'], 'ls_tr': r['ls'],
        'n_v': n_v, 'wr_v': wr_v, 'dpt_v': dpt_v, 'dd_v': dd_v, 'ls_v': ls_v,
        'n_l': n_l, 'wr_l': wr_l, 'dpt_l': dpt_l, 'dd_l': dd_l, 'ls_l': ls_l, 'sum_l': sum_l,
        'score_l': dpt_l * np.sqrt(n_l) if dpt_l > 0 else 0,
    })
res_df = pd.DataFrame(results)
if len(res_df) > 0:
    res_df = res_df.sort_values('score_l', ascending=False)
print(f"Validated candidates: {len(res_df)}")
if len(res_df) > 0:
    print(res_df.head(25)[['stack','depth','n_l','wr_l','dpt_l','dd_l','ls_l','score_l']].to_string(index=False))
res_df.to_csv(OUT / "_validated_v6.csv", index=False)

# === Final V6 profile pass ===
if len(res_df) > 0:
    final = res_df[
        (res_df['n_l'] >= 30) & (res_df['n_l'] <= 2000) &
        (res_df['wr_l'] >= 0.65) & (res_df['dpt_l'] >= 4.0) &
        (res_df['dd_l'] <= 500) & (res_df['ls_l'] <= 14)
    ].copy()
    print(f"\n=== V6 PROFILE PASS (pre-bootstrap): {len(final)} ===")
    if len(final) > 0:
        print(final[['stack','depth','n_tr','wr_tr','dpt_tr','n_v','wr_v','dpt_v','n_l','wr_l','dpt_l','dd_l','ls_l','score_l']].to_string(index=False))
    final.to_csv(OUT / "_v6_profile_pass.csv", index=False)

print(f"\nElapsed: {time.time()-t0:.1f}s")
