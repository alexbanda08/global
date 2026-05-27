"""Inspect master_gate_features_v2 for SOL 5m and hybrid_features_5m."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

mgf = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
sol = mgf[(mgf['asset'] == 'SOL') & (mgf['tf'] == '5m')].copy()
print("SOL 5m master_gate_features_v2 shape:", sol.shape)
print("All cols:", list(sol.columns))
print()
print("Date range:", pd.to_datetime(sol['fire_us'].min(), unit='us'), "->", pd.to_datetime(sol['fire_us'].max(), unit='us'))
print()
# gate cols (g_)
g_cols = [c for c in sol.columns if c.startswith('g_')]
print(f"Gate cols ({len(g_cols)}):")
for g in g_cols:
    nz = sol[g].fillna(0).astype(int).sum()
    rate = nz / len(sol) * 100
    print(f"  {g}: {nz} ({rate:.1f}%)")
print()
print("won_int present?", 'won_int' in sol.columns, "won?", 'won' in sol.columns)
print("WR baseline (won):", sol['won'].mean(), "n=", len(sol))
print("pnl_legacy_usd mean:", sol['pnl_legacy_usd'].mean())

# offset bins
print("\nOffset bins available:")
print(sol['fire_offset_s'].value_counts().sort_index())

# Days
sol['dt'] = pd.to_datetime(sol['fire_us'], unit='us')
sol['day'] = sol['dt'].dt.date
print("\nDays:")
print(sol.groupby('day').size())

# unique slugs
print("\nUnique slugs:", sol['slug'].nunique())
