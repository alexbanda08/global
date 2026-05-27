"""Threshold sweep — augment deep_stack panels with extra continuous columns.

deep_stack_panel_{s6,s15,v15m}.parquet already has most continuous cols, but is missing:
  - rv_60s, rv_300s, hurst_300s (continuous vol/hurst features)

Output:
  data/v4/canonical/_results/threshold_panel_s6.parquet
  data/v4/canonical/_results/threshold_panel_s15.parquet
  data/v4/canonical/_results/threshold_panel_v15m.parquet
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def augment(base_file: str, vol_files: list[str], out_file: str):
    log(f"=== {base_file} ===")
    df = pd.read_parquet(RES / base_file)
    log(f"  base: {df.shape}")

    # Load vol/hurst panels — concat 5m and 15m if needed
    vh_parts = [pd.read_parquet(RES / f) for f in vol_files]
    vh = pd.concat(vh_parts, ignore_index=True)
    keep = ["asset", "slug", "fire_us", "fire_offset_s",
            "rv_60s", "rv_300s", "hurst_300s"]
    vh = vh[keep].drop_duplicates(["asset", "slug", "fire_us", "fire_offset_s"], keep="first")
    df = df.merge(vh, on=["asset", "slug", "fire_us", "fire_offset_s"], how="left")
    log(f"  rv_60s nonnull: {df.rv_60s.notna().sum():,}/{len(df):,}")

    df.to_parquet(RES / out_file, index=False, compression="zstd")
    log(f"  wrote {out_file}: {df.shape}")


def main():
    augment("deep_stack_panel_s6.parquet",
            ["vol_hurst_at_fire_5m.parquet"],
            "threshold_panel_s6.parquet")
    augment("deep_stack_panel_s15.parquet",
            ["vol_hurst_at_fire_5m.parquet"],
            "threshold_panel_s15.parquet")
    augment("deep_stack_panel_v15m.parquet",
            ["vol_hurst_at_fire_15m.parquet"],
            "threshold_panel_v15m.parquet")


if __name__ == "__main__":
    main()
