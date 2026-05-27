"""V8 panel build for SOL 5m.

Adds to V7 panel:
  Path J — 2-asset confluence (BTC + ETH trend/slope at fire_us → SOL fire)
  Path K — TOD bucket gates (asia/european_morning/us_afternoon/us_evening)
  Path Q — 5m + 15m confluence (SOL 15m fire near same time agreeing dir)
  Path O — HL liquidation cascade gates (SOL-specific perp signals)

Built on top of V7 panel for full 32.7d v3 fires window.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v8")
t0 = time.time()

# === Load V3 fires (full 32.7d) directly — V7 panel is reduced/joined; we want full window ===
v3 = pd.read_parquet("data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_5m_full_v3.parquet")
print(f"V3 fires: {v3.shape}")
print(f"  date range: {pd.to_datetime(v3.fire_us.min(),unit='us')} -> {pd.to_datetime(v3.fire_us.max(),unit='us')}")

# === Load V7 panel & merge V7 enrichments into V3 fires ===
v7 = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet")
print(f"V7 panel: {v7.shape}")
# Only keep extra v7 cols not in v3
v3_cols = set(v3.columns)
v7_extra = [c for c in v7.columns if c not in v3_cols and c not in ['slug','fire_us','fire_offset_s']]
print(f"V7-extra cols to merge: {len(v7_extra)}")

v8 = v3.merge(v7[['slug','fire_us','fire_offset_s','direction'] + v7_extra],
              on=['slug','fire_us','fire_offset_s','direction'], how='left')
print(f"After merge: {v8.shape}")
assert len(v8) == len(v3), f"Merge created duplicates: {len(v8)} vs {len(v3)}"

# === DERIVE ws_s_int if missing (will be NaN for fires not in V7 panel) ===
if 'ws_s_int' not in v8.columns or v8['ws_s_int'].isna().any():
    v8['ws_s_int'] = (v8['slot_start_us'] // 1_000_000 - 300).astype('int64')
v8['ws_s_int'] = v8['ws_s_int'].astype('int64')

# === PATH J: 2-asset confluence (BTC + ETH → SOL) ===
print("\n=== PATH J: 2-asset confluence ===")
reg5 = pd.read_parquet("data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet")
print(f"regime_panel_5m: {reg5.shape}, date range: {pd.to_datetime(reg5['ts_us'].min(), unit='us')} -> {pd.to_datetime(reg5['ts_us'].max(), unit='us')}")

def asof_lookup(ts_arr, val_arr, query_ts_arr):
    idx = np.searchsorted(ts_arr, query_ts_arr, side='right') - 1
    out = np.full(len(query_ts_arr), np.nan, dtype=np.float64)
    valid = idx >= 0
    out[valid] = val_arr[idx[valid]]
    return out

def asof_label(ts_arr, label_arr, query_ts_arr):
    idx = np.searchsorted(ts_arr, query_ts_arr, side='right') - 1
    out = np.full(len(query_ts_arr), '', dtype=object)
    valid = idx >= 0
    out[valid] = label_arr[idx[valid]]
    return out

for asset in ['BTC', 'ETH']:
    sub = reg5[reg5['asset']==asset].sort_values('ts_s')
    ts = sub['ts_s'].astype('int64').values
    slope = sub['trend_slope_30m'].fillna(0).astype(np.float64).values
    label = sub['regime_label'].values
    score = sub['regime_score'].fillna(0).astype(np.float64).values
    adx = sub['adx_14'].fillna(0).astype(np.float64).values
    v8[f'{asset.lower()}_5m_slope_at_ws'] = asof_lookup(ts, slope, v8['ws_s_int'].values)
    v8[f'{asset.lower()}_5m_regime_at_ws'] = asof_label(ts, label, v8['ws_s_int'].values)
    v8[f'{asset.lower()}_5m_score_at_ws'] = asof_lookup(ts, score, v8['ws_s_int'].values)
    v8[f'{asset.lower()}_5m_adx_at_ws'] = asof_lookup(ts, adx, v8['ws_s_int'].values)
    print(f"  {asset}: slope notna {v8[f'{asset.lower()}_5m_slope_at_ws'].notna().mean()*100:.1f}%")

# SOL slope at ws for confluence checks
sub = reg5[reg5['asset']=='SOL'].sort_values('ts_s')
v8['sol_5m_slope_at_ws_v8'] = asof_lookup(sub['ts_s'].astype('int64').values,
                                          sub['trend_slope_30m'].fillna(0).astype(np.float64).values,
                                          v8['ws_s_int'].values)
v8['sol_5m_regime_at_ws_v8'] = asof_label(sub['ts_s'].astype('int64').values,
                                          sub['regime_label'].values, v8['ws_s_int'].values)

v8['_dir_sign'] = np.where(v8['direction']=='UP', 1, -1)

# 2-asset confluence: BTC + ETH BOTH have slope agreeing with SOL direction
v8['g_2asset_confluence_btc_eth'] = (
    (
        ((v8['_dir_sign']==1) & (v8['btc_5m_slope_at_ws']>0) & (v8['eth_5m_slope_at_ws']>0)) |
        ((v8['_dir_sign']==-1) & (v8['btc_5m_slope_at_ws']<0) & (v8['eth_5m_slope_at_ws']<0))
    )
).fillna(False).astype('int8')

# Strong version: |slope| > 0.0003 on both
v8['g_2asset_confluence_strong'] = (
    (
        ((v8['_dir_sign']==1) & (v8['btc_5m_slope_at_ws']>0.0003) & (v8['eth_5m_slope_at_ws']>0.0003)) |
        ((v8['_dir_sign']==-1) & (v8['btc_5m_slope_at_ws']<-0.0003) & (v8['eth_5m_slope_at_ws']<-0.0003))
    )
).fillna(False).astype('int8')

# 3-asset unanimity (BTC + ETH + SOL all agree)
v8['g_3asset_unanimity'] = (
    (
        ((v8['_dir_sign']==1) & (v8['btc_5m_slope_at_ws']>0) & (v8['eth_5m_slope_at_ws']>0) & (v8['sol_5m_slope_at_ws_v8']>0)) |
        ((v8['_dir_sign']==-1) & (v8['btc_5m_slope_at_ws']<0) & (v8['eth_5m_slope_at_ws']<0) & (v8['sol_5m_slope_at_ws_v8']<0))
    )
).fillna(False).astype('int8')

# 2-asset confluence AGAINST (BTC+ETH both opposite — contrarian)
v8['g_2asset_confluence_against'] = (
    (
        ((v8['_dir_sign']==1) & (v8['btc_5m_slope_at_ws']<0) & (v8['eth_5m_slope_at_ws']<0)) |
        ((v8['_dir_sign']==-1) & (v8['btc_5m_slope_at_ws']>0) & (v8['eth_5m_slope_at_ws']>0))
    )
).fillna(False).astype('int8')

# Regime label confluence: BTC + ETH both trending in same direction
v8['g_2asset_regime_trending_with'] = (
    (
        ((v8['_dir_sign']==1) & (v8['btc_5m_regime_at_ws']=='trending_up') & (v8['eth_5m_regime_at_ws']=='trending_up')) |
        ((v8['_dir_sign']==-1) & (v8['btc_5m_regime_at_ws']=='trending_dn') & (v8['eth_5m_regime_at_ws']=='trending_dn'))
    )
).astype('int8')

# Either trending (less restrictive)
v8['g_2asset_either_trending_with'] = (
    (
        ((v8['_dir_sign']==1) & (
            ((v8['btc_5m_regime_at_ws']=='trending_up') | (v8['eth_5m_regime_at_ws']=='trending_up')) &
            ~((v8['btc_5m_regime_at_ws']=='trending_dn') | (v8['eth_5m_regime_at_ws']=='trending_dn'))
        )) |
        ((v8['_dir_sign']==-1) & (
            ((v8['btc_5m_regime_at_ws']=='trending_dn') | (v8['eth_5m_regime_at_ws']=='trending_dn')) &
            ~((v8['btc_5m_regime_at_ws']=='trending_up') | (v8['eth_5m_regime_at_ws']=='trending_up'))
        ))
    )
).astype('int8')

# Both ranging
v8['g_2asset_both_ranging'] = (
    (v8['btc_5m_regime_at_ws']=='ranging') & (v8['eth_5m_regime_at_ws']=='ranging')
).astype('int8')

for g in ['g_2asset_confluence_btc_eth','g_2asset_confluence_strong','g_3asset_unanimity',
          'g_2asset_confluence_against','g_2asset_regime_trending_with',
          'g_2asset_either_trending_with','g_2asset_both_ranging']:
    print(f"  {g}: pass_rate={v8[g].mean()*100:.2f}%")

# === PATH K: TOD bucket gates ===
print("\n=== PATH K: TOD specialization ===")
v8['_hour_utc'] = pd.to_datetime(v8['fire_us'], unit='us').dt.hour
v8['g_tod_asia'] = (v8['_hour_utc'].between(0, 6)).astype('int8')        # 00-07 UTC
v8['g_tod_european'] = (v8['_hour_utc'].between(7, 12)).astype('int8')   # 07-13 UTC
v8['g_tod_us_afternoon'] = (v8['_hour_utc'].between(13, 18)).astype('int8')   # 13-19 UTC
v8['g_tod_us_evening'] = (v8['_hour_utc'].between(19, 23)).astype('int8')     # 19-24 UTC
# Sub-buckets for finer slicing
v8['g_tod_asia_early'] = (v8['_hour_utc'].between(0, 3)).astype('int8')
v8['g_tod_asia_late'] = (v8['_hour_utc'].between(4, 6)).astype('int8')
v8['g_tod_eu_open'] = (v8['_hour_utc'].between(7, 9)).astype('int8')
v8['g_tod_lunch'] = (v8['_hour_utc'].between(10, 12)).astype('int8')
v8['g_tod_us_open'] = (v8['_hour_utc'].between(13, 15)).astype('int8')
v8['g_tod_us_close'] = (v8['_hour_utc'].between(20, 22)).astype('int8')
# AVOID gates
v8['g_tod_avoid_us_afternoon'] = (~v8['_hour_utc'].between(13, 18)).astype('int8')

for g in ['g_tod_asia','g_tod_european','g_tod_us_afternoon','g_tod_us_evening',
          'g_tod_asia_early','g_tod_asia_late','g_tod_eu_open','g_tod_lunch',
          'g_tod_us_open','g_tod_us_close','g_tod_avoid_us_afternoon']:
    print(f"  {g}: pass_rate={v8[g].mean()*100:.2f}%")

# === PATH Q: 5m + 15m confluence ===
# Per slug-time-asset: is there a 15m SOL fire firing the same direction in the
# 15-minute window that contains this 5m fire?
print("\n=== PATH Q: 5m + 15m confluence ===")
f15 = pd.read_parquet("data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet")
print(f"SOL 15m fires: {len(f15)}")

# Make a lookup: for each 5m fire's slot_start, find the 15m fires whose slot_start
# is within the same 15m window (i.e. (slot_start_5m // 900) == (slot_start_15m // 900)) and direction matches
f15['slot_15m_idx'] = (f15['slot_start_us'] // (900 * 1_000_000)).astype('int64')
f15['dir_sign_15m'] = np.where(f15['direction']=='UP', 1, -1)
# Aggregate per (slot_15m_idx, direction)
f15_agg = f15.groupby(['slot_15m_idx', 'direction']).agg(
    n_15m_fires=('fire_us', 'count'),
    wr_15m_avg=('won', 'mean'),
).reset_index()
print(f"15m agg rows: {len(f15_agg)}")

v8['slot_15m_idx'] = (v8['slot_start_us'] // (900 * 1_000_000)).astype('int64')
v8 = v8.merge(f15_agg, on=['slot_15m_idx','direction'], how='left')
v8['n_15m_fires'] = v8['n_15m_fires'].fillna(0).astype('int32')

v8['g_q_15m_confluence'] = (v8['n_15m_fires'] >= 1).astype('int8')
v8['g_q_15m_dense_confluence'] = (v8['n_15m_fires'] >= 5).astype('int8')
v8['g_q_15m_very_dense'] = (v8['n_15m_fires'] >= 10).astype('int8')
v8['g_q_15m_sparse'] = ((v8['n_15m_fires'] >= 1) & (v8['n_15m_fires'] < 3)).astype('int8')

# Opposite direction: is there a 15m fire in opposite direction (warning gate)
f15_opp = f15.copy()
f15_opp['opp_direction'] = np.where(f15_opp['direction']=='UP', 'DOWN', 'UP')
f15_opp_agg = f15_opp.groupby(['slot_15m_idx', 'opp_direction']).agg(
    n_15m_opposite=('fire_us', 'count')
).reset_index().rename(columns={'opp_direction':'direction'})
v8 = v8.merge(f15_opp_agg, on=['slot_15m_idx','direction'], how='left')
v8['n_15m_opposite'] = v8['n_15m_opposite'].fillna(0).astype('int32')

# Bias ratio: more 15m fires our way than opposite
v8['n_15m_diff'] = (v8['n_15m_fires'] - v8['n_15m_opposite']).astype('int32')
v8['g_q_15m_dir_bias'] = (v8['n_15m_diff'] >= 3).astype('int8')   # at least 3 more in our dir
v8['g_q_15m_dir_strong_bias'] = (v8['n_15m_diff'] >= 7).astype('int8')
# Heavy: ratio our_dir / total > 0.7 with non-trivial total
total_15m = v8['n_15m_fires'] + v8['n_15m_opposite']
v8['g_q_15m_dir_majority'] = ((total_15m >= 5) & (v8['n_15m_fires'] > 0.65 * total_15m)).astype('int8')
v8['g_q_15m_dir_supermajority'] = ((total_15m >= 5) & (v8['n_15m_fires'] > 0.80 * total_15m)).astype('int8')

# 15m WR (in opposing direction) — could be a warning
# Use 15m fire wr_15m_avg as a leading-WR signal (if 15m fires in OUR dir have high WR, 5m fires may too)
v8['wr_15m_our_dir'] = v8['wr_15m_avg'].fillna(0.5)
v8['g_q_15m_high_wr_with'] = (v8['wr_15m_our_dir'] >= 0.65).astype('int8')
v8['g_q_15m_low_wr_with'] = (v8['wr_15m_our_dir'] < 0.40).astype('int8')

for g in ['g_q_15m_confluence','g_q_15m_dense_confluence','g_q_15m_very_dense','g_q_15m_sparse',
          'g_q_15m_dir_bias','g_q_15m_dir_strong_bias','g_q_15m_dir_majority','g_q_15m_dir_supermajority',
          'g_q_15m_high_wr_with','g_q_15m_low_wr_with']:
    print(f"  {g}: pass_rate={v8[g].mean()*100:.2f}%")

# === PATH O: HL liquidation cascade gates (SOL-specific) ===
print("\n=== PATH O: HL liquidation cascade ===")
hl = pd.read_parquet("data/v4/canonical/hyperliquid_liquidations_full.parquet")
hl_sol = hl[hl['coin']=='SOL'].copy()
print(f"HL SOL liq: {len(hl_sol)} rows, date range: {pd.to_datetime(hl_sol['time_exchange_us'].min(),unit='us')} -> {pd.to_datetime(hl_sol['time_exchange_us'].max(),unit='us')}")

# Aggregate per-minute long-liq and short-liq counts + USD notional
# side='A' = SELL = LONG liquidation (long forced to sell), side='B' = BUY = SHORT liquidation
hl_sol['ts_min'] = (hl_sol['time_exchange_us'] // (60 * 1_000_000)).astype('int64')
hl_sol['usd'] = hl_sol['price'] * hl_sol['size']
hl_min = hl_sol.groupby(['ts_min', 'side']).agg(
    n_liq=('time_exchange_us', 'count'),
    usd_liq=('usd', 'sum'),
).reset_index()

# pivot
hl_min_p = hl_min.pivot(index='ts_min', columns='side', values=['n_liq','usd_liq']).fillna(0)
hl_min_p.columns = [f'{a}_{b}' for a,b in hl_min_p.columns]
hl_min_p = hl_min_p.reset_index()
print(f"HL minute aggregation: {len(hl_min_p)} rows; cols: {list(hl_min_p.columns)}")

# For each fire, count liquidations in last 5 min window before fire_us
# Convert to per-fire lookup: sum of n_liq and usd_liq in (fire_us - 5min, fire_us)
hl_min_p = hl_min_p.sort_values('ts_min').reset_index(drop=True)
ts_min_arr = hl_min_p['ts_min'].values  # minute index

# build cumulative arrays for window sums
def windowed_sum(query_min, value_arr, window_min, ts_arr):
    """For each query minute, sum value_arr where ts in (query_min - window_min, query_min]."""
    cum = np.concatenate([[0], np.cumsum(value_arr)])
    # We need to find for each query the start index (ts > query - window) and end (ts <= query)
    end_idx = np.searchsorted(ts_arr, query_min, side='right')  # exclusive end
    start_idx = np.searchsorted(ts_arr, query_min - window_min, side='right')  # exclusive start
    return cum[end_idx] - cum[start_idx]

v8_fire_min = (v8['fire_us'] // (60 * 1_000_000)).astype('int64').values

# Long liquidation = side 'A' (forced sell — bearish)
long_liq_usd_arr = hl_min_p.get('usd_liq_A', pd.Series(np.zeros(len(hl_min_p)))).values
short_liq_usd_arr = hl_min_p.get('usd_liq_B', pd.Series(np.zeros(len(hl_min_p)))).values
long_liq_n_arr = hl_min_p.get('n_liq_A', pd.Series(np.zeros(len(hl_min_p)))).values
short_liq_n_arr = hl_min_p.get('n_liq_B', pd.Series(np.zeros(len(hl_min_p)))).values

v8['hl_long_liq_usd_5m'] = windowed_sum(v8_fire_min, long_liq_usd_arr, 5, ts_min_arr)
v8['hl_short_liq_usd_5m'] = windowed_sum(v8_fire_min, short_liq_usd_arr, 5, ts_min_arr)
v8['hl_long_liq_usd_15m'] = windowed_sum(v8_fire_min, long_liq_usd_arr, 15, ts_min_arr)
v8['hl_short_liq_usd_15m'] = windowed_sum(v8_fire_min, short_liq_usd_arr, 15, ts_min_arr)
v8['hl_long_liq_n_5m'] = windowed_sum(v8_fire_min, long_liq_n_arr, 5, ts_min_arr)
v8['hl_short_liq_n_5m'] = windowed_sum(v8_fire_min, short_liq_n_arr, 5, ts_min_arr)

# Gates — thresholds tuned to actual HL SOL liq size distribution
# Side 'A' total $3M (rare = LONG liq, $364 median); Side 'B' total $3.5B ($921 median = SHORT liq)
# Long liq cascade in last 5m → typically bearish move (price falling); fire SOL DOWN with it
v8['g_hl_long_cascade_with'] = (
    (v8['hl_long_liq_usd_5m'] > 1_000) & (v8['_dir_sign']==-1)
).astype('int8')
# Short liq cascade in last 5m → bullish; fire UP with it
v8['g_hl_short_cascade_with'] = (
    (v8['hl_short_liq_usd_5m'] > 50_000) & (v8['_dir_sign']==1)
).astype('int8')
# Long liq cascade AGAINST direction → mean-revert opportunity (longs flushed, bottom-pick UP)
v8['g_hl_long_cascade_revert'] = (
    (v8['hl_long_liq_usd_5m'] > 1_000) & (v8['_dir_sign']==1)
).astype('int8')
# Short liq cascade AGAINST → revert (shorts flushed, top-pick DOWN)
v8['g_hl_short_cascade_revert'] = (
    (v8['hl_short_liq_usd_5m'] > 50_000) & (v8['_dir_sign']==-1)
).astype('int8')

# 15m versions
v8['g_hl_long_cascade_with_15m'] = (
    (v8['hl_long_liq_usd_15m'] > 2_500) & (v8['_dir_sign']==-1)
).astype('int8')
v8['g_hl_short_cascade_with_15m'] = (
    (v8['hl_short_liq_usd_15m'] > 100_000) & (v8['_dir_sign']==1)
).astype('int8')

# Strong cascade in last 5m
v8['g_hl_short_cascade_strong'] = (
    (v8['hl_short_liq_usd_5m'] > 250_000) & (v8['_dir_sign']==1)
).astype('int8')
v8['g_hl_short_cascade_extreme'] = (
    (v8['hl_short_liq_usd_5m'] > 1_000_000) & (v8['_dir_sign']==1)
).astype('int8')

# Quiet — no liq either side in 5m (rare for short side, common for long)
v8['g_hl_quiet_5m'] = ((v8['hl_short_liq_usd_5m'] < 5_000)).astype('int8')
v8['g_hl_very_quiet_5m'] = ((v8['hl_short_liq_usd_5m'] < 1_000) & (v8['hl_long_liq_usd_5m'] < 100)).astype('int8')

# Asymmetric ratios using actual side distribution
total_5m = v8['hl_long_liq_usd_5m'] + v8['hl_short_liq_usd_5m']
v8['hl_long_pct_5m'] = np.where(total_5m > 0, v8['hl_long_liq_usd_5m'] / total_5m, 0.0)
v8['g_hl_short_dominant'] = ((v8['hl_long_pct_5m'] < 0.05) & (total_5m > 10_000)).astype('int8')
# "Active short liq market" — total > p75
total_5m_p75 = np.nanpercentile(total_5m[total_5m > 0], 75) if (total_5m > 0).any() else 0
v8['g_hl_high_activity'] = (total_5m > total_5m_p75).astype('int8')
v8['g_hl_high_activity_dir_up'] = ((v8['g_hl_high_activity']==1) & (v8['_dir_sign']==1)).astype('int8')
v8['g_hl_high_activity_dir_dn'] = ((v8['g_hl_high_activity']==1) & (v8['_dir_sign']==-1)).astype('int8')

# Coverage check
hl_min_max = hl_min_p['ts_min'].max()
fire_min_max = v8_fire_min.max()
coverage_pct = (v8_fire_min <= hl_min_max).mean() * 100
print(f"  HL coverage: {coverage_pct:.1f}% of fires have HL data (HL ends at {pd.to_datetime(hl_min_max * 60, unit='s')})")

for g in ['g_hl_long_cascade_with','g_hl_short_cascade_with','g_hl_long_cascade_revert','g_hl_short_cascade_revert',
          'g_hl_long_cascade_with_15m','g_hl_short_cascade_with_15m',
          'g_hl_short_cascade_strong','g_hl_short_cascade_extreme',
          'g_hl_quiet_5m','g_hl_very_quiet_5m','g_hl_short_dominant',
          'g_hl_high_activity','g_hl_high_activity_dir_up','g_hl_high_activity_dir_dn']:
    print(f"  {g}: pass_rate={v8[g].mean()*100:.2f}%")

# === Drop helper cols ===
v8 = v8.drop(columns=['_dir_sign', '_hour_utc'])

# === Ensure pnl_legacy_usd exists in v8 ===
print(f"\nKey eval cols: pnl_legacy_usd notna={v8['pnl_legacy_usd'].notna().sum()}, won notna={v8['won'].notna().sum()}")

# Summary of all new V8 gates
new_v8_gates = [c for c in v8.columns if (c.startswith('g_2asset_') or c.startswith('g_3asset_') or
                c.startswith('g_tod_') or c.startswith('g_q_') or c.startswith('g_hl_'))]
print(f"\nV8 NEW gates ({len(new_v8_gates)}):")
for g in new_v8_gates:
    print(f"  {g}: pass_rate={v8[g].mean()*100:.2f}%")

print(f"\nFinal V8 panel: {v8.shape}; total g_* atoms: {sum(1 for c in v8.columns if c.startswith('g_') or c.startswith('mgf_g_'))}")

# Convert all g_ cols to int8
for c in v8.columns:
    if c.startswith('g_') or c.startswith('mgf_g_'):
        try:
            v8[c] = pd.to_numeric(v8[c], errors='coerce').fillna(0).astype('int8')
        except Exception:
            pass

out_path = OUT / "_panel_sol_5m_v8.parquet"
v8.to_parquet(out_path, index=False, compression='zstd')
print(f"\nWrote {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
print(f"Elapsed: {time.time()-t0:.1f}s")
