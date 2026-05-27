"""Final V7 report + plots for SOL 15m."""
import os, pickle, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v7"

vdf = pd.read_csv(f"{OUT}/_v7_validated.csv")
sleeve_data = pickle.load(open(f"{OUT}/_v7_top_sleeves.pkl",'rb'))

# Pick the curated TOP 5 — prefer stable + high WR + low DD
stable = vdf[vdf['stable_3split']==True].copy()
stable = stable[(stable['wr_lockbox'] >= 0.65) & (stable['dpt_lockbox'] >= 4.0) &
                (stable['dd_lockbox'] <= 500) & (stable['loss_streak_lockbox'] <= 14) &
                (stable['bootstrap_p_lockbox'] <= 0.05)]
stable['composite'] = stable['dpt_lockbox'] * np.sqrt(stable['n_lockbox'].clip(lower=0))

# Final TOP 5 ranking: prefer composite, but also reward higher proj_28d
stable['rank_score'] = stable['composite'] + (stable['proj_28d_const25'] / 100)
stable = stable.sort_values('rank_score', ascending=False)
top5 = stable.head(5).copy()

# Add sleeve_id (short names)
def short_id(name):
    if '+g_BTC_adx_strong+g_BTC_vol_low' in name: return "S1_BTC_ADX_VOLLOW"
    if '+g_BTC_adx_strong+g_ETH_vol_low' in name: return "S2_BTC_ADX_ETHVOLLOW"
    if '+g_BTC_adx_strong+g_ETH_adx_strong+g_ETH_vol_low' in name: return "S3_XADX_ETHVOLLOW"
    if '+g_BTC_adx_strong+g_ETH_adx_strong+g_BTC_vol_low' in name: return "S4_XADX_BTCVOLLOW"
    if '+g_BTC_slope_strong_with+g_BTC_slope_with' in name or name.endswith('g_BTC_slope_strong_with'): return "S5_BTC_SLOPE_STR"
    if '+g_ETH_slope_with+g_ETH_adx_strong' in name: return "S6_ETH_SLOPE_ADX"
    if '+g_ETH_tr_stack_with+g_BTC_adx_strong+g_BTC_vol_low' in name: return "S7_ETHTR_BTCADX_VOLLOW"
    if '+g_BTC_tr_stack_with+g_BTC_adx_strong+g_BTC_vol_low' in name: return "S8_BTCTR_BTCADX_VOLLOW"
    return name[:30].replace('+','_')

top5['sleeve_id'] = top5['sleeve'].apply(short_id)
# Ensure unique ids
seen = {}
new_ids = []
for sid in top5['sleeve_id']:
    if sid not in seen:
        seen[sid] = 0
        new_ids.append(sid)
    else:
        seen[sid] += 1
        new_ids.append(f"{sid}_v{seen[sid]+1}")
top5['sleeve_id'] = new_ids

# Save final top5 candidates CSV
top5_out = top5[['sleeve_id','sleeve','n_train','n_val','n_lockbox','n_total',
                 'wr_train','wr_val','wr_lockbox','wr_full',
                 'dpt_train','dpt_val','dpt_lockbox','dpt_full',
                 'sum_train','sum_val','sum_lockbox','sum_full','proj_28d_const25',
                 'dd_lockbox','dd_full','loss_streak_lockbox','loss_streak_full',
                 'bootstrap_p_lockbox','bootstrap_p_full','sharpe_lockbox','stable_3split']].copy()

# Add columns matching V7 brief §6 spec
top5_out['anchor'] = 'offset_60_240s (15m window early-mid)'
top5_out['gate_stack'] = top5_out['sleeve']
top5_out['weights'] = 'AND-stack (equal weight 1.0)'
top5_out['conviction_method'] = 'A (gate-count via AND-mask)'
top5_out['vwap_filter'] = 'entry_vwap < 0.80'
top5_out['dpt_25_train'] = top5_out['dpt_train']
top5_out['dpt_25_val'] = top5_out['dpt_val']
top5_out['dpt_25_lockbox'] = top5_out['dpt_lockbox']
top5_out['sum_25_28d_const'] = top5_out['proj_28d_const25']
top5_out['max_dd_25'] = top5_out['dd_lockbox']
top5_out['loss_streak'] = top5_out['loss_streak_lockbox']
top5_out['sharpe'] = top5_out['sharpe_lockbox']
top5_out['n_lockbox'] = top5_out['n_lockbox'].astype(int)

cols_v7 = ['sleeve_id','anchor','gate_stack','weights','conviction_method',
           'n_train','n_val','n_lockbox',
           'wr_train','wr_val','wr_lockbox',
           'dpt_25_train','dpt_25_val','dpt_25_lockbox',
           'sum_25_28d_const','max_dd_25','loss_streak','sharpe','bootstrap_p_lockbox']
top5_out[cols_v7].to_csv(f"{OUT}/top_5_candidates_v7.csv", index=False)
print(f"WROTE top_5_candidates_v7.csv")
print(top5_out[cols_v7].to_string())

# === PLOTS: cumulative PnL per top sleeve ===
for _, row in top5.iterrows():
    sid = row['sleeve_id']
    name = row['sleeve']
    if name not in sleeve_data:
        continue
    sub = sleeve_data[name].sort_values('fire_us').copy()
    sub['fire_dt'] = pd.to_datetime(sub['fire_us'], unit='us', utc=True)
    sub['cum'] = sub['pnl25'].cumsum()
    fig, ax = plt.subplots(figsize=(10, 5))
    # Color by split
    for s, color in [('train','tab:blue'),('val','tab:orange'),('lockbox','tab:green')]:
        ss = sub[sub['split']==s]
        if len(ss):
            ax.plot(ss['fire_dt'], ss['cum'], '-', color=color, label=f"{s} (n={len(ss)})", linewidth=1.5)
    ax.axhline(0, color='gray', alpha=0.3, linestyle='--')
    ax.set_title(f"V7 SOL 15m — {sid}\n{name}\n"
                 f"WR lockbox={row['wr_lockbox']:.1%} | $/tr={row['dpt_lockbox']:.2f} | "
                 f"n_lock={int(row['n_lockbox'])} | DD={row['dd_lockbox']:.0f} | "
                 f"BootP={row['bootstrap_p_lockbox']:.3f}", fontsize=10)
    ax.set_ylabel("Cumulative PnL ($25 stake)")
    ax.set_xlabel("Date (UTC)")
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=30, ha='right')
    plt.tight_layout()
    plt.savefig(f"{OUT}/cumulative_pnl_{sid}.png", dpi=100)
    plt.close()
    print(f"  saved {sid}.png")

# === COMPARISON: V7 best vs V6 best ===
# Get V6 best from CSV
v6 = pd.read_csv(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_15m_v6/top_5_candidates_v6.csv")
v6_best = v6.sort_values('dpt_25_lockbox', ascending=False).iloc[0]
print("\n=== V6 BEST ===")
print(v6_best[['sleeve_id','gate_stack','n_lockbox','wr_lockbox','dpt_25_lockbox','dd_25_lockbox','loss_streak_lockbox']])
v7_best = top5.iloc[0]
print("\n=== V7 BEST ===")
print(v7_best[['sleeve_id','sleeve','n_lockbox','wr_lockbox','dpt_lockbox','dd_lockbox','loss_streak_lockbox']])

print("DONE")
