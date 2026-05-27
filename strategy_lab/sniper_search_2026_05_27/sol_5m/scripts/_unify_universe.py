"""Build unified SOL 5m universe combining prefix_fires + oos_fires, then check fields."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

# Load both
pf = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/prefix_fires.parquet")
oos = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_SOL_5m_v2_fixed.parquet")
pf_sol = pf[(pf['asset'] == 'SOL') & (pf['tf'] == '5m')].copy()
print(f"prefix_fires SOL 5m: {len(pf_sol)}")
print(f"oos SOL 5m: {len(oos)}")

# Common cols?
common = sorted(set(pf_sol.columns) & set(oos.columns))
print(f"\nCommon cols ({len(common)}):")
for c in common:
    print(f"  {c}")
only_pf = sorted(set(pf_sol.columns) - set(oos.columns))
only_oos = sorted(set(oos.columns) - set(pf_sol.columns))
print(f"\nOnly in prefix ({len(only_pf)}): {only_pf}")
print(f"\nOnly in oos ({len(only_oos)}): {only_oos}")
