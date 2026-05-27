"""V8 BTC 15m: pick the top 5 sleeves with proper bootstrap p, generate plots, save final top_5_candidates_v8.csv."""
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

log("loading panel + survivors")
df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
total_secs = (df.fire_date.max() - df.fire_date.min()).total_seconds()
total_days = total_secs / 86400
t_min = df.fire_date.min()
t_train_end = t_min + pd.Timedelta(seconds=total_secs * 0.60)
t_val_end   = t_min + pd.Timedelta(seconds=total_secs * 0.80)
df['split'] = np.where(df.fire_date < t_train_end, 'train',
              np.where(df.fire_date < t_val_end, 'val', 'lockbox'))
train_days = (t_train_end-t_min).total_seconds()/86400
val_days = (t_val_end-t_train_end).total_seconds()/86400
lock_days = (df.fire_date.max()-t_val_end).total_seconds()/86400

survivors = pd.read_csv(f"{OUTDIR}/v8_strict_survivors.csv").sort_values('proj_honest', ascending=False)

# Pick TOP 5 by min(n_full*proj_lock, n_lock_robustness)
# Dedup by gates list (some have 3leg == 4leg with redundant gate that adds nothing)
# Practical: take top 5 unique by 'effective gate footprint'
def normalize_gates(s):
    return frozenset(s.split('+'))

seen = set()
top5 = []
for _, r in survivors.iterrows():
    key = (r['off'], r['dir'], normalize_gates(r['gates']))
    # Also de-dup near-identical: if same off+dir+core 3 gates within larger set
    is_dup = False
    for s_key in seen:
        s_off, s_dir, s_gates = s_key
        if s_off==r['off'] and s_dir==r['dir']:
            # subset/superset filter
            if normalize_gates(r['gates']) <= s_gates or s_gates <= normalize_gates(r['gates']):
                # take the higher proj_honest one — but we're iterating sorted, so first wins
                is_dup = True
                break
    if not is_dup:
        seen.add(key)
        top5.append(r)
    if len(top5) >= 5:
        break

top5 = pd.DataFrame(top5)
log(f"Top 5 (dedup): {len(top5)}")

# Bootstrap p for each
def bootstrap_p(pnls, n_boot=5000, seed=42):
    if len(pnls) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    obs = pnls.mean()
    if obs <= 0: return 1.0
    n = len(pnls)
    centered = pnls - obs
    boots = np.array([centered[rng.integers(0, n, n)].mean() for _ in range(n_boot)])
    return (boots >= obs).mean()

PNL = 'pnl_legacy_usd'

# Compute bootstrap p + emit final CSV with full per-split + plot per sleeve
final_rows = []
for idx, (_, row) in enumerate(top5.iterrows()):
    off, direction, gates = row['off'], row['dir'], row['gates']
    sub_df = df[(df.fire_offset_s == off) & (df.direction == direction)].copy()
    m = np.ones(len(sub_df), dtype=bool)
    for g in gates.split('+'):
        if g and g in sub_df.columns:
            m &= (sub_df[g].values == 1)
    sub = sub_df[m].sort_values('fire_us').reset_index(drop=True)
    # split slices
    tr_sub = sub[sub.split=='train']
    vl_sub = sub[sub.split=='val']
    lk_sub = sub[sub.split=='lockbox']

    p_lock = bootstrap_p(lk_sub[PNL].values * 25.0)
    p_full = bootstrap_p(sub[PNL].values * 25.0)

    # Compute max DD over FULL window
    pnl25 = sub[PNL].values * 25.0
    cum = pnl25.cumsum()
    peak = np.maximum.accumulate(cum)
    full_dd = (cum - peak).min() if len(cum) else 0

    # Loss streak full
    losses = (pnl25 < 0).astype(int)
    s=0; max_s=0
    for L in losses:
        if L==1: s+=1; max_s=max(max_s,s)
        else: s=0

    proj_32d_lock = (lk_sub[PNL].sum()*25.0 / lock_days) * 32.66 if lock_days else 0
    proj_full = (sub[PNL].sum()*25.0 / total_days) * 32.66

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
        loss_streak=max_s,
        sharpe=(pnl25.mean()/pnl25.std()*np.sqrt(252)) if pnl25.std()>0 else 0,
        bootstrap_p_lockbox=p_lock,
        bootstrap_p_full=p_full,
        proj_32d=proj_32d_lock,
        proj_full=proj_full,
        proj_honest=min(proj_32d_lock, proj_full),
    ))

    # Cumulative PnL plot
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(sub.fire_date, cum, lw=1.5, color='steelblue')
    ax.axhline(0, color='gray', lw=0.5)
    ax.axvline(t_train_end, color='orange', ls='--', label='train/val')
    ax.axvline(t_val_end, color='red', ls='--', label='val/lock')
    ax.set_title(f"#{idx+1} V8 BTC 15m off={off} {direction} | n={len(sub)} WR_lock={lk_sub.won.mean():.2f} $/tr_lock=${lk_sub[PNL].mean()*25:+.1f}\nGates: {gates}",
                 fontsize=9)
    ax.set_ylabel("Cumulative PnL ($, @$25)")
    ax.set_xlabel("Date (UTC)")
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fname = f"{OUTDIR}/plots/sleeve_{idx+1}_off{off}_{direction}.png"
    fig.savefig(fname, dpi=110)
    plt.close(fig)
    log(f"  saved plot: {fname}")

final_df = pd.DataFrame(final_rows)
final_df.to_csv(f"{OUTDIR}/top_5_candidates_v8.csv", index=False)
log(f"saved {OUTDIR}/top_5_candidates_v8.csv")

print()
print("="*130)
print("V8 BTC 15m FINAL TOP 5 (with bootstrap p)")
print("="*130)
for _, r in final_df.iterrows():
    print(f"\n#{r['rank']}: off={r['off']} {r['dir']} | n_full={r['n_full']}  proj_honest=${r['proj_honest']:+.0f}")
    print(f"   gates: {r['gates']}")
    print(f"   TRAIN (n={r['n_train']}):   WR={r['wr_train']:.3f}  $/tr=${r['dpt_25_train']:+.2f}")
    print(f"   VAL   (n={r['n_val']}):   WR={r['wr_val']:.3f}  $/tr=${r['dpt_25_val']:+.2f}")
    print(f"   LOCK  (n={r['n_lockbox']}):   WR={r['wr_lockbox']:.3f}  $/tr=${r['dpt_25_lockbox']:+.2f}  bootstrap_p={r['bootstrap_p_lockbox']:.4f}")
    print(f"   FULL  (n={r['n_full']}):   WR={r['wr_full']:.3f}  $/tr=${r['dpt_25_full']:+.2f}  bootstrap_p={r['bootstrap_p_full']:.4f}")
    print(f"   max_DD=${r['max_dd_25']:+.0f}  loss_streak={r['loss_streak']}  sharpe={r['sharpe']:.2f}")
    print(f"   proj_32d=${r['proj_32d']:+.0f}  proj_full=${r['proj_full']:+.0f}  proj_honest=${r['proj_honest']:+.0f}")

log("DONE")
