"""Verify ALL canonical sources are current after 2026-05-27 refresh."""
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

CANON = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")

def ts(x): return pd.to_datetime(int(x), unit="us", utc=True).strftime("%Y-%m-%d %H:%M:%S")

print(f"{'SOURCE':<40s} {'ROWS':>15s}  MAX TS")
print("-" * 80)

# Non-L25
for name, p, ts_col in [
    ("klines_1m.parquet", CANON/"klines_1m.parquet", "time_period_start_us"),
    ("klines_1s.parquet", CANON/"klines_1s.parquet", "time_period_start_us"),
    ("chainlink_rtds.parquet", CANON/"chainlink_rtds.parquet", "timestamp_us"),
    ("resolutions.parquet", CANON/"resolutions.parquet", "slot_start_us"),
    ("resolutions_from_rtds.parquet", CANON/"resolutions_from_rtds.parquet", "slot_start_us"),
    ("trading_events_30d.parquet", CANON/"trading_events_30d.parquet", None),
]:
    if not p.exists():
        print(f"{name:<40s} MISSING")
        continue
    if ts_col is None:
        df = pd.read_parquet(p, columns=["at"])
        at = pd.to_datetime(df['at'], utc=True, format='mixed', errors='coerce')
        print(f"{name:<40s} {len(df):>15,}  {at.max().strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        df = pd.read_parquet(p, columns=[ts_col])
        print(f"{name:<40s} {len(df):>15,}  {ts(df[ts_col].max())}")

# Trades polymarket
for asset in ["btc","eth","sol"]:
    p = CANON / "trades_polymarket" / f"{asset}.parquet"
    df = pd.read_parquet(p, columns=["timestamp_us"])
    print(f"{f'trades_polymarket/{asset}.parquet':<40s} {len(df):>15,}  {ts(df.timestamp_us.max())}")

# L25 consolidated
for asset in ["btc","eth","sol"]:
    p = CANON / "orderbook_l25" / f"{asset}.parquet"
    pf = pq.ParquetFile(str(p))
    # last row group max
    df = pd.read_parquet(p, columns=["timestamp_us"])
    print(f"{f'orderbook_l25/{asset}.parquet':<40s} {pf.metadata.num_rows:>15,}  {ts(df.timestamp_us.max())}")

# HL
for name in ["hyperliquid_klines.parquet", "hyperliquid_liquidations_full.parquet"]:
    p = CANON / name
    if name.endswith("klines.parquet"):
        df = pd.read_parquet(p, columns=["time_period_start_us"])
        print(f"{name:<40s} {len(df):>15,}  {ts(df.time_period_start_us.max())}")
    else:
        df = pd.read_parquet(p, columns=["time_exchange_us"])
        print(f"{name:<40s} {len(df):>15,}  {ts(df.time_exchange_us.max())}")
