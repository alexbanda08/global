"""mgf v2 is sleeve-specific. We need universal SOL fires panel for search.
Strategy: use OOS fires v2_fixed for lockbox, and we need TRAIN/VAL from the broader window.
Option A: use master_gate_features_v2 SOL slice (covers May 1-25). Both UP+DOWN.
Option B: use prefix_fires (Apr 24-30) for train.

Let me check what mgf v2 actually has for SOL when we look at directions and unique sleeves.
The key question: is mgf v2 a UNIVERSAL panel (every offset, every direction available)?
"""
import sys, os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np

mgf = pd.read_parquet("data/v4/canonical/_results/master_gate_features_v2.parquet")
sol = mgf[(mgf['asset'] == 'SOL') & (mgf['tf'] == '5m')].copy()

# Check if mgf has same slug+offset+direction combos as OOS fires in the May 21-25 window
oos = pd.read_parquet("data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_SOL_5m_v2_fixed.parquet")
oos_keys = set(zip(oos['slug'], oos['fire_offset_s'], oos['direction']))
print(f"OOS unique (slug,offset,direction): {len(oos_keys)}")

# Filter mgf to same window
sol_inwin = sol[(sol['fire_us'] >= oos['fire_us'].min()) & (sol['fire_us'] <= oos['fire_us'].max())]
mgf_keys = set(zip(sol_inwin['slug'], sol_inwin['fire_offset_s'], sol_inwin['direction']))
print(f"mgf v2 in OOS window unique keys: {len(mgf_keys)}")
print(f"Overlap: {len(oos_keys & mgf_keys)}")
print(f"In mgf only: {len(mgf_keys - oos_keys)}")
print(f"In OOS only: {len(oos_keys - mgf_keys)}")

# So mgf v2 is a SUBSET that already passes sleeve gates. It's not universal.
# For sniper search, we need universal universe with gates COMPUTED at fire time.
# The OOS fires panel has gates built-in for the lockbox.
# For train/val, we need the same kind of panel. Let me check hybrid_features_5m more carefully.

hf = pd.read_parquet("data/v4/canonical/_results/hybrid_features_5m.parquet")
sol_hf = hf[hf['asset'] == 'SOL'].copy()
print(f"\nhybrid_features_5m SOL: {len(sol_hf)}")
# what is direction in hybrid?
print("'direction' in hf cols:", 'direction' in sol_hf.columns)
print("'won' in hf cols:", 'won' in sol_hf.columns)
print("'pnl_legacy_usd' in hf cols:", 'pnl_legacy_usd' in sol_hf.columns)
# what kind of records?
print("Slugs unique:", sol_hf['slug'].nunique())
print("offset bins (each slug presumably has all offsets):")
print(sol_hf.groupby('slug')['fire_offset_s'].nunique().value_counts().head())
# this is per (slug, offset) — both UP+DOWN derived as needed

# OK so hf has one row per (slug, offset). To get both UP/DOWN PnL we'd need to derive it.
# Check if up_fill_ok / dn_fill_ok give us this
print("\nup_fill_ok/dn_fill_ok present?")
print(sol_hf[['up_fill_ok', 'dn_fill_ok', 'up_vwap', 'dn_vwap', 'up_shares', 'dn_shares']].head())
print("outcome col:", sol_hf['outcome'].value_counts() if 'outcome' in sol_hf.columns else "no")
