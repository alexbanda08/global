"""V6 ETH 5m universe build.

Adds pre-window signal features anchored at ws_s (NOT fire_us):
  - F7 RSI at ws_s (from master_gate_features_v2 -> f7_rsi_at_ws)
  - Markov M1V state at ws_s (from master_gate_features_v2 -> g_markov_with)
  - mp_skew, mp_skew_change_500ms anchored at ws_s (asof from microprice_panel)
  - Regime label at ws_s (asof from regime_panel_v2_fixed)
  - SMS choch/bos at ws_s
  - microstructure depth (for fill-time skip later)

Plus all v3 fire columns (offsets 30/60/90/120/150/...) + microprice at fire_offset_s.

Output: data/v4/canonical/_results/_sniper_eth5m_v6_universe.parquet

Convention:
- ws_s_us = ws_s * 1_000_000 (microsecond UTC at ws_s)
- pre-window features = asof-join feature panel ts_us <= ws_s_us (strict causal)
- fire-time features = at fire_us (already in v3 fires)
- Differentiate columns with `_at_ws` suffix vs `_at_fire` suffix
"""

import sys
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
sys.path.insert(0, os.path.join(ROOT, "data/v4/canonical"))

V3_FIRES = os.path.join(ROOT, "data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_5m_full_v3.parquet")
MG = os.path.join(ROOT, "data/v4/canonical/_results/master_gate_features_v2.parquet")
MP = os.path.join(ROOT, "data/v4/canonical/_results/microprice_panel.parquet")
RG = os.path.join(ROOT, "data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet")
MS = os.path.join(ROOT, "data/v4/canonical/_results/microstructure_panel.parquet")
SMS = os.path.join(ROOT, "data/v4/canonical/_results/sms_panel_5m_v2_fixed.parquet")
VH = os.path.join(ROOT, "data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")

OUT = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v6_universe.parquet")


def main():
    print(f"Loading v3 fires {V3_FIRES} ...")
    fires = pd.read_parquet(V3_FIRES)
    print(f"  shape: {fires.shape}")
    print(f"  baseline WR: {fires['won'].mean():.4f}")
    fires["ws_s_us"] = fires["ws_s"].astype(np.int64) * 1_000_000

    # ---- 1. Merge master_gate_features_v2 (pre-joined fire-time features) ----
    # Use as ws_s anchored: f7_rsi_at_ws, g_markov_with
    print(f"\nLoading master_gate {MG} ...")
    mg = pd.read_parquet(MG)
    eth5_mg = mg[(mg.asset == "ETH") & (mg.tf == "5m")].copy()
    print(f"  ETH 5m mg rows: {len(eth5_mg):,}")
    # mg is indexed by (slug, fire_offset_s) — join on those
    mg_cols_keep = [
        "slug", "fire_offset_s",
        "f7_rsi_at_ws",
        "g_markov_with",
        "vwap_since_open_bps",
        "mp_skew", "mp_skew_change_500ms",
        "mp_weighted_skew", "mp_imbalance", "mp_weighted_imbalance",
        "up_imb5", "dn_imb5", "up_imb5_change_500ms",
        "hurst_300s", "vol_regime",
        "vpin_zscore", "hawkes_lambda_imbalance",
        "g_lm_high_stat", "g_hurst_trending", "g_vol_high", "g_vol_contracting",
        "g_imb5_strong_with", "g_queue_top_high", "g_imb_change_with",
        "g_mp_no_extreme", "g_mp_change_with", "g_mp_skew_with",
        "g_hawkes_imbalance_with", "g_vwap_ge_50_le_85",
        "g_trend_slope_with", "g_within_dev", "g_dev_extreme",
        "rv_60s", "rv_300s",
    ]
    mg_cols_keep = [c for c in mg_cols_keep if c in eth5_mg.columns]
    fires = fires.merge(
        eth5_mg[mg_cols_keep].drop_duplicates(["slug", "fire_offset_s"]),
        on=["slug", "fire_offset_s"], how="left",
        suffixes=("", "_mg"),
    )
    print(f"  after mg join: {fires.shape}")

    # ---- 2. Asof-merge microprice at ws_s anchor (pre-window) ----
    # microprice_panel has fire_offset_s=15 minimum; we want closest at-or-before ws_s_us.
    # Convert MP to time-series view: each (slug, fire_offset_s) row has fire_us.
    # ws_s = fire_us - fire_offset_s * 1e6 for that row. So mp rows ALREADY tied to slugs.
    # For pre-window we need mp evaluated AT ws_s (offset=0 logical). But mp only goes
    # back to offset=15. So we asof-join from the SAME slug, picking the smallest offset
    # available <= ws_s_us. Since offset increases through window, offset=15 IS the earliest.
    # The mp_skew_at_ws ≈ mp_skew at fire_offset=15s post slot start = 15s INTO window.
    # That's NOT at ws_s (= slot_start - window_s). True pre-window mp would need
    # microprice data BEFORE slot_start.

    # Reality: the v3 fire row's mp at fire_offset_s=120 reflects book at fire_us.
    # To get a PRE-WINDOW microprice (at ws_s), we'd need to use the PRIOR slug's
    # microprice at its offset_s = window_s - X (i.e. near end of prior window).
    # For simplicity: use master_gate's mp_skew which IS at fire_us. Call that "at_fire".
    # For "at_ws" approximation: take the mp_skew of the prior slug at LARGEST offset.

    # Actually master_gate has mp_skew already at_fire. Let's also build "mp_skew_at_ws"
    # via asof: load full microprice panel, asof on ws_s_us using slugs of THIS slug's prior.
    # Compute prior_slug_ws_s: ws_s = current_slot_start - 300; prior_slot_start = ws_s; prior_slug fires from prior_slot_start_us with offset=270 ≈ end of prior window.
    print("\nBuilding prior-window microprice for pre-window mp_skew_at_ws ...")
    mp_all = pd.read_parquet(MP)
    eth5_mp = mp_all[(mp_all.asset == "ETH") & (mp_all.tf == "5m")][
        ["slug", "fire_offset_s", "fire_us", "mp_skew", "mp_skew_change_500ms",
         "mp_up_dev_bps", "mp_dn_dev_bps", "mp_imbalance"]
    ].copy()
    eth5_mp = eth5_mp.sort_values(["slug", "fire_us"]).reset_index(drop=True)
    # For each fire's ws_s_us, asof-pick microprice row with fire_us <= ws_s_us across ALL ETH 5m slugs.
    eth5_mp_sorted = eth5_mp.sort_values("fire_us").reset_index(drop=True)
    fires_sorted = fires[["slug", "ws_s_us", "fire_us"]].copy().sort_values("ws_s_us").reset_index(drop=True)
    # asof merge globally (no by). But we want SAME slug or prior slug — since slugs are sequential
    # by slot_start, the prior slug's late-window mp WILL be at ts < ws_s of current slug. So a global asof works.
    fires_sorted = pd.merge_asof(
        fires_sorted, eth5_mp_sorted[["fire_us", "mp_skew", "mp_skew_change_500ms", "mp_imbalance"]],
        left_on="ws_s_us", right_on="fire_us", direction="backward", tolerance=900_000_000,  # 900s = 15min
        suffixes=("", "_mp"),
    )
    fires_sorted.rename(columns={
        "mp_skew": "mp_skew_at_ws",
        "mp_skew_change_500ms": "mp_skew_change_500ms_at_ws",
        "mp_imbalance": "mp_imbalance_at_ws",
    }, inplace=True)
    fires_sorted.drop(columns=["fire_us_mp"], errors="ignore", inplace=True)
    fires = fires.merge(
        fires_sorted[["slug", "ws_s_us", "mp_skew_at_ws", "mp_skew_change_500ms_at_ws", "mp_imbalance_at_ws"]].drop_duplicates(["slug","ws_s_us"]),
        on=["slug", "ws_s_us"], how="left",
    )
    print(f"  after mp@ws asof: {fires.shape}, mp_skew_at_ws non-null: {fires['mp_skew_at_ws'].notna().sum()}")

    # ---- 3. Regime label at ws_s (asof) ----
    print("\nAsof-joining regime panel at ws_s ...")
    rg = pd.read_parquet(RG)
    eth_rg = rg[rg.asset == "ETH"][["ts_us", "regime_label", "regime_score", "trend_slope_30m",
                                     "tr_ema_stack_score", "atr_14", "adx_14"]].copy()
    eth_rg = eth_rg.sort_values("ts_us").reset_index(drop=True)
    fires_sorted2 = fires[["slug", "ws_s_us"]].copy().sort_values("ws_s_us").reset_index(drop=True)
    fires_sorted2 = pd.merge_asof(
        fires_sorted2, eth_rg, left_on="ws_s_us", right_on="ts_us", direction="backward",
        tolerance=900_000_000,
    )
    fires_sorted2 = fires_sorted2.rename(columns={
        "regime_label": "regime_label_at_ws", "regime_score": "regime_score_at_ws",
        "trend_slope_30m": "trend_slope_30m_at_ws", "tr_ema_stack_score": "tr_ema_stack_at_ws",
        "atr_14": "atr_14_at_ws", "adx_14": "adx_14_at_ws",
    })
    fires_sorted2.drop(columns=["ts_us"], errors="ignore", inplace=True)
    fires = fires.merge(
        fires_sorted2.drop_duplicates(["slug", "ws_s_us"]),
        on=["slug", "ws_s_us"], how="left",
    )
    print(f"  after regime asof: regime_label_at_ws non-null: {fires['regime_label_at_ws'].notna().sum()}")

    # ---- 4. SMS at ws_s ----
    print("\nAsof-joining SMS panel at ws_s ...")
    sms = pd.read_parquet(SMS)
    eth_sms = sms[sms.asset == "ETH"][["ts_us", "choch_buy", "choch_sell", "bos_buy", "bos_sell",
                                        "liquidity_up", "liquidity_dn", "cvd_sign",
                                        "rsi_14", "trend_strength_raw"]].copy()
    eth_sms = eth_sms.sort_values("ts_us").reset_index(drop=True)
    fires_sorted3 = fires[["slug", "ws_s_us"]].copy().sort_values("ws_s_us").reset_index(drop=True)
    fires_sorted3 = pd.merge_asof(
        fires_sorted3, eth_sms, left_on="ws_s_us", right_on="ts_us", direction="backward",
        tolerance=900_000_000,
    )
    fires_sorted3 = fires_sorted3.rename(columns={
        "choch_buy": "choch_buy_at_ws", "choch_sell": "choch_sell_at_ws",
        "bos_buy": "bos_buy_at_ws", "bos_sell": "bos_sell_at_ws",
        "liquidity_up": "liquidity_up_at_ws", "liquidity_dn": "liquidity_dn_at_ws",
        "cvd_sign": "cvd_sign_at_ws", "rsi_14": "rsi_14_at_ws_sms",
        "trend_strength_raw": "trend_strength_raw_at_ws",
    })
    fires_sorted3.drop(columns=["ts_us"], errors="ignore", inplace=True)
    fires = fires.merge(
        fires_sorted3.drop_duplicates(["slug", "ws_s_us"]),
        on=["slug", "ws_s_us"], how="left",
    )

    # ---- 5. Microstructure (depth, spread) at fire_us via (slug, fire_offset_s) merge ----
    print("\nMerging microstructure at fire_us ...")
    ms = pd.read_parquet(MS)
    eth5_ms = ms[(ms.asset == "ETH") & (ms.tf == "5m")][
        ["slug", "fire_offset_s", "up_total_ask_size", "dn_total_ask_size",
         "up_depth_2pct", "dn_depth_2pct", "up_spread_bps", "dn_spread_bps",
         "up_eff_spread_25", "dn_eff_spread_25"]
    ].drop_duplicates(["slug", "fire_offset_s"]).copy()
    fires = fires.merge(eth5_ms, on=["slug", "fire_offset_s"], how="left")
    print(f"  after ms join: {fires.shape}")

    # Chosen-direction depth
    is_up = (fires["direction"] == "UP")
    fires["chosen_total_size"] = np.where(is_up, fires["up_total_ask_size"], fires["dn_total_ask_size"])
    fires["chosen_spread_bps"] = np.where(is_up, fires["up_spread_bps"], fires["dn_spread_bps"])

    # ---- 6. Vol/hurst at fire ----
    print("\nMerging vol_hurst at fire ...")
    vh = pd.read_parquet(VH)
    print(f"  vh cols: {vh.columns.tolist()[:15]}")
    if "asset" in vh.columns:
        vh_eth = vh[vh.asset == "ETH"].copy()
    else:
        vh_eth = vh.copy()
    vh_cols = [c for c in vh_eth.columns if c not in ("asset", "tf", "fire_us", "outcome", "won", "pnl_legacy_usd")]
    if {"slug", "fire_offset_s"}.issubset(vh_eth.columns):
        vh_keep = ["slug", "fire_offset_s"] + [c for c in vh_cols if c not in ("slug","fire_offset_s")]
        vh_keep = list(dict.fromkeys(vh_keep))
        fires = fires.merge(vh_eth[vh_keep].drop_duplicates(["slug","fire_offset_s"]),
                            on=["slug","fire_offset_s"], how="left", suffixes=("","_vh"))

    # ---- 7. Direction-aware gate atoms ----
    # Conviction-based gates at ws_s
    # F7 RSI extreme matching direction
    f7 = fires["f7_rsi_at_ws"]
    fires["g_f7_with"] = ((is_up & (f7 < 35)) | (~is_up & (f7 > 65))).astype(int)
    fires["g_f7_extreme_with"] = ((is_up & (f7 < 25)) | (~is_up & (f7 > 75))).astype(int)
    fires["g_f7_strong_with"] = ((is_up & (f7 < 30)) | (~is_up & (f7 > 70))).astype(int)
    # F7 RSI within "trend" band aligned with direction
    fires["g_f7_trend_with"] = ((is_up & (f7 < 50)) | (~is_up & (f7 > 50))).astype(int)

    # mp_skew_at_ws aligned with direction
    mp_w = fires["mp_skew_at_ws"]
    fires["g_mp_skew_at_ws_with"] = ((is_up & (mp_w > 30)) | (~is_up & (mp_w < -30))).astype(int)
    fires["g_mp_skew_at_ws_strong"] = ((is_up & (mp_w > 80)) | (~is_up & (mp_w < -80))).astype(int)

    # mp_skew_change_500ms_at_ws aligned with direction
    mp_c = fires["mp_skew_change_500ms_at_ws"]
    fires["g_mp_change_at_ws_with"] = ((is_up & (mp_c > 20)) | (~is_up & (mp_c < -20))).astype(int)

    # Regime label-based composables
    rl = fires["regime_label_at_ws"]
    fires["g_regime_trending_at_ws"] = (rl == "trending").astype(int)
    fires["g_regime_ranging_at_ws"] = (rl == "ranging").astype(int)

    # CHOCH alignment at ws_s
    cb = fires["choch_buy_at_ws"].fillna(0)
    cs = fires["choch_sell_at_ws"].fillna(0)
    fires["g_choch_with"] = ((is_up & (cb == 1)) | (~is_up & (cs == 1))).astype(int)
    bb = fires["bos_buy_at_ws"].fillna(0)
    bs = fires["bos_sell_at_ws"].fillna(0)
    fires["g_bos_with"] = ((is_up & (bb == 1)) | (~is_up & (bs == 1))).astype(int)

    # cvd alignment
    cvd_s = fires["cvd_sign_at_ws"].fillna(0)
    fires["g_cvd_with"] = ((is_up & (cvd_s > 0)) | (~is_up & (cvd_s < 0))).astype(int)

    # liquidity reclaim at ws_s (analogous to sms_liq_reclaim)
    lu = fires["liquidity_up_at_ws"].fillna(0)
    ld = fires["liquidity_dn_at_ws"].fillna(0)
    # Reclaim = direction matches the side with high liq (taker rides liq) — match V5 sense
    fires["g_sms_liq_reclaim_with_at_ws"] = ((is_up & (lu > ld) & (lu > 0)) | (~is_up & (ld > lu) & (ld > 0))).astype(int)

    # Time-of-day gates
    fires["hour_utc"] = pd.to_datetime(fires["fire_us"], unit="us").dt.hour
    h = fires["hour_utc"]
    fires["g_hod_european"] = ((h >= 7) & (h <= 11)).astype(int)
    fires["g_hod_us_morning"] = ((h >= 13) & (h <= 17)).astype(int)
    fires["g_hod_overnight"] = ((h >= 23) | (h <= 5)).astype(int)

    # Entry vwap band
    ev = fires["entry_vwap"]
    fires["g_entry_vwap_in_band"] = ((ev >= 0.10) & (ev <= 0.65)).astype(int)
    fires["g_entry_vwap_in_band_narrow"] = ((ev >= 0.15) & (ev <= 0.55)).astype(int)
    fires["g_entry_vwap_in_band_wide"] = ((ev >= 0.08) & (ev <= 0.75)).astype(int)

    # Day labels
    fires["day"] = pd.to_datetime(fires["fire_us"], unit="us").dt.date
    days_sorted = sorted(fires["day"].unique())
    print(f"\nTotal days: {len(days_sorted)} [{days_sorted[0]} ... {days_sorted[-1]}]")

    # Save
    print(f"\nWriting -> {OUT}")
    fires.to_parquet(OUT)
    print(f"  shape: {fires.shape}")
    # Show gate coverage
    new_gates = [c for c in fires.columns if c.startswith("g_") and c not in (
        "g_rf_with", "g_rf_fresh", "g_rf_aged", "g_rf_strong", "g_rf_in_band",
        "g_tr_stack_with", "g_tr_stack_full_with", "g_tr_above_cloud", "g_tr_within_adr",
        "g_tr_in_active_session", "g_tr_above_pp", "g_tr_above_ema50", "g_tr_above_ema200",
        "g_tr_above_ema800", "g_ribbon_agrees", "g_ribbon_slope_with", "g_tight_ribbon",
        "g_bb_pos_with", "g_stoch_with", "g_mfi_with", "g_cci_with",
        "g_sms_liq_reclaim_with", "g_sms_no_liquidity_above", "g_within_dev", "g_dev_extreme",
    )]
    print(f"\nNew V6 gates ({len(new_gates)}):")
    for g in new_gates:
        cov = fires[g].fillna(0).astype(float).mean()
        print(f"  {g}: cov={cov*100:.1f}%")


if __name__ == "__main__":
    main()
