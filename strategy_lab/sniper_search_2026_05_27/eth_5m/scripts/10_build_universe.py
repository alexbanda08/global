"""
Build the ETH 5m sniper universe.

INPUT:
  - v3 fires (133k, 33d, 48 pre-joined gates)  [PRIMARY]
  - microprice panel (31.7d, slug+offset)      [join: mp_skew, mp_imbalance, deviations]
  - microstructure panel (23d, slug+offset)    [join: up/dn ask size, depth_2pct, eff_spread → book-depth gate]
  - master_gate_v2 panel (24.8d, slug+offset)  [join: F7 RSI, vol_regime, hurst, markov pass, ribbon]
  - regime_5m_v2 panel (28d, asof ts_us≤fire_us) [join: regime_label, regime_score]

OUTPUT:
  data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet (long-format per fire)

DERIVED gates (added in this script):
  - g_book_depth_supports_250       chosen-side total_ask_size > $1500 (6x notional)
  - g_book_depth_supports_250_tight chosen-side > $3000 (12x)
  - g_book_depth_supports_25        chosen-side > $150  (6x)
  - g_mp_skew_with                  chosen-direction mp_skew sign match
  - g_mp_skew_strong_with           |mp_skew| > 0.05 + sign match
  - g_mp_no_extreme                 |mp_up_dev_bps| < 150 AND |mp_dn_dev_bps| < 150
  - g_imb5_with                     chosen-side imb5 > 0
  - g_imb5_strong_with              chosen-side imb5 > 0.3
  - g_regime_trend                  regime_label in {'strong_trend','trending'}
  - g_regime_chop                   regime_label in {'chop','squeeze'}
  - g_regime_score_high             regime_score >= 0.7
  - g_vol_regime_normal_or_high     vol_regime in {1,2} (skip 0=low)
  - g_vol_regime_low                vol_regime == 0
  - g_f7_with                       F7 RSI sign matches direction
  - g_f7_extreme                    rsi < 30 or > 70
  - g_hurst_trending                hurst_100s >= 0.50
  - g_eff_spread_tight              chosen eff_spread_25 <= 2%
"""
import sys, os
import pandas as pd
import numpy as np

R = "data/v4/canonical/_results"
F_V3 = f"{R}/_full_window_v3_2026_05_27/oos_fires_ETH_5m_full_v3.parquet"
F_MP = f"{R}/microprice_panel.parquet"
F_MS = f"{R}/microstructure_panel.parquet"
F_RG = f"{R}/regime_panel_5m_v2_fixed.parquet"
F_MG = f"{R}/master_gate_features_v2.parquet"
OUT = f"{R}/_sniper_eth5m_v3_universe.parquet"

ASSET, TF = "ETH", "5m"

def main():
    print(f"== Load v3 fires {F_V3}")
    fires = pd.read_parquet(F_V3)
    print(f"   n={len(fires):,}  baseline WR={fires['won'].mean():.4f}  $/tr={fires['pnl_legacy_usd'].mean():+.4f}")
    fires["dir_sign"] = np.where(fires["direction"] == "UP", 1, -1)

    # ---- microprice (31.7d)
    print(f"\n== Load microprice")
    mp = pd.read_parquet(F_MP)
    mp = mp[(mp["asset"] == ASSET) & (mp["tf"] == TF)].copy()
    mp_cols_keep = ["slug","fire_offset_s","mp_up_simple","mp_dn_simple",
                    "mp_up_dev_bps","mp_dn_dev_bps","mp_up_weighted_dev_bps","mp_dn_weighted_dev_bps",
                    "mp_skew","mp_imbalance"]
    mp_cols_keep = [c for c in mp_cols_keep if c in mp.columns]
    mp = mp[mp_cols_keep].drop_duplicates(subset=["slug","fire_offset_s"])
    fires = fires.merge(mp, on=["slug","fire_offset_s"], how="left")
    cov = fires["mp_skew"].notna().mean()
    print(f"   microprice merged. Coverage on fires: {cov*100:.1f}%")

    # ---- microstructure (23d)
    print(f"\n== Load microstructure")
    ms = pd.read_parquet(F_MS)
    ms = ms[(ms["asset"] == ASSET) & (ms["tf"] == TF)].copy()
    ms_cols_keep = ["slug","fire_offset_s",
                    "up_ask0","up_bid0","up_spread_bps","up_imb1","up_imb5","up_imb25",
                    "up_eff_spread_25","up_depth_2pct","up_total_ask_size","up_total_bid_size",
                    "dn_ask0","dn_bid0","dn_spread_bps","dn_imb1","dn_imb5","dn_imb25",
                    "dn_eff_spread_25","dn_depth_2pct","dn_total_ask_size","dn_total_bid_size"]
    ms_cols_keep = [c for c in ms_cols_keep if c in ms.columns]
    ms = ms[ms_cols_keep].drop_duplicates(subset=["slug","fire_offset_s"])
    fires = fires.merge(ms, on=["slug","fire_offset_s"], how="left")
    cov_ms = fires["up_total_ask_size"].notna().mean()
    print(f"   microstructure merged. Coverage on fires: {cov_ms*100:.1f}%")

    # ---- master_gate_v2 (24.8d) — pick a select set: F7 RSI, vol_regime, hurst, markov, ribbon_alignment
    print(f"\n== Load master_gate_v2")
    mg = pd.read_parquet(F_MG)
    mg = mg[(mg["asset"] == ASSET) & (mg["tf"] == TF)].copy()
    mg_cols_pick = [
        "slug","fire_offset_s",
        "f7_rsi_at_ws","vwap_since_open_bps",
        "ribbon_alignment_pct","rv_60s","rv_300s","rv_900s","rv_3600s","rv_pct_24h",
        "vol_regime","hurst_100s","hurst_300s",
        "markov_pass_w20_1m_voladaptive","markov_pass_w20_1m_fixed",
        "markov_pass_w20_5m_voladaptive","markov_pass_w20_5m_fixed",
    ]
    mg_cols_pick = [c for c in mg_cols_pick if c in mg.columns]
    mg = mg[mg_cols_pick].drop_duplicates(subset=["slug","fire_offset_s"])
    fires = fires.merge(mg, on=["slug","fire_offset_s"], how="left")
    cov_mg = fires["f7_rsi_at_ws"].notna().mean() if "f7_rsi_at_ws" in fires.columns else 0
    print(f"   master_gate_v2 merged. Coverage on fires: {cov_mg*100:.1f}%")

    # ---- regime_5m_v2 (28d, asof)
    print(f"\n== Load regime_5m_v2 (asof)")
    rg = pd.read_parquet(F_RG)
    rg = rg[(rg["asset"] == ASSET) & (rg["tf"] == TF)].copy().sort_values("ts_us")
    rg_cols = ["ts_us","regime_label","regime_score","adx_14","tr_ema_stack_score",
               "bb_width_60s","realized_vol_60m","range_compression","trend_slope_30m"]
    rg_cols = [c for c in rg_cols if c in rg.columns]
    rg = rg[rg_cols].rename(columns={c: f"rg_{c}" for c in rg_cols if c != "ts_us"})
    # asof merge backward — feature at-or-before fire_us
    fires = fires.sort_values("fire_us")
    fires = pd.merge_asof(fires, rg, left_on="fire_us", right_on="ts_us", direction="backward")
    cov_rg = fires["rg_regime_label"].notna().mean()
    print(f"   regime_v2 asof merged. Coverage on fires: {cov_rg*100:.1f}%")

    # ---- chosen-direction derived columns
    is_up = (fires["direction"] == "UP")
    fires["chosen_total_size"] = np.where(is_up, fires["up_total_ask_size"], fires["dn_total_ask_size"])
    fires["chosen_depth_2pct"] = np.where(is_up, fires["up_depth_2pct"], fires["dn_depth_2pct"])
    fires["chosen_spread_bps"] = np.where(is_up, fires["up_spread_bps"], fires["dn_spread_bps"])
    fires["chosen_eff_spread_25"] = np.where(is_up, fires["up_eff_spread_25"], fires["dn_eff_spread_25"])
    fires["chosen_imb5"] = np.where(is_up, fires["up_imb5"], fires["dn_imb5"])
    fires["chosen_imb25"] = np.where(is_up, fires["up_imb25"], fires["dn_imb25"])
    fires["chosen_ask0"] = np.where(is_up, fires["up_ask0"], fires["dn_ask0"])

    # ---- derived gates
    print(f"\n== Derive gates")
    # Book depth (chosen side $ available)
    fires["g_book_depth_supports_250"] = (fires["chosen_total_size"].fillna(0) > 1500.0).astype("Int8")
    fires["g_book_depth_supports_250_tight"] = (fires["chosen_total_size"].fillna(0) > 3000.0).astype("Int8")
    fires["g_book_depth_supports_25"] = (fires["chosen_total_size"].fillna(0) > 150.0).astype("Int8")
    # Eff spread tight
    fires["g_eff_spread_tight"] = (fires["chosen_eff_spread_25"].fillna(1.0) < 0.02).astype("Int8")
    # Microprice gates
    mp_skew_sign = np.sign(fires["mp_skew"].fillna(0))
    fires["g_mp_skew_with"] = (mp_skew_sign == fires["dir_sign"]).astype("Int8")
    fires["g_mp_skew_strong_with"] = ((np.abs(fires["mp_skew"].fillna(0)) > 0.05) &
                                       (mp_skew_sign == fires["dir_sign"])).astype("Int8")
    fires["g_mp_no_extreme"] = ((np.abs(fires["mp_up_dev_bps"].fillna(0)) < 150) &
                                (np.abs(fires["mp_dn_dev_bps"].fillna(0)) < 150)).astype("Int8")
    # Imbalance gates
    fires["g_imb5_with"] = (fires["chosen_imb5"].fillna(0) > 0).astype("Int8")
    fires["g_imb5_strong_with"] = (fires["chosen_imb5"].fillna(0) > 0.3).astype("Int8")
    fires["g_imb25_with"] = (fires["chosen_imb25"].fillna(0) > 0).astype("Int8")
    # Regime gates
    if "rg_regime_label" in fires.columns:
        fires["g_regime_trend"] = fires["rg_regime_label"].isin(["strong_trend","trending"]).astype("Int8")
        fires["g_regime_chop"] = fires["rg_regime_label"].isin(["chop","squeeze"]).astype("Int8")
    if "rg_regime_score" in fires.columns:
        fires["g_regime_score_high"] = (fires["rg_regime_score"].fillna(0) >= 0.7).astype("Int8")
    # Vol regime
    if "vol_regime" in fires.columns:
        fires["g_vol_regime_normal_or_high"] = fires["vol_regime"].isin([1,2]).astype("Int8")
        fires["g_vol_regime_low"] = (fires["vol_regime"] == 0).astype("Int8")
    # Hurst
    if "hurst_100s" in fires.columns:
        fires["g_hurst_trending"] = (fires["hurst_100s"].fillna(0) >= 0.50).astype("Int8")
        fires["g_hurst_strong"] = (fires["hurst_100s"].fillna(0) >= 0.55).astype("Int8")
    # F7 RSI gates
    if "f7_rsi_at_ws" in fires.columns:
        # UP momentum if RSI > 50, DOWN if RSI < 50
        fires["g_f7_with"] = (((fires["f7_rsi_at_ws"].fillna(50) > 50) & is_up) |
                              ((fires["f7_rsi_at_ws"].fillna(50) < 50) & ~is_up)).astype("Int8")
        fires["g_f7_extreme"] = ((fires["f7_rsi_at_ws"].fillna(50) < 30) |
                                  (fires["f7_rsi_at_ws"].fillna(50) > 70)).astype("Int8")
        fires["g_f7_strong"] = (((fires["f7_rsi_at_ws"].fillna(50) > 60) & is_up) |
                                 ((fires["f7_rsi_at_ws"].fillna(50) < 40) & ~is_up)).astype("Int8")
    # Markov
    for mk in ["markov_pass_w20_1m_voladaptive","markov_pass_w20_1m_fixed",
               "markov_pass_w20_5m_voladaptive","markov_pass_w20_5m_fixed"]:
        if mk in fires.columns:
            fires[f"g_{mk}"] = (fires[mk].fillna(0) > 0).astype("Int8")

    # Time helpers
    fires["fire_dt"] = pd.to_datetime(fires["fire_us"], unit="us")
    fires["day"] = fires["fire_dt"].dt.date
    fires["hour"] = fires["fire_dt"].dt.hour
    fires["offset_bin"] = pd.cut(fires["fire_offset_s"],
                                 bins=[-1, 60, 150, 240, 300],
                                 labels=["0-60","60-150","150-240","240-300"]).astype(str)

    # Drop the float helper cols + heavy "rg_ts_us" if present
    drop = [c for c in fires.columns if c == "ts_us"]
    if drop:
        fires = fires.drop(columns=drop)

    print(f"\n== Final shape: {fires.shape}")
    print(f"   days: {fires['day'].nunique()}")
    g_cols = [c for c in fires.columns if c.startswith("g_")]
    print(f"   total g_ cols: {len(g_cols)}")
    print(g_cols)
    print()
    print("write ->", OUT)
    fires.to_parquet(OUT)
    print("done")

if __name__ == "__main__":
    main()
