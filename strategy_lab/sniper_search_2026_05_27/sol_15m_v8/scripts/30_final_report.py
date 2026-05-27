"""V8 SOL 15m final report + cumulative PnL plots + top_5_candidates_v8.csv."""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v8"
STAKE = 25.0

log("loading universe + validated")
df = pd.read_parquet(f"{OUT}/sol_15m_v8_universe.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
shares = STAKE / df['entry_vwap']
df['pnl25'] = np.where(df['won']==1, (1-df['entry_vwap'])*shares*0.98, -df['entry_vwap']*shares)
df['fire_dt'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
total_days = (df['fire_dt'].max() - df['fire_dt'].min()).total_seconds() / 86400
train_end = df['fire_dt'].min() + pd.Timedelta(days=int(total_days*0.6))
val_end   = df['fire_dt'].min() + pd.Timedelta(days=int(total_days*0.8))
df['split'] = pd.cut(df['fire_dt'],
    bins=[df['fire_dt'].min()-pd.Timedelta(seconds=1), train_end, val_end, df['fire_dt'].max()+pd.Timedelta(seconds=1)],
    labels=['train','val','lockbox'])
days_per_split = {s: (df[df['split']==s]['fire_dt'].max() - df[df['split']==s]['fire_dt'].min()).total_seconds()/86400 for s in ['train','val','lockbox']}

val = pd.read_csv(f"{OUT}/_v8_validated.csv")
val = val.sort_values('proj_honest', ascending=False)

# Pick top 5 with diversity criteria:
# - Different gate compositions (avoid duplicates with same lockbox metrics)
# - Mix of high-WR + high-$/tr
candidates = val.head(15).copy()
# Dedup by lockbox sum_total since many sleeves give identical lockbox sets
candidates['fingerprint'] = candidates['sum_lockbox'].round(2).astype(str) + '_' + candidates['n_lockbox'].astype(str)
top5 = candidates.drop_duplicates('fingerprint', keep='first').head(5).copy()
log(f"top5 selected: {top5['sleeve'].tolist()}")

# Plot cumulative PnL for each (full window, mark split boundaries)
V6_BASE = ['g_hod_european_morning','g_off_60_240','g_rf_with','g_tr_stack_with']
V6_NO_HOD = ['g_off_60_240','g_rf_with','g_tr_stack_with']
V7_BASES = {
    'S5_SLOPE_STR': V6_BASE + ['g_BTC_slope_with','g_BTC_slope_strong_with'],
    'S1_ADX_VOLLOW': V6_BASE + ['g_BTC_tr_stack_with','g_BTC_adx_strong','g_BTC_vol_low'],
    'S3_XADX_ETHVOLLOW': V6_BASE + ['g_BTC_adx_strong','g_ETH_adx_strong','g_ETH_vol_low'],
    'S1': V6_BASE + ['g_BTC_tr_stack_with','g_BTC_adx_strong','g_BTC_vol_low'],
    'S3': V6_BASE + ['g_BTC_adx_strong','g_ETH_adx_strong','g_ETH_vol_low'],
}
def parse_label(label):
    if label == 'V6_BASE': return list(V6_BASE)
    if label.startswith('V7_BASE_'):
        return list(V7_BASES[label.replace('V7_BASE_', '')])
    if '_TOD_' in label:
        parts = label.split('_TOD_')
        name_part = parts[0].replace('V7_', '')
        bucket = parts[1]
        base = list(V7_BASES.get(name_part, V6_BASE))
        base = [g for g in base if g != 'g_hod_european_morning']
        base.append(f'g_K_tod_{bucket}')
        return base
    if label.startswith('V7_'):
        parts = label.split('+')
        name_part = parts[0].replace('V7_', '')
        base = list(V7_BASES.get(name_part, V6_BASE))
        for p in parts[1:]:
            base.append(p)
        return base
    if label.startswith('V6+'):
        return list(V6_BASE) + label[3:].split('+')
    return None

def gate_mask(stack, df=df, extra_vwap_lt=0.80):
    m = pd.Series(True, index=df.index)
    for g in stack:
        if g not in df.columns:
            return pd.Series(False, index=df.index)
        v = df[g].fillna(0).astype(float)
        m = m & (v >= 0.5)
    if extra_vwap_lt is not None:
        m = m & (df['entry_vwap'] < extra_vwap_lt)
    return m

# Build top5 csv with all columns the brief asks for
final_rows = []
for _, row in top5.iterrows():
    label = row['sleeve']
    stack = parse_label(label)
    out = dict(row)
    # Match brief column conventions: dpt_25_*, max_dd_25, loss_streak, sharpe, bootstrap_p_lockbox, proj_*
    out['gates'] = '+'.join(stack)
    final_rows.append(out)

top5_df = pd.DataFrame(final_rows)
# Rename to brief spec
col_order = ['sleeve','gates',
    'n_train','n_val','n_lockbox','n_full',
    'wr_train','wr_val','wr_lockbox','wr_full',
    'dpt_25_train','dpt_25_val','dpt_25_lockbox','dpt_25_full',
    'max_dd_25','loss_streak','sharpe','bootstrap_p_lockbox',
    'proj_32d','proj_full','proj_honest']
present = [c for c in col_order if c in top5_df.columns]
top5_df[present].to_csv(f"{OUT}/top_5_candidates_v8.csv", index=False)
log(f"WROTE top_5_candidates_v8.csv ({len(top5_df)} rows)")

# Per-sleeve cum PnL plots
for i, row in top5_df.iterrows():
    label = row['sleeve']
    stack = parse_label(label)
    mask = gate_mask(stack, extra_vwap_lt=0.80)
    sub = df[mask].copy().sort_values('fire_us')
    if len(sub) < 5: continue
    sub['cumpnl'] = sub['pnl25'].cumsum()
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(sub['fire_dt'], sub['cumpnl'], lw=1.4, color='#1f77b4')
    ax.axvline(train_end, color='orange', ls='--', alpha=0.6, label='train→val')
    ax.axvline(val_end, color='red', ls='--', alpha=0.6, label='val→lockbox')
    ax.axhline(0, color='gray', ls=':', alpha=0.4)
    ax.set_title(f"V8 {label}\nn={len(sub)}, full WR={sub['won'].mean():.1%}, full $/tr={sub['pnl25'].mean():+.2f}, proj_honest=${row['proj_honest']:.0f}/32.7d", fontsize=9)
    ax.set_xlabel('Date (UTC)')
    ax.set_ylabel('Cumulative PnL ($)')
    ax.legend(loc='upper left', fontsize=8)
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    safe = label.replace('+','_').replace(' ','').replace('/','_')[:60]
    fpath = f"{OUT}/plots/cumpnl_v8_{i+1:02d}_{safe}.png"
    fig.savefig(fpath, dpi=120)
    plt.close(fig)
    log(f"  saved {fpath}")

log("DONE")
