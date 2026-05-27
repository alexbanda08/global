import pandas as pd, numpy as np
df = pd.read_parquet(r'C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/btc_5m_v7/_sandbox/universe_v7.parquet')
df['fire_dt'] = pd.to_datetime(df['fire_us'], unit='us', utc=True)
df['fire_date'] = df['fire_dt'].dt.date

def inspect(label, mask):
    sub = df[mask].sort_values('fire_us')
    print(f'\n=== {label} ===')
    print(f'n_total={len(sub)}, WR={sub["won_int"].mean():.4f}, sum_pnl=${sub["pnl_legacy_usd"].sum():+.1f}')
    print(f'  unique slugs: {sub["slug"].nunique()}')
    print(f'  offset distribution: {sub["fire_offset_s"].value_counts().head(5).to_dict()}')
    print(f'  direction distribution: {sub["dir_sign"].value_counts().to_dict()}')
    print(f'  lockbox by date (sum/n):')
    lb = sub[sub['fire_date'] >= pd.Timestamp('2026-05-21').date()]
    grp = lb.groupby('fire_date')['pnl_legacy_usd'].agg(['count', 'sum', 'mean'])
    print(grp)

# Top 1
inspect('F_g_parent_15m_regime_with+g_within_dev+g_hurst_trending',
        (df['g_parent_15m_regime_with']==1) & (df['g_within_dev']==1) & (df['g_hurst_trending']==1))
# Top 2
inspect('H_g_hurst_regime_with+g_trend_slope_strong_with+g_hawkes_imbalance_with',
        (df['g_hurst_regime_with']==1) & (df['g_trend_slope_strong_with']==1) & (df['g_hawkes_imbalance_with']==1))
# Top 4 — D path
inspect('D_ofi+g_trend_slope_strong_with (offset>=240)',
        df['fire_offset_s'].isin([240, 255, 270]) & (df['g_slot_end_ofi_with']==1) & (df['g_trend_slope_strong_with']==1))
