"""ETH 15m sniper search v2 — coverage-aware splits.

The enriched universe has 39,546 fires but per-gate coverage differs:
  - Microprice gates: Apr 24 -> May 25 (31.7d), 1-day gap on May 26
  - Regime v2_fixed gates (trend_slope, adx, ATR, BB squeeze): Apr 28 -> May 25 (28d)
  - Vol/Hurst gates (g_hurst_trending, g_vol_*, g_rv_with): Apr 30 -> May 22 (22d)
  - SMS gates (g_markov_with, g_cvd_with, g_rsi_*, g_bos_with, g_trend_strong_*): May 1 -> May 22 (22d)
  - Master gate features (g_lm_*, g_hawkes_*, g_flow_*, g_within_dev): May 1 -> May 22 (24.8d but exotic)
  - 1h VWAP / pivot (g_above_1h_dailyvwap_with, g_near_pivot, g_far_from_pivot): full 33d (binance 1m roll-up)
  - Offset / TA / RF / ribbon from v3 fires: full 33d

Strategy: determine EFFECTIVE WINDOW per stack based on gates used, then split accordingly.

Effective-window classification:
  - FULL_33D: only stacks using v3-fires gates + 1h VWAP/pivot + microprice (no hurst/sms/mgf)
  - REGIME_28D: stacks using regime v2_fixed gates (no hurst/sms/mgf)
  - HURST_22D: any stack using hurst, sms, rsi, cvd, bos, markov, mgf-exotic

Splits per effective window:
  - FULL_33D: train Apr 24 - May 14 (20d), val May 14-21 (7d), lock May 21-26 (5d)  (when stack avoids day-gap, otherwise prune)
  - REGIME_28D: train Apr 28 - May 14 (16d), val May 14-21 (7d), lock May 21-25 (4d)
  - HURST_22D: train May 1 - May 14 (13d), val May 14-18 (4d), lock May 18-22 (4d)

Search:
  PATH A: pre-window proxies (RSI extreme + markov)
  PATH B: beginning of window (offset bins)
  PATH C: high-bar designed stacks
  PATH D: greedy combinatorial constrained per effective window
  PATH E: per-offset bin sweep
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
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
log(f"loaded {len(df)} fires")

# ---- Classify gates by coverage cohort ----
FULL_33D_GATES = set([
    # base from v3 (TA, RF, ribbon, TR pivot, offset gates)
    'g_rf_with','g_rf_fresh','g_rf_aged','g_rf_strong','g_rf_in_band',
    'g_tr_stack_with','g_tr_stack_full_with','g_tr_above_cloud','g_tr_within_adr',
    'g_tr_in_active_session','g_tr_above_pp','g_tr_above_ema50','g_tr_above_ema200','g_tr_above_ema800',
    'g_ribbon_agrees','g_ribbon_slope_with','g_tight_ribbon',
    'g_bb_pos_with','g_stoch_with','g_mfi_with','g_cci_with',
    # 1h VWAP / pivot (computed from binance 1m roll-up — full 33d)
    'g_above_1h_dailyvwap_with','g_near_pivot','g_far_from_pivot',
    # offset bins (from v3 fires themselves)
    'g_offset_early','g_offset_mid','g_offset_late',
])
# Microprice gates: Apr 24 - May 25 (31.7d, missing only May 26)
MICROPRICE_GATES = set([
    'g_mp_no_extreme','g_mp_no_extreme_150','g_mp_skew_with','g_mp_change_with',
    'g_mp_weighted_skew_with','g_mp_imbalance_with',
])
# Regime v2_fixed: Apr 28 - May 25 (28d)
REGIME_28D_GATES = set([
    'g_trend_slope_with','g_trend_slope_strong_with','g_adx_strong',
    'g_range_compressed','g_bb_squeeze','g_atr_high',
])
# Vol/Hurst at fire 15m: Apr 30 - May 22 (22d)
HURST_22D_GATES = set([
    'g_hurst_trending','g_hurst_reverting','g_vol_high','g_vol_low','g_vol_med',
    'g_vol_expanding','g_vol_contracting','g_rv_with',
])
# SMS panel v2_fixed: May 1 - May 22 (22d)
SMS_22D_GATES = set([
    'g_markov_with','g_multi_tf_align_with','g_cvd_with',
    'g_rsi_oversold','g_rsi_overbought','g_rsi_extreme_with',
    'g_bos_with','g_trend_strong_60','g_trend_strong_80',
])
# Master gate features v2: May 1 - May 22 (24.8d)
MGF_22D_GATES = set([
    'g_imb5_strong_with','g_queue_top_high','g_imb_change_with','g_vwap_ge_50_le_85',
    'g_book_slope_steep_against','g_coinbase_basis_extreme_against','g_hl_liq_cascade_with',
    'g_flow_with_and_no_whale','g_lm_high_stat','g_lm_extreme_against','g_hawkes_imbalance_with',
    'g_within_dev','g_dev_extreme',
])

def cohort(gates):
    """Determine the most-restrictive coverage cohort needed for this stack."""
    gset = set(gates)
    if gset & (HURST_22D_GATES | SMS_22D_GATES | MGF_22D_GATES):
        return '22D'
    if gset & REGIME_28D_GATES:
        return '28D'
    if gset & MICROPRICE_GATES:
        return '31D'
    return '33D'

# Splits per cohort
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
        train=(pd.Timestamp('2026-04-28', tz='UTC'), pd.Timestamp('2026-05-14', tz='UTC')),  # 16d
        val  =(pd.Timestamp('2026-05-14', tz='UTC'), pd.Timestamp('2026-05-20', tz='UTC')),  # 6d
        lock =(pd.Timestamp('2026-05-20', tz='UTC'), pd.Timestamp('2026-05-25', tz='UTC')),  # 5d
    ),
    '22D': dict(
        train=(pd.Timestamp('2026-05-01', tz='UTC'), pd.Timestamp('2026-05-14', tz='UTC')),  # 13d
        val  =(pd.Timestamp('2026-05-14', tz='UTC'), pd.Timestamp('2026-05-18', tz='UTC')),  # 4d
        lock =(pd.Timestamp('2026-05-18', tz='UTC'), pd.Timestamp('2026-05-22', tz='UTC')),  # 4d
    ),
}

def split_for(gates):
    c = cohort(gates)
    spl = SPLITS[c]
    fd = df['fire_date']
    m_tr = (fd >= spl['train'][0]) & (fd < spl['train'][1])
    m_va = (fd >= spl['val'][0])   & (fd < spl['val'][1])
    m_lo = (fd >= spl['lock'][0])  & (fd < spl['lock'][1])
    full = (fd >= spl['train'][0]) & (fd < spl['lock'][1])
    days_lock = (spl['lock'][1] - spl['lock'][0]).total_seconds() / 86400.0
    days_full = (spl['lock'][1] - spl['train'][0]).total_seconds() / 86400.0
    return c, m_tr, m_va, m_lo, full, days_lock, days_full

ALL_GATES = sorted([c for c in df.columns if c.startswith('g_')])
def is_useful(g, d):
    ones = (d[g]==1).mean()
    return 0.02 <= ones <= 0.98
USEFUL = [g for g in ALL_GATES if is_useful(g, df)]
log(f"useful gates: {len(USEFUL)}")

STAKE = 25.0

def gate_passes(d, gates):
    if not gates: return np.ones(len(d), dtype=bool)
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        col = np.nan_to_num(col, nan=0.0)
        m &= (col == 1)
    return m

def compute_metrics(d, gates):
    m = gate_passes(d, gates)
    sub = d[m].sort_values('fire_us').reset_index(drop=True)
    n = len(sub)
    if n == 0:
        return dict(n=0, wr=np.nan, dpt=np.nan, sum=0.0, max_dd=0.0, loss_streak=0, sharpe=0.0, n_days=0)
    pnl = sub['pnl_legacy_usd'].values
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

def bootstrap_p(d, gates, n_iter=1000, seed=42):
    """Daily-clustered bootstrap. P[mean<=0 | obs > 0]."""
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
    obs = sub['pnl_legacy_usd'].mean()
    if obs <= 0: return 0.5
    p = (means <= 0).mean()
    return max(float(p), 1e-4)

def evaluate(name, gates):
    c, m_tr, m_va, m_lo, full_m, days_lock, days_full = split_for(gates)
    d_tr = df[m_tr]; d_va = df[m_va]; d_lo = df[m_lo]; d_full = df[full_m]
    mt_tr = compute_metrics(d_tr, gates)
    mt_va = compute_metrics(d_va, gates)
    mt_lo = compute_metrics(d_lo, gates)
    full = compute_metrics(d_full, gates)
    bp_lo  = bootstrap_p(d_lo, gates)
    bp_ful = bootstrap_p(d_full, gates)
    fpd_full = full['n'] / max(days_full, 1)
    fpd_lock = mt_lo['n'] / max(days_lock, 1)
    return dict(
        sleeve_id=name, cohort=c, gate_stack='&'.join(gates), depth=len(gates),
        n_train=mt_tr['n'], n_val=mt_va['n'], n_lockbox=mt_lo['n'], n_full=full['n'],
        wr_train=mt_tr['wr'], wr_val=mt_va['wr'], wr_lockbox=mt_lo['wr'], wr_full=full['wr'],
        dpt_25=mt_lo['dpt'], dpt_train=mt_tr['dpt'], dpt_val=mt_va['dpt'], dpt_full=full['dpt'],
        sum_25_28d=full['sum'], sum_lockbox=mt_lo['sum'],
        max_dd_25=mt_lo['max_dd'], max_dd_full=full['max_dd'],
        loss_streak=mt_lo['loss_streak'], loss_streak_full=full['loss_streak'],
        sharpe=mt_lo['sharpe'], sharpe_full=full['sharpe'],
        n_days_lock=mt_lo['n_days'], n_days_full=full['n_days'],
        fires_per_day=fpd_full, fires_per_day_lock=fpd_lock,
        days_lock=days_lock, days_full=days_full,
        bootstrap_p_lockbox=bp_lo, bootstrap_p_full=bp_ful,
    )

# ---- PATH C: hand-designed stacks ----
log("=== PATH C: designed stacks ===")
HIGH_BAR = {
    # Pure FULL_33D (no hurst/sms/mgf)
    'FULL_VWAP_TREND_RIB':                  ['g_above_1h_dailyvwap_with','g_ribbon_agrees','g_stoch_with'],
    'FULL_VWAP_TREND_RIB_TR50':             ['g_above_1h_dailyvwap_with','g_ribbon_agrees','g_stoch_with','g_tr_above_ema50'],
    'FULL_VWAP_TR50_MFI':                   ['g_above_1h_dailyvwap_with','g_tr_above_ema50','g_mfi_with'],
    'FULL_VWAP_RIB_BB_STOCH':               ['g_above_1h_dailyvwap_with','g_ribbon_agrees','g_bb_pos_with','g_stoch_with'],
    'FULL_VWAP_RIB_TR50_CCI':               ['g_above_1h_dailyvwap_with','g_ribbon_agrees','g_tr_above_ema50','g_cci_with'],
    'FULL_NEAR_PIVOT_TR50':                 ['g_near_pivot','g_tr_above_ema50','g_stoch_with'],
    'FULL_FAR_PIVOT_VWAP':                  ['g_far_from_pivot','g_above_1h_dailyvwap_with','g_ribbon_agrees'],
    'FULL_OFFSET_EARLY_VWAP_RIB':           ['g_offset_early','g_above_1h_dailyvwap_with','g_ribbon_agrees'],
    'FULL_OFFSET_MID_VWAP_RIB':             ['g_offset_mid','g_above_1h_dailyvwap_with','g_ribbon_agrees'],
    'FULL_OFFSET_LATE_VWAP_RIB':            ['g_offset_late','g_above_1h_dailyvwap_with','g_ribbon_agrees'],
    'FULL_OFFSET_EARLY_VWAP_TR50_MFI':      ['g_offset_early','g_above_1h_dailyvwap_with','g_tr_above_ema50','g_mfi_with'],
    'FULL_OFFSET_MID_VWAP_TR50_STOCH':      ['g_offset_mid','g_above_1h_dailyvwap_with','g_tr_above_ema50','g_stoch_with'],
    'FULL_TR_STACK_VWAP_RIB':               ['g_tr_stack_with','g_above_1h_dailyvwap_with','g_ribbon_agrees'],

    # 31D microprice + base
    'MP31_VWAP_MPSKEW_RIB':                 ['g_above_1h_dailyvwap_with','g_mp_skew_with','g_ribbon_agrees'],
    'MP31_VWAP_MPSKEW_TR50':                ['g_above_1h_dailyvwap_with','g_mp_skew_with','g_tr_above_ema50'],
    'MP31_VWAP_MPSKEW_BB':                  ['g_above_1h_dailyvwap_with','g_mp_skew_with','g_bb_pos_with'],
    'MP31_MPSKEW_RIB_STOCH':                ['g_mp_skew_with','g_ribbon_agrees','g_stoch_with'],
    'MP31_MPSKEW_RIB_STOCH_TR50':           ['g_mp_skew_with','g_ribbon_agrees','g_stoch_with','g_tr_above_ema50'],
    'MP31_OFFSET_EARLY_MPSKEW_VWAP':        ['g_offset_early','g_mp_skew_with','g_above_1h_dailyvwap_with'],
    'MP31_OFFSET_MID_MPSKEW_VWAP':          ['g_offset_mid','g_mp_skew_with','g_above_1h_dailyvwap_with'],
    'MP31_OFFSET_LATE_MPSKEW_VWAP':         ['g_offset_late','g_mp_skew_with','g_above_1h_dailyvwap_with'],
    'MP31_MPSKEW_NOEXTREME_RIB':            ['g_mp_skew_with','g_mp_no_extreme','g_ribbon_agrees'],
    'MP31_MPSKEW_WEIGHTED_RIB':             ['g_mp_weighted_skew_with','g_ribbon_agrees','g_stoch_with'],
    'MP31_MPCHANGE_VWAP_RIB':               ['g_mp_change_with','g_above_1h_dailyvwap_with','g_ribbon_agrees'],
    'MP31_MPSKEW_VWAP_RIB_TR50':            ['g_mp_skew_with','g_above_1h_dailyvwap_with','g_ribbon_agrees','g_tr_above_ema50'],

    # 28D regime
    'RG28_TREND_VWAP_RIB':                  ['g_trend_slope_with','g_above_1h_dailyvwap_with','g_ribbon_agrees'],
    'RG28_TREND_STRONG_VWAP':               ['g_trend_slope_strong_with','g_above_1h_dailyvwap_with'],
    'RG28_TREND_STRONG_MPSKEW_VWAP':        ['g_trend_slope_strong_with','g_mp_skew_with','g_above_1h_dailyvwap_with'],
    'RG28_TREND_STRONG_RIB_STOCH':          ['g_trend_slope_strong_with','g_ribbon_agrees','g_stoch_with'],
    'RG28_TREND_ADX_RIB':                   ['g_trend_slope_with','g_adx_strong','g_ribbon_agrees'],
    'RG28_TREND_ADX_VWAP':                  ['g_trend_slope_with','g_adx_strong','g_above_1h_dailyvwap_with'],
    'RG28_TREND_BBSQUEEZE_VWAP':            ['g_trend_slope_with','g_bb_squeeze','g_above_1h_dailyvwap_with'],
    'RG28_TREND_STRONG_MP_NOEXT':           ['g_trend_slope_strong_with','g_mp_no_extreme','g_above_1h_dailyvwap_with'],

    # 22D hurst stacks
    'HURST22_TREND_MP_RIB':                 ['g_trend_slope_with','g_hurst_trending','g_mp_no_extreme','g_ribbon_agrees'],
    'HURST22_TREND_MP_VWAP':                ['g_trend_slope_with','g_hurst_trending','g_mp_no_extreme','g_above_1h_dailyvwap_with'],
    'HURST22_TREND_HURST_VOLHIGH':          ['g_trend_slope_with','g_hurst_trending','g_vol_high'],
    'HURST22_HURST_STRONG_TREND_VWAP':      ['g_trend_slope_strong_with','g_hurst_trending','g_above_1h_dailyvwap_with'],
    'HURST22_HURST_MPSKEW_VWAP':            ['g_hurst_trending','g_mp_skew_with','g_above_1h_dailyvwap_with'],
    'HURST22_HURST_MPSKEW_RIB':             ['g_hurst_trending','g_mp_skew_with','g_ribbon_agrees'],

    # SMS-based (22d)
    'SMS22_MARKOV_TREND_VWAP':              ['g_markov_with','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'SMS22_MARKOV_MPSKEW_VWAP':             ['g_markov_with','g_mp_skew_with','g_above_1h_dailyvwap_with'],
    'SMS22_CVD_TREND_VWAP':                 ['g_cvd_with','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'SMS22_CVD_HURST_VWAP':                 ['g_cvd_with','g_hurst_trending','g_above_1h_dailyvwap_with'],
    'SMS22_RSI_EXT_TREND_VWAP':             ['g_rsi_extreme_with','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'SMS22_RSI_OVERBOUGHT_TREND':           ['g_rsi_overbought','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'SMS22_RSI_OVERSOLD_TREND':             ['g_rsi_oversold','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'SMS22_TREND_STRONG60_VWAP_RIB':        ['g_trend_strong_60','g_above_1h_dailyvwap_with','g_ribbon_agrees'],
    'SMS22_TREND_STRONG80_VWAP':            ['g_trend_strong_80','g_above_1h_dailyvwap_with'],
    'SMS22_MULTI_TF_VWAP':                  ['g_multi_tf_align_with','g_above_1h_dailyvwap_with'],
    'SMS22_MULTI_TF_VWAP_TR50':             ['g_multi_tf_align_with','g_above_1h_dailyvwap_with','g_tr_above_ema50'],

    # MGF exotic stacks
    'MGF22_WITHINDEV_TREND_VWAP':           ['g_within_dev','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'MGF22_QUEUE_TOP_HIGH_TREND':           ['g_queue_top_high','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'MGF22_IMB5_STRONG_TREND_VWAP':         ['g_imb5_strong_with','g_trend_slope_with','g_above_1h_dailyvwap_with'],
    'MGF22_VWAP_50_85_TREND_RIB':           ['g_vwap_ge_50_le_85','g_trend_slope_with','g_ribbon_agrees'],
}

# ---- PATH D: per-cohort greedy ----
log("=== PATH D: per-cohort greedy ===")
for cohort_name, gate_set in [
    ('FULL', FULL_33D_GATES),
    ('MP31', FULL_33D_GATES | MICROPRICE_GATES),
    ('REG28', FULL_33D_GATES | MICROPRICE_GATES | REGIME_28D_GATES),
    ('HUR22', FULL_33D_GATES | MICROPRICE_GATES | REGIME_28D_GATES | HURST_22D_GATES),
    ('SMS22', FULL_33D_GATES | MICROPRICE_GATES | REGIME_28D_GATES | SMS_22D_GATES),
    ('ALL22', FULL_33D_GATES | MICROPRICE_GATES | REGIME_28D_GATES | HURST_22D_GATES | SMS_22D_GATES | MGF_22D_GATES),
]:
    cands = [g for g in USEFUL if g in gate_set]
    # Determine cohort + split based on a probe stack containing first gate
    # We'll just use the cohort name to pick split
    cohort_code = {'FULL':'33D','MP31':'31D','REG28':'28D','HUR22':'22D','SMS22':'22D','ALL22':'22D'}[cohort_name]
    spl = SPLITS[cohort_code]
    fd = df['fire_date']
    m_tr_c = (fd >= spl['train'][0]) & (fd < spl['train'][1])
    d_tr_c = df[m_tr_c]
    log(f"  cohort {cohort_name} ({cohort_code}): n_train={len(d_tr_c)}, n_candidates={len(cands)}")
    for k in [3, 4, 5]:
        for min_n in [20, 40, 80]:
            chosen = []
            avail = list(cands)
            for _ in range(k):
                best_g, best_s = None, -np.inf
                for g in avail:
                    trial = chosen + [g]
                    mt = compute_metrics(d_tr_c, trial)
                    if mt['n'] < min_n: continue
                    s = mt['dpt']
                    if s > best_s:
                        best_s = s; best_g = g
                if best_g is None: break
                chosen.append(best_g)
                avail.remove(best_g)
            name = f"GR_{cohort_name}_k{k}_n{min_n}"
            HIGH_BAR[name] = chosen
            log(f"    {name}: {chosen}")

# ---- PATH E: per-offset bin sweep ----
log("=== PATH E: per-offset bin sweep ===")
OFFSET_BINS = ['0-60','60-150','150-300','300-480','480-720','720-900']
for ob in OFFSET_BINS:
    d_bin = df[df.offset_bin == ob].copy()
    if len(d_bin) < 30: continue
    # Use FULL_33D cohort (largest train window) for greedy
    cohort_code = '33D'
    spl = SPLITS[cohort_code]
    fd = d_bin['fire_date']
    m_tr_b = (fd >= spl['train'][0]) & (fd < spl['train'][1])
    d_tr_b = d_bin[m_tr_b]
    if len(d_tr_b) < 50: continue
    # Only test FULL_33D + MP31 + REG28 gates (since we're using the 33D split)
    cands = [g for g in USEFUL if g in (FULL_33D_GATES | MICROPRICE_GATES | REGIME_28D_GATES)]
    log(f"  offset {ob}: n_train={len(d_tr_b)} cands={len(cands)}")
    for k in [3,4]:
        chosen = []
        avail = list(cands)
        for _ in range(k):
            best_g, best_s = None, -np.inf
            for g in avail:
                trial = chosen + [g]
                mt = compute_metrics(d_tr_b, trial)
                if mt['n'] < 20: continue
                s = mt['dpt']
                if s > best_s: best_s = s; best_g = g
            if best_g is None: break
            chosen.append(best_g)
            avail.remove(best_g)
        # Always include the offset gate
        offset_gate = {'0-60':'g_offset_early','60-150':None,'150-300':None,'300-480':'g_offset_mid',
                       '480-720':None,'720-900':'g_offset_late'}.get(ob)
        if offset_gate and offset_gate not in chosen:
            chosen = [offset_gate] + chosen
        name = f"OFFSET_{ob.replace('-','_')}_GR{k}"
        HIGH_BAR[name] = chosen

# ---- Evaluate all ----
log(f"=== EVALUATING {len(HIGH_BAR)} stacks ===")
results = []
for name, gates in HIGH_BAR.items():
    if not gates: continue
    r = evaluate(name, gates)
    results.append(r)
res_df = pd.DataFrame(results)
res_df.to_csv(f"{OUT}/all_candidates.csv", index=False)
log(f"WROTE all_candidates.csv ({len(res_df)} rows)")

# Sniper filter
def passes_sniper(r):
    if r['n_lockbox'] < 5: return False
    if r['n_full'] > 500: return False
    if r['fires_per_day'] < 1.5: return False
    if r['fires_per_day'] > 15: return False
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

def score(r):
    s = 0
    if r['wr_lockbox'] >= 75: s += 1
    if r['dpt_25'] >= 3: s += 1
    if r['max_dd_25'] <= 300: s += 1
    if r['loss_streak'] <= 6: s += 1
    if r['sharpe'] >= 2: s += 1
    if r['n_lockbox'] >= 5 and r['n_full'] <= 500: s += 1
    if pd.notna(r['bootstrap_p_lockbox']) and r['bootstrap_p_lockbox'] <= 0.05: s += 1
    if 1.5 <= r['fires_per_day'] <= 15: s += 1
    return s

res_df['sniper_score'] = res_df.apply(score, axis=1)

log("\n=== TOP candidates by sniper_score + dpt ===")
view = res_df[res_df.n_lockbox >= 5].sort_values(['sniper_score','dpt_25'], ascending=[False, False]).head(30)
for _, r in view.iterrows():
    log(f"  {r['sleeve_id']:35} [{r['cohort']}] score={r['sniper_score']} lock n={int(r['n_lockbox']):3} WR={r['wr_lockbox']:5.1f}% dpt=${r['dpt_25']:+.2f} dd=${r['max_dd_25']:5.0f} streak={int(r['loss_streak'])} sharpe={r['sharpe']:5.2f} p={r['bootstrap_p_lockbox']:.3f} fpd={r['fires_per_day']:5.2f}")

if len(sniper) >= 5:
    top5 = sniper.head(5)
else:
    top5 = res_df[res_df.n_lockbox >= 5].sort_values(['sniper_score','dpt_25'], ascending=[False, False]).head(5)
top5.to_csv(f"{OUT}/top_5_candidates.csv", index=False)
log(f"WROTE top_5_candidates.csv ({len(top5)})")

nm = res_df[(res_df.sniper_score >= 6) & (~res_df.pass_sniper) & (res_df.n_lockbox >= 5)].sort_values(['sniper_score','dpt_25'], ascending=[False, False]).head(15)
nm.to_csv(f"{OUT}/near_misses.csv", index=False)
log(f"WROTE near_misses.csv ({len(nm)})")

summary = dict(
    universe='ETH 15m (v3)', n_fires=len(df),
    splits=str({k: {kk: str(vv) for kk, vv in v.items()} for k,v in SPLITS.items()}),
    n_useful_gates=len(USEFUL),
    n_stacks_evaluated=len(res_df),
    n_passing_sniper=int(len(sniper)),
    n_near_misses=int(len(nm)),
)
with open(f"{OUT}/_summary.json", 'w') as f:
    json.dump(summary, f, indent=2)
log("DONE")
