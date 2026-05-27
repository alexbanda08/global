"""Inspect existing V6 panel + BTC panel for V7 SOL 5m work."""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

# V6 SOL panel
p = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v6/_panel_sol_5m_v6.parquet")
print(f"V6 SOL panel: {p.shape}")
print(f"  date range: {pd.to_datetime(p.fire_us.min(),unit='us')} -> {pd.to_datetime(p.fire_us.max(),unit='us')}")
print(f"  columns: {len(p.columns)}")

gates = [c for c in p.columns if c.startswith('g_') or c.startswith('mgf_g_')]
print(f"\nGates: {len(gates)}")
print("Gates (first 30):", gates[:30])

# Check vol_hurst panel
vh = pd.read_parquet("data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")
print(f"\nvol_hurst_at_fire_5m: {vh.shape}")
print("  cols:", list(vh.columns))
print("  assets:", vh['asset'].unique() if 'asset' in vh.columns else 'N/A')
print("  date range:", pd.to_datetime(vh['fire_us'].min(),unit='us') if 'fire_us' in vh.columns else 'N/A',
      "->", pd.to_datetime(vh['fire_us'].max(),unit='us') if 'fire_us' in vh.columns else 'N/A')

# Check 15m fires for parent-regime path
parent = pd.read_parquet("data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet")
print(f"\nSOL 15m fires: {parent.shape}")
print("  cols:", list(parent.columns)[:20])
print("  date range:", pd.to_datetime(parent['fire_us'].min(),unit='us'), "->", pd.to_datetime(parent['fire_us'].max(),unit='us'))

# Check BTC 5m fires for cross-asset path
btc = pd.read_parquet("data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet")
print(f"\nBTC 5m fires: {btc.shape}")
print("  cols:", list(btc.columns)[:30])

# Check what cols exist in master_gate_features for BTC
mgf = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
mgf_btc = mgf[(mgf['asset']=='BTC') & (mgf['tf']=='5m')]
print(f"\nmgf BTC 5m: {mgf_btc.shape}")
print("  cols:", list(mgf_btc.columns)[:30])

# Check regime panel 15m for SOL (parent)
reg15 = pd.read_parquet("data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
reg15_sol = reg15[reg15['asset']=='SOL'] if 'asset' in reg15.columns else reg15
print(f"\nregime_panel_15m_v2_fixed SOL: {reg15_sol.shape}")
print("  cols:", list(reg15_sol.columns)[:30])
print("  regime_label uniques:", reg15_sol['regime_label'].unique() if 'regime_label' in reg15_sol.columns else 'N/A')

# Check microstructure for cross-asset BTC features
microstr = pd.read_parquet("data/v4/canonical/_results/microstructure_panel.parquet")
print(f"\nmicrostructure_panel: {microstr.shape}")
print("  cols:", list(microstr.columns)[:30])
