"""Refine SOL 15m sniper search: add vwap-aware filters.

KEY INSIGHT from 03: Top candidates have lockbox WR 95%+ but FULL-window negative dpt
because entry_vwap is too high (mean 0.84 for wins). At p=0.84, max win = +0.16 = $4
@ $25 stake, but loss = -$25. Need WR > ~84% just to break even.

Strategy:
- Add filter: entry_vwap in [0.50, 0.85] (the "sweet spot" — small enough for upside, big enough WR base)
- Apply on top of best gate stacks from 03
- Re-validate sniper constraints
- Also produce a "vwap-aware" stack: g_mp_no_extreme + g_tr_stack + others
"""
import os, time, itertools, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m"

log("loading fires")
df = pd.read_parquet(f"{OUT}/sol_15m_fires_v2fix_gates.parquet")
log(f"loaded {len(df):,}")
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
TRAIN_START = pd.Timestamp('2026-04-28', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-05-16', tz='UTC')
VAL_END     = pd.Timestamp('2026-05-22', tz='UTC')
LOCK_END    = pd.Timestamp('2026-05-26', tz='UTC')

# Add direction-aware vwap constraint:
# For UP, entry vwap = ask of UP token. For DOWN, entry vwap = ask of DOWN token.
# Either way, entry_vwap close to 0.5 = small market-implied prob → high upside.
# Filter: 0.45 <= entry_vwap <= 0.80 → reasonable mid-range
df['g_vwap_sweet'] = ((df.entry_vwap >= 0.45) & (df.entry_vwap <= 0.80)).astype(float)
df['g_vwap_low_mid'] = ((df.entry_vwap >= 0.35) & (df.entry_vwap <= 0.65)).astype(float)
df['g_vwap_lt_75'] = (df.entry_vwap <= 0.75).astype(float)
df['g_vwap_lt_70'] = (df.entry_vwap <= 0.70).astype(float)
df['g_vwap_lt_65'] = (df.entry_vwap <= 0.65).astype(float)
df['g_vwap_gt_50'] = (df.entry_vwap >= 0.50).astype(float)
df['g_vwap_gt_55'] = (df.entry_vwap >= 0.55).astype(float)
df['g_vwap_gt_60'] = (df.entry_vwap >= 0.60).astype(float)

def split_masks(d):
    return (
        (d['fire_date'] >= TRAIN_START) & (d['fire_date'] < TRAIN_END),
        (d['fire_date'] >= TRAIN_END)   & (d['fire_date'] < VAL_END),
        (d['fire_date'] >= VAL_END)     & (d['fire_date'] < LOCK_END),
    )

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        m &= (col == 1)
    return m

def compute_metrics(d, gates):
    m = gate_passes(d, gates)
    sub = d[m].sort_values('fire_us').reset_index(drop=True)
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, sum=0.0, max_dd=0.0, loss_streak=0, sharpe=np.nan, n_days=0)
    pnl = sub['pnl_legacy_usd'].values
    wr = sub['won'].mean() * 100
    dpt = pnl.mean()
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = peak - cum
    max_dd = float(dd.max()) if len(dd) else 0.0
    losers = (pnl < 0).astype(int)
    max_run = cur_run = 0
    for v in losers:
        if v == 1:
            cur_run += 1
            if cur_run > max_run: max_run = cur_run
        else:
            cur_run = 0
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    daily = sub.groupby('date')['pnl_legacy_usd'].sum()
    n_days = len(daily)
    if len(daily) > 1 and daily.std() > 0:
        sharpe = (daily.mean() / daily.std()) * np.sqrt(252)
    else:
        sharpe = 0.0
    return dict(n=n, wr=wr, dpt=dpt, sum=float(pnl.sum()),
                max_dd=max_dd, loss_streak=max_run, sharpe=float(sharpe), n_days=n_days)

def bootstrap_p(d, gates, n_iter=1000, seed=42):
    m = gate_passes(d, gates)
    sub = d[m]
    n = len(sub)
    if n < 10: return np.nan
    pnl = sub['pnl_legacy_usd'].values
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n, n)
        means[i] = pnl[idx].mean()
    se = means.std()
    if se == 0: return 0.5
    obs = pnl.mean()
    from math import erf, sqrt
    z = obs / se
    p = 0.5 * (1 - erf(z / sqrt(2)))
    return max(float(p), 1e-4)

# Best base stacks from 03
BASE_STACKS = {
    'TS_RFA': ['g_rf_aged', 'g_tr_stack_full_with'],   # the topper
    'TS_VOLH': ['g_tr_stack_full_with', 'g_vol_high'],
    'LATE_RFA_TS': ['g_rf_aged', 'g_tr_stack_full_with'],  # in late window
    'HURST_TS': ['g_hurst_trending', 'g_tr_stack_full_with'],
    'TS_MARK': ['g_tr_stack_full_with', 'g_markov_with'],
    'TS_TS_STRONG': ['g_tr_stack_full_with', 'g_trend_slope_strong_with'],
    'TS_ALONE': ['g_tr_stack_full_with'],
    'RFA_ALONE': ['g_rf_aged'],
}
VWAP_FILTERS = ['none', 'g_vwap_sweet', 'g_vwap_low_mid', 'g_vwap_lt_75', 'g_vwap_lt_70', 'g_vwap_lt_65',
                'g_vwap_gt_50', 'g_vwap_gt_55']
OFFSET_FILTERS = ['none', 'fire_offset_s <= 240', 'fire_offset_s >= 240 and fire_offset_s <= 480',
                  'fire_offset_s >= 480']

results = []
for base_name, base in BASE_STACKS.items():
    for vfilt in VWAP_FILTERS:
        for off_filt_name in ['all', '60-240', '240-480', '480-840', 'late_480plus', 'late_360plus']:
            d = df.copy()
            if off_filt_name == '60-240':
                d = d[d.fire_offset_s <= 240]
            elif off_filt_name == '240-480':
                d = d[(d.fire_offset_s > 240) & (d.fire_offset_s <= 480)]
            elif off_filt_name == '480-840':
                d = d[d.fire_offset_s > 480]
            elif off_filt_name == 'late_480plus':
                d = d[d.fire_offset_s >= 480]
            elif off_filt_name == 'late_360plus':
                d = d[d.fire_offset_s >= 360]
            if vfilt == 'none':
                gates = list(base)
            else:
                gates = list(base) + [vfilt]
            sleeve = f"{base_name}_OFF[{off_filt_name}]_VWAP[{vfilt}]"
            full = compute_metrics(d, gates)
            if full['n'] < 50 or full['n'] > 500: continue
            m_tr, m_va, m_lo = split_masks(d)
            mt_tr = compute_metrics(d[m_tr], gates)
            mt_va = compute_metrics(d[m_va], gates)
            mt_lo = compute_metrics(d[m_lo], gates)
            bp_lo = bootstrap_p(d[m_lo], gates) if mt_lo['n'] >= 10 else np.nan
            bp_fu = bootstrap_p(d, gates)
            r = dict(
                sleeve_id=sleeve, anchor=f"offset_{off_filt_name}",
                gate_stack='&'.join(gates), depth=len(gates),
                offset_filter=off_filt_name,
                n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
                wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
                dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
                sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
                max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
                loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
                sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
                n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
                bootstrap_p_lockbox=bp_lo, bootstrap_p_full=bp_fu,
            )
            results.append(r)

res_df = pd.DataFrame(results).drop_duplicates(subset=['gate_stack','offset_filter'])
res_df.to_csv(f"{OUT}/all_candidates_v4_vwap_aware.csv", index=False)
log(f"WROTE all_candidates_v4_vwap_aware.csv ({len(res_df)} rows)")

# Sniper filter — REQUIRE positive full-window dpt
def passes_sniper(r):
    if r['n_lockbox'] < 5: return False
    if r['n_full'] > 500: return False
    n_per_32d = r['n_full'] * (32.0/28.0)
    if n_per_32d < 50: return False
    if r['wr_lockbox'] < 75: return False
    if r['dpt_25'] < 3: return False
    if r['max_dd_25'] > 300: return False
    if r['loss_streak'] > 6: return False
    if r['sharpe'] < 2: return False
    if pd.isna(r['bootstrap_p_lockbox']) or r['bootstrap_p_lockbox'] > 0.05: return False
    # Extra: require full-window dpt > 0 (don't be lockbox-lucky)
    if r['dpt_full'] <= 0: return False
    if r['loss_streak_full'] > 8: return False
    return True

res_df['pass_sniper'] = res_df.apply(passes_sniper, axis=1)
sniper = res_df[res_df.pass_sniper].sort_values('dpt_full', ascending=False)
log(f"SNIPER (with vwap-aware + full-window positive dpt): {len(sniper)}")
for _, r in sniper.head(20).iterrows():
    log(f"  {r['sleeve_id']:80} lock n={r['n_lockbox']:3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f}  full n={r['n_full']:3} WR={r['wr_full']:5.1f}% dpt=${r['dpt_full']:+.2f} dd={r['max_dd_full']:.0f}")

# Top 5
if len(sniper):
    top5 = sniper.head(5)
else:
    # Fall back to sniper_score
    def score(r):
        s = 0
        if r['wr_lockbox'] >= 75: s += 1
        if r['dpt_25'] >= 3: s += 1
        if r['max_dd_25'] <= 300: s += 1
        if r['loss_streak'] <= 6: s += 1
        if r['sharpe'] >= 2: s += 1
        if r['n_lockbox'] >= 5 and r['n_full'] <= 500: s += 1
        if pd.notna(r['bootstrap_p_lockbox']) and r['bootstrap_p_lockbox'] <= 0.05: s += 1
        if r['dpt_full'] > 0: s += 1
        if r['wr_full'] >= 70: s += 1
        return s
    res_df['sniper_score'] = res_df.apply(score, axis=1)
    top5 = res_df.sort_values(['sniper_score','dpt_full'], ascending=[False,False]).head(5)
top5.to_csv(f"{OUT}/top_5_candidates.csv", index=False)
log(f"WROTE top_5_candidates.csv ({len(top5)})")
log("DONE")
