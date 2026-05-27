"""V8 BTC 15m panel build.

Starts from V7 panel (218 cols, 97 gates). Adds new V8 gates:
- Path K: 4 TOD buckets (asia_morning, european_morning, us_afternoon, us_evening)
- Path L: 1h grandparent regime gate (from binance 1m klines resampled)
- Path J: 2-asset confluence — BTC + ETH + SOL trend slope (from regime_v2 panel)
- Path P: liquidity shock — microprice depth-shock (mp_skew_change_500ms extreme)
- Pre-window pre-fire flow (using ret_2m_at_ws which is already in V7 panel)

Output: data/v4/canonical/_results/sniper_btc15m_v8_gated.parquet
"""
import os, sys, time
import numpy as np
import pandas as pd

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
sys.path.insert(0, f"{ROOT}/data/v4/canonical")
from load import load_klines

RES = f"{ROOT}/data/v4/canonical/_results"
IN_V7 = f"{RES}/sniper_btc15m_v7_gated.parquet"
OUT = f"{RES}/sniper_btc15m_v8_gated.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading v7 panel")
df = pd.read_parquet(IN_V7)
log(f"  rows: {len(df)}, cols: {len(df.columns)}")

# Ensure fire_us is canonical us int
df['fire_us'] = df.fire_us.astype('int64')

# ====================== Path K: TOD buckets ======================
log("Path K: TOD buckets")
fire_hour = pd.to_datetime(df.fire_us, unit='us', utc=True).dt.hour
df['fire_hour_utc'] = fire_hour.values
df['g_tod_asia_morning']      = ((fire_hour >= 0) & (fire_hour <= 6)).astype('int8').values
df['g_tod_european_morning']  = ((fire_hour >= 7) & (fire_hour <= 12)).astype('int8').values
df['g_tod_us_afternoon']      = ((fire_hour >= 13) & (fire_hour <= 18)).astype('int8').values
df['g_tod_us_evening']        = ((fire_hour >= 19) & (fire_hour <= 23)).astype('int8').values

# ====================== Path L: 1h grandparent regime ======================
log("Path L: build 1h grandparent regime from 1m klines")
k1 = load_klines("BTC", source="binance-spot-ws", period_id="1MIN")
k1 = k1[['time_period_start_us','time_period_end_us','price_open','price_high','price_low','price_close','volume_traded']].copy()
k1['ts'] = pd.to_datetime(k1.time_period_start_us, unit='us', utc=True)
k1 = k1.set_index('ts').sort_index()

# resample 1h OHLC
k1h = k1.resample('1H', label='right', closed='right').agg({
    'price_open':'first','price_high':'max','price_low':'min','price_close':'last','volume_traded':'sum',
    'time_period_end_us':'last'
}).dropna()
log(f"  1h bars: {len(k1h)}")

# ATR(14) for 1h
high = k1h.price_high.values
low = k1h.price_low.values
close = k1h.price_close.values
prev_close = np.roll(close, 1); prev_close[0] = close[0]
tr = np.maximum.reduce([high-low, np.abs(high-prev_close), np.abs(low-prev_close)])
atr_1h = pd.Series(tr).rolling(14, min_periods=14).mean().values
k1h['atr_14'] = atr_1h

# 30m slope (close diff over 2 1h bars / 2)
k1h['slope_3h'] = (k1h.price_close - k1h.price_close.shift(3)) / 3.0   # ~3h slope
k1h['slope_1h'] = (k1h.price_close - k1h.price_close.shift(1))

# trend label
sl3 = k1h.slope_3h.values
atr_vals = k1h.atr_14.values
labels = np.where(sl3 > 0.3*atr_vals, 'trending_up',
          np.where(sl3 < -0.3*atr_vals, 'trending_dn', 'ranging'))
k1h['regime_label_1h'] = labels
k1h['bar_end_us'] = k1h.time_period_end_us.astype('int64')

# Build asof index for fire_us
k1h_sorted = k1h.dropna(subset=['atr_14']).reset_index().rename(columns={'ts':'bar_close_ts'})
k1h_sorted['key_us'] = k1h_sorted.bar_end_us
k1h_sorted = k1h_sorted[['key_us','regime_label_1h','slope_3h','slope_1h','atr_14']].sort_values('key_us').reset_index(drop=True)
log(f"  k1h_sorted: {len(k1h_sorted)} bars")

# asof_strict: causal lookup of 1h bar that ENDED at-or-before fire_us - 1us
fire_us = df.fire_us.values
target = fire_us - 1
keys = k1h_sorted.key_us.values
idx = np.searchsorted(keys, target, side='right') - 1
idx = np.clip(idx, 0, len(keys)-1)
df['regime_1h'] = k1h_sorted.regime_label_1h.values[idx]
df['slope_3h_1h'] = k1h_sorted.slope_3h.values[idx]
df['slope_1h_1h'] = k1h_sorted.slope_1h.values[idx]
df['atr_1h'] = k1h_sorted.atr_14.values[idx]

# also handle: where idx<0 (before first bar), set NaN
mask_invalid = (np.searchsorted(keys, target, side='right') - 1) < 0
df.loc[mask_invalid, 'regime_1h'] = None
df.loc[mask_invalid, 'slope_3h_1h'] = np.nan

# 1h grandparent direction gates
df['g_grandparent_1h_trend_with'] = (
    ((df.direction == 'UP') & (df.regime_1h == 'trending_up')) |
    ((df.direction == 'DOWN') & (df.regime_1h == 'trending_dn'))
).astype('int8')

df['g_grandparent_1h_ranging'] = (df.regime_1h == 'ranging').astype('int8')

df['g_grandparent_1h_slope_with'] = (
    ((df.direction == 'UP') & (df.slope_3h_1h > 0)) |
    ((df.direction == 'DOWN') & (df.slope_3h_1h < 0))
).astype('int8')

df['g_grandparent_1h_slope_strong_with'] = (
    ((df.direction == 'UP') & (df.slope_3h_1h > 0.5*df.atr_1h)) |
    ((df.direction == 'DOWN') & (df.slope_3h_1h < -0.5*df.atr_1h))
).astype('int8')

log(f"  regime_1h dist: {df.regime_1h.value_counts().to_dict()}")
log(f"  grandparent_1h_trend_with fire_rate: {df.g_grandparent_1h_trend_with.mean():.3f}")
log(f"  grandparent_1h_ranging fire_rate: {df.g_grandparent_1h_ranging.mean():.3f}")
log(f"  grandparent_1h_slope_with fire_rate: {df.g_grandparent_1h_slope_with.mean():.3f}")

# ====================== Path J: 2-asset confluence (ETH+SOL 5m and 15m regime) ======================
log("Path J: 2-asset confluence from regime_v2 panels")
for tf_aux in ["5m","15m"]:
    r2 = pd.read_parquet(f"{RES}/regime_panel_{tf_aux}_v2_fixed.parquet")
    log(f"  regime_v2 {tf_aux}: {len(r2)} rows")
    # Need: per asset, asof(fire_us-1us) → trend_slope_30m or regime_label
    for asset_aux in ["ETH","SOL"]:
        sub = r2[r2.asset == asset_aux].sort_values('ts_us').reset_index(drop=True)
        if 'trend_slope_30m' not in sub.columns:
            log(f"    {asset_aux} {tf_aux} no trend_slope_30m — skip")
            continue
        keys_a = sub.ts_us.values
        target = fire_us - 1
        ix = np.searchsorted(keys_a, target, side='right') - 1
        ix = np.clip(ix, 0, len(keys_a)-1)
        mask_bad = (np.searchsorted(keys_a, target, side='right') - 1) < 0
        slope = sub.trend_slope_30m.values[ix].astype(float)
        regime = sub.regime_label.values[ix] if 'regime_label' in sub.columns else None
        slope[mask_bad] = np.nan
        df[f'{asset_aux.lower()}_{tf_aux}_slope'] = slope
        if regime is not None:
            df[f'{asset_aux.lower()}_{tf_aux}_regime'] = regime
            df.loc[mask_bad, f'{asset_aux.lower()}_{tf_aux}_regime'] = None

# 2-asset confluence gates (BTC's direction + ETH and/or SOL trend alignment)
btc_slope = df['trend_slope_30m'].values if 'trend_slope_30m' in df.columns else None
eth5_slope = df.get('eth_5m_slope', pd.Series([np.nan]*len(df))).values
eth15_slope = df.get('eth_15m_slope', pd.Series([np.nan]*len(df))).values
sol5_slope = df.get('sol_5m_slope', pd.Series([np.nan]*len(df))).values
sol15_slope = df.get('sol_15m_slope', pd.Series([np.nan]*len(df))).values

dir_up = (df.direction == 'UP').values
dir_dn = (df.direction == 'DOWN').values

# All-3 alignment on 5m
ok_all3_up = (btc_slope > 0) & (eth5_slope > 0) & (sol5_slope > 0)
ok_all3_dn = (btc_slope < 0) & (eth5_slope < 0) & (sol5_slope < 0)
df['g_xa_unanimity_5m_with'] = ((dir_up & ok_all3_up) | (dir_dn & ok_all3_dn)).astype('int8')

ok_all3_up_15 = (btc_slope > 0) & (eth15_slope > 0) & (sol15_slope > 0)
ok_all3_dn_15 = (btc_slope < 0) & (eth15_slope < 0) & (sol15_slope < 0)
df['g_xa_unanimity_15m_with'] = ((dir_up & ok_all3_up_15) | (dir_dn & ok_all3_dn_15)).astype('int8')

# 2-asset BTC+ETH (5m)
ok_btc_eth_up = (btc_slope > 0) & (eth5_slope > 0)
ok_btc_eth_dn = (btc_slope < 0) & (eth5_slope < 0)
df['g_btc_eth_confluence_5m_with'] = ((dir_up & ok_btc_eth_up) | (dir_dn & ok_btc_eth_dn)).astype('int8')

# BTC+SOL (5m)
ok_btc_sol_up = (btc_slope > 0) & (sol5_slope > 0)
ok_btc_sol_dn = (btc_slope < 0) & (sol5_slope < 0)
df['g_btc_sol_confluence_5m_with'] = ((dir_up & ok_btc_sol_up) | (dir_dn & ok_btc_sol_dn)).astype('int8')

# 2-asset BTC+ETH (15m)
df['g_btc_eth_confluence_15m_with'] = (
    (dir_up & (btc_slope > 0) & (eth15_slope > 0)) |
    (dir_dn & (btc_slope < 0) & (eth15_slope < 0))
).astype('int8')

# ANY confluence (BTC + at least one other)
ok_any_up = (btc_slope > 0) & ((eth5_slope > 0) | (sol5_slope > 0))
ok_any_dn = (btc_slope < 0) & ((eth5_slope < 0) | (sol5_slope < 0))
df['g_xa_majority_5m_with'] = ((dir_up & ok_any_up) | (dir_dn & ok_any_dn)).astype('int8')

# DIVERGENCE — BTC and ETH disagree (means range, contrarian)
df['g_btc_eth_divergence'] = (
    ((btc_slope > 0) & (eth5_slope < 0)) | ((btc_slope < 0) & (eth5_slope > 0))
).astype('int8')

log(f"  g_xa_unanimity_5m_with fire_rate: {df.g_xa_unanimity_5m_with.mean():.3f}")
log(f"  g_xa_unanimity_15m_with fire_rate: {df.g_xa_unanimity_15m_with.mean():.3f}")
log(f"  g_btc_eth_confluence_5m_with fire_rate: {df.g_btc_eth_confluence_5m_with.mean():.3f}")
log(f"  g_xa_majority_5m_with fire_rate: {df.g_xa_majority_5m_with.mean():.3f}")
log(f"  g_btc_eth_divergence fire_rate: {df.g_btc_eth_divergence.mean():.3f}")

# ====================== Path P: liquidity shock from mp_skew_change_500ms ======================
log("Path P: liquidity shock detection")
if 'mp_skew_change_500ms' in df.columns:
    # mp_skew_change_500ms is microprice skew change in 500ms ending at fire_us
    # large absolute value = liquidity event; AGAINST our direction = adverse, WITH = favorable shock
    mpc = df.mp_skew_change_500ms.fillna(0).values
    abs_mpc = np.abs(mpc)
    df['g_liq_shock_with'] = (
        (abs_mpc > 20) & (
            ((df.direction == 'UP') & (mpc > 20)) |
            ((df.direction == 'DOWN') & (mpc < -20))
        )
    ).astype('int8')
    df['g_liq_shock_against'] = (
        (abs_mpc > 20) & (
            ((df.direction == 'UP') & (mpc < -20)) |
            ((df.direction == 'DOWN') & (mpc > 20))
        )
    ).astype('int8')
    df['g_liq_calm'] = (abs_mpc < 5).astype('int8')
    log(f"  g_liq_shock_with rate: {df.g_liq_shock_with.mean():.3f}")
    log(f"  g_liq_shock_against rate: {df.g_liq_shock_against.mean():.3f}")
    log(f"  g_liq_calm rate: {df.g_liq_calm.mean():.3f}")
else:
    log("  mp_skew_change_500ms not available")

# ====================== Path L extension: TOD + grandparent stack ======================
df['g_us_session_with_grandparent'] = (
    (df.g_tod_us_afternoon == 1) & (df.g_grandparent_1h_trend_with == 1)
).astype('int8')

df['g_european_session_with_grandparent'] = (
    (df.g_tod_european_morning == 1) & (df.g_grandparent_1h_trend_with == 1)
).astype('int8')

# ====================== Save ======================
new_gates = [c for c in df.columns if c.startswith('g_') and c not in pd.read_parquet(IN_V7).columns]
log(f"NEW V8 gates count: {len(new_gates)}")
for g in new_gates:
    fr = df[g].astype(float).mean()
    won_at = df[df[g]==1]['won'].mean() if df[g].sum() > 0 else np.nan
    print(f"  {g:50s}  fire_rate={fr:.3f}  sum={int(df[g].sum()):5d}  WR_when_on={won_at:.3f}")

log("saving V8 panel")
df.to_parquet(OUT, index=False)
log(f"saved {OUT}  rows={len(df)}  cols={len(df.columns)}")
log("DONE")
