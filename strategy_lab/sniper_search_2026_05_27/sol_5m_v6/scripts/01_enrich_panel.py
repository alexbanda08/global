"""V6: enrich V5 SOL 5m panel with master_gate_features_v2 + $25 depth + extras."""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m_v6")
t0 = time.time()

# --- Load V5 panel (already has microprice, regime, vol/hurst, SMS, 102 g_* cols) ---
base = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m/_panel_sol_5m_gated.parquet")
print(f"V5 base panel: {base.shape}")

# --- Load master_gate_features_v2 (Markov, F7 RSI, Hawkes, LM, MP no-extreme, etc.) ---
mgf = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
mgf_sol = mgf[(mgf['asset']=='SOL') & (mgf['tf']=='5m')].copy()
print(f"mgf SOL 5m rows: {len(mgf_sol)}; date range: {pd.to_datetime(mgf_sol.fire_us.min(),unit='us')} -> {pd.to_datetime(mgf_sol.fire_us.max(),unit='us')}")

# Gates to bring in from mgf (avoid collisions with V5 panel)
mgf_gate_cols = [
    'g_markov_with', 'g_lm_high_stat', 'g_lm_extreme_against',
    'g_hawkes_imbalance_with', 'g_mp_no_extreme', 'g_mp_change_with',
    'g_book_slope_steep_against', 'g_imb5_strong_with', 'g_queue_top_high',
    'g_imb_change_with', 'g_vwap_ge_50_le_85',
    'g_flow_with_and_no_whale', 'g_coinbase_basis_extreme_against',
    'g_hl_liq_cascade_with',
]
mgf_extra = ['f7_rsi_at_ws', 'cvd', 'cvd_sign', 'rsi_14', 'L_stat', 'is_jump_05',
             'hawkes_lambda_imbalance', 'vpin_value', 'vpin_zscore',
             'up_imb5', 'dn_imb5', 'up_microprice', 'dn_microprice',
             'up_quote_intensity_5s']
mgf_keep = ['slug', 'fire_us', 'fire_offset_s'] + mgf_gate_cols + mgf_extra
mgf_keep = [c for c in mgf_keep if c in mgf_sol.columns]
mgf_sub = mgf_sol[mgf_keep].drop_duplicates(subset=['slug', 'fire_us', 'fire_offset_s'])
# Rename gates to mgf_g_ prefix to avoid collisions
ren = {c: ('mgf_' + c) for c in mgf_gate_cols if c in mgf_sub.columns}
mgf_sub = mgf_sub.rename(columns=ren)
p1 = base.merge(mgf_sub, on=['slug', 'fire_us', 'fire_offset_s'], how='left')
print(f"after mgf join: {p1.shape}; markov coverage: {p1['mgf_g_markov_with'].notna().sum()/len(p1)*100:.1f}%")

# --- Build $25 depth gate from existing depth file (vwap_25 already there) ---
dep = pd.read_parquet("strategy_lab/sniper_search_2026_05_27/sol_5m/_depth_capacity_250.parquet")
# Build a $25 fill viability check: vwap_25 valid (<0.998) means full fill at $25
dep['g_book_depth_supports_25'] = ((dep['vwap_25'] > 0) & (dep['vwap_25'] < 0.998)).astype('int8')
# slip_25 not in file; build proxy: ratio vwap_25 vs current entry_vwap (entry_vwap is from L25 walk too)
# Just check fill validity
dep_keep = ['slug', 'fire_us', 'direction', 'vwap_25', 'g_book_depth_supports_25']
dep_sub = dep[dep_keep].drop_duplicates(subset=['slug', 'fire_us', 'direction'])
p2 = p1.merge(dep_sub, on=['slug', 'fire_us', 'direction'], how='left')
p2['g_book_depth_supports_25'] = p2['g_book_depth_supports_25'].fillna(0).astype('int8')
print(f"$25 depth gate pass rate: {p2['g_book_depth_supports_25'].mean():.3f}")

# --- New V6 composable atoms ---
# Conviction-style time-of-day
p2['hour'] = pd.to_datetime(p2['fire_us'], unit='us').dt.hour
p2['g_hod_european_morning'] = ((p2['hour'] >= 7) & (p2['hour'] < 11)).astype('int8')
p2['g_hod_us_morning_v6'] = ((p2['hour'] >= 13) & (p2['hour'] < 17)).astype('int8')
p2['g_hod_overnight'] = ((p2['hour'] >= 23) | (p2['hour'] < 5)).astype('int8')
p2['g_hod_avoid_us_pm'] = ((p2['hour'] < 17) | (p2['hour'] >= 21)).astype('int8')

# Entry vwap bands (avoid lottery + heavy favorites)
p2['g_vwap_in_25_60'] = ((p2['entry_vwap'] >= 0.25) & (p2['entry_vwap'] <= 0.60)).astype('int8')
p2['g_vwap_in_40_70'] = ((p2['entry_vwap'] >= 0.40) & (p2['entry_vwap'] <= 0.70)).astype('int8')
p2['g_vwap_in_55_80'] = ((p2['entry_vwap'] >= 0.55) & (p2['entry_vwap'] <= 0.80)).astype('int8')
p2['g_vwap_in_30_75'] = ((p2['entry_vwap'] >= 0.30) & (p2['entry_vwap'] <= 0.75)).astype('int8')
p2['g_vwap_in_45_85'] = ((p2['entry_vwap'] >= 0.45) & (p2['entry_vwap'] <= 0.85)).astype('int8')

# Strict early offset (V6 priority)
p2['g_offset_le_60'] = (p2['fire_offset_s'] <= 60).astype('int8')
p2['g_offset_le_90'] = (p2['fire_offset_s'] <= 90).astype('int8')
p2['g_offset_30_only'] = (p2['fire_offset_s'] == 30).astype('int8')
p2['g_offset_60_only'] = (p2['fire_offset_s'] == 60).astype('int8')

# Pre-window microprice movement (already have mp_skew/imb_change_500ms)
# g_mp_skew_with_dir: skew sign aligned with dir
p2['_dir_sign'] = np.where(p2['direction']=='UP', 1, -1)
if 'mp_weighted_skew' in p2.columns:
    p2['g_mp_wt_skew_with'] = ((p2['mp_weighted_skew'].fillna(0) * p2['_dir_sign']) > 0).astype('int8')
if 'mp_skew_change_500ms' in p2.columns:
    p2['g_mp_skew_change_with'] = ((p2['mp_skew_change_500ms'].fillna(0) * p2['_dir_sign']) > 0).astype('int8')

# F7 RSI extreme matching direction (pre-window)
if 'f7_rsi_at_ws' in p2.columns:
    p2['g_f7_rsi_overbought'] = (p2['f7_rsi_at_ws'] > 70).fillna(False).astype('int8')
    p2['g_f7_rsi_oversold'] = (p2['f7_rsi_at_ws'] < 30).fillna(False).astype('int8')
    p2['g_f7_rsi_with'] = (
        ((p2['_dir_sign'] == 1) & p2['g_f7_rsi_oversold'].astype(bool)) |
        ((p2['_dir_sign'] == -1) & p2['g_f7_rsi_overbought'].astype(bool))
    ).astype('int8')
    p2['g_f7_rsi_extreme_against'] = (
        ((p2['_dir_sign'] == 1) & p2['g_f7_rsi_overbought'].astype(bool)) |
        ((p2['_dir_sign'] == -1) & p2['g_f7_rsi_oversold'].astype(bool))
    ).astype('int8')

# CVD aligned
if 'cvd_sign' in p2.columns:
    p2['g_cvd_with'] = ((p2['cvd_sign'].fillna(0) * p2['_dir_sign']) > 0).astype('int8')

# up vs dn imb5 favor BET dir (book microstructure aligned)
if 'up_imb5' in p2.columns and 'dn_imb5' in p2.columns:
    p2['_bet_imb'] = np.where(p2['direction']=='UP', p2['up_imb5'].fillna(0), p2['dn_imb5'].fillna(0))
    p2['_off_imb'] = np.where(p2['direction']=='UP', p2['dn_imb5'].fillna(0), p2['up_imb5'].fillna(0))
    p2['g_bet_imb_strong'] = (p2['_bet_imb'] > 0.05).astype('int8')
    p2['g_bet_imb_dominant'] = ((p2['_bet_imb'] - p2['_off_imb']) > 0.10).astype('int8')

# Drop helper cols (avoid leaking into search)
for c in ['_dir_sign', '_bet_imb', '_off_imb', 'hour']:
    if c in p2.columns:
        p2 = p2.drop(columns=[c])

# Convert NaN gate values to 0 for boolean atoms
for c in p2.columns:
    if c.startswith('g_') or c.startswith('mgf_g_'):
        try:
            p2[c] = pd.to_numeric(p2[c], errors='coerce').fillna(0).astype('int8')
        except Exception:
            pass

# Final
print(f"\nFinal V6 panel: {p2.shape}")
print(f"  total g_* atoms: {sum(1 for c in p2.columns if c.startswith('g_') or c.startswith('mgf_g_'))}")
print(f"  date range: {pd.to_datetime(p2.fire_us.min(),unit='us')} -> {pd.to_datetime(p2.fire_us.max(),unit='us')}")

out_path = OUT / "_panel_sol_5m_v6.parquet"
p2.to_parquet(out_path, index=False, compression='zstd')
print(f"\nWrote {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
print(f"Elapsed: {time.time()-t0:.1f}s")
