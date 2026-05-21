"""Reverse-engineer the live F7 controller's RSI anchor.

`fires_with_gates.csv` from the other agent's report has `is_f7` per fire =
whether the LIVE F7 sleeve kept that fire. Compute F7 (RSI > 50 for UP /
< 50 for DOWN) at 4 candidate anchors and match against `is_f7`:

  - fire_us  = the fire timestamp (slot_start - (window_s - 120))
  - ws_s     = slot_start - window_s   (signal anchor, 120s before fire)
  - slot_start = slug suffix            (window_s - 120 AFTER fire)
  - slot_end = slot_start + window_s    (way after fire, lookahead)

Whichever anchor's keep-decisions match `is_f7` is what production uses.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, 'data/v4/canonical')
from load import load_klines_asof

src = Path('strategy_lab/markov_filter/_results/post_f7_real_compare_v2/fires_with_gates.csv')
df = pd.read_csv(src)
print(f'Loaded {len(df):,} fires from {src.name}')
print(f'Date range: fire_us min={int(df.fire_us.min())}us  max={int(df.fire_us.max())}us')
print(f'  ({pd.Timestamp(int(df.fire_us.min()), unit="us", tz="UTC")} -> '
      f'{pd.Timestamp(int(df.fire_us.max()), unit="us", tz="UTC")})')
print()

# Build the relevant timestamps
df['fire_s']       = (df.fire_us // 1_000_000).astype('int64')
df['window_s']     = df.tf.map({'5m': 300, '15m': 900})
df['ws_s']         = df.fire_s - 120                # fire = ws_s + 120 in production
df['slot_start_s'] = df.ws_s + df.window_s         # slot_start = ws_s + window_s = slug suffix
df['slot_end_s']   = df.slot_start_s + df.window_s  # next slot's start

# Sanity check anchor distances
print(f'For 5m: fire-ws_s={120}s  slot_start-fire={(df[df.tf=="5m"].slot_start_s - df[df.tf=="5m"].fire_s).iloc[0]}s')
print(f'For 15m: fire-ws_s={120}s  slot_start-fire={(df[df.tf=="15m"].slot_start_s - df[df.tf=="15m"].fire_s).iloc[0]}s')

# Filter to momo family only (F7 only applies there)
df = df[df.family == 'momo'].copy()
print(f'\nAfter momo filter: {len(df):,}')

# Load klines
klines = {}
for a in ['BTC','ETH','SOL']:
    eu, cl = load_klines_asof(a, 'binance-spot-ws', '1MIN')
    klines[a] = (eu.astype('int64'), cl.astype('float64'))
    print(f'  {a} klines: last={pd.Timestamp(int(eu[-1]), unit="us", tz="UTC")}')

# Note: live F7 sleeves fire 2026-05-20 19:57+; our klines end 2026-05-19 23:35
# So most fires will be POST kline data - RSI will be NaN unless we have fresh data
# Check coverage
df['kline_covered'] = False
for a in ['BTC','ETH','SOL']:
    m = df.symbol == a
    last_kline_s = int(klines[a][0][-1]) // 1_000_000
    df.loc[m, 'kline_covered'] = df.loc[m, 'fire_s'] <= last_kline_s
print(f'\nFires within kline coverage: {df.kline_covered.sum():,} / {len(df):,}')

if df.kline_covered.sum() == 0:
    print('NO KLINE COVERAGE - klines too stale. Need fresh canonical pull.')
    sys.exit(0)

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

# Compute RSI at each candidate anchor
print('\nComputing RSI at 4 candidate anchors for kline-covered fires...')
for col, ts_col in [('rsi_fire','fire_s'), ('rsi_ws_s','ws_s'),
                     ('rsi_slot_start','slot_start_s'), ('rsi_slot_end','slot_end_s')]:
    df[col] = np.nan
    for a in ['BTC','ETH','SOL']:
        m = (df.symbol == a) & df.kline_covered
        if not m.any(): continue
        eu, cl = klines[a]
        ts_arr = df.loc[m, ts_col].values
        df.loc[m, col] = [rsi_at(eu, cl, int(t) * 1_000_000) for t in ts_arr]

# F7 keep predicate
def f7_keep(sig, rsi):
    if not (rsi == rsi): return None  # NaN -> drop
    if sig == 'UP' and rsi <= 50: return False
    if sig == 'DOWN' and rsi >= 50: return False
    return True

# Apply F7 at each anchor
for col in ['rsi_fire', 'rsi_ws_s', 'rsi_slot_start', 'rsi_slot_end']:
    df[f'keep_{col}'] = [f7_keep(s, r) for s, r in zip(df.signal, df[col])]

# Filter to rows where we computed all 4 RSIs AND live decision exists
df_match = df[df.kline_covered & df.is_f7.notna()].copy()
print(f'\nRows with both live is_f7 AND all 4 RSI candidates: {len(df_match):,}')

if len(df_match) == 0:
    print('\nNo overlap between live F7 fires and kline coverage.')
    print('The F7 sleeves were deployed AFTER our kline snapshot. Need fresh canonical pull.')
    sys.exit(0)

# Compare each anchor's keep decision to live is_f7
print()
print('=' * 90)
print('LIVE is_f7 vs RECOMPUTED keep at each anchor')
print('=' * 90)
print(f'  {"anchor":<18}  {"match":>8}  {"total":>8}  {"acc%":>7}  {"agree-T":>9}  {"agree-F":>9}')
live = df_match.is_f7.astype(bool).values
for anchor in ['rsi_fire', 'rsi_ws_s', 'rsi_slot_start', 'rsi_slot_end']:
    candidate = df_match[f'keep_{anchor}'].values
    mask_both = np.array([(c is not None) for c in candidate])
    c_bool = np.array([bool(c) if c is not None else False for c in candidate])
    matches = (c_bool == live) & mask_both
    n_both = mask_both.sum()
    n_match = matches.sum()
    agree_t = (matches & live).sum()
    agree_f = (matches & ~live).sum()
    print(f'  {anchor:<18}  {int(n_match):>8}  {int(n_both):>8}  {100*n_match/max(n_both,1):>6.2f}%  '
          f'{int(agree_t):>9}  {int(agree_f):>9}')

print()
print('Sample mismatches (first 6) for rsi_ws_s vs live:')
mismatch = df_match[df_match.is_f7.astype(bool) != (df_match.keep_rsi_ws_s == True)].head(6)
cols = ['symbol','tf','signal','is_f7','rsi_fire','rsi_ws_s','rsi_slot_start','rsi_slot_end']
print(mismatch[cols].to_string(index=False))
