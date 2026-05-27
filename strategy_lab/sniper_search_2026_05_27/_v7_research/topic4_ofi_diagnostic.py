"""Topic 4 diagnostic: relationship between fire direction and OFI sign on BTC 15m offset 840."""
import pandas as pd
import numpy as np
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

fires = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_15m_full_v3.parquet",
                         columns=['slug','slot_start_us','slot_end_us','fire_offset_s','fire_us','direction','outcome','won','pnl_legacy_usd'])
late = fires[fires['fire_offset_s']==840].copy()
ofi = pd.read_csv(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/_v7_research/topic4_btc15m_ofi.csv")
late = late.merge(ofi, on='slug', how='inner')
late = late[late['ofi_total']>0].copy()
print(f"n={len(late):,}")

# diagnostic: does fire direction follow ofi sign?
late['ofi_sign'] = np.sign(late['ofi'])
late['dir_sign'] = np.where(late['direction']=='UP', 1, -1)
agreement = (late['ofi_sign'] == late['dir_sign']).mean()
print(f"\nFire-direction agrees with OFI sign: {agreement:.4f}")
# breakdown
print("\nCross-tab direction × ofi_sign:")
print(pd.crosstab(late['direction'], late['ofi_sign']))

# breakdown WR by combination
print("\nWR by direction & ofi_sign:")
for d in ['UP', 'DOWN']:
    for s in [1, -1]:
        sub = late[(late['direction']==d) & (late['ofi_sign']==s)]
        if len(sub)<10: continue
        print(f"  dir={d}  ofi_sign={s:+d}: n={len(sub):,}  WR={sub['won'].mean():.4f}  $/tr=${sub['pnl_legacy_usd'].mean():+.4f}  outcome-UP rate={(sub['outcome']=='Up').mean():.4f}")

# Crucially: what is the outcome rate per ofi sign x train/val/lockbox?
late = late.sort_values('fire_us').reset_index(drop=True)
n = len(late)
i_tr = int(n*0.6); i_v = int(n*0.8)
tr = late.iloc[:i_tr]; vl = late.iloc[i_tr:i_v]; lb = late.iloc[i_v:]

print("\nOutcome UP rate by OFI sign × split:")
for split_name, split_df in [('train', tr), ('val', vl), ('lockbox', lb)]:
    print(f"  {split_name}:")
    for s in [1, -1]:
        sub = split_df[split_df['ofi_sign']==s]
        if len(sub)<10: continue
        print(f"    ofi_sign={s:+d}: n={len(sub):,}  UP-outcome={(sub['outcome']=='Up').mean():.4f}")
