"""V8 ETH 15m — extend V7 enriched with NEW V8 paths J/K/L gates.

V8 brief priorities (eth_15m):
  - Path J: 2-asset confluence ensembles (BTC+SOL → ETH; 3-asset unanimity)
  - Path K: TOD bucket specialization (4 buckets per asset)
  - Path L: 1h grandparent regime (5m + 15m parent + 1h grandparent confluence)
  - Path M: offset=0 (V8 brief notes "when built — N/A this round, min offset in fires is 60s)

OUTPUT: eth_15m_enriched_v8.parquet (V7 cols + V8 path J/K/L gates)
"""
import os, time, warnings, sys
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v8"
os.makedirs(OUT, exist_ok=True)

# --- 1. Load V7 enriched (already has BTC trend slope + 3-asset RFs) ---
log("loading V7 enriched ETH 15m universe")
fires = pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/eth_15m_v7/eth_15m_enriched_v7.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
log(f"V7 enriched: {fires.shape}; gates: {sum(1 for c in fires.columns if c.startswith('g_'))}")
ds = np.where(fires.direction == 'UP', 1, -1)

# ============================================================
# PATH J — 2-asset confluence ensembles
# ============================================================
# V7 already has rf_dir_btc/eth/sol AT ws_s-30s and btc_trend_slope_30m AT ws_s
# Need: sol_trend_slope_30m AT ws_s (NEW for V8 to enable BTC+SOL → ETH confluence)

log("\n[Path J] Loading SOL 15m regime panel for sol_trend_slope_30m at ws_s")
rg = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
rg_sol = rg[rg.asset == 'SOL'][['ts_us', 'trend_slope_30m', 'regime_label']].copy().sort_values('ts_us').reset_index(drop=True)
rg_sol.columns = ['sol_rg_ts_us', 'sol_trend_slope_30m', 'sol_regime_label']
log(f"  SOL 15m regime rows: {len(rg_sol)}")
fires = pd.merge_asof(fires.sort_values('ws_s_us'), rg_sol,
                      left_on='ws_s_us', right_on='sol_rg_ts_us', direction='backward')
fires = fires.sort_values('fire_us').reset_index(drop=True)
sts = fires.sol_trend_slope_30m
log(f"  sol_trend_slope_30m non-null: {sts.notna().sum()}/{len(fires)}")

# Gate: g_pw_sol_15m_trend_with — SOL 15m trend aligned with fire direction
fires['g_pw_sol_15m_trend_with'] = np.where(sts.isna(), 0,
    ((sts > 0) & (fires.direction == 'UP')) | ((sts < 0) & (fires.direction == 'DOWN'))).astype(int)
sol_thr = sts.abs().quantile(0.75)
fires['g_pw_sol_15m_trend_strong_with'] = np.where(sts.isna(), 0,
    ((sts > sol_thr) & (fires.direction == 'UP')) | ((sts < -sol_thr) & (fires.direction == 'DOWN'))).astype(int)
log(f"  g_pw_sol_15m_trend_with: ones={fires.g_pw_sol_15m_trend_with.sum()}")
log(f"  g_pw_sol_15m_trend_strong_with: ones={fires.g_pw_sol_15m_trend_strong_with.sum()}")

# Path J — 2-asset confluence: BTC AND SOL both align with ETH direction
bts = fires.btc_trend_slope_30m
fires['g_2a_btc_sol_trend_with'] = (
    ((bts > 0) & (sts > 0) & (fires.direction == 'UP')) |
    ((bts < 0) & (sts < 0) & (fires.direction == 'DOWN'))
).fillna(False).astype(int)

# Path J — 3-asset trend unanimity (BTC + SOL + ETH parent trend ALL align)
# ETH parent = pw_trend_slope_30m_rg (already in fires)
ets = fires.pw_trend_slope_30m_rg
fires['g_3a_trend_unanimity_with'] = (
    ((bts > 0) & (sts > 0) & (ets > 0) & (fires.direction == 'UP')) |
    ((bts < 0) & (sts < 0) & (ets < 0) & (fires.direction == 'DOWN'))
).fillna(False).astype(int)

# Path J — 2-asset RF + 1-asset trend confluence: BTC RF AND SOL RF at ws_s-30s + ETH 15m trend
rb = fires['rf_dir_btc'].fillna(0)
rs = fires['rf_dir_sol'].fillna(0)
fires['g_2a_rf_btc_sol_with'] = (
    ((rb > 0) & (rs > 0) & (fires.direction == 'UP')) |
    ((rb < 0) & (rs < 0) & (fires.direction == 'DOWN'))
).astype(int)

# Path J — strict 3-asset RF + trend confluence (uses existing g_pw_xa_unanimity_with AND trend_slope)
# Combined gates: g_pw_xa_unanimity_with already exists, so create stack-friendly compound
fires['g_3a_rf_and_trend_with'] = (
    fires.g_pw_xa_unanimity_with & fires.g_pw_trend_slope_with
).astype(int)
log(f"  g_2a_btc_sol_trend_with: ones={fires.g_2a_btc_sol_trend_with.sum()}")
log(f"  g_3a_trend_unanimity_with: ones={fires.g_3a_trend_unanimity_with.sum()}")
log(f"  g_2a_rf_btc_sol_with: ones={fires.g_2a_rf_btc_sol_with.sum()}")
log(f"  g_3a_rf_and_trend_with: ones={fires.g_3a_rf_and_trend_with.sum()}")

# Path J — strong variant: 3-asset trend + |slope| > median
abs_b_med = fires.btc_trend_slope_30m.abs().median()
abs_s_med = fires.sol_trend_slope_30m.abs().median()
abs_e_med = fires.pw_trend_slope_30m_rg.abs().median()
fires['g_3a_trend_unanimity_strong_with'] = (
    fires.g_3a_trend_unanimity_with &
    (fires.btc_trend_slope_30m.abs() > abs_b_med) &
    (fires.sol_trend_slope_30m.abs() > abs_s_med) &
    (fires.pw_trend_slope_30m_rg.abs() > abs_e_med)
).fillna(False).astype(int)
log(f"  g_3a_trend_unanimity_strong_with: ones={fires.g_3a_trend_unanimity_strong_with.sum()}")

# ============================================================
# PATH K — Time-of-day systematic specialization
# ============================================================
log("\n[Path K] Building 4 TOD buckets")
# V6 had: g_hod_european_morning, g_hod_us_morning, g_hod_overnight
# V8 brief: 4 buckets:
#   asia_morning:     00-07 UTC
#   european_morning: 07-13 UTC
#   us_afternoon:     13-19 UTC
#   us_evening:       19-24 UTC
h = fires.hour_utc
fires['g_tod_asia']      = ((h >= 0)  & (h < 7)).astype(int)
fires['g_tod_european']  = ((h >= 7)  & (h < 13)).astype(int)
fires['g_tod_us_pm']     = ((h >= 13) & (h < 19)).astype(int)
fires['g_tod_us_eve']    = ((h >= 19) & (h < 24)).astype(int)
for k_ in ['g_tod_asia','g_tod_european','g_tod_us_pm','g_tod_us_eve']:
    log(f"  {k_}: ones={fires[k_].sum()} ({fires[k_].mean():.3f})")

# ============================================================
# PATH L — 1h grandparent regime
# ============================================================
# Build 1h ETH price slope from binance 1m klines (already in canonical via load_klines).
log("\n[Path L] Building 1h grandparent ETH regime from 1m klines")
sys.path.insert(0, f"{ROOT}/data/v4/canonical")
from load import load_klines

k1m = load_klines('ETH', period_id='1MIN')
k1m = k1m[['time_period_end_us','price_close']].copy().sort_values('time_period_end_us').reset_index(drop=True)
k1m['end_us'] = k1m.time_period_end_us.astype('int64')
# Resample to 1h bars: take last close in each hour
k1m['hour_idx'] = k1m.end_us // (3600 * 1_000_000)
k1h = k1m.groupby('hour_idx', as_index=False).agg(
    close_1h=('price_close','last'),
    end_us_max=('end_us','max')).sort_values('hour_idx').reset_index(drop=True)
k1h['ts_us'] = k1h.end_us_max
# Compute 1h trend slope: linear regression slope of last 4 closes (4h window)
log(f"  1h bars built: {len(k1h)}")
# rolling 4-period slope via diff (simpler): close[t] - close[t-4]
k1h['close_4h_ago'] = k1h.close_1h.shift(4)
k1h['trend_slope_4h'] = (k1h.close_1h - k1h.close_4h_ago) / k1h.close_4h_ago.replace(0, np.nan)
# Also a 1h slope (1-period diff)
k1h['close_1h_ago'] = k1h.close_1h.shift(1)
k1h['trend_slope_1h'] = (k1h.close_1h - k1h.close_1h_ago) / k1h.close_1h_ago.replace(0, np.nan)
# Regime label: trending_up if slope_4h > 0.002 (0.2%), trending_dn if < -0.002, else ranging
k1h['regime_1h_label'] = np.where(k1h.trend_slope_4h > 0.002, 'trending_up',
                          np.where(k1h.trend_slope_4h < -0.002, 'trending_dn', 'ranging'))
log(f"  1h regime label dist: {k1h.regime_1h_label.value_counts().to_dict()}")

# asof-join 1h regime onto fires at ws_s
k1h_keep = k1h[['ts_us','trend_slope_4h','trend_slope_1h','regime_1h_label']].copy()
k1h_keep.columns = ['eth_1h_ts_us','eth_trend_slope_4h','eth_trend_slope_1h','eth_regime_1h_label']
k1h_keep = k1h_keep.sort_values('eth_1h_ts_us')
fires = pd.merge_asof(fires.sort_values('ws_s_us'), k1h_keep,
                      left_on='ws_s_us', right_on='eth_1h_ts_us', direction='backward')
fires = fires.sort_values('fire_us').reset_index(drop=True)
log(f"  eth_trend_slope_4h non-null: {fires.eth_trend_slope_4h.notna().sum()}/{len(fires)}")

# Path L gates
e4h = fires.eth_trend_slope_4h
e1h = fires.eth_trend_slope_1h
elabel = fires.eth_regime_1h_label
fires['g_gp_1h_trend_with'] = np.where(e4h.isna(), 0,
    ((e4h > 0) & (fires.direction == 'UP')) | ((e4h < 0) & (fires.direction == 'DOWN'))).astype(int)
fires['g_gp_1h_trend_strong_with'] = (
    ((elabel == 'trending_up') & (fires.direction == 'UP')) |
    ((elabel == 'trending_dn') & (fires.direction == 'DOWN'))
).fillna(False).astype(int)
fires['g_gp_1h_slope_with'] = np.where(e1h.isna(), 0,
    ((e1h > 0) & (fires.direction == 'UP')) | ((e1h < 0) & (fires.direction == 'DOWN'))).astype(int)
# Strong: |4h slope| > 0.5% AND aligned
fires['g_gp_1h_trend_extreme_with'] = np.where(e4h.isna(), 0,
    ((e4h > 0.005) & (fires.direction == 'UP')) | ((e4h < -0.005) & (fires.direction == 'DOWN'))).astype(int)
# Ranging gate
fires['g_gp_1h_ranging'] = (elabel == 'ranging').fillna(False).astype(int)
log(f"  g_gp_1h_trend_with: ones={fires.g_gp_1h_trend_with.sum()}")
log(f"  g_gp_1h_trend_strong_with: ones={fires.g_gp_1h_trend_strong_with.sum()}")
log(f"  g_gp_1h_trend_extreme_with: ones={fires.g_gp_1h_trend_extreme_with.sum()}")
log(f"  g_gp_1h_slope_with: ones={fires.g_gp_1h_slope_with.sum()}")
log(f"  g_gp_1h_ranging: ones={fires.g_gp_1h_ranging.sum()}")

# Path L cascade: 1h gp aligned + 15m parent aligned + 5m fire direction
# 15m parent already represented by pw_trend_slope_30m_rg
# 5m alignment: ETH ws_s position vs daily VWAP — proxy via g_above_1h_dailyvwap_with
fires['g_cascade_5m_15m_1h_aligned'] = (
    fires.g_gp_1h_trend_with & fires.g_pw_trend_slope_with & fires.g_above_1h_dailyvwap_with
).astype(int)
fires['g_cascade_full_strong'] = (
    fires.g_gp_1h_trend_strong_with & fires.g_pw_trend_slope_with & fires.g_above_1h_dailyvwap_with
).astype(int)
log(f"  g_cascade_5m_15m_1h_aligned: ones={fires.g_cascade_5m_15m_1h_aligned.sum()}")
log(f"  g_cascade_full_strong: ones={fires.g_cascade_full_strong.sum()}")

# ============================================================
# Persist V8 enriched
# ============================================================
gate_cols = [c for c in fires.columns if c.startswith('g_')]
v8_new = [c for c in gate_cols if (
    c.startswith('g_pw_sol_15m') or c.startswith('g_2a_') or c.startswith('g_3a_')
    or c.startswith('g_tod_') or c.startswith('g_gp_') or c.startswith('g_cascade_'))]
log(f"\nFINAL shape: {fires.shape} | total gates: {len(gate_cols)} | V8 new: {len(v8_new)}")
for g in v8_new: log(f"  - {g}: ones={fires[g].sum()}")

fires.to_parquet(f"{OUT}/eth_15m_enriched_v8.parquet", index=False)
log(f"\nWROTE eth_15m_enriched_v8.parquet")
log("DONE")
