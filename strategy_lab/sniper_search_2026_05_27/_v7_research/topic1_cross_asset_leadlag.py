"""Topic 1: Cross-asset lead-lag analysis on rf_1s + regime panels.

- close in rf_1s = 1s binance kline close per asset
- compute log returns at multiple lags, then cross-correlation
- separately: RF direction transitions (rf_dir flips) lead-lag
- separately: trend_slope_30m alignment across assets on regime_panel_5m
"""
import pandas as pd
import numpy as np
import json
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path

OUT = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/_v7_research")
OUT.mkdir(exist_ok=True, parents=True)

# --- Topic 1a: microprice/close lead-lag at multiple lags ---
print("[1a] Loading rf_1s...")
rf = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/range_filter_1s.parquet",
                     columns=['asset', 'ts_us', 'close', 'rf_dir', 'rf_dir_age', 'rf_band_pos'])
print(f"  rf_1s: {len(rf):,} rows")

# pivot to wide 1s grid
rf['ts_s'] = (rf['ts_us'] // 1_000_000).astype('int64')
wide_close = rf.pivot_table(index='ts_s', columns='asset', values='close', aggfunc='last')
print(f"  wide_close: {wide_close.shape}")
wide_close = wide_close.dropna()
print(f"  after dropna: {wide_close.shape}")
print(f"  ts_s range: {wide_close.index.min()} -> {wide_close.index.max()}")

# log returns at multiple horizons
horizons_s = [1, 5, 30, 60, 300]
results_corr = []

for h in horizons_s:
    log_ret = np.log(wide_close / wide_close.shift(h))
    log_ret = log_ret.dropna()
    # cross-asset corr matrix at SAME timestamp
    for src in ['BTC', 'ETH', 'SOL']:
        for tgt in ['BTC', 'ETH', 'SOL']:
            if src == tgt: continue
            # lag src→tgt: src at t, tgt at t+lag
            for lag_s in [0, 1, 5, 30, 60, 300]:
                if lag_s == 0:
                    c = log_ret[src].corr(log_ret[tgt])
                else:
                    c = log_ret[src].corr(log_ret[tgt].shift(-lag_s))
                results_corr.append({
                    'horizon_s': h,
                    'src': src, 'tgt': tgt,
                    'lag_s': lag_s,
                    'corr': c,
                    'n': int(min(len(log_ret[src].dropna()), len(log_ret[tgt].dropna())))
                })

dfc = pd.DataFrame(results_corr)
dfc.to_csv(OUT / "topic1a_log_ret_corr.csv", index=False)
print("\nTop 20 src→tgt lag pairs by abs corr (horizon=5s):")
sub = dfc[dfc['horizon_s']==5].copy()
sub['abs_corr'] = sub['corr'].abs()
print(sub.sort_values('abs_corr', ascending=False).head(20).to_string(index=False))

# --- Topic 1b: RF dir lead-lag (rf_dir flips) ---
print("\n[1b] RF direction lead-lag...")
wide_rfdir = rf.pivot_table(index='ts_s', columns='asset', values='rf_dir', aggfunc='last').dropna()
print(f"  rf_dir wide: {wide_rfdir.shape}")

# direction agree freq per lag
rf_results = []
for src in ['BTC', 'ETH', 'SOL']:
    for tgt in ['BTC', 'ETH', 'SOL']:
        if src == tgt: continue
        for lag_s in [0, 1, 5, 30, 60, 300]:
            if lag_s == 0:
                same = (wide_rfdir[src] == wide_rfdir[tgt]).mean()
            else:
                same = (wide_rfdir[src] == wide_rfdir[tgt].shift(-lag_s)).mean()
            rf_results.append({'src': src, 'tgt': tgt, 'lag_s': lag_s, 'agree_freq': same})

dfr = pd.DataFrame(rf_results)
dfr.to_csv(OUT / "topic1b_rf_dir_agree.csv", index=False)
print("\nRF dir agreement freq (sample):")
print(dfr.head(20).to_string(index=False))

# --- Topic 1c: trend_slope_30m lead-lag from regime_panel_5m_v2_fixed ---
print("\n[1c] Regime panel trend_slope_30m lead-lag...")
reg5 = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet",
                        columns=['asset', 'ts_us', 'trend_slope_30m', 'regime_label'])
print(f"  regime_5m: {len(reg5):,}")
reg5['ts_s'] = (reg5['ts_us'] // 1_000_000).astype('int64')
wide_ts = reg5.pivot_table(index='ts_s', columns='asset', values='trend_slope_30m', aggfunc='last').dropna()
print(f"  wide trend_slope_30m: {wide_ts.shape}")

# lag in MINUTES (300s bar)
ts_results = []
# Regime panel is 5m bars: ts_s steps by 300
for src in ['BTC', 'ETH', 'SOL']:
    for tgt in ['BTC', 'ETH', 'SOL']:
        if src == tgt: continue
        # corr at same bar, and lag by 1, 2, 3 bars (5, 10, 15 min)
        for lag_bars in [-3, -2, -1, 0, 1, 2, 3]:
            x = wide_ts[src]
            y = wide_ts[tgt].shift(-lag_bars)
            c = x.corr(y)
            # sign agreement
            agree_sign = ((np.sign(x) == np.sign(y)) & (x.abs() > 1e-9)).mean()
            ts_results.append({'src': src, 'tgt': tgt, 'lag_bars_5m': lag_bars, 'corr': c, 'sign_agree': agree_sign})

dfts = pd.DataFrame(ts_results)
dfts.to_csv(OUT / "topic1c_trend_slope_corr.csv", index=False)
print("\nTrend slope corr (sample):")
print(dfts.to_string(index=False))

# --- Topic 1d: which 3 cross-asset gates have biggest lift? ---
# Test on actual fire universe — pick BTC microprice change >0 at fire_us, then ask if ETH outcome
# is biased UP/DOWN
print("\n[1d] Build cross-asset gates and measure lift on ETH/SOL fires...")
# load ETH fires
eth = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_5m_full_v3.parquet",
                      columns=['slug', 'fire_us', 'direction', 'won', 'outcome'])
print(f"  ETH 5m fires: {len(eth):,}")
# baseline UP rate
print(f"  Outcome UP rate (ETH 5m): {(eth['outcome']=='Up').mean():.4f}")

# build BTC 30s log return at fire_us
btc_close = rf[rf['asset']=='BTC'][['ts_s', 'close']].drop_duplicates('ts_s').set_index('ts_s')['close']
btc_close = btc_close.sort_index()
# asof join: for each eth fire_us, get BTC close at fire_us and 30s prior
eth['fire_s'] = (eth['fire_us'] // 1_000_000).astype('int64')
eth_btc = eth.merge(btc_close.rename('btc_close_t'), left_on='fire_s', right_index=True, how='left')
eth_btc = eth_btc.merge(btc_close.shift(30).rename('btc_close_tm30'), left_on='fire_s', right_index=True, how='left')
eth_btc['btc_ret_30s'] = np.log(eth_btc['btc_close_t'] / eth_btc['btc_close_tm30'])
eth_btc = eth_btc.dropna(subset=['btc_ret_30s'])
print(f"  after BTC join: {len(eth_btc):,} fires")

# Gate: BTC 30s return > 5bps -> ETH UP bias?
bps_thresh = 5e-4  # 5bps
gate_pos = eth_btc[eth_btc['btc_ret_30s'] > bps_thresh]
gate_neg = eth_btc[eth_btc['btc_ret_30s'] < -bps_thresh]
gate_zero = eth_btc[eth_btc['btc_ret_30s'].abs() <= bps_thresh]
print(f"\nBTC 30s ret > +5bps: n={len(gate_pos):,}  ETH UP-outcome rate = {(gate_pos['outcome']=='Up').mean():.4f}")
print(f"BTC 30s ret < -5bps: n={len(gate_neg):,}  ETH UP-outcome rate = {(gate_neg['outcome']=='Up').mean():.4f}")
print(f"BTC 30s ret in band:  n={len(gate_zero):,}  ETH UP-outcome rate = {(gate_zero['outcome']=='Up').mean():.4f}")

# Also: BTC 5min return
eth_btc = eth_btc.merge(btc_close.shift(300).rename('btc_close_tm300'), left_on='fire_s', right_index=True, how='left')
eth_btc['btc_ret_300s'] = np.log(eth_btc['btc_close_t'] / eth_btc['btc_close_tm300'])
eth_btc2 = eth_btc.dropna(subset=['btc_ret_300s'])
bps_thresh = 1e-3
g_pos = eth_btc2[eth_btc2['btc_ret_300s'] > bps_thresh]
g_neg = eth_btc2[eth_btc2['btc_ret_300s'] < -bps_thresh]
print(f"\nBTC 300s ret > +10bps: n={len(g_pos):,}  ETH UP-outcome rate = {(g_pos['outcome']=='Up').mean():.4f}")
print(f"BTC 300s ret < -10bps: n={len(g_neg):,}  ETH UP-outcome rate = {(g_neg['outcome']=='Up').mean():.4f}")

# Same for SOL fires
sol = pd.read_parquet(r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_5m_full_v3.parquet",
                      columns=['slug', 'fire_us', 'direction', 'won', 'outcome'])
sol['fire_s'] = (sol['fire_us'] // 1_000_000).astype('int64')
sol_btc = sol.merge(btc_close.rename('btc_close_t'), left_on='fire_s', right_index=True, how='left')
sol_btc = sol_btc.merge(btc_close.shift(30).rename('btc_close_tm30'), left_on='fire_s', right_index=True, how='left')
sol_btc['btc_ret_30s'] = np.log(sol_btc['btc_close_t'] / sol_btc['btc_close_tm30'])
sol_btc = sol_btc.dropna(subset=['btc_ret_30s'])
print(f"\nSOL 5m fires: {len(sol_btc):,}")
print(f"  Outcome UP rate (SOL 5m baseline): {(sol_btc['outcome']=='Up').mean():.4f}")
g_pos = sol_btc[sol_btc['btc_ret_30s'] > 5e-4]
g_neg = sol_btc[sol_btc['btc_ret_30s'] < -5e-4]
print(f"BTC 30s ret > +5bps: n={len(g_pos):,}  SOL UP-outcome rate = {(g_pos['outcome']=='Up').mean():.4f}")
print(f"BTC 30s ret < -5bps: n={len(g_neg):,}  SOL UP-outcome rate = {(g_neg['outcome']=='Up').mean():.4f}")

print("\n[1] DONE.")
