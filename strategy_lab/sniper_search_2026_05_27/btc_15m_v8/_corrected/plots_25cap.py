"""Plots for $25-CAP convention (max payout $25)."""
import os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8/_corrected"

df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
df = df[(df.asset == 'BTC') & (df.tf == '15m')].copy()

total_secs = (df.fire_date.max() - df.fire_date.min()).total_seconds()
t_min = df.fire_date.min()
t_train_end = t_min + pd.Timedelta(seconds=total_secs * 0.60)
t_val_end   = t_min + pd.Timedelta(seconds=total_secs * 0.80)

SLEEVES = [
    (1, 600, 'DOWN', ['g_btc_sol_confluence_5m_with', 'g_liq_shock_against']),
    (2, 600, 'DOWN', ['g_xa_unanimity_5m_with', 'g_liq_shock_against']),
    (3, 600, 'DOWN', ['g_btc_eth_confluence_5m_with', 'g_di_agrees', 'g_liq_shock_against']),
    (4, 720, 'UP',   ['g_btc_eth_divergence', 'g_stoch_with', 'g_vol_contracting']),
    (5, 720, 'UP',   ['g_grandparent_1h_slope_strong_with', 'g_stoch_with', 'g_vol_high']),
]

for rank, off, direction, gates in SLEEVES:
    sub = df[(df.fire_offset_s == off) & (df.direction == direction)].copy()
    m = np.ones(len(sub), dtype=bool)
    for g in gates:
        m &= (sub[g].values == 1)
    sub = sub[m].sort_values('fire_us')
    vwap = sub['entry_vwap'].values
    won = sub['won'].values
    pnl_25cap = np.where(won == 1,
                         25.0 * (1.0 - vwap) * 0.98,
                         -25.0 * vwap)
    cum = pnl_25cap.cumsum()
    times = pd.to_datetime(sub.fire_us, unit='us', utc=True)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(times, cum, '-', lw=1.4, color='tab:green')
    ax.axhline(0, color='k', lw=0.5, alpha=0.5)
    ax.axvline(t_train_end, color='orange', lw=0.7, alpha=0.5, label='train end')
    ax.axvline(t_val_end, color='red', lw=0.7, alpha=0.5, label='val end')
    final = cum[-1] if len(cum) > 0 else 0
    title = f"Sleeve #{rank} ($25 MAX PAYOUT): {'+'.join(gates)}"
    ax.set_title(f"{title}\nn={len(sub)} final=${final:+.2f}", fontsize=9)
    ax.set_ylabel('Cumulative PnL ($, $25-cap stake)')
    ax.legend(loc='best', fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    plot_path = f"{OUTDIR}/cum_pnl_sleeve_{rank}_25CAP.png"
    fig.savefig(plot_path, dpi=110)
    plt.close(fig)
    print(f"saved {plot_path}")
print("DONE")
