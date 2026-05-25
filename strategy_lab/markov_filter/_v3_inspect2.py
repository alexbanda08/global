"""Inspect V2 CVD overlay further — semantics of maker_side, scenario, outcome interplay."""
import pandas as pd
import numpy as np

path = r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\mint_and_sell_cvd_overlay.csv"
df = pd.read_csv(path)

print("== scenario distribution ==")
print(df['scenario'].value_counts())
print()
print("== scenario × maker_side cross-tab ==")
print(pd.crosstab(df['scenario'], df['maker_side']))
print()
print("== outcome × maker_side cross-tab ==")
print(pd.crosstab(df['outcome'], df['maker_side']))
print()
print("== up_filled / dn_filled × maker_side ==")
print(df.groupby('maker_side').agg(
    up_filled_pct=('up_filled', 'mean'),
    dn_filled_pct=('dn_filled', 'mean'),
    n=('slug', 'count'),
    mean_pnl=('pnl_hold', 'mean'),
    sum_pnl=('pnl_hold', 'sum'),
).round(4))
print()
print("== pnl_hold by scenario ==")
print(df.groupby('scenario').agg(
    n=('slug', 'count'),
    mean_pnl=('pnl_hold', 'mean'),
    sum_pnl=('pnl_hold', 'sum'),
).round(4))
print()
# Distribution of pnl by maker_side × outcome
print("== pnl by maker_side × outcome (mean) ==")
print(df.groupby(['maker_side','outcome'])['pnl_hold'].agg(['count','mean','sum']).round(4))

# Time span
ts_min = df['ts'].min()
ts_max = df['ts'].max()
span_us = ts_max - ts_min
span_days = span_us / (24*3600*1e6)
print(f"\n== span: {span_days:.2f} days ==")

# Per-cell V2 baseline daily pnl
print("\n== V2 baseline daily PnL per cell ==")
v2 = df.groupby('cell').agg(
    n=('slug','count'),
    sum_pnl=('pnl_hold','sum'),
    sum_pnl_hybrid=('pnl_hybrid','sum'),
)
v2['daily_hold'] = v2['sum_pnl'] / span_days
v2['daily_hybrid'] = v2['sum_pnl_hybrid'] / span_days
print(v2.round(3))
print()
print("TOTAL V2 daily (hold):", v2['daily_hold'].sum())
print("TOTAL V2 daily (hybrid):", v2['daily_hybrid'].sum())
