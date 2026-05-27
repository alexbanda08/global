"""Explore additional feature panels available for SOL 5m enrichment."""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")
import pandas as pd
import numpy as np

# What canonical _results / gate panels exist?
import glob
files = sorted(glob.glob("data/v4/canonical/_results/*.parquet"))
print("PARQUETS in _results:")
for f in files:
    try:
        sz = os.path.getsize(f) / 1e6
        print(f"  {f} ({sz:.1f} MB)")
    except: pass

# Check master_gate features v2 and hybrid_features_5m
print()
for path in [
    "data/v4/canonical/_results/master_gate_features_v2.parquet",
    "data/v4/canonical/_results/hybrid_features_5m.parquet",
    "data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet",
    "data/v4/canonical/_results/sms_panel_5m_v2_fixed.parquet",
    "data/v4/canonical/_results/microprice_panel.parquet",
    "data/v4/canonical/_results/microstructure_panel.parquet",
    "data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet",
    "data/v4/canonical/_results/lee_mykland_panel.parquet",
    "data/v4/canonical/_results/hawkes_panel.parquet",
    "data/v4/canonical/_results/vpin_panel.parquet",
]:
    if os.path.exists(path):
        try:
            df = pd.read_parquet(path)
            print(f"\n{path}:")
            print(f"  shape: {df.shape}")
            print(f"  cols(20): {list(df.columns)[:20]}")
            if 'asset' in df.columns:
                print(f"  assets: {df['asset'].value_counts().to_dict()}")
            if 'tf' in df.columns:
                print(f"  tfs: {df['tf'].value_counts().to_dict()}")
        except Exception as e:
            print(f"\n{path}: ERR {e}")
    else:
        print(f"\n{path}: MISSING")
