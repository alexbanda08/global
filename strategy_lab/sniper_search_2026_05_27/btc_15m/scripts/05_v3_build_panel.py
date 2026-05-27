"""Build BTC 15m sniper panel from v3 fires (33d) + bug-fixed regime panel.

Why this script supersedes 01/02 from prior agent:
- Uses oos_fires_BTC_15m_full_v3.parquet (43,456 fires, 33d Apr 24 - May 26)
- Old hybrid_features_15m was bounded by SMS (22d only, Apr 30 - May 22)
- Joins regime_panel_15m_v2_fixed at ws_us-1s (causal) → effective window = 28d
- Adds microprice (31.7d), microstructure, hawkes, lee-mykland, vpin
- Reuses pre-computed gates already in v3 fires (23 gates)
- Adds R4 (trend_slope) + R5 (mp / lm / hawkes) gates correctly
- entry_vwap and PnL are already canonical (engine_v2 LegacyConfig)

Output: data/v4/canonical/_results/sniper_btc15m_v3_panel.parquet
"""
import os, sys, time
import numpy as np
import pandas as pd

RES = "data/v4/canonical/_results"
V3_IN = f"{RES}/_full_window_v3_2026_05_27/oos_fires_BTC_15m_full_v3.parquet"
OUT = f"{RES}/sniper_btc15m_v3_panel.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


# ============== 1) Load v3 fires ==============
log("loading v3 fires")
df = pd.read_parquet(V3_IN)
df["fire_date"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
log(f"v3 BTC 15m fires: {len(df)} ({df.fire_date.min()} to {df.fire_date.max()})")

# Add ws_us for asof joins
df["ws_us"] = (df["ws_s"].astype("int64") * 1_000_000)
df["ws_us_eps"] = df["ws_us"] - 1_000_000  # 1s causal epsilon
df = df.sort_values("fire_us").reset_index(drop=True)


# ============== 2) Join regime_panel_15m_v2_fixed (at ws_us-1s) ==============
log("joining regime_panel_15m_v2_fixed (asof at ws_us-1s, causal)")
rg = pd.read_parquet(f"{RES}/regime_panel_15m_v2_fixed.parquet")
rg = rg[rg["asset"] == "BTC"].copy()
rg["ts_us"] = rg["ts_us"].astype("int64")
rg = rg.sort_values("ts_us").reset_index(drop=True)

rg_cols = ["ts_us", "trend_slope_30m", "regime_label", "regime_score",
           "adx_14", "plus_di_14", "minus_di_14", "atr_14",
           "tr_ema_stack_score", "realized_vol_60m", "range_compression",
           "bb_width_60s"]
rg_use = rg[rg_cols].rename(columns={"tr_ema_stack_score": "regime_tr_ema_stack_score"})

df_sorted = df.sort_values("ws_us_eps").reset_index(drop=True)
merged = pd.merge_asof(
    df_sorted, rg_use,
    left_on="ws_us_eps", right_on="ts_us",
    direction="backward", allow_exact_matches=True,
)
merged = merged.drop(columns=["ts_us"])
log(f"  regime coverage: {merged['trend_slope_30m'].notna().sum()}/{len(merged)}")


# ============== 3) Join microprice_panel (slug + offset) ==============
log("joining microprice_panel (slug+offset)")
mp = pd.read_parquet(f"{RES}/microprice_panel.parquet")
mp = mp[(mp.asset == "BTC") & (mp.tf == "15m")].copy()
mp_cols = ["slug", "fire_offset_s", "mp_skew", "mp_imbalance",
           "mp_weighted_skew", "mp_weighted_imbalance",
           "mp_up_dev_bps", "mp_dn_dev_bps",
           "mp_skew_change_500ms", "mp_up_dev_change_500ms", "mp_dn_dev_change_500ms"]
mp_use = mp[mp_cols].drop_duplicates(subset=["slug", "fire_offset_s"], keep="first")
merged = merged.merge(mp_use, on=["slug", "fire_offset_s"], how="left")
log(f"  microprice coverage: {merged['mp_skew'].notna().sum()}/{len(merged)}")


# ============== 4) Join microstructure_panel (slug + offset) ==============
log("joining microstructure_panel (slug+offset)")
ms = pd.read_parquet(f"{RES}/microstructure_panel.parquet")
ms = ms[(ms.asset == "BTC") & (ms.tf == "15m")].copy()
ms_cols = ["slug", "fire_offset_s",
           "up_imb1", "up_imb5", "up_imb25", "up_microprice", "up_micro_dev_bps",
           "up_bid_slope", "up_ask_slope", "up_queue_top_bid",
           "up_imb5_change_500ms", "up_quote_intensity_5s",
           "up_total_bid_size", "up_total_ask_size",
           "dn_imb1", "dn_imb5", "dn_imb25", "dn_microprice", "dn_micro_dev_bps",
           "dn_bid_slope", "dn_ask_slope", "dn_queue_top_bid",
           "dn_imb5_change_500ms",
           "imb5_diff", "imb1_diff", "imb25_diff", "micro_dev_diff", "spread_diff",
           "vpin"]
ms_use = ms[ms_cols].drop_duplicates(subset=["slug", "fire_offset_s"], keep="first")
merged = merged.merge(ms_use, on=["slug", "fire_offset_s"], how="left")
log(f"  microstructure coverage: {merged['up_imb5'].notna().sum()}/{len(merged)}")


# ============== 5) Join hawkes_panel (asof at ws_us-1s) ==============
log("joining hawkes_panel")
hk = pd.read_parquet(f"{RES}/hawkes_panel.parquet")
hk = hk[hk.asset == "BTC"].copy()
hk["ts_us"] = hk["ts_us"].astype("int64")
hk = hk.sort_values("ts_us").reset_index(drop=True)
hk_use = hk[["ts_us", "lambda_total", "lambda_imbalance", "recent_burst"]].rename(
    columns={"lambda_total": "hawkes_lambda_total",
             "lambda_imbalance": "hawkes_lambda_imbalance",
             "recent_burst": "hawkes_recent_burst"})

merged = merged.sort_values("ws_us_eps").reset_index(drop=True)
merged = pd.merge_asof(
    merged, hk_use,
    left_on="ws_us_eps", right_on="ts_us",
    direction="backward", allow_exact_matches=True,
)
merged = merged.drop(columns=["ts_us"])
log(f"  hawkes coverage: {merged['hawkes_lambda_imbalance'].notna().sum()}/{len(merged)}")


# ============== 6) Join lee_mykland_panel (asof at ws_us-1s) ==============
log("joining lee_mykland_panel")
lm = pd.read_parquet(f"{RES}/lee_mykland_panel.parquet")
lm = lm[lm.asset == "BTC"].copy()
lm["ts_us"] = lm["ts_us"].astype("int64")
lm = lm.sort_values("ts_us").reset_index(drop=True)
lm_use = lm[["ts_us", "L_stat", "is_jump_01", "is_jump_05",
             "jump_dir_01", "jump_dir_05"]].rename(columns={"L_stat": "lm_L_stat"})

merged = merged.sort_values("ws_us_eps").reset_index(drop=True)
merged = pd.merge_asof(
    merged, lm_use,
    left_on="ws_us_eps", right_on="ts_us",
    direction="backward", allow_exact_matches=True,
)
merged = merged.drop(columns=["ts_us"])
log(f"  lm coverage: {merged['lm_L_stat'].notna().sum()}/{len(merged)}")


# ============== 7) Join vpin_panel ==============
log("joining vpin_panel")
vp = pd.read_parquet(f"{RES}/vpin_panel.parquet")
vp = vp[vp.asset == "BTC"].copy()
vp["ts_us"] = vp["ts_us"].astype("int64")
vp = vp.sort_values("ts_us").reset_index(drop=True)

merged = merged.sort_values("ws_us_eps").reset_index(drop=True)
merged = pd.merge_asof(
    merged, vp[["ts_us", "vpin_value", "vpin_zscore"]],
    left_on="ws_us_eps", right_on="ts_us",
    direction="backward", allow_exact_matches=True,
)
merged = merged.drop(columns=["ts_us"])
log(f"  vpin coverage: {merged['vpin_zscore'].notna().sum()}/{len(merged)}")


# ============== 8) Join f7_rsi at ws_s + sms panel if available ==============
# v3 fires DON'T have f7_rsi_at_ws — need from hybrid_features_15m
log("attaching f7_rsi_at_ws from hybrid_features_15m where available")
hyb = pd.read_parquet(f"{RES}/hybrid_features_15m.parquet")
hyb = hyb[hyb.asset == "BTC"].copy()
if "f7_rsi_at_ws" in hyb.columns:
    hyb_f7 = hyb[["slug", "f7_rsi_at_ws"]].drop_duplicates("slug")
    merged = merged.merge(hyb_f7, on="slug", how="left")
    log(f"  f7_rsi coverage: {merged['f7_rsi_at_ws'].notna().sum()}/{len(merged)}")


# SMS panel for sms_rsi / cvd
log("joining sms_panel_15m_v2_fixed (asof at ws_us-1s)")
sms = pd.read_parquet(f"{RES}/sms_panel_15m_v2_fixed.parquet")
sms = sms[sms.asset == "BTC"].copy()
sms["ts_us"] = sms["ts_us"].astype("int64")
sms = sms.sort_values("ts_us").reset_index(drop=True)
sms_cols = ["ts_us", "rsi_14", "cvd", "cvd_sign",
            "liquidity_up", "liquidity_dn",
            "trend_strength_raw", "trend_strength_pct", "system_confidence"]
sms_use = sms[sms_cols].rename(columns={
    "rsi_14": "sms_rsi_14", "cvd": "sms_cvd", "cvd_sign": "sms_cvd_sign",
    "liquidity_up": "sms_liq_up", "liquidity_dn": "sms_liq_dn",
    "trend_strength_raw": "sms_trend_strength",
    "trend_strength_pct": "sms_trend_strength_pct",
    "system_confidence": "sms_sys_conf",
})
merged = merged.sort_values("ws_us_eps").reset_index(drop=True)
merged = pd.merge_asof(
    merged, sms_use,
    left_on="ws_us_eps", right_on="ts_us",
    direction="backward", allow_exact_matches=True,
)
merged = merged.drop(columns=["ts_us"])
log(f"  sms coverage: {merged['sms_rsi_14'].notna().sum()}/{len(merged)}")


# ============== 9) Save ==============
merged = merged.sort_values("fire_us").reset_index(drop=True)
log(f"final shape: {merged.shape}")
merged.to_parquet(OUT, index=False)
log(f"WROTE -> {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB)")

# Date summary
print()
print(f"effective panel coverage (rows where regime + microprice both present):")
both = merged[merged["trend_slope_30m"].notna() & merged["mp_skew"].notna()]
print(f"  rows: {len(both)} ({len(both)/len(merged)*100:.1f}%)")
print(f"  date range: {both.fire_date.min()} to {both.fire_date.max()}")
print(f"  unique days: {both.fire_date.dt.date.nunique()}")
