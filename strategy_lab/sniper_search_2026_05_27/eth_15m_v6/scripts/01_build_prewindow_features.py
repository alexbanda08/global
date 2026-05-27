"""V6 ETH 15m — extend V5 enriched universe with pre-window features (ws_s anchor).

The V5 enriched panel already has ALL gates evaluated at fire_us. For V6 we need
to evaluate the SAME gate atoms at ws_s (= slot_start - 900s for 15m) to check:

  (a) Does the same gate stack still pass at the earlier anchor?
  (b) Do pre-window features add NEW alpha not captured by fire_us anchors?

We add:
  - Pre-window SMS gates (asof at ws_s): g_pw_markov_with, g_pw_rsi_extreme_with,
    g_pw_cvd_with, g_pw_multi_tf_align_with, g_pw_trend_strong_60
  - Pre-window regime: g_pw_trend_slope_with, g_pw_adx_strong, g_pw_atr_high
  - Pre-window F7 RSI: g_pw_f7_rsi_extreme_with (Wilder simple-mean, 14 closes back from ws_s)
  - Pre-window microprice change: NOT AVAILABLE (15m panel has no offset<60)
  - Causality sanity: gate_at_ws == gate_at_fire_us check on a sample
"""
import os, time, warnings, sys
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/eth_15m_v6"
os.makedirs(OUT, exist_ok=True)

# --- 1. Load V5 enriched (has all fire_us-anchored gates) ---
log("loading V5 enriched ETH 15m universe")
fires = pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/eth_15m/eth_15m_enriched.parquet")
fires = fires.sort_values('fire_us').reset_index(drop=True)
log(f"v5 enriched: {fires.shape}; gates: {sum(1 for c in fires.columns if c.startswith('g_'))}")

# v3 fires already include ws_s. Verify.
assert 'ws_s' in fires.columns
fires['ws_s_us'] = (fires['ws_s'] * 1_000_000).astype('int64')   # ws_s anchor in micros
fires['ws_s_m30_us'] = fires['ws_s_us'] - 30_000_000              # ws_s - 30s
fires['ws_s_m60_us'] = fires['ws_s_us'] - 60_000_000              # ws_s - 60s

log(f"sample ws_s vs fire_us deltas (s): {((fires.fire_us - fires.ws_s_us)/1e6).describe().to_dict()}")

# --- 2. Pre-window SMS (asof at ws_s) ---
log("layer: SMS at ws_s")
sms = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/sms_panel_15m_v2_fixed.parquet")
sms = sms[sms.asset=='ETH'].copy().sort_values('ts_us').reset_index(drop=True)
sms_cols = ['ts_us','rsi_14','cvd_sign','choch_buy','choch_sell','bos_buy','bos_sell',
            'trend_5m','trend_15m','trend_30m','trend_1h','trend_strength_pct','system_confidence']
sms_keep = sms[[c for c in sms_cols if c in sms.columns]].copy()
sms_keep.columns = ['pw_sms_ts_us'] + ['pw_' + c + '_sms' for c in sms_keep.columns if c != 'ts_us']
sms_keep = sms_keep.sort_values('pw_sms_ts_us')

# asof on ws_s_us
fires = pd.merge_asof(fires.sort_values('ws_s_us'), sms_keep,
                       left_on='ws_s_us', right_on='pw_sms_ts_us', direction='backward')
fires = fires.sort_values('fire_us').reset_index(drop=True)
fires['pw_sms_age_s'] = (fires.ws_s_us - fires.pw_sms_ts_us) / 1e6
log(f"  pw_sms age @ ws_s: mean={fires.pw_sms_age_s.mean():.1f}s | null={fires.pw_sms_ts_us.isna().sum()}")

# Build pw_ gates
ds = np.where(fires.direction == 'UP', 1, -1)
if 'pw_trend_15m_sms' in fires.columns:
    t15 = fires.pw_trend_15m_sms.fillna(0)
    fires['g_pw_markov_with'] = (((t15 > 0) & (fires.direction=='UP')) |
                                  ((t15 < 0) & (fires.direction=='DOWN'))).fillna(False).astype(int)
if 'pw_trend_1h_sms' in fires.columns and 'pw_trend_15m_sms' in fires.columns:
    t1h = fires.pw_trend_1h_sms.fillna(0); t15 = fires.pw_trend_15m_sms.fillna(0)
    fires['g_pw_multi_tf_align_with'] = ((((t1h > 0) & (t15 > 0)) & (fires.direction=='UP')) |
                                          (((t1h < 0) & (t15 < 0)) & (fires.direction=='DOWN'))).astype(int)
if 'pw_cvd_sign_sms' in fires.columns:
    cvd = fires.pw_cvd_sign_sms.fillna(0)
    fires['g_pw_cvd_with'] = (((cvd > 0) & (fires.direction=='UP')) |
                               ((cvd < 0) & (fires.direction=='DOWN'))).fillna(False).astype(int)
if 'pw_rsi_14_sms' in fires.columns:
    rsi = fires.pw_rsi_14_sms.fillna(50)
    fires['g_pw_rsi_oversold']   = (rsi < 30).astype(int)
    fires['g_pw_rsi_overbought'] = (rsi > 70).astype(int)
    fires['g_pw_rsi_extreme_with'] = (((rsi < 30) & (fires.direction=='UP')) |
                                       ((rsi > 70) & (fires.direction=='DOWN'))).astype(int)
if 'pw_trend_strength_pct_sms' in fires.columns:
    ts_st = fires.pw_trend_strength_pct_sms.fillna(0)
    fires['g_pw_trend_strong_60'] = (ts_st > 60).astype(int)
    fires['g_pw_trend_strong_80'] = (ts_st > 80).astype(int)

# --- 3. Pre-window regime panel (asof at ws_s) ---
log("layer: regime v2_fixed at ws_s")
rg = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
rg = rg[rg.asset=='ETH'].copy().sort_values('ts_us').reset_index(drop=True)
rg_cols = ['ts_us','trend_slope_30m','regime_label','regime_score',
           'adx_14','plus_di_14','minus_di_14','atr_14',
           'tr_ema_stack_score','realized_vol_60m','range_compression','bb_width_60s']
rg_keep = rg[[c for c in rg_cols if c in rg.columns]].copy()
rg_keep.columns = ['pw_rg_ts_us'] + ['pw_' + c + '_rg' for c in rg_keep.columns if c != 'ts_us']
rg_keep = rg_keep.sort_values('pw_rg_ts_us')
fires = pd.merge_asof(fires.sort_values('ws_s_us'), rg_keep,
                       left_on='ws_s_us', right_on='pw_rg_ts_us', direction='backward')
fires = fires.sort_values('fire_us').reset_index(drop=True)
fires['pw_rg_age_s'] = (fires.ws_s_us - fires.pw_rg_ts_us) / 1e6
log(f"  pw_rg age @ ws_s: mean={fires.pw_rg_age_s.mean():.1f}s | null={fires.pw_rg_ts_us.isna().sum()}")

# Build pre-window regime gates
ts = fires['pw_trend_slope_30m_rg']
fires['g_pw_trend_slope_with'] = np.where(ts.isna(), 0,
                                           ((ds > 0) & (ts > 0)) | ((ds < 0) & (ts < 0))).astype(int)
thr_pw = ts.abs().quantile(0.75)
fires['g_pw_trend_slope_strong_with'] = np.where(ts.isna(), 0,
                                                  ((ds > 0) & (ts > thr_pw)) | ((ds < 0) & (ts < -thr_pw))).astype(int)
fires['g_pw_adx_strong'] = (fires.pw_adx_14_rg.fillna(0) > 25).astype(int)
fires['g_pw_atr_high'] = (fires.pw_atr_14_rg > fires.pw_atr_14_rg.quantile(0.75)).astype(int)
fires['g_pw_bb_squeeze'] = (fires.pw_bb_width_60s_rg < fires.pw_bb_width_60s_rg.quantile(0.25)).astype(int)
log(f"  pre-window slope thr: {thr_pw:.4f}")

# --- 4. F7 RSI at ws_s — Wilder simple-mean from binance 1m closes ---
log("layer: F7 RSI at ws_s (Wilder simple-mean, 14-close lookback)")
try:
    sys.path.insert(0, f"{ROOT}/data/v4/canonical")
    from load import load_klines  # noqa
    k1m = load_klines('ETH', source='binance-spot-ws', period_id='1MIN')
    log(f"  loaded 1m klines: {len(k1m)}")
    k1m = k1m.sort_values('time_period_start_us').reset_index(drop=True)
    # Build close array indexed by minute_start_us
    k1m['minute_us'] = (k1m['time_period_start_us'] // (60 * 1_000_000)) * 60 * 1_000_000
    closes_map = k1m.set_index('minute_us')['price_close'].to_dict()
    minutes_sorted = np.array(sorted(closes_map.keys()))
    closes_sorted = np.array([closes_map[m] for m in minutes_sorted])

    def f7_rsi_at(ws_s_arr):
        """For each ws_s timestamp (in seconds), compute Wilder simple-mean RSI(14)
        on the 15 closes ending at ws_s (inclusive). Uses minute closes."""
        out = np.full(len(ws_s_arr), np.nan)
        for i, ws_s in enumerate(ws_s_arr):
            target_min = (int(ws_s) // 60) * 60 * 1_000_000  # floor to 1m
            # Find index in minutes_sorted of target_min
            idx = np.searchsorted(minutes_sorted, target_min, side='right') - 1
            if idx < 14:
                continue  # not enough history
            # 15 closes ending at idx
            cls = closes_sorted[idx-14:idx+1]  # 15 closes
            diffs = np.diff(cls)
            gains = np.where(diffs > 0, diffs, 0).sum() / 14
            losses = np.where(diffs < 0, -diffs, 0).sum() / 14
            if losses == 0:
                out[i] = 100.0
            else:
                rs = gains / losses
                out[i] = 100 - (100 / (1 + rs))
        return out

    fires['pw_f7_rsi_ws'] = f7_rsi_at(fires.ws_s.values)
    log(f"  pw_f7_rsi_ws: null={fires.pw_f7_rsi_ws.isna().sum()} | mean={fires.pw_f7_rsi_ws.mean():.1f}")
    rsi = fires.pw_f7_rsi_ws
    fires['g_pw_f7_rsi_oversold']   = (rsi < 30).fillna(False).astype(int)
    fires['g_pw_f7_rsi_overbought'] = (rsi > 70).fillna(False).astype(int)
    fires['g_pw_f7_rsi_extreme_with'] = (((rsi < 30) & (fires.direction=='UP')) |
                                          ((rsi > 70) & (fires.direction=='DOWN'))).fillna(False).astype(int)
    # Also: F7 RSI extreme "with" (trend-follow): high RSI + UP, low RSI + DOWN
    fires['g_pw_f7_rsi_momentum_with'] = (((rsi > 55) & (fires.direction=='UP')) |
                                           ((rsi < 45) & (fires.direction=='DOWN'))).fillna(False).astype(int)
    log(f"  g_pw_f7_rsi_extreme_with: {fires.g_pw_f7_rsi_extreme_with.sum()}/{len(fires)}")
    log(f"  g_pw_f7_rsi_momentum_with: {fires.g_pw_f7_rsi_momentum_with.sum()}/{len(fires)}")
except Exception as e:
    log(f"  F7 RSI build failed: {e}")
    import traceback; traceback.print_exc()
    fires['pw_f7_rsi_ws'] = np.nan
    fires['g_pw_f7_rsi_oversold'] = 0
    fires['g_pw_f7_rsi_overbought'] = 0
    fires['g_pw_f7_rsi_extreme_with'] = 0
    fires['g_pw_f7_rsi_momentum_with'] = 0

# --- 5. Causality sanity check: g_markov_with @ fire_us vs g_pw_markov_with @ ws_s ---
log("CAUSALITY CHECK — comparing same-feature evaluations at fire_us vs ws_s")
# Both gates use trend_15m from sms_panel. The fire_us anchor and ws_s anchor will
# pull DIFFERENT SMS rows (one bar apart in 15m), so they SHOULD differ in non-trivial
# cases. The point is: g_markov_with @ fire_us uses info up to fire_us (i.e. uses
# the close of the previous 15m bar = ws_s). g_pw_markov_with @ ws_s uses info up
# to ws_s (i.e. close of the 15m bar 2 steps before slot_start).
# These should match in MOST trending cases, but can differ at transitions. Lookahead
# would manifest as g_pw_markov_with > g_markov_with on trades that won — we report
# the agreement rate.
if 'g_markov_with' in fires.columns and 'g_pw_markov_with' in fires.columns:
    agree = (fires.g_markov_with == fires.g_pw_markov_with).mean()
    log(f"  agreement g_markov_with vs g_pw_markov_with: {agree:.4f}")

# --- 6. Composable stake-supports gate (replaces $250) ---
log("layer: g_book_supports_25 / g_book_supports_5 — proxy from entry_vwap")
# We don't have direct book depth. Use entry_vwap proxy: if entry_vwap is in
# [0.05, 0.95] AND fire_offset_s implies non-edge book, the book likely supports
# small stakes. For now: define as entry_vwap ∈ [0.05, 0.95] (sane range).
ev = fires.entry_vwap.fillna(0)
fires['g_book_supports_5']  = ((ev > 0.02) & (ev < 0.98)).astype(int)
fires['g_book_supports_25'] = ((ev > 0.05) & (ev < 0.95)).astype(int)
log(f"  g_book_supports_25 ones: {fires.g_book_supports_25.mean():.3f}")

# --- 7. VWAP-band gates (replace lottery-ticket avoidance) ---
fires['g_entry_vwap_in_10_65'] = ((ev > 0.10) & (ev < 0.65)).astype(int)
fires['g_entry_vwap_in_30_70'] = ((ev > 0.30) & (ev < 0.70)).astype(int)
fires['g_entry_vwap_favorite'] = ((ev > 0.40) & (ev < 0.60)).astype(int)  # 50/50ish

# --- 8. Time-of-day gates ---
fires['hour_utc'] = pd.to_datetime(fires.fire_us, unit='us', utc=True).dt.hour
fires['g_hod_european_morning'] = ((fires.hour_utc >= 7) & (fires.hour_utc <= 11)).astype(int)
fires['g_hod_us_morning']        = ((fires.hour_utc >= 13) & (fires.hour_utc <= 17)).astype(int)
fires['g_hod_overnight']         = ((fires.hour_utc >= 23) | (fires.hour_utc <= 5)).astype(int)

# --- 9. Direction columns ---
fires['g_dir_up']   = (fires.direction == 'UP').astype(int)
fires['g_dir_down'] = (fires.direction == 'DOWN').astype(int)

# --- 10. Save ---
gate_cols = [c for c in fires.columns if c.startswith('g_')]
log(f"FINAL shape: {fires.shape} | total gates: {len(gate_cols)}")
new_pw_gates = [c for c in gate_cols if c.startswith('g_pw_') or c in (
    'g_book_supports_5','g_book_supports_25','g_entry_vwap_in_10_65','g_entry_vwap_in_30_70',
    'g_entry_vwap_favorite','g_hod_european_morning','g_hod_us_morning','g_hod_overnight',
    'g_dir_up','g_dir_down')]
log(f"NEW V6 gates added: {len(new_pw_gates)}")
log(f"  list: {new_pw_gates}")

fires.to_parquet(f"{OUT}/eth_15m_enriched_v6.parquet", index=False)
log(f"WROTE eth_15m_enriched_v6.parquet ({len(fires)} rows, {len(fires.columns)} cols)")
log("DONE")
