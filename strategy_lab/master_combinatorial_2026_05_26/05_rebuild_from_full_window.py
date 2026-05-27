"""Rebuild the master joined features dataframe USING THE FULL-WINDOW base.

Base: data/v4/canonical/_results/full_window_gate_search_per_fire.parquet
  - 77,906 rows through May 24/25 (32d window)
  - has direction, won, pnl_legacy_usd, sleeve identity = (tf, offset_bin, gate_stack)

This is the right base because it covers the full canonical window and has each
sleeve's per-fire direction.

We join the SAME feature panels but on (asset, slug, fire_us, tf).
NB: tf in this file is 's6_5m', 'v15m_15m', 's15_5m' etc — strip suffix.
"""
import os, time, sys
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
BASE_FP = f"{RES}/full_window_gate_search_per_fire.parquet"
OUT = f"{RES}/master_gate_features_v2.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

log("loading base")
base = pd.read_parquet(BASE_FP)
log(f"base rows={len(base):,} cols={len(base.columns)}")
log(f"unique sleeves (tf,offset_bin,gate_stack): {base.groupby(['asset','tf','offset_bin']).size().shape[0]}")

# Normalize tf
base['tf_orig'] = base['tf']
base['tf'] = base['tf_orig'].str[-3:]  # last 3 chars: '5m' or '15m'
# Fix '_5m' -> '5m'
base['tf'] = base['tf'].str.replace('_','')
log(f"tf values: {base['tf'].unique()}")

# Add direction sign + won_int + fire_date
base['dir_sign'] = np.where(base['direction'].str.upper() == 'UP', 1, -1)
base['won_int'] = base['won'].astype(int)
base['fire_date'] = pd.to_datetime(base['fire_us'], unit='us', utc=True)
log(f"dates: {base['fire_date'].min()} -> {base['fire_date'].max()}")

# Drop duplicates (same fire appears under multiple sleeves)
# Keep one row per (slug, fire_us, sleeve_id) for now — the sleeve = (tf_orig, offset_bin, gate_stack)
base['sleeve_id'] = base['tf_orig'] + '|' + base['offset_bin'] + '|' + base['gate_stack']
log(f"unique sleeve_ids: {base['sleeve_id'].nunique()}")
log(f"sleeve_id counts (top 20):\n{base['sleeve_id'].value_counts().head(20)}")

# ---- 2) hybrid_features (R1+R2 baseline TR/RF/stoch/cci) ----
log("loading hybrid_features {5m,15m}")
hf5 = pd.read_parquet(f"{RES}/hybrid_features_5m.parquet")
hf15 = pd.read_parquet(f"{RES}/hybrid_features_15m.parquet")
hf = pd.concat([hf5, hf15], ignore_index=True)
log(f"hybrid_features rows={len(hf):,}")

HF_KEEP = ['asset', 'slug', 'fire_us', 'tf',
           'ribbon_color', 'ribbon_alignment_pct', 'ribbon_compression_bps',
           'stoch_k_60s', 'stoch_d_60s',
           'bb_pos_60s', 'bb_width_60s', 'mfi_60s', 'cci_60s',
           'rf_dir', 'rf_dist_bps', 'rf_band_pos',
           'tr_ema_50', 'tr_ema_200', 'tr_ema_800', 'tr_ema_cloud_pos',
           'tr_ema_stack_score', 'tr_close_vs_ema50', 'tr_close_vs_ema200',
           'tr_close_vs_ema800', 'tr_pvsra',
           'tr_above_pp', 'tr_within_adr', 'tr_close_vs_PP',
           'rf_binance_close_1s', 'f7_rsi_at_ws',
           'vwap_since_open_bps',
           ]
HF_KEEP = [c for c in HF_KEEP if c in hf.columns]
hf = hf[HF_KEEP].drop_duplicates(['asset','slug','fire_us','tf'])
base = base.merge(hf, on=['asset','slug','fire_us','tf'], how='left')
log(f"after hybrid_features merge cols={len(base.columns)}")

# ---- 3) microprice ----
log("merging microprice_panel")
mp = pd.read_parquet(f"{RES}/microprice_panel.parquet")
MP_KEEP = ['asset','slug','tf','fire_us',
           'mp_skew','mp_imbalance','mp_weighted_skew','mp_weighted_imbalance',
           'mp_up_dev_bps','mp_dn_dev_bps','mp_skew_change_500ms']
MP_KEEP = [c for c in MP_KEEP if c in mp.columns]
mp = mp[MP_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(mp, on=['asset','slug','tf','fire_us'], how='left')
log(f"after microprice cols={len(base.columns)}")

# ---- 4) microstructure ----
log("merging microstructure_panel")
ms = pd.read_parquet(f"{RES}/microstructure_panel.parquet")
MS_KEEP = ['asset','slug','tf','fire_us',
           'up_imb1','up_imb5','up_imb25','up_microprice','up_micro_dev_bps',
           'up_bid_slope','up_ask_slope','up_queue_top_bid',
           'up_imb5_change_500ms','up_quote_intensity_5s',
           'dn_imb1','dn_imb5','dn_imb25','dn_microprice','dn_micro_dev_bps',
           'dn_bid_slope','dn_ask_slope']
MS_KEEP = [c for c in MS_KEEP if c in ms.columns]
ms = ms[MS_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(ms, on=['asset','slug','tf','fire_us'], how='left')
log(f"after microstructure cols={len(base.columns)}")

# ---- 5) vol/hurst at fire ----
log("merging vol_hurst_at_fire {5m,15m}")
vh5 = pd.read_parquet(f"{RES}/vol_hurst_at_fire_5m.parquet")
vh15 = pd.read_parquet(f"{RES}/vol_hurst_at_fire_15m.parquet")
vh = pd.concat([vh5, vh15], ignore_index=True)
VH_KEEP = ['asset','slug','tf','fire_us',
           'rv_60s','rv_300s','rv_900s','rv_3600s',
           'rv_ratio_60_to_3600','rv_pct_24h','vol_regime','gk_sigma']
for c in vh.columns:
    if 'hurst' in c.lower(): VH_KEEP.append(c)
VH_KEEP = [c for c in VH_KEEP if c in vh.columns]
vh = vh[VH_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(vh, on=['asset','slug','tf','fire_us'], how='left')
log(f"after vol_hurst cols={len(base.columns)}")

# ---- 6) vpin_hawkes_at_fires ----
log("merging vpin_hawkes_at_fires")
vh_p = pd.read_parquet(f"{RES}/vpin_hawkes_at_fires.parquet")
VHP_KEEP = ['asset','slug','tf','fire_us',
            'vpin_value','vpin_zscore',
            'hawkes_lambda_total','hawkes_lambda_imbalance','hawkes_recent_burst']
VHP_KEEP = [c for c in VHP_KEEP if c in vh_p.columns]
vh_p = vh_p[VHP_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(vh_p, on=['asset','slug','tf','fire_us'], how='left')
log(f"after vpin_hawkes cols={len(base.columns)}")

# ---- 7) as_panel ----
log("merging as_panel")
asp = pd.read_parquet(f"{RES}/as_panel.parquet")
AS_KEEP = ['asset','slug','tf','fire_us','as_uncertainty','as_skew',
           'as_uncertainty_norm_24h','as_uncertainty_pct_24h']
AS_KEEP = [c for c in AS_KEEP if c in asp.columns]
asp = asp[AS_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(asp, on=['asset','slug','tf','fire_us'], how='left')
log(f"after as_panel cols={len(base.columns)}")

# ---- 8) MLOFI ----
log("merging mlofi_panel")
ml = pd.read_parquet(f"{RES}/mlofi_panel.parquet")
ML_KEEP = ['asset','slug','tf','fire_us',
           'mlofi_skew_l5_30s','mlofi_skew_l5_60s','mlofi_skew_l25_30s',
           'ofi_skew_l1_30s']
ML_KEEP = [c for c in ML_KEEP if c in ml.columns]
ml = ml[ML_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(ml, on=['asset','slug','tf','fire_us'], how='left')
log(f"after mlofi cols={len(base.columns)}")

# ---- 9) regime panels (asof) ----
log("merging regime_panel {5m,15m} asof")
rp5 = pd.read_parquet(f"{RES}/regime_panel_5m.parquet").rename(columns={'ts_us':'fire_us'})
rp15 = pd.read_parquet(f"{RES}/regime_panel_15m.parquet").rename(columns={'ts_us':'fire_us'})
RP_KEEP = ['asset','fire_us','adx_14','plus_di_14','minus_di_14','atr_14',
           'tr_ema_stack_score','bb_width_60s','realized_vol_60m',
           'range_compression','trend_slope_30m','regime_label','regime_score']
rp5 = rp5[[c for c in RP_KEEP if c in rp5.columns]].sort_values(['asset','fire_us'])
rp15 = rp15[[c for c in RP_KEEP if c in rp15.columns]].sort_values(['asset','fire_us'])

def asof_merge_per_asset(left, right, on='fire_us', by='asset', suffix='_rp'):
    rs = []
    for ast in left[by].unique():
        L = left[left[by]==ast].sort_values(on).reset_index(drop=False)
        R = right[right[by]==ast].sort_values(on)
        if len(R) == 0:
            L_out = L.copy()
            for c in right.columns:
                if c not in (on, by): L_out[c+suffix] = np.nan
        else:
            L_out = pd.merge_asof(L, R, on=on, direction='backward', suffixes=('', suffix))
        rs.append(L_out)
    out = pd.concat(rs, ignore_index=True).sort_values('index').drop(columns=['index'])
    return out

base5 = base[base['tf']=='5m'].copy()
base15 = base[base['tf']=='15m'].copy()
base5 = asof_merge_per_asset(base5, rp5, suffix='_rp')
base15 = asof_merge_per_asset(base15, rp15, suffix='_rp')
base = pd.concat([base5, base15], ignore_index=True)
log(f"after regime asof cols={len(base.columns)}")

# ---- 10) SMS panel (asof) ----
log("merging sms_panel {5m,15m} asof")
sms5 = pd.read_parquet(f"{RES}/sms_panel_5m.parquet").rename(columns={'ts_us':'fire_us'})
sms15 = pd.read_parquet(f"{RES}/sms_panel_15m.parquet").rename(columns={'ts_us':'fire_us'})
SMS_KEEP = ['asset','fire_us','choch_sell','choch_buy','bos_sell','bos_buy',
            'rsi_14','cvd','cvd_sign','liquidity_up','liquidity_dn',
            'trend_strength_raw']
sms5 = sms5[[c for c in SMS_KEEP if c in sms5.columns]].sort_values(['asset','fire_us'])
sms15 = sms15[[c for c in SMS_KEEP if c in sms15.columns]].sort_values(['asset','fire_us'])

base5 = base[base['tf']=='5m'].copy()
base15 = base[base['tf']=='15m'].copy()
base5 = asof_merge_per_asset(base5, sms5, suffix='_sms')
base15 = asof_merge_per_asset(base15, sms15, suffix='_sms')
base = pd.concat([base5, base15], ignore_index=True)
log(f"after sms asof cols={len(base.columns)}")

# ---- 11) Lee-Mykland (asof on fire_us per asset) ----
log("merging lee_mykland asof")
lm = pd.read_parquet(f"{RES}/lee_mykland_panel.parquet")
lm = lm.rename(columns={'ts_us':'fire_us'})
LM_KEEP = ['asset','fire_us','L_stat','is_jump_01','is_jump_05','is_jump_extreme',
           'jump_dir_01','jump_dir_05','jump_dir_extreme']
lm = lm[[c for c in LM_KEEP if c in lm.columns]].sort_values(['asset','fire_us'])

base5 = base[base['tf']=='5m'].copy()
base15 = base[base['tf']=='15m'].copy()
base5 = asof_merge_per_asset(base5, lm, suffix='_lm')
base15 = asof_merge_per_asset(base15, lm, suffix='_lm')
base = pd.concat([base5, base15], ignore_index=True)
log(f"after lee_mykland asof cols={len(base.columns)}")

log(f"final base shape={base.shape}")
base.to_parquet(OUT, index=False)
log(f"WROTE {OUT}  size={os.path.getsize(OUT)/1e6:.1f} MB")
