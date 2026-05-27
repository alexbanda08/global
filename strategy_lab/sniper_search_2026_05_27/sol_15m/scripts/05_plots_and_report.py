"""Generate PnL plots + final report for SOL 15m sniper search."""
import os, time, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m"

log("loading fires")
df = pd.read_parquet(f"{OUT}/sol_15m_fires_v2fix_gates.parquet")
df['fire_date'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)

# vwap gates
df['g_vwap_sweet'] = ((df.entry_vwap >= 0.45) & (df.entry_vwap <= 0.80)).astype(float)
df['g_vwap_lt_75'] = (df.entry_vwap <= 0.75).astype(float)
df['g_vwap_lt_70'] = (df.entry_vwap <= 0.70).astype(float)
df['g_vwap_lt_65'] = (df.entry_vwap <= 0.65).astype(float)

top5 = pd.read_csv(f"{OUT}/top_5_candidates.csv")
log(f"top5 to plot: {len(top5)}")

def apply_filters(d, off_filter_str):
    d = d.copy()
    if off_filter_str == '60-240':
        d = d[d.fire_offset_s <= 240]
    elif off_filter_str == '240-480':
        d = d[(d.fire_offset_s > 240) & (d.fire_offset_s <= 480)]
    elif off_filter_str == '480-840':
        d = d[d.fire_offset_s > 480]
    elif off_filter_str == 'late_480plus':
        d = d[d.fire_offset_s >= 480]
    elif off_filter_str == 'late_360plus':
        d = d[d.fire_offset_s >= 360]
    return d

def gate_passes(d, gates):
    m = np.ones(len(d), dtype=bool)
    for g in gates:
        if g not in d.columns: continue
        col = np.asarray(d[g], dtype=float)
        m &= (col == 1)
    return m

# Plot each
for i, r in top5.iterrows():
    gates = r['gate_stack'].split('&')
    off_str = r['offset_filter']
    d = apply_filters(df, off_str)
    m = gate_passes(d, gates)
    sub = d[m].sort_values('fire_us').reset_index(drop=True)
    if len(sub) == 0:
        log(f"  skip {r['sleeve_id']} - no fires")
        continue
    pnl = sub['pnl_legacy_usd'].values
    cum = np.cumsum(pnl)
    sub['date'] = pd.to_datetime(sub.fire_us, unit='us', utc=True).dt.date
    daily = sub.groupby('date')['pnl_legacy_usd'].sum()
    daily_cum = daily.cumsum()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=False)
    # Trade-level cumulative
    ax1.plot(np.arange(len(cum)), cum, label='cum PnL @ $25 stake')
    ax1.axhline(0, color='gray', linestyle='--', alpha=0.5)
    ax1.set_title(f"{r['sleeve_id']}\nn={len(sub)}, WR={sub.won.mean()*100:.1f}%, $/tr=${pnl.mean():+.2f}, sum=${pnl.sum():+.0f}, max_dd=${(np.maximum.accumulate(np.concatenate([[0.0],cum]))[1:]-cum).max():.0f}")
    ax1.set_xlabel('trade #')
    ax1.set_ylabel('cum PnL USD')
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    # Daily PnL
    ax2.bar(range(len(daily)), daily.values, color=['green' if v >= 0 else 'red' for v in daily.values])
    ax2.set_title('Daily PnL')
    ax2.set_xticks(range(len(daily)))
    ax2.set_xticklabels([str(d) for d in daily.index], rotation=45, ha='right', fontsize=7)
    ax2.axhline(0, color='gray', linestyle='-', alpha=0.5)
    ax2.set_ylabel('daily PnL USD')
    ax2.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    sid = r['sleeve_id'].replace('/','_').replace('[','').replace(']','').replace(' ','_')[:60]
    fpath = f"{OUT}/cumulative_pnl_{sid}.png"
    plt.savefig(fpath, dpi=80)
    plt.close()
    log(f"  wrote {fpath}")

# Fire histogram across all sleeves
fig, ax = plt.subplots(figsize=(12, 4))
all_dates = pd.to_datetime(df['fire_us'], unit='us', utc=True).dt.date
hist = all_dates.value_counts().sort_index()
ax.bar(range(len(hist)), hist.values, alpha=0.5, label='all fires')
# Top sleeve overlay
top1 = top5.iloc[0]
gates = top1['gate_stack'].split('&')
d1 = apply_filters(df, top1['offset_filter'])
m1 = gate_passes(d1, gates)
sub1 = d1[m1].copy()
sub1['date'] = pd.to_datetime(sub1.fire_us, unit='us', utc=True).dt.date
top1_hist = sub1['date'].value_counts().sort_index()
positions = [list(hist.index).index(d) for d in top1_hist.index if d in list(hist.index)]
vals = [top1_hist[d] for d in top1_hist.index if d in list(hist.index)]
ax.bar(positions, vals, color='red', alpha=0.9, label=f'top sleeve: {top1["sleeve_id"][:40]}')
ax.set_title(f'SOL 15m fires per day - all (blue) vs top sniper sleeve (red)')
ax.set_xticks(range(len(hist)))
ax.set_xticklabels([str(d) for d in hist.index], rotation=45, ha='right', fontsize=7)
ax.legend()
plt.tight_layout()
plt.savefig(f"{OUT}/fire_histogram_per_day.png", dpi=80)
plt.close()
log(f"wrote fire_histogram_per_day.png")

log("DONE")
