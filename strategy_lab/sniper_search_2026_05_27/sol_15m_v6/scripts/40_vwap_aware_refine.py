"""V6 SOL 15m: vwap-aware refinement on top candidates.

Observation: Q1_low_vwap (vwap<0.55) consistently gives $5-7/tr (best $/tr),
while Q4_high_vwap (>0.83) gives ~$0/tr despite high WR (lottery-ticket dynamic).
Add vwap-filter to top sleeves to lift $/tr.

Goal: get $/tr_lock >= $4 on constant $25 stake.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_15m_v6")
PLOTS = OUT / "plots"
PLOTS.mkdir(exist_ok=True)
t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

p = pd.read_parquet(OUT / "sol_15m_v6_universe.parquet")
p = p[p['entry_vwap'] < 0.998].copy()
p['date'] = pd.to_datetime(p['fire_us'], unit='us').dt.date
dates_sorted = sorted(p['date'].unique())
train_end = dates_sorted[22]
val_end = dates_sorted[29]
lock_start = val_end


def eval_stack(df, atoms, extra_filter=None):
    mask = np.ones(len(df), dtype=bool)
    for a in atoms:
        col = df[a].values
        if col.dtype == float:
            col = np.where(np.isnan(col), 0, col)
        mask &= (col == 1)
    sub = df[mask]
    if extra_filter is not None:
        sub = sub[extra_filter(sub)]
    if len(sub) == 0:
        return None
    sub = sub.sort_values('fire_us')
    pnl = sub['pnl_legacy_usd'].values
    cumsum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cumsum) - cumsum))
    ls_max = 0; cur = 0
    for v in pnl:
        if v < 0:
            cur += 1
            ls_max = max(ls_max, cur)
        else:
            cur = 0
    return {'n':len(sub), 'wr':float(sub['won'].mean()), 'dpt':float(pnl.mean()),
            'sum':float(pnl.sum()), 'dd':dd, 'ls':ls_max, 'pnl':pnl,
            'sub': sub}


def bootstrap_p(pnl_arr, dates_arr, n_iter=1000, seed=42):
    if len(pnl_arr) < 5: return np.nan
    rng = np.random.default_rng(seed)
    dates = np.array(dates_arr)
    unique_dates = np.unique(dates)
    if len(unique_dates) < 3: return np.nan
    sims = []
    for _ in range(n_iter):
        sample = rng.choice(unique_dates, size=len(unique_dates), replace=True)
        b_pnl = []
        for d in sample:
            b_pnl.extend(pnl_arr[dates == d])
        if len(b_pnl) == 0: continue
        sims.append(np.mean(b_pnl))
    return (np.array(sims) <= 0).mean()


# Test sleeves with various vwap filters
SLEEVES = [
    {'id':'C1_HOD_EU_OFF60_240', 'stack':['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with']},
    {'id':'C2_OFF60_RFA_HOD',    'stack':['g_hod_european_morning','g_off_60','g_tr_stack_with','g_tr_within_adr']},
    {'id':'C3_HOD_TIGHTRIB',     'stack':['g_hod_european_morning','g_rf_with','g_tight_ribbon','g_tr_stack_with']},
    {'id':'C4_HOD_BBPOS',        'stack':['g_bb_pos_with','g_hod_european_morning','g_rf_with','g_tr_stack_with']},
    {'id':'C5_VOL_ADR_TS',       'stack':['g_tr_stack_with','g_tr_within_adr','g_vol_high']},
    {'id':'C6_TR_S_VWAP',        'stack':['g_tr_stack_with','g_rf_with','g_ribbon_slope_with']},  # broader
]
VWAP_BANDS = [
    ('none',          lambda s: pd.Series([True]*len(s), index=s.index)),
    ('lt_55',         lambda s: s['entry_vwap'] < 0.55),
    ('lt_65',         lambda s: s['entry_vwap'] < 0.65),
    ('lt_75',         lambda s: s['entry_vwap'] < 0.75),
    ('lt_80',         lambda s: s['entry_vwap'] < 0.80),
    ('15_55',         lambda s: (s['entry_vwap'] >= 0.15) & (s['entry_vwap'] < 0.55)),
    ('20_65',         lambda s: (s['entry_vwap'] >= 0.20) & (s['entry_vwap'] < 0.65)),
    ('10_45',         lambda s: (s['entry_vwap'] >= 0.10) & (s['entry_vwap'] < 0.45)),
    ('30_70',         lambda s: (s['entry_vwap'] >= 0.30) & (s['entry_vwap'] < 0.70)),
]

results = []
for sleeve in SLEEVES:
    log(f"=== {sleeve['id']}: {' & '.join(sleeve['stack'])} ===")
    for vname, vfn in VWAP_BANDS:
        # Apply to each window
        train_df = p[p['date'] < train_end]
        val_df   = p[(p['date'] >= train_end) & (p['date'] < val_end)]
        lock_df  = p[p['date'] >= lock_start]
        tr = eval_stack(train_df, sleeve['stack'], vfn)
        if tr is None or tr['n'] < 30: continue
        vl = eval_stack(val_df,   sleeve['stack'], vfn) or dict(n=0,wr=0,dpt=0,sum=0,dd=0,ls=0,pnl=np.array([]))
        lk = eval_stack(lock_df,  sleeve['stack'], vfn) or dict(n=0,wr=0,dpt=0,sum=0,dd=0,ls=0,pnl=np.array([]))
        fu = eval_stack(p,         sleeve['stack'], vfn)
        if fu is None: continue
        # Bootstrap on lock
        if lk['n'] >= 5:
            sub_l = lk['sub'] if 'sub' in lk else None
            if sub_l is not None:
                bp_l = bootstrap_p(lk['pnl'], sub_l['date'].values, n_iter=500)
            else:
                bp_l = np.nan
        else:
            bp_l = np.nan
        # Bootstrap on full
        bp_f = bootstrap_p(fu['pnl'], fu['sub']['date'].values, n_iter=500)
        results.append({
            'sleeve': sleeve['id'], 'stack': '|'.join(sleeve['stack']), 'vwap_filter': vname,
            'n_tr': tr['n'], 'wr_tr': tr['wr'], 'dpt_tr': tr['dpt'],
            'n_v': vl['n'], 'wr_v': vl['wr'], 'dpt_v': vl['dpt'],
            'n_l': lk['n'], 'wr_l': lk['wr'], 'dpt_l': lk['dpt'], 'dd_l': lk['dd'], 'ls_l': lk['ls'],
            'n_f': fu['n'], 'wr_f': fu['wr'], 'dpt_f': fu['dpt'], 'dd_f': fu['dd'], 'ls_f': fu['ls'],
            'sum_l': lk['sum'], 'sum_f': fu['sum'],
            'bp_l': bp_l, 'bp_f': bp_f,
            'score_l': lk['dpt'] * np.sqrt(lk['n']) if lk['dpt'] > 0 else 0,
            'score_f': fu['dpt'] * np.sqrt(fu['n']) if fu['dpt'] > 0 else 0,
        })

df = pd.DataFrame(results)
df = df.sort_values('score_f', ascending=False).reset_index(drop=True)
df.to_csv(OUT / "_v6_vwap_aware_refine.csv", index=False)
log(f"All variants: {len(df)}")

# Filter to V6 strict (lockbox)
strict = df[
    (df['n_l'] >= 20) & (df['n_l'] <= 2000) &
    (df['wr_l'] >= 0.65) & (df['dpt_l'] >= 4.0) &
    (df['dd_l'] <= 500) & (df['ls_l'] <= 14) & (df['bp_l'] <= 0.05)
].copy()
log(f"V6 STRICT pass (lockbox $/tr>=$4, WR>=65, bp<=0.05): {len(strict)}")
print(strict[['sleeve','stack','vwap_filter','n_l','wr_l','dpt_l','dd_l','ls_l','bp_l','n_f','wr_f','dpt_f','bp_f','score_f']].to_string(index=False))

# Try medium pass (lockbox $/tr >= $3)
medium = df[
    (df['n_l'] >= 20) & (df['n_l'] <= 2000) &
    (df['wr_l'] >= 0.65) & (df['dpt_l'] >= 3.0) &
    (df['dd_l'] <= 500) & (df['ls_l'] <= 14) & (df['bp_l'] <= 0.05)
].copy()
log(f"V6 MEDIUM pass (lockbox $/tr>=$3): {len(medium)}")
print(medium[['sleeve','stack','vwap_filter','n_l','wr_l','dpt_l','dd_l','ls_l','bp_l','n_f','wr_f','dpt_f','bp_f','score_f']].to_string(index=False))

# Also: V6 with $/tr_full >= $4 (more believable than lockbox-only)
strict_full = df[
    (df['n_f'] >= 80) &
    (df['wr_f'] >= 0.70) & (df['dpt_f'] >= 4.0) &
    (df['dd_f'] <= 500) & (df['ls_f'] <= 14) & (df['bp_f'] <= 0.05)
].copy()
log(f"V6 STRICT FULL-WINDOW pass ($/tr_full>=$4, n_f>=80): {len(strict_full)}")
print(strict_full[['sleeve','stack','vwap_filter','n_f','wr_f','dpt_f','dd_f','ls_f','bp_f','n_l','wr_l','dpt_l','bp_l','score_f']].to_string(index=False))
strict_full.to_csv(OUT / "_v6_strict_full.csv", index=False)

# Best per sleeve (one row per sleeve, best vwap_filter)
best_per_sleeve = df.sort_values('score_f', ascending=False).drop_duplicates('sleeve', keep='first').reset_index(drop=True)
log(f"\nBest per sleeve (top by score_f):")
print(best_per_sleeve[['sleeve','stack','vwap_filter','n_f','wr_f','dpt_f','dd_f','ls_f','bp_f','n_l','wr_l','dpt_l','bp_l']].to_string(index=False))

log(f"\nTop 25 overall by score_f:")
print(df.head(25)[['sleeve','vwap_filter','n_f','wr_f','dpt_f','dd_f','ls_f','bp_f','n_l','wr_l','dpt_l','bp_l']].to_string(index=False))

log(f"Elapsed: {time.time()-t0:.1f}s")
