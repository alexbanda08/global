"""V6 gate-stack search for ETH 15m.

Mission: extend V5 winning stacks. V5 winners:
  - S1 (HIGH): g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high
    -> n=26 lockbox, WR 88.5%, $/tr +$10.53 (22D cohort, May 18-22)
  - S2 (MED): g_mp_skew_with & g_offset_early & g_above_1h_dailyvwap_with
    -> n=152 lockbox, WR 63.8%, $/tr +$5.98 (31D cohort)
  - S5 (MED): g_tr_stack_full_with & g_offset_early & g_above_1h_dailyvwap_with
    -> n=60 lockbox, WR 75.0%, $/tr +$4.69 (31D cohort)

V6 relaxes: WR >=65%, LS<=14, $/tr>=$4, n 30-2000, DD<=$500. Drops $250 gate.

Approach:
  A. Validate V5 S1/S2/S5 under V6 bar
  B. Extend S1 with pre-window anchors (swap g_markov_with for g_pw_markov_with etc.)
  C. Add pre-window F7 RSI momentum gates
  D. Composable stacking — try 4-7 gates with conviction-bucket grouping
  E. Asymmetric direction sleeves (UP-only, DOWN-only)
  F. Time-of-day filter sleeves
"""
import os, time, warnings, json
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
from itertools import combinations
from collections import defaultdict

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v6"
LOG  = f"{OUT}/_logs"
os.makedirs(LOG, exist_ok=True)

log("loading v6 enriched")
fires = pd.read_parquet(f"{OUT}/eth_15m_enriched_v6.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
log(f"shape: {fires.shape}")

# ---- Cohort definitions (when which gates have data) ----
# Same as V5: HUR22 (22d), MP31 (31d), REG28 (28d), FULL (33d)
# Plus V6 pre-window cohorts:
#   PW_HUR22 (22d): pw_sms gates + hurst (the strictest)
#   PW_REG28 (28d): pw_regime + 1h vwap (no sms)
#   PW_FULL (33d): pw_f7_rsi + 1h vwap + microprice etc

# v3 fires span Apr 24 -> May 26 (33d)
# Compute datetime midnight bucket
fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date

def cohort_split(df, cohort):
    """Return (train, val, lockbox) date masks per cohort."""
    if cohort == 'FULL':
        # 33d: train Apr 24-May 15 (21d), val May 15-22 (7d), lock May 22-26 (4d)
        train = df.date < pd.to_datetime('2026-05-15').date()
        val   = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-22').date())
        lock  = df.date >= pd.to_datetime('2026-05-22').date()
    elif cohort == 'MP31':
        # 31d (Apr 24 - May 25): train 21d, val 6d, lock 4d
        train = df.date < pd.to_datetime('2026-05-15').date()
        val   = (df.date >= pd.to_datetime('2026-05-15').date()) & (df.date < pd.to_datetime('2026-05-21').date())
        lock  = (df.date >= pd.to_datetime('2026-05-21').date()) & (df.date <= pd.to_datetime('2026-05-25').date())
    elif cohort == 'REG28':
        # 28d (Apr 28 - May 25): train 16d, val 6d, lock 5d
        train = (df.date >= pd.to_datetime('2026-04-28').date()) & (df.date < pd.to_datetime('2026-05-14').date())
        val   = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-20').date())
        lock  = (df.date >= pd.to_datetime('2026-05-20').date()) & (df.date <= pd.to_datetime('2026-05-25').date())
    elif cohort == 'HUR22':
        # 22d (May 1 - May 22): train 13d, val 4d, lock 4d
        train = (df.date >= pd.to_datetime('2026-05-01').date()) & (df.date < pd.to_datetime('2026-05-14').date())
        val   = (df.date >= pd.to_datetime('2026-05-14').date()) & (df.date < pd.to_datetime('2026-05-18').date())
        lock  = (df.date >= pd.to_datetime('2026-05-18').date()) & (df.date <= pd.to_datetime('2026-05-22').date())
    else:
        raise ValueError(cohort)
    return train, val, lock

def evaluate(df_sub, sub_pnl_col='pnl_legacy_usd'):
    """Compute metrics dict for a gated subset."""
    n = len(df_sub)
    if n == 0:
        return None
    wr = df_sub.won.mean()
    pnl_per_dollar = df_sub[sub_pnl_col].sum() / max(1, n)
    # $25 PnL approx via scaling pnl_legacy_usd which is at $1 nominal
    # Confirm: pnl_legacy_usd convention — check below
    return {
        'n': n,
        'wr': wr,
        'sum_pnl': df_sub[sub_pnl_col].sum(),
        'dpt': pnl_per_dollar,
    }

# Quick: verify pnl_legacy_usd magnitude. If it's at $25 already, dpt is the $/tr at $25.
# If it's at $1, we multiply by 25 for $25.
log(f"pnl_legacy_usd describe: {fires.pnl_legacy_usd.describe().to_dict()}")
# Given v3 fires from full_window_validation_v2.py — should be PnL at $25 nominal? Check by sum:
mean_abs = fires.pnl_legacy_usd.abs().mean()
log(f"mean |pnl_legacy_usd|: {mean_abs:.4f}")
# If mean abs is around ~10-15, it's $25 stake (since vwap ~ 0.4-0.6 → losing $10-15 expected).
# If mean abs is around ~0.4-0.5, it's $1 stake.

# Determine the dollar nominal:
if mean_abs > 1:
    STAKE_NOMINAL_25 = 1.0  # already at $25 stake equivalent
    log("  pnl_legacy_usd appears to be at $25 stake (no scaling needed)")
else:
    STAKE_NOMINAL_25 = 25.0  # scale by 25
    log("  pnl_legacy_usd appears to be at $1 stake (will multiply by 25)")

def gated_metrics(df, mask, cohort_split_fn=None):
    """Return train/val/lock + full metrics dict on a gated subset."""
    sub = df[mask].copy()
    if len(sub) == 0:
        return None
    out = {'n_full': len(sub), 'wr_full': sub.won.mean()}
    out['sum_pnl_full'] = sub.pnl_legacy_usd.sum() * STAKE_NOMINAL_25
    out['dpt_full_25'] = (sub.pnl_legacy_usd.mean() if len(sub) else 0) * STAKE_NOMINAL_25
    if cohort_split_fn is not None:
        train_mask, val_mask, lock_mask = cohort_split_fn(sub)
        for split_name, m in [('train',train_mask),('val',val_mask),('lock',lock_mask)]:
            sub_s = sub[m]
            out[f'n_{split_name}'] = len(sub_s)
            out[f'wr_{split_name}'] = sub_s.won.mean() if len(sub_s) else 0
            out[f'dpt_{split_name}_25'] = (sub_s.pnl_legacy_usd.mean() if len(sub_s) else 0) * STAKE_NOMINAL_25
            out[f'sum_pnl_{split_name}'] = sub_s.pnl_legacy_usd.sum() * STAKE_NOMINAL_25
        # Loss streak + DD on full subset for the candidate (V6 §3 — DD/streak from sleeve's actual fires)
        eq = (sub.sort_values('fire_us').pnl_legacy_usd.cumsum() * STAKE_NOMINAL_25).values
        peak = np.maximum.accumulate(eq)
        dd = peak - eq
        out['max_dd_25'] = float(dd.max()) if len(dd) else 0.0
        # Loss streak: consecutive losses
        losses = (sub.sort_values('fire_us').won == 0).astype(int).values
        max_streak = 0; cur = 0
        for l in losses:
            cur = cur + 1 if l else 0
            if cur > max_streak: max_streak = cur
        out['loss_streak'] = max_streak
        # Sharpe: daily returns
        daily = sub.groupby('date').pnl_legacy_usd.sum() * STAKE_NOMINAL_25
        if len(daily) > 1 and daily.std() > 0:
            out['sharpe_daily'] = daily.mean() / daily.std() * np.sqrt(252)
        else:
            out['sharpe_daily'] = 0
        out['fires_per_day'] = out['n_full'] / max(1, len(sub.date.unique()))
    return out

def bootstrap_p_lockbox(df_sub, n_iter=1000, rng=None):
    """Daily-clustered bootstrap p-value for sum_pnl_lock > 0."""
    if rng is None:
        rng = np.random.default_rng(42)
    if len(df_sub) == 0:
        return 1.0, 0.0, 0.0, 0.0
    daily = df_sub.groupby('date').pnl_legacy_usd.sum().values * STAKE_NOMINAL_25
    if len(daily) <= 1:
        return 1.0, 0.0, 0.0, 0.0
    # Resample days with replacement
    boot_sums = np.empty(n_iter)
    n_days = len(daily)
    for i in range(n_iter):
        idx = rng.integers(0, n_days, n_days)
        boot_sums[i] = daily[idx].sum()
    # p = fraction of boot sums <= 0
    p = (boot_sums <= 0).mean()
    return p, boot_sums.mean(), np.percentile(boot_sums, 2.5), np.percentile(boot_sums, 97.5)

# ===== PASS V6 BAR FUNC =====
def passes_v6_bar(metrics):
    """V6 sniper bar — relaxed."""
    if metrics is None: return False, []
    fails = []
    n_lock = metrics.get('n_lock', 0)
    wr_lock = metrics.get('wr_lock', 0)
    dpt_lock = metrics.get('dpt_lock_25', 0)
    n_full = metrics.get('n_full', 0)
    dd = metrics.get('max_dd_25', float('inf'))
    streak = metrics.get('loss_streak', float('inf'))
    fpd = metrics.get('fires_per_day', 0)

    if n_lock < 5: fails.append(f'n_lock<5 ({n_lock})')
    if n_full > 2000: fails.append(f'n_full>2000 ({n_full})')
    if wr_lock < 0.65: fails.append(f'wr_lock<0.65 ({wr_lock:.3f})')
    if dpt_lock < 4.0: fails.append(f'dpt_lock<$4 ({dpt_lock:.2f})')
    if dd > 500: fails.append(f'dd>$500 (${dd:.0f})')
    if streak > 14: fails.append(f'streak>14 ({streak})')
    if fpd > 50: fails.append(f'fpd>50 ({fpd:.1f})')  # very relaxed
    return len(fails) == 0, fails

# ===== GATE STACKS TO TEST =====
# V5 reproductions (baseline)
v5_stacks = [
    # name, gate_list, cohort
    ('V5_S1_REPL', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high'], 'HUR22'),
    ('V5_S2_REPL', ['g_mp_skew_with','g_offset_early','g_above_1h_dailyvwap_with'], 'MP31'),
    ('V5_S3_REPL', ['g_above_1h_dailyvwap_with','g_offset_early','g_rf_aged','g_ribbon_slope_with'], 'FULL'),
    ('V5_S4_REPL', ['g_near_pivot','g_offset_early','g_above_1h_dailyvwap_with'], 'MP31'),
    ('V5_S5_REPL', ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with'], 'MP31'),
]

# V6 pre-window swap-ins (replace fire_us gates with ws_s gates)
v6_pw_swap = [
    # S1 with PW gates swapped in
    ('V6_S1_PW_F7_MOMO', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_pw_f7_rsi_momentum_with'], 'HUR22'),
    ('V6_S1_PW_TREND_SLOPE', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_pw_trend_slope_with'], 'HUR22'),
    ('V6_S1_PW_MARKOV', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_pw_markov_with'], 'HUR22'),
    ('V6_S1_PW_MULTI_TF', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_pw_multi_tf_align_with'], 'HUR22'),
    ('V6_S1_PW_CVD', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_pw_cvd_with'], 'HUR22'),
    # S5 (broader cohort, MP31) with PW
    ('V6_S5_PW_F7_MOMO', ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with','g_pw_f7_rsi_momentum_with'], 'MP31'),
    ('V6_S5_PW_TREND_SLOPE', ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with','g_pw_trend_slope_with'], 'MP31'),
    # S2 + PW microprice/trend
    ('V6_S2_PW_F7_MOMO', ['g_mp_skew_with','g_offset_early','g_above_1h_dailyvwap_with','g_pw_f7_rsi_momentum_with'], 'MP31'),
    ('V6_S2_PW_TREND_SLOPE', ['g_mp_skew_with','g_offset_early','g_above_1h_dailyvwap_with','g_pw_trend_slope_with'], 'MP31'),
    # S4 + PW
    ('V6_S4_PW_F7_MOMO', ['g_near_pivot','g_offset_early','g_above_1h_dailyvwap_with','g_pw_f7_rsi_momentum_with'], 'MP31'),
]

# V6 new high-conviction stacks (5-7 gates, designed)
v6_hi_conv = [
    ('V6_HIQ_TR_VOL_F7_RSI', ['g_tr_stack_full_with','g_vol_high','g_above_1h_dailyvwap_with','g_offset_early','g_pw_f7_rsi_momentum_with','g_pw_trend_slope_with'], 'HUR22'),
    ('V6_HIQ_TR_VOL_MARKOV_F7', ['g_tr_stack_full_with','g_vol_high','g_above_1h_dailyvwap_with','g_offset_early','g_markov_with','g_pw_f7_rsi_momentum_with'], 'HUR22'),
    ('V6_HIQ_TR_MARKOV_HURST', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_markov_with','g_hurst_trending','g_vol_high'], 'HUR22'),
    ('V6_HIQ_TR_RIBBON_HURST_F7', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_ribbon_slope_with','g_hurst_trending','g_pw_f7_rsi_momentum_with'], 'HUR22'),
]

# V6 directional-asymmetry (UP-only, DOWN-only on best stack)
v6_asymm = [
    ('V6_S1_UP_ONLY',   ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_dir_up'], 'HUR22'),
    ('V6_S1_DOWN_ONLY', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_dir_down'], 'HUR22'),
    ('V6_S5_UP_ONLY',   ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with','g_dir_up'], 'MP31'),
    ('V6_S5_DOWN_ONLY', ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with','g_dir_down'], 'MP31'),
]

# V6 time-of-day overlays
v6_tod = [
    ('V6_S5_HOD_EU',  ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with','g_hod_european_morning'], 'MP31'),
    ('V6_S5_HOD_US',  ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with','g_hod_us_morning'], 'MP31'),
    ('V6_S5_HOD_NIGHT', ['g_tr_stack_full_with','g_offset_early','g_above_1h_dailyvwap_with','g_hod_overnight'], 'MP31'),
]

# V6 wider net — Greedy beam through 30+ atom combos
v6_misc = [
    # Composable depth + vwap-band
    ('V6_S1_BOOK25', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_book_supports_25'], 'HUR22'),
    ('V6_S1_VWAP_1065', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_entry_vwap_in_10_65'], 'HUR22'),
    ('V6_S1_VWAP_3070', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_early','g_vol_high','g_entry_vwap_in_30_70'], 'HUR22'),
    # Test mid/late offsets
    ('V6_TRSTACK_VOL_MID', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_mid','g_vol_high'], 'HUR22'),
    ('V6_TRSTACK_VOL_LATE', ['g_tr_stack_full_with','g_above_1h_dailyvwap_with','g_offset_late','g_vol_high'], 'HUR22'),
]

all_stacks = v5_stacks + v6_pw_swap + v6_hi_conv + v6_asymm + v6_tod + v6_misc

# ===== EVALUATE ALL STACKS =====
results = []
for name, stack, cohort in all_stacks:
    # Build mask
    missing = [g for g in stack if g not in fires.columns]
    if missing:
        log(f"  {name}: SKIP — missing gates {missing}")
        continue
    mask = fires[stack].all(axis=1) > 0
    if mask.sum() == 0:
        log(f"  {name}: no fires")
        continue
    sub = fires[mask].copy()
    metrics = gated_metrics(fires, mask, lambda d: cohort_split(d, cohort))
    if metrics is None:
        continue
    # bootstrap p on lockbox
    train_m, val_m, lock_m = cohort_split(sub, cohort)
    sub_lock = sub[lock_m]
    p, bm, ci_lo, ci_hi = bootstrap_p_lockbox(sub_lock)
    metrics['bootstrap_p'] = p
    metrics['boot_ci_lo_$25'] = ci_lo
    metrics['boot_ci_hi_$25'] = ci_hi
    metrics['days_lock'] = len(sub_lock.date.unique())

    passes, fails = passes_v6_bar(metrics)
    metrics['passes_v6'] = passes
    metrics['fails'] = ';'.join(fails)
    metrics['sleeve_id'] = name
    metrics['gate_stack'] = '&'.join(stack)
    metrics['cohort'] = cohort
    metrics['n_gates'] = len(stack)
    results.append(metrics)
    flag = 'PASS' if passes else 'fail'
    log(f"  [{flag}] {name} ({cohort}, {len(stack)}g): n={metrics['n_full']:>5} | n_lock={metrics['n_lock']:>4} | WR_lock={metrics['wr_lock']:.3f} | dpt_lock=${metrics['dpt_lock_25']:>6.2f} | DD=${metrics['max_dd_25']:>5.0f} | LS={metrics['loss_streak']:>2} | p={metrics['bootstrap_p']:.4f}{' | '+metrics['fails'] if not passes else ''}")

df_results = pd.DataFrame(results)
df_results = df_results.sort_values('dpt_lock_25', ascending=False)
log(f"\nTotal stacks evaluated: {len(df_results)}")
log(f"Passing V6 bar: {df_results.passes_v6.sum()}")

# Save full results
df_results.to_csv(f"{OUT}/all_candidates_v6.csv", index=False)
log(f"WROTE all_candidates_v6.csv")

# Save passing subset
df_pass = df_results[df_results.passes_v6 == True].copy()
df_pass.to_csv(f"{OUT}/passing_v6.csv", index=False)
log(f"WROTE passing_v6.csv ({len(df_pass)} passing)")

# Top 10 by dpt_lock × sqrt(n_lock) (primary V6 objective)
df_results['v6_score'] = df_results.dpt_lock_25 * np.sqrt(np.maximum(0, df_results.n_lock))
top10 = df_results.sort_values('v6_score', ascending=False).head(10)
log("\nTOP 10 by v6_score (dpt_lock × sqrt(n_lock)):")
for _, r in top10.iterrows():
    log(f"  {r.sleeve_id:<35} | score={r.v6_score:>6.1f} | n_lock={int(r.n_lock):>4} | WR={r.wr_lock:.3f} | dpt=${r.dpt_lock_25:.2f} | passes={r.passes_v6}")

log("DONE")
