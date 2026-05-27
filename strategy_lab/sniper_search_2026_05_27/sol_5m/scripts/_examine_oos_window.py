"""Look at the full _full_window_2026_05_26 directory to find the right SOL 5m source."""
import sys, os, glob
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")

# List what's in full_window dir
print("Files in _full_window_2026_05_26:")
for f in sorted(glob.glob("data/v4/canonical/_results/_full_window_2026_05_26/*")):
    try:
        sz = os.path.getsize(f) / 1e6
        print(f"  {f} ({sz:.1f} MB)")
    except:
        pass

# Check other panels for SOL 5m
import pandas as pd
print("\n--- Check full_window_gate_search_per_fire ---")
gs = pd.read_parquet("data/v4/canonical/_results/full_window_gate_search_per_fire.parquet")
print("cols:", list(gs.columns))
print("shape:", gs.shape)
if 'asset' in gs.columns:
    print("by asset/tf:")
    print(gs.groupby(['asset', 'tf']).size())
