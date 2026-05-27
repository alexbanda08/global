"""V8 finalize ETH 15m — dedupe results, write top-5 + PNGs + final report."""
import os, time, warnings, json
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v8"

log("loading combined candidates + dedupe")
df = pd.read_csv(f"{OUT}/all_candidates_v8.csv")
log(f"raw: {len(df)} rows")
# Dedupe by sleeve_id + split_kind (keep first)
df = df.drop_duplicates(subset=['sleeve_id','split_kind']).reset_index(drop=True)
log(f"deduped: {len(df)}")
df.to_csv(f"{OUT}/all_candidates_v8.csv", index=False)

passing = df[df.passes_v8 == True].copy().sort_values('proj_honest', ascending=False).reset_index(drop=True)
passing.to_csv(f"{OUT}/passing_v8.csv", index=False)
log(f"Passing V8 (unique): {len(passing)}")

# === Top 5 (dedupe by gate_stack to surface DISTINCT sleeves) ===
top5 = passing.drop_duplicates(subset=['gate_stack']).head(5)
log(f"top-5 distinct stacks: {len(top5)}")
keep = ['sleeve_id','gate_stack','split_kind','n_gates','n_train','n_val','n_lock','n_full',
        'wr_train','wr_val','wr_lock','wr_full',
        'dpt_train_25','dpt_val_25','dpt_lock_25','dpt_full_25',
        'max_dd_25','loss_streak','sharpe_daily','bootstrap_p_lockbox',
        'proj_32d','proj_full','proj_honest']
rename = {'dpt_train_25':'dpt_25_train','dpt_val_25':'dpt_25_val',
          'dpt_lock_25':'dpt_25_lockbox','dpt_full_25':'dpt_25_full',
          'wr_lock':'wr_lockbox','n_lock':'n_lockbox','sharpe_daily':'sharpe'}
top5_out = top5[keep].rename(columns=rename)
top5_out.to_csv(f"{OUT}/top_5_candidates_v8.csv", index=False)
log("\nTOP 5:")
for _, r in top5.iterrows():
    log(f"  {r.sleeve_id:<42} | n_full={int(r.n_full):>4} | n_lock={int(r.n_lock):>3} | WR_f={r.wr_full:.3f} | WR_l={r.wr_lock:.3f} | dpt_l=${r.dpt_lock_25:.2f} | DD=${r.max_dd_25:.0f} | LS={int(r.loss_streak)} | p={r.bootstrap_p_lockbox:.3f} | proj_h=${r.proj_honest:.0f}")

# === Cumulative PnL PNGs for top 5 ===
fires = pd.read_parquet(f"{OUT}/eth_15m_enriched_v8.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
# Need same vol_high_rg gate as the search used
rv = fires.realized_vol_60m_rg
fires['g_vol_high_rg']    = (rv > rv.quantile(0.75)).fillna(False).astype(int)
fires['g_vol_extreme_rg'] = (rv > rv.quantile(0.90)).fillna(False).astype(int)
fires['date'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.date
all_dates = sorted(fires.date.unique())
i1 = int(len(all_dates) * 0.60); i2 = int(len(all_dates) * 0.80)
TRAIN_DATES = set(all_dates[:i1]); VAL_DATES = set(all_dates[i1:i2]); LOCK_DATES = set(all_dates[i2:])
HUR22_LOCK = (lambda d: (d >= pd.to_datetime('2026-05-18').date()) & (d <= pd.to_datetime('2026-05-22').date()))

STAKE_NOMINAL = 1.0  # pnl_legacy_usd already $25 stake

for _, r in top5.iterrows():
    name = r.sleeve_id
    gates = r.gate_stack.split('&')
    missing = [g for g in gates if g not in fires.columns]
    if missing:
        log(f"  PNG SKIP {name}: missing {missing}"); continue
    mask = fires[gates].all(axis=1) > 0
    sub = fires[mask].sort_values('fire_us').copy()
    if len(sub) == 0: continue
    if r.split_kind == 'hur22':
        lock_mask = HUR22_LOCK(sub.date)
        split_label = 'HUR22'
    else:
        lock_mask = sub.date.isin(LOCK_DATES)
        split_label = 'V8 (60/20/20)'
    sub['cumpnl'] = (sub.pnl_legacy_usd * STAKE_NOMINAL).cumsum()
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(pd.to_datetime(sub.fire_us, unit='us'), sub.cumpnl, lw=1.4, color='steelblue', label='Cumulative PnL ($25 const)')
    # Shade lock region
    lock_mask_arr = lock_mask.values
    if lock_mask_arr.any():
        lock_ts = pd.to_datetime(sub.fire_us[lock_mask_arr], unit='us')
        ax.axvspan(lock_ts.min(), lock_ts.max(), alpha=0.15, color='goldenrod', label=f'LOCK ({split_label})')
    ax.axhline(0, color='gray', lw=0.5)
    ax.set_xlabel('Time UTC')
    ax.set_ylabel('Cumulative PnL ($25 stake)')
    ax.set_title(f'{name}\nn_full={int(r.n_full)} | WR_full={r.wr_full:.2%} | $/tr_full=${r.dpt_full_25:.2f} | proj_honest=${r.proj_honest:.0f}')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    pngpath = f"{OUT}/cumulative_pnl_const25_{name}.png"
    plt.savefig(pngpath, dpi=80)
    plt.close()
    log(f"  PNG: {pngpath}")

# === Path summary stats ===
log("\n=== PATH SUMMARY ===")
def path_tag(s):
    if 'BASELINE' in s: return 'baseline'
    if s.startswith('V8_PJ') or s.startswith('V8_PJ_RG'): return 'J_2asset'
    if s.startswith('V8_PK') or s.startswith('V8_PK_RG'): return 'K_TOD'
    if s.startswith('V8_PL') or s.startswith('V8_PL_RG'): return 'L_1h_grand'
    if s.startswith('V8_JK_'): return 'J+K'
    if s.startswith('V8_JL_'): return 'J+L'
    if s.startswith('V8_JKL'): return 'J+K+L'
    if s.startswith('V8_V7TOP_VOLRG'): return 'baseline_volrg'
    return 'other'
df['path'] = df.sleeve_id.apply(path_tag)
log(df.groupby('path').agg(
    n=('sleeve_id','count'),
    n_pass=('passes_v8','sum'),
    best_proj_honest=('proj_honest','max'),
    best_dpt_lock=('dpt_lock_25','max'),
    best_wr_lock=('wr_lock','max')).to_string())

log("DONE")
