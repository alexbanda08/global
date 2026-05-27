"""SOL 15m sniper search.

GREENFIELD market — no prior session searched this. Test all 5 approach paths:
  A) Pre-window entries (ws_s anchor) — for SOL 15m, fire_offset_s starts at 60 so
     no pre-window fires; treat first-60s as proxy
  B) Per-offset bin sweep (different fire_offset bins)
  C) Single-gate enumeration baseline
  D) Greedy combinatorial
  E) High-bar deterministic stacks

3-way split using INTERSECTION window:
  Effective coverage = primary fires (33d Apr 24-May 26) ∩ regime_v2_fixed (28d Apr 28-May 25)
  = ~28d. Use train 18d / val 6d / lock 4d (per brief §5).

Sniper filter (per brief §2):
  n_per_32d in [50, 500], WR_lock >= 75%, dpt_25 >= $3, max_dd_25 <= $300,
  loss_streak <= 6, sharpe >= 2.0, bootstrap_p_lock <= 0.05.
"""
import os, time, itertools, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m"

log("loading fires (v2_fixed gates)")
df = pd.read_parquet(f"{OUT}/sol_15m_fires_v2fix_gates.parquet")
log(f"loaded {len(df):,} fires")
log(f"date range: {pd.to_datetime(df.fire_us.min(),unit='us',utc=True)} -> {pd.to_datetime(df.fire_us.max(),unit='us',utc=True)}")

# Splits: train 18d / val 6d / lockbox 4d
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
# Effective window starts when regime_v2_fixed has coverage = Apr 28
TRAIN_START = pd.Timestamp('2026-04-28', tz='UTC')
TRAIN_END   = pd.Timestamp('2026-05-16', tz='UTC')   # 18d train
VAL_END     = pd.Timestamp('2026-05-22', tz='UTC')   # 6d val
LOCK_END    = pd.Timestamp('2026-05-26', tz='UTC')   # 4d lockbox

def split_masks(d):
    return (
        (d['fire_date'] >= TRAIN_START) & (d['fire_date'] < TRAIN_END),
        (d['fire_date'] >= TRAIN_END)   & (d['fire_date'] < VAL_END),
        (d['fire_date'] >= VAL_END)     & (d['fire_date'] < LOCK_END),
    )

m_tr, m_va, m_lo = split_masks(df)
log(f"splits: train={m_tr.sum():,} val={m_va.sum():,} lock={m_lo.sum():,}")
log(f"  WR train={df[m_tr].won.mean()*100:.1f}% val={df[m_va].won.mean()*100:.1f}% lock={df[m_lo].won.mean()*100:.1f}%")

# Gate vocabulary — keep only gates with >50% coverage
ALL_GATES = sorted([c for c in df.columns if c.startswith('g_')])
def is_useful(g, d):
    cov = d[g].notna().mean()
    if cov < 0.50: return False
    ones = (d[g]==1).sum()
    zeros = (d[g]==0).sum()
    if min(ones, zeros) < 100: return False
    return True
USEFUL_GATES = [g for g in ALL_GATES if is_useful(g, df)]
log(f"useful gates (cov>=50%, both classes >=100): {len(USEFUL_GATES)}")
for g in USEFUL_GATES:
    cov = df[g].notna().mean()*100
    ones = (df[g]==1).mean()*100
    log(f"  {g:40} cov={cov:5.1f}%  ones={ones:5.1f}%")

# pnl_legacy_usd in primary fires is ALREADY at $25 notional (per full_window_validation_v2 NOTIONAL=25.0)
# So stake multiplier MUST be 1.0 — do not double-count
STAKE = 1.0

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        m &= (col == 1)
    return m

def compute_metrics(d, gates, stake=STAKE):
    m = gate_passes(d, gates)
    sub = d[m].sort_values('fire_us').reset_index(drop=True)
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, sum=0.0, max_dd=0.0, loss_streak=0, sharpe=np.nan, n_days=0)
    pnl = sub['pnl_legacy_usd'].values * stake
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
    daily = sub.groupby('date')['pnl_legacy_usd'].sum() * stake
    n_days = len(daily)
    if len(daily) > 1 and daily.std() > 0:
        sharpe = (daily.mean() / daily.std()) * np.sqrt(252)
    else:
        sharpe = 0.0
    return dict(n=n, wr=wr, dpt=dpt, sum=float(pnl.sum()),
                max_dd=max_dd, loss_streak=max_run, sharpe=float(sharpe), n_days=n_days)

def bootstrap_p(d, gates, n_iter=1000, stake=STAKE, seed=42):
    m = gate_passes(d, gates)
    sub = d[m]
    n = len(sub)
    if n < 10: return np.nan
    pnl = sub['pnl_legacy_usd'].values * stake
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

# ---- PATH C: single-gate enumeration ----
log("=== PATH C: Single-gate enumeration ===")
sg_rows = []
for g in USEFUL_GATES:
    mt = compute_metrics(df, [g])
    sg_rows.append(dict(gate=g, n=mt['n'], wr=mt['wr'], dpt=mt['dpt'], sum=mt['sum'],
                        max_dd=mt['max_dd'], loss_streak=mt['loss_streak'], sharpe=mt['sharpe']))
sg_df = pd.DataFrame(sg_rows).sort_values('dpt', ascending=False)
sg_df.to_csv(f"{OUT}/single_gate_full_window.csv", index=False)
log(f"top single gates by dpt:")
for _, r in sg_df.head(15).iterrows():
    log(f"  {r['gate']:35} n={r['n']:5} WR={r['wr']:5.1f}% dpt=${r['dpt']:+.2f} dd=${r['max_dd']:.0f} streak={r['loss_streak']}")

# ---- PATH D: Greedy combinatorial ----
log("=== PATH D: Greedy combinatorial ===")
d_tr = df[m_tr].copy(); d_va = df[m_va].copy(); d_lo = df[m_lo].copy()
N_MIN_TR = 25

def greedy_search(d_t, candidates, max_k=6, score='sum', min_n_per_step=N_MIN_TR):
    chosen = []
    avail = list(candidates)
    for _ in range(max_k):
        best_g, best_s = None, -np.inf
        for g in avail:
            trial = chosen + [g]
            mt = compute_metrics(d_t, trial)
            if mt['n'] < min_n_per_step: continue
            if score == 'sum': s = mt['sum']
            elif score == 'dpt': s = mt['dpt']
            elif score == 'wr_dpt':
                # composite: WR * dpt to prefer high-WR sniper sleeves
                if mt['wr'] < 60: continue
                s = mt['wr'] * mt['dpt']
            else: s = mt['sum']
            if s > best_s:
                best_s = s; best_g = g
        if best_g is None: break
        chosen.append(best_g)
        avail.remove(best_g)
    return chosen

g_sum_6 = greedy_search(d_tr, USEFUL_GATES, max_k=6, score='sum')
g_sum_4 = greedy_search(d_tr, USEFUL_GATES, max_k=4, score='sum')
g_sum_3 = greedy_search(d_tr, USEFUL_GATES, max_k=3, score='sum')
g_dpt_5 = greedy_search(d_tr, USEFUL_GATES, max_k=5, score='dpt')
g_dpt_3 = greedy_search(d_tr, USEFUL_GATES, max_k=3, score='dpt')
g_wd_5  = greedy_search(d_tr, USEFUL_GATES, max_k=5, score='wr_dpt')
log(f"GREEDY_SUM_6: {g_sum_6}")
log(f"GREEDY_SUM_4: {g_sum_4}")
log(f"GREEDY_SUM_3: {g_sum_3}")
log(f"GREEDY_DPT_5: {g_dpt_5}")
log(f"GREEDY_DPT_3: {g_dpt_3}")
log(f"GREEDY_WD_5:  {g_wd_5}")

# ---- PATH E: High-bar deterministic stacks ----
log("=== PATH E: High-bar deterministic stacks ===")
HIGH_BAR = {
    # R4-anchored
    'TS_RIB_MARK': ['g_trend_slope_with', 'g_ribbon_agrees', 'g_markov_with'],
    'TS_HURST_MP': ['g_trend_slope_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    'TS_RF_TR50':  ['g_trend_slope_with', 'g_rf_with', 'g_tr_above_ema50'],
    'TS_STOCH_MFI':['g_trend_slope_with', 'g_stoch_with', 'g_mfi_with'],
    'TS_BB_MFI':   ['g_trend_slope_with', 'g_bb_pos_with', 'g_mfi_with'],
    'TS_CCI_STOCH':['g_trend_slope_with', 'g_cci_with', 'g_stoch_with'],
    'TS_RF_STOCH_VOL':  ['g_trend_slope_with', 'g_rf_with', 'g_stoch_with', 'g_vol_expanding'],
    'TS_RIB_MP_HURST':  ['g_trend_slope_with', 'g_ribbon_agrees', 'g_mp_no_extreme', 'g_hurst_trending'],
    'TS_RIB_MARK_MP':   ['g_trend_slope_with', 'g_ribbon_agrees', 'g_markov_with', 'g_mp_no_extreme'],
    'TS_STRONG_RIB':    ['g_trend_slope_strong_with', 'g_ribbon_agrees'],
    'TS_STRONG_MARK':   ['g_trend_slope_strong_with', 'g_markov_with'],
    'TS_STRONG_HURST':  ['g_trend_slope_strong_with', 'g_hurst_trending'],
    'TS_STRONG_MP':     ['g_trend_slope_strong_with', 'g_mp_no_extreme'],
    'TS_STRONG_RF':     ['g_trend_slope_strong_with', 'g_rf_with'],
    'TS_STRONG_STOCH':  ['g_trend_slope_strong_with', 'g_stoch_with'],
    'TS_STRONG_MFI':    ['g_trend_slope_strong_with', 'g_mfi_with'],
    'TS_STRONG_TR50':   ['g_trend_slope_strong_with', 'g_tr_above_ema50'],
    'TS_STRONG_RIB_MP': ['g_trend_slope_strong_with', 'g_ribbon_agrees', 'g_mp_no_extreme'],
    'TS_STRONG_RIB_MARK':['g_trend_slope_strong_with', 'g_ribbon_agrees', 'g_markov_with'],
    'TS_STRONG_HURST_MP':['g_trend_slope_strong_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    'TS_STRONG_VOL':    ['g_trend_slope_strong_with', 'g_vol_expanding'],
    'TS_STRONG_VOL_HIGH':['g_trend_slope_strong_with', 'g_vol_high'],
    'TS_ALONE':         ['g_trend_slope_with'],
    'TS_STRONG_ALONE':  ['g_trend_slope_strong_with'],
    # Without trend_slope — use other gates
    'MARK_HURST_MP':    ['g_markov_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    'MARK_RIB_MP':      ['g_markov_with', 'g_ribbon_agrees', 'g_mp_no_extreme'],
    'MARK_RF_STOCH':    ['g_markov_with', 'g_rf_with', 'g_stoch_with'],
    'RIB_MP_MFI':       ['g_ribbon_agrees', 'g_mp_no_extreme', 'g_mfi_with'],
    'STACK_MARK_MP':    ['g_tr_stack_with', 'g_markov_with', 'g_mp_no_extreme'],
    'STACK_HURST_MP':   ['g_tr_stack_with', 'g_hurst_trending', 'g_mp_no_extreme'],
    'STACK_RIB_MP':     ['g_tr_stack_with', 'g_ribbon_agrees', 'g_mp_no_extreme'],
    'STACK_RF_MARK':    ['g_tr_stack_with', 'g_rf_with', 'g_markov_with'],
    'TRSTACK_TS':       ['g_tr_stack_with', 'g_trend_slope_with'],
    'TRSTACK_TS_RIB':   ['g_tr_stack_with', 'g_trend_slope_with', 'g_ribbon_agrees'],
    'TRSTACK_TS_MP':    ['g_tr_stack_with', 'g_trend_slope_with', 'g_mp_no_extreme'],
    'TRSTACK_TS_MARK':  ['g_tr_stack_with', 'g_trend_slope_with', 'g_markov_with'],
    'TRSTACK_FULL':     ['g_tr_stack_full_with'],
    'TRSTACK_FULL_TS':  ['g_tr_stack_full_with', 'g_trend_slope_with'],
    'TRSTACK_FULL_MARK':['g_tr_stack_full_with', 'g_markov_with'],
    'TRSTACK_FULL_MP':  ['g_tr_stack_full_with', 'g_mp_no_extreme'],
    'TRSTACK_FULL_TS_MP':['g_tr_stack_full_with', 'g_trend_slope_with', 'g_mp_no_extreme'],
    'TRSTACK_FULL_TS_RIB':['g_tr_stack_full_with', 'g_trend_slope_with', 'g_ribbon_agrees'],
    'TRSTACK_FULL_TS_MARK_MP':['g_tr_stack_full_with', 'g_trend_slope_with', 'g_markov_with', 'g_mp_no_extreme'],
    'TRSTACK_FULL_RIB_MP':['g_tr_stack_full_with', 'g_ribbon_agrees', 'g_mp_no_extreme'],
    # RF subset
    'RF_STRONG_TS':     ['g_rf_strong', 'g_trend_slope_with'],
    'RF_STRONG_MARK':   ['g_rf_strong', 'g_markov_with'],
    'RF_STRONG_MP':     ['g_rf_strong', 'g_mp_no_extreme'],
    'RF_STRONG_TS_MP':  ['g_rf_strong', 'g_trend_slope_with', 'g_mp_no_extreme'],
    'RF_STRONG_TS_RIB': ['g_rf_strong', 'g_trend_slope_with', 'g_ribbon_agrees'],
    'RF_STRONG_TS_MARK':['g_rf_strong', 'g_trend_slope_with', 'g_markov_with'],
    'RF_STRONG_TS_MARK_MP':['g_rf_strong', 'g_trend_slope_with', 'g_markov_with', 'g_mp_no_extreme'],
    'RF_IN_BAND_TS':    ['g_rf_in_band', 'g_trend_slope_with'],
    'RF_IN_BAND_TS_MP': ['g_rf_in_band', 'g_trend_slope_with', 'g_mp_no_extreme'],
}
# Add greedies
for name, gs in [('GREEDY_SUM_6', g_sum_6), ('GREEDY_SUM_4', g_sum_4),
                 ('GREEDY_SUM_3', g_sum_3), ('GREEDY_DPT_5', g_dpt_5),
                 ('GREEDY_DPT_3', g_dpt_3), ('GREEDY_WD_5', g_wd_5)]:
    HIGH_BAR[name] = gs

results = []
for name, gates in HIGH_BAR.items():
    if not gates: continue
    mt_tr = compute_metrics(d_tr, gates)
    mt_va = compute_metrics(d_va, gates)
    mt_lo = compute_metrics(d_lo, gates)
    bp = bootstrap_p(d_lo, gates)
    full = compute_metrics(df, gates)
    full_bp = bootstrap_p(df, gates)
    r = dict(
        sleeve_id=name, anchor='offset_60s+', gate_stack='&'.join(gates), depth=len(gates),
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
        sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
        loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
        sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
        n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
        bootstrap_p_lockbox=bp, bootstrap_p_full=full_bp,
    )
    results.append(r)

# ---- PATH B: Per-offset bin sweep ----
log("=== PATH B: Per-offset bin sweep ===")
for off_bin in df.offset_bin.unique():
    d_bin = df[df.offset_bin == off_bin].copy()
    if len(d_bin) < 100: continue
    m_tr_b, m_va_b, m_lo_b = split_masks(d_bin)
    d_tr_b = d_bin[m_tr_b]; d_va_b = d_bin[m_va_b]; d_lo_b = d_bin[m_lo_b]
    if len(d_tr_b) < 100: continue
    log(f"  {off_bin}: tr={len(d_tr_b)} va={len(d_va_b)} lo={len(d_lo_b)}")
    greedy_b = greedy_search(d_tr_b, USEFUL_GATES, max_k=4, score='sum')
    if not greedy_b: continue
    log(f"    greedy(4)={greedy_b}")
    mt_tr = compute_metrics(d_tr_b, greedy_b)
    mt_va = compute_metrics(d_va_b, greedy_b)
    mt_lo = compute_metrics(d_lo_b, greedy_b)
    bp = bootstrap_p(d_lo_b, greedy_b)
    full = compute_metrics(d_bin, greedy_b)
    full_bp = bootstrap_p(d_bin, greedy_b)
    r = dict(
        sleeve_id=f"OFFSET_{off_bin}_GREEDY4", anchor=f'offset_{off_bin}s',
        gate_stack='&'.join(greedy_b), depth=len(greedy_b),
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
        sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
        loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
        sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
        n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
        bootstrap_p_lockbox=bp, bootstrap_p_full=full_bp,
    )
    results.append(r)

# Also test per-offset bin with sniper greedy (wr_dpt scoring)
log("=== PATH B2: Per-offset bin with WR-DPT scoring ===")
for off_bin in df.offset_bin.unique():
    d_bin = df[df.offset_bin == off_bin].copy()
    if len(d_bin) < 100: continue
    m_tr_b, m_va_b, m_lo_b = split_masks(d_bin)
    d_tr_b = d_bin[m_tr_b]; d_va_b = d_bin[m_va_b]; d_lo_b = d_bin[m_lo_b]
    if len(d_tr_b) < 100: continue
    greedy_b = greedy_search(d_tr_b, USEFUL_GATES, max_k=5, score='wr_dpt')
    if not greedy_b: continue
    mt_tr = compute_metrics(d_tr_b, greedy_b)
    mt_va = compute_metrics(d_va_b, greedy_b)
    mt_lo = compute_metrics(d_lo_b, greedy_b)
    bp = bootstrap_p(d_lo_b, greedy_b)
    full = compute_metrics(d_bin, greedy_b)
    full_bp = bootstrap_p(d_bin, greedy_b)
    r = dict(
        sleeve_id=f"OFFSET_{off_bin}_WD5", anchor=f'offset_{off_bin}s',
        gate_stack='&'.join(greedy_b), depth=len(greedy_b),
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
        sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
        loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
        sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
        n_days_full=full['n_days'], n_days_lock=mt_lo['n_days'],
        bootstrap_p_lockbox=bp, bootstrap_p_full=full_bp,
    )
    results.append(r)

res_df = pd.DataFrame(results)
res_df.to_csv(f"{OUT}/all_candidates_v2fix.csv", index=False)
log(f"WROTE all_candidates_v2fix.csv ({len(res_df)} rows)")

# Print top candidates by lockbox dpt
log("=== TOP candidates by LOCKBOX dpt ===")
top = res_df.sort_values('dpt_25', ascending=False)
for _, r in top.head(20).iterrows():
    log(f"  {r['sleeve_id']:30} lock n={r['n_lockbox']:3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f} dd=${r['max_dd_25']:.0f} streak={r['loss_streak']} sharpe={r['sharpe']:.2f} p={r['bootstrap_p_lockbox']:.3f}")
log("")
log("=== FULL-window stats for top candidates ===")
for _, r in top.head(20).iterrows():
    log(f"  {r['sleeve_id']:30} full n={r['n_full']:4} WR={r['wr_full']:5.1f}% dpt=${r['dpt_full']:+.2f} dd=${r['max_dd_full']:.0f} streak={r['loss_streak_full']} sharpe={r['sharpe_full']:.2f} p={r['bootstrap_p_full']:.3f}")

# Sniper filter
def passes_sniper(r):
    if r['n_lockbox'] < 5: return False
    if r['n_full'] > 500: return False
    # n_per_32d projection - use n_full normalized to 32d via effective ~28d window
    n_per_32d = r['n_full'] * (32.0/28.0)
    if n_per_32d < 50: return False
    if r['wr_lockbox'] < 75: return False
    if r['dpt_25'] < 3: return False
    if r['max_dd_25'] > 300: return False
    if r['loss_streak'] > 6: return False
    if r['sharpe'] < 2: return False
    if pd.isna(r['bootstrap_p_lockbox']) or r['bootstrap_p_lockbox'] > 0.05: return False
    return True

res_df['pass_sniper'] = res_df.apply(passes_sniper, axis=1)
sniper = res_df[res_df.pass_sniper].sort_values('dpt_25', ascending=False)
log(f"SNIPER-passing: {len(sniper)}")
for _, r in sniper.iterrows():
    log(f"  PASS {r['sleeve_id']:30} lock n={r['n_lockbox']:3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f}")

# Top 5 — even if no full pass, rank by sniper_score
def score(r):
    s = 0
    if r['wr_lockbox'] >= 75: s += 1
    if r['dpt_25'] >= 3: s += 1
    if r['max_dd_25'] <= 300: s += 1
    if r['loss_streak'] <= 6: s += 1
    if r['sharpe'] >= 2: s += 1
    if r['n_lockbox'] >= 5 and r['n_full'] <= 500: s += 1
    if pd.notna(r['bootstrap_p_lockbox']) and r['bootstrap_p_lockbox'] <= 0.05: s += 1
    return s
res_df['sniper_score'] = res_df.apply(score, axis=1)
if len(sniper):
    top5 = sniper.head(5)
else:
    top5 = res_df.sort_values(['sniper_score', 'dpt_25'], ascending=[False, False]).head(5)
top5.to_csv(f"{OUT}/top_5_candidates.csv", index=False)
log(f"WROTE top_5_candidates.csv ({len(top5)})")
log("DONE")
