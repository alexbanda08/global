"""Inspect SOL 15m data sources before building anything."""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"

# 1. The PRIMARY fire universe per brief
log("loading PRIMARY fire universe (oos_fires_SOL_15m_full_v3.parquet)")
prim = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet")
log(f"primary fires SOL 15m: {len(prim):,}")
log(f"  cols: {len(prim.columns)} - first 15: {list(prim.columns[:15])}")
log(f"  Won.mean: {prim.won.mean()*100:.2f}%  date range: {pd.to_datetime(prim.fire_us.min(),unit='us',utc=True)} -> {pd.to_datetime(prim.fire_us.max(),unit='us',utc=True)}")
log(f"  fire_offset_s unique: {sorted(prim.fire_offset_s.unique())}")
log(f"  direction counts: {prim.direction.value_counts().to_dict()}")
# Check for g_* columns
g_cols = [c for c in prim.columns if c.startswith('g_')]
log(f"  g_* columns: {len(g_cols)}")
log(f"    {g_cols[:25]}")

# 2. Master gate features
log("\nloading master_gate_features_v2 for SOL 15m")
mgf = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/master_gate_features_v2.parquet")
mgf_sol = mgf[(mgf.asset=='SOL')&(mgf.tf=='15m')].copy()
log(f"master_gate_features_v2 SOL 15m: {len(mgf_sol):,}")
log(f"  date range: {pd.to_datetime(mgf_sol.fire_us.min(),unit='us',utc=True)} -> {pd.to_datetime(mgf_sol.fire_us.max(),unit='us',utc=True)}")
g_cols_mgf = [c for c in mgf_sol.columns if c.startswith('g_')]
log(f"  g_* columns: {len(g_cols_mgf)}")
log(f"    {g_cols_mgf}")

# 3. Regime panel v2_fixed
log("\nloading regime_panel_15m_v2_fixed for SOL")
r2 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
r2_sol = r2[r2.asset=='SOL'].copy()
log(f"regime_panel_15m_v2_fixed SOL: {len(r2_sol):,}")
log(f"  date range: {pd.to_datetime(r2_sol.ts_us.min(),unit='us',utc=True)} -> {pd.to_datetime(r2_sol.ts_us.max(),unit='us',utc=True)}")
log(f"  cols: {list(r2_sol.columns)}")

# 4. microprice for SOL
log("\nloading microprice panel")
mp = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/microprice_panel.parquet")
# detect asset col if present
mp_cols = list(mp.columns)
log(f"  microprice cols (first 10): {mp_cols[:10]}")
if 'asset' in mp.columns:
    mp_sol = mp[mp.asset=='SOL']
    log(f"  microprice SOL rows: {len(mp_sol):,}")
elif 'slug' in mp.columns:
    sol_mask = mp.slug.astype(str).str.startswith('crypto-up-or-down-sol')
    log(f"  microprice SOL (by slug prefix) rows: {sol_mask.sum():,}")

# 5. SMS panel
log("\nloading sms_panel_15m_v2_fixed")
sms = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/sms_panel_15m_v2_fixed.parquet")
if 'asset' in sms.columns:
    sms_sol = sms[sms.asset=='SOL']
    log(f"  sms SOL rows: {len(sms_sol):,}")
log(f"  sms cols (first 10): {list(sms.columns)[:10]}")

log("\nDONE")
