"""Sanity check: is the May 23-26 absence of fires real or a data gap?"""
import os, sys
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
OUTDIR = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/btc_15m_v8"
PANEL = f"{RES}/sniper_btc15m_v8_gated.parquet"

df = pd.read_parquet(PANEL)
df['fire_date'] = pd.to_datetime(df.fire_us, unit='us', utc=True)

# Off=240 UP fires per day across whole window
base = df[(df.fire_offset_s==240) & (df.direction=='UP')].copy()
daily = base.groupby(base.fire_date.dt.date).size()
print("Off=240 UP fires per day (all 33 days):")
for d, n in daily.items():
    print(f"  {d}: {n} fires")

# How many fires by each gate per day in lockbox
print("\nGate-level fire counts per day in lockbox window (May 20-26):")
gates = ['g_bb_pos_with','g_mp_no_extreme_150','g_ret_2m_strong_with','g_tr_above_cloud']
lock_window = base[(base.fire_date >= pd.Timestamp("2026-05-20", tz="UTC")) &
                   (base.fire_date < pd.Timestamp("2026-05-27", tz="UTC"))].copy()
print(f"Total off=240 UP fires in lockbox: {len(lock_window)}")
print("Per-day:")
for d, n in lock_window.groupby(lock_window.fire_date.dt.date).size().items():
    print(f"  {d}: {n}")

# Per-gate fire-rate per day in lockbox
print("\nFire-rate when each gate ON, per day:")
for g in gates:
    print(f"\n  {g}:")
    sub_g = lock_window[lock_window[g] == 1]
    for d, n in sub_g.groupby(sub_g.fire_date.dt.date).size().items():
        print(f"    {d}: {n}")

# All-3 (no cloud) combined per day:
print("\nWINNER (3-leg) fires per day in lockbox:")
m = np.ones(len(lock_window), dtype=bool)
for g in ['g_bb_pos_with','g_mp_no_extreme_150','g_ret_2m_strong_with']:
    m &= (lock_window[g].values == 1)
sub_win = lock_window[m]
for d, n in sub_win.groupby(sub_win.fire_date.dt.date).size().items():
    print(f"  {d}: {n}")

# Which gate is the limiting filter on May 23-26?
print("\nDIAGNOSTIC May 23-26: which gates DON'T fire?")
late = lock_window[lock_window.fire_date.dt.date >= pd.Timestamp("2026-05-23").date()]
print(f"  off=240 UP fires May 23-26: {len(late)}")
for g in gates:
    print(f"    {g} ON: {(late[g]==1).sum()} / {len(late)}")

# 2-leg ret_2m_strong + bb_pos
m2 = (late['g_ret_2m_strong_with']==1) & (late['g_bb_pos_with']==1)
print(f"  ret_2m_strong + bb_pos: {m2.sum()}")
m3 = (late['g_ret_2m_strong_with']==1)
print(f"  ret_2m_strong alone: {m3.sum()}")

print("\nFire-date max in panel:")
print(f"  max fire_date: {df.fire_date.max()}")
print(f"  panel coverage end (last UP fire): {base.fire_date.max()}")
