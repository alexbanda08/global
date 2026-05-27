"""Derive directional gates that have FULL coverage on SOL 5m unified panel.

Strategy:
  - R1 atoms: already there (100% coverage)
  - Microprice gates: build from mp_up_dev_bps / mp_dn_dev_bps (95.8% coverage)
  - SMS gates: g_sms_liq_reclaim_with, g_sms_no_liquidity_above already there
  - HoD / session: derive from fire_us
  - Cross-asset: skip for now (focus on SOL alone)
  - Volatility: use ribbon_compression_bps as proxy
  - F7 RSI: derive from rf_close history (would need klines) — skip for now

Add the following NEW gates:
  - g_mp_skew_with: micropip skew aligned with direction (already from mgf where available)
  - g_mp_no_extreme_50bps: mp dev < 50bps absolute
  - g_mp_no_extreme_100bps: mp dev < 100bps absolute (looser, R7 recommended)
  - g_mp_no_extreme_150bps: looser still
  - g_mp_skew_strong_with: mp_skew > 0.10 with direction
  - g_hod_active_session: in 9-21 UTC
  - g_hod_late: in 22-02 UTC (F2 pattern)
  - g_hod_eu_morning: 7-11 UTC
  - g_hod_us_afternoon: 17-21 UTC
  - g_compression_tight: ribbon_compression_bps < 1.0
  - g_compression_extra_tight: < 0.5
  - g_stoch_extreme_with: stoch_k_60s < 20 or > 80, with direction
  - g_mfi_extreme_with: mfi_60s < 30 or > 70, with direction
  - g_cci_extreme_with: |cci| > 100, with direction
  - g_bb_pos_extreme_with: bb_pos > 0.8 or < 0.2 with direction
  - g_rf_aligned_full: rf_with + rf_strong + rf_in_band
  - g_tr_full_stack_with: tr_above_ema50 + ema200 + ema800 all aligned
  - g_ribbon_strong: ribbon_lead_slope_bps > 2 or < -2 with direction
  - g_dev_bps_strong_with: dev with absolute value > 10
"""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
import time
from pathlib import Path

OUT = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\sniper_search_2026_05_27\sol_5m")
t0 = time.time()

u = pd.read_parquet(OUT / "_unified_sol_5m_full.parquet")
print(f"Loaded: {len(u)} rows, {len(u.columns)} cols")
n0 = len(u)
g = lambda s: s.fillna(False).astype('int8')

dir_up = u['direction'] == 'UP'
dir_dn = u['direction'] == 'DOWN'

# --- Microprice gates ---
if 'mp_up_dev_bps' in u.columns and 'mp_dn_dev_bps' in u.columns:
    # The "side-specific" microprice dev: for UP bet, use mp_up_dev_bps; for DOWN bet, use mp_dn_dev_bps
    mp_side_dev = np.where(dir_up, u['mp_up_dev_bps'], u['mp_dn_dev_bps'])
    u['g_mp_no_extreme_50'] = g(pd.Series(np.abs(mp_side_dev) < 50, index=u.index))
    u['g_mp_no_extreme_100'] = g(pd.Series(np.abs(mp_side_dev) < 100, index=u.index))
    u['g_mp_no_extreme_150'] = g(pd.Series(np.abs(mp_side_dev) < 150, index=u.index))
    # Microprice favors the direction (mp_up > mp_dn for UP bet means UP token is closer to fair)
    # mp_up_simple vs mp_dn_simple — UP bet wants mp_up > 0.50 favoring? Actually:
    #  mp_up = microprice of UP token. If mp_up > simple_mid_up, more bid pressure on UP token.
    # Define mp_skew_with as: bid pressure on bet side
    if 'mp_up_weighted' in u.columns and 'up_mid_for_mp' in u.columns:
        mp_up_signal = u['mp_up_weighted'] - u['up_mid_for_mp']  # positive = bid pressure on UP
        mp_dn_signal = u['mp_dn_weighted'] - u['dn_mid_for_mp']  # positive = bid pressure on DOWN
        # For UP bet: want mp_up_signal > 0 (buying UP token) and mp_dn_signal < 0 (selling DOWN)
        # Simplify: skew = mp_up_signal - mp_dn_signal; positive favors UP
        u['mp_dir_skew'] = mp_up_signal - mp_dn_signal
        u['g_mp_skew_with_raw'] = g(((u['mp_dir_skew'] > 0) & dir_up) | ((u['mp_dir_skew'] < 0) & dir_dn))
        u['g_mp_skew_strong_with'] = g(((u['mp_dir_skew'] > 0.005) & dir_up) | ((u['mp_dir_skew'] < -0.005) & dir_dn))

# --- Time-of-day gates ---
dt = pd.to_datetime(u['fire_us'], unit='us')
hour = dt.dt.hour
u['g_hod_active_session'] = g((hour >= 9) & (hour <= 21))
u['g_hod_late'] = g((hour >= 22) | (hour <= 2))
u['g_hod_eu_morning'] = g((hour >= 7) & (hour <= 11))
u['g_hod_us_afternoon'] = g((hour >= 17) & (hour <= 21))
u['g_hod_us_morning'] = g((hour >= 13) & (hour <= 16))
u['g_hod_quiet'] = g((hour >= 3) & (hour <= 6))

# --- Ribbon compression ---
if 'ribbon_compression_bps' in u.columns:
    u['g_compression_tight'] = g(u['ribbon_compression_bps'] < 1.0)
    u['g_compression_extra_tight'] = g(u['ribbon_compression_bps'] < 0.5)
    u['g_compression_loose'] = g(u['ribbon_compression_bps'] > 5.0)

# --- Indicator extremes with direction ---
if 'stoch_k_60s' in u.columns:
    u['g_stoch_extreme_with'] = g(((u['stoch_k_60s'] > 80) & dir_up) | ((u['stoch_k_60s'] < 20) & dir_dn))
    u['g_stoch_neutral'] = g((u['stoch_k_60s'] > 30) & (u['stoch_k_60s'] < 70))
if 'mfi_60s' in u.columns:
    u['g_mfi_extreme_with'] = g(((u['mfi_60s'] > 70) & dir_up) | ((u['mfi_60s'] < 30) & dir_dn))
    u['g_mfi_strong_with'] = g(((u['mfi_60s'] > 60) & dir_up) | ((u['mfi_60s'] < 40) & dir_dn))
if 'cci_60s' in u.columns:
    u['g_cci_extreme_with'] = g(((u['cci_60s'] > 100) & dir_up) | ((u['cci_60s'] < -100) & dir_dn))
    u['g_cci_strong_with'] = g(((u['cci_60s'] > 50) & dir_up) | ((u['cci_60s'] < -50) & dir_dn))
if 'bb_pos_60s' in u.columns:
    u['g_bb_pos_extreme_with'] = g(((u['bb_pos_60s'] > 0.8) & dir_up) | ((u['bb_pos_60s'] < 0.2) & dir_dn))
    u['g_bb_pos_strong_with'] = g(((u['bb_pos_60s'] > 0.7) & dir_up) | ((u['bb_pos_60s'] < 0.3) & dir_dn))

# --- Range Filter aligned ---
if all(c in u.columns for c in ['g_rf_with', 'g_rf_strong', 'g_rf_in_band']):
    u['g_rf_full_align'] = g((u['g_rf_with'] == 1) & (u['g_rf_strong'] == 1))
    u['g_rf_strict_align'] = g((u['g_rf_with'] == 1) & (u['g_rf_strong'] == 1) & (u['g_rf_in_band'] == 1) & (u['g_rf_fresh'] == 1))

# --- TR EMA full stack ---
if all(c in u.columns for c in ['g_tr_above_ema50', 'g_tr_above_ema200', 'g_tr_above_ema800']):
    u['g_tr_full_stack_with'] = g((u['g_tr_above_ema50'] == 1) & (u['g_tr_above_ema200'] == 1) & (u['g_tr_above_ema800'] == 1))
    u['g_tr_partial_stack_with'] = g((u['g_tr_above_ema50'] == 1) & (u['g_tr_above_ema200'] == 1))

# --- Ribbon slope strong ---
if 'ribbon_lead_slope_bps' in u.columns:
    u['g_ribbon_slope_strong'] = g(((u['ribbon_lead_slope_bps'] > 2.0) & dir_up) | ((u['ribbon_lead_slope_bps'] < -2.0) & dir_dn))
    u['g_ribbon_slope_very_strong'] = g(((u['ribbon_lead_slope_bps'] > 5.0) & dir_up) | ((u['ribbon_lead_slope_bps'] < -5.0) & dir_dn))

# --- Hawkes (only 6.4% coverage but useful where present) ---
if 'hk_lambda_imbalance' in u.columns:
    u['g_hawkes_with'] = g(((u['hk_lambda_imbalance'] > 0.1) & dir_up) | ((u['hk_lambda_imbalance'] < -0.1) & dir_dn))
    u['g_hawkes_strong_with'] = g(((u['hk_lambda_imbalance'] > 0.3) & dir_up) | ((u['hk_lambda_imbalance'] < -0.3) & dir_dn))
    u['g_hawkes_burst'] = g(u['hk_recent_burst'] > 0)

# --- Combined "all R1 with direction" gate ---
r1_with = ['g_rf_with', 'g_ribbon_agrees', 'g_stoch_with', 'g_mfi_with', 'g_cci_with',
           'g_bb_pos_with', 'g_tr_above_ema50']
present_r1 = [c for c in r1_with if c in u.columns]
if present_r1:
    u['g_r1_all_with'] = g(u[present_r1].sum(axis=1) == len(present_r1))
    u['g_r1_5_of_n'] = g(u[present_r1].sum(axis=1) >= 5)
    u['g_r1_6_of_n'] = g(u[present_r1].sum(axis=1) >= 6)
    print(f"  R1 atoms present: {len(present_r1)} ({present_r1})")

# Print gate inventory
new_gates = [c for c in u.columns if c.startswith('g_')]
print(f"\nGate inventory ({len(new_gates)}):")
for c in sorted(new_gates):
    nz = u[c].fillna(0).astype(int).sum()
    print(f"  {c}: {nz} ({nz/n0*100:.1f}%)")

out_path = OUT / "_unified_sol_5m_gated.parquet"
u.to_parquet(out_path, index=False, compression="zstd")
print(f"\nWrote {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
print(f"Elapsed: {time.time()-t0:.1f}s")
