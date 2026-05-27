"""Check prefix_fires.parquet for the wider date range we need."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

pf = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/prefix_fires.parquet")
print("prefix_fires shape:", pf.shape)
print("cols:", list(pf.columns))
print()
print("Date range:", pd.to_datetime(pf['fire_us'].min(), unit='us'), "->", pd.to_datetime(pf['fire_us'].max(), unit='us'))
print()
if 'asset' in pf.columns and 'tf' in pf.columns:
    print("by asset/tf:")
    print(pf.groupby(['asset', 'tf']).size())
print()
sol = pf[(pf['asset'] == 'SOL') & (pf['tf'] == '5m')]
print(f"SOL 5m prefix_fires: {len(sol)}")
print("Direction split:", sol['direction'].value_counts().to_dict() if 'direction' in sol.columns else "no direction")
sol_dt = pd.to_datetime(sol['fire_us'], unit='us')
sol2 = sol.copy()
sol2['day'] = sol_dt.dt.date
print("\nDaily fire counts:")
print(sol2.groupby('day').size())

# Also check oos_fires_SOL_5m.parquet (without v2_fixed)
of = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_SOL_5m.parquet")
print(f"\noos_fires_SOL_5m (non-v2) shape: {of.shape}")
of_dt = pd.to_datetime(of['fire_us'], unit='us')
print("Date range:", of_dt.min(), "->", of_dt.max())
