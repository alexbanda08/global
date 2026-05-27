"""Greedy beam search for V6 ETH 15m.

Starts from g_offset_early as anchor (V5 lesson). Adds 3-7 more gates via beam
search maximizing v6_score = dpt_lock × sqrt(n_lock) under V6 pass-bar.

We test 4 atom pools by cohort:
  POOL_HUR22 = full vocabulary (22d coverage)
  POOL_REG28 = no hurst/sms (28d coverage)
  POOL_MP31  = no regime (31d coverage)
  POOL_FULL  = 1h vwap + offsets + pre-window F7 only (33d)
"""
import os, time, warnings, json
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v6"

log("loading v6 enriched")
fires = pd.read_parquet(f"{OUT}/eth_15m_enriched_v6.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date

def cohort_split(df, cohort):
    if cohort == 'FULL':
        train = df.date < pd.to_datetime('2026-05-15').date()
        val   = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-22').date())
        lock  = df.date >= pd.to_datetime('2026-05-22').date()
    elif cohort == 'MP31':
        train = df.date < pd.to_datetime('2026-05-15').date()
        val   = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-21').date())
        lock  = (df.date >= pd.to_datetime('2026-05-21').date()) & (df.date <= pd.to_datetime('2026-05-25').date())
    elif cohort == 'REG28':
        train = (df.date >= pd.to_datetime('2026-04-28').date()) & (df.date < pd.to_datetime('2026-05-14').date())
        val   = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-20').date())
        lock  = (df.date >= pd.to_datetime('2026-05-20').date()) & (df.date <= pd.to_datetime('2026-05-25').date())
    elif cohort == 'HUR22':
        train = (df.date >= pd.to_datetime('2026-05-01').date()) & (df.date < pd.to_datetime('2026-05-14').date())
        val   = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-18').date())
        lock  = (df.date >= pd.to_datetime('2026-05-18').date()) & (df.date <= pd.to_datetime('2026-05-22').date())
    return train, val, lock

def metrics_for_stack(df, stack, cohort, n_iter_boot=500):
    mask = df[stack].all(axis=1) > 0
    if mask.sum() == 0:
        return None
    sub = df[mask].copy()
    train_m, val_m, lock_m = cohort_split(sub, cohort)
    out = {
        'n_full': len(sub),
        'wr_full': sub.won.mean(),
        'n_train': train_m.sum(),
        'wr_train': sub[train_m].won.mean() if train_m.sum() else 0,
        'dpt_train': sub[train_m].pnl_legacy_usd.mean() if train_m.sum() else 0,
        'n_val': val_m.sum(),
        'wr_val': sub[val_m].won.mean() if val_m.sum() else 0,
        'dpt_val': sub[val_m].pnl_legacy_usd.mean() if val_m.sum() else 0,
        'n_lock': lock_m.sum(),
        'wr_lock': sub[lock_m].won.mean() if lock_m.sum() else 0,
        'dpt_lock_25': sub[lock_m].pnl_legacy_usd.mean() if lock_m.sum() else 0,
        'sum_full_25': sub.pnl_legacy_usd.sum(),
        'sum_lock_25': sub[lock_m].pnl_legacy_usd.sum(),
        'days_lock': sub[lock_m].date.nunique(),
    }
    # Streak + DD
    eq = sub.sort_values('fire_us').pnl_legacy_usd.cumsum().values
    peak = np.maximum.accumulate(eq); dd = peak - eq
    out['max_dd_25'] = float(dd.max()) if len(dd) else 0.0
    losses = (sub.sort_values('fire_us').won == 0).astype(int).values
    max_streak, cur = 0, 0
    for l in losses:
        cur = cur + 1 if l else 0
        if cur > max_streak: max_streak = cur
    out['loss_streak'] = max_streak
    daily = sub.groupby('date').pnl_legacy_usd.sum()
    out['sharpe_daily'] = (daily.mean()/daily.std()*np.sqrt(252)) if (len(daily)>1 and daily.std()>0) else 0
    out['fires_per_day'] = out['n_full'] / max(1, sub.date.nunique())
    out['fires_per_day_lock'] = out['n_lock'] / max(1, out['days_lock'])
    # Bootstrap p
    if lock_m.sum() > 0:
        daily_lock = sub[lock_m].groupby('date').pnl_legacy_usd.sum().values
        if len(daily_lock) > 1:
            rng = np.random.default_rng(42)
            boot = np.array([daily_lock[rng.integers(0,len(daily_lock),len(daily_lock))].sum() for _ in range(n_iter_boot)])
            out['bootstrap_p'] = (boot <= 0).mean()
            out['boot_ci_lo'] = np.percentile(boot, 2.5)
            out['boot_ci_hi'] = np.percentile(boot, 97.5)
        else:
            out['bootstrap_p'] = 1.0
            out['boot_ci_lo'] = 0.0
            out['boot_ci_hi'] = 0.0
    else:
        out['bootstrap_p'] = 1.0
        out['boot_ci_lo'] = 0.0
        out['boot_ci_hi'] = 0.0
    out['v6_score'] = out['dpt_lock_25'] * np.sqrt(max(0, out['n_lock']))
    return out

def passes_v6(m):
    if m is None: return False
    return (m['n_lock'] >= 5 and m['n_full'] <= 2000 and m['wr_lock'] >= 0.65
            and m['dpt_lock_25'] >= 4.0 and m['max_dd_25'] <= 500 and m['loss_streak'] <= 14
            and m['fires_per_day'] <= 50)

# Atom pools by cohort
POOLS = {
    'HUR22': [
        # core anchors
        'g_offset_early', 'g_above_1h_dailyvwap_with',
        # tr/ribbon
        'g_tr_stack_full_with', 'g_tr_stack_with', 'g_tr_above_cloud', 'g_tr_above_pp', 'g_tr_within_adr',
        'g_ribbon_slope_with', 'g_tight_ribbon',
        # range filter / momentum
        'g_rf_with', 'g_rf_fresh', 'g_rf_aged', 'g_rf_strong',
        # bb/stoch/mfi/cci
        'g_bb_pos_with', 'g_stoch_with', 'g_mfi_with', 'g_cci_with',
        # regime
        'g_trend_slope_with', 'g_trend_slope_strong_with', 'g_adx_strong', 'g_atr_high',
        # vol/hurst
        'g_vol_high', 'g_vol_expanding', 'g_hurst_trending',
        # microprice
        'g_mp_no_extreme_150', 'g_mp_skew_with', 'g_mp_weighted_skew_with', 'g_mp_imbalance_with', 'g_mp_change_with',
        # sms / markov
        'g_markov_with', 'g_multi_tf_align_with', 'g_cvd_with', 'g_trend_strong_60',
        # PW (pre-window)
        'g_pw_markov_with', 'g_pw_cvd_with', 'g_pw_trend_strong_60', 'g_pw_trend_slope_with',
        'g_pw_f7_rsi_momentum_with', 'g_pw_multi_tf_align_with', 'g_pw_adx_strong',
        # parent TF
        'g_near_pivot',
        # composable
        'g_book_supports_25', 'g_entry_vwap_in_10_65', 'g_entry_vwap_in_30_70',
        # TOD
        'g_hod_european_morning', 'g_hod_us_morning',
    ],
    'MP31': [
        'g_offset_early', 'g_above_1h_dailyvwap_with',
        'g_tr_stack_full_with', 'g_tr_stack_with', 'g_tr_above_cloud', 'g_tr_above_pp',
        'g_ribbon_slope_with', 'g_tight_ribbon', 'g_rf_with', 'g_rf_aged', 'g_rf_strong',
        'g_bb_pos_with', 'g_stoch_with', 'g_mfi_with', 'g_cci_with',
        'g_trend_slope_with', 'g_trend_slope_strong_with', 'g_adx_strong', 'g_atr_high',
        'g_mp_no_extreme_150', 'g_mp_skew_with', 'g_mp_weighted_skew_with', 'g_mp_imbalance_with', 'g_mp_change_with',
        'g_pw_trend_slope_with', 'g_pw_f7_rsi_momentum_with', 'g_pw_adx_strong',
        'g_near_pivot', 'g_book_supports_25', 'g_entry_vwap_in_10_65', 'g_entry_vwap_in_30_70',
        'g_hod_european_morning', 'g_hod_us_morning',
    ],
    'REG28': [
        'g_offset_early', 'g_above_1h_dailyvwap_with',
        'g_tr_stack_full_with', 'g_tr_stack_with', 'g_tr_above_cloud', 'g_tr_above_pp',
        'g_ribbon_slope_with', 'g_rf_with', 'g_rf_aged', 'g_rf_strong',
        'g_bb_pos_with', 'g_stoch_with',
        'g_trend_slope_with', 'g_trend_slope_strong_with', 'g_adx_strong', 'g_atr_high',
        'g_pw_trend_slope_with', 'g_pw_f7_rsi_momentum_with',
        'g_near_pivot', 'g_book_supports_25', 'g_entry_vwap_in_10_65',
        'g_hod_european_morning', 'g_hod_us_morning',
    ],
    'FULL': [
        'g_offset_early', 'g_above_1h_dailyvwap_with',
        'g_tr_stack_full_with', 'g_tr_stack_with', 'g_tr_above_pp', 'g_tr_above_cloud',
        'g_ribbon_slope_with', 'g_rf_with', 'g_rf_aged', 'g_rf_strong',
        'g_bb_pos_with', 'g_stoch_with', 'g_mfi_with', 'g_cci_with',
        'g_pw_f7_rsi_momentum_with',
        'g_near_pivot', 'g_book_supports_25', 'g_entry_vwap_in_10_65',
        'g_hod_european_morning', 'g_hod_us_morning',
    ],
}

def greedy_beam(pool, cohort, k_target=5, beam_size=4, seed_stack=None):
    """Greedy beam: at each step, take top beam_size stacks by v6_score that pass V6 bar.
    Continue extending until stack reaches k_target or beam empties.
    """
    seed = seed_stack if seed_stack else ['g_offset_early','g_above_1h_dailyvwap_with']
    log(f"  cohort {cohort}: seed {seed}")
    current_beams = [(seed, metrics_for_stack(fires, seed, cohort))]
    all_found = []

    for k in range(len(seed)+1, k_target+1):
        next_candidates = []
        for stack, _ in current_beams:
            for atom in pool:
                if atom in stack:
                    continue
                new_stack = stack + [atom]
                m = metrics_for_stack(fires, new_stack, cohort)
                if m is None:
                    continue
                if m['n_lock'] >= 5 and m['v6_score'] > 0:
                    next_candidates.append((new_stack, m))
        if not next_candidates:
            log(f"  k={k}: no extensions")
            break
        # Sort by v6_score, take top beam_size that pass
        next_candidates.sort(key=lambda x: x[1]['v6_score'], reverse=True)
        # Take only passing ones (for next round), but keep all for record
        for stack, m in next_candidates:
            if passes_v6(m):
                all_found.append((stack, m, cohort, k))
        current_beams = next_candidates[:beam_size]
        log(f"  k={k}: {len(next_candidates)} extensions, top score {next_candidates[0][1]['v6_score']:.1f}, beam size {len(current_beams)}")

    return all_found

# Run greedy per cohort
all_results = []
for cohort, pool in POOLS.items():
    log(f"=== greedy beam {cohort} ===")
    found = greedy_beam(pool, cohort, k_target=6, beam_size=5)
    for stack, m, c, k in found:
        m['cohort'] = c
        m['gate_stack'] = '&'.join(stack)
        m['n_gates'] = k
        m['sleeve_id'] = f"V6_GR_{c}_k{k}_n{m['n_lock']}_dpt{int(m['dpt_lock_25']*10)}"
        m['passes_v6'] = passes_v6(m)
        all_results.append(m)

df = pd.DataFrame(all_results)
log(f"Greedy total found: {len(df)}")
df = df.sort_values('v6_score', ascending=False).reset_index(drop=True)
df.to_csv(f"{OUT}/greedy_results_v6.csv", index=False)

# Dedup near-identical stacks: same gates same n
log("\nTop 20 unique greedy results (by v6_score, passing):")
seen_gates = set()
shown = 0
for _, r in df[df.passes_v6==True].iterrows():
    gset = frozenset(r.gate_stack.split('&'))
    if gset in seen_gates:
        continue
    seen_gates.add(gset)
    shown += 1
    if shown > 25: break
    log(f"  [{r.cohort}/k{r.n_gates}] n={int(r.n_full)} n_lk={int(r.n_lock)} WR_lk={r.wr_lock:.3f} dpt=${r.dpt_lock_25:.2f} DD=${r.max_dd_25:.0f} LS={int(r.loss_streak)} p={r.bootstrap_p:.3f} | {r.gate_stack}")

log("DONE")
