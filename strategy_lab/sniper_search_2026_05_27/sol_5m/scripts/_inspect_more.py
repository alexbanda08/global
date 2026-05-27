"""Inspect more cols + offset distribution."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

fires = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_SOL_5m_v2_fixed.parquet")
print("Cols 40-end:")
for c in fires.columns[40:]:
    nz = (fires[c] != 0).sum() if fires[c].dtype != 'object' else fires[c].notna().sum()
    print(f"  {c}: dtype={fires[c].dtype}, nz={nz}")
print()

# Distinct slugs?
print("Unique slugs:", fires['slug'].nunique())
print("Direction counts:", fires['direction'].value_counts().to_dict())
print()

# offset distribution
print("fire_offset_s distribution:")
print(fires['fire_offset_s'].value_counts().sort_index())
print()

# Days
fires['dt'] = pd.to_datetime(fires['fire_us'], unit='us')
fires['day'] = fires['dt'].dt.date
print("Daily counts:")
print(fires.groupby('day').size())
print()

# WR overall
print("Total WR baseline (UP+DOWN):", fires['won'].mean(), "n=", len(fires))
print("Mean PnL legacy / fire ($25):", fires['pnl_legacy_usd'].mean())

# UP/DOWN split
for d in ['UP', 'DOWN']:
    sub = fires[fires['direction'] == d]
    print(f"  {d}: n={len(sub)}, WR={sub['won'].mean():.4f}, dpt=${sub['pnl_legacy_usd'].mean():.3f}")
