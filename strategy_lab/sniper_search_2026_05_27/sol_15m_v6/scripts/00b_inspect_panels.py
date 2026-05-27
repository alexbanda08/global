"""Inspect column names for all panels needed."""
import os, sys
import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
os.chdir(ROOT)
sys.path.insert(0, "data/v4/canonical")

panels = {
    "sms_15m_v2": "data/v4/canonical/_results/sms_panel_15m_v2_fixed.parquet",
    "master_v2": "data/v4/canonical/_results/master_gate_features_v2.parquet",
    "microprice": "data/v4/canonical/_results/microprice_panel.parquet",
    "ta_1s": "data/v4/canonical/_results/ta_indicators_1s.parquet",
    "rf_1s": "data/v4/canonical/_results/range_filter_1s.parquet",
    "tr_1s": "data/v4/canonical/_results/traders_reality_1s.parquet",
    "vol_hurst": "data/v4/canonical/_results/vol_hurst_at_fire_15m.parquet",
    "microstructure": "data/v4/canonical/_results/microstructure_panel.parquet",
}

for name, p in panels.items():
    try:
        df = pd.read_parquet(p)
        print(f"=== {name} ({len(df):,} rows) ===")
        print(f"  cols ({len(df.columns)}): {df.columns.tolist()[:25]}")
        ts_cols = [c for c in df.columns if 'us' in c.lower() or 'ts' in c.lower() or 'time' in c.lower()][:3]
        print(f"  ts cols: {ts_cols}")
        if 'asset' in df.columns:
            print(f"  assets: {df['asset'].unique().tolist()}")
            sol = df[df['asset']=='SOL'] if 'asset' in df.columns else df
            print(f"  SOL rows: {len(sol):,}")
        if name == 'master_v2':
            print(f"  ALL cols: {df.columns.tolist()}")
        if name == 'microprice':
            print(f"  ALL cols: {df.columns.tolist()}")
        if name == 'sms_15m_v2':
            print(f"  ALL cols: {df.columns.tolist()}")
        if name == 'vol_hurst':
            print(f"  ALL cols: {df.columns.tolist()}")
        print()
    except Exception as e:
        print(f"=== {name}: ERROR {e}")
