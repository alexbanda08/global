"""Check auxiliary data for V8: 1h klines (for grandparent), microprice panel (for shock), HL funding range, regime_v2."""
import pandas as pd, numpy as np
ROOT = r"C:/Users/alexandre bandarra/Desktop/global"

# klines for 1h grandparent
import sys
sys.path.insert(0, f"{ROOT}/data/v4/canonical")
from load import load_klines

# Check what tf are loadable
for tf in ["1h", "15m", "5m"]:
    try:
        k = load_klines(asset="BTC", tf=tf)
        print(f"BTC {tf}: {len(k)} rows, cols={list(k.columns)[:8]}, min={pd.to_datetime(k.iloc[0,0])}, max={pd.to_datetime(k.iloc[-1,0])}")
    except Exception as e:
        print(f"BTC {tf}: FAIL {e}")

# microprice panel
try:
    mp = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/microprice_panel.parquet")
    print("MICROPRICE:", len(mp), "cols:", list(mp.columns)[:20])
    print("min slot_start_us:", pd.to_datetime(mp.slot_start_us.min(), unit='us', utc=True))
    print("max slot_start_us:", pd.to_datetime(mp.slot_start_us.max(), unit='us', utc=True))
    print("assets:", mp.asset.unique() if 'asset' in mp.columns else 'no asset')
    print("tf:", mp.tf.unique() if 'tf' in mp.columns else 'no tf')
except Exception as e:
    print("MICROPRICE fail:", e)

# regime_v2 panels
for tf in ["15m", "5m"]:
    try:
        r = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_{tf}_v2_fixed.parquet")
        print(f"REGIME {tf} v2: {len(r)} rows, cols={list(r.columns)[:10]}")
        if 'bar_end_us' in r.columns:
            print(f"  min={pd.to_datetime(r.bar_end_us.min(), unit='us', utc=True)}, max={pd.to_datetime(r.bar_end_us.max(), unit='us', utc=True)}")
        if 'asset' in r.columns:
            print(f"  assets: {r.asset.unique()}")
    except Exception as e:
        print(f"REGIME {tf} fail:", e)

# HL funding range
hl = pd.read_parquet(f"{ROOT}/data/v4/canonical/hyperliquid_funding.parquet")
btc_hl = hl[hl.symbol == "BTC"].copy().sort_values("funding_time_us")
print("HL BTC funding: n=", len(btc_hl))
print("  min:", pd.to_datetime(btc_hl.funding_time_us.min(), unit='us', utc=True))
print("  max:", pd.to_datetime(btc_hl.funding_time_us.max(), unit='us', utc=True))
print("  funding_rate stats:", btc_hl.funding_rate.describe())

# HL liquidations
hl_liq = pd.read_parquet(f"{ROOT}/data/v4/canonical/hyperliquid_liquidations_full.parquet")
print("HL LIQ cols:", list(hl_liq.columns))
print("HL LIQ rows:", len(hl_liq))
if 'time' in hl_liq.columns:
    print("  min time:", hl_liq.iloc[0])
print(hl_liq.head(2))
