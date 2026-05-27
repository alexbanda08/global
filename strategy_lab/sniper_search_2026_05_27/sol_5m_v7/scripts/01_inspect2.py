"""Inspect klines for BTC cross-asset feature build."""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

# Check klines available for BTC trend → SOL fire
# We'll use load helpers
sys.path.insert(0, "data/v4/canonical")
from load import load_klines, asof_strict

# Load BTC binance 1m klines as the source for cross-asset
btc_1m = load_klines('BTC', source='binance-spot-ws', period_id='1MIN')
print(f"BTC 1m klines: {btc_1m.shape}")
print(f"  cols: {list(btc_1m.columns)[:20]}")
print(f"  date range: {pd.to_datetime(btc_1m['time_period_start_us'].min(), unit='us')} -> {pd.to_datetime(btc_1m['time_period_start_us'].max(), unit='us')}")
print(f"  head:")
print(btc_1m.head(3))
print(f"  tail:")
print(btc_1m.tail(3))

# What does ribbon_color encode?
p = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v6/_panel_sol_5m_v6.parquet")
print(f"\nribbon_color uniques: {p['ribbon_color'].unique()[:20] if 'ribbon_color' in p.columns else 'N/A'}")
print(f"\nVol regime / hurst signal cols available:")
for c in ['vol_regime', 'rv_60s', 'rv_300s', 'rv_900s', 'rv_3600s', 'rv_pct_24h',
          'hurst_100s', 'hurst_300s', 'hurst_900s',
          'g_vol_low','g_vol_med','g_vol_high','g_hurst_trending','g_hurst_reverting',
          'g_vol_expanding','g_vol_contracting']:
    if c in p.columns:
        try:
            print(f"  {c}: dtype={p[c].dtype}, present_frac={p[c].notna().mean():.3f}, mean={p[c].mean():.4f}")
        except Exception as e:
            print(f"  {c}: error {e}")

# Check existing offset distribution to make sure we know what's there
print(f"\nOffset distribution: {p['fire_offset_s'].value_counts().sort_index().to_dict()}")

# Show some example f7_rsi_at_ws values
if 'f7_rsi_at_ws' in p.columns:
    print(f"\nf7_rsi_at_ws stats: notna={p['f7_rsi_at_ws'].notna().mean():.3f}, median={p['f7_rsi_at_ws'].median():.2f}")
