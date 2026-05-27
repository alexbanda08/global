"""Inspect full features panel & top R4 deployables."""
import os
import pandas as pd

os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
BASE = "data/v4/canonical/_results"

df = pd.read_parquet(f"{BASE}/sleeve_hunt_15m_full_features.parquet")
print("full features:", df.shape)
print("cols (first 60):", list(df.columns)[:60])
print("...")
print("g_ gates:", sorted([c for c in df.columns if c.startswith("g_")]))
print("\nwindow split:", df["window"].value_counts().to_dict())
print("\nby asset:")
print(df.groupby(["asset","window"]).size().unstack(fill_value=0))

print("\nfire_us range:")
ts = pd.to_datetime(df["fire_us"], unit="us", utc=True)
print(f"  {ts.min()} -> {ts.max()}")

# Deployable list — top 25 by lockbox_sum_pnl
dep = pd.read_csv(f"{BASE}/sleeve_hunt_15m_v2_deployable.csv")
dep = dep.sort_values("lockbox_sum_pnl", ascending=False).reset_index(drop=True)
print(f"\nDeployables: {len(dep)}")
top25 = dep.head(25)[["asset","offset_bin","pool","gate_stack","k",
                       "lockbox_n","lockbox_WR","lockbox_dpt","lockbox_sum_pnl",
                       "train_n","train_WR","val_n","val_WR"]]
print("\nTop 25 R4 deployable sleeves:")
print(top25.to_string())
