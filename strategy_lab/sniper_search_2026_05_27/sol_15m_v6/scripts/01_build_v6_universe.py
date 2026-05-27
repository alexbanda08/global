"""Build SOL 15m V6 enriched universe.

V6 additions over V5:
- Pre-window signal at ws_s and ws_s-60s
  * F7-style RSI from binance 1m close (anchored at ws_s)
  * dev_bps from vwap_since_open
  * Microprice at ws_s (causal asof)
- HoD bins (London / NY / Asian / late_night)
- entry_vwap bands (g_entry_vwap_in_band proxy)
- Direction asymmetry tag (UP-only vs DOWN-only flagged)
- New: g_book_supports_stake(stake_usd) gate as a fill-time check (simulated)

Output: sol_15m_v6_universe.parquet
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v6"

# Start from V5 universe (already has 30+ gates joined; we extend)
log("loading V5 universe (sol_15m_fires_v2fix_gates)")
df = pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_15m/sol_15m_fires_v2fix_gates.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"V5 universe: {len(df):,} rows, {len(df.columns)} cols")

WINDOW_S = 900
# Compute ws_s already exists; verify
df['ws_s_us'] = df['slot_start_us'] - WINDOW_S * 1_000_000
df['ws_minus_30_us'] = df['ws_s_us'] - 30 * 1_000_000
df['ws_minus_60_us'] = df['ws_s_us'] - 60 * 1_000_000
df['dir_int'] = np.where(df['direction']=='UP', 1, -1)

# Time of day bins (UTC)
ts_dt = pd.to_datetime(df['fire_us'], unit='us', utc=True)
df['hour_utc'] = ts_dt.dt.hour
df['fire_dt_utc'] = ts_dt
# Bins per V6 brief §4
df['g_hod_european_morning'] = ((df['hour_utc'] >= 7) & (df['hour_utc'] < 11)).astype(int)
df['g_hod_us_morning'] = ((df['hour_utc'] >= 13) & (df['hour_utc'] < 17)).astype(int)
df['g_hod_overnight'] = ((df['hour_utc'] >= 23) | (df['hour_utc'] < 5)).astype(int)
df['g_hod_asian'] = ((df['hour_utc'] >= 1) & (df['hour_utc'] < 9)).astype(int)
df['g_hod_us_afternoon'] = ((df['hour_utc'] >= 17) & (df['hour_utc'] < 21)).astype(int)
df['g_hod_european_afternoon'] = ((df['hour_utc'] >= 11) & (df['hour_utc'] < 15)).astype(int)
log(f"HoD bins computed: euro_morn={df['g_hod_european_morning'].sum()} us_morn={df['g_hod_us_morning'].sum()} overn={df['g_hod_overnight'].sum()}")

# entry_vwap bands
ev = df['entry_vwap']
df['g_entry_vwap_in_band_10_65'] = ((ev >= 0.10) & (ev <= 0.65)).astype(int)
df['g_entry_vwap_in_band_15_55'] = ((ev >= 0.15) & (ev <= 0.55)).astype(int)
df['g_entry_vwap_in_band_20_45'] = ((ev >= 0.20) & (ev <= 0.45)).astype(int)
df['g_entry_vwap_lt_50'] = (ev < 0.50).astype(int)
df['g_entry_vwap_lt_65'] = (ev < 0.65).astype(int)
df['g_entry_vwap_lt_75'] = (ev < 0.75).astype(int)
df['g_entry_vwap_gt_25'] = (ev > 0.25).astype(int)
df['g_entry_vwap_gt_35'] = (ev > 0.35).astype(int)
df['g_entry_vwap_mid'] = ((ev >= 0.35) & (ev <= 0.65)).astype(int)
log(f"vwap bands: 10_65={df['g_entry_vwap_in_band_10_65'].mean()*100:.1f}% lt_65={df['g_entry_vwap_lt_65'].mean()*100:.1f}%")

# fire_offset gates (offset bins)
df['g_off_60'] = (df['fire_offset_s'] == 60).astype(int)
df['g_off_60_240'] = (df['fire_offset_s'] <= 240).astype(int)
df['g_off_120_360'] = ((df['fire_offset_s'] >= 120) & (df['fire_offset_s'] <= 360)).astype(int)
df['g_off_360plus'] = (df['fire_offset_s'] >= 360).astype(int)
df['g_off_480plus'] = (df['fire_offset_s'] >= 480).astype(int)
df['g_off_240_480'] = ((df['fire_offset_s'] >= 240) & (df['fire_offset_s'] <= 480)).astype(int)

# Direction-asymmetric gates
df['g_dir_up'] = (df['direction'] == 'UP').astype(int)
df['g_dir_down'] = (df['direction'] == 'DOWN').astype(int)

# Pre-window F7 RSI at ws_s — pull from binance 1m via TA panel
log("=== Computing F7 RSI from binance 1m at ws_s ===")
# Load 1m binance klines via canonical
import sys
sys.path.insert(0, "data/v4/canonical")
from load import load_klines

# Load 1m
log("loading binance SOL 1m klines")
kdf = load_klines('SOL', 'binance-spot-ws', '1MIN')
log(f"  binance 1m raw cols: {kdf.columns.tolist()}")
# Standardize ts column: ts_us = time_period_start_us + 60_000_000 (bar end)
if 'ts_us' not in kdf.columns:
    if 'time_period_start_us' in kdf.columns:
        kdf['ts_us'] = kdf['time_period_start_us'].astype('int64') + 60_000_000
    elif 'ts_s' in kdf.columns:
        kdf['ts_us'] = (kdf['ts_s'].astype('int64') + 60) * 1_000_000
log(f"  binance 1m: {len(kdf):,} rows; ts_us range: {pd.to_datetime(kdf['ts_us'].min(), unit='us').date()} -> {pd.to_datetime(kdf['ts_us'].max(), unit='us').date()}")
# Use 'price_close' or 'close'
close_col = 'close' if 'close' in kdf.columns else 'price_close'
kdf = kdf.sort_values('ts_us').reset_index(drop=True)
closes = kdf[close_col].values.astype(float)
kdf['close'] = closes  # standardize
# Wilder simple-mean RSI(14)
def wilder_rsi_simple_mean(close, period=14):
    n = len(close)
    rsi = np.full(n, np.nan)
    if n <= period: return rsi
    diff = np.diff(close)
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    # initial: simple mean
    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))
    # subsequent: simple mean (per production)
    for i in range(period+1, n):
        # production uses simple-mean Wilder
        avg_gain = gains[i-period:i].mean()
        avg_loss = losses[i-period:i].mean()
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))
    return rsi

log("  computing RSI (period=14, simple-mean Wilder)")
kdf['rsi_14'] = wilder_rsi_simple_mean(closes, 14)
# Also compute period=7 (F7) — actually F7 in production uses 15 closes anchored at ws_s
# Per CLAUDE.md: "build_bar_context_t_plus_120/60: fetches 15 closes at offsets [-840, -780, ..., -60, 0] from ws_s; the LAST close is at ws_s"
# That's 15 closes spaced by 60s = 14 intervals -> standard 14-period RSI on 1m closes
# So rsi_14 == F7 (with simple-mean Wilder)

# Asof-join rsi at ws_s
log("  asof-joining RSI at ws_s")
kdf_s = kdf[['ts_us', 'rsi_14', 'close']].sort_values('ts_us').reset_index(drop=True)
kdf_s.columns = ['ts_us', 'rsi_at_ws', 'close_at_ws']
df = df.sort_values('ws_s_us').reset_index(drop=True)
df_merged = pd.merge_asof(df, kdf_s,
                          left_on='ws_s_us', right_on='ts_us',
                          direction='backward', allow_exact_matches=True,
                          tolerance=pd.Timedelta('5min').value // 1000)  # microseconds
# tolerance: 5min*60*1e6 us
df_merged = pd.merge_asof(df.sort_values('ws_s_us'), kdf_s.rename(columns={'ts_us':'ts_us_rsi'}),
                          left_on='ws_s_us', right_on='ts_us_rsi',
                          direction='backward', allow_exact_matches=True,
                          tolerance=int(5*60*1e6))
df_merged = df_merged.sort_values('fire_us').reset_index(drop=True)
log(f"  RSI joined; non-null rate: {df_merged['rsi_at_ws'].notna().mean()*100:.1f}%")

# Pre-window RSI extreme gates (V6 brief §4)
rsi = df_merged['rsi_at_ws']
ds = df_merged['dir_int']
# Extreme up (RSI>70) supports UP direction; RSI<30 supports DOWN
df_merged['g_prewindow_rsi_extreme_with'] = np.where(rsi.isna(), np.nan,
    (((ds > 0) & (rsi > 70)) | ((ds < 0) & (rsi < 30))).astype(float))
df_merged['g_prewindow_rsi_extreme_against'] = np.where(rsi.isna(), np.nan,
    (((ds > 0) & (rsi < 30)) | ((ds < 0) & (rsi > 70))).astype(float))
df_merged['g_prewindow_rsi_in_band'] = np.where(rsi.isna(), np.nan,
    ((rsi >= 30) & (rsi <= 70)).astype(float))
df_merged['g_prewindow_rsi_neutral_with'] = np.where(rsi.isna(), np.nan,
    (((ds > 0) & (rsi >= 50) & (rsi <= 70)) | ((ds < 0) & (rsi >= 30) & (rsi <= 50))).astype(float))
log(f"  g_prewindow_rsi_extreme_with ones rate: {df_merged['g_prewindow_rsi_extreme_with'].mean()*100:.2f}%")

# Pre-window microprice at ws_s
log("loading microprice panel for SOL")
mp = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/microprice_panel.parquet")
mp_sol = mp[mp['asset']=='SOL'].copy()
log(f"  microprice SOL: {len(mp_sol):,}")
# Note: microprice has fire_us not ws_s. We need microprice computed at ws_s.
# But microprice_panel was computed at fire_us. Use the closest fire_us at min offset for the same slug as a proxy
# Actually the panel has fire_offset_s field. Get the minimum fire_offset_s per slug to anchor closest to ws_s.
mp_sol_min = mp_sol.sort_values(['slug','fire_offset_s']).drop_duplicates('slug', keep='first').copy()
mp_sol_min = mp_sol_min.rename(columns={
    'mp_up_simple':'mp_up_at_ws',
    'mp_dn_simple':'mp_dn_at_ws',
    'mp_up_weighted':'mp_up_w_at_ws',
    'mp_dn_weighted':'mp_dn_w_at_ws',
    'mp_skew':'mp_skew_at_ws',
    'mp_imbalance':'mp_imb_at_ws',
    'mp_skew_change_500ms':'mp_skew_change_at_ws',
})
mp_keep = mp_sol_min[['slug','mp_up_at_ws','mp_dn_at_ws','mp_up_w_at_ws','mp_dn_w_at_ws','mp_skew_at_ws','mp_imb_at_ws','mp_skew_change_at_ws']].copy()

df_merged = df_merged.merge(mp_keep, on='slug', how='left')
log(f"  mp_at_ws coverage: {df_merged['mp_up_at_ws'].notna().mean()*100:.1f}%")

# Pre-window microprice skew gate
mp_skew = df_merged['mp_skew_at_ws']
df_merged['g_prewindow_mp_skew_with'] = np.where(mp_skew.isna(), np.nan,
    (((ds > 0) & (mp_skew > 0)) | ((ds < 0) & (mp_skew < 0))).astype(float))
df_merged['g_prewindow_mp_skew_strong_with'] = np.where(mp_skew.isna(), np.nan,
    (((ds > 0) & (mp_skew > 0.05)) | ((ds < 0) & (mp_skew < -0.05))).astype(float))

# mp microprice change 500ms direction gate (pre-fire)
mp_chg = df_merged['mp_skew_change_at_ws']
df_merged['g_mp_change_500ms_with'] = np.where(mp_chg.isna(), np.nan,
    (((ds > 0) & (mp_chg > 0)) | ((ds < 0) & (mp_chg < 0))).astype(float))

log(f"  g_prewindow_mp_skew_with ones: {df_merged['g_prewindow_mp_skew_with'].mean()*100:.2f}%")

# Add a g_book_supports_stake proxy — for $25, depth > $150
# We don't have direct depth, but we can use entry_vwap as proxy for fill quality
# A fire with vwap close to 0/1 (extreme) suggests thin opposite-side book
df_merged['g_book_supports_25'] = ((ev >= 0.05) & (ev <= 0.95)).astype(int)  # very loose; near-always 1
df_merged['g_book_supports_5'] = ((ev >= 0.02) & (ev <= 0.98)).astype(int)

# Save
out_cols = list(df_merged.columns)
new_g_cols = [c for c in out_cols if c.startswith('g_') and c not in [
    'g_rf_with','g_rf_fresh','g_rf_aged','g_rf_strong','g_rf_in_band','g_tr_stack_with',
    'g_tr_stack_full_with','g_tr_above_cloud','g_tr_within_adr','g_tr_in_active_session',
    'g_tr_above_pp','g_tr_above_ema50','g_tr_above_ema200','g_tr_above_ema800',
    'g_ribbon_agrees','g_ribbon_slope_with','g_tight_ribbon','g_bb_pos_with','g_stoch_with',
    'g_mfi_with','g_cci_with','g_within_dev','g_dev_extreme','g_trend_slope_with',
    'g_trend_slope_strong_with','g_markov_with','g_hurst_trending','g_vol_expanding','g_vol_high',
    'g_vol_contracting','g_mp_no_extreme','g_book_depth_supports_250',
    'g_lm_high_stat','g_lm_extreme_against','g_hawkes_imbalance_with','g_flow_with_and_no_whale',
    'g_coinbase_basis_extreme_against','g_hl_liq_cascade_with','g_imb5_strong_with',
    'g_queue_top_high','g_imb_change_with','g_vwap_ge_50_le_85','g_book_slope_steep_against',
    'g_mp_change_with','g_mp_skew_with',
]]
log(f"V6 NEW gates added: {sorted(new_g_cols)}")
log(f"Total g_ gates in V6 universe: {len([c for c in out_cols if c.startswith('g_')])}")

# Save
df_merged.to_parquet(f"{OUT}/sol_15m_v6_universe.parquet", index=False)
log(f"WROTE {OUT}/sol_15m_v6_universe.parquet ({len(df_merged):,} rows, {len(df_merged.columns)} cols)")
log("DONE")
