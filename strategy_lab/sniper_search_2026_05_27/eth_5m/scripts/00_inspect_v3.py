"""Inspect ETH 5m v3 fire schema and baseline stats."""
import pandas as pd, numpy as np

p = "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_5m_full_v3.parquet"
df = pd.read_parquet(p)
print("shape:", df.shape)
print("cols:", len(df.columns))
for c in df.columns:
    try:
        nu = df[c].nunique(dropna=True) if df[c].dtype != 'O' else df[c].astype(str).nunique()
    except Exception:
        nu = -1
    nn = int(df[c].notna().sum())
    sample = ""
    if nu <= 10 and df[c].dtype != float:
        try:
            sample = " " + str(df[c].value_counts(dropna=False).head(5).to_dict())[:80]
        except Exception:
            pass
    print(f"  {c:44s} {str(df[c].dtype):12s} nu={nu:8d} nn={nn}{sample}")

print()
print(f"baseline WR={df['won'].mean():.4f}  $/tr={df['pnl_legacy_usd'].mean():+.4f}  sum={df['pnl_legacy_usd'].sum():+.2f}")
print(f"fire_us range: {pd.to_datetime(df['fire_us'].min(),unit='us')} -> {pd.to_datetime(df['fire_us'].max(),unit='us')}")
print(f"days: {pd.to_datetime(df['fire_us'],unit='us').dt.date.nunique()}")
print(f"offsets: {sorted(df['fire_offset_s'].unique())}")
print(f"directions: {df['direction'].value_counts().to_dict()}")

# Identify g_* columns already joined
gcols = [c for c in df.columns if c.startswith('g_') or c.startswith('rf_') or c.startswith('ribbon_') or c.startswith('stoch_') or c.startswith('bb_') or c.startswith('mfi_') or c.startswith('cci_') or c.startswith('tr_')]
print(f"\nGate-like cols: {len(gcols)}")
print(gcols)
