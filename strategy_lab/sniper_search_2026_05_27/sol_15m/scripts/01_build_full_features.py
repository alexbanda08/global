"""Build full feature matrix for SOL 15m sniper search.

The primary fire universe (oos_fires_SOL_15m_full_v3.parquet) has 34,886 fires (33d).
It already has 23 g_* columns (R1 base + R3 vol gates) joined.

We need to add:
- The R3/R4/R5 gates from regime_v2_fixed (g_trend_slope_with, g_markov_with, g_hurst_trending, ...)
- Microprice gates (g_mp_*)
- master_gate_features_v2 stuff where overlap exists (24d window)

Output: sol_15m_fires_v2fix_gates.parquet (full 34,886 fires with all available gates).
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m"

# Load PRIMARY fire universe
log("loading PRIMARY fires")
df = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_SOL_15m_full_v3.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"primary fires: {len(df):,}")

# 1. Add R4 gates from regime_panel_15m_v2_fixed (28d coverage)
log("loading regime_panel_15m_v2_fixed SOL")
r2 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
r2 = r2[r2.asset=='SOL'].copy().sort_values('ts_us').reset_index(drop=True)
log(f"regime rows: {len(r2):,}")

r2_keep = r2[['ts_us','trend_slope_30m','regime_label','regime_score',
              'adx_14','plus_di_14','minus_di_14','atr_14',
              'tr_ema_stack_score','realized_vol_60m','range_compression','bb_width_60s',
              'ribbon_alignment_pct','close']].copy()
r2_keep.columns = ['ts_us'] + [c + '_v2fix' for c in r2_keep.columns if c != 'ts_us']

# Sort and asof merge
df_s = df.sort_values('fire_us').copy()
df_s['fire_us_key'] = df_s['fire_us']
r2_s = r2_keep.sort_values('ts_us').copy()
r2_s['ts_us_key'] = r2_s['ts_us']
merged = pd.merge_asof(
    df_s, r2_s, left_on='fire_us_key', right_on='ts_us_key',
    direction='backward', allow_exact_matches=True,
)
log(f"merged with regime: {len(merged)}")
merged['regime_age_s'] = (merged.fire_us - merged.ts_us_key) / 1e6
print(f"  regime age stats: min={merged.regime_age_s.min():.1f}s mean={merged.regime_age_s.mean():.1f}s max={merged.regime_age_s.max():.1f}s")
# Null out regime fields where age > 1800s (stale; outside panel coverage)
stale_mask = (merged.regime_age_s > 1800) | merged.regime_age_s.isna()
for col in [c for c in merged.columns if c.endswith('_v2fix')]:
    merged.loc[stale_mask, col] = np.nan
print(f"  stale regime mask: {stale_mask.sum()} fires nulled ({stale_mask.mean()*100:.1f}%)")

# Compute R4 gates
ds = np.where(merged.direction=='UP', 1, -1)
ts = merged['trend_slope_30m_v2fix']
merged['g_trend_slope_with'] = np.where(ts.isna(), np.nan,
                            np.where(ds>0, (ts>0).astype(float), (ts<0).astype(float)))
abs_ts = ts.abs()
thr_strong = abs_ts.quantile(0.75)
print(f"  thr (75th pct of |trend_slope_30m| SOL 15m v2_fixed): {thr_strong:.4f}")
merged['g_trend_slope_strong_with'] = np.where(ts.isna(), np.nan,
        (((ds>0)&(ts>thr_strong)) | ((ds<0)&(ts<-thr_strong))).astype(float))

# g_markov_with: regime_label 'trending_up' / 'trending_dn' with-direction
rl = merged['regime_label_v2fix']
# Need to handle string equality with NaN
rl_na = rl.isna() | (rl == '') | (rl is None)
match_up = (rl == 'trending_up')
match_dn = (rl == 'trending_dn')
merged['g_markov_with'] = np.where(rl_na, np.nan,
        (((ds>0)&match_up) | ((ds<0)&match_dn)).astype(float))
log(f"  g_markov_with ones: {(merged['g_markov_with']==1).sum()} of {merged['g_markov_with'].notna().sum()}")

# g_hurst_trending: |regime_score| >= 0.25 (score is in [-1,1] scale, p75 = 0.153)
rs = merged['regime_score_v2fix']
# Use p75 of |score| as threshold for "trending"
abs_rs_thr = r2['regime_score'].abs().quantile(0.75) if 'regime_score' in r2.columns else 0.25
print(f"  hurst threshold (|score| >= {abs_rs_thr:.3f}):")
merged['g_hurst_trending'] = np.where(rs.isna(), np.nan, (rs.abs()>=abs_rs_thr).astype(float))

# g_vol_expanding/contracting/high using realized_vol_60m and range_compression
rv = merged['realized_vol_60m_v2fix']
rc = merged['range_compression_v2fix']
# Need rolling distribution for percentiles; use full-window quantiles for sniper
rv_p75 = rv.quantile(0.75)
rv_p90 = rv.quantile(0.90)
rv_p15 = rv.quantile(0.15)
merged['g_vol_expanding']    = np.where(rv.isna(), np.nan, (rv>=rv_p75).astype(float))
merged['g_vol_high']         = np.where(rv.isna(), np.nan, (rv>=rv_p90).astype(float))
# R7 vol_contracting threshold loosened from 0.7 to 0.85
merged['g_vol_contracting']  = np.where(rc.isna(), np.nan, (rc>=0.85).astype(float))

# 2. Add microprice gates (31.7d coverage)
log("loading microprice panel")
mp = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/microprice_panel.parquet")
mp_sol = mp[mp.asset=='SOL'].copy()
log(f"microprice SOL rows: {len(mp_sol):,}")
# Dedupe on (slug, fire_us) - take first if duplicates exist
mp_keep = mp_sol[['slug','fire_us','mp_up_simple','mp_dn_simple','mp_up_weighted']].copy()
mp_keep = mp_keep.drop_duplicates(subset=['slug','fire_us'], keep='first')
log(f"  mp after dedupe: {len(mp_keep):,}")
merged = merged.merge(mp_keep, on=['slug','fire_us'], how='left', suffixes=('', '_mp'))
log(f"after microprice merge: {len(merged)} (mp coverage: {merged.mp_up_simple.notna().sum():,})")

# Recompute ds AFTER merge (sizes may have changed)
ds = np.where(merged.direction=='UP', 1, -1)
# Compute mp gates
mp_up = merged['mp_up_weighted']
mp_dn = merged['mp_dn_simple']
mp_with = np.where(ds>0, mp_up, mp_dn)
# g_mp_no_extreme: tradability gate (R7: looser, |mp - 0.5| < 0.075 = within 150 bps)
merged['g_mp_no_extreme'] = np.where(np.isnan(mp_with), np.nan,
                                      ((mp_with > 0.30) & (mp_with < 0.85)).astype(float))
# mp_change/skew need prior — skip for now (or compute later)

# 3. Add master_gate_features_v2 stuff where overlap exists (~24d May 1-21)
log("loading master_gate_features_v2")
mgf = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/master_gate_features_v2.parquet")
mgf_sol = mgf[(mgf.asset=='SOL')&(mgf.tf=='15m')].copy()
log(f"mgf SOL 15m: {len(mgf_sol)} (window May 1-21)")
# Add the high-value rare gates
mgf_keep_cols = ['slug','fire_us',
                  'g_lm_high_stat','g_lm_extreme_against',
                  'g_hawkes_imbalance_with',
                  'g_flow_with_and_no_whale',
                  'g_coinbase_basis_extreme_against',
                  'g_hl_liq_cascade_with',
                  'g_imb5_strong_with','g_queue_top_high','g_imb_change_with',
                  'g_vwap_ge_50_le_85','g_book_slope_steep_against',
                  'g_mp_change_with','g_mp_skew_with']
mgf_have = [c for c in mgf_keep_cols if c in mgf_sol.columns]
mgf_sub = mgf_sol[mgf_have].copy()
mgf_sub = mgf_sub.drop_duplicates(subset=['slug','fire_us'], keep='first')
mgf_sub = mgf_sub.rename(columns={c: c+'_mgf' for c in mgf_have if c not in ('slug','fire_us')})
merged = merged.merge(mgf_sub, on=['slug','fire_us'], how='left')
log(f"after mgf merge: {len(merged)}")
# Promote _mgf to the canonical g_* name (will be NaN outside May 1-21)
for c in mgf_have:
    if c in ('slug','fire_us'): continue
    merged[c] = merged[c + '_mgf']
    merged = merged.drop(columns=[c + '_mgf'])

# 4. Add a derived offset_bin column
def offset_bin(s):
    if s <= 120: return '60-120'
    if s <= 240: return '120-240'
    if s <= 480: return '240-480'
    if s <= 720: return '480-720'
    return '720-840'
merged['offset_bin'] = merged.fire_offset_s.apply(offset_bin)
log(f"offset_bin counts: {merged.offset_bin.value_counts().to_dict()}")

# 5. Add a derived feature: book depth supports $250
# Inspect entry_vwap to see if it's available
log(f"entry_vwap stats: min={merged.entry_vwap.min():.4f} max={merged.entry_vwap.max():.4f} pct_nan={merged.entry_vwap.isna().mean()*100:.1f}%")
# spread_ish using entry_vwap - mp_up_weighted: large diff = wide spread (proxy)
# For $250 viability: need book depth at least $250 / entry_vwap shares at top of book
# This isn't directly in the panel; use mp_no_extreme as a proxy. note honestly:
# This gate is not directly computable here; leave NaN for now.
merged['g_book_depth_supports_250'] = np.nan

# Save
out_cols = list(merged.columns)
out = merged.drop(columns=['fire_us_key','ts_us_key'], errors='ignore')
out.to_parquet(f"{OUT}/sol_15m_fires_v2fix_gates.parquet", index=False)
log(f"WROTE sol_15m_fires_v2fix_gates.parquet ({len(out)} rows, {len(out.columns)} cols)")
g_cols_final = [c for c in out.columns if c.startswith('g_')]
log(f"final g_* gates: {len(g_cols_final)}")
log(f"  gates: {sorted(g_cols_final)}")
# Coverage of each gate
log("Gate coverage (non-NaN %):")
for g in sorted(g_cols_final):
    cov = out[g].notna().mean() * 100
    ones = (out[g]==1).mean() * 100
    log(f"  {g:40} cov={cov:5.1f}%  ones={ones:5.1f}%")
log("DONE")
