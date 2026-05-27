"""Probe trades_polymarket / trading_events + fire universe."""
import pandas as pd
from datetime import datetime, timezone

# Fire universe
fp = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_BTC_15m_full_v3.parquet"
df = pd.read_parquet(fp)
print("=== oos_fires_BTC_15m ===")
print(f"  rows: {len(df):,}")
print(f"  cols ({len(df.columns)}): {list(df.columns)}")
print(f"  head:")
print(df.head(3))
print(f"  outcome.unique: {df['outcome'].unique() if 'outcome' in df.columns else 'NA'}")
print(f"  direction.unique: {df['direction'].unique() if 'direction' in df.columns else 'NA'}")
print(f"  fire_offset_s.unique: {sorted(df['fire_offset_s'].unique()) if 'fire_offset_s' in df.columns else 'NA'}")
print()

# trading_events
fp = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trading_events_30d.parquet"
df = pd.read_parquet(fp)
print("=== trading_events_30d ===")
print(f"  rows: {len(df):,}")
print(f"  cols: {list(df.columns)}")
print(f"  event types: {df['event_type'].value_counts().head(10) if 'event_type' in df.columns else 'na'}")
print(df.head(3))
print()

# trades_polymarket
import glob, os
tp_dir = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trades_polymarket"
files = sorted(glob.glob(os.path.join(tp_dir, "*.parquet")))
print(f"=== trades_polymarket files ({len(files)}) ===")
for f in files[:5]:
    print(f"  {os.path.basename(f)} ({os.path.getsize(f)/1e6:.1f} MB)")
if files:
    df = pd.read_parquet(files[0])
    print(f"  cols: {list(df.columns)}")
    print(f"  rows: {len(df):,}")
    print(df.head(3))
