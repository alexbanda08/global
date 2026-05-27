"""TASK 1 — Build the MASTER joined features dataframe.

Base: master_5m_panel + master_15m_panel (one row per fire with direction+pnl).
Joins: hybrid_features_{5m,15m} (TR/RF/stoch/cci/bb/mfi/ribbon),
microprice_panel, microstructure_panel, vol_hurst_at_fire_{5m,15m},
regime_panel_{5m,15m} (asof on ts_us), sms_panel (asof on ts_us),
vpin_hawkes_at_fires, as_panel, mlofi_panel, lee_mykland_panel (asof on ts_us per asset).

Then compute ALL ~36 gates as direction-aware booleans (NaN -> False = "inactive").

Output: data/v4/canonical/_results/master_gate_features.parquet
"""
import sys, os, time, math
sys.path.insert(0, "data/v4/canonical")

import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
OUT = f"{RES}/master_gate_features.parquet"

t0 = time.time()
def log(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

# ---- 1) BASE ----
log("loading master_5m + master_15m base panels")
b5 = pd.read_parquet(f"{RES}/master_5m_panel.parquet")
b5['tf'] = '5m'
b15 = pd.read_parquet(f"{RES}/master_15m_panel.parquet")
b15['tf'] = '15m'
base = pd.concat([b5, b15], ignore_index=True)
log(f"base rows={len(base):,}  cols={len(base.columns)}")

# normalise direction to +1 / -1
base['dir_sign'] = np.where(base['direction'].str.upper() == 'UP', 1, -1)
base['won_int'] = base['won'].astype(int)

# ---- 2) hybrid_features (R1+R2 baseline TR/RF/stoch/cci) ----
log("loading hybrid_features {5m,15m}")
hf5 = pd.read_parquet(f"{RES}/hybrid_features_5m.parquet")
hf15 = pd.read_parquet(f"{RES}/hybrid_features_15m.parquet")
hf = pd.concat([hf5, hf15], ignore_index=True)
log(f"hybrid_features rows={len(hf):,}")

# we keep only features we need to compute gates
HF_KEEP = ['asset', 'slug', 'fire_us', 'tf',
           # ribbon
           'ribbon_color', 'ribbon_alignment_pct', 'ribbon_compression_bps',
           # stoch
           'stoch_k_60s', 'stoch_d_60s',
           # bb/mfi/cci
           'bb_pos_60s', 'bb_width_60s', 'mfi_60s', 'cci_60s',
           # RF
           'rf_dir', 'rf_dist_bps', 'rf_band_pos',
           # TR EMA
           'tr_ema_50', 'tr_ema_200', 'tr_ema_800', 'tr_ema_cloud_pos',
           'tr_ema_stack_score', 'tr_close_vs_ema50', 'tr_close_vs_ema200',
           'tr_close_vs_ema800', 'tr_pvsra',
           # TR pivots
           'tr_above_pp', 'tr_within_adr', 'tr_close_vs_PP', 'tr_close_vs_R1',
           'tr_close_vs_S1', 'tr_close_vs_dayopen',
           # 1s binance close (for close-based gates)
           'rf_binance_close_1s',
           # f7 rsi
           'f7_rsi_at_ws',
           # outcome (for sanity, will drop duplicate)
           ]
HF_KEEP = [c for c in HF_KEEP if c in hf.columns]
hf = hf[HF_KEEP]
base = base.merge(hf, on=['asset','slug','fire_us','tf'], how='left',
                  suffixes=('','_hf'))
log(f"after hybrid_features merge cols={len(base.columns)}")

# ---- 3) microprice panel (R5) ----
log("merging microprice_panel")
mp = pd.read_parquet(f"{RES}/microprice_panel.parquet")
MP_KEEP = ['asset','slug','tf','fire_us',
           'mp_skew','mp_imbalance','mp_weighted_skew','mp_weighted_imbalance',
           'mp_up_dev_bps','mp_dn_dev_bps','mp_skew_change_500ms']
MP_KEEP = [c for c in MP_KEEP if c in mp.columns]
mp = mp[MP_KEEP]
base = base.merge(mp, on=['asset','slug','tf','fire_us'], how='left')
log(f"after microprice cols={len(base.columns)}")

# ---- 4) microstructure panel (R3-R4) ----
log("merging microstructure_panel")
ms = pd.read_parquet(f"{RES}/microstructure_panel.parquet")
MS_KEEP = ['asset','slug','tf','fire_us',
           'up_imb1','up_imb5','up_imb25','up_microprice','up_micro_dev_bps',
           'up_bid_slope','up_ask_slope','up_queue_top_bid',
           'up_imb5_change_500ms','up_quote_intensity_5s',
           'dn_imb1','dn_imb5','dn_imb25','dn_microprice','dn_micro_dev_bps',
           'dn_bid_slope','dn_ask_slope']
MS_KEEP = [c for c in MS_KEEP if c in ms.columns]
ms = ms[MS_KEEP]
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
# May also have hurst columns — discover
for c in vh.columns:
    if 'hurst' in c.lower():
        VH_KEEP.append(c)
VH_KEEP = [c for c in VH_KEEP if c in vh.columns]
vh = vh[VH_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(vh, on=['asset','slug','tf','fire_us'], how='left')
log(f"after vol_hurst cols={len(base.columns)}")

# ---- 6) vpin_hawkes_at_fires (R5) ----
log("merging vpin_hawkes_at_fires")
vh_p = pd.read_parquet(f"{RES}/vpin_hawkes_at_fires.parquet")
VHP_KEEP = ['asset','slug','tf','fire_us',
            'vpin_value','vpin_zscore',
            'hawkes_lambda_total','hawkes_lambda_imbalance','hawkes_recent_burst']
VHP_KEEP = [c for c in VHP_KEEP if c in vh_p.columns]
vh_p = vh_p[VHP_KEEP].drop_duplicates(['asset','slug','tf','fire_us'])
base = base.merge(vh_p, on=['asset','slug','tf','fire_us'], how='left')
log(f"after vpin_hawkes cols={len(base.columns)}")

# ---- 7) as_panel (Avellaneda-Stoikov) ----
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

# ---- 9) regime panels (asof on ts_us per asset) ----
log("merging regime_panel {5m,15m} asof")
rp5 = pd.read_parquet(f"{RES}/regime_panel_5m.parquet").rename(columns={'ts_us':'fire_us'})
rp15 = pd.read_parquet(f"{RES}/regime_panel_15m.parquet").rename(columns={'ts_us':'fire_us'})
RP_KEEP = ['asset','fire_us','adx_14','plus_di_14','minus_di_14','atr_14',
           'tr_ema_stack_score','bb_width_60s','realized_vol_60m',
           'range_compression','trend_slope_30m','regime_label','regime_score']
rp5 = rp5[[c for c in RP_KEEP if c in rp5.columns]].sort_values(['asset','fire_us'])
rp15 = rp15[[c for c in RP_KEEP if c in rp15.columns]].sort_values(['asset','fire_us'])

def asof_merge_per_asset(left, right, on='fire_us', by='asset', suffix='_rp'):
    """asof merge — for each asset separately."""
    rs = []
    for ast in left[by].unique():
        L = left[left[by]==ast].sort_values(on).reset_index(drop=False)  # keep index
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
base5 = asof_merge_per_asset(base5, rp5)
base15 = asof_merge_per_asset(base15, rp15)
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

# ---- 11) Lee-Mykland panel (asof on ts_us per asset, NEAR/at-or-before fire_us) ----
log("merging lee_mykland asof")
lm = pd.read_parquet(f"{RES}/lee_mykland_panel.parquet")
# rename ts -> fire_us, but only keep the latest tick before each fire
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

# remove suffix mess for downstream gate computation
# our gate functions reference plain names: regime cols & sms cols & lm cols are already disambig.

log(f"final base shape={base.shape}")
log(f"sample columns: {list(base.columns)[:20]}...")

base.to_parquet(OUT, index=False)
log(f"WROTE {OUT}  size={os.path.getsize(OUT)/1e6:.1f} MB")
