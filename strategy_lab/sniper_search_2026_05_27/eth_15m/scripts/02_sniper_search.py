"""ETH 15m sniper search on enriched v3 universe.

Universe: 39,546 fires (33d) with 69 gates.
Approach paths (per §7 of brief):
  A) Pre-window proxies: g_rsi_extreme_with + g_markov_with + g_trend_strong_60
  B) Beginning-of-window: offset_bin == '0-60'
  C) High-bar stacks: 4-7 strict gates
  D) Greedy combinatorial with sniper constraints
  E) Per-offset bin sweep

Validation:
  - 3-way chronological split: train 20d / val 7d / lockbox 5d (Apr 24 - May 14, May 14 - 21, May 21 - 26)
  - Bootstrap p (1000-iter daily-clustered) on lockbox
  - All 7 metrics must pass on LOCKBOX

Output: top_5_candidates.csv, all_candidates.csv, near_misses.csv, single_gate.csv
"""
import os, time, itertools, warnings, json
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m"

log("loading enriched fires")
df = pd.read_parquet(f"{OUT}/eth_15m_enriched.parquet")
log(f"loaded {len(df)} fires, {len(df.columns)} cols")

# ---- splits (3-way chronological) ----
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
TRAIN_START = pd.Timestamp('2026-04-24', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-05-14', tz='UTC')   # 20d train
VAL_END     = pd.Timestamp('2026-05-21', tz='UTC')   # 7d val
LOCK_END    = pd.Timestamp('2026-05-26', tz='UTC')   # 5d lockbox (May 21-26)

def split_masks(d):
    fd = d['fire_date']
    return ((fd >= TRAIN_START) & (fd < TRAIN_END),
            (fd >= TRAIN_END)   & (fd < VAL_END),
            (fd >= VAL_END)     & (fd < LOCK_END))

m_tr, m_va, m_lo = split_masks(df)
log(f"splits: train={m_tr.sum()} val={m_va.sum()} lock={m_lo.sum()}")

# Useful gates
ALL_GATES = sorted([c for c in df.columns if c.startswith('g_')])
def is_useful(g, d):
    ones = (d[g]==1).mean()
    return 0.02 <= ones <= 0.98
USEFUL = [g for g in ALL_GATES if is_useful(g, df)]
log(f"useful gates: {len(USEFUL)}")
for g in USEFUL:
    ones = (df[g]==1).mean()
    log(f"  {g:35} ones={ones:.3f}")

STAKE = 25.0
# NOTE: v3 fires pnl_legacy_usd is ALREADY at $25 stake (loss=-25.0). Do not multiply.

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        # treat NaN as 0 (gate fails)
        col = np.nan_to_num(col, nan=0.0)
        m &= (col == 1)
    return m

def compute_metrics(d, gates, stake=STAKE):
    m = gate_passes(d, gates)
    sub = d[m].sort_values('fire_us').reset_index(drop=True)
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, sum=0.0, max_dd=0.0, loss_streak=0, sharpe=0.0, n_days=0)
    pnl = sub['pnl_legacy_usd'].values  # already at $25
    wr = sub['won'].mean() * 100
    dpt = float(pnl.mean())
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
    if len(daily) > 1 and daily.std() > 0:
        sharpe = float((daily.mean() / daily.std()) * np.sqrt(252))
    else:
        sharpe = 0.0
    return dict(n=n, wr=float(wr), dpt=dpt, sum=float(pnl.sum()),
                max_dd=max_dd, loss_streak=int(max_run), sharpe=sharpe, n_days=int(daily.shape[0]))

def bootstrap_p(d, gates, n_iter=1000, stake=STAKE, seed=42):
    """Daily-clustered bootstrap on lockbox PnL.

    Tests H0: mean PnL <= 0. Uses cluster-of-days resampling.
    Returns one-sided p-value (P[bootstrap_mean <= 0 | obs > 0]).
    """
    m = gate_passes(d, gates)
    sub = d[m].copy()
    n = len(sub)
    if n < 10: return np.nan
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    grp = sub.groupby('date')['pnl_legacy_usd']
    daily_pnl = grp.sum().values
    daily_n   = grp.count().values
    n_days = len(daily_pnl)
    if n_days < 3: return np.nan
    rng = np.random.default_rng(seed)
    means = np.empty(n_iter)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        boot_sum = daily_pnl[idx].sum()
        boot_n   = daily_n[idx].sum()
        means[i] = boot_sum / max(boot_n, 1)
    # one-sided p = fraction of bootstrap means <= 0 (under H0: true_mean=0)
    obs = sub['pnl_legacy_usd'].mean()
    if obs <= 0: return 0.5
    p = (means <= 0).mean()
    return max(float(p), 1e-4)

# ---- PATH A: single-gate enumeration (full window) ----
log("=== PATH A: single-gate enumeration ===")
sg_rows = []
for g in USEFUL:
    mt = compute_metrics(df, [g])
    sg_rows.append(dict(gate=g, n=mt['n'], wr=mt['wr'], dpt=mt['dpt'], sum=mt['sum'],
                        max_dd=mt['max_dd'], loss_streak=mt['loss_streak'], sharpe=mt['sharpe']))
sg_df = pd.DataFrame(sg_rows).sort_values('dpt', ascending=False)
sg_df.to_csv(f"{OUT}/single_gate.csv", index=False)
log(f"top 15 single gates by dpt:")
for _, r in sg_df.head(15).iterrows():
    log(f"  {r['gate']:35} n={int(r['n']):5} WR={r['wr']:5.1f}% dpt=${r['dpt']:+.3f} dd=${r['max_dd']:7.0f} streak={int(r['loss_streak']):2} sharpe={r['sharpe']:.2f}")

# ---- PATH D: Greedy combinatorial on train ----
d_tr = df[m_tr].copy(); d_va = df[m_va].copy(); d_lo = df[m_lo].copy()

def greedy(d_t, candidates, max_k=6, score='dpt', min_n=30):
    chosen = []
    avail = list(candidates)
    for _ in range(max_k):
        best_g, best_s = None, -np.inf
        for g in avail:
            trial = chosen + [g]
            mt = compute_metrics(d_t, trial)
            if mt['n'] < min_n: continue
            s = mt['sum'] if score=='sum' else mt['dpt']
            if s > best_s:
                best_s = s; best_g = g
        if best_g is None: break
        chosen.append(best_g)
        avail.remove(best_g)
    return chosen

log("=== PATH D: greedy search (train) ===")
greedies = {}
for k in [3,4,5,6,7]:
    for score, min_n in [('dpt', 20), ('dpt', 40), ('sum', 50)]:
        name = f"GREEDY_{score.upper()}_{k}_n{min_n}"
        gs = greedy(d_tr, USEFUL, max_k=k, score=score, min_n=min_n)
        greedies[name] = gs
        mt = compute_metrics(d_tr, gs)
        log(f"  {name:25} -> n_tr={mt['n']} WR={mt['wr']:.1f}% dpt=${mt['dpt']:+.2f} | gates={gs}")

# ---- PATH C: high-bar designed stacks ----
log("=== PATH C: high-bar designed stacks ===")
HIGH_BAR = {
    # CORE: trend slope + microprice no-extreme + hurst trending
    'CORE_MP_HURST':              ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    'CORE_MP_HURST_RIB':          ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_ribbon_agrees'],
    'CORE_MP_HURST_RF':           ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_rf_with'],
    'CORE_MP_HURST_STOCH':        ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_stoch_with'],
    'CORE_MP_HURST_TR50':         ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_tr_above_ema50'],
    'CORE_MP_HURST_BB':           ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_bb_pos_with'],
    'CORE_MP_HURST_CCI':          ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_cci_with'],
    'CORE_MP_HURST_MFI':          ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_mfi_with'],
    'CORE_MP_HURST_ADX':          ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme', 'g_adx_strong'],
    # MP_SKEW_WITH variants
    'MP_SKEW_TREND':              ['g_mp_skew_with', 'g_trend_slope_with'],
    'MP_SKEW_TREND_HURST':        ['g_mp_skew_with', 'g_trend_slope_with', 'g_hurst_trending'],
    'MP_SKEW_TREND_RIB':          ['g_mp_skew_with', 'g_trend_slope_with', 'g_ribbon_agrees'],
    'MP_SKEW_TREND_VWAP':         ['g_mp_skew_with', 'g_trend_slope_with', 'g_above_1h_dailyvwap_with'],
    'MP_SKEW_HURST_RIB':          ['g_mp_skew_with', 'g_hurst_trending', 'g_ribbon_agrees'],
    'MP_WEIGHTED_SKEW_HURST_RIB': ['g_mp_weighted_skew_with', 'g_hurst_trending', 'g_ribbon_agrees'],
    # MULTI-TF alignment
    'MULTI_TF_HURST_MP':          ['g_multi_tf_align_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    'MULTI_TF_RF_MP':             ['g_multi_tf_align_with', 'g_rf_with', 'g_mp_no_extreme'],
    'MULTI_TF_TREND_RIB':         ['g_multi_tf_align_with', 'g_trend_slope_with', 'g_ribbon_agrees'],
    # STRONG TREND base
    'TREND_STRONG_RIB':           ['g_trend_slope_strong_with', 'g_ribbon_agrees'],
    'TREND_STRONG_MP':            ['g_trend_slope_strong_with', 'g_mp_no_extreme'],
    'TREND_STRONG_HURST':         ['g_trend_slope_strong_with', 'g_hurst_trending'],
    'TREND_STRONG_HURST_MP':      ['g_trend_slope_strong_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    'TREND_STRONG_HURST_RIB':     ['g_trend_slope_strong_with', 'g_hurst_trending', 'g_ribbon_agrees'],
    'TREND_STRONG_VWAP':          ['g_trend_slope_strong_with', 'g_above_1h_dailyvwap_with'],
    # ADX-strong stacks
    'ADX_HURST_MP':               ['g_adx_strong', 'g_hurst_trending', 'g_mp_no_extreme'],
    'ADX_TREND_RIB':              ['g_adx_strong', 'g_trend_slope_with', 'g_ribbon_agrees'],
    # Volume / volatility
    'TREND_VOL_HIGH_HURST':       ['g_trend_slope_with', 'g_vol_high', 'g_hurst_trending'],
    'TREND_VOL_EXP_RIB':          ['g_trend_slope_with', 'g_vol_expanding', 'g_ribbon_agrees'],
    'TREND_VOL_CONTRACTING':      ['g_trend_slope_with', 'g_vol_contracting', 'g_hurst_trending'],
    # Smart money divergence + trend
    'CVD_TREND_HURST':            ['g_cvd_with', 'g_trend_slope_with', 'g_hurst_trending'],
    'CVD_TREND_MP':               ['g_cvd_with', 'g_trend_slope_with', 'g_mp_no_extreme'],
    # 1h VWAP alpha
    'VWAP_TREND_HURST':           ['g_above_1h_dailyvwap_with', 'g_trend_slope_with', 'g_hurst_trending'],
    'VWAP_TREND_RIB':             ['g_above_1h_dailyvwap_with', 'g_trend_slope_with', 'g_ribbon_agrees'],
    'VWAP_HURST_MP':              ['g_above_1h_dailyvwap_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    # Pivot
    'PIVOT_HURST_TREND':          ['g_near_pivot', 'g_trend_slope_with', 'g_hurst_trending'],
    'FAR_PIVOT_TREND':            ['g_far_from_pivot', 'g_trend_slope_with', 'g_hurst_trending'],
    # Offset bin gates (Path B: beginning of window)
    'OFFSET_EARLY_TREND_MP':      ['g_offset_early', 'g_trend_slope_with', 'g_mp_no_extreme'],
    'OFFSET_EARLY_TREND_HURST':   ['g_offset_early', 'g_trend_slope_with', 'g_hurst_trending'],
    'OFFSET_MID_TREND_HURST':     ['g_offset_mid', 'g_trend_slope_with', 'g_hurst_trending'],
    'OFFSET_MID_TREND_MP':        ['g_offset_mid', 'g_trend_slope_with', 'g_mp_no_extreme'],
    'OFFSET_LATE_TREND_HURST':    ['g_offset_late', 'g_trend_slope_with', 'g_hurst_trending'],
    'OFFSET_LATE_TREND_MP':       ['g_offset_late', 'g_trend_slope_with', 'g_mp_no_extreme'],
    # RSI extremes (Path A: pre-window RSI)
    'RSI_EXT_TREND':              ['g_rsi_extreme_with', 'g_trend_slope_with'],
    'RSI_EXT_TREND_HURST':        ['g_rsi_extreme_with', 'g_trend_slope_with', 'g_hurst_trending'],
    'RSI_EXT_MP':                 ['g_rsi_extreme_with', 'g_mp_no_extreme'],
    # BOS / CHOCH
    'BOS_TREND_MP':               ['g_bos_with', 'g_trend_slope_with', 'g_mp_no_extreme'],
    # TREND_STRONG_60 from SMS
    'TREND_STRONG60_RIB_MP':      ['g_trend_strong_60', 'g_ribbon_agrees', 'g_mp_no_extreme'],
    'TREND_STRONG60_HURST_MP':    ['g_trend_strong_60', 'g_hurst_trending', 'g_mp_no_extreme'],
    'TREND_STRONG80_HURST':       ['g_trend_strong_80', 'g_hurst_trending'],
    # 5-7 gate high-bar
    'FIVE_TREND_HURST_MP_RIB_STOCH':  ['g_trend_slope_with','g_hurst_trending','g_mp_no_extreme','g_ribbon_agrees','g_stoch_with'],
    'FIVE_TREND_HURST_MP_RIB_CCI':    ['g_trend_slope_with','g_hurst_trending','g_mp_no_extreme','g_ribbon_agrees','g_cci_with'],
    'FIVE_TREND_HURST_MP_RIB_MFI':    ['g_trend_slope_with','g_hurst_trending','g_mp_no_extreme','g_ribbon_agrees','g_mfi_with'],
    'FIVE_TREND_HURST_MP_TR50_VWAP':  ['g_trend_slope_with','g_hurst_trending','g_mp_no_extreme','g_tr_above_ema50','g_above_1h_dailyvwap_with'],
    'FIVE_MP_SKEW_HURST_TREND_RIB_BB':['g_mp_skew_with','g_hurst_trending','g_trend_slope_with','g_ribbon_agrees','g_bb_pos_with'],
    'SIX_FULL': ['g_trend_slope_with','g_hurst_trending','g_mp_no_extreme','g_ribbon_agrees','g_stoch_with','g_above_1h_dailyvwap_with'],
    # Add all greedies
}
HIGH_BAR.update(greedies)

# ---- PATH E: per-offset bin sweep ----
log("=== PATH E: per-offset bin sweep (greedy within bin) ===")
for ob in ['0-60','60-150','150-300','300-480','480-720','720-900']:
    d_bin = df[df.offset_bin == ob].copy()
    if len(d_bin) < 30: continue
    m_tr_b, m_va_b, m_lo_b = split_masks(d_bin)
    d_tr_b = d_bin[m_tr_b]; d_va_b = d_bin[m_va_b]; d_lo_b = d_bin[m_lo_b]
    if len(d_tr_b) < 50: continue
    log(f"  offset {ob}: tr={len(d_tr_b)} va={len(d_va_b)} lo={len(d_lo_b)}")
    for k in [3, 4]:
        gs = greedy(d_tr_b, USEFUL, max_k=k, score='dpt', min_n=30)
        name = f"OFFSET_{ob.replace('-','_')}_GREEDY{k}"
        HIGH_BAR[name] = gs

# ---- evaluate all stacks ----
log("=== EVALUATING ALL STACKS ===")
results = []
for name, gates in HIGH_BAR.items():
    mt_tr = compute_metrics(d_tr, gates)
    mt_va = compute_metrics(d_va, gates)
    mt_lo = compute_metrics(d_lo, gates)
    bp = bootstrap_p(d_lo, gates)
    full = compute_metrics(df, gates)
    full_bp = bootstrap_p(df, gates)
    days_full = full['n_days']
    fires_per_day = full['n'] / max(days_full, 1)
    r = dict(
        sleeve_id=name, anchor='offset_v3', gate_stack='&'.join(gates), depth=len(gates),
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
        sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
        loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
        sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
        n_days_full=days_full, fires_per_day=fires_per_day,
        bootstrap_p_lockbox=bp, bootstrap_p_full=full_bp,
    )
    results.append(r)
res_df = pd.DataFrame(results)
res_df.to_csv(f"{OUT}/all_candidates.csv", index=False)
log(f"WROTE all_candidates.csv ({len(res_df)} rows)")

# Show top by lockbox dpt with constraint n_lockbox >= 5
log("\n=== TOP candidates by LOCKBOX dpt (n_lock>=5) ===")
top = res_df[res_df.n_lockbox >= 5].sort_values('dpt_25', ascending=False)
for _, r in top.head(25).iterrows():
    log(f"  {r['sleeve_id']:35} lock n={int(r['n_lockbox']):3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f} dd=${r['max_dd_25']:5.0f} streak={int(r['loss_streak'])} sharpe={r['sharpe']:5.2f} p={r['bootstrap_p_lockbox']:.3f} full n={int(r['n_full']):4} WR={r['wr_full']:5.1f}% fpd={r['fires_per_day']:5.2f}")

# Sniper filter
def passes_sniper(r):
    if r['n_lockbox'] < 5: return False
    fires_per_32d = r['n_full'] * (33.0 / max(r['n_days_full'],1))  # extrapolation
    # Use n_full * 32/n_days as proxy for full-window count
    if r['n_full'] > 500: return False
    if r['fires_per_day'] < 1.5: return False
    if r['wr_lockbox'] < 75: return False
    if r['dpt_25'] < 3: return False
    if r['max_dd_25'] > 300: return False
    if r['loss_streak'] > 6: return False
    if r['sharpe'] < 2: return False
    if pd.isna(r['bootstrap_p_lockbox']) or r['bootstrap_p_lockbox'] > 0.05: return False
    return True

res_df['pass_sniper'] = res_df.apply(passes_sniper, axis=1)
sniper = res_df[res_df.pass_sniper].sort_values('dpt_25', ascending=False)
log(f"\nSNIPER-passing: {len(sniper)}")
for _, r in sniper.iterrows():
    log(f"  PASS {r['sleeve_id']:35} lock n={int(r['n_lockbox']):3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f}")

# Score by # criteria met
def score(r):
    s = 0
    if r['wr_lockbox'] >= 75: s += 1
    if r['dpt_25'] >= 3: s += 1
    if r['max_dd_25'] <= 300: s += 1
    if r['loss_streak'] <= 6: s += 1
    if r['sharpe'] >= 2: s += 1
    if r['n_lockbox'] >= 5 and r['n_full'] <= 500: s += 1
    if pd.notna(r['bootstrap_p_lockbox']) and r['bootstrap_p_lockbox'] <= 0.05: s += 1
    if r['fires_per_day'] >= 1.5 and r['fires_per_day'] <= 15: s += 1
    return s

res_df['sniper_score'] = res_df.apply(score, axis=1)

# top_5
if len(sniper) >= 5:
    top5 = sniper.head(5)
else:
    top5 = res_df[res_df.n_lockbox >= 5].sort_values(['sniper_score','dpt_25'], ascending=[False, False]).head(5)
top5.to_csv(f"{OUT}/top_5_candidates.csv", index=False)
log(f"WROTE top_5_candidates.csv ({len(top5)})")

# near-misses: passed >=6 of 8 criteria but missed at least 1
nm = res_df[(res_df.sniper_score >= 6) & (~res_df.pass_sniper) & (res_df.n_lockbox >= 5)].sort_values('sniper_score', ascending=False).head(15)
nm.to_csv(f"{OUT}/near_misses.csv", index=False)
log(f"WROTE near_misses.csv ({len(nm)})")

# Save grid search summary
summary = dict(
    universe='ETH 15m (v3)',
    n_fires=len(df),
    n_train=int(m_tr.sum()), n_val=int(m_va.sum()), n_lockbox=int(m_lo.sum()),
    n_useful_gates=len(USEFUL),
    n_stacks_evaluated=len(res_df),
    n_passing_sniper=int(len(sniper)),
    n_near_misses=int(len(nm)),
)
with open(f"{OUT}/_summary.json", 'w') as f:
    json.dump(summary, f, indent=2)
log("DONE")
