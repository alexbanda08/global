"""Build unified SOL 5m search universe.
Train: Apr 24 - May 13 (prefix_fires + early OOS) ~20 days
Val:   May 14 - May 20 (7 days from mgf v2 if needed... actually we don't have val fires)
Lockbox: May 21 - May 25 (4 days from oos_fires_v2_fixed)

We have these sources:
  - prefix_fires Apr 24-30 (7d) — has R1 atoms
  - oos_fires May 21-25 (4d) — has R1 atoms (v2_fixed = bug-fix corrected)
  - mgf v2 covers May 1-25 (25d) but is sleeve-filtered

So our raw fire universe is Apr 24-30 + May 21-25 = 11 days from prefix + oos.
That's not 28d but it IS what we have. We split:
  - Train: Apr 24 - Apr 30 (7d)
  - Val: May 21 - May 22 (2d)
  - Lockbox: May 23 - May 25 (3d)

Or more aligned with the brief's intent:
  - "Reference" (train+val): Apr 24 - Apr 30 (7d), accepted as train+val combined
  - "Lockbox" (out-of-sample): May 21 - May 25 (4d)

Per brief §2 the lockbox is the deciding metric. The full window 11d gives us
~50-500 n target → 5-45 fires/day on a sniper sleeve, achievable.

We also need to enrich with R3/R4/R5 features from microprice, vol_hurst etc.
"""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, ".")
import pandas as pd
import numpy as np
import time
from pathlib import Path

OUT = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\sniper_search_2026_05_27\sol_5m")
OUT.mkdir(exist_ok=True)

t0 = time.time()

# --- 1. Load + concat prefix + oos for SOL 5m ---
print("[1/5] Loading prefix_fires + oos_fires for SOL 5m...")
pf = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/prefix_fires.parquet")
oos = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_SOL_5m_v2_fixed.parquet")
pf_sol = pf[(pf['asset'] == 'SOL') & (pf['tf'] == '5m')].copy()
print(f"  prefix SOL 5m: {len(pf_sol)} rows, {pf_sol['fire_offset_s'].nunique()} offsets")
print(f"  oos SOL 5m:    {len(oos)} rows, {oos['fire_offset_s'].nunique()} offsets")

# Align columns: keep common only
common = sorted(set(pf_sol.columns) & set(oos.columns))
unified = pd.concat([pf_sol[common], oos[common]], ignore_index=True)
print(f"  Unified SOL 5m: {len(unified)} rows, {len(common)} cols")
print(f"  Date range: {pd.to_datetime(unified['fire_us'].min(), unit='us')} -> {pd.to_datetime(unified['fire_us'].max(), unit='us')}")

# --- 2. Enrich with mgf v2 gates (R3, R4, R5) ---
print("\n[2/5] Enriching with mgf v2 advanced gates (R3/R4/R5)...")
mgf = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
sol_mgf = mgf[(mgf['asset'] == 'SOL') & (mgf['tf'] == '5m')].copy()
print(f"  mgf v2 SOL 5m rows: {len(sol_mgf)}")
# extra gates (R3/R4/R5)
extra_gates = [
    'g_hurst_trending', 'g_hurst_reverting',
    'g_vol_expanding', 'g_vol_contracting', 'g_vol_high', 'g_book_slope_steep_against',
    'g_trend_slope_with', 'g_trend_slope_strong_with',
    'g_imb5_strong_with', 'g_queue_top_high', 'g_imb_change_with', 'g_vwap_ge_50_le_85',
    'g_mp_no_extreme', 'g_mp_change_with', 'g_mp_skew_with',
    'g_lm_high_stat', 'g_lm_extreme_against',
    'g_hawkes_imbalance_with', 'g_flow_with_and_no_whale',
    'g_coinbase_basis_extreme_against', 'g_hl_liq_cascade_with',
    'g_markov_with',
]
# also include features (so we can build new gates if needed)
extra_feats = [
    'f7_rsi_at_ws', 'mp_skew', 'mp_imbalance', 'mp_weighted_skew', 'mp_weighted_imbalance',
    'mp_up_dev_bps', 'mp_dn_dev_bps', 'mp_skew_change_500ms',
    'up_imb1', 'up_imb5', 'up_imb25', 'up_microprice', 'up_micro_dev_bps',
    'up_bid_slope', 'up_ask_slope', 'up_queue_top_bid', 'up_imb5_change_500ms',
    'up_quote_intensity_5s',
    'dn_imb1', 'dn_imb5', 'dn_imb25', 'dn_microprice', 'dn_micro_dev_bps',
    'rv_60s', 'rv_300s', 'rv_900s', 'rv_3600s', 'rv_ratio_60_to_3600', 'rv_pct_24h', 'vol_regime',
    'hurst_100s', 'hurst_300s', 'hurst_900s',
    'vpin_value', 'vpin_zscore', 'hawkes_lambda_total', 'hawkes_lambda_imbalance', 'hawkes_recent_burst',
    'as_uncertainty', 'as_skew',
    'mlofi_skew_l5_30s', 'mlofi_skew_l5_60s', 'mlofi_skew_l25_30s',
    'adx_14', 'plus_di_14', 'minus_di_14', 'atr_14',
    'trend_slope_30m', 'regime_label', 'regime_score',
    'choch_sell', 'choch_buy', 'bos_sell', 'bos_buy',
    'rsi_14', 'cvd', 'cvd_sign',
    'L_stat', 'is_jump_01', 'is_jump_05', 'jump_dir_01', 'jump_dir_05',
]
keep = ['slug', 'fire_us', 'direction'] + [c for c in extra_gates + extra_feats if c in sol_mgf.columns]
sol_mgf_slim = sol_mgf[keep].drop_duplicates(['slug', 'fire_us', 'direction'])
print(f"  mgf v2 slim: {len(sol_mgf_slim)} rows × {len(keep)} cols")

# Merge — use slug + fire_us + direction
unified_e = unified.merge(sol_mgf_slim, on=['slug', 'fire_us', 'direction'], how='left')
print(f"  After merge: {len(unified_e)} rows × {len(unified_e.columns)} cols")
# count enriched rows
enriched_count = unified_e['g_mp_no_extreme'].notna().sum() if 'g_mp_no_extreme' in unified_e.columns else 0
print(f"  Rows with mgf v2 enrichment: {enriched_count} ({enriched_count/len(unified_e)*100:.1f}%)")

# --- 3. Enrich with microprice panel (broader coverage than mgf) ---
print("\n[3/5] Enriching with microprice panel...")
mp = pd.read_parquet("data/v4/canonical/_results/microprice_panel.parquet")
sol_mp = mp[(mp['asset'] == 'SOL') & (mp['tf'] == '5m')].copy()
print(f"  microprice SOL 5m: {len(sol_mp)} rows")
mp_keep = ['slug', 'fire_us', 'mp_up_simple', 'mp_dn_simple', 'mp_up_weighted', 'mp_dn_weighted',
           'mp_up_dev_bps', 'mp_dn_dev_bps', 'mp_up_weighted_dev_bps', 'mp_dn_weighted_dev_bps',
           'up_mid_for_mp', 'dn_mid_for_mp']
mp_keep = [c for c in mp_keep if c in sol_mp.columns]
sol_mp_slim = sol_mp[mp_keep].drop_duplicates(['slug', 'fire_us'])
print(f"  mp slim: {len(sol_mp_slim)} rows")
# Merge — note no direction (microprice is per-fire not per-direction; we have both UP/DOWN cols)
# Use suffix to avoid collision with mgf enrichment
unified_e = unified_e.merge(sol_mp_slim, on=['slug', 'fire_us'], how='left', suffixes=('', '_mp'))
print(f"  After mp merge: {len(unified_e)} rows × {len(unified_e.columns)} cols")
mp_enriched = unified_e['mp_up_simple'].notna().sum()
print(f"  Rows with mp enrichment: {mp_enriched} ({mp_enriched/len(unified_e)*100:.1f}%)")

# --- 4. Add vol_hurst at fire (5m) ---
print("\n[4/5] Enriching with vol_hurst_at_fire_5m...")
vh = pd.read_parquet("data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")
sol_vh = vh[vh['asset'] == 'SOL'].copy()
print(f"  vol_hurst SOL 5m: {len(sol_vh)} rows")
vh_cols = [c for c in sol_vh.columns if c not in ('asset', 'slug', 'fire_us', 'fire_offset_s', 'outcome',
                                                    'tf', 'slot_start_us', 'slot_end_us', 'ws_s',
                                                    'strike_price', 'settle_price', 'vwap_since_open_bps',
                                                    'ret_2m_at_ws', 'mag_ratio', 'up_fill_ok', 'dn_fill_ok',
                                                    'up_vwap', 'up_shares', 'up_usd', 'dn_vwap', 'dn_shares',
                                                    'dn_usd', 'up_ask0', 'up_bid0', 'dn_ask0', 'dn_bid0',
                                                    'up_book_dt_us', 'dn_book_dt_us', 'prod_q90', 'row_id')]
# add a prefix to avoid collision
vh_keep = ['slug', 'fire_us'] + vh_cols
vh_keep = list(dict.fromkeys(vh_keep))  # dedup
sol_vh_slim = sol_vh[[c for c in vh_keep if c in sol_vh.columns]].drop_duplicates(['slug', 'fire_us'])
# rename to vh_*
rename = {c: f'vh_{c}' for c in sol_vh_slim.columns if c not in ('slug', 'fire_us')}
sol_vh_slim = sol_vh_slim.rename(columns=rename)
print(f"  vh slim: {len(sol_vh_slim)} rows × {len(sol_vh_slim.columns)} cols")
unified_e = unified_e.merge(sol_vh_slim, on=['slug', 'fire_us'], how='left')
print(f"  After vh merge: {len(unified_e)} rows × {len(unified_e.columns)} cols")

# --- 5. Persist ---
print("\n[5/5] Writing unified panel...")
out_path = OUT / "_unified_sol_5m.parquet"
unified_e.to_parquet(out_path, index=False, compression="zstd")
print(f"  Wrote {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")

# Summary
unified_e['dt'] = pd.to_datetime(unified_e['fire_us'], unit='us')
unified_e['day'] = unified_e['dt'].dt.date
print(f"\n=== UNIFIED PANEL SUMMARY ===")
print(f"Total fires: {len(unified_e)}")
print(f"Date range: {unified_e['dt'].min()} -> {unified_e['dt'].max()}")
print(f"Days covered: {unified_e['day'].nunique()}")
print(f"UP fires: {(unified_e['direction']=='UP').sum()}")
print(f"DOWN fires: {(unified_e['direction']=='DOWN').sum()}")
print(f"WR baseline: {unified_e['won'].mean():.4f}")
print(f"$/tr baseline: ${unified_e['pnl_legacy_usd'].mean():.3f}")
print(f"\nElapsed: {time.time()-t0:.1f}s")
