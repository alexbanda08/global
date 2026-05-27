"""Verify HL canonical loaders + parquets."""
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import (
    load_hyperliquid_klines,
    load_hyperliquid_liquidations,
    load_hyperliquid_liquidations_full,
)
import pandas as pd

def ts(x): return pd.to_datetime(int(x), unit="us", utc=True)

print("=== HL klines (full) ===")
df = load_hyperliquid_klines()
print(f"  rows: {len(df):,}  symbols: {df.symbol_id.nunique()}  periods: {sorted(df.period_id.unique())}")
print(f"  window: {ts(df.time_period_start_us.min())} -> {ts(df.time_period_start_us.max())}")

print("\n=== HL klines (BTC, 5MIN) ===")
df = load_hyperliquid_klines(asset="BTC", period_id="5MIN")
print(f"  rows: {len(df):,}  window: {ts(df.time_period_start_us.min())} -> {ts(df.time_period_start_us.max())}")

print("\n=== HL liquidations (last 30d filter) ===")
df = load_hyperliquid_liquidations()
print(f"  rows: {len(df):,}  unique coins: {df.coin.nunique()}")
print(f"  window: {ts(df.time_exchange_us.min())} -> {ts(df.time_exchange_us.max())}")
print(f"  top10 coins: {df.coin.value_counts().head(10).to_dict()}")

print("\n=== HL liquidations FULL (~1 year) ===")
df = load_hyperliquid_liquidations_full()
print(f"  rows: {len(df):,}  unique coins: {df.coin.nunique()}")
print(f"  window: {ts(df.time_exchange_us.min())} -> {ts(df.time_exchange_us.max())}")

print("\n=== HL liqs BTC only (full) ===")
df = load_hyperliquid_liquidations_full(asset="BTC")
print(f"  rows: {len(df):,}  window: {ts(df.time_exchange_us.min())} -> {ts(df.time_exchange_us.max())}")
