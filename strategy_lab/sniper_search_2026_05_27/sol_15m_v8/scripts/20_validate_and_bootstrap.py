"""V8 SOL 15m validation: stability + bootstrap p-value.

For each candidate from _v8_top_composite + _v8_profile_pass:
- Bootstrap p on lockbox (daily-block, 1000 resamples)
- Stability check: train, val, lockbox $/tr signs
- Re-eval with proj_32d / proj_full / proj_honest per V8 brief
"""
import os, time, warnings, pickle
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v8"
STAKE = 25.0

log("loading V8 universe")
df = pd.read_parquet(f"{OUT}/sol_15m_v8_universe.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
shares = STAKE / df['entry_vwap']
df['pnl25'] = np.where(df['won']==1,
                       (1 - df['entry_vwap']) * shares * 0.98,
                       -df['entry_vwap'] * shares)
df['fire_dt'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
total_days = (df['fire_dt'].max() - df['fire_dt'].min()).total_seconds() / 86400
train_end = df['fire_dt'].min() + pd.Timedelta(days=int(total_days*0.6))
val_end   = df['fire_dt'].min() + pd.Timedelta(days=int(total_days*0.8))
df['split'] = pd.cut(df['fire_dt'],
    bins=[df['fire_dt'].min()-pd.Timedelta(seconds=1), train_end, val_end, df['fire_dt'].max()+pd.Timedelta(seconds=1)],
    labels=['train','val','lockbox'])

# Days per split
days_per_split = {}
for s in ['train','val','lockbox']:
    sub = df[df['split']==s]
    days_per_split[s] = (sub['fire_dt'].max() - sub['fire_dt'].min()).total_seconds() / 86400 if len(sub)>0 else 0
log(f"days_per_split: {days_per_split}, total={total_days:.2f}")

# Load top composite & profile pass
top_comp = pd.read_csv(f"{OUT}/_v8_top_composite.csv")
prof = pd.read_csv(f"{OUT}/_v8_profile_pass.csv")
candidates = pd.concat([top_comp, prof], ignore_index=True).drop_duplicates('sleeve', keep='first')
log(f"candidates to validate: {len(candidates)}")

# Define candidate sleeves by gate stack (we need to reconstruct from the sleeve label since
# original stacks weren't saved). We'll re-search to find masks for each by parsing labels.

V6_BASE = ['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with']
V6_NO_HOD = ['g_off_60_240','g_rf_with','g_tr_stack_with']
V6_VWAP = 0.80

V7_BASES = {
    'S5_SLOPE_STR': V6_BASE + ['g_BTC_slope_with','g_BTC_slope_strong_with'],
    'S1_ADX_VOLLOW': V6_BASE + ['g_BTC_tr_stack_with','g_BTC_adx_strong','g_BTC_vol_low'],
    'S3_XADX_ETHVOLLOW': V6_BASE + ['g_BTC_adx_strong','g_ETH_adx_strong','g_ETH_vol_low'],
    'S1': V6_BASE + ['g_BTC_tr_stack_with','g_BTC_adx_strong','g_BTC_vol_low'],
    'S3': V6_BASE + ['g_BTC_adx_strong','g_ETH_adx_strong','g_ETH_vol_low'],
}

def parse_label(label):
    """Return list of gates from a sleeve label."""
    stack = list(V6_BASE)
    if label == 'V6_BASE':
        return list(V6_BASE)
    if label.startswith('V7_BASE_'):
        name = label.replace('V7_BASE_', '')
        return list(V7_BASES[name])
    if label.startswith('V7_'):
        # Check for _TOD_ pattern: V7_{NAME}_TOD_{bucket}
        if '_TOD_' in label:
            parts = label.split('_TOD_')
            name_part = parts[0].replace('V7_', '')
            bucket = parts[1]
            base = list(V7_BASES.get(name_part, V6_BASE))
            base = [g for g in base if g != 'g_hod_european_morning']
            base.append(f'g_K_tod_{bucket}')
            return base
        # Otherwise: V7_{NAME}+{g}+{g}...
        parts = label.split('+')
        name_part = parts[0].replace('V7_', '')
        base = list(V7_BASES.get(name_part, V6_BASE))
        for p in parts[1:]:
            base.append(p)
        return base
    if label.startswith('V7_S5_NO_HOD_'):
        bucket = label.replace('V7_S5_NO_HOD_', '')
        base = [g for g in V7_BASES['S5_SLOPE_STR'] if g != 'g_hod_european_morning']
        base.append(f'g_K_{bucket}')
        return base
    if label.startswith('V6_NO_HOD_TOD_'):
        bucket = label.replace('V6_NO_HOD_TOD_', '')
        return list(V6_NO_HOD) + [f'g_K_tod_{bucket}']
    if label.startswith('V6+'):
        gates = label[3:].split('+')
        return list(V6_BASE) + gates
    if label.startswith('PURE_'):
        return [label.replace('PURE_', '')]
    if label.startswith('MIN_RF_TRS+'):
        g = label.replace('MIN_RF_TRS+', '')
        return ['g_rf_with', 'g_tr_stack_with', g]
    if label.startswith('NOHOD_'):
        g = label.replace('NOHOD_', '')
        return ['g_off_60_240','g_rf_with','g_tr_stack_with', g]
    if label.startswith('HL_'):
        # Not validated here
        return None
    return None

def gate_mask(stack, df=df, extra_vwap_lt=V6_VWAP):
    m = pd.Series(True, index=df.index)
    for g in stack:
        if g not in df.columns:
            return pd.Series(False, index=df.index)
        v = df[g].fillna(0).astype(float)
        m = m & (v >= 0.5)
    if extra_vwap_lt is not None:
        m = m & (df['entry_vwap'] < extra_vwap_lt)
    return m

def bootstrap_p_daily(pnl_series, dt_series, B=1000, rng_seed=42):
    """Daily-block bootstrap test for mean > 0 on PnL.
       Resample days (with replacement), compute mean per resample, return p(mean<=0)."""
    if len(pnl_series) < 5:
        return 1.0
    rng = np.random.default_rng(rng_seed)
    by_day = pd.DataFrame({'pnl': pnl_series, 'day': dt_series.dt.date.values})
    days = by_day['day'].unique()
    means = np.zeros(B)
    for i in range(B):
        sampled = rng.choice(days, size=len(days), replace=True)
        ms = []
        for d in sampled:
            ms.extend(by_day[by_day['day']==d]['pnl'].values)
        means[i] = np.mean(ms) if len(ms) > 0 else 0
    return float((means <= 0).mean())

# Filter candidates: must parse; lockbox n>=15 already filtered in _v8_top_composite
results = []
for _, row in candidates.iterrows():
    label = row['sleeve']
    stack = parse_label(label)
    if stack is None:
        continue
    mask = gate_mask(stack, extra_vwap_lt=V6_VWAP)
    sub = df[mask].copy()
    if len(sub) < 5:
        continue
    out = {'sleeve': label, 'gates': '+'.join(stack)}
    for s in ['train','val','lockbox']:
        ss = sub[sub['split']==s]
        out[f'n_{s}'] = len(ss)
        out[f'wr_{s}'] = ss['won'].mean() if len(ss)>0 else 0
        out[f'dpt_25_{s}'] = ss['pnl25'].mean() if len(ss)>0 else 0
        out[f'sum_{s}'] = ss['pnl25'].sum() if len(ss)>0 else 0
    out['n_full'] = len(sub)
    out['wr_full'] = sub['won'].mean()
    out['dpt_25_full'] = sub['pnl25'].mean()
    out['sum_full'] = sub['pnl25'].sum()

    lb = sub[sub['split']=='lockbox'].sort_values('fire_us')
    cum = lb['pnl25'].cumsum().values if len(lb)>0 else np.array([0])
    out['max_dd_25'] = (np.maximum.accumulate(cum) - cum).max() if len(cum)>0 else 0
    losses = (lb['won']==0).astype(int).values if len(lb)>0 else np.array([0])
    ms, cur = 0, 0
    for x in losses:
        if x==1: cur+=1; ms = max(ms, cur)
        else: cur=0
    out['loss_streak'] = ms
    # Sharpe lockbox
    if len(lb) > 1:
        per_day = lb.groupby(lb['fire_dt'].dt.date)['pnl25'].sum()
        out['sharpe'] = per_day.mean() / per_day.std() * np.sqrt(252) if per_day.std() > 0 else 0
    else:
        out['sharpe'] = 0
    # Bootstrap p on lockbox
    if len(lb) > 5:
        out['bootstrap_p_lockbox'] = bootstrap_p_daily(lb['pnl25'].values, lb['fire_dt'], B=1000)
    else:
        out['bootstrap_p_lockbox'] = 1.0
    # Projections
    # proj_32d  = $/tr_lockbox * (n_lockbox / days_lockbox) * 32.66
    n_lock = out['n_lockbox']
    n_full = out['n_full']
    d_lock = days_per_split['lockbox']
    out['proj_32d'] = out['dpt_25_lockbox'] * (n_lock / d_lock) * 32.66 if d_lock > 0 else 0
    out['proj_full'] = out['dpt_25_full'] * (n_full / total_days) * 32.66
    out['proj_honest'] = min(out['proj_32d'], out['proj_full'])
    results.append(out)

rdf = pd.DataFrame(results)
rdf = rdf.sort_values('proj_honest', ascending=False)
rdf.to_csv(f"{OUT}/_v8_validated.csv", index=False)
log(f"WROTE _v8_validated.csv ({len(rdf)} rows)")

# Apply v8 profile + bootstrap p filter
def hard_profile(r):
    return (r['n_lockbox'] >= 15 and r['max_dd_25'] <= 500 and r['loss_streak'] <= 14
            and r['n_full'] >= 30
            and ((r['wr_lockbox'] >= 0.65) or (r['wr_lockbox'] >= 0.55 and r['dpt_25_lockbox'] >= 10.0))
            and r['bootstrap_p_lockbox'] <= 0.05
            and r['dpt_25_lockbox'] >= 4.0
            and r['dpt_25_train'] > 0 and r['dpt_25_val'] > 0)
filt = rdf[rdf.apply(hard_profile, axis=1)].copy()
filt = filt.sort_values('proj_honest', ascending=False)
filt.to_csv(f"{OUT}/_v8_validated_hard.csv", index=False)
log(f"V8 hard-profile + bootstrap: {len(filt)} candidates")

# Top by proj_honest with stability
print("\n=== TOP 15 V8 by proj_honest (validated) ===")
top = rdf.head(15)
print(top[['sleeve','n_train','n_val','n_lockbox','n_full','wr_train','wr_val','wr_lockbox','wr_full',
           'dpt_25_train','dpt_25_val','dpt_25_lockbox','dpt_25_full','max_dd_25','loss_streak',
           'bootstrap_p_lockbox','proj_32d','proj_full','proj_honest']].to_string())

print("\n=== TOP 10 HARD-PROFILE PASSERS ===")
print(filt.head(10)[['sleeve','n_lockbox','wr_lockbox','dpt_25_lockbox','wr_full','dpt_25_full',
                     'max_dd_25','loss_streak','bootstrap_p_lockbox','proj_32d','proj_full','proj_honest']].to_string())

log("DONE")
