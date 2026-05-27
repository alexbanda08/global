"""TASK 6: Per-market BEST sleeve table on CLEAN (v2_fixed) panels.

For each (asset, tf) market, find the BEST sleeve by sum_28d_clean after applying:
  - 9-offset canonical grid
  - Correct 28/3.96 scaling
  - L25 fill simulation at $25, $250, $2500

Output:
  data/v4/canonical/_results/per_market_best_sleeve_clean.csv
"""
import os
from pathlib import Path
import pandas as pd
import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

scaling = pd.read_csv(RES / "sleeve_notional_scaling_truth.csv")
master = pd.read_csv(RES / "master_sleeve_catalog_v2_clean.csv")

# Merge — bring in master sleeve metadata for any sleeves not in scaling (e.g. UNIV)
m = master.merge(scaling, on="sleeve_id", how="left", suffixes=("", "_scl"))

# Per-market best: for each (asset, tf, offset bin), top sleeve by sum_28d_clean
def offset_bin(lo, hi):
    if hi <= 60: return "0-60"
    if hi <= 150: return "60-150"
    if hi <= 240: return "150-240"
    if hi <= 300: return "240-300"
    if hi <= 480: return "300-480"
    return "480+"

m["offset_bin"] = m.apply(lambda r: offset_bin(r["off_lo"], r["off_hi"]), axis=1)
m["market"] = m["asset"] + " " + m["tf"]

# Best per market+offset bin
ranked = m.sort_values(["market", "offset_bin", "sum_28d_clean"], ascending=[True, True, False])
best = ranked.groupby(["market", "offset_bin"]).head(1).reset_index(drop=True)

print("=== Per-market BEST CLEAN sleeve ===\n")
disp = best[["market", "offset_bin", "sleeve_id",
              "n_clean", "WR_clean", "dpt_clean", "sum_28d_clean",
              "sum_28d_250", "sum_28d_2500",
              "avg_slip_250", "p90_slip_250", "avg_depth_pct_250",
              "scale_250", "scale_2500"]]
print(disp.to_string(index=False))

# Save
out = RES / "per_market_best_sleeve_clean.csv"
best.to_csv(out, index=False)
print(f"\nwrote {out}")
