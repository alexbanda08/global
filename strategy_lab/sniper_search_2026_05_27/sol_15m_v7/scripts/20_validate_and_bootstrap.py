"""Stage 2: Stability + bootstrap validation for V7 top candidates.

Add columns:
- All-splits dpt + WR (require not-negative across all 3)
- Bootstrap p on lockbox (1000 iterations, daily-clustered)
- 28d projected PnL (full window const $25)
- Train→val→lockbox monotonicity sanity

Filter to V7 publishable candidates.
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v7"
STAKE = 25.0

log("loading V7 universe + full search")
df = pd.read_parquet(f"{OUT}/sol_15m_v7_universe.parquet").sort_values('fire_us').reset_index(drop=True)
df['fire_dt'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
shares = STAKE / df['entry_vwap']
df['pnl25'] = np.where(df['won']==1, (1 - df['entry_vwap']) * shares * 0.98, -df['entry_vwap'] * shares)

dt_min, dt_max = df['fire_dt'].min(), df['fire_dt'].max()
total_days = (dt_max - dt_min).total_seconds() / 86400
train_end = dt_min + pd.Timedelta(days=int(total_days*0.6))
val_end = dt_min + pd.Timedelta(days=int(total_days*0.8))
df['split'] = pd.cut(df['fire_dt'], bins=[dt_min - pd.Timedelta(seconds=1), train_end, val_end, dt_max + pd.Timedelta(seconds=1)],
                     labels=['train','val','lockbox'])
log(f"split sizes: {df['split'].value_counts().to_dict()}")
log(f"lockbox window: {val_end} -> {dt_max} (~{(dt_max-val_end).total_seconds()/86400:.1f}d)")

# Parse candidate sleeves from full search
search = pd.read_csv(f"{OUT}/_v7_full_search.csv")
log(f"loaded {len(search)} candidates")

V6_BASE = ['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with']
V6_VWAP = 0.80

def parse_sleeve(name):
    """Return (gates, vwap_filter) from sleeve name."""
    vwap = None
    nohod = name.startswith("NOHOD_")
    if "_vwap_lt80" in name:
        vwap = 0.80
    if "_no_vwap" in name:
        vwap = None
    if name.startswith("V6_BASE_"):
        return list(V6_BASE), 0.80
    if nohod:
        # NOHOD_<gate>
        g = name[len("NOHOD_"):]
        for suf in ['_vwap_lt80','_no_vwap']:
            if g.endswith(suf): g = g[:-len(suf)]
        return ['g_off_60_240','g_rf_with','g_tr_stack_with', g], (vwap if vwap is not None else 0.80)
    if name.startswith("V6+"):
        rest = name[len("V6+"):]
        for suf in ['_vwap_lt80','_no_vwap']:
            if rest.endswith(suf): rest = rest[:-len(suf)]
        adds = rest.split("+")
        return V6_BASE + adds, (vwap if vwap is not None else V6_VWAP)
    if name.startswith("ENSEMBLE_"):
        # Special: ENSEMBLE_norm<thr>_<optional vol gate>_vwap_lt80
        return None, None  # handle separately
    return None, None

def gate_mask_for(stack):
    m = pd.Series(True, index=df.index)
    for g in stack:
        if g not in df.columns:
            return pd.Series(False, index=df.index)
        v = df[g].fillna(0).astype(float)
        m = m & (v >= 0.5)
    return m

def evaluate_full(mask, label):
    sub = df[mask].copy().sort_values('fire_us').reset_index(drop=True)
    if len(sub) < 5:
        return None
    out = {'sleeve': label, 'n_total': len(sub)}
    for s in ['train','val','lockbox']:
        ss = sub[sub['split']==s]
        out[f'n_{s}'] = len(ss)
        out[f'wr_{s}'] = ss['won'].mean() if len(ss) else np.nan
        out[f'dpt_{s}'] = ss['pnl25'].mean() if len(ss) else np.nan
        out[f'sum_{s}'] = ss['pnl25'].sum()
    # Full-window
    out['wr_full'] = sub['won'].mean()
    out['dpt_full'] = sub['pnl25'].mean()
    out['sum_full'] = sub['pnl25'].sum()
    # DD + loss streak — lockbox AND full
    for slab, sub_slab in [('lockbox', sub[sub['split']=='lockbox']), ('full', sub)]:
        sub_slab = sub_slab.sort_values('fire_us')
        cum = sub_slab['pnl25'].cumsum().values if len(sub_slab) else np.array([0])
        out[f'dd_{slab}'] = (np.maximum.accumulate(cum) - cum).max() if len(cum) else 0
        losses = (sub_slab['won']==0).astype(int).values if len(sub_slab) else np.array([0])
        ms, cur = 0, 0
        for x in losses:
            if x == 1: cur += 1; ms = max(ms, cur)
            else: cur = 0
        out[f'loss_streak_{slab}'] = ms
    # Sharpe (daily approx) lockbox
    lb = sub[sub['split']=='lockbox']
    if len(lb) > 1:
        per_day = lb.groupby(lb['fire_dt'].dt.date)['pnl25'].sum()
        out['sharpe_lockbox'] = (per_day.mean() / per_day.std() * np.sqrt(252)) if per_day.std() > 0 else 0
    else:
        out['sharpe_lockbox'] = 0
    return out, sub

def bootstrap_p(sub_lockbox, n_iter=1000, seed=42):
    """Daily-clustered bootstrap: resample DAYS with replacement, compute mean dpt; p = P(mean<=0)."""
    rng = np.random.default_rng(seed)
    if len(sub_lockbox) == 0: return 1.0
    sub = sub_lockbox.copy()
    sub['day'] = sub['fire_dt'].dt.date
    days = sub['day'].unique()
    if len(days) < 2:
        return 1.0
    means = []
    day_groups = {d: sub[sub['day']==d]['pnl25'].values for d in days}
    for _ in range(n_iter):
        picks = rng.choice(days, size=len(days), replace=True)
        sample = np.concatenate([day_groups[d] for d in picks])
        means.append(sample.mean())
    means = np.array(means)
    return float((means <= 0).mean())

# Score top 30 by composite
search['composite'] = search['dpt_lockbox'] * np.sqrt(search['n_lockbox'].clip(lower=0))
candidates = search[(search['n_lockbox'] >= 15) & (search['dpt_lockbox'] >= 4.0)].sort_values('composite', ascending=False).head(40)
log(f"validating top {len(candidates)} candidates")

validated = []
sleeve_data = {}
for _, row in candidates.iterrows():
    name = row['sleeve']
    parsed = parse_sleeve(name)
    if parsed[0] is None:
        log(f"  skip {name} (unparseable)")
        continue
    stack, vwap = parsed
    m = gate_mask_for(stack)
    if vwap is not None:
        m = m & (df['entry_vwap'] < vwap)
    res = evaluate_full(m, name)
    if res is None:
        continue
    rec, sub = res
    # Bootstrap p on lockbox
    lb = sub[sub['split']=='lockbox']
    rec['bootstrap_p_lockbox'] = bootstrap_p(lb, n_iter=1000)
    # Bootstrap p on full
    rec['bootstrap_p_full'] = bootstrap_p(sub, n_iter=1000)
    # Train+val+lockbox monotonicity check
    dpts = [rec.get(f'dpt_{s}') for s in ['train','val','lockbox'] if rec.get(f'n_{s}',0) >= 5]
    rec['min_split_dpt'] = min(dpts) if dpts else np.nan
    rec['stable_3split'] = all(d > 0 for d in dpts) if dpts else False
    validated.append(rec)
    sleeve_data[name] = sub

vdf = pd.DataFrame(validated)
vdf = vdf.sort_values(['stable_3split','composite' if 'composite' in vdf.columns else 'dpt_lockbox'], ascending=[False, False])

# Add composite as col for sort
vdf['composite'] = vdf['dpt_lockbox'] * np.sqrt(vdf['n_lockbox'].clip(lower=0))

# 28d projection from full sum scaled to 28 days
days_full = (dt_max - dt_min).total_seconds() / 86400
vdf['proj_28d_const25'] = vdf['sum_full'] * (28.0 / days_full)

vdf.to_csv(f"{OUT}/_v7_validated.csv", index=False)
log(f"WROTE _v7_validated.csv ({len(vdf)} rows)")

# Pick "Top 5" — stable AND profile-pass
stable = vdf[vdf['stable_3split']==True].copy()
stable = stable[(stable['wr_lockbox'] >= 0.65) & (stable['dpt_lockbox'] >= 4.0) &
                (stable['dd_lockbox'] <= 500) & (stable['loss_streak_lockbox'] <= 14) &
                (stable['bootstrap_p_lockbox'] <= 0.05)]
stable = stable.sort_values('composite', ascending=False)
log(f"V7 profile + stable + bootstrap: {len(stable)} candidates")

if len(stable) > 0:
    print("\n=== STABLE TOP CANDIDATES (V7 profile + train/val/lockbox positive + bootstrap p<=0.05) ===")
    print(stable[['sleeve','n_train','n_val','n_lockbox','wr_train','wr_val','wr_lockbox',
                  'dpt_train','dpt_val','dpt_lockbox','dd_lockbox','loss_streak_lockbox',
                  'bootstrap_p_lockbox','sharpe_lockbox','proj_28d_const25']].head(10).to_string())

# Always keep top 5 by composite for the report (even if stable filter empty)
print("\n=== TOP 10 by composite (all validated) ===")
print(vdf.head(15)[['sleeve','n_train','n_val','n_lockbox','wr_train','wr_val','wr_lockbox',
                    'dpt_train','dpt_val','dpt_lockbox','dd_lockbox','loss_streak_lockbox',
                    'bootstrap_p_lockbox','stable_3split','proj_28d_const25']].to_string())

# Save sleeve detail data for plotting
top5 = vdf.head(10)
top5.to_csv(f"{OUT}/_v7_top10_for_report.csv", index=False)
import pickle
pickle.dump({n: sleeve_data[n] for n in top5['sleeve'] if n in sleeve_data}, open(f"{OUT}/_v7_top_sleeves.pkl",'wb'))
log("WROTE top10 + sleeve_data pickle")

log("DONE")
