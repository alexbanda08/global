"""Verify all canonical loaders still work after dedup."""
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from load import (
    load_resolutions, load_klines, load_chainlink_rtds,
    load_orderbook_l25_streaming, load_trades,
    load_hyperliquid_klines, load_hyperliquid_liquidations,
    load_hyperliquid_liquidations_full,
)
import pandas as pd

def ts(x): return pd.to_datetime(int(x), unit="us", utc=True).strftime("%Y-%m-%d %H:%M:%S")

print("=== Smoke-testing every loader ===")

res = load_resolutions()
print(f"  load_resolutions: {len(res):,} rows  max ts: {ts(res.slot_start_us.max())}")

k = load_klines("BTC", period_id="1MIN", source="binance-spot-ws")
print(f"  load_klines(BTC, 1MIN): {len(k):,} rows  max ts: {ts(k.time_period_start_us.max())}")

cl = load_chainlink_rtds("BTC")
print(f"  load_chainlink_rtds(BTC): {len(cl):,} rows  max ts: {ts(cl.timestamp_us.max())}")

# Pick a couple recent BTC slugs and load L25
late = res[(res.ticker == "BTC") & (res.slot_start_us > 1779840000_000_000)]  # May 27 04:00+
print(f"  late BTC resolutions (>May 27 04:00): {len(late)}")
sample = set(late.slug.head(3))
books = load_orderbook_l25_streaming("btc", slugs=sample)
print(f"  load_orderbook_l25_streaming(btc, sample 3 slugs): {len(books)} (slug,outcome) keys")

trades = load_trades("btc")
print(f"  load_trades(btc): metadata loaded ({trades})")

hk = load_hyperliquid_klines(asset="BTC", period_id="5MIN")
print(f"  load_hyperliquid_klines(BTC,5MIN): {len(hk):,} rows  max ts: {ts(hk.time_period_start_us.max())}")

hl = load_hyperliquid_liquidations(asset="BTC")
print(f"  load_hyperliquid_liquidations(BTC,last 30d): {len(hl):,} rows  max ts: {ts(hl.time_exchange_us.max())}")

hlf = load_hyperliquid_liquidations_full(asset="BTC")
print(f"  load_hyperliquid_liquidations_full(BTC): {len(hlf):,} rows  max ts: {ts(hlf.time_exchange_us.max())}")

# Verify deleted loader fails clean
try:
    from load import load_binance_metrics
    load_binance_metrics()
    print(f"  load_binance_metrics: UNEXPECTEDLY OK (should have raised)")
except FileNotFoundError as e:
    print(f"  load_binance_metrics: raises FileNotFoundError as expected ({str(e)[:60]}...)")

print("\n=== All loaders OK ===")
