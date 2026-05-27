"""V7 sniper search ETH 15m — Paths I/A/C/G/H per V7 brief.

Path I (PRIMARY): deeper pre-window stacks built on V6_S1_PW_TREND_SLOPE winner
  V6 winner gate: g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_trend_slope_with
  -> n_lock=18 WR=94.4% $/tr=$11.27

  V7 additions:
    + g_pw_m1v_with
    + g_pw_xa_unanimity_with (and variants)
    + g_pw_btc_15m_trend_with (cross-asset Path C combined)
    + g_pw_mp_change_real_with (microprice at fire_us proxy)
    + g_hurst_regime_with
    + Triple/quad/quintuple PW combos

Path A: Weighted ensembles — gate-sum threshold (sigma-style)
Path C: BTC 15m trend → ETH 15m fire (g_pw_btc_15m_trend_with)
Path G: Vol regime specialization (g_vol_extreme_high cohorts)
Path H: Hurst variants (g_hurst_strong_trending, g_hurst_regime_with)

Stake: constant $25.
"""
import os, time, warnings, json
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
from itertools import combinations

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v7"
LOG = f"{OUT}/_logs"
os.makedirs(LOG, exist_ok=True)

log("loading v7 enriched")
fires = pd.read_parquet(f"{OUT}/eth_15m_enriched_v7.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
log(f"shape: {fires.shape}")

# Validate that the V6 winner replicates first
v6_winner_stack = ['g_tr_stack_full_with', 'g_above_1h_dailyvwap_with', 'g_offset_early', 'g_vol_high', 'g_pw_trend_slope_with']
mask_v6 = fires[v6_winner_stack].all(axis=1) > 0
log(f"V6 winner stack matches: {mask_v6.sum()} fires (V6 report said 63 full / 18 lockbox)")

# Determine stake nominal (same logic as V6)
mean_abs_pnl = fires.pnl_legacy_usd.abs().mean()
STAKE_NOMINAL = 1.0 if mean_abs_pnl > 1 else 25.0
log(f"mean |pnl_legacy_usd|: {mean_abs_pnl:.4f} | STAKE_NOMINAL = {STAKE_NOMINAL}")

fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date

# Cohort splits (HUR22 is the most relevant for V6 winner — M1V cohort starts May 1)
def cohort_split(df, cohort):
    if cohort == 'HUR22':
        train = (df.date >= pd.to_datetime('2026-05-01').date()) & (df.date < pd.to_datetime('2026-05-14').date())
        val = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-18').date())
        lock = (df.date >= pd.to_datetime('2026-05-18').date()) & (df.date <= pd.to_datetime('2026-05-22').date())
    elif cohort == 'MP31':
        train = df.date < pd.to_datetime('2026-05-15').date()
        val = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-21').date())
        lock = (df.date >= pd.to_datetime('2026-05-21').date()) & (df.date <= pd.to_datetime('2026-05-25').date())
    elif cohort == 'FULL':
        train = df.date < pd.to_datetime('2026-05-15').date()
        val = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-22').date())
        lock = df.date >= pd.to_datetime('2026-05-22').date()
    else:
        raise ValueError(cohort)
    return train, val, lock

def bootstrap_p(df_sub, n_iter=1000, rng=None):
    if rng is None: rng = np.random.default_rng(42)
    if len(df_sub) == 0: return 1.0, 0.0, 0.0, 0.0
    daily = df_sub.groupby('date').pnl_legacy_usd.sum().values * STAKE_NOMINAL
    if len(daily) <= 1: return 1.0, 0.0, 0.0, 0.0
    boot = np.empty(n_iter)
    n_d = len(daily)
    for i in range(n_iter):
        idx = rng.integers(0, n_d, n_d)
        boot[i] = daily[idx].sum()
    p = (boot <= 0).mean()
    return p, boot.mean(), np.percentile(boot, 2.5), np.percentile(boot, 97.5)

def gated_metrics(df, mask, cohort):
    sub = df[mask].copy()
    if len(sub) == 0:
        return None
    out = {'n_full': len(sub), 'wr_full': sub.won.mean()}
    out['sum_pnl_full'] = sub.pnl_legacy_usd.sum() * STAKE_NOMINAL
    out['dpt_full_25'] = (sub.pnl_legacy_usd.mean() if len(sub) else 0) * STAKE_NOMINAL
    train_m, val_m, lock_m = cohort_split(sub, cohort)
    for sn, m in [('train', train_m), ('val', val_m), ('lock', lock_m)]:
        s = sub[m]
        out[f'n_{sn}'] = len(s)
        out[f'wr_{sn}'] = s.won.mean() if len(s) else 0
        out[f'dpt_{sn}_25'] = (s.pnl_legacy_usd.mean() if len(s) else 0) * STAKE_NOMINAL
        out[f'sum_pnl_{sn}'] = s.pnl_legacy_usd.sum() * STAKE_NOMINAL
    eq = (sub.sort_values('fire_us').pnl_legacy_usd.cumsum() * STAKE_NOMINAL).values
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    out['max_dd_25'] = float(dd.max()) if len(dd) else 0.0
    losses = (sub.sort_values('fire_us').won == 0).astype(int).values
    max_s = 0; cur = 0
    for l in losses:
        cur = cur + 1 if l else 0
        if cur > max_s: max_s = cur
    out['loss_streak'] = max_s
    daily = sub.groupby('date').pnl_legacy_usd.sum() * STAKE_NOMINAL
    out['sharpe_daily'] = daily.mean() / daily.std() * np.sqrt(252) if len(daily) > 1 and daily.std() > 0 else 0
    out['fires_per_day'] = out['n_full'] / max(1, len(sub.date.unique()))
    return out

def passes_v7(m):
    if m is None: return False, []
    fails = []
    if m['n_lock'] < 5: fails.append(f"n_lock<5 ({m['n_lock']})")
    if m['n_full'] > 2000: fails.append(f"n_full>2000 ({m['n_full']})")
    if m['wr_lock'] < 0.65 and m['dpt_lock_25'] < 10: fails.append(f"wr_lock<0.65 & dpt<$10 ({m['wr_lock']:.3f},${m['dpt_lock_25']:.2f})")
    if m['dpt_lock_25'] < 4.0: fails.append(f"dpt_lock<$4 (${m['dpt_lock_25']:.2f})")
    if m['max_dd_25'] > 500: fails.append(f"dd>$500 (${m['max_dd_25']:.0f})")
    if m['loss_streak'] > 14: fails.append(f"streak>14 ({m['loss_streak']})")
    return len(fails) == 0, fails

# ===================== STACKS =====================
# V6 baselines for reference
v6_baselines = [
    ('V6_BASELINE_VWAP_3070', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_entry_vwap_in_30_70'], 'HUR22'),
    ('V6_BASELINE_PW_TREND_SLOPE', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_pw_trend_slope_with'], 'HUR22'),
    ('V6_BASELINE_DOWN_ONLY', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_dir_down'], 'HUR22'),
]

# ============================================================
# Path I — DEEPER PRE-WINDOW STACKS (PRIMARY)
# ============================================================
# Build V6 winner core (4 gates) + add 1-2 PW gates
core4 = ['g_tr_stack_full_with', 'g_above_1h_dailyvwap_with', 'g_offset_early', 'g_vol_high']

# Single-add (replicate V6 PW winners)
v7_path_i_single = [
    ('V7_PI_S1_M1V',                core4 + ['g_pw_m1v_with'], 'HUR22'),
    ('V7_PI_S1_XA_UNANIMITY',       core4 + ['g_pw_xa_unanimity_with'], 'HUR22'),
    ('V7_PI_S1_XA_UNANIMITY_STR',   core4 + ['g_pw_xa_unanimity_strong_with'], 'HUR22'),
    ('V7_PI_S1_XA_PARTIAL',         core4 + ['g_pw_xa_partial_with'], 'HUR22'),
    ('V7_PI_S1_XA_BTC_ETH',         core4 + ['g_pw_xa_btc_eth_with'], 'HUR22'),
    ('V7_PI_S1_BTC_RF',             core4 + ['g_pw_btc_rf_with'], 'HUR22'),
    ('V7_PI_S1_BTC_15M_TREND',      core4 + ['g_pw_btc_15m_trend_with'], 'HUR22'),
    ('V7_PI_S1_BTC_15M_TREND_STR',  core4 + ['g_pw_btc_15m_trend_strong_with'], 'HUR22'),
    ('V7_PI_S1_MP_CHANGE_REAL',     core4 + ['g_pw_mp_change_real_with'], 'HUR22'),
    ('V7_PI_S1_MP_CHANGE_STRONG',   core4 + ['g_pw_mp_change_strong_with'], 'HUR22'),
    ('V7_PI_S1_F7_RSI_MOMO',        core4 + ['g_pw_f7_rsi_momentum_with'], 'HUR22'),
    ('V7_PI_S1_HURST_REGIME',       core4 + ['g_hurst_regime_with'], 'HUR22'),
    ('V7_PI_S1_HURST_STRONG_TR',    core4 + ['g_hurst_strong_trending'], 'HUR22'),
]

# 2-gate PW stack on top of core4 (DEEPER) — V7 brief Path I primary objective
v7_path_i_double = [
    ('V7_PI_S1_TS_AND_M1V',         core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with'], 'HUR22'),
    ('V7_PI_S1_TS_AND_XA',          core4 + ['g_pw_trend_slope_with', 'g_pw_xa_unanimity_with'], 'HUR22'),
    ('V7_PI_S1_TS_AND_XA_BTC_ETH',  core4 + ['g_pw_trend_slope_with', 'g_pw_xa_btc_eth_with'], 'HUR22'),
    ('V7_PI_S1_TS_AND_BTC_RF',      core4 + ['g_pw_trend_slope_with', 'g_pw_btc_rf_with'], 'HUR22'),
    ('V7_PI_S1_TS_AND_BTC_15M',     core4 + ['g_pw_trend_slope_with', 'g_pw_btc_15m_trend_with'], 'HUR22'),
    ('V7_PI_S1_TS_AND_F7_MOMO',     core4 + ['g_pw_trend_slope_with', 'g_pw_f7_rsi_momentum_with'], 'HUR22'),
    ('V7_PI_S1_TS_AND_MARKOV',      core4 + ['g_pw_trend_slope_with', 'g_pw_markov_with'], 'HUR22'),
    ('V7_PI_S1_TS_AND_MULTI_TF',    core4 + ['g_pw_trend_slope_with', 'g_pw_multi_tf_align_with'], 'HUR22'),
    ('V7_PI_S1_M1V_AND_XA',         core4 + ['g_pw_m1v_with', 'g_pw_xa_unanimity_with'], 'HUR22'),
    ('V7_PI_S1_M1V_AND_BTC_RF',     core4 + ['g_pw_m1v_with', 'g_pw_btc_rf_with'], 'HUR22'),
    ('V7_PI_S1_M1V_AND_MARKOV',     core4 + ['g_pw_m1v_with', 'g_pw_markov_with'], 'HUR22'),
    ('V7_PI_S1_XA_AND_F7_MOMO',     core4 + ['g_pw_xa_unanimity_with', 'g_pw_f7_rsi_momentum_with'], 'HUR22'),
    ('V7_PI_S1_XA_AND_BTC_15M',     core4 + ['g_pw_xa_unanimity_with', 'g_pw_btc_15m_trend_with'], 'HUR22'),
    ('V7_PI_S1_BTC_RF_AND_BTC_15M', core4 + ['g_pw_btc_rf_with', 'g_pw_btc_15m_trend_with'], 'HUR22'),
]

# 3-gate PW stack — TRIPLE PW
v7_path_i_triple = [
    ('V7_PI_S1_TS_M1V_XA',          core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with', 'g_pw_xa_unanimity_with'], 'HUR22'),
    ('V7_PI_S1_TS_M1V_BTC_RF',      core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with', 'g_pw_btc_rf_with'], 'HUR22'),
    ('V7_PI_S1_TS_M1V_F7',          core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with', 'g_pw_f7_rsi_momentum_with'], 'HUR22'),
    ('V7_PI_S1_TS_XA_BTC_15M',      core4 + ['g_pw_trend_slope_with', 'g_pw_xa_unanimity_with', 'g_pw_btc_15m_trend_with'], 'HUR22'),
    ('V7_PI_S1_TS_M1V_MARKOV',      core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with', 'g_pw_markov_with'], 'HUR22'),
    ('V7_PI_S1_TRIPLE_ALIGN',       core4 + ['g_pw_triple_align'], 'HUR22'),
    ('V7_PI_S1_TS_M1V_XA_F7',       core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with', 'g_pw_xa_unanimity_with', 'g_pw_f7_rsi_momentum_with'], 'HUR22'),
]

# Path I + DOWN-only asymmetric
v7_path_i_down = [
    ('V7_PI_DOWN_TS_M1V',           core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with', 'g_dir_down'], 'HUR22'),
    ('V7_PI_DOWN_M1V_XA',           core4 + ['g_pw_m1v_with', 'g_pw_xa_unanimity_with', 'g_dir_down'], 'HUR22'),
    ('V7_PI_DOWN_TS_BTC_RF',        core4 + ['g_pw_trend_slope_with', 'g_pw_btc_rf_with', 'g_dir_down'], 'HUR22'),
    ('V7_PI_UP_TS_M1V',             core4 + ['g_pw_trend_slope_with', 'g_pw_m1v_with', 'g_dir_up'], 'HUR22'),
]

# ============================================================
# Path G — VOL REGIME SPECIALIZATION
# ============================================================
v7_path_g = [
    ('V7_PG_VOL_EXTREME_TS',       core4 + ['g_pw_trend_slope_with', 'g_vol_extreme_high'], 'HUR22'),
    # Replace g_vol_high with g_vol_extreme_high in core
    ('V7_PG_VOL_EXTREME_CORE',     ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_extreme_high','g_pw_trend_slope_with'], 'HUR22'),
    ('V7_PG_RV_ABOVE_MED',         core4 + ['g_pw_trend_slope_with', 'g_rv_60_above_med'], 'HUR22'),
    ('V7_PG_RV_BELOW_MED',         core4 + ['g_pw_trend_slope_with', 'g_rv_60_below_med'], 'HUR22'),
]

# ============================================================
# Path H — HURST VARIANTS
# ============================================================
v7_path_h = [
    ('V7_PH_HURST_REG_TS',         core4 + ['g_pw_trend_slope_with', 'g_hurst_regime_with'], 'HUR22'),
    ('V7_PH_HURST_TR_M1V',         core4 + ['g_pw_m1v_with', 'g_hurst_trending'], 'HUR22'),
    ('V7_PH_HURST_STRONG_TS',      core4 + ['g_pw_trend_slope_with', 'g_hurst_strong_trending'], 'HUR22'),
]

# ============================================================
# Path C — CROSS-ASSET ONLY (NO ETH-derived trend gates)
# ============================================================
v7_path_c = [
    ('V7_PC_BTC15M_ALONE',         core4 + ['g_pw_btc_15m_trend_with'], 'HUR22'),
    ('V7_PC_BTC_RF_ALONE',         core4 + ['g_pw_btc_rf_with'], 'HUR22'),
    ('V7_PC_BTC_BOTH',             core4 + ['g_pw_btc_15m_trend_with', 'g_pw_btc_rf_with'], 'HUR22'),
    ('V7_PC_XA_BTC15M',            core4 + ['g_pw_xa_unanimity_with', 'g_pw_btc_15m_trend_with'], 'HUR22'),
]

# Combine all explicit stacks
all_stacks = (v6_baselines + v7_path_i_single + v7_path_i_double + v7_path_i_triple
              + v7_path_i_down + v7_path_g + v7_path_h + v7_path_c)

# Deduplicate by gate-set
seen = set()
unique_stacks = []
for name, gates, cohort in all_stacks:
    key = (tuple(sorted(gates)), cohort)
    if key in seen: continue
    seen.add(key)
    unique_stacks.append((name, gates, cohort))
log(f"Total unique stacks to test: {len(unique_stacks)}")

# ============================================================
# EVALUATE ALL STACKS
# ============================================================
results = []
for name, stack, cohort in unique_stacks:
    missing = [g for g in stack if g not in fires.columns]
    if missing:
        log(f"  {name}: SKIP — missing {missing}")
        continue
    mask = fires[stack].all(axis=1) > 0
    if mask.sum() == 0:
        log(f"  {name}: no fires")
        continue
    m = gated_metrics(fires, mask, cohort)
    if m is None: continue
    sub = fires[mask].copy()
    train_m, val_m, lock_m = cohort_split(sub, cohort)
    p, bm, ci_lo, ci_hi = bootstrap_p(sub[lock_m])
    m['bootstrap_p'] = p
    m['boot_ci_lo_$25'] = ci_lo
    m['boot_ci_hi_$25'] = ci_hi
    m['days_lock'] = len(sub[lock_m].date.unique())
    passes, fails = passes_v7(m)
    m['passes_v7'] = passes
    m['fails'] = ';'.join(fails)
    m['sleeve_id'] = name
    m['gate_stack'] = '&'.join(stack)
    m['cohort'] = cohort
    m['n_gates'] = len(stack)
    results.append(m)
    flag = 'PASS' if passes else 'fail'
    log(f"  [{flag}] {name:<35} ({cohort}, {len(stack)}g): n={m['n_full']:>5}|lock={m['n_lock']:>4}|WR={m['wr_lock']:.3f}|dpt=${m['dpt_lock_25']:>6.2f}|DD=${m['max_dd_25']:>5.0f}|LS={m['loss_streak']:>2}|p={m['bootstrap_p']:.3f}")

df_res = pd.DataFrame(results)
df_res = df_res.sort_values('dpt_lock_25', ascending=False)
df_res['v7_score'] = df_res.dpt_lock_25 * np.sqrt(np.maximum(0, df_res.n_lock))
df_res.to_csv(f"{OUT}/all_candidates_v7.csv", index=False)
log(f"\nTotal stacks evaluated: {len(df_res)}")
log(f"Passing V7 bar: {df_res.passes_v7.sum()}")

df_pass = df_res[df_res.passes_v7 == True].copy().sort_values('v7_score', ascending=False)
df_pass.to_csv(f"{OUT}/passing_v7.csv", index=False)
log(f"WROTE passing_v7.csv ({len(df_pass)} passing)")

# ============================================================
# Path A — WEIGHTED ENSEMBLES (separate evaluation)
# ============================================================
log("\n" + "="*60)
log("Path A: Weighted ensemble — gate-sum threshold sleeves")
log("="*60)

# Weight V6/V7 winners highest. Score each fire by weighted gate sum.
# Use universal & PW winners with weights tuned by V6 train-window WR-lift.
gate_weights = {
    'g_tr_stack_full_with': 1.5,
    'g_above_1h_dailyvwap_with': 1.2,
    'g_offset_early': 1.0,        # always 1 for ETH 15m offset 60s fires
    'g_vol_high': 1.0,
    'g_pw_trend_slope_with': 1.3,
    'g_pw_m1v_with': 1.0,
    'g_pw_xa_unanimity_with': 1.1,
    'g_pw_btc_15m_trend_with': 0.9,
    'g_pw_f7_rsi_momentum_with': 0.7,
    'g_pw_markov_with': 0.8,
    'g_hurst_regime_with': 0.6,
    'g_mp_skew_with': 0.5,
    'g_ribbon_slope_with': 0.5,
    'g_above_1h_dailyvwap_with': 0.0,  # already in core
}

# Compute gate sum per row
gate_keys = list(gate_weights.keys())
# Remove duplicates by going through dict
gate_keys = list({k: 1 for k in gate_keys}.keys())
log(f"  ensemble gates: {gate_keys}")
present = [g for g in gate_keys if g in fires.columns]
weights_arr = np.array([gate_weights[g] for g in present])
log(f"  present: {len(present)}/{len(gate_keys)} | weights: {weights_arr}")
fires['ensemble_score'] = (fires[present].astype(float).values @ weights_arr)
max_score = fires['ensemble_score'].max()
log(f"  max ensemble_score: {max_score:.2f}")
log(f"  ensemble_score quantiles: {fires.ensemble_score.quantile([0.5, 0.75, 0.9, 0.95, 0.99]).to_dict()}")

# Test thresholds and report
ensemble_results = []
for thr in [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]:
    mask = fires.ensemble_score >= thr
    if mask.sum() == 0: continue
    m = gated_metrics(fires, mask, 'HUR22')
    if m is None: continue
    sub = fires[mask].copy()
    _, _, lock_m = cohort_split(sub, 'HUR22')
    p, _, ci_lo, ci_hi = bootstrap_p(sub[lock_m])
    m['bootstrap_p'] = p
    m['boot_ci_lo_$25'] = ci_lo
    m['boot_ci_hi_$25'] = ci_hi
    passes, fails = passes_v7(m)
    m['passes_v7'] = passes
    m['fails'] = ';'.join(fails)
    m['sleeve_id'] = f'V7_PA_ENSEMBLE_THR_{thr}'
    m['gate_stack'] = f'ensemble_score>={thr}'
    m['cohort'] = 'HUR22'
    m['n_gates'] = len(present)
    m['threshold'] = thr
    ensemble_results.append(m)
    flag = 'PASS' if passes else 'fail'
    log(f"  [{flag}] thr={thr:>4.1f}: n={m['n_full']:>5}|lock={m['n_lock']:>4}|WR={m['wr_lock']:.3f}|dpt=${m['dpt_lock_25']:>6.2f}|DD=${m['max_dd_25']:>5.0f}|p={p:.3f}")

if ensemble_results:
    df_ens = pd.DataFrame(ensemble_results)
    df_ens['v7_score'] = df_ens.dpt_lock_25 * np.sqrt(np.maximum(0, df_ens.n_lock))
    df_ens.to_csv(f"{OUT}/ensemble_candidates_v7.csv", index=False)
    # Merge into main results
    df_res = pd.concat([df_res, df_ens], ignore_index=True, sort=False)
    df_res = df_res.sort_values('v7_score', ascending=False, na_position='last')

# ============================================================
# FINAL TOP CANDIDATES
# ============================================================
log("\n" + "="*60)
log("TOP CANDIDATES BY V7 SCORE")
log("="*60)
df_pass_all = df_res[df_res.passes_v7 == True].copy().sort_values('v7_score', ascending=False)
top10 = df_pass_all.head(10)
for _, r in top10.iterrows():
    log(f"  {r.sleeve_id:<35} | score={r.v7_score:>6.1f} | n_lock={int(r.n_lock):>4} | WR={r.wr_lock:.3f} | dpt=${r.dpt_lock_25:.2f} | p={r.bootstrap_p:.3f}")

df_res.to_csv(f"{OUT}/all_candidates_v7.csv", index=False)
df_pass_all.to_csv(f"{OUT}/passing_v7.csv", index=False)
log(f"\nFINAL passing V7: {len(df_pass_all)}")
log("DONE")
