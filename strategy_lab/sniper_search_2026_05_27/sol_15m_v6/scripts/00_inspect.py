"""Inspect schemas and basic stats for SOL 15m V6."""
import sys, os
sys.path.insert(0, "data/v4/canonical")
import pandas as pd
import numpy as np

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
os.chdir(ROOT)

# Primary fires
fp = "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet"
df = pd.read_parquet(fp)
print(f"=== SOL 15m v3 fires: {len(df):,} rows, {len(df.columns)} cols ===")
print(df.columns.tolist())
print("\nDtype sample:")
print(df.dtypes.head(30))
print(f"\nfire_offset_s unique: {sorted(df['fire_offset_s'].unique())}")
print(f"Direction counts: {df['direction'].value_counts().to_dict()}")
print(f"Won.mean: {df['won'].mean():.4f}")
print(f"Outcome columns: {[c for c in df.columns if 'outcome' in c.lower() or 'won' in c.lower()]}")
print(f"Date range: {pd.to_datetime(df['slot_start_us'].min(), unit='us')} → {pd.to_datetime(df['slot_start_us'].max(), unit='us')}")
print(f"Entry vwap stats: min={df['entry_vwap'].min():.3f} max={df['entry_vwap'].max():.3f} mean={df['entry_vwap'].mean():.3f}")

# Check V5 saved file (already has gate columns joined)
fp5 = "strategy_lab/sniper_search_2026_05_27/sol_15m/sol_15m_fires_v2fix_gates.parquet"
df5 = pd.read_parquet(fp5)
print(f"\n=== V5 saved fires (with gates): {len(df5):,} rows, {len(df5.columns)} cols ===")
print([c for c in df5.columns if c.startswith("g_") or c in ("rf_aged","tr_stack_with","tr_stack_full_with","trend_slope_with")])
