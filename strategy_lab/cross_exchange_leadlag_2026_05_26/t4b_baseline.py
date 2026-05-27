"""Sanity: compute baseline WR + PnL for bet-UP-always and bet-DN-always on the fire universe."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"
FIRE_PATH = ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_5m.parquet"

WIN_START_US = int(pd.Timestamp("2026-04-30", tz="UTC").value // 1000)
WIN_END_US   = int(pd.Timestamp("2026-05-22", tz="UTC").value // 1000)

df = pd.read_parquet(FIRE_PATH)
df = df[(df.fire_us >= WIN_START_US) & (df.fire_us <= WIN_END_US)]
df['ts'] = pd.to_datetime(df.fire_us, unit='us', utc=True)
print(f"window: {df.ts.min()} → {df.ts.max()}")
print(f"n fires: {len(df):,}")
print(f"outcomes: {df.outcome.value_counts().to_dict()}")

def pnl_up(row):
    if not row.up_fill_ok or not (row.up_usd > 0): return np.nan
    won = (row.outcome == "Up")
    if won:
        return 0.98 * row.up_shares * (1 - row.up_vwap)
    else:
        return -row.up_usd

def pnl_dn(row):
    if not row.dn_fill_ok or not (row.dn_usd > 0): return np.nan
    won = (row.outcome == "Down")
    if won:
        return 0.98 * row.dn_shares * (1 - row.dn_vwap)
    else:
        return -row.dn_usd

# Compute per asset baselines for bet-UP-always
print("\n=== BET-UP-ALWAYS baseline ===")
df['pnl_up'] = df.apply(pnl_up, axis=1)
df['pnl_dn'] = df.apply(pnl_dn, axis=1)
for asset in ["BTC","ETH","SOL"]:
    a = df[df.asset == asset]
    a_up = a[a.pnl_up.notna()]
    a_dn = a[a.pnl_dn.notna()]
    print(f"  {asset} UP: n={len(a_up):,} wr={(a_up.outcome=='Up').mean():.3f} mean={a_up.pnl_up.mean():.4f} sum={a_up.pnl_up.sum():.1f} median={a_up.pnl_up.median():.3f}")
    print(f"  {asset} DN: n={len(a_dn):,} wr={(a_dn.outcome=='Down').mean():.3f} mean={a_dn.pnl_dn.mean():.4f} sum={a_dn.pnl_dn.sum():.1f} median={a_dn.pnl_dn.median():.3f}")
