"""V7 ETH 15m — extend V6 enriched with NEW pre-window gates.

V7 Path I priority: pre-window deeper combos. Build:
  - g_pw_m1v_with(direction): M1V regime at ws_s aligned with direction
  - g_pw_xa_unanimity_with(direction): all 3 asset RFs (BTC,ETH,SOL) at ws_s-30s agree with direction
  - g_pw_mp_change_with(direction): microprice change in last 500ms before ws_s aligned with direction (from MGF v2 mp_skew_change_500ms at fire_us as proxy; if available at ws_s, use that)
  - g_pw_xa_unanimity_strong: all 3 asset RFs agree + |rf_dist_bps| > median at ws_s-30s
  - g_pw_xa_unanimity_btc_lead: BTC + ETH RF agree at ws_s-30s, SOL optional
  - g_pw_xa_partial: 2-of-3 RFs agree at ws_s-30s

Path H: hurst variants
  - g_hurst_strong_trending(>=0.65), g_hurst_reverting(<0.40)
  - g_hurst_regime_with(direction): hurst>0.55 AND trend_slope sign aligned with direction

Path G: vol regime
  - g_vol_high_only / g_vol_low_only / g_vol_med_only (already in V6)
  - rv_60s vs median: g_rv_60_above_median / below

Path C: cross-asset BTC 15m trend → ETH 15m fire
  - g_btc_15m_trend_with(direction): BTC trend_slope_30m at ETH ws_s aligned with ETH direction
"""
import os, time, warnings, sys
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v7"
os.makedirs(OUT, exist_ok=True)

# --- 1. Load V6 enriched (already has all V6 gates + pre-window features) ---
log("loading V6 enriched ETH 15m universe")
fires = pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/eth_15m_v6/eth_15m_enriched_v6.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
log(f"v6 enriched: {fires.shape}; gates: {sum(1 for c in fires.columns if c.startswith('g_'))}")
assert 'ws_s_us' in fires.columns and 'ws_s_m30_us' in fires.columns
ds = np.where(fires.direction == 'UP', 1, -1)

# --- 2. V7 NEW: M1V regime at ws_s ---
# Use s15_with_ta_and_markov.parquet which has per-bar m1v for ETH
log("layer: M1V at ws_s")
m15 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/s15_with_ta_and_markov.parquet")
m15_eth = m15[m15.asset == 'ETH'].copy().sort_values('ts_us').reset_index(drop=True)
m15_keep = m15_eth[['ts_us', 'm1v']].copy()
m15_keep.columns = ['pw_m1v_ts_us', 'pw_m1v_state']
m15_keep = m15_keep.sort_values('pw_m1v_ts_us')

fires = pd.merge_asof(fires.sort_values('ws_s_us'), m15_keep,
                      left_on='ws_s_us', right_on='pw_m1v_ts_us', direction='backward')
fires = fires.sort_values('fire_us').reset_index(drop=True)
fires['pw_m1v_age_s'] = (fires.ws_s_us - fires.pw_m1v_ts_us) / 1e6
nulls = fires.pw_m1v_state.isna().sum()
log(f"  pw_m1v_state @ ws_s: nulls={nulls} / {len(fires)} | mean_age_s={fires.pw_m1v_age_s.mean():.1f}")

# M1V: 0=bearish, 1=neutral, 2=bullish (typical Markov regime convention)
m1v = fires.pw_m1v_state
fires['g_pw_m1v_with'] = (((m1v == 2) & (fires.direction == 'UP')) |
                          ((m1v == 0) & (fires.direction == 'DOWN'))).fillna(False).astype(int)
fires['g_pw_m1v_strong_with'] = fires['g_pw_m1v_with']  # alias for now; m1v has only 3 states
fires['g_pw_m1v_neutral'] = (m1v == 1).fillna(False).astype(int)
log(f"  g_pw_m1v_with: ones={fires.g_pw_m1v_with.sum()} ({fires.g_pw_m1v_with.mean():.3f})")

# --- 3. V7 NEW: Cross-asset RF unanimity at ws_s - 30s ---
log("layer: range_filter_1s for cross-asset RF unanimity")
rf1s = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/range_filter_1s.parquet")
rf1s = rf1s.sort_values('ts_us').reset_index(drop=True)
log(f"  range_filter_1s shape: {rf1s.shape}")
log(f"  ts_us range: {pd.to_datetime(rf1s.ts_us.min(), unit='us')} -> {pd.to_datetime(rf1s.ts_us.max(), unit='us')}")

# For each asset, asof-join rf_dir + rf_dist_bps at ws_s - 30s
for asset in ['BTC', 'ETH', 'SOL']:
    rfa = rf1s[rf1s.asset == asset][['ts_us', 'rf_dir', 'rf_dist_bps']].copy()
    rfa.columns = [f'rf_ts_us_{asset.lower()}', f'rf_dir_{asset.lower()}', f'rf_dist_bps_{asset.lower()}']
    rfa = rfa.sort_values(f'rf_ts_us_{asset.lower()}')
    fires = pd.merge_asof(fires.sort_values('ws_s_m30_us'), rfa,
                          left_on='ws_s_m30_us', right_on=f'rf_ts_us_{asset.lower()}', direction='backward')
    fires = fires.sort_values('fire_us').reset_index(drop=True)
    n_null = fires[f'rf_dir_{asset.lower()}'].isna().sum()
    log(f"  RF {asset} @ ws_s-30s: nulls={n_null}")

# Unanimity gates
rb = fires['rf_dir_btc'].fillna(0)
re = fires['rf_dir_eth'].fillna(0)
rs = fires['rf_dir_sol'].fillna(0)

# All 3 agree with fire direction
fires['g_pw_xa_unanimity_with'] = (
    (((rb > 0) & (re > 0) & (rs > 0)) & (fires.direction == 'UP')) |
    (((rb < 0) & (re < 0) & (rs < 0)) & (fires.direction == 'DOWN'))
).astype(int)

# All 3 agree (no direction filter) — pure unanimity (cross-market trend regime)
fires['g_pw_xa_unanimity'] = (
    ((rb > 0) & (re > 0) & (rs > 0)) | ((rb < 0) & (re < 0) & (rs < 0))
).astype(int)

# Strong unanimity: all 3 + ETH magnitude > median
eth_dist_med = fires.rf_dist_bps_eth.abs().median()
fires['g_pw_xa_unanimity_strong_with'] = (
    fires.g_pw_xa_unanimity_with & (fires.rf_dist_bps_eth.abs() > eth_dist_med)
).astype(int)
log(f"  median |rf_dist_bps_eth| = {eth_dist_med:.3f}")

# Partial 2-of-3
agree_count_up   = ((rb > 0).astype(int) + (re > 0).astype(int) + (rs > 0).astype(int))
agree_count_down = ((rb < 0).astype(int) + (re < 0).astype(int) + (rs < 0).astype(int))
fires['g_pw_xa_partial_with'] = (
    ((agree_count_up >= 2) & (fires.direction == 'UP')) |
    ((agree_count_down >= 2) & (fires.direction == 'DOWN'))
).astype(int)

# BTC+ETH agree (without SOL noise)
fires['g_pw_xa_btc_eth_with'] = (
    (((rb > 0) & (re > 0)) & (fires.direction == 'UP')) |
    (((rb < 0) & (re < 0)) & (fires.direction == 'DOWN'))
).astype(int)

# BTC alone leading (Path C): BTC RF dir at ws_s-30s aligned with ETH fire direction
fires['g_pw_btc_rf_with'] = (
    ((rb > 0) & (fires.direction == 'UP')) | ((rb < 0) & (fires.direction == 'DOWN'))
).astype(int)

log(f"  g_pw_xa_unanimity_with: ones={fires.g_pw_xa_unanimity_with.sum()} ({fires.g_pw_xa_unanimity_with.mean():.3f})")
log(f"  g_pw_xa_unanimity_strong_with: ones={fires.g_pw_xa_unanimity_strong_with.sum()}")
log(f"  g_pw_xa_partial_with: ones={fires.g_pw_xa_partial_with.sum()}")
log(f"  g_pw_xa_btc_eth_with: ones={fires.g_pw_xa_btc_eth_with.sum()}")
log(f"  g_pw_btc_rf_with: ones={fires.g_pw_btc_rf_with.sum()}")

# --- 4. V7 NEW: Cross-asset BTC 15m trend at ETH ws_s (Path C deeper) ---
log("layer: BTC 15m regime trend at ETH ws_s")
rg = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
rg_btc = rg[rg.asset == 'BTC'][['ts_us', 'trend_slope_30m', 'regime_label']].copy().sort_values('ts_us').reset_index(drop=True)
rg_btc.columns = ['btc_rg_ts_us', 'btc_trend_slope_30m', 'btc_regime_label']
fires = pd.merge_asof(fires.sort_values('ws_s_us'), rg_btc,
                      left_on='ws_s_us', right_on='btc_rg_ts_us', direction='backward')
fires = fires.sort_values('fire_us').reset_index(drop=True)
bts = fires.btc_trend_slope_30m
fires['g_pw_btc_15m_trend_with'] = np.where(bts.isna(), 0,
    ((bts > 0) & (fires.direction == 'UP')) | ((bts < 0) & (fires.direction == 'DOWN'))).astype(int)
btc_thr = bts.abs().quantile(0.75)
fires['g_pw_btc_15m_trend_strong_with'] = np.where(bts.isna(), 0,
    ((bts > btc_thr) & (fires.direction == 'UP')) | ((bts < -btc_thr) & (fires.direction == 'DOWN'))).astype(int)
log(f"  g_pw_btc_15m_trend_with: ones={fires.g_pw_btc_15m_trend_with.sum()}")
log(f"  g_pw_btc_15m_trend_strong_with: ones={fires.g_pw_btc_15m_trend_strong_with.sum()}")

# --- 5. V7 NEW: Microprice change at ws_s (best effort) ---
# V6 doesn't have microprice change at ws_s — only at fire_us via MGF v2
# Use MGF v2 for HUR22 cohort: join slug → mp_skew_change_500ms (this is at fire_us, NOT ws_s)
# Better proxy: use existing g_mp_change_with (fire_us anchored). For V7 PW, we'd need
# to re-extract microprice from L25 books at ws_s, which is heavy. Defer; use the
# fire_us proxy as g_pw_mp_change_with substitute (it's pre-window-ish for early offsets).
log("layer: g_pw_mp_change_with — using fire_us proxy from existing g_mp_change_with")
# Already in fires as g_mp_change_with — copy as g_pw_mp_change_with alias for early offsets
fires['g_pw_mp_change_with'] = fires['g_mp_change_with']  # offset_early so fire_us ≈ ws_s+60s, close to ws_s
log(f"  g_pw_mp_change_with (proxy): ones={fires.g_pw_mp_change_with.sum()}")

# --- 6. V7 Path H: Hurst variants ---
# Need hurst data at fire_us. Check MGF v2 for hurst columns.
log("layer: Hurst + rv variants from master_gate_features_v2 (slug+fire_us join)")
try:
    mgf = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/master_gate_features_v2.parquet")
    mgf_eth = mgf[(mgf.asset == 'ETH') & (mgf.tf == '15m')].copy()
    # Dedup mgf_eth by (slug, fire_us) — should already be unique but force
    mgf_eth = mgf_eth.drop_duplicates(subset=['slug', 'fire_us'])
    keep_cols = ['slug', 'fire_us', 'hurst_900s', 'hurst_300s', 'hurst_100s', 'rv_60s', 'rv_900s', 'mp_skew_change_500ms']
    keep_cols = [c for c in keep_cols if c in mgf_eth.columns]
    mgf_eth = mgf_eth[keep_cols].copy()
    # Join on (slug, fire_us)
    fires = fires.merge(mgf_eth, on=['slug', 'fire_us'], how='left', suffixes=('', '_mgf'))
    log(f"  post-merge fires shape: {fires.shape}")
    if 'hurst_900s' in fires.columns:
        n_hurst = fires.hurst_900s.notna().sum()
        log(f"  hurst_900s joined: non-null={n_hurst}/{len(fires)}")
        hu = fires.hurst_900s.fillna(0.5)
        fires['g_hurst_strong_trending'] = (hu >= 0.65).astype(int)
        fires['g_hurst_reverting_strict'] = (hu < 0.40).astype(int)
        ts = fires['pw_trend_slope_30m_rg'] if 'pw_trend_slope_30m_rg' in fires.columns else pd.Series(np.zeros(len(fires)))
        fires['g_hurst_regime_with'] = ((hu > 0.55) &
            (((ts > 0) & (fires.direction == 'UP')) | ((ts < 0) & (fires.direction == 'DOWN')))).astype(int)
        log(f"  g_hurst_strong_trending: ones={fires.g_hurst_strong_trending.sum()}")
        log(f"  g_hurst_reverting_strict: ones={fires.g_hurst_reverting_strict.sum()}")
        log(f"  g_hurst_regime_with: ones={fires.g_hurst_regime_with.sum()}")
    if 'rv_60s' in fires.columns:
        n_rv = fires.rv_60s.notna().sum()
        log(f"  rv_60s joined: non-null={n_rv}/{len(fires)}")
        if n_rv > 0:
            rv = fires.rv_60s
            rv_med = rv.median()
            fires['g_vol_extreme_high'] = (rv > rv.quantile(0.90)).fillna(False).astype(int)
            fires['g_rv_60_above_med'] = (rv > rv_med).fillna(False).astype(int)
            fires['g_rv_60_below_med'] = (rv < rv_med).fillna(False).astype(int)
            log(f"  rv_60 median: {rv_med:.4f}")
            log(f"  g_vol_extreme_high: ones={fires.g_vol_extreme_high.sum()}")
    if 'mp_skew_change_500ms' in fires.columns:
        # Use mp_skew_change_500ms (this IS the 500ms microprice change feature)
        mpc = fires.mp_skew_change_500ms.fillna(0)
        fires['g_pw_mp_change_strong_with'] = (
            ((mpc > 5) & (fires.direction == 'UP')) | ((mpc < -5) & (fires.direction == 'DOWN'))
        ).astype(int)
        # Override the proxy with real data when available
        fires['g_pw_mp_change_real_with'] = (
            ((mpc > 0) & (fires.direction == 'UP')) | ((mpc < 0) & (fires.direction == 'DOWN'))
        ).astype(int)
        log(f"  g_pw_mp_change_strong_with: ones={fires.g_pw_mp_change_strong_with.sum()}")
        log(f"  g_pw_mp_change_real_with: ones={fires.g_pw_mp_change_real_with.sum()}")
except Exception as e:
    log(f"  MGF join FAILED: {e}")
    import traceback; traceback.print_exc()
    for c in ['g_hurst_strong_trending', 'g_hurst_reverting_strict', 'g_hurst_regime_with',
              'g_vol_extreme_high', 'g_rv_60_above_med', 'g_rv_60_below_med',
              'g_pw_mp_change_strong_with', 'g_pw_mp_change_real_with']:
        fires[c] = 0

# --- 8. V7 NEW: Stronger PW combos pre-defined ---
# Compound: g_pw_m1v_with AND g_pw_trend_slope_with
fires['g_pw_m1v_and_trend'] = (fires.g_pw_m1v_with & fires.g_pw_trend_slope_with).astype(int)
# Compound: g_pw_xa_unanimity_with AND g_pw_m1v_with
fires['g_pw_xa_and_m1v'] = (fires.g_pw_xa_unanimity_with & fires.g_pw_m1v_with).astype(int)
# Compound: 3 PWs (trend + m1v + xa) — likely VERY rare
fires['g_pw_triple_align'] = (
    fires.g_pw_trend_slope_with & fires.g_pw_m1v_with & fires.g_pw_xa_unanimity_with
).astype(int)
log(f"  g_pw_m1v_and_trend: ones={fires.g_pw_m1v_and_trend.sum()}")
log(f"  g_pw_xa_and_m1v: ones={fires.g_pw_xa_and_m1v.sum()}")
log(f"  g_pw_triple_align: ones={fires.g_pw_triple_align.sum()}")

# --- 9. Persist enriched V7 panel ---
gate_cols = [c for c in fires.columns if c.startswith('g_')]
v7_new = [c for c in gate_cols if (c.startswith('g_pw_m1v') or c.startswith('g_pw_xa') or
          c.startswith('g_pw_btc') or c.startswith('g_pw_mp_change') or
          c.startswith('g_hurst_strong') or c.startswith('g_hurst_reverting_strict') or
          c == 'g_hurst_regime_with' or c.startswith('g_vol_extreme') or c.startswith('g_rv_60') or
          c.startswith('g_pw_m1v_and') or c == 'g_pw_xa_and_m1v' or c == 'g_pw_triple_align')]
log(f"FINAL shape: {fires.shape} | total gates: {len(gate_cols)}")
log(f"NEW V7 gates: {len(v7_new)}")
for g in v7_new: log(f"  - {g}")

fires.to_parquet(f"{OUT}/eth_15m_enriched_v7.parquet", index=False)
log(f"WROTE eth_15m_enriched_v7.parquet")
log("DONE")
