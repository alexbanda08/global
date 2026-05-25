"""Reverse-engineer the live F7 controller's RSI anchor — VERSION-AWARE.

Production code (build_bar_context_t_plus_120/60 in poly_updown_loop.py) samples
RSI from 15 closes at offsets [-840, -780, ..., -60, 0] relative to ws_s.
The LAST close is at ws_s, so the RSI anchor IS ws_s.

v1 fires at ws_s + 120s, so ws_s = fire_s - 120.
v2 fires at ws_s + 60s, so ws_s = fire_s - 60.

Previous verifier subtracted 120 from BOTH versions — wrong for v2.
This version derives ws_s correctly per sleeve_id version.
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

# Filter to momo family only
df = df[df.family == 'momo'].copy()
print(f'momo fires: {len(df):,}')
print(f'versions present: {df.version.value_counts().to_dict()}')

df['fire_s']   = (df.fire_us // 1_000_000).astype('int64')
df['window_s'] = df.tf.map({'5m': 300, '15m': 900})

# Version-aware ws_s derivation
df['fire_offset_s'] = df.version.map({'v1': 120, 'v2': 60})
df['ws_s'] = df.fire_s - df.fire_offset_s
df['slot_start_s'] = df.ws_s + df.window_s
df['slot_end_s']   = df.slot_start_s + df.window_s

print(f'\nFire offsets (s) per version: {df.groupby("version").fire_offset_s.first().to_dict()}')

# Load klines
klines = {}
for a in ['BTC','ETH','SOL']:
    eu, cl = load_klines_asof(a, 'binance-spot-ws', '1MIN')
    klines[a] = (eu.astype('int64'), cl.astype('float64'))
    print(f'  {a} klines: last={pd.Timestamp(int(eu[-1]), unit="us", tz="UTC")}')

# Match production's RSI sampling EXACTLY
def rsi_from_offsets(asset, anchor_us):
    """Sample 15 closes at offsets [-840, ..., 0] from anchor, compute Wilder/simple RSI.
    This is EXACTLY what production does in build_bar_context_t_plus_120/60."""
    eu, cl = klines[asset]
    # fetch_close_asof returns close of bar that ENDED at-or-before target_us.
    # Offsets in seconds: -840, -780, ..., -60, 0.
    closes = []
    for off_s in range(-840, 1, 60):
        target_us = anchor_us + off_s * 1_000_000
        idx = int(np.searchsorted(eu, target_us, side='right')) - 1
        if idx < 0 or idx >= len(cl):
            closes.append(float('nan'))
            continue
        # No staleness check — production code has none here
        closes.append(float(cl[idx]))
    if any(not np.isfinite(c) for c in closes) or len(closes) < 15:
        return float('nan')
    # compute_rsi_14 logic from production rsi.py:
    log_rets = np.log(np.array(closes[1:]) / np.array(closes[:-1]))
    gains = np.where(log_rets > 0, log_rets, 0.0)
    losses = np.where(log_rets < 0, -log_rets, 0.0)
    avg_up = gains.mean()
    avg_dn = losses.mean()
    if avg_dn == 0:
        return 100.0 if avg_up > 0 else 50.0
    if avg_up == 0:
        return 0.0
    rs = avg_up / avg_dn
    return 100.0 - 100.0 / (1.0 + rs)

# Compute RSI at three CAUSAL anchor candidates
print('\nComputing RSI at candidate anchors (production-matching method)...')
df['rsi_at_ws_s'] = np.nan
df['rsi_at_fire'] = np.nan
df['rsi_at_slot_start'] = np.nan
for a in ['BTC','ETH','SOL']:
    m = df.symbol == a
    if not m.any(): continue
    eu, cl = klines[a]
    # Check coverage
    last_kl_us = int(eu[-1])
    n_covered = (df.loc[m, 'fire_us'] <= last_kl_us).sum()
    print(f'  {a}: {n_covered}/{m.sum()} fires within kline window')
    df.loc[m, 'rsi_at_ws_s']       = df.loc[m].apply(lambda r: rsi_from_offsets(a, int(r.ws_s)*1_000_000), axis=1)
    df.loc[m, 'rsi_at_fire']       = df.loc[m].apply(lambda r: rsi_from_offsets(a, int(r.fire_s)*1_000_000), axis=1)
    df.loc[m, 'rsi_at_slot_start'] = df.loc[m].apply(lambda r: rsi_from_offsets(a, int(r.slot_start_s)*1_000_000), axis=1)

# F7 keep predicate (production basic mode)
def f7_basic(sig, rsi):
    if not (rsi == rsi): return None
    if sig == 'UP'   and rsi <= 50: return False
    if sig == 'DOWN' and rsi >= 50: return False
    return True

for col in ['rsi_at_ws_s', 'rsi_at_fire', 'rsi_at_slot_start']:
    df[f'keep_{col}'] = [f7_basic(s, r) for s, r in zip(df.signal, df[col])]

# Compare to live is_f7
print()
print('=' * 100)
print('LIVE is_f7 vs RECOMPUTED keep at each anchor (version-aware ws_s)')
print('=' * 100)
print(f'{"anchor":<20} {"match":>8} {"total":>8} {"acc%":>7} {"agree-T":>9} {"agree-F":>9}')

df_match = df[df.is_f7.notna() & df.rsi_at_ws_s.notna()].copy()
print(f'\nfires with both is_f7 AND all RSI candidates computed: {len(df_match):,}')

live = df_match.is_f7.astype(bool).values
for anchor in ['rsi_at_ws_s', 'rsi_at_fire', 'rsi_at_slot_start']:
    keep_col = f'keep_{anchor}'
    candidate = df_match[keep_col].values
    # candidate is None when RSI is NaN — treat None as False (skip)
    c_bool = np.array([bool(c) if c is not None else False for c in candidate])
    matches = (c_bool == live)
    n_match = matches.sum()
    agree_t = (matches & live).sum()
    agree_f = (matches & ~live).sum()
    print(f'{anchor:<20} {int(n_match):>8} {len(df_match):>8} {100*n_match/len(df_match):>6.2f}% '
          f'{int(agree_t):>9} {int(agree_f):>9}')

# Per-version split
print()
print('=== Split by version ===')
for v in ['v1', 'v2']:
    sub = df_match[df_match.version == v]
    print(f'\nversion {v}: n={len(sub):,}')
    for anchor in ['rsi_at_ws_s', 'rsi_at_fire', 'rsi_at_slot_start']:
        keep_col = f'keep_{anchor}'
        candidate = sub[keep_col].values
        c_bool = np.array([bool(c) if c is not None else False for c in candidate])
        live_v = sub.is_f7.astype(bool).values
        matches = (c_bool == live_v)
        n_match = matches.sum()
        print(f'  {anchor:<20} {n_match:>5}/{len(sub):>5} = {100*n_match/max(len(sub),1):>6.2f}%')

# Sample mismatches for the best anchor
print('\n=== Sample mismatches for rsi_at_ws_s (first 6) ===')
mismatch = df_match[(df_match.is_f7.astype(bool)) != (df_match.keep_rsi_at_ws_s == True)].head(6)
cols = ['version','symbol','tf','signal','is_f7','rsi_at_ws_s','rsi_at_fire','rsi_at_slot_start']
print(mismatch[cols].to_string(index=False))
