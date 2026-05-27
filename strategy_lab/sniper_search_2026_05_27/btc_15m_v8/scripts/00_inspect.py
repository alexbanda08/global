"""V8 BTC 15m: inspect v3 fires + V7 panel + auxiliary data."""
import pandas as pd, numpy as np, os
ROOT = r"C:/Users/alexandre bandarra/Desktop/global"

# v3 full fires
df = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_15m_full_v3.parquet")
print("=== V3 FULL FIRES ===")
print("n_rows:", len(df))
print("cols:", list(df.columns))
print("min_date:", pd.to_datetime(df.slot_start_us.min(), unit='us', utc=True))
print("max_date:", pd.to_datetime(df.slot_start_us.max(), unit='us', utc=True))
print("offsets:", sorted(df.fire_offset_s.unique()))
print("dirs:", df.direction.value_counts().to_dict())
print("won mean:", df.won.mean())
print()

# v7 panel for BTC 15m (joinable to v3 fires)
v7 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/sniper_btc15m_v7_gated.parquet")
print("=== V7 PANEL ===")
print("rows:", len(v7), "cols:", len(v7.columns))
print("min_date:", v7.fire_date.min(), "max_date:", v7.fire_date.max())
print("offsets:", sorted(v7.fire_offset_s.unique()))
g_cols = [c for c in v7.columns if c.startswith('g_')]
print("gate count:", len(g_cols))
print("gates:", g_cols[:50])
print("...")
print("non-g cols:", [c for c in v7.columns if not c.startswith('g_')][:50])
print()

# HL panels
hl_fund = pd.read_parquet(f"{ROOT}/data/v4/canonical/hyperliquid_funding.parquet")
print("=== HL FUNDING ===")
print("rows:", len(hl_fund), "cols:", list(hl_fund.columns))
print(hl_fund.head(3))
print("assets:", hl_fund.coin.unique() if 'coin' in hl_fund.columns else 'no coin col')
print("min:", hl_fund.iloc[0])
