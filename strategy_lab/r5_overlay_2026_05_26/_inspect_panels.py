"""Inspect panel schemas for R5-on-R4 overlay task."""
import os, sys
import pandas as pd

os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
BASE = "data/v4/canonical/_results"


def head(p, n=2):
    df = pd.read_parquet(p)
    print(f"\n=== {p} ===")
    print(f"shape: {df.shape}")
    print(f"cols: {list(df.columns)}")
    if len(df):
        print(f"sample:\n{df.head(n).to_string()}")
        # ts range
        for c in ("fire_us", "ws_s", "slot_start_us", "timestamp_us", "ts_us", "t_us", "us"):
            if c in df.columns:
                print(f"{c} range: {df[c].min()} .. {df[c].max()}")
                break


# inputs
head(f"{BASE}/hybrid_fire_universe_15m.parquet", 3)
head(f"{BASE}/microprice_panel.parquet", 3)
head(f"{BASE}/lee_mykland_panel.parquet", 3)
head(f"{BASE}/hawkes_panel.parquet", 3)
head(f"{BASE}/regime_panel_15m.parquet", 3)

# deployable list
dep = pd.read_csv(f"{BASE}/sleeve_hunt_15m_v2_deployable.csv")
print(f"\n=== sleeve_hunt_15m_v2_deployable.csv ===")
print(f"shape: {dep.shape}")
print(f"cols: {list(dep.columns)}")
print(dep.head(5).to_string())
