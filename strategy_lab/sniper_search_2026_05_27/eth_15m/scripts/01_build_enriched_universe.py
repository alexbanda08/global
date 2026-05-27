"""Build enriched ETH 15m fire universe (v3, 33d).

Strategy: start from v3 fires (full 33d, 39,546 rows). Layer panels with proper coverage:

  Layer A: regime_panel_15m_v2_fixed (28d, asof on fire_us)
     -> trend_slope_30m_rg, atr_14_rg, bb_width_60s_rg, range_compression_rg, etc.
     -> compute g_trend_slope_with (causal), g_trend_slope_strong_with

  Layer B: vol_hurst_at_fire_15m (22d, slug+fire_us+offset join)
     -> g_hurst_trending, g_hurst_reverting, g_vol_high, g_vol_low, g_vol_expanding, g_vol_contracting, g_rv_with
     -> hurst_300s, hurst_900s, rv_60s, rv_300s, rv_900s, vwap_since_open_bps

  Layer C: microprice_panel (31.7d, slug+fire_us+offset join)
     -> mp_skew, mp_imbalance, mp_weighted_skew, mp_skew_500ms, mp_skew_change_500ms
     -> compute g_mp_no_extreme, g_mp_skew_with, g_mp_change_with (causal v3-thresholds)

  Layer D: sms_panel_15m_v2_fixed (22d, asof — gives smart-money cvd/rsi divergence)
     -> rsi_14, cvd_sign, choch_buy/sell, trend_strength_pct, system_confidence
     -> compute g_markov_with (via trend cluster), g_sms_divergence_with

  Layer E: master_gate_features_v2 (24.8d, slug+fire_us join — bonus exotic gates)
     -> g_imb5_strong_with, g_queue_top_high, g_imb_change_with, g_vwap_ge_50_le_85,
        g_flow_with_and_no_whale, g_coinbase_basis_extreme_against, g_hl_liq_cascade_with,
        g_lm_high_stat, g_hawkes_imbalance_with, etc.

  Layer F: fresh 15m alpha (NEW — own computation):
     -> g_above_1h_dailyvwap_with (binance ETH 1h)
     -> g_near_pivot
     -> g_offset_late, g_offset_mid, g_offset_early (offset bins)

Output: eth_15m_enriched.parquet
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m"
os.makedirs(OUT, exist_ok=True)

# ---- 1. v3 fires ----
log("loading v3 fires")
fires = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_15m_full_v3.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
log(f"v3 fires: {len(fires)} | date {pd.to_datetime(fires.fire_us.min(), unit='us', utc=True)} -> {pd.to_datetime(fires.fire_us.max(), unit='us', utc=True)}")
fires['fire_us_key'] = fires['fire_us']

# ---- A: regime v2_fixed ----
log("layer A: regime_panel_15m_v2_fixed (ETH)")
r2 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
r2 = r2[r2.asset=='ETH'].copy().sort_values('ts_us').reset_index(drop=True)
log(f"  regime v2_fixed rows: {len(r2)} | {pd.to_datetime(r2.ts_us.min(), unit='us', utc=True)} -> {pd.to_datetime(r2.ts_us.max(), unit='us', utc=True)}")
r2_keep = r2[['ts_us','trend_slope_30m','regime_label','regime_score',
              'adx_14','plus_di_14','minus_di_14','atr_14',
              'tr_ema_stack_score','realized_vol_60m','range_compression','bb_width_60s']].copy()
r2_keep.columns = ['rg_ts_us'] + [c + '_rg' for c in r2_keep.columns if c != 'ts_us']
r2_keep = r2_keep.sort_values('rg_ts_us')
fires = pd.merge_asof(fires, r2_keep, left_on='fire_us_key', right_on='rg_ts_us', direction='backward')
fires['rg_age_s'] = (fires.fire_us - fires.rg_ts_us) / 1e6
log(f"  regime age: mean={fires.rg_age_s.mean():.1f}s max={fires.rg_age_s.max():.1f}s null={fires.rg_ts_us.isna().sum()}")
# Build g_trend_slope_with
ds = np.where(fires.direction == 'UP', 1, -1)
ts = fires['trend_slope_30m_rg']
fires['g_trend_slope_with'] = np.where(ts.isna(), 0, ((ds > 0) & (ts > 0)) | ((ds < 0) & (ts < 0))).astype(int)
thr = ts.abs().quantile(0.75)
fires['g_trend_slope_strong_with'] = np.where(ts.isna(), 0, ((ds > 0) & (ts > thr)) | ((ds < 0) & (ts < -thr))).astype(int)
log(f"  thr |slope| 75pct: {thr:.4f}; g_trend_slope_with ones: {fires.g_trend_slope_with.mean():.3f}; strong ones: {fires.g_trend_slope_strong_with.mean():.3f}")
# Build g_adx_strong: adx_14 > 25
fires['g_adx_strong']    = (fires.adx_14_rg.fillna(0) > 25).astype(int)
# g_range_compressed: range_compression in bottom 25%
rc_q = fires.range_compression_rg.quantile(0.25)
fires['g_range_compressed'] = (fires.range_compression_rg < rc_q).astype(int)
# g_bb_squeeze: bb_width_60s in bottom 25%
bb_q = fires.bb_width_60s_rg.quantile(0.25)
fires['g_bb_squeeze'] = (fires.bb_width_60s_rg < bb_q).astype(int)
# g_atr_high
atr_q = fires.atr_14_rg.quantile(0.75)
fires['g_atr_high'] = (fires.atr_14_rg > atr_q).astype(int)

# ---- B: vol_hurst_at_fire_15m ----
log("layer B: vol_hurst_at_fire_15m")
vh = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/vol_hurst_at_fire_15m.parquet")
vh = vh[vh.asset=='ETH'].copy()
log(f"  vh ETH rows: {len(vh)} | {pd.to_datetime(vh.fire_us.min(), unit='us', utc=True)} -> {pd.to_datetime(vh.fire_us.max(), unit='us', utc=True)}")
vh_gates = ['g_hurst_trending','g_hurst_reverting','g_vol_high','g_vol_low','g_vol_med','g_vol_expanding','g_vol_contracting','g_rv_with']
vh_feats = ['hurst_300s','hurst_900s','rv_60s','rv_300s','rv_900s','rv_pct_24h','vwap_since_open_bps','ret_30s']
vh_keep = ['slug','fire_us','fire_offset_s'] + [c for c in vh_gates+vh_feats if c in vh.columns]
vh_k = vh[vh_keep].drop_duplicates(['slug','fire_us'])
fires = fires.merge(vh_k, on=['slug','fire_us','fire_offset_s'], how='left', suffixes=('', '_vh'))
# Where vh missing, set gates to 0; coverage check
log(f"  vh coverage: g_hurst_trending non-null: {fires.g_hurst_trending.notna().mean():.3f}")
for g in vh_gates:
    if g in fires.columns:
        fires[g] = fires[g].fillna(0).astype(int)

# ---- C: microprice_panel ----
log("layer C: microprice_panel")
mp = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/microprice_panel.parquet")
mp = mp[mp.asset=='ETH'].copy()
log(f"  mp ETH rows: {len(mp)} | {pd.to_datetime(mp.fire_us.min(), unit='us', utc=True)} -> {pd.to_datetime(mp.fire_us.max(), unit='us', utc=True)}")
mp_keep = ['slug','fire_us','fire_offset_s','mp_skew','mp_imbalance','mp_weighted_skew','mp_weighted_imbalance',
           'mp_skew_500ms','mp_skew_change_500ms','mp_up_dev_bps','mp_dn_dev_bps','mp_up_dev_change_500ms','mp_dn_dev_change_500ms']
mp_keep = [c for c in mp_keep if c in mp.columns]
mp_k = mp[mp_keep].drop_duplicates(['slug','fire_us'])
fires = fires.merge(mp_k, on=['slug','fire_us','fire_offset_s'], how='left', suffixes=('', '_mp'))
log(f"  mp coverage: mp_skew non-null: {fires.mp_skew.notna().mean():.3f}")
# g_mp_no_extreme: |mp_skew| < 100 bps
fires['g_mp_no_extreme'] = (fires.mp_skew.abs() < 100).fillna(False).astype(int)
# Looser variant per R7 (150 bps)
fires['g_mp_no_extreme_150'] = (fires.mp_skew.abs() < 150).fillna(False).astype(int)
# g_mp_skew_with: sign matches direction
fires['g_mp_skew_with'] = (((fires.mp_skew > 5) & (fires.direction=='UP')) |
                            ((fires.mp_skew < -5) & (fires.direction=='DOWN'))).fillna(False).astype(int)
# g_mp_change_with: 500ms skew change aligned
if 'mp_skew_change_500ms' in fires.columns:
    fires['g_mp_change_with'] = (((fires.mp_skew_change_500ms > 0) & (fires.direction=='UP')) |
                                  ((fires.mp_skew_change_500ms < 0) & (fires.direction=='DOWN'))).fillna(False).astype(int)
else:
    fires['g_mp_change_with'] = 0
# g_mp_weighted_skew_with: same but with weighted_skew
if 'mp_weighted_skew' in fires.columns:
    fires['g_mp_weighted_skew_with'] = (((fires.mp_weighted_skew > 5) & (fires.direction=='UP')) |
                                         ((fires.mp_weighted_skew < -5) & (fires.direction=='DOWN'))).fillna(False).astype(int)
else:
    fires['g_mp_weighted_skew_with'] = 0
# g_mp_imbalance_with
if 'mp_imbalance' in fires.columns:
    fires['g_mp_imbalance_with'] = (((fires.mp_imbalance > 0.05) & (fires.direction=='UP')) |
                                     ((fires.mp_imbalance < -0.05) & (fires.direction=='DOWN'))).fillna(False).astype(int)

# ---- D: sms_panel_15m_v2_fixed ----
log("layer D: sms_panel_15m_v2_fixed (smart money)")
sms = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/sms_panel_15m_v2_fixed.parquet")
sms = sms[sms.asset=='ETH'].copy().sort_values('ts_us').reset_index(drop=True)
log(f"  sms ETH rows: {len(sms)} | {pd.to_datetime(sms.ts_us.min(), unit='us', utc=True)} -> {pd.to_datetime(sms.ts_us.max(), unit='us', utc=True)}")
sms_cols = ['ts_us','rsi_14','cvd_sign','choch_buy','choch_sell','bos_buy','bos_sell',
            'trend_5m','trend_15m','trend_30m','trend_1h','trend_strength_pct','system_confidence',
            'rsi_bullish_div','rsi_bearish_div']
sms_keep = sms[[c for c in sms_cols if c in sms.columns]].copy()
sms_keep.columns = ['sms_ts_us'] + [c + '_sms' for c in sms_keep.columns if c != 'ts_us']
sms_keep = sms_keep.sort_values('sms_ts_us')
fires = pd.merge_asof(fires, sms_keep, left_on='fire_us_key', right_on='sms_ts_us', direction='backward')
fires['sms_age_s'] = (fires.fire_us - fires.sms_ts_us) / 1e6
log(f"  sms age: mean={fires.sms_age_s.mean():.1f}s null={fires.sms_ts_us.isna().sum()}")
# Build markov gates based on trend_strength_pct + trend_15m direction
if 'trend_15m_sms' in fires.columns:
    t15 = fires.trend_15m_sms.fillna(0)
    # trend_15m is typically 1 (bull) / -1 (bear) / 0
    fires['g_markov_with'] = (((t15 > 0) & (fires.direction=='UP')) |
                              ((t15 < 0) & (fires.direction=='DOWN'))).fillna(False).astype(int)
else:
    fires['g_markov_with'] = 0
# Multi-TF trend alignment
if 'trend_1h_sms' in fires.columns and 'trend_15m_sms' in fires.columns:
    t1h = fires.trend_1h_sms.fillna(0); t15 = fires.trend_15m_sms.fillna(0)
    aligned_up   = (t1h > 0) & (t15 > 0)
    aligned_down = (t1h < 0) & (t15 < 0)
    fires['g_multi_tf_align_with'] = ((aligned_up & (fires.direction=='UP')) |
                                       (aligned_down & (fires.direction=='DOWN'))).astype(int)
# CVD with direction
if 'cvd_sign_sms' in fires.columns:
    cvd = fires.cvd_sign_sms.fillna(0)
    fires['g_cvd_with'] = (((cvd > 0) & (fires.direction=='UP')) |
                           ((cvd < 0) & (fires.direction=='DOWN'))).fillna(False).astype(int)
# RSI extremes
if 'rsi_14_sms' in fires.columns:
    rsi = fires.rsi_14_sms.fillna(50)
    # ws_s anchor RSI extreme: low RSI bullish reversal
    fires['g_rsi_oversold']   = (rsi < 30).astype(int)
    fires['g_rsi_overbought'] = (rsi > 70).astype(int)
    fires['g_rsi_extreme_with'] = (((rsi < 30) & (fires.direction=='UP')) |
                                    ((rsi > 70) & (fires.direction=='DOWN'))).astype(int)
# BOS / CHOCH alignment
if 'bos_buy_sms' in fires.columns:
    fires['g_bos_with'] = ((fires.bos_buy_sms.fillna(0) > 0) & (fires.direction=='UP') |
                           (fires.bos_sell_sms.fillna(0) > 0) & (fires.direction=='DOWN')).astype(int)
# Trend strength gate
if 'trend_strength_pct_sms' in fires.columns:
    ts_strength = fires.trend_strength_pct_sms.fillna(0)
    fires['g_trend_strong_60'] = (ts_strength > 60).astype(int)
    fires['g_trend_strong_80'] = (ts_strength > 80).astype(int)

# ---- E: master_gate_features_v2 ----
log("layer E: master_gate_features_v2 (R3/R4/R5 exotic atoms)")
mgf = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/master_gate_features_v2.parquet")
mgf = mgf[(mgf.asset=='ETH') & (mgf.tf=='15m')].copy()
log(f"  mgf ETH 15m rows: {len(mgf)}")
exotic_gates = ['g_imb5_strong_with','g_queue_top_high','g_imb_change_with','g_vwap_ge_50_le_85',
                'g_book_slope_steep_against','g_coinbase_basis_extreme_against','g_hl_liq_cascade_with',
                'g_flow_with_and_no_whale','g_lm_high_stat','g_lm_extreme_against','g_hawkes_imbalance_with',
                'g_within_dev','g_dev_extreme']
have = [g for g in exotic_gates if g in mgf.columns]
log(f"  exotic gates in mgf: {have}")
mgf_keep = mgf[['slug','fire_us'] + have].drop_duplicates(['slug','fire_us'])
# Drop any pre-existing gate with same name from v3 fires (the v3 fires have g_within_dev / g_dev_extreme already)
for g in have:
    if g in fires.columns:
        fires = fires.drop(columns=[g])
fires = fires.merge(mgf_keep, on=['slug','fire_us'], how='left')
for g in have:
    fires[g] = fires[g].fillna(0).astype(int)
log(f"  mgf coverage: g_lm_high_stat non-null fraction: {(fires.g_lm_high_stat.sum()/len(fires)):.3f}")

# ---- F: fresh 15m alpha (1h VWAP, pivot) ----
log("layer F: 1h ETH binance klines for parent VWAP / pivot")
try:
    import sys; sys.path.insert(0, f"{ROOT}/data/v4/canonical")
    from load import load_klines
    # Use 1m as base (1h doesn't exist in WS — only vision); roll up to 1h
    k1m = load_klines('ETH', source='binance-spot-ws', period_id='1MIN')
    log(f"  1m klines: {len(k1m)} rows")
    end_col = 'time_period_start_us'
    k1m = k1m.sort_values(end_col).reset_index(drop=True)
    # Bucket to 1h (using floor of period_start)
    k1m['hour_us'] = (k1m[end_col] // (3600 * 1_000_000)) * 3600 * 1_000_000
    k1h = k1m.groupby('hour_us').agg(
        open=('price_open','first'), high=('price_high','max'), low=('price_low','min'),
        close=('price_close','last'), volume=('volume_traded','sum')
    ).reset_index()
    k1h = k1h.rename(columns={'hour_us':'ts_us'}).sort_values('ts_us').reset_index(drop=True)
    end_col = 'ts_us'
    log(f"  rolled to 1h: {len(k1h)} rows")
    # Daily VWAP per UTC day
    k1h['date'] = pd.to_datetime(k1h[end_col], unit='us', utc=True).dt.date
    k1h['pv'] = k1h.close * k1h.volume
    k1h['cum_pv'] = k1h.groupby('date').pv.cumsum()
    k1h['cum_v']  = k1h.groupby('date').volume.cumsum().replace(0,1)
    k1h['daily_vwap'] = k1h.cum_pv / k1h.cum_v
    # Daily pivot from prior day
    daily = k1h.groupby('date').agg(high=('high','max'), low=('low','min'), close=('close','last')).reset_index()
    daily['pp'] = (daily.high + daily.low + daily.close) / 3
    daily['date_next'] = pd.to_datetime(daily.date) + pd.Timedelta(days=1)
    daily['date_next'] = daily.date_next.dt.date
    pp_map = dict(zip(daily.date_next, daily.pp))
    k1h['pp_today'] = k1h.date.map(pp_map)
    k1h_keep = k1h[[end_col, 'close', 'daily_vwap', 'pp_today']].copy()
    k1h_keep.columns = ['k1h_ts_us', 'close_1h', 'daily_vwap_1h', 'pp_today_1h']
    k1h_keep = k1h_keep.sort_values('k1h_ts_us')
    fires = pd.merge_asof(fires, k1h_keep, left_on='fire_us_key', right_on='k1h_ts_us', direction='backward')
    above_vwap = fires.close_1h > fires.daily_vwap_1h
    fires['g_above_1h_dailyvwap_with'] = ((above_vwap & (fires.direction=='UP')) |
                                          (~above_vwap & (fires.direction=='DOWN'))).fillna(False).astype(int)
    pp_dist = (fires.close_1h - fires.pp_today_1h).abs() / fires.pp_today_1h.replace(0, np.nan)
    fires['g_near_pivot']    = (pp_dist < 0.005).fillna(False).astype(int)
    fires['g_far_from_pivot'] = (pp_dist > 0.02).fillna(False).astype(int)
    log(f"  1h VWAP & pivot OK; g_above_1h_dailyvwap_with ones: {fires.g_above_1h_dailyvwap_with.mean():.3f}")
except Exception as e:
    log(f"  1h klines load failed: {e}")
    fires['g_above_1h_dailyvwap_with'] = 0
    fires['g_near_pivot'] = 0
    fires['g_far_from_pivot'] = 0

# ---- Offset bins ----
fires['offset_bin'] = pd.cut(fires.fire_offset_s, bins=[-1, 60, 150, 300, 480, 720, 900],
                              labels=['0-60','60-150','150-300','300-480','480-720','720-900'])
# Late-window offsets are >=600s
fires['g_offset_early'] = (fires.fire_offset_s <= 60).astype(int)
fires['g_offset_mid']   = ((fires.fire_offset_s >= 240) & (fires.fire_offset_s <= 480)).astype(int)
fires['g_offset_late']  = (fires.fire_offset_s >= 600).astype(int)

# ---- Bonus: book depth at $250 (for sub-deployment) ----
# We don't have direct $250 fillability here; will check post-hoc

# ---- Drop helper col ----
fires = fires.drop(columns=['fire_us_key'])

# ---- Save ----
gate_cols = [c for c in fires.columns if c.startswith('g_')]
log(f"final shape: {fires.shape}; gates: {len(gate_cols)}")
log(f"all gates: {gate_cols}")
fires.to_parquet(f"{OUT}/eth_15m_enriched.parquet", index=False)
log(f"WROTE eth_15m_enriched.parquet ({len(fires)} rows, {len(fires.columns)} cols)")
log("DONE")
