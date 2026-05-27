"""V7 SOL 15m universe = V6 + cross-asset triggers.

Path C (PRIMARY): BTC/ETH 15m signals → SOL fire
- BTC 15m trend_slope_30m at ws_s aligned with SOL direction
- BTC 15m regime_label (trending_up/dn) at ws_s
- ETH 15m vol_high regime at ws_s (risk-on/off)
- BTC microprice change at ws_s (lead asset)
- ETH microprice skew at ws_s
- Cross-asset RF unanimity: BTC RF + ETH RF + SOL direction agreement

Path G: vol regime specialization (rv_60 split)
Path H: hurst variants (strong/regime-with)

Output: sol_15m_v7_universe.parquet
"""
import os, time, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
OUT  = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/sol_15m_v7"

# Start from V6 universe
log("loading V6 universe")
df = pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_15m_v6/sol_15m_v6_universe.parquet")
df = df.sort_values('fire_us').reset_index(drop=True)
log(f"V6 universe: {len(df):,} rows, {len(df.columns)} cols")
df['dir_int'] = np.where(df['direction']=='UP', 1, -1)
df['ws_s_us'] = df['slot_start_us'] - 900 * 1_000_000

# === PATH C: Cross-asset regime signals (BTC/ETH 15m at SOL ws_s) ===
log("=== PATH C: cross-asset regime panel ===")
rp15 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
rp15 = rp15.sort_values(['asset','ts_us']).reset_index(drop=True)
log(f"  regime_15m: BTC={int((rp15['asset']=='BTC').sum())} ETH={int((rp15['asset']=='ETH').sum())} SOL={int((rp15['asset']=='SOL').sum())}")

for src in ['BTC','ETH']:
    log(f"  asof-joining {src} regime at SOL ws_s")
    rp_a = rp15[rp15['asset']==src][['ts_us','trend_slope_30m','regime_label','realized_vol_60m','adx_14','range_compression','tr_ema_stack_score','ribbon_alignment_pct','bb_width_60s']].sort_values('ts_us').reset_index(drop=True)
    rp_a.columns = ['ts_us', f'{src}_slope_30m', f'{src}_reg', f'{src}_rv60', f'{src}_adx', f'{src}_rc', f'{src}_tr_stack', f'{src}_ribbon', f'{src}_bbw']
    df = pd.merge_asof(df.sort_values('ws_s_us'),
                       rp_a,
                       left_on='ws_s_us', right_on='ts_us',
                       direction='backward', allow_exact_matches=True,
                       tolerance=int(20*60*1e6))  # 20min tol
    if 'ts_us' in df.columns:
        df = df.drop(columns=['ts_us'])
    df = df.sort_values('fire_us').reset_index(drop=True)
    log(f"    {src}_slope_30m non-null={df[f'{src}_slope_30m'].notna().mean()*100:.1f}%")

# Cross-asset gates (BTC leads SOL — beta ~1.5)
ds = df['dir_int']
for src in ['BTC','ETH']:
    sl = df[f'{src}_slope_30m']
    df[f'g_{src}_slope_with'] = np.where(sl.isna(), np.nan,
        (((ds>0) & (sl>0)) | ((ds<0) & (sl<0))).astype(float))
    df[f'g_{src}_slope_strong_with'] = np.where(sl.isna(), np.nan,
        (((ds>0) & (sl>0.5)) | ((ds<0) & (sl<-0.5))).astype(float))
    # Regime label gates
    rl = df[f'{src}_reg']
    df[f'g_{src}_regime_trend_with'] = np.where(rl.isna(), np.nan,
        (((ds>0) & (rl=='trending_up')) | ((ds<0) & (rl=='trending_dn'))).astype(float))
    df[f'g_{src}_regime_trend_either'] = np.where(rl.isna(), np.nan,
        ((rl=='trending_up') | (rl=='trending_dn')).astype(float))
    df[f'g_{src}_regime_ranging'] = np.where(rl.isna(), np.nan,
        (rl=='ranging').astype(float))
    # vol high
    rv = df[f'{src}_rv60']
    rv_med = rv.median()
    df[f'g_{src}_vol_high'] = np.where(rv.isna(), np.nan, (rv > rv_med).astype(float))
    df[f'g_{src}_vol_low'] = np.where(rv.isna(), np.nan, (rv <= rv_med).astype(float))
    # ADX strong trend
    adx = df[f'{src}_adx']
    df[f'g_{src}_adx_strong'] = np.where(adx.isna(), np.nan, (adx > 25).astype(float))
    # TR stack with
    trs = df[f'{src}_tr_stack']
    df[f'g_{src}_tr_stack_with'] = np.where(trs.isna(), np.nan,
        (((ds>0) & (trs>0)) | ((ds<0) & (trs<0))).astype(float))

# Cross-asset unanimity: BTC + ETH slope direction aligned with SOL fire
df['g_xa_btc_eth_slope_unanimity_with'] = np.where(
    df['BTC_slope_30m'].isna() | df['ETH_slope_30m'].isna(), np.nan,
    (((ds>0) & (df['BTC_slope_30m']>0) & (df['ETH_slope_30m']>0)) |
     ((ds<0) & (df['BTC_slope_30m']<0) & (df['ETH_slope_30m']<0))).astype(float))
df['g_xa_btc_eth_regime_trend_with'] = np.where(
    df['BTC_reg'].isna() | df['ETH_reg'].isna(), np.nan,
    (((ds>0) & (df['BTC_reg']=='trending_up') & (df['ETH_reg']=='trending_up')) |
     ((ds<0) & (df['BTC_reg']=='trending_dn') & (df['ETH_reg']=='trending_dn'))).astype(float))

log(f"  g_BTC_slope_with ones rate: {df['g_BTC_slope_with'].mean():.3f}")
log(f"  g_ETH_slope_with ones rate: {df['g_ETH_slope_with'].mean():.3f}")
log(f"  g_xa_btc_eth_slope_unanimity_with ones rate: {df['g_xa_btc_eth_slope_unanimity_with'].mean():.3f}")
log(f"  g_xa_btc_eth_regime_trend_with ones rate: {df['g_xa_btc_eth_regime_trend_with'].mean():.3f}")

# === PATH C cont'd: Cross-asset microprice (BTC/ETH leads SOL) ===
log("=== PATH C: cross-asset microprice ===")
mp = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/microprice_panel.parquet")
log(f"  mp panel: {len(mp):,} rows")
print(f"  mp cols: {mp.columns.tolist()}")

# For cross-asset, we want BTC/ETH microprice at SOL's ws_s
# microprice_panel has fire_us-anchored values per slug. We need a ts_us index.
# Use 'fire_us' as the timestamp (this is the asof timestamp the panel was computed at)
mp_keep_cols = [c for c in mp.columns if c in ['fire_us','asset','slug','mp_up_simple','mp_dn_simple','mp_skew','mp_imbalance','mp_skew_change_500ms']]
for src in ['BTC','ETH']:
    mp_src = mp[mp['asset']==src][mp_keep_cols].copy()
    if 'fire_us' not in mp_src.columns:
        log(f"  WARNING no fire_us in microprice; skip {src}")
        continue
    mp_src = mp_src.sort_values('fire_us').drop_duplicates(['fire_us'], keep='last').reset_index(drop=True)
    mp_src.columns = ['ts_us' if c=='fire_us' else c for c in mp_src.columns]
    mp_src = mp_src.rename(columns={
        'mp_up_simple': f'{src}_mp_up',
        'mp_dn_simple': f'{src}_mp_dn',
        'mp_skew': f'{src}_mp_skew',
        'mp_imbalance': f'{src}_mp_imb',
        'mp_skew_change_500ms': f'{src}_mp_skew_chg',
    })
    if 'asset' in mp_src.columns:
        mp_src = mp_src.drop(columns=['asset'])
    if 'slug' in mp_src.columns:
        mp_src = mp_src.drop(columns=['slug'])
    df = pd.merge_asof(df.sort_values('ws_s_us'),
                       mp_src.sort_values('ts_us'),
                       left_on='ws_s_us', right_on='ts_us',
                       direction='backward', allow_exact_matches=True,
                       tolerance=int(15*60*1e6))
    if 'ts_us' in df.columns:
        df = df.drop(columns=['ts_us'])
    df = df.sort_values('fire_us').reset_index(drop=True)
    log(f"    {src}_mp_skew non-null={df[f'{src}_mp_skew'].notna().mean()*100:.1f}%")

# Cross-asset MP gates
for src in ['BTC','ETH']:
    sk = df[f'{src}_mp_skew']
    df[f'g_{src}_mp_skew_with'] = np.where(sk.isna(), np.nan,
        (((ds>0) & (sk>0)) | ((ds<0) & (sk<0))).astype(float))
    df[f'g_{src}_mp_skew_strong_with'] = np.where(sk.isna(), np.nan,
        (((ds>0) & (sk>0.05)) | ((ds<0) & (sk<-0.05))).astype(float))
    chg = df[f'{src}_mp_skew_chg']
    df[f'g_{src}_mp_change_with'] = np.where(chg.isna(), np.nan,
        (((ds>0) & (chg>0)) | ((ds<0) & (chg<0))).astype(float))

# 3-asset MP unanimity
df['g_xa_3asset_mp_skew_with'] = np.where(
    df['BTC_mp_skew'].isna() | df['ETH_mp_skew'].isna() | df['mp_skew_at_ws'].isna(), np.nan,
    (((ds>0) & (df['BTC_mp_skew']>0) & (df['ETH_mp_skew']>0) & (df['mp_skew_at_ws']>0)) |
     ((ds<0) & (df['BTC_mp_skew']<0) & (df['ETH_mp_skew']<0) & (df['mp_skew_at_ws']<0))).astype(float))

log(f"  g_BTC_mp_skew_with: {df['g_BTC_mp_skew_with'].mean():.3f}")
log(f"  g_ETH_mp_skew_with: {df['g_ETH_mp_skew_with'].mean():.3f}")
log(f"  g_xa_3asset_mp_skew_with: {df['g_xa_3asset_mp_skew_with'].mean():.3f}")

# === PATH G: Vol regime specialization (use vol_hurst_at_fire_15m) ===
log("=== PATH G: vol regime specialization ===")
vh15_path = f"{ROOT}/data/v4/canonical/_results/vol_hurst_at_fire_15m.parquet"
if os.path.exists(vh15_path):
    vh15 = pd.read_parquet(vh15_path)
    log(f"  vol_hurst_15m: {len(vh15):,}; cols={vh15.columns.tolist()}")
    vh_sol = vh15[vh15['asset']=='SOL'] if 'asset' in vh15.columns else vh15
    # Match on slug+fire_us
    # Actual col names: rv_60s, rv_300s, rv_900s, hurst_100s/300s/900s, vol_regime
    keep = [c for c in ['slug','fire_us','fire_offset_s','rv_60s','rv_300s','rv_900s',
                        'hurst_100s','hurst_300s','hurst_900s','vol_regime',
                        'rv_ratio_60_to_3600','rv_pct_24h','gk_sigma'] if c in vh_sol.columns]
    if 'slug' in vh_sol.columns and 'fire_us' in vh_sol.columns:
        vh_sol = vh_sol[keep].drop_duplicates(['slug','fire_us'], keep='last')
        rename = {c: f'v15_{c}' for c in keep if c not in ['slug','fire_us']}
        vh_sol = vh_sol.rename(columns=rename)
        df = df.merge(vh_sol, on=['slug','fire_us'], how='left')
        for c in ['v15_rv_60s','v15_hurst_300s','v15_vol_regime']:
            if c in df.columns:
                log(f"    {c} nonnull={df[c].notna().mean()*100:.1f}%")
    else:
        log("  WARNING — slug/fire_us missing in vh15")
else:
    log(f"  no {vh15_path}")

# vol regime gates from SOL's own rv_60s
if 'v15_rv_60s' in df.columns:
    rv = df['v15_rv_60s']
    rv_med = rv.median()
    rv_q75 = rv.quantile(0.75)
    rv_q25 = rv.quantile(0.25)
    df['g_rv_high'] = np.where(rv.isna(), np.nan, (rv > rv_med).astype(float))
    df['g_rv_low'] = np.where(rv.isna(), np.nan, (rv <= rv_med).astype(float))
    df['g_rv_very_high'] = np.where(rv.isna(), np.nan, (rv > rv_q75).astype(float))
    df['g_rv_very_low'] = np.where(rv.isna(), np.nan, (rv <= rv_q25).astype(float))
    log(f"  g_rv_high rate: {df['g_rv_high'].mean():.3f}")

# vol_regime categorical
if 'v15_vol_regime' in df.columns:
    vr = df['v15_vol_regime']
    df['g_vol_regime_low'] = np.where(vr.isna(), np.nan, (vr=='low').astype(float))
    df['g_vol_regime_high'] = np.where(vr.isna(), np.nan, (vr=='high').astype(float))
    df['g_vol_regime_med'] = np.where(vr.isna(), np.nan, (vr=='med').astype(float))
    log(f"  v15_vol_regime values: {vr.value_counts(dropna=False).to_dict()}")

# === PATH H: Hurst variants ===
log("=== PATH H: hurst variants ===")
# Try hurst_300s as primary
hu_col = None
for cand in ['v15_hurst_300s','v15_hurst_100s','v15_hurst_900s']:
    if cand in df.columns and df[cand].notna().sum() > 1000:
        hu_col = cand
        break
if hu_col:
    log(f"  using {hu_col}")
    hu = df[hu_col]
    df['g_hurst_strong_trending'] = np.where(hu.isna(), np.nan, (hu > 0.65).astype(float))
    df['g_hurst_reverting'] = np.where(hu.isna(), np.nan, (hu < 0.40).astype(float))
    df['g_hurst_mid_trending'] = np.where(hu.isna(), np.nan, ((hu > 0.55) & (hu <= 0.65)).astype(float))
    df['g_hurst_50_plus'] = np.where(hu.isna(), np.nan, (hu > 0.50).astype(float))
    log(f"  g_hurst_strong_trending rate: {df['g_hurst_strong_trending'].mean():.3f}")
    log(f"  g_hurst_reverting rate: {df['g_hurst_reverting'].mean():.3f}")

# === PATH A pre-prep: weighted ensemble — we precompute gate_sum below ===
# Already have many gates; the weighted ensemble logic will be in 10_v7_search.py

# Save
df.to_parquet(f"{OUT}/sol_15m_v7_universe.parquet", index=False)
new_gs = sorted([c for c in df.columns if c.startswith('g_') and c not in pd.read_parquet(f"{ROOT}/strategy_lab/sniper_search_2026_05_27/sol_15m_v6/sol_15m_v6_universe.parquet", columns=None).columns])
log(f"V7 NEW gates: {new_gs}")
log(f"WROTE {OUT}/sol_15m_v7_universe.parquet ({len(df):,} rows, {len(df.columns)} cols)")
log("DONE")
