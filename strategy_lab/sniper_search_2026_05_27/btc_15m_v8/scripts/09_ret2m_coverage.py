"""Investigate why g_ret_2m_strong_with = 0 from May 23-26 — is it a real regime or data gap?"""
import os, sys
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"

df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
df['day'] = df.fire_date.dt.date

# Check ret_2m_at_ws coverage
print("ret_2m_at_ws coverage by day (off=240 UP):")
base = df[(df.fire_offset_s==240) & (df.direction=='UP')].copy()
if 'ret_2m_at_ws' in base.columns:
    by_day = base.groupby('day').agg(
        n=('ret_2m_at_ws','size'),
        n_nonnull=('ret_2m_at_ws', lambda s: s.notna().sum()),
        mean=('ret_2m_at_ws','mean'),
        std=('ret_2m_at_ws','std'),
        n_above_0005=('ret_2m_at_ws', lambda s: (s > 0.0005).sum()),
        n_below_neg0005=('ret_2m_at_ws', lambda s: (s < -0.0005).sum()),
    ).reset_index()
    print(by_day.tail(15).to_string(index=False))
else:
    print("ret_2m_at_ws column missing!")
    print("Available cols matching ret:", [c for c in df.columns if 'ret' in c.lower()])

# is ret_2m_at_ws missing for May 23-26?
late = base[base.fire_date.dt.date >= pd.Timestamp("2026-05-23").date()]
print(f"\nLate window n={len(late)}, ret_2m_at_ws coverage={late.ret_2m_at_ws.notna().mean():.3f}")
print(f"  ret_2m_at_ws stats: {late.ret_2m_at_ws.describe()}")
print(f"  ret_2m_at_ws > 0.0005: {(late.ret_2m_at_ws > 0.0005).sum()}")
print(f"  ret_2m_at_ws > 0:      {(late.ret_2m_at_ws > 0).sum()}")
print(f"  ret_2m_at_ws < 0:      {(late.ret_2m_at_ws < 0).sum()}")
print(f"  ret_2m_at_ws == 0:     {(late.ret_2m_at_ws == 0).sum()}")
print(f"  ret_2m_at_ws is NaN:   {late.ret_2m_at_ws.isna().sum()}")

# Spot check a couple of rows
late_sample = late.head(5)[['fire_date','fire_offset_s','direction','ret_2m_at_ws','won','pnl_legacy_usd']]
print("\nLate sample:")
print(late_sample.to_string(index=False))
