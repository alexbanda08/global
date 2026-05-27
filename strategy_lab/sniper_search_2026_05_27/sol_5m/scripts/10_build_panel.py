"""Build unified sniper-search panel for SOL 5m.

Joins OOS fires (101,500) with:
  - microprice_panel (31.7d coverage, slug+fire_us+fire_offset_s)
  - regime_panel_5m_v2_fixed (28d coverage, slot_start_us)
  - vol_hurst_at_fire_5m (23d coverage, slug+fire_us)
  - sms_panel_5m_v2_fixed (22d, slot_start_us)

Outputs `_panel_sol_5m.parquet` ready for combinatorial gate search.
"""
import os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path("strategy_lab/sniper_search_2026_05_27/sol_5m")
t0 = time.time()

# --- Load OOS fires ---
oos = pd.read_parquet("data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_5m_full_v3.parquet")
print(f"OOS fires loaded: {len(oos)} rows, {len(oos.columns)} cols")

# Add date column
oos['date'] = pd.to_datetime(oos['fire_us'], unit='us').dt.date

# --- Join microprice (full 31.7d) ---
mp = pd.read_parquet("data/v4/canonical/_results/microprice_panel.parquet")
mp_sol = mp[(mp['asset']=='SOL') & (mp['tf']=='5m')].copy()
mp_keep = ['slug', 'fire_us', 'fire_offset_s',
           'mp_up_dev_bps', 'mp_dn_dev_bps', 'mp_up_weighted_dev_bps', 'mp_dn_weighted_dev_bps',
           'mp_skew', 'mp_imbalance', 'mp_weighted_skew', 'mp_weighted_imbalance',
           'mp_up_dev_change_500ms', 'mp_dn_dev_change_500ms', 'mp_skew_change_500ms']
mp_sub = mp_sol[mp_keep].drop_duplicates(subset=['slug', 'fire_us', 'fire_offset_s'])
print(f"  microprice rows: {len(mp_sub)}")
p1 = oos.merge(mp_sub, on=['slug', 'fire_us', 'fire_offset_s'], how='left')
print(f"  after MP join: {len(p1)} rows; MP coverage: {p1['mp_skew'].notna().sum()/len(p1)*100:.1f}%")

# --- Join regime_panel_5m_v2_fixed ---
# Regime panel ts_us = slot_END - 1us. A row with ts_s = T-1 covers the bar [T-300, T).
# LEAKAGE FIX: regime values are computed at bar CLOSE. Fire at slot_start + offset is INSIDE the
# 5-min bar that starts at slot_start. So we must use the PRIOR bar's regime (the one that ended
# at slot_start). Shift forward: bar covering [T-300, T) becomes the gate for fires at [T, T+300).
rg = pd.read_parquet("data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet")
rg_sol = rg[rg['asset']=='SOL'].copy()
# The bar that ENDS at slot_start has ts_s = (slot_start_seconds - 1). Map join to next bar's slot_start:
rg_sol['join_slot_us'] = (rg_sol['ts_s'] + 1) * 1_000_000  # this is the slot_start of the FOLLOWING bar
rg_keep = ['join_slot_us', 'adx_14', 'plus_di_14', 'minus_di_14', 'atr_14',
           'tr_ema_stack_score', 'ribbon_alignment_pct', 'bb_width_60s',
           'realized_vol_60m', 'range_compression', 'trend_slope_30m',
           'regime_label', 'regime_score']
rg_sub = rg_sol[rg_keep].rename(columns={'join_slot_us': 'slot_start_us'})
p2 = p1.merge(rg_sub, on='slot_start_us', how='left')
print(f"  after regime join: {len(p2)} rows; regime coverage: {p2['regime_label'].notna().sum()/len(p2)*100:.1f}%")

# --- Join vol_hurst (23d) ---
vh = pd.read_parquet("data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")
vh_sol = vh[vh['asset']=='SOL'].copy()
vh_keep = ['slug', 'fire_us', 'rv_60s', 'rv_300s', 'rv_900s', 'rv_3600s',
           'rv_ratio_60_to_3600', 'rv_pct_24h', 'vol_regime', 'gk_sigma', 'gk_sigma_ma12',
           'hurst_100s', 'hurst_300s', 'hurst_900s',
           'g_vol_low', 'g_vol_med', 'g_vol_high', 'g_hurst_trending',
           'g_hurst_reverting', 'g_vol_expanding', 'g_vol_contracting']
vh_sub = vh_sol[vh_keep].drop_duplicates(subset=['slug', 'fire_us'])
# Prefix vh gates so they don't collide
vh_sub = vh_sub.rename(columns={c: f'vh_{c}' for c in vh_sub.columns if c.startswith('g_') or c == 'vol_regime'})
p3 = p2.merge(vh_sub, on=['slug', 'fire_us'], how='left')
print(f"  after vol_hurst join: {len(p3)} rows; vh coverage: {p3['rv_60s'].notna().sum()/len(p3)*100:.1f}%")

# --- Join SMS panel (22d) ---
# LEAKAGE FIX: SMS row at slot_start_us = T contains bos_buy/choch_buy detected on the bar
# STARTING at T (ending at T+300s). When we fire INSIDE that bar (at T + 30..270s), reading
# the current row's bos_buy is lookahead. SHIFT by 1 bar: at fire time T+offset, use SMS row
# whose slot_start_us = T - 300 (i.e. the PREVIOUS bar that already closed).
sms = pd.read_parquet("data/v4/canonical/_results/sms_panel_5m_v2_fixed.parquet")
sms_sol = sms[sms['asset']=='SOL'].copy()
sms_sol['join_slot_us'] = sms_sol['slot_start_us'] + 300 * 1_000_000  # shift forward by 1 bar so it joins to NEXT bar's fires
sms_keep = ['join_slot_us', 'rsi_14', 'rsi_bullish_div', 'choch_buy', 'choch_sell',
            'bos_buy', 'bos_sell', 'bars_since_bos_buy', 'bars_since_bos_sell',
            'bars_since_choch_buy', 'bars_since_choch_sell']
sms_sub = sms_sol[sms_keep].drop_duplicates(subset=['join_slot_us']).rename(columns={'join_slot_us':'slot_start_us'})
p4 = p3.merge(sms_sub, on='slot_start_us', how='left')
print(f"  after SMS join (shifted +1 bar to avoid leakage): {len(p4)} rows; SMS coverage: {p4['rsi_14'].notna().sum()/len(p4)*100:.1f}%")

print(f"\nTotal cols: {len(p4.columns)}; final shape: {p4.shape}")
print(f"Sleeve preview:")
print(p4[['won', 'pnl_legacy_usd']].agg(['mean', 'sum', 'count']))

# Cast g_* to int8 if not already
for c in p4.columns:
    if c.startswith('g_'):
        p4[c] = p4[c].fillna(0).astype('int8')

out_path = OUT / "_panel_sol_5m.parquet"
p4.to_parquet(out_path, index=False, compression='zstd')
print(f"\nWrote {out_path} ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
print(f"Elapsed: {time.time()-t0:.1f}s")
