"""Reverse-engineer the live VPS3 F7 controller's RSI anchor.

Production writes `rsi_14` in poly_updown_signal event payloads at signal time.
Compute RSI(14) at 3 candidate anchors and see which matches the live value:
  - fire_us  = ws_s + 120         (sampled at order placement time)
  - ws_s     = slot_start - window_s   (signal anchor per CLAUDE.md)
  - slot_start = slug_suffix      (the wrong anchor that previous agent used)

Whichever anchor reproduces the live rsi_14 value is what production uses.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, 'data/v4/canonical')
from load import load_klines_asof

events_p = Path('data/v4/canonical/trading_events_30d.parquet')
df = pd.read_parquet(events_p)
print(f'Total events: {len(df):,}')

# Look at poly_updown_signal events (fire-time signal log)
sig = df[df.kind == 'poly_updown_signal'].copy()
print(f'poly_updown_signal events: {len(sig):,}')

# Parse data
sig['parsed'] = sig.data.apply(lambda s: json.loads(s) if isinstance(s, str) else s)
sig['rsi_14_live'] = sig.parsed.apply(lambda d: d.get('rsi_14') if isinstance(d, dict) else None)
sig['symbol'] = sig.parsed.apply(lambda d: d.get('symbol') if isinstance(d, dict) else None)
sig['tf'] = sig.parsed.apply(lambda d: d.get('tf') if isinstance(d, dict) else None)
sig['signal'] = sig.parsed.apply(lambda d: d.get('signal') if isinstance(d, dict) else None)
sig['condition_id'] = sig.parsed.apply(lambda d: d.get('condition_id') if isinstance(d, dict) else None)

# Filter to rows with rsi_14 set
sig = sig[sig.rsi_14_live.notna() & sig.symbol.isin(['BTC','ETH','SOL']) & sig.tf.isin(['5m','15m'])].copy()
print(f'After filter (has rsi_14, BTC/ETH/SOL, 5m/15m): {len(sig):,}')

sig['rsi_14_live'] = pd.to_numeric(sig.rsi_14_live, errors='coerce')
sig['at_ts'] = pd.to_datetime(sig['at'], utc=True, format='mixed', errors='coerce')
print(f'at_ts range: {sig.at_ts.min()} -> {sig.at_ts.max()}')

# at_ts of poly_updown_signal = fire time = when controller decided + logged signal
# fire_us in seconds:
sig['fire_s'] = (sig.at_ts.astype('int64') // 1_000_000_000)

# Per CLAUDE.md, fire_us = ws_s + 120 -> ws_s = fire_s - 120
sig['ws_s_derived'] = sig.fire_s - 120
# window_s for the bet slot
sig['window_s'] = sig.tf.map({'5m': 300, '15m': 900})
# slot_start = ws_s + window_s (= ws_s + 300 for 5m, +900 for 15m)
sig['slot_start_s'] = sig.ws_s_derived + sig.window_s
# slot_end = slot_start + window_s (next slot's start, 2 windows out from ws_s)
sig['slot_end_s'] = sig.slot_start_s + sig.window_s

# Load klines
klines = {}
for a in ['BTC','ETH','SOL']:
    eu, cl = load_klines_asof(a, 'binance-spot-ws', '1MIN')
    klines[a] = (eu.astype('int64'), cl.astype('float64'))
    print(f'  {a} klines: last={pd.Timestamp(int(eu[-1]), unit="us", tz="UTC")}')

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

# Compute RSI at 4 candidate anchors for the same fires
print('\nComputing RSI at 4 candidate anchors...')
for col_name, ts_col in [('rsi_at_fire',       'fire_s'),
                          ('rsi_at_ws_s',      'ws_s_derived'),
                          ('rsi_at_slot_start','slot_start_s'),
                          ('rsi_at_slot_end',  'slot_end_s')]:
    sig[col_name] = np.nan
    for a in ['BTC','ETH','SOL']:
        m = sig.symbol == a
        if not m.any(): continue
        eu, cl = klines[a]
        ts = sig.loc[m, ts_col].values.astype('int64')
        sig.loc[m, col_name] = [rsi_at(eu, cl, t * 1_000_000) for t in ts]

# Compare each candidate to the live rsi_14
print()
print('=' * 90)
print('LIVE rsi_14 vs RECOMPUTED rsi_14 at each candidate anchor')
print('=' * 90)
for col in ['rsi_at_fire', 'rsi_at_ws_s', 'rsi_at_slot_start', 'rsi_at_slot_end']:
    diff = (sig[col] - sig.rsi_14_live).abs()
    n_match_001 = int((diff <= 0.01).sum())
    n_match_01  = int((diff <= 0.1).sum())
    n_match_1   = int((diff <= 1.0).sum())
    n_total = int(diff.notna().sum())
    median_diff = float(diff.median())
    print(f'{col:<22}  n_compared={n_total:>6}  median|Δ|={median_diff:>6.3f}  '
          f'match≤0.01: {n_match_001:>5} ({100*n_match_001/max(n_total,1):>5.1f}%)  '
          f'≤0.1: {n_match_01:>5} ({100*n_match_01/max(n_total,1):>5.1f}%)  '
          f'≤1.0: {n_match_1:>5} ({100*n_match_1/max(n_total,1):>5.1f}%)')

# Show some sample rows
print()
print('Sample rows (first 8 with all 4 RSI candidates computed):')
samples = sig.dropna(subset=['rsi_14_live','rsi_at_fire','rsi_at_ws_s','rsi_at_slot_start','rsi_at_slot_end']).head(8)
cols_to_show = ['symbol','tf','signal','rsi_14_live','rsi_at_fire','rsi_at_ws_s','rsi_at_slot_start','rsi_at_slot_end']
print(samples[cols_to_show].to_string(index=False))

# Save outputs
out = Path('data/v4/canonical/_results/_f7_live_rsi_compare.csv')
sig[['at_ts','symbol','tf','signal','rsi_14_live','rsi_at_fire','rsi_at_ws_s','rsi_at_slot_start','rsi_at_slot_end','fire_s','ws_s_derived','slot_start_s','slot_end_s']].to_csv(out, index=False)
print(f'\nSaved: {out}')
