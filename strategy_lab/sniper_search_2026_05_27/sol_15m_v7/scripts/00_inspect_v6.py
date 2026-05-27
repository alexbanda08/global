"""Inspect V6 universe + identify cross-asset data sources."""
import os, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
V6 = pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_15m_v6/sol_15m_v6_universe.parquet")
print(f"V6 SOL 15m: {len(V6):,} rows, {len(V6.columns)} cols")
print(f"fire_us range: {pd.to_datetime(V6['fire_us'].min(), unit='us')} -> {pd.to_datetime(V6['fire_us'].max(), unit='us')}")
print(f"\nfire_offset_s unique: {sorted(V6['fire_offset_s'].unique())}")
print(f"won.mean: {V6['won'].mean():.3f}")
print(f"\nGates available:")
gcols = sorted([c for c in V6.columns if c.startswith('g_')])
for g in gcols:
    nn = V6[g].notna().mean()
    if g in V6.columns:
        try:
            ones = V6[g].mean()
            print(f"  {g:50s} non-null={nn*100:5.1f}% ones_rate={ones:.3f}")
        except:
            pass

print(f"\nKey cols: {[c for c in V6.columns if c in ['slug','slot_start_us','ws_s_us','fire_us','direction','outcome','won','entry_vwap','pnl_legacy_usd']]}")
print(f"\nrsi_at_ws non-null: {V6['rsi_at_ws'].notna().mean()*100:.1f}%")
print(f"mp_skew_at_ws non-null: {V6['mp_skew_at_ws'].notna().mean()*100:.1f}%")

# Check microprice panel for BTC/ETH
print("\n=== checking microprice panel for BTC/ETH ===")
mp = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/microprice_panel.parquet", columns=['asset'])
print(f"microprice assets: {mp['asset'].value_counts().to_dict()}")

# Check regime panel
print("\n=== checking regime panel for cross-asset slope ===")
rp15 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
print(f"regime_15m cols: {rp15.columns.tolist()[:30]}")
print(f"regime_15m: {len(rp15):,} rows; assets: {rp15['asset'].value_counts().to_dict() if 'asset' in rp15.columns else 'NO asset col'}")
print(f"first row: {rp15.head(1).T}")
