"""V6 SOL 15m: dedupe near-duplicate stacks, bootstrap-validate, Kelly sizing.

For SOL 15m: g_tr_stack_with == g_tr_stack_full_with (identical columns). Treat as one.
Pick canonical form and dedupe via canonical gate-key.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_15m_v6")
t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

# Pull validated candidates
v = pd.read_csv(OUT / "_validated_v6.csv")
log(f"Validated candidates: {len(v)}")

# Canonical key: identical gate cols collapsed
DUPE_MAP = {
    'g_tr_stack_full_with': 'g_tr_stack_with',
    'g_prewindow_mp_skew_strong_with': 'g_prewindow_mp_skew_with',
}
def canon_stack(s):
    atoms = s.split('|')
    atoms = [DUPE_MAP.get(a, a) for a in atoms]
    atoms = sorted(set(atoms))
    return '|'.join(atoms)

v['stack_canon'] = v['stack'].apply(canon_stack)

# For each canonical stack, pick the entry with the highest score_l
v_dedup = v.sort_values('score_l', ascending=False).drop_duplicates('stack_canon', keep='first').reset_index(drop=True)
log(f"After dedup: {len(v_dedup)} unique canonical stacks")
v_dedup.to_csv(OUT / "_v6_dedupe.csv", index=False)

# Load universe again for full-window evaluation
p = pd.read_parquet(OUT / "sol_15m_v6_universe.parquet")
p = p[p['entry_vwap'] < 0.998].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date


def eval_stack_full(df, atoms):
    """Returns (n, wr, pnl_arr, sum_pnl, dd, ls)"""
    mask = np.ones(len(df), dtype=bool)
    for a in atoms:
        col = df[a].values
        if col.dtype == float:
            col = np.where(np.isnan(col), 0, col)
        mask &= (col == 1)
    sub = df[mask].sort_values('fire_us')
    if len(sub) == 0:
        return 0, 0.0, np.array([]), 0.0, 0.0, 0
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0
    cur = 0
    for x in pnl:
        if x < 0:
            cur += 1
            ls_max = max(ls_max, cur)
        else:
            cur = 0
    return len(sub), float(sub['won'].mean()), pnl, float(pnl.sum()), dd, ls_max


def bootstrap_p_lockbox(pnl_arr, dates_arr, n_iter=1000, seed=42):
    """Daily-clustered bootstrap. Tests H0: dpt<=0."""
    if len(pnl_arr) < 5:
        return np.nan
    rng = np.random.default_rng(seed)
    dates = np.array(dates_arr)
    unique_dates = np.unique(dates)
    if len(unique_dates) < 3:
        return np.nan
    obs_dpt = pnl_arr.mean()
    sims = []
    for _ in range(n_iter):
        sample = rng.choice(unique_dates, size=len(unique_dates), replace=True)
        b_pnl = []
        for d in sample:
            b_pnl.extend(pnl_arr[dates == d])
        if len(b_pnl) == 0:
            continue
        sims.append(np.mean(b_pnl))
    sims = np.array(sims)
    # p-value: prob that sim_dpt <= 0
    p_val = (sims <= 0).mean()
    return p_val


# Evaluate dedup'd candidates on FULL window
log("=== Full-window eval + bootstrap ===")
rows = []
# Use top 80 by score_l (limit bootstrap cost)
to_eval = v_dedup.head(80)
for _, r in to_eval.iterrows():
    atoms = r['stack_canon'].split('|')
    # Drop dupe-map atoms not in universe
    atoms_real = [a for a in atoms if a in p.columns]
    if len(atoms_real) < len(atoms):
        continue
    n_f, wr_f, pnl_f, sum_f, dd_f, ls_f = eval_stack_full(p, atoms_real)
    if n_f < 30:
        continue
    dpt_f = sum_f / n_f
    # Now lockbox split for bootstrap
    dates_sorted = sorted(p['date'].unique())
    lock_start = dates_sorted[29]
    p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
    mask_full = np.ones(len(p), dtype=bool)
    for a in atoms_real:
        col = p[a].values
        if col.dtype == float:
            col = np.where(np.isnan(col), 0, col)
        mask_full &= (col == 1)
    sub = p[mask_full].copy().sort_values('fire_us')
    lock_sub = sub[sub['date'] >= lock_start]
    if len(lock_sub) >= 5:
        bp_lock = bootstrap_p_lockbox(lock_sub['pnl_legacy_usd'].values,
                                      lock_sub['date'].values, n_iter=1000)
    else:
        bp_lock = np.nan
    # Bootstrap on full
    if n_f >= 30:
        bp_full = bootstrap_p_lockbox(sub['pnl_legacy_usd'].values,
                                      sub['date'].values, n_iter=1000)
    else:
        bp_full = np.nan
    rows.append({
        'stack_canon': r['stack_canon'],
        'depth': r['depth'],
        'n_f': n_f, 'wr_f': wr_f, 'dpt_f': dpt_f, 'dd_f': dd_f, 'ls_f': ls_f, 'sum_f': sum_f,
        'n_l': r['n_l'], 'wr_l': r['wr_l'], 'dpt_l': r['dpt_l'], 'dd_l': r['dd_l'], 'ls_l': r['ls_l'],
        'bp_lock': bp_lock, 'bp_full': bp_full,
        'score_l': r['score_l'],
        # Sharpe daily (approx): if pnl per fire arr → mean*sqrt(fires_per_day)/std
        'sharpe_f': float(pnl_f.mean() / pnl_f.std() * np.sqrt(33) if pnl_f.std() > 0 else 0),
    })

res = pd.DataFrame(rows).sort_values('score_l', ascending=False)
res.to_csv(OUT / "_v6_full_bootstrap.csv", index=False)
log(f"Full+bootstrap results: {len(res)}")
print(res.head(25)[['stack_canon','depth','n_f','wr_f','dpt_f','dd_f','ls_f','n_l','wr_l','dpt_l','dd_l','ls_l','bp_lock','bp_full','score_l']].to_string(index=False))

log(f"Elapsed: {time.time()-t0:.1f}s")
