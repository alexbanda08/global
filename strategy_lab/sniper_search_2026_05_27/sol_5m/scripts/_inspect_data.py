"""Inspect SOL 5m universe."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

# Load OOS fires SOL 5m
fires = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_SOL_5m_v2_fixed.parquet")
print("SOL 5m OOS fires shape:", fires.shape)
print("Cols (first 40):", list(fires.columns)[:40])
print()
print("Date range:", pd.to_datetime(fires['fire_us'].min(), unit='us'), "->", pd.to_datetime(fires['fire_us'].max(), unit='us'))
print()
print("Dtypes summary:")
for c in fires.columns[:40]:
    print(f"  {c}: {fires[c].dtype}")
print()
print("Head 2:")
print(fires.head(2).T.to_string())
