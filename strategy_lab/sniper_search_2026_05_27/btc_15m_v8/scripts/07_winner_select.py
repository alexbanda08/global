"""Pick THE winner sleeve — 3-leg version of Sleeve #3 (drop g_tr_above_cloud).
Verify: train+val+lock all positive, 13 lockbox fires (more samples), 92% WR, $/tr $377.
Verify lockbox fires aren't all from May 20-22.

Then write final BLOCK-WALK plot + per-fire trace + report-ready summary.
"""
import os, sys, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

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

# Variant comparison
WINNER_3LEG = ['g_bb_pos_with','g_mp_no_extreme_150','g_ret_2m_strong_with']
WINNER_4LEG = ['g_bb_pos_with','g_mp_no_extreme_150','g_ret_2m_strong_with','g_tr_above_cloud']

base = df[(df.fire_offset_s==240) & (df.direction=='UP')].copy()

def select(sub_df, gates):
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates:
        m &= (sub_df[g].values == 1)
    return sub_df[m].sort_values('fire_us').reset_index(drop=True)

s3 = select(base, WINNER_3LEG)
s4 = select(base, WINNER_4LEG)

def bootstrap_p(pnls, n_boot=10000, seed=42):
    if len(pnls) < 5: return 1.0
    rng = np.random.default_rng(seed)
    obs = pnls.mean()
    if obs <= 0: return 1.0
    n = len(pnls)
    centered = pnls - obs
    boots = np.array([centered[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return (boots >= obs).mean()

def ci_95(pnls, n_boot=5000, seed=42):
    if len(pnls) < 5: return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    n = len(pnls)
    boots = np.array([pnls[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return tuple(np.quantile(boots, [0.025, 0.975]))

def summary(sl, label):
    pnl25 = sl[PNL].values * 25.0
    if len(pnl25) == 0:
        print(f"  {label}: empty")
        return
    cum = pnl25.cumsum()
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak).min()
    losses = (pnl25 < 0).astype(int)
    s=0; mx=0
    for L in losses:
        if L==1: s+=1; mx=max(mx,s)
        else: s=0
    tr = sl[sl.split=='train']
    vl = sl[sl.split=='val']
    lk = sl[sl.split=='lockbox']
    ci_full = ci_95(pnl25)
    ci_lock = ci_95(lk[PNL].values*25.0)
    p_full = bootstrap_p(pnl25)
    p_lock = bootstrap_p(lk[PNL].values * 25.0)

    proj_32d_lock = (lk[PNL].sum()*25 / lock_days) * 32.66
    proj_full = (sl[PNL].sum()*25 / total_days) * 32.66
    proj_honest = min(proj_32d_lock, proj_full)

    print(f"\n  {label} (n={len(sl)})")
    print(f"    full:   WR={sl.won.mean():.3f}  $/tr=${sl[PNL].mean()*25:+6.2f}  total=${pnl25.sum():+7.1f}  DD=${dd:+6.1f}  ls={mx}")
    print(f"    train:  WR={tr.won.mean():.3f}  $/tr=${tr[PNL].mean()*25:+6.2f}  n={len(tr)}")
    print(f"    val:    WR={vl.won.mean():.3f}  $/tr=${vl[PNL].mean()*25:+6.2f}  n={len(vl)}")
    print(f"    lock:   WR={lk.won.mean():.3f}  $/tr=${lk[PNL].mean()*25:+6.2f}  n={len(lk)}")
    print(f"    95% CI $/tr: full=[${ci_full[0]:+.2f},${ci_full[1]:+.2f}]  lock=[${ci_lock[0]:+.2f},${ci_lock[1]:+.2f}]")
    print(f"    bootstrap p: full={p_full:.4f}  lock={p_lock:.4f}")
    print(f"    proj_32d=${proj_32d_lock:+.0f}  proj_full=${proj_full:+.0f}  proj_honest=${proj_honest:+.0f}")

    # Day breakdown on lockbox
    if len(lk):
        daily = lk.groupby(lk.fire_date.dt.date).size()
        print(f"    lockbox day breakdown: {daily.to_dict()}")
        print(f"    lockbox days with fires: {len(daily)} / {lock_days:.2f}d")

print("="*120)
print("COMPARISON: 3-leg vs 4-leg variant")
print("="*120)
summary(s3, "3-LEG: g_bb_pos_with+g_mp_no_extreme_150+g_ret_2m_strong_with")
summary(s4, "4-LEG (orig): + g_tr_above_cloud")

# Plot side-by-side cumulative PnL
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
for ax, sl, label in zip(axes, [s3, s4], ["3-LEG", "4-LEG"]):
    pnl25 = sl[PNL].values * 25.0
    cum = pnl25.cumsum()
    ax.plot(sl.fire_date, cum, marker='o', ms=3, lw=1.2, color='steelblue' if 'leg' in label.lower() else 'tomato')
    ax.fill_between(sl.fire_date, cum, 0, where=cum>=0, alpha=0.2, color='green')
    ax.fill_between(sl.fire_date, cum, 0, where=cum<0, alpha=0.2, color='red')
    ax.axhline(0, color='gray', lw=0.5)
    ax.axvline(t_train_end, color='orange', ls='--', alpha=0.7, label='train→val')
    ax.axvline(t_val_end, color='red', ls='--', alpha=0.7, label='val→lock')
    ax.set_title(f"V8 BTC 15m off=240 UP — {label}  n={len(sl)} WR={sl.won.mean():.2f} total=${cum[-1]:+.0f}",
                 fontsize=10)
    ax.set_ylabel("Cumulative PnL ($, @$25)")
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(alpha=0.3)
axes[1].set_xlabel("Fire date (UTC)")
fig.tight_layout()
plot_path = f"{OUTDIR}/plots/WINNER_3leg_vs_4leg_off240_UP.png"
fig.savefig(plot_path, dpi=110)
plt.close(fig)
print(f"\nsaved comparison plot: {plot_path}")

# Save per-fire trace for the 3-leg winner
trace = s3[['fire_date','slug','direction','fire_offset_s','entry_vwap','won','pnl_legacy_usd','split']].copy()
trace['pnl_at_25'] = trace.pnl_legacy_usd * 25
trace['cum_pnl'] = trace.pnl_at_25.cumsum()
trace.to_csv(f"{OUTDIR}/winner_3leg_per_fire_trace.csv", index=False)
print(f"saved trace: {OUTDIR}/winner_3leg_per_fire_trace.csv")

log("DONE")
