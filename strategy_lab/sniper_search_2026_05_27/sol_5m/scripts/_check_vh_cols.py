"""Check vol_hurst and other feature panel columns."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

vh = pd.read_parquet("data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")
sol = vh[vh['asset'] == 'SOL']
print("vh SOL 5m cols:", list(sol.columns))
print(f"vh SOL 5m shape: {sol.shape}")
print()

# load unified to see what's in vh_*
u = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\sniper_search_2026_05_27\sol_5m\_unified_sol_5m.parquet")
vh_cols = [c for c in u.columns if c.startswith('vh_')]
print(f"vh_* cols in unified ({len(vh_cols)}):", vh_cols)
print()

# Check non-null rates for key features
for c in ['vh_hurst_300s', 'vh_hurst_900s', 'vh_rv_60s', 'vh_rv_300s', 'vh_vol_regime',
          'vh_hawkes_lambda_imbalance', 'vh_vpin_zscore', 'vh_adx_14', 'vh_trend_slope_30m',
          'vh_regime_score', 'vh_L_stat', 'vh_f7_rsi_at_ws']:
    if c in u.columns:
        nn = u[c].notna().sum()
        print(f"  {c}: non-null={nn} ({nn/len(u)*100:.1f}%)")
