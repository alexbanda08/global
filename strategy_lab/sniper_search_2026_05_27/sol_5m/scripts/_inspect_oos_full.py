"""Inspect FULL OOS fires panel cols and the hybrid_features_5m for SOL coverage."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

fires = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_SOL_5m_v2_fixed.parquet")
print("OOS fires cols (all 68):")
for c in fires.columns:
    nz = (fires[c].fillna(0).astype(float) != 0).sum() if fires[c].dtype != 'object' else fires[c].notna().sum()
    print(f"  {c}: dtype={fires[c].dtype}, nz/non-null={nz}")

print()
print("OOS fires has ws_s? Date range from fire_us:")
fires['dt'] = pd.to_datetime(fires['fire_us'], unit='us')
print(fires['dt'].min(), "->", fires['dt'].max(), "(", (fires['dt'].max() - fires['dt'].min()).days, "days)")

# Now check hybrid_features_5m for SOL with broader date range
hf = pd.read_parquet("data/v4/canonical/_results/hybrid_features_5m.parquet")
sol_hf = hf[hf['asset'] == 'SOL'].copy()
print(f"\nhybrid_features_5m SOL shape: {sol_hf.shape}")
sol_hf['dt'] = pd.to_datetime(sol_hf['fire_us'], unit='us')
print(f"Date range: {sol_hf['dt'].min()} -> {sol_hf['dt'].max()} ({(sol_hf['dt'].max() - sol_hf['dt'].min()).days} days)")
# offsets
print("Offset distribution:")
print(sol_hf['fire_offset_s'].value_counts().sort_index())

# direction split
print("\nDirection counts:")
print(sol_hf['direction'].value_counts() if 'direction' in sol_hf.columns else "no direction col")
# what cols differ?
extra = set(sol_hf.columns) - set(fires.columns)
print(f"\nCols in hf but not OOS fires ({len(extra)}):")
for c in sorted(extra)[:80]:
    print(f"  {c}: {sol_hf[c].dtype}")
