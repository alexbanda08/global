"""Deep dive on Sleeve #3 (off=240 UP, g_bb_pos_with + g_mp_no_extreme_150 + g_ret_2m_strong_with + g_tr_above_cloud).

Tasks:
1. Show per-gate ablation — what does each gate contribute?
2. Compare to BB-replaced-with-CCI version (sleeve #4)
3. Compare to lighter 3-leg version
4. Sleeve #3 vs V7 best (g_tr_above_ema200 + g_mp_skew_strong + g_rf_with @offset 600 DOWN)
5. Distribution of fires per day on lockbox — fire-rate sanity check.
6. Compute extended bootstrap p (10k) for full window.
7. Compute confidence intervals on $/tr.
"""
import os, sys, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading panel")
df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
total_secs = (df.fire_date.max() - df.fire_date.min()).total_seconds()
total_days = total_secs / 86400
t_min = df.fire_date.min()
t_train_end = t_min + pd.Timedelta(seconds=total_secs * 0.60)
t_val_end   = t_min + pd.Timedelta(seconds=total_secs * 0.80)
df['split'] = np.where(df.fire_date < t_train_end, 'train',
              np.where(df.fire_date < t_val_end, 'val', 'lockbox'))
lock_days = (df.fire_date.max()-t_val_end).total_seconds()/86400

PNL = 'pnl_legacy_usd'

def report_sleeve(sub_df, gates, label):
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates:
        if g and g in sub_df.columns:
            m &= (sub_df[g].values == 1)
    sub = sub_df[m].sort_values('fire_us').reset_index(drop=True)
    if len(sub) == 0:
        print(f"  {label:60s}  n=0")
        return
    pnl25 = sub[PNL].values * 25.0
    cum = pnl25.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    losses = (pnl25 < 0).astype(int)
    s=0; max_s=0
    for L in losses:
        if L==1: s+=1; max_s=max(max_s,s)
        else: s=0

    tr=sub[sub.split=='train']; vl=sub[sub.split=='val']; lk=sub[sub.split=='lockbox']
    print(f"  {label}")
    print(f"    full: n={len(sub):3} WR={sub.won.mean():.3f}  $/tr=${sub[PNL].mean()*25:+6.2f}  total=${pnl25.sum():+8.1f}  DD=${dd:+7.1f}  ls={max_s}")
    print(f"    train: n={len(tr):3} WR={tr.won.mean():.3f}  $/tr=${tr[PNL].mean()*25 if len(tr) else 0:+6.2f}")
    print(f"    val:   n={len(vl):3} WR={vl.won.mean():.3f}  $/tr=${vl[PNL].mean()*25 if len(vl) else 0:+6.2f}")
    print(f"    lock:  n={len(lk):3} WR={lk.won.mean():.3f}  $/tr=${lk[PNL].mean()*25 if len(lk) else 0:+6.2f}  total=${lk[PNL].sum()*25 if len(lk) else 0:+6.1f}")

# off=240 UP base subset
base = df[(df.fire_offset_s==240) & (df.direction=='UP')].copy()
print(f"\nBaseline off=240 UP: n={len(base)}, WR={base.won.mean():.3f}")

print("\n--- ABLATION: full sleeve and each gate dropped ---")
all_gates = ['g_bb_pos_with','g_mp_no_extreme_150','g_ret_2m_strong_with','g_tr_above_cloud']
report_sleeve(base, all_gates, "FULL: " + '+'.join(all_gates))
for drop in all_gates:
    rem = [g for g in all_gates if g != drop]
    report_sleeve(base, rem, f"DROP {drop}: " + '+'.join(rem))

print("\n--- VARIANTS: CCI vs BB swap ---")
report_sleeve(base, ['g_cci_with','g_mp_no_extreme_150','g_ret_2m_strong_with','g_tr_above_cloud'], "CCI variant (sleeve #4)")

# Per-leg vs intersection: which single gate is most predictive?
print("\n--- SINGLE-GATE eval on off=240 UP ---")
for g in all_gates:
    report_sleeve(base, [g], f"single {g}")

# 2-leg
print("\n--- 2-LEG ---")
for combo in [
    ('g_ret_2m_strong_with', 'g_tr_above_cloud'),
    ('g_bb_pos_with', 'g_tr_above_cloud'),
    ('g_mp_no_extreme_150', 'g_tr_above_cloud'),
    ('g_ret_2m_strong_with', 'g_mp_no_extreme_150'),
]:
    report_sleeve(base, combo, "+".join(combo))

# Compare to V7 best
print("\n--- V7 BEST baseline comparison ---")
v7_best = df[(df.fire_offset_s==600) & (df.direction=='DOWN')].copy()
report_sleeve(v7_best, ['g_tr_above_ema200','g_mp_skew_strong_with','g_rf_with'], "V7 best: g_tr_above_ema200+g_mp_skew_strong_with+g_rf_with @off=600 DOWN")

# Fire rate per day on lockbox for Sleeve 3
print("\n--- FIRE-RATE per day on LOCKBOX for Sleeve 3 ---")
sleeve3 = base
m = np.ones(len(sleeve3), dtype=bool)
for g in all_gates:
    m &= (sleeve3[g].values == 1)
sl = sleeve3[m]
sl_lock = sl[sl.split == 'lockbox']
print(f"  Lockbox: {len(sl_lock)} fires in {lock_days:.2f} days = {len(sl_lock)/lock_days:.2f}/day")
sl_lock_daily = sl_lock.groupby(sl_lock.fire_date.dt.date).size()
print(f"  Per-day breakdown: {sl_lock_daily.to_dict()}")

# Extended bootstrap p
def bootstrap_p(pnls, n_boot=10000, seed=42):
    if len(pnls) < 5: return 1.0
    rng = np.random.default_rng(seed)
    obs = pnls.mean()
    if obs <= 0: return 1.0
    n = len(pnls)
    centered = pnls - obs
    boots = np.array([centered[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return (boots >= obs).mean()

print("\n--- Extended bootstrap p (10k) ---")
sleeve3_full = sl[PNL].values * 25.0
sleeve3_lock = sl_lock[PNL].values * 25.0
print(f"  Full (n={len(sleeve3_full)}):  $/tr={sleeve3_full.mean():+.3f}  bootstrap_p={bootstrap_p(sleeve3_full):.5f}")
print(f"  Lock (n={len(sleeve3_lock)}):  $/tr={sleeve3_lock.mean():+.3f}  bootstrap_p={bootstrap_p(sleeve3_lock):.5f}")

# 95% CI on dpt
def ci_95(pnls, n_boot=5000, seed=42):
    if len(pnls) < 5: return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    n = len(pnls)
    boots = np.array([pnls[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return tuple(np.quantile(boots, [0.025, 0.975]))

ci_full = ci_95(sleeve3_full)
ci_lock = ci_95(sleeve3_lock)
print(f"  Full 95% CI on $/tr: [${ci_full[0]:+.2f}, ${ci_full[1]:+.2f}]")
print(f"  Lock 95% CI on $/tr: [${ci_lock[0]:+.2f}, ${ci_lock[1]:+.2f}]")

# Honest projection (no proj_full > proj_32d cherry-picking)
proj_32d = sleeve3_lock.sum() / lock_days * 32.66
proj_full = sleeve3_full.sum() / total_days * 32.66
print(f"\n  proj_32d (lockbox-based): ${proj_32d:+.0f}")
print(f"  proj_full (full-window):  ${proj_full:+.0f}")
print(f"  proj_honest = min:         ${min(proj_32d, proj_full):+.0f}")

log("DONE")
