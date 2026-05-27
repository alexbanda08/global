"""Enrich unified panel with hawkes + lee_mykland (broad time-series, full coverage)
via causal asof on fire_us-1s.
"""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
import time
from pathlib import Path

OUT = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\sniper_search_2026_05_27\sol_5m")
t0 = time.time()

print("[1/4] Loading unified panel...")
u = pd.read_parquet(OUT / "_unified_sol_5m.parquet")
print(f"  rows: {len(u)}")

# --- Hawkes (1s granularity per asset) ---
print("\n[2/4] Enriching with Hawkes...")
hk = pd.read_parquet("data/v4/canonical/_results/hawkes_panel.parquet")
hk_sol = hk[hk['asset'] == 'SOL'][['ts_us', 'lambda_buy', 'lambda_sell', 'lambda_total', 'lambda_imbalance', 'recent_burst']].copy()
hk_sol = hk_sol.sort_values('ts_us').reset_index(drop=True)
print(f"  hawkes SOL rows: {len(hk_sol)}, ts range {pd.to_datetime(hk_sol['ts_us'].min(),unit='us')} -> {pd.to_datetime(hk_sol['ts_us'].max(),unit='us')}")

u = u.sort_values('fire_us').reset_index(drop=True)
u['ts_us_lookup'] = u['fire_us'] - 1_000_000  # 1s back
# asof merge
u = pd.merge_asof(u, hk_sol, left_on='ts_us_lookup', right_on='ts_us', direction='backward', tolerance=5_000_000)
u = u.rename(columns={'lambda_buy': 'hk_lambda_buy', 'lambda_sell': 'hk_lambda_sell',
                       'lambda_total': 'hk_lambda_total', 'lambda_imbalance': 'hk_lambda_imbalance',
                       'recent_burst': 'hk_recent_burst', 'ts_us': 'hk_ts_us'})
nn = u['hk_lambda_imbalance'].notna().sum()
print(f"  After hawkes: {nn} ({nn/len(u)*100:.1f}%) enriched")

# --- VPIN ---
print("\n[3/4] Enriching with VPIN...")
vp = pd.read_parquet("data/v4/canonical/_results/vpin_panel.parquet")
vp_sol = vp[vp['asset'] == 'SOL'][['ts_us', 'vpin_value', 'vpin_zscore', 'current_bucket_buy_pct']].sort_values('ts_us').reset_index(drop=True)
vp_sol = vp_sol.rename(columns={'vpin_value': 'vp_value', 'vpin_zscore': 'vp_zscore', 'current_bucket_buy_pct': 'vp_buy_pct'})
print(f"  vpin SOL rows: {len(vp_sol)}")
u = u.sort_values('ts_us_lookup').reset_index(drop=True)
u = pd.merge_asof(u, vp_sol, left_on='ts_us_lookup', right_on='ts_us', direction='backward', tolerance=5_000_000)
u = u.rename(columns={'ts_us': 'vp_ts_us'})
nn = u['vp_value'].notna().sum()
print(f"  After vpin: {nn} ({nn/len(u)*100:.1f}%) enriched")

# --- Lee-Mykland ---
print("\n[4/4] Enriching with Lee-Mykland...")
lm = pd.read_parquet("data/v4/canonical/_results/lee_mykland_panel.parquet")
lm_sol = lm[lm['asset'] == 'SOL'][['ts_us', 'L_stat', 'is_jump_01', 'is_jump_05', 'is_jump_extreme', 'jump_dir_01', 'jump_dir_05']].sort_values('ts_us').reset_index(drop=True)
lm_sol = lm_sol.rename(columns={'L_stat': 'lm_L_stat', 'is_jump_01': 'lm_is_jump_01',
                                  'is_jump_05': 'lm_is_jump_05', 'is_jump_extreme': 'lm_is_jump_extreme',
                                  'jump_dir_01': 'lm_jump_dir_01', 'jump_dir_05': 'lm_jump_dir_05'})
print(f"  LM SOL rows: {len(lm_sol)}")
u = u.sort_values('ts_us_lookup').reset_index(drop=True)
u = pd.merge_asof(u, lm_sol, left_on='ts_us_lookup', right_on='ts_us', direction='backward', tolerance=5_000_000)
u = u.rename(columns={'ts_us': 'lm_ts_us'})
nn = u['lm_L_stat'].notna().sum()
print(f"  After LM: {nn} ({nn/len(u)*100:.1f}%) enriched")

# clean up
u = u.drop(columns=['ts_us_lookup', 'hk_ts_us', 'vp_ts_us', 'lm_ts_us', 'dt', 'day'], errors='ignore')
u = u.sort_values('fire_us').reset_index(drop=True)

out_path = OUT / "_unified_sol_5m_full.parquet"
u.to_parquet(out_path, index=False, compression="zstd")
print(f"\nWrote {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
print(f"Total cols: {len(u.columns)}")
print(f"Elapsed: {time.time()-t0:.1f}s")
