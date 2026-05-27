"""Build the master BTC 15m sniper-search panel.

Joins hybrid_features_15m (BTC only) with all clean feature panels,
expands rows into UP and DOWN candidates, computes per-row PnL with
engine_v2.LegacyConfig.

Also REBUILDS g_trend_slope_with from the v2_fixed regime panel (the
load-bearing gate for the 15m family that was previously derived from
the leaky panel).

Output: data/v4/canonical/_results/sniper_btc15m_master.parquet
"""
import os
import sys
import time
import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
from load import asof_strict  # noqa: F401

RES = "data/v4/canonical/_results"
OUT = f"{RES}/sniper_btc15m_master.parquet"
LEGACY_FEE = 0.02
NOTIONAL = 25.0

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


# ---------------------------------------------------------------- load
log("loading hybrid_features_15m")
hyb = pd.read_parquet(f"{RES}/hybrid_features_15m.parquet")
btc = hyb[hyb["asset"] == "BTC"].copy()
log(f"BTC 15m hybrid rows: {len(btc)}")

# Filter to fills available on at least one side
btc = btc[btc["up_fill_ok"] | btc["dn_fill_ok"]].copy()
log(f"after fill_ok filter: {len(btc)}")

# Add ws_s + slot_start_s
btc["slot_start_s"] = (btc["slot_start_us"] // 1_000_000).astype("int64")
btc["ws_s_check"] = btc["slot_start_s"] - 900
# verify ws_s column matches
assert (btc["ws_s_check"] == btc["ws_s"]).all(), "ws_s column mismatch"

# ---------------------------------------------------------------- doubled panel: UP / DOWN
log("doubling panel into UP and DOWN candidates")
up = btc.copy()
up["direction"] = "UP"
up["entry_vwap"] = up["up_vwap"]
up["fill_ok"] = up["up_fill_ok"]
up["dir_sign"] = 1
dn = btc.copy()
dn["direction"] = "DOWN"
dn["entry_vwap"] = dn["dn_vwap"]
dn["fill_ok"] = dn["dn_fill_ok"]
dn["dir_sign"] = -1
mp = pd.concat([up, dn], ignore_index=True)
log(f"doubled rows: {len(mp)}")

# Filter fills only - if no fill, no trade
mp = mp[mp["fill_ok"]].copy()
log(f"after directional fill filter: {len(mp)}")

# ---------------------------------------------------------------- PnL
log("computing PnL with engine_v2 LegacyConfig")
shares = NOTIONAL / mp["entry_vwap"]
mp["won"] = (
    ((mp["outcome"] == "Up") & (mp["direction"] == "UP")) |
    ((mp["outcome"] == "Down") & (mp["direction"] == "DOWN"))
).astype(int)
# Legacy 2% on profit only
gross_win = shares * (1.0 - mp["entry_vwap"])
fee_win = gross_win * LEGACY_FEE
mp["pnl_legacy_usd"] = np.where(mp["won"] == 1, gross_win - fee_win, -NOTIONAL)
mp.loc[~mp["fill_ok"], "pnl_legacy_usd"] = np.nan

# ---------------------------------------------------------------- join regime panel
log("joining regime_panel_15m_v2_fixed")
rg = pd.read_parquet(f"{RES}/regime_panel_15m_v2_fixed.parquet")
rg = rg[rg["asset"] == "BTC"].copy()
rg["ts_us"] = rg["ts_us"].astype("int64")
rg = rg.sort_values("ts_us").reset_index(drop=True)
# strict asof: use bar that ENDED at-or-before ws_s
# ws_s is in seconds; convert
mp["ws_us"] = mp["ws_s"] * 1_000_000
# asof merge requires sorted left
mp = mp.sort_values("ws_us").reset_index(drop=True)
# We do asof join by ts_us <= ws_us - 1s (causal epsilon)
mp["ws_us_eps"] = mp["ws_us"] - 1_000_000
merged = pd.merge_asof(
    mp,
    rg[["ts_us", "trend_slope_30m", "regime_label", "regime_score", "adx_14",
        "plus_di_14", "minus_di_14", "atr_14", "realized_vol_60m",
        "range_compression", "tr_ema_stack_score"]].rename(columns={
            "tr_ema_stack_score": "regime_tr_ema_stack_score",
        }),
    left_on="ws_us_eps",
    right_on="ts_us",
    direction="backward",
)
log(f"regime merge: {merged['trend_slope_30m'].notna().sum()} / {len(merged)} have trend_slope")

# ---------------------------------------------------------------- join SMS panel
log("joining sms_panel_15m_v2_fixed")
sms = pd.read_parquet(f"{RES}/sms_panel_15m_v2_fixed.parquet")
sms = sms[sms["asset"] == "BTC"].copy()
sms["ts_us"] = sms["ts_us"].astype("int64")
sms = sms.sort_values("ts_us").reset_index(drop=True)
sms_cols = ["ts_us", "rsi_14", "cvd", "cvd_sign", "liquidity_up", "liquidity_dn",
            "trend_strength_raw", "trend_strength_pct", "system_confidence",
            "choch_buy", "choch_sell", "bos_buy", "bos_sell",
            "bars_since_bos_buy", "bars_since_bos_sell"]
sms_use = sms[sms_cols].rename(columns={
    "rsi_14": "sms_rsi_14",
    "cvd": "sms_cvd",
    "cvd_sign": "sms_cvd_sign",
    "liquidity_up": "sms_liq_up",
    "liquidity_dn": "sms_liq_dn",
    "trend_strength_raw": "sms_trend_strength",
    "trend_strength_pct": "sms_trend_strength_pct",
    "system_confidence": "sms_sys_conf",
    "choch_buy": "sms_choch_buy", "choch_sell": "sms_choch_sell",
    "bos_buy": "sms_bos_buy", "bos_sell": "sms_bos_sell",
    "bars_since_bos_buy": "sms_bars_since_bos_buy",
    "bars_since_bos_sell": "sms_bars_since_bos_sell",
})
merged = pd.merge_asof(
    merged.sort_values("ws_us_eps"),
    sms_use,
    left_on="ws_us_eps",
    right_on="ts_us",
    direction="backward",
    suffixes=("", "_sms"),
)
log(f"sms merge: {merged['sms_rsi_14'].notna().sum()} / {len(merged)} have sms_rsi")

# ---------------------------------------------------------------- join microstructure (per fire_us)
log("joining microstructure_panel")
ms = pd.read_parquet(f"{RES}/microstructure_panel.parquet")
ms = ms[(ms["asset"] == "BTC") & (ms["tf"] == "15m")].copy()
ms_cols = ["slug", "fire_offset_s",
           "up_imb1", "up_imb5", "up_imb25", "up_microprice", "up_micro_dev_bps",
           "up_bid_slope", "up_ask_slope", "up_queue_top_bid",
           "up_imb5_change_500ms", "up_quote_intensity_5s",
           "up_total_bid_size", "up_total_ask_size",
           "dn_imb1", "dn_imb5", "dn_imb25", "dn_microprice", "dn_micro_dev_bps",
           "dn_bid_slope", "dn_ask_slope", "dn_queue_top_bid",
           "imb5_diff", "imb1_diff", "imb25_diff", "micro_dev_diff", "spread_diff",
           "vpin"]
merged = merged.merge(
    ms[ms_cols],
    on=["slug", "fire_offset_s"],
    how="left",
)
log(f"microstructure merge: {merged['up_imb5'].notna().sum()} / {len(merged)} have up_imb5")

# ---------------------------------------------------------------- microprice
log("joining microprice_panel")
mppanel = pd.read_parquet(f"{RES}/microprice_panel.parquet")
mppanel = mppanel[(mppanel["asset"] == "BTC") & (mppanel["tf"] == "15m")].copy()
mppanel_cols = ["slug", "fire_offset_s", "mp_skew", "mp_imbalance",
                "mp_weighted_skew", "mp_weighted_imbalance",
                "mp_up_dev_bps", "mp_dn_dev_bps",
                "mp_skew_change_500ms", "mp_up_dev_change_500ms",
                "mp_dn_dev_change_500ms"]
merged = merged.merge(mppanel[mppanel_cols], on=["slug", "fire_offset_s"], how="left")
log(f"microprice merge: {merged['mp_skew'].notna().sum()} / {len(merged)} have mp_skew")

# ---------------------------------------------------------------- Hawkes (at ws_s)
log("joining hawkes_panel (asof at ws_us-1s)")
hk = pd.read_parquet(f"{RES}/hawkes_panel.parquet")
hk = hk[hk["asset"] == "BTC"].copy()
hk = hk.sort_values("ts_us").reset_index(drop=True)
merged = pd.merge_asof(
    merged.sort_values("ws_us_eps"),
    hk[["ts_us", "lambda_total", "lambda_imbalance", "recent_burst"]].rename(
        columns={"lambda_total": "hawkes_lambda_total",
                 "lambda_imbalance": "hawkes_lambda_imbalance",
                 "recent_burst": "hawkes_recent_burst"}),
    left_on="ws_us_eps",
    right_on="ts_us",
    direction="backward",
    suffixes=("", "_hk"),
)

# ---------------------------------------------------------------- Lee-Mykland (at ws_s)
log("joining lee_mykland_panel (asof at ws_us-1s)")
lm = pd.read_parquet(f"{RES}/lee_mykland_panel.parquet")
lm = lm[lm["asset"] == "BTC"].copy()
lm = lm.sort_values("ts_us").reset_index(drop=True)
merged = pd.merge_asof(
    merged.sort_values("ws_us_eps"),
    lm[["ts_us", "L_stat", "is_jump_01", "is_jump_05", "is_jump_extreme",
        "jump_dir_01", "jump_dir_05", "jump_dir_extreme"]].rename(columns={
            "L_stat": "lm_L_stat",
        }),
    left_on="ws_us_eps",
    right_on="ts_us",
    direction="backward",
    suffixes=("", "_lm"),
)

# ---------------------------------------------------------------- VPIN (at ws_s)
log("joining vpin_panel (asof at ws_us-1s)")
vp = pd.read_parquet(f"{RES}/vpin_panel.parquet")
vp = vp[vp["asset"] == "BTC"].copy()
vp = vp.sort_values("ts_us").reset_index(drop=True)
merged = pd.merge_asof(
    merged.sort_values("ws_us_eps"),
    vp[["ts_us", "vpin_value", "vpin_zscore"]],
    left_on="ws_us_eps",
    right_on="ts_us",
    direction="backward",
    suffixes=("", "_vp"),
)

# Drop ts_us columns from merges
ts_cols = [c for c in merged.columns if c == "ts_us" or c.startswith("ts_us_")]
merged = merged.drop(columns=ts_cols, errors="ignore")

# Add f7_rsi at ws_s (already in hybrid_features as f7_rsi_at_ws)
log(f"final merged shape: {merged.shape}")
log(f"f7_rsi_at_ws coverage: {merged['f7_rsi_at_ws'].notna().sum()} / {len(merged)}")

# ---------------------------------------------------------------- save
merged["fire_date"] = pd.to_datetime(merged["fire_us"], unit="us", utc=True)
log("saving master panel")
merged.to_parquet(OUT, index=False)
log(f"DONE → {OUT} ({os.path.getsize(OUT)/1e6:.1f} MB)")
