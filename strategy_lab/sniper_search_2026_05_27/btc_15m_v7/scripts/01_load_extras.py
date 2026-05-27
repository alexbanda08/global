"""Inspect vol_hurst_at_fire_15m to know columns + join key."""
import pandas as pd
RES = "data/v4/canonical/_results"
vh = pd.read_parquet(f"{RES}/vol_hurst_at_fire_15m.parquet")
print(f"vol_hurst_at_fire_15m: {len(vh)} rows, {len(vh.columns)} cols")
print(vh.columns.tolist())
print()
print(vh.dtypes)
print()
print(vh.head(3))
print()
print("coverage of key features:")
for c in vh.columns:
    if vh[c].dtype in ('float32', 'float64', 'int32', 'int64'):
        non_null = vh[c].notna().sum()
        print(f"  {c}: non_null={non_null}/{len(vh)} ({non_null/len(vh)*100:.0f}%)")
