"""Inspect v3 ETH 5m and 15m fires + BTC/SOL 5m for Path J/Q construction."""
import pandas as pd
import pyarrow.parquet as pq

base = r'C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\_full_window_v3_2026_05_27'
for path in [
    'oos_fires_ETH_5m_full_v3.parquet',
    'oos_fires_ETH_15m_full_v3.parquet',
    'oos_fires_BTC_5m_full_v3.parquet',
    'oos_fires_SOL_5m_full_v3.parquet',
]:
    p = base + '\\' + path
    df = pd.read_parquet(p)
    print(f'== {path} ==')
    print('rows:', len(df))
    print('cols:', list(df.columns)[:60])
    if 'fire_offset_s' in df.columns:
        print('fire_offsets:', df['fire_offset_s'].value_counts().to_dict())
    if 'asset' in df.columns:
        print('assets:', df['asset'].value_counts().to_dict())
    print('first ws:', pd.to_datetime(df['fire_us'].min(), unit='us', utc=True))
    print('last ws:', pd.to_datetime(df['fire_us'].max(), unit='us', utc=True))
    print()
