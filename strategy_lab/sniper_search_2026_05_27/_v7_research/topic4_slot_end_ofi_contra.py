"""Topic 4 follow-up: confirm contrarian OFI sleeve for BTC 15m offset 840."""
import pandas as pd
import numpy as np
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

fires = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_15m_full_v3.parquet",
                         columns=['slug','slot_start_us','slot_end_us','fire_offset_s','fire_us','direction','outcome','won','pnl_legacy_usd','entry_vwap'])
late = fires[fires['fire_offset_s']==840].copy()

ofi = pd.read_csv(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/_v7_research/topic4_btc15m_ofi.csv")
late = late.merge(ofi, on='slug', how='inner')
late = late[late['ofi_total']>0].copy()
print(f"BTC 15m offset=840 fires with OFI: {len(late):,}")
print(f"  baseline outcome UP rate: {(late['outcome']=='Up').mean():.4f}")
print(f"  baseline WR (engine-decided direction): {late['won'].mean():.4f}")
print(f"  baseline $/tr: ${late['pnl_legacy_usd'].mean():+.4f}")

# CONTRARIAN: fire OPPOSITE to OFI sign
print("\n=== CONTRARIAN sleeve: fire OPPOSITE to OFI sign ===")
for ofi_pct_thr in [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]:
    contra = late[
        ((late['direction']=='DOWN') & (late['ofi_pct'] > ofi_pct_thr)) |
        ((late['direction']=='UP') & (late['ofi_pct'] < -ofi_pct_thr))
    ]
    if len(contra) < 10: continue
    print(f"  ofi_pct |>| {ofi_pct_thr}: n_contra={len(contra):,}  WR={contra['won'].mean():.4f}  $/tr=${contra['pnl_legacy_usd'].mean():+.4f}")

# What if we use absolute OFI?
print("\n=== CONTRARIAN sleeve using abs(OFI) percentile ===")
for q in [0.50, 0.60, 0.70, 0.80, 0.90, 0.95]:
    thr = late['ofi'].abs().quantile(q)
    contra = late[
        ((late['direction']=='DOWN') & (late['ofi'] > thr)) |
        ((late['direction']=='UP') & (late['ofi'] < -thr))
    ]
    if len(contra) < 10: continue
    print(f"  abs(OFI) pctile {q:.2f} (thr={thr:.0f}): n_contra={len(contra):,}  WR={contra['won'].mean():.4f}  $/tr=${contra['pnl_legacy_usd'].mean():+.4f}")

# Verify on chronological split: train 60% / val 20% / lockbox 20%
print("\n=== Chronological 60/20/20 split with ofi_pct |>| 0.5 contrarian ===")
late = late.sort_values('fire_us').reset_index(drop=True)
n = len(late)
i_tr = int(n*0.6)
i_v = int(n*0.8)
tr = late.iloc[:i_tr]; vl = late.iloc[i_tr:i_v]; lb = late.iloc[i_v:]

for ofi_pct_thr in [0.30, 0.40, 0.50, 0.60, 0.70]:
    print(f"\n  Threshold ofi_pct |>| {ofi_pct_thr}:")
    for name, sub in [('train', tr), ('val', vl), ('lockbox', lb)]:
        c = sub[((sub['direction']=='DOWN') & (sub['ofi_pct'] > ofi_pct_thr)) |
                ((sub['direction']=='UP') & (sub['ofi_pct'] < -ofi_pct_thr))]
        if len(c) < 5:
            print(f"    {name:<10}n={len(c):,}  (too small)")
            continue
        print(f"    {name:<10}n={len(c):,}  WR={c['won'].mean():.4f}  $/tr=${c['pnl_legacy_usd'].mean():+.4f}")

# What about MOMENTUM (follow OFI sign)?
print("\n=== MOMENTUM sleeve (direction follows OFI sign) on lockbox ===")
for ofi_pct_thr in [0.30, 0.50, 0.70]:
    mom = late[((late['direction']=='UP') & (late['ofi_pct'] > ofi_pct_thr)) |
               ((late['direction']=='DOWN') & (late['ofi_pct'] < -ofi_pct_thr))]
    if len(mom) < 10: continue
    print(f"  ofi_pct |>| {ofi_pct_thr}: n_mom={len(mom):,}  WR={mom['won'].mean():.4f}  $/tr=${mom['pnl_legacy_usd'].mean():+.4f}")
