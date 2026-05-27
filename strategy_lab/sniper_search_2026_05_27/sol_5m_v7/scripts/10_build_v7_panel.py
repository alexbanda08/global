"""V7 panel build for SOL 5m.

Adds to V6 panel:
  1) f7_rsi_at_ws_v7 — rebuilt with FULL coverage from binance 1m klines (SOL)
     (V6 had only 12.3% coverage from mgf join)
  2) f7_rsi_btc_at_ws — Path C cross-asset (BTC microstructure → SOL fire)
  3) hurst variants (g_hurst_strong_trending, g_hurst_reverting, g_hurst_regime_with_dir)
  4) Vol regime specialization gates (g_vol_low_v7, g_vol_high_v7, g_rv_pct_low/med/high)
  5) Parent 15m regime gate (g_parent_15m_with_dir, ranging vs trending)
  6) BTC trend/microstructure lead → SOL gate (g_btc_trend_with, g_btc_micro_lead_with)
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path
from numba import njit

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v7")
t0 = time.time()

# === Load V6 panel as base ===
p = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m_v6/_panel_sol_5m_v6.parquet")
print(f"V6 panel: {p.shape}")
print(f"  date range: {pd.to_datetime(p.fire_us.min(),unit='us')} -> {pd.to_datetime(p.fire_us.max(),unit='us')}")

# === BUILD V7 #1: f7_rsi_at_ws_v7 (full coverage) ===
# Production = simple-mean Wilder RSI(7) on 1m closes, 15 closes back from ws_s.
sys.path.insert(0, "data/v4/canonical")
from load import load_klines

def wilder_rsi_simple(closes, period=7):
    """Production-matching: simple mean of last N gains/losses, length-N=15 series gives RSI at last point."""
    if len(closes) < period + 1:
        return np.nan
    closes = np.asarray(closes, dtype=np.float64)
    diff = np.diff(closes)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    # production fetches 15 closes → 14 diffs → uses last `period` for the simple-mean
    # but actual production runs Wilder smoothing with N=period. Try the simple-mean version (per CLAUDE.md note: "simple-mean Wilder")
    avg_gain = gains[-period:].mean() if len(gains) >= period else gains.mean()
    avg_loss = losses[-period:].mean() if len(losses) >= period else losses.mean()
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def build_f7_rsi_per_asset(asset_code):
    """Returns dict: ts_s -> rsi value (one per minute)."""
    k = load_klines(asset_code, source='binance-spot-ws', period_id='1MIN')
    k = k[['time_period_start_us', 'price_close']].dropna()
    k = k.sort_values('time_period_start_us').drop_duplicates(subset='time_period_start_us').reset_index(drop=True)
    k['ts_s'] = (k['time_period_start_us'] // 1_000_000).astype('int64')
    closes = k['price_close'].astype(np.float64).values
    ts_s = k['ts_s'].values
    # rolling Wilder simple-mean RSI(7)
    rsi_arr = np.full(len(closes), np.nan, dtype=np.float64)
    period = 7
    diffs = np.diff(closes)
    # We need (period + 1) closes for the first valid rsi; that's at index `period`.
    # The RSI value at index i applies to the close at index i (close at ts_s[i]).
    # Last 7 gains/losses ending at idx i are diffs[i-period:i] (period values).
    for i in range(period, len(closes)):
        g = diffs[i-period:i]
        gains = np.where(g > 0, g, 0.0).mean()
        losses = np.where(g < 0, -g, 0.0).mean()
        if losses == 0:
            rsi_arr[i] = 100.0 if gains > 0 else 50.0
        else:
            rs = gains / losses
            rsi_arr[i] = 100.0 - 100.0 / (1.0 + rs)
    return ts_s, rsi_arr


print("Building f7_rsi_v7 for SOL 1m...")
sol_ts, sol_rsi = build_f7_rsi_per_asset('SOL')
print(f"  SOL RSI built: {len(sol_ts)} minutes, valid={np.isfinite(sol_rsi).sum()}")
print("Building f7_rsi_v7 for BTC 1m...")
btc_ts, btc_rsi = build_f7_rsi_per_asset('BTC')
print(f"  BTC RSI built: {len(btc_ts)} minutes, valid={np.isfinite(btc_rsi).sum()}")

# Compute ws_s per row, then asof-strict the rsi to ws_s
p['ws_s_int'] = (p['slot_start_us'] // 1_000_000 - 300).astype('int64')  # 5m → window_s=300

def asof_lookup(ts_arr, val_arr, query_ts_arr):
    """For each q in query_ts_arr, return the val at the LARGEST ts <= q."""
    idx = np.searchsorted(ts_arr, query_ts_arr, side='right') - 1
    out = np.full(len(query_ts_arr), np.nan, dtype=np.float64)
    valid = idx >= 0
    out[valid] = val_arr[idx[valid]]
    return out

p['f7_rsi_at_ws_v7'] = asof_lookup(sol_ts, sol_rsi, p['ws_s_int'].values)
p['f7_rsi_btc_at_ws'] = asof_lookup(btc_ts, btc_rsi, p['ws_s_int'].values)
print(f"\nf7_rsi_at_ws_v7 notna: {p['f7_rsi_at_ws_v7'].notna().sum()} ({p['f7_rsi_at_ws_v7'].notna().mean()*100:.1f}%)")
print(f"f7_rsi_btc_at_ws notna: {p['f7_rsi_btc_at_ws'].notna().sum()} ({p['f7_rsi_btc_at_ws'].notna().mean()*100:.1f}%)")

# Build V7 f7 gates with full coverage
p['_dir_sign'] = np.where(p['direction']=='UP', 1, -1)
p['g_f7_v7_overbought'] = (p['f7_rsi_at_ws_v7'] > 70).fillna(False).astype('int8')
p['g_f7_v7_oversold'] = (p['f7_rsi_at_ws_v7'] < 30).fillna(False).astype('int8')
p['g_f7_v7_with'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_at_ws_v7'] < 30).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_at_ws_v7'] > 70).fillna(False))
).astype('int8')
p['g_f7_v7_against'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_at_ws_v7'] > 70).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_at_ws_v7'] < 30).fillna(False))
).astype('int8')
# Looser zones
p['g_f7_v7_with_loose'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_at_ws_v7'] < 35).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_at_ws_v7'] > 65).fillna(False))
).astype('int8')
p['g_f7_v7_neutral'] = ((p['f7_rsi_at_ws_v7'] >= 40) & (p['f7_rsi_at_ws_v7'] <= 60)).fillna(False).astype('int8')
p['g_f7_v7_strong_with'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_at_ws_v7'] < 25).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_at_ws_v7'] > 75).fillna(False))
).astype('int8')

# BTC cross-asset: BTC F7 RSI extreme leading SOL direction
# Two flavors:
#   1) BTC RSI extreme matching direction (SOL UP & BTC oversold or SOL DOWN & BTC overbought) — beta-following
#   2) BTC RSI extreme against SOL direction (counter-trend leadership)
p['g_btc_f7_with'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_btc_at_ws'] < 30).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_btc_at_ws'] > 70).fillna(False))
).astype('int8')
p['g_btc_f7_against'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_btc_at_ws'] > 70).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_btc_at_ws'] < 30).fillna(False))
).astype('int8')
p['g_btc_f7_with_loose'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_btc_at_ws'] < 35).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_btc_at_ws'] > 65).fillna(False))
).astype('int8')
p['g_btc_f7_strong_with'] = (
    ((p['_dir_sign'] == 1) & (p['f7_rsi_btc_at_ws'] < 25).fillna(False)) |
    ((p['_dir_sign'] == -1) & (p['f7_rsi_btc_at_ws'] > 75).fillna(False))
).astype('int8')

# === BUILD V7 #2: BTC microstructure → SOL gate ===
# Use BTC 1m kline trend (last 5m and last 30m direction) as cross-asset leader
def kline_trend(ts_arr, closes_arr, query_ts_arr, lookback_s):
    """For each q, compute pct change from close at (q - lookback) to close at q."""
    cur = asof_lookup(ts_arr, closes_arr, query_ts_arr)
    prev = asof_lookup(ts_arr, closes_arr, query_ts_arr - lookback_s)
    return (cur - prev) / prev

# Need raw closes
btc_k = load_klines('BTC', source='binance-spot-ws', period_id='1MIN')
btc_k = btc_k[['time_period_start_us', 'price_close']].dropna().sort_values('time_period_start_us').drop_duplicates(subset='time_period_start_us').reset_index(drop=True)
btc_k['ts_s'] = (btc_k['time_period_start_us'] // 1_000_000).astype('int64')
btc_ts_arr = btc_k['ts_s'].values
btc_close_arr = btc_k['price_close'].astype(np.float64).values

p['btc_ret_5m_at_ws'] = kline_trend(btc_ts_arr, btc_close_arr, p['ws_s_int'].values, 300)
p['btc_ret_15m_at_ws'] = kline_trend(btc_ts_arr, btc_close_arr, p['ws_s_int'].values, 900)
p['btc_ret_30m_at_ws'] = kline_trend(btc_ts_arr, btc_close_arr, p['ws_s_int'].values, 1800)

p['g_btc_trend_5m_with'] = (
    ((p['_dir_sign'] == 1) & (p['btc_ret_5m_at_ws'] > 0.0005)) |
    ((p['_dir_sign'] == -1) & (p['btc_ret_5m_at_ws'] < -0.0005))
).fillna(False).astype('int8')
p['g_btc_trend_15m_with'] = (
    ((p['_dir_sign'] == 1) & (p['btc_ret_15m_at_ws'] > 0.0010)) |
    ((p['_dir_sign'] == -1) & (p['btc_ret_15m_at_ws'] < -0.0010))
).fillna(False).astype('int8')
p['g_btc_trend_30m_with'] = (
    ((p['_dir_sign'] == 1) & (p['btc_ret_30m_at_ws'] > 0.0015)) |
    ((p['_dir_sign'] == -1) & (p['btc_ret_30m_at_ws'] < -0.0015))
).fillna(False).astype('int8')
p['g_btc_trend_strong_with'] = (
    ((p['_dir_sign'] == 1) & (p['btc_ret_15m_at_ws'] > 0.0025)) |
    ((p['_dir_sign'] == -1) & (p['btc_ret_15m_at_ws'] < -0.0025))
).fillna(False).astype('int8')
p['g_btc_trend_against'] = (
    ((p['_dir_sign'] == 1) & (p['btc_ret_15m_at_ws'] < -0.0010)) |
    ((p['_dir_sign'] == -1) & (p['btc_ret_15m_at_ws'] > 0.0010))
).fillna(False).astype('int8')

# === BUILD V7 #3: Hurst variants (Path H) ===
# V6 panel already has hurst_100s, hurst_300s, hurst_900s in vol_hurst panel (joined as g_hurst_trending)
# But hurst_300s etc may not be raw values in V6 panel. Let me re-join vol_hurst
vh = pd.read_parquet("data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")
vh_sol = vh[vh['asset']=='SOL'][['slug','fire_us','fire_offset_s','hurst_100s','hurst_300s','hurst_900s',
                                  'rv_60s','rv_300s','rv_900s','rv_3600s','rv_pct_24h','vol_regime',
                                  'g_vol_low','g_vol_med','g_vol_high','g_hurst_trending','g_hurst_reverting',
                                  'g_vol_expanding','g_vol_contracting']]
vh_sol = vh_sol.drop_duplicates(subset=['slug','fire_us','fire_offset_s'])

# Drop overlapping cols from p, then re-join
overlap = [c for c in vh_sol.columns if c in p.columns and c not in ['slug','fire_us','fire_offset_s']]
p = p.drop(columns=overlap)
p = p.merge(vh_sol, on=['slug','fire_us','fire_offset_s'], how='left')
print(f"After re-join with vol_hurst: hurst_300s notna = {p['hurst_300s'].notna().mean()*100:.1f}%")

# New gates: hurst variants
p['g_hurst_strong_trending'] = (p['hurst_300s'].fillna(0) > 0.65).astype('int8')
p['g_hurst_super_strong_trending'] = (p['hurst_300s'].fillna(0) > 0.70).astype('int8')
p['g_hurst_reverting_strong'] = (p['hurst_300s'].fillna(1) < 0.35).astype('int8')
p['g_hurst_mid_trending'] = ((p['hurst_300s'].fillna(0) > 0.55) & (p['hurst_300s'].fillna(0) <= 0.65)).astype('int8')

# Hurst aligned with direction (combine with trend dir)
# Use binance 1m SOL price trend at ws_s as direction proxy
sol_k = load_klines('SOL', source='binance-spot-ws', period_id='1MIN')
sol_k = sol_k[['time_period_start_us', 'price_close']].dropna().sort_values('time_period_start_us').drop_duplicates(subset='time_period_start_us').reset_index(drop=True)
sol_k['ts_s'] = (sol_k['time_period_start_us'] // 1_000_000).astype('int64')
sol_ts_arr = sol_k['ts_s'].values
sol_close_arr = sol_k['price_close'].astype(np.float64).values

p['sol_ret_5m_at_ws'] = kline_trend(sol_ts_arr, sol_close_arr, p['ws_s_int'].values, 300)
p['sol_ret_15m_at_ws'] = kline_trend(sol_ts_arr, sol_close_arr, p['ws_s_int'].values, 900)

p['g_hurst_trending_with_dir'] = (
    (p['hurst_300s'].fillna(0) > 0.55) &
    (
        ((p['_dir_sign'] == 1) & (p['sol_ret_15m_at_ws'] > 0.001)) |
        ((p['_dir_sign'] == -1) & (p['sol_ret_15m_at_ws'] < -0.001))
    )
).astype('int8')
p['g_hurst_strong_with_dir'] = (
    (p['hurst_300s'].fillna(0) > 0.65) &
    (
        ((p['_dir_sign'] == 1) & (p['sol_ret_15m_at_ws'] > 0.001)) |
        ((p['_dir_sign'] == -1) & (p['sol_ret_15m_at_ws'] < -0.001))
    )
).astype('int8')

# === BUILD V7 #4: Vol regime specialization (Path G) ===
# Use rv_60s median split to define HIGH/LOW vol regimes
rv_med = p['rv_60s'].median()
rv_q25 = p['rv_60s'].quantile(0.25)
rv_q75 = p['rv_60s'].quantile(0.75)
print(f"rv_60s median: {rv_med:.6f}, q25: {rv_q25:.6f}, q75: {rv_q75:.6f}")
p['g_vol_v7_low'] = (p['rv_60s'].fillna(rv_med) < rv_q25).astype('int8')
p['g_vol_v7_med'] = ((p['rv_60s'].fillna(rv_med) >= rv_q25) & (p['rv_60s'].fillna(rv_med) < rv_q75)).astype('int8')
p['g_vol_v7_high'] = (p['rv_60s'].fillna(rv_med) >= rv_q75).astype('int8')
# rv_pct_24h based
p['g_vol_pct_low'] = (p['rv_pct_24h'].fillna(0.5) < 0.30).astype('int8')
p['g_vol_pct_high'] = (p['rv_pct_24h'].fillna(0.5) > 0.70).astype('int8')

# === BUILD V7 #5: Parent 15m regime → 5m fire (Path F) ===
reg15 = pd.read_parquet("data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
reg15_sol = reg15[reg15['asset']=='SOL'][['ts_us','ts_s','regime_label','regime_score',
                                            'trend_slope_30m','adx_14','tr_ema_stack_score']].sort_values('ts_s')
print(f"reg15 SOL: {len(reg15_sol)}, ts_s range: {reg15_sol['ts_s'].min()} -> {reg15_sol['ts_s'].max()}")

reg15_ts = reg15_sol['ts_s'].astype('int64').values
reg15_label = reg15_sol['regime_label'].values
reg15_slope = reg15_sol['trend_slope_30m'].fillna(0).astype(np.float64).values
reg15_score = reg15_sol['regime_score'].fillna(0).astype(np.float64).values

# asof at ws_s_int — but regime panel is at BAR END, so we need ts_s <= ws_s_int (causal)
# Need bar_end <= ws_s_int (ts_us in panel = bar end)
def asof_label(ts_arr, label_arr, query_ts):
    idx = np.searchsorted(ts_arr, query_ts, side='right') - 1
    out = np.full(len(query_ts), '', dtype=object)
    valid = idx >= 0
    out[valid] = label_arr[idx[valid]]
    return out

p['parent_15m_regime'] = asof_label(reg15_ts, reg15_label, p['ws_s_int'].values)
p['parent_15m_slope'] = asof_lookup(reg15_ts, reg15_slope, p['ws_s_int'].values)
p['parent_15m_score'] = asof_lookup(reg15_ts, reg15_score, p['ws_s_int'].values)
print(f"parent_15m_regime coverage: {(p['parent_15m_regime']!='').mean()*100:.1f}%")

# Parent regime gates
p['g_parent_trending_up'] = (p['parent_15m_regime']=='trending_up').astype('int8')
p['g_parent_trending_dn'] = (p['parent_15m_regime']=='trending_dn').astype('int8')
p['g_parent_ranging'] = (p['parent_15m_regime']=='ranging').astype('int8')

p['g_parent_with_dir'] = (
    ((p['_dir_sign']==1) & (p['parent_15m_regime']=='trending_up')) |
    ((p['_dir_sign']==-1) & (p['parent_15m_regime']=='trending_dn'))
).astype('int8')
p['g_parent_against_dir'] = (
    ((p['_dir_sign']==1) & (p['parent_15m_regime']=='trending_dn')) |
    ((p['_dir_sign']==-1) & (p['parent_15m_regime']=='trending_up'))
).astype('int8')
# Parent slope aligned (continuous version)
p['g_parent_slope_with'] = (
    ((p['_dir_sign']==1) & (p['parent_15m_slope'] > 0)) |
    ((p['_dir_sign']==-1) & (p['parent_15m_slope'] < 0))
).fillna(False).astype('int8')
p['g_parent_slope_strong_with'] = (
    ((p['_dir_sign']==1) & (p['parent_15m_slope'] > 0.0005)) |
    ((p['_dir_sign']==-1) & (p['parent_15m_slope'] < -0.0005))
).fillna(False).astype('int8')

# === Drop helper cols ===
for c in ['_dir_sign']:
    if c in p.columns:
        p = p.drop(columns=[c])

# Convert all g_ cols to int8 ensuring no NaN
for c in p.columns:
    if c.startswith('g_') or c.startswith('mgf_g_'):
        try:
            p[c] = pd.to_numeric(p[c], errors='coerce').fillna(0).astype('int8')
        except Exception:
            pass

# Summary
new_gates = [c for c in p.columns if c.startswith('g_f7_v7') or c.startswith('g_btc_') or
             c.startswith('g_hurst_') or c.startswith('g_vol_v7') or c.startswith('g_vol_pct') or
             c.startswith('g_parent_')]
print(f"\nV7 NEW gates ({len(new_gates)}):")
for g in new_gates:
    print(f"  {g}: pass_rate={p[g].mean()*100:.2f}%")

print(f"\nFinal V7 panel: {p.shape}; total g_* atoms: {sum(1 for c in p.columns if c.startswith('g_') or c.startswith('mgf_g_'))}")

out_path = OUT / "_panel_sol_5m_v7.parquet"
p.to_parquet(out_path, index=False, compression='zstd')
print(f"\nWrote {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
print(f"Elapsed: {time.time()-t0:.1f}s")
