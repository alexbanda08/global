"""Inspect master_gate_features_v2.parquet schema + per-sleeve direction distribution."""
import pandas as pd
import numpy as np
import os, sys

PANEL = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"

df = pd.read_parquet(PANEL)
print("ROWS:", len(df))
print("COLS:", len(df.columns))
print("\nDTYPES sample:")
for c in df.columns[:60]:
    print(f"  {c}: {df[c].dtype}")
print("\n...REST of columns:")
for c in df.columns[60:]:
    print(f"  {c}: {df[c].dtype}")

# Show any direction/asset/tf/offset cols
candidates = [c for c in df.columns if any(k in c.lower() for k in
              ['direction','dir','asset','tf','offset','sleeve','cell','win','won','pnl','fire_us','slug','strategy','source'])]
print("\nLIKELY ID cols:")
for c in candidates:
    try:
        u = df[c].nunique(dropna=True)
        sample = df[c].dropna().unique()[:8]
        print(f"  {c}: nunique={u} sample={sample}")
    except Exception as e:
        print(f"  {c}: err {e}")

# All g_* gate cols
gates = [c for c in df.columns if c.startswith("g_")]
print(f"\nGATES count: {len(gates)}")
print("Gates:", gates)
