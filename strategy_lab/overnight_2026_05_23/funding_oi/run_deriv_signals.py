#!/usr/bin/env python3
"""
Derivative-side signals backtest:
  - Funding rate extremes (HL perp)
  - Open interest delta (HL perp metrics)
  - Liquidation cascades (HL perp liqs)
  - Perp-spot basis (HL perp vs binance spot)

Universe: tier1_entries (BTC/ETH/SOL, t+120 books)
Fee model: LegacyConfig (2% on profit)
Outcome: chainlink resolutions
Window: Apr 30 -> May 16 2026 (HL data ends 2026-05-16)
"""
from __future__ import annotations
import sys, os, json
sys.path.insert(0, 'data/v4/canonical')
sys.path.insert(0, 'strategy_lab')

import numpy as np
import pandas as pd
import load

OUT_DIR = 'strategy_lab/overnight_2026_05_23/funding_oi'
os.makedirs(OUT_DIR, exist_ok=True)

# ============================================================================
# DATA LOAD
# ============================================================================
print('[load] resolutions...')
res = load.load_resolutions()  # chainlink-resolved
res = res.rename(columns={'ticker': 'asset_upper'})
res['asset'] = res.asset_upper.str.lower()
res['won_up']   = (res.outcome == 'Up').astype(int)
res['won_down'] = (res.outcome == 'Down').astype(int)

# fire universe = tier1 entries (one row per outcome per slug at t+120)
print('[load] tier1 entries...')
te_list = []
for a in ['btc', 'eth', 'sol']:
    df = load.load_tier1_entries(a)
    df['asset_upper'] = a.upper()
    te_list.append(df)
te = pd.concat(te_list, ignore_index=True)
te['fire_us'] = te.target_ts_us  # = slot_start + 120s
te['asset'] = te.asset_upper.str.lower()
print(f'  tier1 rows total: {len(te)}')

# Merge resolutions with tier1
# we keep one row per (slug, outcome side bet)
m = te.merge(
    res[['slug', 'outcome', 'asset_upper', 'timeframe', 'slot_start_us', 'slot_end_us']],
    on=['slug'],
    suffixes=('', '_res'),
    how='inner',
)
# outcome from tier1 (which it's actually market 'side', not winner)
# need actual winner from res
m = m.rename(columns={'outcome': 'side_outcome', 'outcome_res': 'winner', 'asset_upper': 'asset_upper_te', 'asset_upper_res': 'asset_upper'})
# side: 'Up' or 'Down' = which side we bet
# won = side_outcome == winner
m['won'] = (m.side_outcome == m.winner).astype(int)

# window restriction: HL data ends 2026-05-16 07:00 UTC -> use up to 2026-05-15
WINDOW_START_US = pd.Timestamp('2026-04-30 00:00', tz='UTC').value // 1000
WINDOW_END_US   = pd.Timestamp('2026-05-16 07:00', tz='UTC').value // 1000
m = m[(m.fire_us >= WINDOW_START_US) & (m.fire_us <= WINDOW_END_US)].copy()
print(f'  fires in window: {len(m)}')
print(f'  by asset: {m.asset.value_counts().to_dict()}')
print(f'  by tf: {m.timeframe.value_counts().to_dict()}')

# Compute fill_price from ask side of tier1 book (ask_price_0)
# Production buys best ask
m['fill_price'] = m.ask_price_0
m = m[m.fill_price.notna() & (m.fill_price > 0) & (m.fill_price < 0.99)].copy()
print(f'  after fillable filter: {len(m)}')

# legacy pnl: bet $25 notional, won -> qty * (1 - p) * 0.98, lost -> -qty * p
NOTIONAL = 25.0
m['qty'] = NOTIONAL / m['fill_price']
m['pnl'] = np.where(
    m['won'] == 1,
    m['qty'] * (1.0 - m['fill_price']) * 0.98,
    -m['qty'] * m['fill_price'],
)

# ============================================================================
# DERIVATIVE FEATURES
# ============================================================================

# ----- Funding (per asset, per hour) -----
print('[feat] funding...')
funding_assets = {}
for asset_up in ['BTC', 'ETH', 'SOL']:
    f = load.load_hyperliquid_funding(asset_up).copy()
    f['funding_rate'] = pd.to_numeric(f['funding_rate'], errors='coerce')
    f['premium'] = pd.to_numeric(f['premium'], errors='coerce')
    f = f.sort_values('funding_time_us').reset_index(drop=True)
    # trailing 7d zscore (7 * 24 = 168 hourly samples)
    f['fund_mean_7d'] = f['funding_rate'].rolling(168, min_periods=24).mean().shift(1)
    f['fund_std_7d'] = f['funding_rate'].rolling(168, min_periods=24).std().shift(1)
    f['fund_zscore'] = (f['funding_rate'] - f['fund_mean_7d']) / f['fund_std_7d'].replace(0, np.nan)
    # acceleration = funding_rate - lag1
    f['fund_accel'] = f['funding_rate'] - f['funding_rate'].shift(1)
    # 8h change
    f['fund_8h_change'] = f['funding_rate'] - f['funding_rate'].shift(8)
    funding_assets[asset_up] = f

# ----- Metrics OI (5min resolution-ish) -----
print('[feat] OI...')
metrics_assets = {}
for asset_up in ['BTC', 'ETH', 'SOL']:
    mt = load.load_hyperliquid_metrics(asset_up).copy()
    for c in ['open_interest', 'mid_price', 'mark_price', 'day_notional_volume', 'funding_rate_running']:
        mt[c] = pd.to_numeric(mt[c], errors='coerce')
    mt = mt.sort_values('time_exchange_us').reset_index(drop=True)
    # Resample to 5m bins so we have clean lookups
    mt['time_5m'] = (mt['time_exchange_us'] // (5 * 60 * 1_000_000)) * (5 * 60 * 1_000_000)
    mt5 = mt.groupby('time_5m').agg(
        open_interest=('open_interest', 'last'),
        mid_price=('mid_price', 'last'),
        mark_price=('mark_price', 'last'),
        day_notional_volume=('day_notional_volume', 'last'),
        funding_rate_running=('funding_rate_running', 'last'),
    ).reset_index()
    mt5 = mt5.sort_values('time_5m').reset_index(drop=True)
    # OI delta features
    mt5['oi_1h_lag'] = mt5['open_interest'].shift(12)   # 12 * 5m = 1h
    mt5['oi_4h_lag'] = mt5['open_interest'].shift(48)
    mt5['oi_delta_1h'] = mt5['open_interest'] - mt5['oi_1h_lag']
    mt5['oi_delta_4h'] = mt5['open_interest'] - mt5['oi_4h_lag']
    mt5['oi_pct_1h'] = mt5['oi_delta_1h'] / mt5['oi_1h_lag']
    # 24h zscore
    mt5['oi_mean_24h'] = mt5['open_interest'].rolling(288, min_periods=24).mean().shift(1)
    mt5['oi_std_24h']  = mt5['open_interest'].rolling(288, min_periods=24).std().shift(1)
    mt5['oi_zscore_24h'] = (mt5['open_interest'] - mt5['oi_mean_24h']) / mt5['oi_std_24h'].replace(0, np.nan)
    # price 1h change
    mt5['price_1h_lag'] = mt5['mid_price'].shift(12)
    mt5['price_pct_1h'] = (mt5['mid_price'] - mt5['price_1h_lag']) / mt5['price_1h_lag']
    metrics_assets[asset_up] = mt5

# ----- Liquidations bucketed -----
print('[feat] liqs...')
liqs_assets = {}
for asset_up in ['BTC', 'ETH', 'SOL']:
    l = load.load_hyperliquid_liquidations(asset_up).copy()
    # side: 'B' (buy = closing short), 'A' (ask = closing long)? Let's use dir field
    # dir values: 'Open Long', 'Close Long', 'Open Short', 'Close Short'
    # "Close Long" = long got liquidated (forced sell)
    # "Close Short" = short got liquidated (forced buy)
    # Some events show 'Open Long' for the counterparty - skip those
    l['notional_usd'] = pd.to_numeric(l['price'], errors='coerce') * pd.to_numeric(l['size'], errors='coerce')
    l['is_long_liq']  = l['dir'].str.contains('Close Long', case=False, na=False).astype(int)
    l['is_short_liq'] = l['dir'].str.contains('Close Short', case=False, na=False).astype(int)
    l['long_liq_usd']  = l['notional_usd'] * l['is_long_liq']
    l['short_liq_usd'] = l['notional_usd'] * l['is_short_liq']
    l = l[['time_exchange_us', 'long_liq_usd', 'short_liq_usd', 'notional_usd']].dropna()
    l = l.sort_values('time_exchange_us').reset_index(drop=True)
    liqs_assets[asset_up] = l

# ----- Binance spot klines for basis -----
print('[feat] binance spot klines...')
spot_klines = {}
for asset_up in ['BTC', 'ETH', 'SOL']:
    k = load.load_klines(asset_up).copy()
    k = k.sort_values('time_period_start_us').reset_index(drop=True)
    spot_klines[asset_up] = k

# HL klines for perp
print('[feat] HL klines...')
hl_klines = {}
for asset_up in ['BTC', 'ETH', 'SOL']:
    k = load.load_hyperliquid_klines(asset_up).copy()
    k['time_period_start_us'] = k['time_period_start_us'].astype('int64')
    k = k.sort_values('time_period_start_us').reset_index(drop=True)
    hl_klines[asset_up] = k

# ============================================================================
# JOIN FEATURES TO FIRES
# ============================================================================
print('[feat] joining features to fires...')

def asof_lookup(df_ts, fire_us_arr, val_col):
    """For each fire_us, return the last df_ts row val where ts < fire_us."""
    out = np.full(len(fire_us_arr), np.nan)
    if df_ts is None or len(df_ts) == 0:
        return out
    ts = df_ts['_ts'].values
    vals = df_ts[val_col].values
    idx = np.searchsorted(ts, fire_us_arr, side='right') - 1
    valid = (idx >= 0)
    out[valid] = vals[idx[valid]]
    return out

# Per asset feature build
parts = []
for asset_up, asset_lower in [('BTC','btc'),('ETH','eth'),('SOL','sol')]:
    sub = m[m.asset_upper == asset_up].copy()
    if not len(sub):
        continue
    fire_us = sub['fire_us'].values

    # FUNDING
    f = funding_assets[asset_up].copy()
    f['_ts'] = f['funding_time_us'].astype('int64')
    sub['funding_now'] = asof_lookup(f, fire_us, 'funding_rate')
    sub['funding_zscore'] = asof_lookup(f, fire_us, 'fund_zscore')
    sub['funding_accel'] = asof_lookup(f, fire_us, 'fund_accel')
    sub['funding_8h_change'] = asof_lookup(f, fire_us, 'fund_8h_change')

    # METRICS / OI
    mt = metrics_assets[asset_up].copy()
    mt['_ts'] = mt['time_5m']
    sub['oi_now'] = asof_lookup(mt, fire_us, 'open_interest')
    sub['oi_delta_1h'] = asof_lookup(mt, fire_us, 'oi_delta_1h')
    sub['oi_delta_4h'] = asof_lookup(mt, fire_us, 'oi_delta_4h')
    sub['oi_pct_1h'] = asof_lookup(mt, fire_us, 'oi_pct_1h')
    sub['oi_zscore_24h'] = asof_lookup(mt, fire_us, 'oi_zscore_24h')
    sub['price_pct_1h_perp'] = asof_lookup(mt, fire_us, 'price_pct_1h')
    sub['perp_mid'] = asof_lookup(mt, fire_us, 'mid_price')

    # LIQS: bucket totals for last 60s and 300s before fire
    l = liqs_assets[asset_up].copy()
    ts = l['time_exchange_us'].values
    long_arr = l['long_liq_usd'].values
    short_arr = l['short_liq_usd'].values

    liq_long_60 = np.zeros(len(sub))
    liq_short_60 = np.zeros(len(sub))
    liq_long_300 = np.zeros(len(sub))
    liq_short_300 = np.zeros(len(sub))
    liq_long_5to15 = np.zeros(len(sub))
    liq_short_5to15 = np.zeros(len(sub))

    for i, fu in enumerate(fire_us):
        lo60 = fu - 60_000_000
        lo300 = fu - 300_000_000
        lo15m = fu - 900_000_000  # 15m
        # indices in window [lo, fu)
        i_lo60 = np.searchsorted(ts, lo60, side='left')
        i_lo300 = np.searchsorted(ts, lo300, side='left')
        i_lo15m = np.searchsorted(ts, lo15m, side='left')
        i_hi = np.searchsorted(ts, fu, side='left')
        if i_hi > i_lo60:
            liq_long_60[i]  = long_arr[i_lo60:i_hi].sum()
            liq_short_60[i] = short_arr[i_lo60:i_hi].sum()
        if i_hi > i_lo300:
            liq_long_300[i]  = long_arr[i_lo300:i_hi].sum()
            liq_short_300[i] = short_arr[i_lo300:i_hi].sum()
        # 5-15m back window  [lo15m, lo300)
        if i_lo300 > i_lo15m:
            liq_long_5to15[i]  = long_arr[i_lo15m:i_lo300].sum()
            liq_short_5to15[i] = short_arr[i_lo15m:i_lo300].sum()

    sub['liq_long_60s']   = liq_long_60
    sub['liq_short_60s']  = liq_short_60
    sub['liq_long_300s']  = liq_long_300
    sub['liq_short_300s'] = liq_short_300
    sub['liq_long_5to15m']  = liq_long_5to15
    sub['liq_short_5to15m'] = liq_short_5to15
    total_60s = sub['liq_long_60s'] + sub['liq_short_60s']
    sub['liq_imbalance_60s'] = np.where(total_60s > 0, (sub['liq_short_60s'] - sub['liq_long_60s']) / total_60s, 0.0)

    # PERP-SPOT BASIS
    sk = spot_klines[asset_up].copy()
    sk['_ts'] = sk['time_period_end_us'].astype('int64')
    sub['spot_close'] = asof_lookup(sk, fire_us, 'price_close')
    hk = hl_klines[asset_up].copy()
    hk['_ts'] = hk['time_period_end_us'].astype('int64')
    sub['perp_close'] = asof_lookup(hk, fire_us, 'price_close')
    sub['basis_bps'] = (sub['perp_close'] - sub['spot_close']) / sub['spot_close'] * 10000.0
    # basis change 60s
    fire_us_60 = fire_us - 60_000_000
    spot_60 = np.full(len(sub), np.nan)
    perp_60 = np.full(len(sub), np.nan)
    ts_sk = sk['_ts'].values
    cs_sk = sk['price_close'].values
    idx_sk = np.searchsorted(ts_sk, fire_us_60, side='right') - 1
    v = idx_sk >= 0
    spot_60[v] = cs_sk[idx_sk[v]]
    ts_hk = hk['_ts'].values
    cs_hk = hk['price_close'].values
    idx_hk = np.searchsorted(ts_hk, fire_us_60, side='right') - 1
    v = idx_hk >= 0
    perp_60[v] = cs_hk[idx_hk[v]]
    sub['basis_bps_60s_lag'] = (perp_60 - spot_60) / spot_60 * 10000.0
    sub['basis_change_60s']  = sub['basis_bps'] - sub['basis_bps_60s_lag']

    parts.append(sub)

big = pd.concat(parts, ignore_index=True)
print(f'big: {len(big)} rows')

# Drop rows missing core features
core_feat = ['funding_now', 'funding_zscore', 'oi_delta_1h', 'basis_bps']
before = len(big)
big = big.dropna(subset=core_feat).copy()
print(f'after dropna({core_feat}): {len(big)} (dropped {before-len(big)})')

# Save with features
big.to_parquet(f'{OUT_DIR}/fires_with_deriv_features.parquet', index=False)
print(f'saved {OUT_DIR}/fires_with_deriv_features.parquet')

# ============================================================================
# DISTRIBUTIONS
# ============================================================================
print('\n=== FEATURE DISTRIBUTIONS ===')
for c in ['funding_now','funding_zscore','funding_accel','oi_pct_1h','oi_zscore_24h',
          'liq_long_60s','liq_short_60s','liq_imbalance_60s','basis_bps','basis_change_60s']:
    if c in big.columns:
        s = big[c]
        print(f'  {c}: n={s.notna().sum()} mean={s.mean():.5f} std={s.std():.5f} p10={s.quantile(0.1):.5f} p90={s.quantile(0.9):.5f}')

# ============================================================================
# RULE EVALUATION HELPER
# ============================================================================
def evaluate_rule(df, mask_fire, bet_direction, rule_name):
    """
    df: dataframe
    mask_fire: boolean mask of which rows fire
    bet_direction: 'Up', 'Down', 'side_outcome' (already correct from tier1 row),
                   or callable -> series of 'Up'/'Down'
    """
    sub = df[mask_fire].copy()
    if len(sub) == 0:
        return None
    # determine bet side
    if callable(bet_direction):
        sub['_bet'] = bet_direction(sub)
    elif bet_direction in ('Up','Down'):
        sub['_bet'] = bet_direction
    elif bet_direction == 'side_outcome':
        sub['_bet'] = sub.side_outcome
    else:
        raise ValueError
    # keep only rows where side_outcome == _bet (since tier1 has both legs duplicated)
    sub = sub[sub.side_outcome == sub._bet].copy()
    if len(sub) == 0:
        return None
    wr = sub.won.mean()
    avg_pnl = sub.pnl.mean()
    sum_pnl = sub.pnl.sum()
    avg_p = sub.fill_price.mean()
    return {
        'rule': rule_name,
        'n': len(sub),
        'wr': wr,
        'avg_pnl': avg_pnl,
        'sum_pnl': sum_pnl,
        'avg_price': avg_p,
    }

results = []

# ============================================================================
# TASK 2: FUNDING RULES
# ============================================================================
print('\n=== FUNDING RULES ===')

# F-A: bet DOWN when funding_zscore > +1.5
mask = (big['funding_zscore'] > 1.5)
r = evaluate_rule(big, mask, 'Down', 'F-A: bet DOWN | funding_z > +1.5'); results.append(r) if r else None
mask = (big['funding_zscore'] > 2.0)
r = evaluate_rule(big, mask, 'Down', 'F-A2: bet DOWN | funding_z > +2.0'); results.append(r) if r else None
# F-B: bet UP when funding_zscore < -1.5
mask = (big['funding_zscore'] < -1.5)
r = evaluate_rule(big, mask, 'Up', 'F-B: bet UP | funding_z < -1.5'); results.append(r) if r else None
mask = (big['funding_zscore'] < -2.0)
r = evaluate_rule(big, mask, 'Up', 'F-B2: bet UP | funding_z < -2.0'); results.append(r) if r else None
# F-C: bet WITH funding_accel sign
mask_up = (big['funding_accel'] > 0)
r = evaluate_rule(big, mask_up, 'Up', 'F-C: bet UP | funding_accel > 0'); results.append(r) if r else None
mask_dn = (big['funding_accel'] < 0)
r = evaluate_rule(big, mask_dn, 'Down', 'F-C: bet DOWN | funding_accel < 0'); results.append(r) if r else None
# Sign of funding now
r = evaluate_rule(big, (big['funding_now'] > 0), 'Down', 'F-D: bet DOWN | funding>0 (longs paying)'); results.append(r) if r else None
r = evaluate_rule(big, (big['funding_now'] < 0), 'Up',   'F-D: bet UP | funding<0 (shorts paying)'); results.append(r) if r else None
# WITH funding sign
r = evaluate_rule(big, (big['funding_now'] > 0), 'Up',   'F-E: bet UP | funding>0 (with)'); results.append(r) if r else None
r = evaluate_rule(big, (big['funding_now'] < 0), 'Down', 'F-E: bet DOWN | funding<0 (with)'); results.append(r) if r else None

# ============================================================================
# TASK 3: OI RULES
# ============================================================================
print('\n=== OI RULES ===')
# OI-A: bet WITH 1h price direction when OI is RISING
mask = (big['oi_delta_1h'] > 0) & (big['price_pct_1h_perp'] > 0)
r = evaluate_rule(big, mask, 'Up', 'OI-A: bet UP | OI rising & price up'); results.append(r) if r else None
mask = (big['oi_delta_1h'] > 0) & (big['price_pct_1h_perp'] < 0)
r = evaluate_rule(big, mask, 'Down', 'OI-A: bet DOWN | OI rising & price down'); results.append(r) if r else None
# OI-B: bet AGAINST price direction when OI is FALLING
mask = (big['oi_delta_1h'] < 0) & (big['price_pct_1h_perp'] > 0)
r = evaluate_rule(big, mask, 'Down', 'OI-B: bet DOWN | OI falling, price up (covering)'); results.append(r) if r else None
mask = (big['oi_delta_1h'] < 0) & (big['price_pct_1h_perp'] < 0)
r = evaluate_rule(big, mask, 'Up', 'OI-B: bet UP | OI falling, price down (covering)'); results.append(r) if r else None
# OI-C: bet UP when OI just spiked AND price at recent low
mask = (big['oi_zscore_24h'] > 1.5) & (big['price_pct_1h_perp'] < -0.005)
r = evaluate_rule(big, mask, 'Up', 'OI-C: bet UP | OI z>1.5 & price -0.5% 1h'); results.append(r) if r else None
mask = (big['oi_zscore_24h'] > 1.5) & (big['price_pct_1h_perp'] > 0.005)
r = evaluate_rule(big, mask, 'Down', 'OI-C: bet DOWN | OI z>1.5 & price +0.5% 1h'); results.append(r) if r else None
# OI extreme percentile
mask = (big['oi_pct_1h'] > 0.005)  # > 0.5% growth in 1h
r = evaluate_rule(big, mask, 'side_outcome', 'OI-D: any side | oi_pct_1h > 0.5%')
# already handled by both sides via per-direction split below
mask = (big['oi_pct_1h'] > 0.005)
r = evaluate_rule(big, mask, lambda d: np.where(d.price_pct_1h_perp > 0, 'Up','Down'), 'OI-D: bet WITH price | oi_pct_1h > 0.5%'); results.append(r) if r else None

# ============================================================================
# TASK 4: LIQ RULES
# ============================================================================
print('\n=== LIQ RULES ===')
# L-A: bet UP when liq_short_60s > $X  (short squeeze)
for thr in [50_000, 100_000, 250_000, 500_000, 1_000_000]:
    mask = (big['liq_short_60s'] > thr)
    r = evaluate_rule(big, mask, 'Up', f'L-A: bet UP | liq_short_60s > ${thr/1000:.0f}k'); results.append(r) if r else None
# L-B: bet DOWN when liq_long_60s > $X
for thr in [50_000, 100_000, 250_000, 500_000, 1_000_000]:
    mask = (big['liq_long_60s'] > thr)
    r = evaluate_rule(big, mask, 'Down', f'L-B: bet DOWN | liq_long_60s > ${thr/1000:.0f}k'); results.append(r) if r else None
# L-C: bet WITH imbalance sign
mask = (big['liq_imbalance_60s'] > 0.5)
r = evaluate_rule(big, mask, 'Up', 'L-C: bet UP | liq_imbalance_60s > +0.5'); results.append(r) if r else None
mask = (big['liq_imbalance_60s'] < -0.5)
r = evaluate_rule(big, mask, 'Down', 'L-C: bet DOWN | liq_imbalance_60s < -0.5'); results.append(r) if r else None
# L-D: mean revert after cascade (using 5-15m window)
mask = (big['liq_short_5to15m'] > 100_000) & (big['liq_short_60s'] < 50_000)
r = evaluate_rule(big, mask, 'Down', 'L-D: bet DOWN | short_cascade 5-15m back, none now'); results.append(r) if r else None
mask = (big['liq_long_5to15m'] > 100_000) & (big['liq_long_60s'] < 50_000)
r = evaluate_rule(big, mask, 'Up', 'L-D: bet UP | long_cascade 5-15m back, none now'); results.append(r) if r else None

# ============================================================================
# TASK 5: BASIS RULES
# ============================================================================
print('\n=== BASIS RULES ===')
# B-A: bet WITH basis sign when |basis| > 5bps
mask = (big['basis_bps'] > 5)
r = evaluate_rule(big, mask, 'Up', 'B-A: bet UP | basis > +5bps'); results.append(r) if r else None
mask = (big['basis_bps'] < -5)
r = evaluate_rule(big, mask, 'Down', 'B-A: bet DOWN | basis < -5bps'); results.append(r) if r else None
mask = (big['basis_bps'] > 10)
r = evaluate_rule(big, mask, 'Up', 'B-A2: bet UP | basis > +10bps'); results.append(r) if r else None
mask = (big['basis_bps'] < -10)
r = evaluate_rule(big, mask, 'Down', 'B-A2: bet DOWN | basis < -10bps'); results.append(r) if r else None
# B-B: bet AGAINST when |basis| > 30bps
mask = (big['basis_bps'] > 30)
r = evaluate_rule(big, mask, 'Down', 'B-B: bet DOWN | basis > +30bps (mean rev)'); results.append(r) if r else None
mask = (big['basis_bps'] < -30)
r = evaluate_rule(big, mask, 'Up', 'B-B: bet UP | basis < -30bps (mean rev)'); results.append(r) if r else None
# B-C: bet WITH basis_change_60s sign
mask = (big['basis_change_60s'] > 1)
r = evaluate_rule(big, mask, 'Up', 'B-C: bet UP | basis_change_60s > +1bps'); results.append(r) if r else None
mask = (big['basis_change_60s'] < -1)
r = evaluate_rule(big, mask, 'Down', 'B-C: bet DOWN | basis_change_60s < -1bps'); results.append(r) if r else None

# ============================================================================
# RESULTS TABLE
# ============================================================================
results = [r for r in results if r is not None]
results_df = pd.DataFrame(results).sort_values('avg_pnl', ascending=False)
print('\n=== ALL RULES (sorted by avg_pnl) ===')
print(results_df.to_string(index=False))
results_df.to_csv(f'{OUT_DIR}/rules_all.csv', index=False)

# ============================================================================
# TASK 6: GATE OVERLAY ON TOP SLEEVES
# ============================================================================
print('\n=== GATE OVERLAY ===')
# Take top 7 by avg_pnl with n>=200, then apply each gate independently
top = results_df[results_df['n'] >= 200].head(7)
print('Top 7 sleeves:')
print(top.to_string(index=False))

# We need the actual fire-level data for the top sleeves
# Reconstruct masks
def rule_to_mask(rule_name, df):
    """Return (mask, bet_direction) for a rule name."""
    rn = rule_name
    if 'F-A: bet DOWN | funding_z > +1.5' in rn: return (df.funding_zscore > 1.5), 'Down'
    if 'F-A2: bet DOWN | funding_z > +2.0' in rn: return (df.funding_zscore > 2.0), 'Down'
    if 'F-B: bet UP | funding_z < -1.5' in rn:   return (df.funding_zscore < -1.5), 'Up'
    if 'F-B2: bet UP | funding_z < -2.0' in rn:  return (df.funding_zscore < -2.0), 'Up'
    if 'F-C: bet UP | funding_accel > 0' in rn:  return (df.funding_accel > 0), 'Up'
    if 'F-C: bet DOWN | funding_accel < 0' in rn: return (df.funding_accel < 0), 'Down'
    if 'F-D: bet DOWN | funding>0' in rn:        return (df.funding_now > 0), 'Down'
    if 'F-D: bet UP | funding<0' in rn:          return (df.funding_now < 0), 'Up'
    if 'F-E: bet UP | funding>0' in rn:          return (df.funding_now > 0), 'Up'
    if 'F-E: bet DOWN | funding<0' in rn:        return (df.funding_now < 0), 'Down'
    if 'OI-A: bet UP | OI rising & price up' in rn:   return ((df.oi_delta_1h > 0) & (df.price_pct_1h_perp > 0)), 'Up'
    if 'OI-A: bet DOWN | OI rising & price down' in rn: return ((df.oi_delta_1h > 0) & (df.price_pct_1h_perp < 0)), 'Down'
    if 'OI-B: bet DOWN | OI falling, price up' in rn:   return ((df.oi_delta_1h < 0) & (df.price_pct_1h_perp > 0)), 'Down'
    if 'OI-B: bet UP | OI falling, price down' in rn:   return ((df.oi_delta_1h < 0) & (df.price_pct_1h_perp < 0)), 'Up'
    if 'OI-C: bet UP | OI z>1.5 & price -0.5% 1h' in rn: return ((df.oi_zscore_24h > 1.5) & (df.price_pct_1h_perp < -0.005)), 'Up'
    if 'OI-C: bet DOWN | OI z>1.5 & price +0.5% 1h' in rn: return ((df.oi_zscore_24h > 1.5) & (df.price_pct_1h_perp > 0.005)), 'Down'
    if 'L-A: bet UP | liq_short_60s > $50k' in rn:  return (df.liq_short_60s > 50000), 'Up'
    if 'L-A: bet UP | liq_short_60s > $100k' in rn: return (df.liq_short_60s > 100000), 'Up'
    if 'L-A: bet UP | liq_short_60s > $250k' in rn: return (df.liq_short_60s > 250000), 'Up'
    if 'L-A: bet UP | liq_short_60s > $500k' in rn: return (df.liq_short_60s > 500000), 'Up'
    if 'L-A: bet UP | liq_short_60s > $1000k' in rn: return (df.liq_short_60s > 1000000), 'Up'
    if 'L-B: bet DOWN | liq_long_60s > $50k' in rn: return (df.liq_long_60s > 50000), 'Down'
    if 'L-B: bet DOWN | liq_long_60s > $100k' in rn: return (df.liq_long_60s > 100000), 'Down'
    if 'L-B: bet DOWN | liq_long_60s > $250k' in rn: return (df.liq_long_60s > 250000), 'Down'
    if 'L-B: bet DOWN | liq_long_60s > $500k' in rn: return (df.liq_long_60s > 500000), 'Down'
    if 'L-B: bet DOWN | liq_long_60s > $1000k' in rn: return (df.liq_long_60s > 1000000), 'Down'
    if 'L-C: bet UP | liq_imbalance_60s > +0.5' in rn: return (df.liq_imbalance_60s > 0.5), 'Up'
    if 'L-C: bet DOWN | liq_imbalance_60s < -0.5' in rn: return (df.liq_imbalance_60s < -0.5), 'Down'
    if 'L-D: bet DOWN | short_cascade 5-15m' in rn: return ((df.liq_short_5to15m > 100000) & (df.liq_short_60s < 50000)), 'Down'
    if 'L-D: bet UP | long_cascade 5-15m' in rn:    return ((df.liq_long_5to15m > 100000) & (df.liq_long_60s < 50000)), 'Up'
    if 'B-A: bet UP | basis > +5bps' in rn:  return (df.basis_bps > 5), 'Up'
    if 'B-A: bet DOWN | basis < -5bps' in rn: return (df.basis_bps < -5), 'Down'
    if 'B-A2: bet UP | basis > +10bps' in rn: return (df.basis_bps > 10), 'Up'
    if 'B-A2: bet DOWN | basis < -10bps' in rn: return (df.basis_bps < -10), 'Down'
    if 'B-B: bet DOWN | basis > +30bps' in rn: return (df.basis_bps > 30), 'Down'
    if 'B-B: bet UP | basis < -30bps' in rn:  return (df.basis_bps < -30), 'Up'
    if 'B-C: bet UP | basis_change_60s > +1bps' in rn:   return (df.basis_change_60s > 1), 'Up'
    if 'B-C: bet DOWN | basis_change_60s < -1bps' in rn: return (df.basis_change_60s < -1), 'Down'
    if 'OI-D: bet WITH price | oi_pct_1h > 0.5%' in rn:
        m_ = (df.oi_pct_1h > 0.005)
        b = np.where(df.price_pct_1h_perp > 0, 'Up', 'Down')
        return m_, b
    return None, None

def apply_gate(df, base_mask, base_bet, gate_name):
    """Return df subset where base_mask & gate satisfied for base_bet direction.
    base_bet is either 'Up'/'Down' scalar OR array-like aligned with df.
    """
    is_scalar = isinstance(base_bet, str)
    if gate_name == 'g_funding_extreme_against':
        if is_scalar:
            if base_bet == 'Up':
                return (df['funding_zscore'] < -1.0)
            else:
                return (df['funding_zscore'] > 1.0)
        else:
            bet_arr = np.asarray(base_bet)
            up = bet_arr == 'Up'
            res = np.where(up, df['funding_zscore'].values < -1.0, df['funding_zscore'].values > 1.0)
            return pd.Series(res, index=df.index)
    elif gate_name == 'g_oi_rising_with':
        return (df['oi_delta_1h'] > 0)
    elif gate_name == 'g_recent_liq_cascade_with':
        if is_scalar:
            if base_bet == 'Up':
                return (df['liq_short_60s'] > 50000)
            else:
                return (df['liq_long_60s'] > 50000)
        else:
            bet_arr = np.asarray(base_bet)
            up = bet_arr == 'Up'
            res = np.where(up, df['liq_short_60s'].values > 50000, df['liq_long_60s'].values > 50000)
            return pd.Series(res, index=df.index)
    elif gate_name == 'g_basis_with':
        if is_scalar:
            if base_bet == 'Up':
                return (df['basis_bps'] > 0)
            else:
                return (df['basis_bps'] < 0)
        else:
            bet_arr = np.asarray(base_bet)
            up = bet_arr == 'Up'
            res = np.where(up, df['basis_bps'].values > 0, df['basis_bps'].values < 0)
            return pd.Series(res, index=df.index)
    elif gate_name == 'g_basis_extreme_against':
        if is_scalar:
            if base_bet == 'Up':
                return (df['basis_bps'] < -10)
            else:
                return (df['basis_bps'] > 10)
        else:
            bet_arr = np.asarray(base_bet)
            up = bet_arr == 'Up'
            res = np.where(up, df['basis_bps'].values < -10, df['basis_bps'].values > 10)
            return pd.Series(res, index=df.index)

gate_results = []
for _, top_row in top.iterrows():
    rule_name = top_row['rule']
    mask, bet = rule_to_mask(rule_name, big)
    if mask is None:
        continue
    base_df = big[mask].copy()
    # filter to bet side
    if isinstance(bet, str):
        base_df = base_df[base_df.side_outcome == bet]
        bet_series = bet
    else:
        # array bet
        bet_ser = pd.Series(bet, index=big.index)
        base_df['_bet'] = bet_ser.loc[base_df.index]
        base_df = base_df[base_df.side_outcome == base_df._bet]
        bet_series = base_df._bet.values

    if len(base_df) == 0:
        continue
    # baseline
    gate_results.append({
        'rule': rule_name,
        'gate': 'baseline',
        'n': len(base_df), 'wr': base_df.won.mean(), 'avg_pnl': base_df.pnl.mean(), 'sum_pnl': base_df.pnl.sum(),
    })
    for g_name in ['g_funding_extreme_against','g_oi_rising_with','g_recent_liq_cascade_with','g_basis_with','g_basis_extreme_against']:
        g_mask = apply_gate(base_df, mask.loc[base_df.index], bet_series, g_name)
        if g_mask is None: continue
        if not g_mask.any():
            gate_results.append({'rule': rule_name, 'gate': g_name, 'n': 0, 'wr': np.nan, 'avg_pnl': np.nan, 'sum_pnl': 0.0})
            continue
        sub = base_df[g_mask]
        gate_results.append({
            'rule': rule_name, 'gate': g_name,
            'n': len(sub), 'wr': sub.won.mean(), 'avg_pnl': sub.pnl.mean(), 'sum_pnl': sub.pnl.sum(),
        })

gate_df = pd.DataFrame(gate_results)
print('\nGATE RESULTS:')
print(gate_df.to_string(index=False))
gate_df.to_csv(f'{OUT_DIR}/gate_overlay.csv', index=False)

# ============================================================================
# TASK 7: WALK-FORWARD on top combos (20d/8d nominal -> 12d/4d given window)
# ============================================================================
print('\n=== WALK-FORWARD ===')
# split big by fire_us into in-sample and out-sample
ts_min = big.fire_us.min()
ts_max = big.fire_us.max()
total_d = (ts_max - ts_min) / (1e6 * 86400)
print(f'window: {total_d:.1f} days')
split = ts_min + (ts_max - ts_min) * 12 / 16  # 12d / 4d
big['is_oos'] = big.fire_us > split

# evaluate top 10 rules in-sample, then check OOS
wf_rows = []
for _, row in results_df.head(10).iterrows():
    rule_name = row['rule']
    mask, bet = rule_to_mask(rule_name, big)
    if mask is None: continue
    is_df  = big[mask & ~big.is_oos]
    oos_df = big[mask & big.is_oos]
    if isinstance(bet, str):
        is_df  = is_df[is_df.side_outcome == bet]
        oos_df = oos_df[oos_df.side_outcome == bet]
    else:
        bet_ser = pd.Series(bet, index=big.index)
        is_df  = is_df[is_df.side_outcome == bet_ser.loc[is_df.index]]
        oos_df = oos_df[oos_df.side_outcome == bet_ser.loc[oos_df.index]]
    wf_rows.append({
        'rule': rule_name,
        'is_n': len(is_df), 'is_wr': is_df.won.mean() if len(is_df) else np.nan, 'is_avg_pnl': is_df.pnl.mean() if len(is_df) else np.nan,
        'oos_n': len(oos_df), 'oos_wr': oos_df.won.mean() if len(oos_df) else np.nan, 'oos_avg_pnl': oos_df.pnl.mean() if len(oos_df) else np.nan,
        'oos_pass': (len(oos_df) >= 20) and (oos_df.pnl.mean() > 0) and (is_df.pnl.mean() > 0),
    })
wf_df = pd.DataFrame(wf_rows)
print(wf_df.to_string(index=False))
wf_df.to_csv(f'{OUT_DIR}/walkforward.csv', index=False)

n_oos_pass = int(wf_df.oos_pass.sum())
print(f'\nOOS PASS COUNT: {n_oos_pass}/{len(wf_df)}')

# ============================================================================
# SUMMARY
# ============================================================================
summary = {
    'window_start': pd.Timestamp(ts_min, unit='us', tz='UTC').isoformat(),
    'window_end': pd.Timestamp(ts_max, unit='us', tz='UTC').isoformat(),
    'window_days': total_d,
    'n_fires': len(big),
    'by_asset': big.asset.value_counts().to_dict(),
    'by_timeframe': big.timeframe.value_counts().to_dict(),
    'n_rules_tested': len(results_df),
    'best_rule_avg_pnl': float(results_df.iloc[0].avg_pnl),
    'best_rule_name': results_df.iloc[0]['rule'],
    'best_rule_n': int(results_df.iloc[0].n),
    'best_rule_wr': float(results_df.iloc[0].wr),
    'oos_pass_count': n_oos_pass,
    'wf_total': len(wf_df),
}
with open(f'{OUT_DIR}/summary.json','w') as fh:
    json.dump(summary, fh, indent=2, default=str)

print('\n=== SUMMARY ===')
print(json.dumps(summary, indent=2, default=str))
print(f'\nALL artifacts in {OUT_DIR}/')
