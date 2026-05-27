"""Why is f7_rsi_at_ws only 12% populated? Can we rebuild more coverage?"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

p = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v6/_panel_sol_5m_v6.parquet")
print(f"Total: {len(p)}, f7_rsi_at_ws notna: {p['f7_rsi_at_ws'].notna().sum()} ({p['f7_rsi_at_ws'].notna().mean()*100:.1f}%)")

# f7_rsi was probably joined from master_gate_features_v2 — check that source
mgf = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
mgf_sol5 = mgf[(mgf['asset']=='SOL') & (mgf['tf']=='5m')]
print(f"\nmgf SOL 5m total: {len(mgf_sol5)}")
print(f"  date range: {pd.to_datetime(mgf_sol5['fire_us'].min(), unit='us')} -> {pd.to_datetime(mgf_sol5['fire_us'].max(), unit='us')}")
print(f"  f7_rsi_at_ws notna: {mgf_sol5['f7_rsi_at_ws'].notna().sum()} ({mgf_sol5['f7_rsi_at_ws'].notna().mean()*100:.1f}%)")

# Effective panel window when restricting to f7_rsi != nan
f7p = p[p['f7_rsi_at_ws'].notna()]
print(f"\nWith f7 notna: {len(f7p)}; date range: {pd.to_datetime(f7p['fire_us'].min(),unit='us')} -> {pd.to_datetime(f7p['fire_us'].max(),unit='us')}")

# Better: build f7_rsi_at_ws ourselves from binance 1m klines
# Production: 15 closes back from ws_s, simple-mean Wilder RSI
sys.path.insert(0, "data/v4/canonical")
from load import load_klines
btc = load_klines('BTC', 'binance-spot-ws', '1MIN')
print(f"\nBTC 1m klines: {len(btc)}; we can build f7 RSI ourselves with full coverage.")

# Check date coverage
print(f"BTC kline date range: {pd.to_datetime(btc['time_period_start_us'].min(),unit='us')} -> {pd.to_datetime(btc['time_period_start_us'].max(),unit='us')}")
sol = load_klines('SOL', 'binance-spot-ws', '1MIN')
print(f"SOL 1m klines: {len(sol)}; date range: {pd.to_datetime(sol['time_period_start_us'].min(),unit='us')} -> {pd.to_datetime(sol['time_period_start_us'].max(),unit='us')}")
