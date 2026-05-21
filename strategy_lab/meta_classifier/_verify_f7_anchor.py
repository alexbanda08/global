"""Verify F7 RSI anchor convention against VPS3 shadow trades.

Three candidate anchors tested side-by-side:
  ws_s        = slot_start - window_s  (CLAUDE.md convention, start of prev slot)
  slot_start  = slug suffix             (one window_s later than ws_s)
  slot_end    = at_ts                   (production resolution event time)

Production reports F7 lifts WR from ~45% to 60-80% per cell.
Whichever anchor reproduces that is the right one.
"""
import pandas as pd
import json
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, 'data/v4/canonical')
from load import load_klines_asof

p = Path('data/v4/canonical/trading_events_30d.parquet')
df = pd.read_parquet(p)
df = df[df.kind == 'poly_updown_resolution'].copy()
print(f'Resolutions in canonical trading_events: {len(df):,}')

df['at_ts'] = pd.to_datetime(df['at'], utc=True, format='mixed', errors='coerce')
print(f'After at parse: NaT={df.at_ts.isna().sum()}  valid={df.at_ts.notna().sum()}')
df = df[df.at_ts.notna()].copy()
print(f'at_ts range: {df.at_ts.min()} -> {df.at_ts.max()}')

df['parsed'] = df.data.apply(lambda s: json.loads(s) if isinstance(s, str) else s)
for fld in ['symbol','tf','signal','won','pnl_usd']:
    df[fld] = df.parsed.apply(lambda d: d.get(fld) if isinstance(d, dict) else None)
df['won'] = df.won == True
df['pnl_usd'] = pd.to_numeric(df.pnl_usd, errors='coerce')

df['version'] = df.sleeve_id.apply(lambda s: 'v2' if 'momo_v2' in s else ('v1' if 'momo_' in s else None))
df = df[df.version.notna() & df.symbol.isin(['BTC','ETH','SOL']) & df.tf.isin(['5m','15m'])].copy()
print(f'After filter (BTC/ETH/SOL x 5m/15m, v1/v2): {len(df):,}')

df['slot_end_s']   = (df.at_ts.astype('int64') // 1_000_000_000)
df['window_s']     = df.tf.map({'5m': 300, '15m': 900})
df['slot_start_s'] = df.slot_end_s - df.window_s
df['ws_s']         = df.slot_start_s - df.window_s

# Mode filter — paper only (production-shadow accounting)
modes = df.parsed.apply(lambda d: d.get('mode') if isinstance(d, dict) else None)
df['mode'] = modes
df = df[df['mode'].isin(['paper', 'live'])].copy()
print(f'After mode filter: {len(df):,} ({df["mode"].value_counts().to_dict()})')

klines = {}
for a in ['BTC','ETH','SOL']:
    eu, cl = load_klines_asof(a, 'binance-spot-ws', '1MIN')
    klines[a] = (eu.astype('int64'), cl.astype('float64'))
    print(f'  {a} klines: {len(eu)} bars, last={pd.Timestamp(int(eu[-1]), unit="us", tz="UTC")}')

def rsi_at(end_us_arr, close_arr, anchor_us):
    if not np.isfinite(anchor_us): return float('nan')
    idx = int(np.searchsorted(end_us_arr, int(anchor_us), side='right')) - 1
    if idx < 14 or idx >= len(close_arr): return float('nan')
    if abs(int(end_us_arr[idx]) - int(anchor_us)) > 5 * 60 * 1_000_000: return float('nan')
    closes = close_arr[idx - 14: idx + 1]
    diffs = np.diff(closes)
    gain = np.where(diffs > 0, diffs, 0.0).mean()
    loss = np.where(diffs < 0, -diffs, 0.0).mean()
    if loss <= 0: return 100.0 if gain > 0 else 50.0
    rs = gain / loss
    return 100.0 - 100.0 / (1.0 + rs)

print('\nComputing RSI at 3 candidate anchors...')
df['rsi_ws_s'] = np.nan
df['rsi_slot_start'] = np.nan
df['rsi_slot_end'] = np.nan
for a in ['BTC','ETH','SOL']:
    m = df.symbol == a
    if not m.any(): continue
    eu, cl = klines[a]
    df.loc[m, 'rsi_ws_s']        = [rsi_at(eu, cl, ws*1_000_000) for ws in df.loc[m, 'ws_s']]
    df.loc[m, 'rsi_slot_start']  = [rsi_at(eu, cl, ws*1_000_000) for ws in df.loc[m, 'slot_start_s']]
    df.loc[m, 'rsi_slot_end']    = [rsi_at(eu, cl, ws*1_000_000) for ws in df.loc[m, 'slot_end_s']]

print(f'  NaN: ws_s={df.rsi_ws_s.isna().sum()}  slot_start={df.rsi_slot_start.isna().sum()}  slot_end={df.rsi_slot_end.isna().sum()}')

def f7_keep(sig, rsi):
    if not (rsi == rsi): return False
    if sig == 'UP' and rsi <= 50: return False
    if sig == 'DOWN' and rsi >= 50: return False
    return True

for col, label in [('rsi_ws_s','keep_ws_s'), ('rsi_slot_start','keep_slot_start'), ('rsi_slot_end','keep_slot_end')]:
    df[label] = [f7_keep(s, r) for s, r in zip(df.signal, df[col])]

print()
print('=' * 100)
print('VPS3 SHADOW — F7 anchor comparison')
print('=' * 100)
print(f'{"v":<3} {"cell":<10} {"anchor":<14} {"n":>5} {"wins":>5} {"WR":>6} {"sumPnL":>10} {"/trade":>8}')

for v in ['v1','v2']:
    for (asset, tf), grp in df[df.version == v].groupby(['symbol','tf']):
        cell = f'{asset.lower()}_{tf}'
        n = len(grp); w = int(grp.won.sum()); pn = grp.pnl_usd.sum()
        print(f'{v:<3} {cell:<10} {"ALL":<14} {n:>5} {w:>5} {w/max(n,1)*100:>5.1f}% ${pn:>+9.2f} ${pn/max(n,1):>+7.4f}')
        for anchor_col, anchor_label in [('keep_ws_s','F7@ws_s'),
                                          ('keep_slot_start','F7@slot_start'),
                                          ('keep_slot_end','F7@slot_end')]:
            sub = grp[grp[anchor_col]]
            n = len(sub); w = int(sub.won.sum()); pn = sub.pnl_usd.sum()
            print(f'{v:<3} {cell:<10} {anchor_label:<14} {n:>5} {w:>5} {w/max(n,1)*100:>5.1f}% ${pn:>+9.2f} ${pn/max(n,1):>+7.4f}')
        print()
