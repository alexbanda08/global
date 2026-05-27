"""Derive sniper-search gates on _panel_sol_5m.parquet.

Atoms:
  R1 base (already in OOS): g_rf_with, g_ribbon_agrees, g_stoch_with, g_mfi_with,
    g_cci_with, g_bb_pos_with, g_tr_above_*, g_tr_stack_*, g_tight_ribbon, g_within_dev,
    g_dev_extreme, g_sms_*
  Microprice (joined): mp_skew, mp_up_dev_bps, mp_dn_dev_bps
  Regime (joined): regime_label, trend_slope_30m, adx_14, atr_14
  Vol/Hurst (joined): vh_g_hurst_*, vh_g_vol_*, rv_60s, hurst_300s
  SMS (joined): rsi_14, choch_buy/sell, bos_*

Derive NEW directional gates:
  g_mp_skew_with: mp_skew aligned with direction (UP -> skew > 0)
  g_mp_skew_strong_with: |mp_skew| >= 0.05 aligned with direction
  g_mp_no_extreme_50/100/150_with: dev_bps on bet side within threshold
  g_hod_active: in 9-21 UTC
  g_hod_late: 22-02 UTC
  g_hod_eu_morning: 7-11 UTC
  g_hod_us_afternoon: 17-21 UTC
  g_hod_quiet: 3-6 UTC
  g_compression_tight: ribbon_compression_bps < 1.0
  g_compression_extra_tight: < 0.5
  g_compression_loose: > 5
  g_stoch_extreme_with: stoch in (>80 UP / <20 DOWN)
  g_mfi_extreme_with: mfi in (>70 UP / <30 DOWN)
  g_cci_extreme_with: |cci|>100 aligned
  g_bb_pos_extreme_with: bb_pos > 0.8 (UP) / < 0.2 (DOWN)
  g_rf_full_align: rf_with + rf_strong
  g_rf_strict_align: rf_with + rf_strong + rf_in_band + rf_fresh
  g_tr_partial_stack_with: ema50 + ema200
  g_tr_full_stack_with: ema50+ema200+ema800
  g_ribbon_slope_strong: |ribbon_lead_slope_bps| >= 2 aligned
  g_ribbon_slope_very_strong: |>=5| aligned
  g_adx_strong: adx_14 >= 25
  g_adx_extreme: adx_14 >= 35
  g_trend_strong: |trend_slope_30m| >= 0.0001 (or similar) aligned
  g_atr_high: atr_14 above 70%-tile
  g_atr_low: below 30%-tile
  g_rsi_extreme_with: RSI_14 >70 (UP) / <30 (DOWN)
  g_rsi_overbought_with: >65 UP / <35 DOWN
  g_sms_choch_with: choch_buy=1 UP / choch_sell=1 DOWN
  g_sms_bos_with: bos_buy=1 UP / bos_sell=1 DOWN
  g_regime_trend: regime_label in trend bucket (encoded as int — check)
  g_regime_chop: chop bucket

Depth gates (from _depth_capacity_250):
  g_book_depth_supports_250_strict: shares_250 fully filled AND slip_bps <= 200
  g_book_depth_supports_250_loose: shares_250 fully filled AND slip_bps <= 300

Composite atoms (for high-bar stacks):
  g_R1_full: g_rf_with + g_ribbon_agrees + g_stoch_with + g_mfi_with + g_cci_with + g_bb_pos_with all = 1
  g_R1_majority_6: sum of R1 ≥ 6 / 7
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m")
t0 = time.time()

p = pd.read_parquet(OUT / "_panel_sol_5m.parquet")
depth = pd.read_parquet(OUT / "_depth_capacity_250.parquet")[['slug', 'fire_us', 'direction', 'shares_250', 'slip_bps_250', 'underfilled_250']]
p = p.merge(depth, on=['slug', 'fire_us', 'direction'], how='left')
print(f"Panel after depth merge: {len(p)} rows", flush=True)

def g_(s): return s.fillna(0).astype('int8')

dir_up = p['direction'] == 'UP'
dir_dn = p['direction'] == 'DOWN'

# --- Microprice ---
# mp_skew positive = UP token has more bid pressure
p['g_mp_skew_with'] = g_(((p['mp_skew'] > 0) & dir_up) | ((p['mp_skew'] < 0) & dir_dn))
p['g_mp_skew_strong_with'] = g_(((p['mp_skew'] >= 0.05) & dir_up) | ((p['mp_skew'] <= -0.05) & dir_dn))
p['g_mp_skew_extreme_with'] = g_(((p['mp_skew'] >= 0.10) & dir_up) | ((p['mp_skew'] <= -0.10) & dir_dn))

# Microprice dev on bet side
mp_side_dev = np.where(dir_up, p['mp_up_dev_bps'], p['mp_dn_dev_bps'])
p['g_mp_no_extreme_50'] = g_(pd.Series(np.abs(mp_side_dev) < 50, index=p.index))
p['g_mp_no_extreme_100'] = g_(pd.Series(np.abs(mp_side_dev) < 100, index=p.index))
p['g_mp_no_extreme_150'] = g_(pd.Series(np.abs(mp_side_dev) < 150, index=p.index))

# weighted dev
mp_wt_dev = np.where(dir_up, p['mp_up_weighted_dev_bps'], p['mp_dn_weighted_dev_bps'])
p['g_mp_wt_no_extreme_100'] = g_(pd.Series(np.abs(mp_wt_dev) < 100, index=p.index))

# mp_imbalance favors direction (positive = more bid on UP side)
p['g_mp_imbalance_with'] = g_(((p['mp_imbalance'] > 0) & dir_up) | ((p['mp_imbalance'] < 0) & dir_dn))
p['g_mp_imbalance_strong_with'] = g_(((p['mp_imbalance'] >= 0.2) & dir_up) | ((p['mp_imbalance'] <= -0.2) & dir_dn))

# --- HoD ---
dt = pd.to_datetime(p['fire_us'], unit='us')
hour = dt.dt.hour
p['g_hod_active'] = g_((hour >= 9) & (hour <= 21))
p['g_hod_late'] = g_((hour >= 22) | (hour <= 2))
p['g_hod_eu_morning'] = g_((hour >= 7) & (hour <= 11))
p['g_hod_us_afternoon'] = g_((hour >= 17) & (hour <= 21))
p['g_hod_us_morning'] = g_((hour >= 13) & (hour <= 16))
p['g_hod_quiet'] = g_((hour >= 3) & (hour <= 6))
p['g_hod_avoid_us'] = g_(~((hour >= 12) & (hour <= 21)))

# --- Compression ---
p['g_compression_tight'] = g_(p['ribbon_compression_bps'] < 1.0)
p['g_compression_extra_tight'] = g_(p['ribbon_compression_bps'] < 0.5)
p['g_compression_loose'] = g_(p['ribbon_compression_bps'] > 5.0)

# --- Indicator extremes with direction ---
p['g_stoch_extreme_with'] = g_(((p['stoch_k_60s'] > 80) & dir_up) | ((p['stoch_k_60s'] < 20) & dir_dn))
p['g_stoch_strong_with'] = g_(((p['stoch_k_60s'] > 70) & dir_up) | ((p['stoch_k_60s'] < 30) & dir_dn))
p['g_mfi_extreme_with'] = g_(((p['mfi_60s'] > 70) & dir_up) | ((p['mfi_60s'] < 30) & dir_dn))
p['g_mfi_strong_with'] = g_(((p['mfi_60s'] > 60) & dir_up) | ((p['mfi_60s'] < 40) & dir_dn))
p['g_cci_extreme_with'] = g_(((p['cci_60s'] > 100) & dir_up) | ((p['cci_60s'] < -100) & dir_dn))
p['g_cci_strong_with'] = g_(((p['cci_60s'] > 50) & dir_up) | ((p['cci_60s'] < -50) & dir_dn))
p['g_bb_pos_extreme_with'] = g_(((p['bb_pos_60s'] > 0.8) & dir_up) | ((p['bb_pos_60s'] < 0.2) & dir_dn))
p['g_bb_pos_strong_with'] = g_(((p['bb_pos_60s'] > 0.7) & dir_up) | ((p['bb_pos_60s'] < 0.3) & dir_dn))

# --- Range Filter strict ---
p['g_rf_full_align'] = g_((p['g_rf_with'] == 1) & (p['g_rf_strong'] == 1))
p['g_rf_strict_align'] = g_((p['g_rf_with'] == 1) & (p['g_rf_strong'] == 1) & (p['g_rf_in_band'] == 1) & (p['g_rf_fresh'] == 1))

# --- TR stack ---
p['g_tr_partial_stack_with'] = g_((p['g_tr_above_ema50'] == 1) & (p['g_tr_above_ema200'] == 1))
p['g_tr_full_stack_with'] = g_((p['g_tr_above_ema50'] == 1) & (p['g_tr_above_ema200'] == 1) & (p['g_tr_above_ema800'] == 1))

# --- Ribbon slope ---
p['g_ribbon_slope_strong'] = g_(((p['ribbon_lead_slope_bps'] > 2.0) & dir_up) | ((p['ribbon_lead_slope_bps'] < -2.0) & dir_dn))
p['g_ribbon_slope_very_strong'] = g_(((p['ribbon_lead_slope_bps'] > 5.0) & dir_up) | ((p['ribbon_lead_slope_bps'] < -5.0) & dir_dn))

# --- ADX/trend (from regime panel) ---
p['g_adx_strong'] = g_(p['adx_14'] >= 25)
p['g_adx_extreme'] = g_(p['adx_14'] >= 35)
p['g_adx_low'] = g_(p['adx_14'] < 20)
p['g_trend_slope_strong_with'] = g_(((p['trend_slope_30m'] > 0.0001) & dir_up) | ((p['trend_slope_30m'] < -0.0001) & dir_dn))
p['g_trend_slope_very_strong_with'] = g_(((p['trend_slope_30m'] > 0.0003) & dir_up) | ((p['trend_slope_30m'] < -0.0003) & dir_dn))

# --- ATR / Volatility ---
atr_q70 = p['atr_14'].quantile(0.70)
atr_q30 = p['atr_14'].quantile(0.30)
p['g_atr_high'] = g_(p['atr_14'] >= atr_q70)
p['g_atr_low'] = g_(p['atr_14'] <= atr_q30)

# --- SMS RSI ---
p['g_rsi_extreme_with'] = g_(((p['rsi_14'] > 70) & dir_up) | ((p['rsi_14'] < 30) & dir_dn))
p['g_rsi_overbought_with'] = g_(((p['rsi_14'] > 65) & dir_up) | ((p['rsi_14'] < 35) & dir_dn))
p['g_rsi_extreme_against'] = g_(((p['rsi_14'] > 70) & dir_dn) | ((p['rsi_14'] < 30) & dir_up))

# --- SMS structural ---
p['g_sms_choch_with'] = g_((p['choch_buy'].fillna(0) > 0) & dir_up | (p['choch_sell'].fillna(0) > 0) & dir_dn)
p['g_sms_bos_with'] = g_((p['bos_buy'].fillna(0) > 0) & dir_up | (p['bos_sell'].fillna(0) > 0) & dir_dn)

# --- Regime labels (need to inspect) ---
if 'regime_label' in p.columns:
    unique_labels = p['regime_label'].dropna().unique()
    print(f"regime_label values: {sorted(unique_labels.tolist())}", flush=True)
    # Encode common regime labels as gates
    for lbl in unique_labels:
        col = f'g_regime_{str(lbl).lower().replace(" ","_")}'
        p[col] = g_(p['regime_label'] == lbl)

# --- Vol/Hurst (already prefixed) ---
# vh_g_hurst_trending, vh_g_vol_low/med/high, etc

# --- Depth gates ---
p['g_depth_250_strict'] = g_((p['underfilled_250'] == 0) & (p['slip_bps_250'] <= 200))
p['g_depth_250_med'] = g_((p['underfilled_250'] == 0) & (p['slip_bps_250'] <= 300))
p['g_depth_250_loose'] = g_((p['underfilled_250'] == 0) & (p['slip_bps_250'] <= 500))

# --- R1 composite ---
r1_atoms = ['g_rf_with', 'g_ribbon_agrees', 'g_stoch_with', 'g_mfi_with', 'g_cci_with', 'g_bb_pos_with', 'g_tr_above_ema50']
present = [c for c in r1_atoms if c in p.columns]
p['g_R1_sum'] = p[present].fillna(0).astype(int).sum(axis=1)
p['g_R1_full'] = g_(p['g_R1_sum'] == len(present))
p['g_R1_six'] = g_(p['g_R1_sum'] >= 6)
p['g_R1_five'] = g_(p['g_R1_sum'] >= 5)

# --- Print inventory ---
gates = sorted([c for c in p.columns if c.startswith('g_')])
print(f"\nTotal gates: {len(gates)}")
for c in gates:
    if c == 'g_R1_sum': continue
    nz = int(p[c].fillna(0).astype(int).sum())
    print(f"  {c}: {nz} ({nz/len(p)*100:.1f}%)")

out = OUT / "_panel_sol_5m_gated.parquet"
p.to_parquet(out, index=False, compression='zstd')
print(f"\nWrote {out} ({os.path.getsize(out)/1024/1024:.1f} MB)")
print(f"Elapsed: {time.time()-t0:.1f}s")
