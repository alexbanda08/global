"""Inspect ETH 15m v3 fires file — schema, columns, date range, offsets."""
import pandas as pd, numpy as np

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
fires = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_15m_full_v3.parquet")
print(f"Rows: {len(fires)}")
print(f"Cols: {len(fires.columns)}")
print(f"\nColumns:")
for c in fires.columns:
    print(f"  {c}: {fires[c].dtype}")

print(f"\nDate range:")
print(f"  fire_us min: {pd.to_datetime(fires.fire_us.min(), unit='us', utc=True)}")
print(f"  fire_us max: {pd.to_datetime(fires.fire_us.max(), unit='us', utc=True)}")

print(f"\nUnique offsets:")
print(fires.fire_offset_s.value_counts().sort_index())

print(f"\nWon mean: {fires.won.mean():.3f}")
print(f"Direction:")
print(fires.direction.value_counts())
print(f"\nGate cols (first 30):")
gcols = [c for c in fires.columns if c.startswith('g_')]
print(f"  {len(gcols)} gates")
for c in gcols[:30]: print(f"    {c}")

print(f"\nPnL dist: mean={fires.pnl_legacy_usd.mean():.4f} median={fires.pnl_legacy_usd.median():.4f}")
print(f"Asset values: {fires.asset.unique()}, TF values: {fires.tf.unique()}")
