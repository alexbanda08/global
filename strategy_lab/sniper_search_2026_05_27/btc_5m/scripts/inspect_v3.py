"""Inspect v3 BTC 5m fire universe schema + coverage."""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
FIRES = ROOT / "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_5m_full_v3.parquet"

df = pd.read_parquet(FIRES)
print(f"Rows: {len(df):,}")
print(f"Cols: {len(df.columns)}")
print()
print("Schema:")
for c in df.columns:
    dt = str(df[c].dtype)
    n_null = df[c].isna().sum()
    sample = df[c].dropna().iloc[0] if df[c].notna().any() else "ALL_NULL"
    print(f"  {c:40s} {dt:15s} nulls={n_null:>8,}  sample={sample}")
print()

# Coverage
df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
print(f"Fire time range: {df.fire_dt.min()} -> {df.fire_dt.max()}")
print(f"Days span: {(df.fire_dt.max()-df.fire_dt.min()).total_seconds()/86400:.2f}")
print()

# Per-offset counts
if "fire_offset_s" in df.columns:
    print("Per-offset counts:")
    print(df.groupby("fire_offset_s").size())
    print()

# Direction / outcome
if "direction" in df.columns:
    print("Direction:")
    print(df["direction"].value_counts())
if "outcome" in df.columns:
    print("Outcome:")
    print(df["outcome"].value_counts())
if "won" in df.columns:
    print(f"Won mean: {df['won'].mean():.4f}")
if "pnl_legacy_usd" in df.columns:
    print(f"pnl_legacy_usd: mean={df['pnl_legacy_usd'].mean():.4f}, min={df['pnl_legacy_usd'].min():.2f}, max={df['pnl_legacy_usd'].max():.2f}")
print()

# g_* columns
g_cols = [c for c in df.columns if c.startswith("g_")]
print(f"Gate cols (g_*): {len(g_cols)}")
for g in g_cols:
    nonnull = df[g].notna().sum()
    n_on = int(df[g].sum()) if nonnull > 0 else 0
    print(f"  {g:40s} nonnull={nonnull:>8,}  on={n_on:>8,}  prev={n_on/max(nonnull,1):.3f}")
print()

# Other interesting fields
other = [c for c in df.columns if c.startswith(("rf_","ribbon_","stoch_","bb_","mfi_","cci_","tr_","markov_","trend_","slope_","imb","queue_","mp_","hawkes_","vpin_","lm_","vol_","hurst_","dev_","ws_s","rsi","ema","hod"))]
print(f"Other feature cols: {len(other)}")
for c in other:
    nonnull = df[c].notna().sum()
    print(f"  {c:40s} nonnull={nonnull:>8,}")
