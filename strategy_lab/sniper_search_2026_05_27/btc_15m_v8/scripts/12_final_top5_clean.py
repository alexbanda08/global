"""Final top 5 V8 CLEAN sleeves (healthy gates only). Compute bootstrap p + plots."""
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

log("loading")
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
strict = pd.read_csv(f"{OUTDIR}/v8_strict_survivors_CLEAN.csv").sort_values('proj_honest', ascending=False)

# Dedup near-duplicates (same off+dir + gate subsets)
seen = []
top5 = []
for _, r in strict.iterrows():
    gs = frozenset(r['gates'].split('+'))
    dup = False
    for prev in seen:
        if prev['off']==r['off'] and prev['dir']==r['dir']:
            if gs <= prev['gs'] or prev['gs'] <= gs:
                dup = True; break
    if not dup:
        seen.append({'off':r['off'],'dir':r['dir'],'gs':gs})
        top5.append(r)
    if len(top5) >= 5: break
top5 = pd.DataFrame(top5)
log(f"top 5 dedup: {len(top5)}")

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

final_rows = []
for idx, (_, row) in enumerate(top5.iterrows()):
    off, direction, gates = row['off'], row['dir'], row['gates']
    sub_df = df[(df.fire_offset_s == off) & (df.direction == direction)].copy()
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates.split('+'):
        if g and g in sub_df.columns:
            m &= (sub_df[g].values == 1)
    sub = sub_df[m].sort_values('fire_us').reset_index(drop=True)
    tr_sub = sub[sub.split=='train']
    vl_sub = sub[sub.split=='val']
    lk_sub = sub[sub.split=='lockbox']
    p_lock = bootstrap_p(lk_sub[PNL].values * 25.0)
    p_full = bootstrap_p(sub[PNL].values * 25.0)
    ci_lock = ci_95(lk_sub[PNL].values * 25.0)
    ci_full = ci_95(sub[PNL].values * 25.0)

    pnl25 = sub[PNL].values * 25.0
    cum = pnl25.cumsum()
    peak = np.maximum.accumulate(cum)
    full_dd = (cum - peak).min() if len(cum) else 0
    losses = (pnl25 < 0).astype(int)
    s=0; mx=0
    for L in losses:
        if L==1: s+=1; mx=max(mx,s)
        else: s=0

    proj_32d_lock = (lk_sub[PNL].sum()*25.0 / lock_days) * 32.66 if lock_days else 0
    proj_full = (sub[PNL].sum()*25.0 / total_days) * 32.66

    # Lockbox per-day breakdown
    lock_daily = lk_sub.groupby(lk_sub.fire_date.dt.date).size()
    lock_days_with_fires = len(lock_daily)

    final_rows.append(dict(
        rank=idx+1, gates=gates, off=off, dir=direction,
        n_train=len(tr_sub), n_val=len(vl_sub), n_lockbox=len(lk_sub), n_full=len(sub),
        wr_train=tr_sub.won.mean() if len(tr_sub) else np.nan,
        wr_val=vl_sub.won.mean() if len(vl_sub) else np.nan,
        wr_lockbox=lk_sub.won.mean() if len(lk_sub) else np.nan,
        wr_full=sub.won.mean(),
        dpt_25_train=tr_sub[PNL].mean()*25 if len(tr_sub) else np.nan,
        dpt_25_val=vl_sub[PNL].mean()*25 if len(vl_sub) else np.nan,
        dpt_25_lockbox=lk_sub[PNL].mean()*25 if len(lk_sub) else np.nan,
        dpt_25_full=sub[PNL].mean()*25,
        total_pnl_full=pnl25.sum(),
        max_dd_25=full_dd,
        loss_streak=mx,
        sharpe=(pnl25.mean()/pnl25.std()*np.sqrt(252)) if pnl25.std()>0 else 0,
        bootstrap_p_lockbox=p_lock,
        bootstrap_p_full=p_full,
        ci_lockbox_lo=ci_lock[0], ci_lockbox_hi=ci_lock[1],
        ci_full_lo=ci_full[0], ci_full_hi=ci_full[1],
        proj_32d=proj_32d_lock,
        proj_full=proj_full,
        proj_honest=min(proj_32d_lock, proj_full),
        lock_days_with_fires=lock_days_with_fires,
        lock_total_days=lock_days,
    ))

    # Plot
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(sub.fire_date, cum, marker='o', ms=2.5, lw=1.2, color='steelblue')
    ax.fill_between(sub.fire_date, cum, 0, where=cum>=0, alpha=0.2, color='green')
    ax.fill_between(sub.fire_date, cum, 0, where=cum<0, alpha=0.2, color='red')
    ax.axhline(0, color='gray', lw=0.5)
    ax.axvline(t_train_end, color='orange', ls='--', alpha=0.6, label='train -> val')
    ax.axvline(t_val_end, color='red', ls='--', alpha=0.6, label='val -> lock')
    ax.set_title(f"V8-CLEAN #{idx+1} BTC 15m off={off} {direction} | n={len(sub)} WR_lock={lk_sub.won.mean():.2f} $/tr_lock=${lk_sub[PNL].mean()*25:+.1f} proj_honest=${min(proj_32d_lock,proj_full):+.0f}\nGates: {gates}",
                 fontsize=9)
    ax.set_ylabel("Cumulative PnL ($, @$25)")
    ax.set_xlabel("Date (UTC)")
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fname = f"{OUTDIR}/plots/CLEAN_sleeve_{idx+1}_off{off}_{direction}.png"
    fig.savefig(fname, dpi=110)
    plt.close(fig)
    log(f"saved {fname}")

final_df = pd.DataFrame(final_rows)
final_df.to_csv(f"{OUTDIR}/top_5_candidates_v8.csv", index=False)
log(f"saved top5: {OUTDIR}/top_5_candidates_v8.csv")

print()
print("="*130)
print("V8 BTC 15m FINAL CLEAN TOP 5 (healthy gates only)")
print("="*130)
for _, r in final_df.iterrows():
    print(f"\n#{r['rank']}: off={r['off']} {r['dir']} | n_full={r['n_full']}  proj_honest=${r['proj_honest']:+.0f}")
    print(f"   gates: {r['gates']}")
    print(f"   TRAIN (n={r['n_train']:3}):   WR={r['wr_train']:.3f}  $/tr=${r['dpt_25_train']:+.2f}")
    print(f"   VAL   (n={r['n_val']:3}):   WR={r['wr_val']:.3f}  $/tr=${r['dpt_25_val']:+.2f}")
    print(f"   LOCK  (n={r['n_lockbox']:3}):   WR={r['wr_lockbox']:.3f}  $/tr=${r['dpt_25_lockbox']:+.2f}  p={r['bootstrap_p_lockbox']:.4f}  CI=[${r['ci_lockbox_lo']:+.1f},${r['ci_lockbox_hi']:+.1f}]")
    print(f"   FULL  (n={r['n_full']:3}):   WR={r['wr_full']:.3f}  $/tr=${r['dpt_25_full']:+.2f}  p={r['bootstrap_p_full']:.4f}  CI=[${r['ci_full_lo']:+.1f},${r['ci_full_hi']:+.1f}]")
    print(f"   max_DD=${r['max_dd_25']:+.0f}  loss_streak={r['loss_streak']}  sharpe={r['sharpe']:.2f}")
    print(f"   proj_32d=${r['proj_32d']:+.0f}  proj_full=${r['proj_full']:+.0f}  proj_honest=${r['proj_honest']:+.0f}")
    print(f"   lockbox: fired on {r['lock_days_with_fires']}/{r['lock_total_days']:.1f} days")
log("DONE")
