"""Inspect existing V5 panel + v3 fires for BTC 15m. Confirm what we have."""
import pandas as pd
import os

RES = "data/v4/canonical/_results"
df = pd.read_parquet(f"{RES}/sniper_btc15m_v3_gated.parquet")
print("V5 GATED PANEL")
print(f"  shape: {df.shape}")
print(f"  date range: {pd.to_datetime(df['fire_us'].min(), unit='us', utc=True)} -> {pd.to_datetime(df['fire_us'].max(), unit='us', utc=True)}")
print(f"  unique days: {pd.to_datetime(df['fire_us'], unit='us', utc=True).dt.date.nunique()}")
print(f"  offsets: {sorted(df['fire_offset_s'].unique().tolist())}")
print(f"  directions: {df['direction'].value_counts().to_dict()}")
print(f"  outcome WR: {df['won'].mean():.3f}")
print(f"  by offset WR (UP/DOWN):")
for off in sorted(df['fire_offset_s'].unique()):
    sub = df[df['fire_offset_s']==off]
    sub_up = sub[sub['direction']=='UP']
    sub_dn = sub[sub['direction']=='DOWN']
    print(f"    off={off:>4}: UP n={len(sub_up):>5} WR={sub_up['won'].mean():.3f} | DOWN n={len(sub_dn):>5} WR={sub_dn['won'].mean():.3f}")

print()
print("GATE LIST:")
gates = sorted([c for c in df.columns if c.startswith("g_")])
print(f"  total gates: {len(gates)}")
for g in gates:
    fr = df[g].mean()
    print(f"    {g:42s} fire_rate={fr:.3f}")

print()
print("NON-GATE columns:", [c for c in df.columns if not c.startswith("g_")])
