"""V6 SOL 15m combinatorial search.

Mission (RETRY after socket close):
- Greenfield deepen V5 winners (C1 OFFSET_120-240_WD5, C3 LATE_3T_rf_a_tr_s_tr_s)
- Try offset=60 (earliest in 15m grid), pre-window signals
- SOL 15m is 50/50 Up/Down: directional asymmetry OK to test
- Use rebuilt g_trend_slope_with from regime_panel_15m_v2_fixed
- Allow LS<=14, $/tr>=$4, DD<=$500
- Maximize $/tr * sqrt(n)

Sniper bar (V6 lockbox):
- WR>=0.65, $/tr>=$4, DD<=$500, LS<=14, n in [30,2000], bootstrap_p<=0.05
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from itertools import combinations
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_15m_v6")
t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

# Load universe
log("Loading SOL 15m V6 universe")
p = pd.read_parquet(OUT / "sol_15m_v6_universe.parquet")
# Drop rows where book_supports_25 (always-1 essentially) but apply fill viability check
p = p[p['entry_vwap'] < 0.998].copy()
log(f"Eligible fires: {len(p):,}")

p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
log(f"Date range: {dates_sorted[0]} -> {dates_sorted[-1]} ({len(dates_sorted)}d)")

# 3-way split (per V5 convention): train 22d / val 7d / lockbox 4d  (sniper_brief §7)
# Actually per V6 brief §7: 18/6/4. But we have 33 days. Use proportional 22/7/4
train_end = dates_sorted[22]
val_end = dates_sorted[29]
log(f"train < {train_end}, val < {val_end}, lockbox >= {val_end}")

train = p[p['date'] < train_end].copy()
val = p[(p['date'] >= train_end) & (p['date'] < val_end)].copy()
lock = p[p['date'] >= val_end].copy()
log(f"train: {len(train):,}, val: {len(val):,}, lockbox: {len(lock):,}")

# Drop atoms per V6 brief
DROP_ATOMS = {
    'g_book_depth_supports_250',  # operator dropped $250
    'g_within_dev', 'g_dev_extreme',  # always 0/1 for SOL 15m
    'g_book_supports_5', 'g_book_supports_25',  # always ~1, useless
    # Rare gates (cov <2%) — drop from combinatorial; they bias by absence
    'g_lm_high_stat','g_lm_extreme_against','g_hawkes_imbalance_with',
    'g_flow_with_and_no_whale','g_coinbase_basis_extreme_against','g_hl_liq_cascade_with',
    'g_imb5_strong_with','g_queue_top_high','g_imb_change_with','g_vwap_ge_50_le_85',
    'g_book_slope_steep_against','g_mp_change_with','g_mp_skew_with',
    # Drop g_mp_change_500ms_with (cov ~87%, but tiny 3.3% rate — combined w/ small cov, mostly 0s)
}
all_gates = [c for c in p.columns
             if c.startswith('g_') and c not in DROP_ATOMS]
# Filter rate range
final_gates = []
for g in all_gates:
    v = p[g]
    if v.dtype == 'object': continue
    rate = v.dropna().mean()
    cov = v.notna().mean()
    if cov < 0.8: continue  # require panel coverage >=80%
    if not (0.02 <= rate <= 0.97): continue
    final_gates.append(g)
log(f"Atoms in search universe ({len(final_gates)}): {final_gates}")


def eval_stack(df, atoms):
    """Returns (n, wr, dpt, dd, ls_max, sum_pnl) for stack applied to df."""
    if len(atoms) == 0:
        sub = df
    else:
        mask = np.ones(len(df), dtype=bool)
        for a in atoms:
            col = df[a].values
            # treat NaN as 0 (gate not satisfied)
            col = np.where(np.isnan(col) if col.dtype == float else False, 0, col).astype(float) if col.dtype == float else col
            mask &= (col == 1)
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
log("=== STAGE 1: single-gate scan (train) ===")
rows = []
for g in final_gates:
    n, wr, dpt, dd, ls, _ = eval_stack(train, [g])
    if n < 50:
        continue
    rows.append({'g': g, 'n': n, 'wr': wr, 'dpt': dpt, 'dd': dd, 'ls': ls,
                 'score': wr * np.sqrt(n)})
seed = pd.DataFrame(rows)
log(f"Single-gate atoms with n>=50: {len(seed)}")
seed = seed.sort_values('wr', ascending=False).reset_index(drop=True)
seed.to_csv(OUT / "_single_gate_v6.csv", index=False)
# Take top 35 by WR + top 15 by dpt → broad seed pool
top_by_wr = list(seed.head(35)['g'])
top_by_dpt = list(seed.sort_values('dpt', ascending=False).head(15)['g'])
seed_atoms = sorted(set(top_by_wr + top_by_dpt))
log(f"Seed atoms (high-WR + high-dpt union): {len(seed_atoms)}")
print(seed.head(25)[['g','n','wr','dpt']].to_string(index=False))

# === STAGE 2: pair scan ===
log("=== STAGE 2: pair scan ===")
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
    log(f"Pairs surviving (n>=25, wr>=0.60): {len(pairs)} (positive-dpt: {len(pos_pairs)})")
    print(pairs.head(20)[['stack','n','wr','dpt','dd','ls','score']].to_string(index=False))
else:
    log("No pairs survived.")

# === STAGE 3: 3-stack from top pairs by score ===
log("=== STAGE 3: 3-stack expansion ===")
seed3 = set()
base_pairs = pairs[pairs['dpt'] > 0].head(120) if len(pairs) > 0 else pd.DataFrame()
high_wr_pairs = pairs[(pairs['wr'] >= 0.68) & (pairs['n'] >= 30)].head(60) if len(pairs) > 0 else pd.DataFrame()
expand_pairs = pd.concat([base_pairs, high_wr_pairs]).drop_duplicates(subset=['stack'])
log(f"  expanding from {len(expand_pairs)} pairs")
for _, r in expand_pairs.iterrows():
    for g3 in seed_atoms:
        if g3 in (r['g1'], r['g2']):
            continue
        stack = tuple(sorted([r['g1'], r['g2'], g3]))
        seed3.add(stack)
log(f"3-stack candidates to test: {len(seed3)}")

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
    log(f"3-stack candidates surviving (n>=25, wr>=0.65): {len(tris)} (dpt>1: {len(pos_tris)})")
    print(tris.head(25)[['stack','n','wr','dpt','dd','ls']].to_string(index=False))
else:
    log("No 3-stacks survived.")


# === STAGE 4: 4-stack greedy ===
log("=== STAGE 4: 4-stack greedy ===")
seed4 = set()
expand_tris = tris[(tris['n'] >= 30) & (tris['wr'] >= 0.70)].head(200) if len(tris) > 0 else pd.DataFrame()
log(f"  expanding from {len(expand_tris)} 3-stacks")
for _, r in expand_tris.iterrows():
    for g4 in seed_atoms:
        if g4 in (r['g1'], r['g2'], r['g3']):
            continue
        stack = tuple(sorted([r['g1'], r['g2'], r['g3'], g4]))
        seed4.add(stack)
log(f"4-stack candidates to test: {len(seed4)}")

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
    log(f"4-stack candidates surviving (n>=20, wr>=0.70, dpt>=2): {len(quads)}")
    print(quads.head(25)[['stack','n','wr','dpt','dd','ls','score']].to_string(index=False))
else:
    log("No 4-stacks survived.")


# === STAGE 5: 5-stack greedy ===
log("=== STAGE 5: 5-stack greedy ===")
seed5 = set()
expand_quads = quads.head(120) if len(quads) > 0 else pd.DataFrame()
for _, r in expand_quads.iterrows():
    stack_atoms = r['stack'].split('|')
    for g5 in seed_atoms:
        if g5 in stack_atoms:
            continue
        new_stack = tuple(sorted(stack_atoms + [g5]))
        seed5.add(new_stack)
log(f"5-stack candidates to test: {len(seed5)}")

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
    log(f"5-stack candidates surviving (n>=15, wr>=0.72, dpt>=3): {len(quints)}")
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
# Keep only train-profitable
all_cands = all_cands[all_cands['dpt'] >= 1.5]
all_cands.to_csv(OUT / "_train_candidates.csv", index=False)
log(f"Total train candidates with dpt>=1.5: {len(all_cands)}")

# === STAGE 6: validate on val + lockbox ===
log("=== STAGE 6: validate on val + lockbox ===")
results = []
for _, r in all_cands.iterrows():
    atoms = r['stack'].split('|')
    n_v, wr_v, dpt_v, dd_v, ls_v, sum_v = eval_stack(val, atoms)
    n_l, wr_l, dpt_l, dd_l, ls_l, sum_l = eval_stack(lock, atoms)
    if n_l < 15:
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
log(f"Validated candidates: {len(res_df)}")
if len(res_df) > 0:
    print(res_df.head(25)[['stack','depth','n_l','wr_l','dpt_l','dd_l','ls_l','score_l']].to_string(index=False))
res_df.to_csv(OUT / "_validated_v6.csv", index=False)

# === V6 PROFILE PASS ===
if len(res_df) > 0:
    final = res_df[
        (res_df['n_l'] >= 20) & (res_df['n_l'] <= 2000) &
        (res_df['wr_l'] >= 0.65) & (res_df['dpt_l'] >= 4.0) &
        (res_df['dd_l'] <= 500) & (res_df['ls_l'] <= 14)
    ].copy()
    log(f"=== V6 PROFILE PASS (pre-bootstrap): {len(final)} ===")
    if len(final) > 0:
        print(final[['stack','depth','n_tr','wr_tr','dpt_tr','n_v','wr_v','dpt_v','n_l','wr_l','dpt_l','dd_l','ls_l','score_l']].to_string(index=False))
    final.to_csv(OUT / "_v6_profile_pass.csv", index=False)

# Also a softer pass (V6 profile relaxed n_l minimum and dpt_l)
if len(res_df) > 0:
    soft = res_df[
        (res_df['n_l'] >= 15) &
        (res_df['wr_l'] >= 0.60) & (res_df['dpt_l'] >= 2.0) &
        (res_df['dd_l'] <= 500) & (res_df['ls_l'] <= 14)
    ].copy()
    log(f"=== V6 SOFT PASS: {len(soft)} ===")
    soft.to_csv(OUT / "_v6_soft_pass.csv", index=False)

log(f"Elapsed: {time.time()-t0:.1f}s")
