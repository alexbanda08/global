"""Inspect all feature panels so we know what columns exist for the master join."""
import sys
import os
sys.path.insert(0, "data/v4/canonical")

import pandas as pd

PANELS = [
    "hybrid_features_5m.parquet",
    "hybrid_features_15m.parquet",
    "microprice_panel.parquet",
    "lee_mykland_panel.parquet",
    "hawkes_panel.parquet",
    "vpin_panel.parquet",
    "vpin_hawkes_at_fires.parquet",
    "vol_hurst_at_fire_5m.parquet",
    "vol_hurst_at_fire_15m.parquet",
    "microstructure_panel.parquet",
    "regime_panel_5m.parquet",
    "regime_panel_15m.parquet",
    "sms_panel_5m.parquet",
    "sms_panel_15m.parquet",
    "hybrid_fire_universe_5m.parquet",
    "hybrid_fire_universe_15m.parquet",
    "master_5m_panel.parquet",
    "master_15m_panel.parquet",
    "mlofi_panel.parquet",
    "as_panel.parquet",
]
BASE = "data/v4/canonical/_results"

for p in PANELS:
    fp = os.path.join(BASE, p)
    if not os.path.exists(fp):
        print(f"MISSING: {p}")
        continue
    try:
        df = pd.read_parquet(fp)
    except Exception as e:
        print(f"ERR {p}: {e}")
        continue
    print(f"\n=== {p}  rows={len(df):,}  cols={len(df.columns)} ===")
    print(f"  cols: {list(df.columns)[:40]}")
    if 'asset' in df.columns:
        print(f"  assets: {df['asset'].unique()[:6]}")
    for tcol in ('fire_us', 'ws_s', 'slot_start_us', 't_us', 'timestamp_us', 'as_of_us', 'at_us'):
        if tcol in df.columns:
            print(f"  has time col {tcol}, dtype={df[tcol].dtype}")
            break
