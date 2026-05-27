"""V7 build: extend BTC 15m gated panel with NEW gates for V7 paths H, G, D.

Adds:
- hurst variants (g_hurst_strong_trending, g_hurst_reverting_strict)
- vol regime tags (g_vol_lo, g_vol_md, g_vol_hi via rv_60s tercile on train)
- slot-end OFI proxy (only valid at offset=840 since slot_end = ws_s + 900 = fire+60s for off=840)
  Proxy: use mp_skew_change_500ms direction-aligned in last second before fire (close to slot end)
- pre-window directional features (g_ret_2m_with — ret_2m_at_ws aligned with direction)
- vwap-bucket gates for use in straddle scoring

Output: data/v4/canonical/_results/sniper_btc15m_v7_gated.parquet
"""
import os, sys, time
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
IN = f"{RES}/sniper_btc15m_v3_gated.parquet"
VH = f"{RES}/vol_hurst_at_fire_15m.parquet"
OUT = f"{RES}/sniper_btc15m_v7_gated.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading v3 gated panel")
df = pd.read_parquet(IN)
log(f"  rows: {len(df)}, cols: {len(df.columns)}")

log("loading vol_hurst_at_fire_15m (BTC only)")
vh = pd.read_parquet(VH)
vh = vh[vh.asset == "BTC"].copy()
log(f"  rows BTC: {len(vh)}")

# Inner join on (slot_start_us, fire_offset_s, direction)
# Note: vh has UP+DOWN per slug both populated; direction-agnostic features
# We join on (slot_start_us, fire_offset_s) keys
JOIN_COLS = ['slot_start_us', 'fire_offset_s']
vh_keep = ['slot_start_us', 'fire_offset_s', 'hurst_100s', 'hurst_300s', 'hurst_900s',
           'rv_60s', 'rv_300s', 'rv_900s', 'rv_3600s', 'rv_ratio_60_to_3600',
           'gk_sigma', 'gk_sigma_ma12', 'vol_regime', 'ret_2m_at_ws', 'mag_ratio',
           'mp_skew_change_500ms' if 'mp_skew_change_500ms' in vh.columns else None]
vh_keep = [c for c in vh_keep if c and c in vh.columns]
log(f"  keeping cols: {vh_keep}")
vh_sub = vh[vh_keep].drop_duplicates(subset=JOIN_COLS, keep='first').copy()
log(f"  after dedup: {len(vh_sub)}")

# also pull mp_skew_change_500ms from df itself (it's present)
n_before = len(df)
df = df.merge(vh_sub, on=JOIN_COLS, how='left', suffixes=('', '_vh'))
log(f"  after merge: {len(df)} (was {n_before}); hurst_300s coverage: {df['hurst_300s'].notna().mean():.3f}")

# ============== NEW V7 GATES ==============
log("building V7 gates")

# --- Path H: hurst variants ---
df['g_hurst_strong_trending'] = ((df.hurst_300s > 0.65)).astype('Int8').fillna(0).astype('int8')
df['g_hurst_reverting'] = ((df.hurst_300s < 0.40)).astype('Int8').fillna(0).astype('int8')
df['g_hurst_strong_trending_900'] = ((df.hurst_900s > 0.65)).astype('Int8').fillna(0).astype('int8')
df['g_hurst_reverting_900'] = ((df.hurst_900s < 0.40)).astype('Int8').fillna(0).astype('int8')

# Direction-aware hurst regime
df['g_hurst_trending_with'] = (
    (df.hurst_300s > 0.55) & (
        ((df.direction == 'UP') & (df.trend_slope_30m > 0)) |
        ((df.direction == 'DOWN') & (df.trend_slope_30m < 0))
    )
).astype('Int8').fillna(0).astype('int8')

# --- Path G: vol regime specialization (3 bins via train-period tercile on rv_60s) ---
# We use train period 18d for tercile, then apply universally
TRAIN_START = pd.Timestamp("2026-04-28", tz="UTC")
TRAIN_END = pd.Timestamp("2026-05-16", tz="UTC")
tr_mask = (df.fire_date >= TRAIN_START) & (df.fire_date < TRAIN_END)
rv = df.loc[tr_mask & df.rv_60s.notna(), 'rv_60s']
if len(rv):
    q33, q67 = rv.quantile([0.33, 0.67]).values
    log(f"  rv_60s train q33={q33:.6f}, q67={q67:.6f}")
    df['g_rv_lo'] = (df.rv_60s <= q33).astype('Int8').fillna(0).astype('int8')
    df['g_rv_md'] = ((df.rv_60s > q33) & (df.rv_60s <= q67)).astype('Int8').fillna(0).astype('int8')
    df['g_rv_hi'] = (df.rv_60s > q67).astype('Int8').fillna(0).astype('int8')

# --- Path D: slot-end OFI proxy for off=840 only ---
# At off=840, fire_us is at ws_s+840s, slot_end at ws_s+900s. fire is 60s before resolution.
# Use mp_skew_change_500ms direction-aligned as the "final OFI in last 0.5s before fire" proxy.
# Real OFI in last 60s would need polymarket trades aggregation - this is a feature-panel proxy.
# Caveat: any feature joined at fire_us-1us is causal. We use mp_skew_change_500ms which is
# microprice skew change in 500ms window ending at fire_us.
df['g_slot_end_ofi_with'] = (
    (df.fire_offset_s == 840) & (
        ((df.direction == 'UP') & (df.mp_skew_change_500ms > 0)) |
        ((df.direction == 'DOWN') & (df.mp_skew_change_500ms < 0))
    )
).astype('Int8').fillna(0).astype('int8')

df['g_slot_end_ofi_strong_with'] = (
    (df.fire_offset_s == 840) & (
        ((df.direction == 'UP') & (df.mp_skew_change_500ms > 10)) |
        ((df.direction == 'DOWN') & (df.mp_skew_change_500ms < -10))
    )
).astype('Int8').fillna(0).astype('int8')

# --- Pre-window directional: ret_2m_at_ws aligned with direction ---
# ret_2m_at_ws = realized 2m return at ws_s timestamp (PRE-window, fully causal)
df['g_ret_2m_with'] = (
    ((df.direction == 'UP') & (df.ret_2m_at_ws > 0)) |
    ((df.direction == 'DOWN') & (df.ret_2m_at_ws < 0))
).astype('Int8').fillna(0).astype('int8')

df['g_ret_2m_strong_with'] = (
    ((df.direction == 'UP') & (df.ret_2m_at_ws > 0.0005)) |
    ((df.direction == 'DOWN') & (df.ret_2m_at_ws < -0.0005))
).astype('Int8').fillna(0).astype('int8')

# --- vwap-band sentinels for ensemble scoring ---
df['g_vwap_deep_premium'] = ((df.entry_vwap >= 0.65) & (df.entry_vwap <= 0.90)).astype('Int8').fillna(0).astype('int8')
df['g_vwap_mid'] = ((df.entry_vwap >= 0.35) & (df.entry_vwap <= 0.65)).astype('Int8').fillna(0).astype('int8')

# Report new gates
new_gates = [c for c in df.columns if c.startswith('g_') and c not in [
    'g_adx_strong','g_adx_trending','g_bb_pos_with','g_book_slope_with_us',
    'g_cci_with','g_dev_extreme','g_di_agrees','g_f7_rsi_extreme_against',
    'g_f7_rsi_extreme_with','g_f7_rsi_mid','g_f7_rsi_strong_with','g_f7_rsi_with',
    'g_hawkes_burst','g_hawkes_imb_loose_with','g_hawkes_imb_strong_with',
    'g_hawkes_imbalance_with','g_imb1_strong_with','g_imb5_strong_with',
    'g_imb5_with','g_imb_change_with','g_jump_dir_with','g_lm_extreme_stat',
    'g_lm_high_stat','g_lm_jump_against','g_lm_jump_with','g_mfi_with',
    'g_mp_change_with','g_mp_no_extreme','g_mp_no_extreme_150','g_mp_our_side_calm',
    'g_mp_skew_strong_with','g_mp_skew_with','g_off_0_60','g_off_240_480',
    'g_off_480_720','g_off_60_240','g_off_720_900','g_queue_top_high',
    'g_regime_ranging','g_regime_stack_full_with','g_regime_stack_with',
    'g_regime_trending_either','g_regime_trending_with','g_rf_aged','g_rf_fresh',
    'g_rf_in_band','g_rf_strong','g_rf_with','g_ribbon_agrees','g_ribbon_slope_with',
    'g_sms_cvd_with','g_sms_rsi_extreme_with','g_sms_rsi_mid','g_sms_rsi_with',
    'g_sms_trend_strong_with','g_sms_trend_with','g_stoch_with','g_tight_ribbon',
    'g_tr_above_cloud','g_tr_above_ema200','g_tr_above_ema50','g_tr_above_ema800',
    'g_tr_above_pp','g_tr_in_active_session','g_tr_stack_full_with','g_tr_stack_with',
    'g_tr_within_adr','g_trend_slope_strong_with','g_trend_slope_with',
    'g_vol_contracting','g_vol_expanding','g_vol_high','g_vpin_calm',
    'g_vpin_very_calm','g_vwap_05_95','g_vwap_10_90','g_vwap_15_85','g_vwap_20_80',
    'g_vwap_25_75','g_vwap_30_70','g_vwap_cheap','g_vwap_premium','g_within_dev'
]]
log(f"new V7 gates ({len(new_gates)}):")
for g in new_gates:
    fr = df[g].astype(float).mean()
    won_at = df[df[g]==1]['won'].mean() if df[g].sum() > 0 else np.nan
    print(f"  {g:40s}  fire_rate={fr:.3f}  sum={int(df[g].sum())}  WR_when_on={won_at:.3f}")

# Save
log("saving V7 panel")
df.to_parquet(OUT, index=False)
log(f"saved: {OUT}  rows={len(df)}  cols={len(df.columns)}")

# Quick sanity: WR by hurst regime on lockbox
LOCK_START = pd.Timestamp("2026-05-22", tz="UTC")
LOCK_END = pd.Timestamp("2026-05-26", tz="UTC")
lo = df[(df.fire_date >= LOCK_START) & (df.fire_date < LOCK_END)]
print()
log("LOCKBOX WR sanity checks:")
for g in ['g_hurst_strong_trending', 'g_hurst_reverting', 'g_hurst_trending_with',
          'g_rv_lo','g_rv_md','g_rv_hi', 'g_slot_end_ofi_with', 'g_slot_end_ofi_strong_with',
          'g_ret_2m_with', 'g_ret_2m_strong_with']:
    sub = lo[lo[g]==1]
    if len(sub):
        print(f"  {g:40s}  n={len(sub):4d}  WR={sub['won'].mean():.3f}  $/tr={sub['pnl_legacy_usd'].mean():+.3f}")

log("DONE")
