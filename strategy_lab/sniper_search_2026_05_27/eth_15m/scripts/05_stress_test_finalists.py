"""Stress-test the top finalists and explore robustness.

Goals:
  1. Deduplicate identical stacks
  2. Add ablation: drop each gate one at a time, see which gates carry the alpha
  3. Test stack on FULL 33d window (using days where ALL gates are computable)
  4. Check slug-overlap with broader gate-eliminated versions
  5. Build truly DIVERSE top-5 (different cohorts/anchors/gate atoms)

Also explore:
  - g_offset_early (0-60s) seems to be doing the heavy lifting
  - g_tr_stack_full_with is rare (16% on-rate) — important to check stability
  - g_above_1h_dailyvwap_with is 50% on-rate (informative baseline)
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m"

df = pd.read_parquet(f"{OUT}/eth_15m_enriched.parquet")
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)

SPLITS = {
    '33D': dict(
        train=(pd.Timestamp('2026-04-24', tz='UTC'), pd.Timestamp('2026-05-15', tz='UTC')),
        val  =(pd.Timestamp('2026-05-15', tz='UTC'), pd.Timestamp('2026-05-22', tz='UTC')),
        lock =(pd.Timestamp('2026-05-22', tz='UTC'), pd.Timestamp('2026-05-26', tz='UTC')),
    ),
    '31D': dict(
        train=(pd.Timestamp('2026-04-24', tz='UTC'), pd.Timestamp('2026-05-15', tz='UTC')),
        val  =(pd.Timestamp('2026-05-15', tz='UTC'), pd.Timestamp('2026-05-21', tz='UTC')),
        lock =(pd.Timestamp('2026-05-21', tz='UTC'), pd.Timestamp('2026-05-25', tz='UTC')),
    ),
    '28D': dict(
        train=(pd.Timestamp('2026-04-28', tz='UTC'), pd.Timestamp('2026-05-14', tz='UTC')),
        val  =(pd.Timestamp('2026-05-14', tz='UTC'), pd.Timestamp('2026-05-20', tz='UTC')),
        lock =(pd.Timestamp('2026-05-20', tz='UTC'), pd.Timestamp('2026-05-25', tz='UTC')),
    ),
    '22D': dict(
        train=(pd.Timestamp('2026-05-01', tz='UTC'), pd.Timestamp('2026-05-14', tz='UTC')),
        val  =(pd.Timestamp('2026-05-14', tz='UTC'), pd.Timestamp('2026-05-18', tz='UTC')),
        lock =(pd.Timestamp('2026-05-18', tz='UTC'), pd.Timestamp('2026-05-22', tz='UTC')),
    ),
}

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        col = np.nan_to_num(col, nan=0.0)
        m &= (col == 1)
    return m

def metrics(d, gates):
    m = gate_passes(d, gates)
    sub = d[m].sort_values('fire_us').reset_index(drop=True)
    n = len(sub)
    if n == 0: return dict(n=0, wr=0, dpt=0, sum=0, dd=0, ls=0, sharpe=0, n_days=0)
    pnl = sub.pnl_legacy_usd.values
    wr = sub.won.mean() * 100
    dpt = pnl.mean()
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    dd = float((peak-cum).max())
    losers = (pnl < 0).astype(int)
    cur_run = max_run = 0
    for v in losers:
        if v == 1:
            cur_run += 1
            if cur_run > max_run: max_run = cur_run
        else: cur_run = 0
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    daily = sub.groupby('date')['pnl_legacy_usd'].sum()
    sharpe = (daily.mean() / daily.std()) * np.sqrt(252) if len(daily)>1 and daily.std()>0 else 0.0
    return dict(n=n, wr=wr, dpt=dpt, sum=float(pnl.sum()), dd=dd, ls=max_run, sharpe=sharpe, n_days=daily.shape[0])

def bootstrap(d, gates, n_iter=1000, seed=42):
    m = gate_passes(d, gates)
    sub = d[m].copy()
    n = len(sub)
    if n < 10: return (np.nan, np.nan, np.nan, np.nan)
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    grp = sub.groupby('date').pnl_legacy_usd
    daily_pnl = grp.sum().values; daily_n = grp.count().values
    n_days = len(daily_pnl)
    if n_days < 3: return (np.nan, np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        means[i] = daily_pnl[idx].sum() / max(daily_n[idx].sum(), 1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    obs = sub.pnl_legacy_usd.mean()
    p = (means <= 0).mean() if obs > 0 else 0.5
    return (obs, lo, hi, max(p, 1e-4))

def split_full_lock(cohort, d=df):
    spl = SPLITS[cohort]
    fd = d['fire_date']
    return (
        (fd >= spl['train'][0]) & (fd < spl['train'][1]),
        (fd >= spl['val'][0])   & (fd < spl['val'][1]),
        (fd >= spl['lock'][0])  & (fd < spl['lock'][1]),
        (fd >= spl['train'][0]) & (fd < spl['lock'][1]),
    )

# ---- 1. ABLATION: which gate carries the alpha? ----
CANDIDATES = {
    'HUR22_k4': dict(cohort='22D',
                     gates=['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high']),
    'HUR22_k5': dict(cohort='22D',
                     gates=['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_rf_strong']),
    'FULL_k4':  dict(cohort='33D',
                     gates=['g_above_1h_dailyvwap_with','g_offset_early','g_rf_aged','g_ribbon_slope_with']),
}

log("\n=== ABLATION TEST: drop one gate at a time ===")
for name, info in CANDIDATES.items():
    gates = info['gates']; cohort = info['cohort']
    m_tr, m_va, m_lo, _ = split_full_lock(cohort)
    print(f"\n{name} ({cohort}) baseline:")
    mt = metrics(df[m_lo], gates)
    obs, lo, hi, p = bootstrap(df[m_lo], gates)
    print(f"  baseline: n={mt['n']} WR={mt['wr']:.1f}% dpt=${mt['dpt']:+.2f} CI=[{lo:.2f},{hi:.2f}] p={p:.4f}")
    for drop_g in gates:
        sub_gates = [g for g in gates if g != drop_g]
        mt = metrics(df[m_lo], sub_gates)
        obs, lo, hi, p = bootstrap(df[m_lo], sub_gates)
        print(f"  drop {drop_g:30}: n={mt['n']:4} WR={mt['wr']:5.1f}% dpt=${mt['dpt']:+6.2f} CI=[{lo if not np.isnan(lo) else 0:+6.2f},{hi if not np.isnan(hi) else 0:+6.2f}] p={p:.4f}")

# ---- 2. Test HUR22_k4 stack on 33D cohort (full window) — measure how it generalizes when we use FULL window split (gates may be missing pre-May-1) ----
log("\n=== HUR22_k4 stack on FULL 33D split ===")
# Just use the same gates but apply 33D split — many fires will have hurst=0, vol_high=0 etc. due to coverage holes.
# The pre-May-1 fires don't have these gates, so they'll all fail. Effective trade count drops to within-window only.
gates = ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high']
m_tr, m_va, m_lo, m_full = split_full_lock('33D')
print(f"On 33D split (train Apr 24 - May 15, val May 15-22, lock May 22-26):")
for label, m in [('TRAIN', m_tr), ('VAL', m_va), ('LOCK', m_lo), ('FULL', m_full)]:
    mt = metrics(df[m], gates)
    print(f"  {label}: n={mt['n']} WR={mt['wr']:.1f}% dpt=${mt['dpt']:+.2f}")

# ---- 3. Try CORE_HUR22_k4 (the variant without g_offset_early) ----
log("\n=== Variant exploration: remove offset_early constraint ===")
variants = {
    'V1_no_offset_early':    ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_vol_high'],
    'V2_no_vol_high':        ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early'],
    'V3_no_tr_stack':        ['g_above_1h_dailyvwap_with','g_offset_early','g_vol_high'],
    'V4_no_vwap':            ['g_tr_stack_full_with','g_offset_early','g_vol_high'],
    'V5_swap_voll_for_volH': ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_low'],
    'V6_swap_vol_for_hurst': ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_hurst_trending'],
    'V7_add_rf_aged':        ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_rf_aged'],
    'V8_add_tr50':           ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_tr_above_ema50'],
    'V9_add_ribbon':         ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_ribbon_agrees'],
}
m_tr, m_va, m_lo, m_full = split_full_lock('22D')
results = []
for name, g in variants.items():
    mt_tr = metrics(df[m_tr], g); mt_va = metrics(df[m_va], g); mt_lo = metrics(df[m_lo], g); mt_full = metrics(df[m_full], g)
    obs, lo, hi, p = bootstrap(df[m_lo], g)
    print(f"  {name:30}: tr n={mt_tr['n']:4} WR={mt_tr['wr']:5.1f}% | va n={mt_va['n']:4} WR={mt_va['wr']:5.1f}% | lock n={mt_lo['n']:3} WR={mt_lo['wr']:5.1f}% dpt=${mt_lo['dpt']:+.2f} CI=[{lo if not np.isnan(lo) else 0:+5.2f},{hi if not np.isnan(hi) else 0:+5.2f}] p={p:.3f} | full n={mt_full['n']:4} dd=${mt_lo['dd']:.0f} streak={mt_lo['ls']}")
    results.append(dict(variant=name, gates='&'.join(g), n_tr=mt_tr['n'], wr_tr=mt_tr['wr'],
                        n_va=mt_va['n'], wr_va=mt_va['wr'], n_lo=mt_lo['n'], wr_lo=mt_lo['wr'],
                        dpt_lo=mt_lo['dpt'], dpt_ci_lo=lo, dpt_ci_hi=hi, p=p,
                        n_full=mt_full['n'], dd_lo=mt_lo['dd'], ls_lo=mt_lo['ls']))
vdf = pd.DataFrame(results)
vdf.to_csv(f"{OUT}/variant_exploration.csv", index=False)

# ---- 4. Try FRESH alpha ideas: combine g_offset_early + multi-TF align + trend ----
log("\n=== FRESH ALPHA: SMS multi-TF + offset_early + trend ===")
fresh = {
    'F1_multi_tf_early_trend':  ['g_multi_tf_align_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F2_multi_tf_early_volH':   ['g_multi_tf_align_with','g_offset_early','g_vol_high'],
    'F3_strong60_early_vwap':   ['g_trend_strong_60','g_offset_early','g_above_1h_dailyvwap_with'],
    'F4_cvd_early_vwap':        ['g_cvd_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F5_bos_early_vwap':        ['g_bos_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F6_rsi_ext_early_vwap':    ['g_rsi_extreme_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F7_trend_strong_early':    ['g_trend_slope_strong_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F8_markov_early_vwap':     ['g_markov_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F9_pivot_early_vwap':      ['g_near_pivot','g_offset_early','g_above_1h_dailyvwap_with'],
    'F10_mpskew_early_vwap':    ['g_mp_skew_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F11_tr_stack_early':       ['g_tr_stack_with','g_offset_early','g_above_1h_dailyvwap_with'],
    'F12_tr_stack_full_early':  ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with'],
}
for name, g in fresh.items():
    coh = '22D' if any(gg in g for gg in ['g_multi_tf_align_with','g_trend_strong_60','g_cvd_with','g_bos_with','g_rsi_extreme_with','g_markov_with','g_hurst_trending']) else '31D'
    m_tr, m_va, m_lo, m_full = split_full_lock(coh)
    mt_tr = metrics(df[m_tr], g); mt_va = metrics(df[m_va], g); mt_lo = metrics(df[m_lo], g); mt_full = metrics(df[m_full], g)
    obs, lo, hi, p = bootstrap(df[m_lo], g)
    print(f"  {name:30} [{coh}]: tr n={mt_tr['n']:4} WR={mt_tr['wr']:5.1f}% | va n={mt_va['n']:4} WR={mt_va['wr']:5.1f}% | lock n={mt_lo['n']:3} WR={mt_lo['wr']:5.1f}% dpt=${mt_lo['dpt']:+.2f} CI=[{lo if not np.isnan(lo) else 0:+5.2f},{hi if not np.isnan(hi) else 0:+5.2f}] p={p:.3f} dd=${mt_lo['dd']:.0f}")

# ---- 5. Verify FULL_k4 sleeve on 33D — what does its full-window cumulative PnL look like? ----
log("\n=== FULL_k4 daily breakdown ===")
gates_full = ['g_above_1h_dailyvwap_with','g_offset_early','g_rf_aged','g_ribbon_slope_with']
m_tr, m_va, m_lo, m_full = split_full_lock('33D')
fires_full = df[m_full & gate_passes(df, gates_full)].sort_values('fire_us').reset_index(drop=True)
fires_full['date'] = pd.to_datetime(fires_full.fire_us, unit='us', utc=True).dt.date
daily_full = fires_full.groupby('date').agg(pnl=('pnl_legacy_usd','sum'), n=('pnl_legacy_usd','count'), wr=('won','mean')).reset_index()
print(daily_full.to_string())
log("DONE")
