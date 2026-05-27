"""Verify why master_gate_features_v2 has 78.8% WR baseline for SOL 5m."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

mgf = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
sol = mgf[(mgf['asset'] == 'SOL') & (mgf['tf'] == '5m')].copy()
print("SOL 5m mgf shape:", sol.shape)
print("direction counts:", sol['direction'].value_counts().to_dict())
print("outcome counts:", sol['outcome'].value_counts().to_dict())
# is this the won-side only? check sleeve_id and gate_stack
print("\ngate_stack unique:", sol['gate_stack'].unique()[:10])
print("sleeve_id unique:", sol['sleeve_id'].unique()[:10])
# offset bins
print("\noffset_bin distinct:", sol['offset_bin'].unique())
# group by direction
for d in ['UP', 'DOWN']:
    sub = sol[sol['direction'] == d]
    print(f"  {d}: n={len(sub)}, WR={sub['won'].mean():.4f}, dpt=${sub['pnl_legacy_usd'].mean():.3f}")

# overall, both sides present?
# count slugs with both sides
slug_dirs = sol.groupby('slug')['direction'].nunique()
print("\nslugs with both UP and DOWN:", (slug_dirs == 2).sum())
print("slugs with one side:", (slug_dirs == 1).sum())

# only certain sleeves?
print("\nsleeve_id value counts:")
print(sol['sleeve_id'].value_counts().head(20))
