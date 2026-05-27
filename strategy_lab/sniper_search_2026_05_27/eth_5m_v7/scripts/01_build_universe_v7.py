"""V7 ETH 5m universe build.

Extends V6 with V7-specific gates:
- Path C: BTC cross-asset features (mp_skew, hurst, trend_slope) at ws_s_us-500ms (BTC leads ETH ~500ms)
- Path F: ETH 15m parent regime confluence at ws_s
- Path H: deeper hurst variants (>0.65, <0.40, regime_with)
- Path I: deeper pre-window combos (combine multiple PW gates)
- Plus: keep ALL V6 gates intact

Input universe: data/v4/canonical/_results/_sniper_eth5m_v6_universe.parquet (already has v3 fires + V6 gates)
Output: data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet
"""

import os
import sys
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
V6_UNIV = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v6_universe.parquet")
MG = os.path.join(ROOT, "data/v4/canonical/_results/master_gate_features_v2.parquet")
MP = os.path.join(ROOT, "data/v4/canonical/_results/microprice_panel.parquet")
RG_5M = os.path.join(ROOT, "data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet")
RG_15M = os.path.join(ROOT, "data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
VH = os.path.join(ROOT, "data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet")

OUT = os.path.join(ROOT, "data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet")


def main():
    print(f"Loading V6 universe {V6_UNIV} ...")
    df = pd.read_parquet(V6_UNIV)
    print(f"  shape: {df.shape}")

    # ws_s_us already in V6 universe
    assert "ws_s_us" in df.columns

    is_up = (df["direction"] == "UP")

    # ========================================================================
    # Path C — BTC cross-asset signals at ws_s (BTC leads ETH ~500ms)
    # ========================================================================
    print("\n=== Path C: BTC cross-asset features at ETH ws_s ===")

    # 1. BTC microprice & skew at ws_s
    print("  Loading microprice panel for BTC...")
    mp_all = pd.read_parquet(MP)
    btc_mp = mp_all[(mp_all.asset == "BTC")][
        ["fire_us", "mp_skew", "mp_skew_change_500ms", "mp_imbalance"]
    ].sort_values("fire_us").drop_duplicates("fire_us").reset_index(drop=True)
    btc_mp.columns = ["fire_us", "btc_mp_skew", "btc_mp_skew_change_500ms", "btc_mp_imbalance"]

    # asof BTC microprice at ETH ws_s (BTC leads ~500ms, so asof backward is causal)
    fires_for_asof = df[["slug", "ws_s_us"]].copy().sort_values("ws_s_us").reset_index(drop=True)
    fires_for_asof = pd.merge_asof(
        fires_for_asof, btc_mp,
        left_on="ws_s_us", right_on="fire_us", direction="backward",
        tolerance=900_000_000,  # 900s
    )
    fires_for_asof.drop(columns=["fire_us"], errors="ignore", inplace=True)
    df = df.merge(
        fires_for_asof.drop_duplicates(["slug", "ws_s_us"]),
        on=["slug", "ws_s_us"], how="left",
    )
    print(f"    btc_mp_skew non-null: {df['btc_mp_skew'].notna().sum()}")

    # 2. BTC trend_slope & regime at ws_s (from regime_panel_5m for finer ts granularity)
    print("  Loading regime 5m for BTC trend_slope_30m...")
    rg5 = pd.read_parquet(RG_5M)
    btc_rg5 = rg5[rg5.asset == "BTC"][["ts_us", "regime_label", "trend_slope_30m", "tr_ema_stack_score", "adx_14"]].copy()
    btc_rg5.columns = ["ts_us", "btc_regime_label_5m", "btc_trend_slope_30m", "btc_tr_stack", "btc_adx_14"]
    btc_rg5 = btc_rg5.sort_values("ts_us").reset_index(drop=True)
    fires_for_asof2 = df[["slug", "ws_s_us"]].copy().sort_values("ws_s_us").reset_index(drop=True)
    fires_for_asof2 = pd.merge_asof(
        fires_for_asof2, btc_rg5,
        left_on="ws_s_us", right_on="ts_us", direction="backward",
        tolerance=900_000_000,
    )
    fires_for_asof2.drop(columns=["ts_us"], errors="ignore", inplace=True)
    df = df.merge(
        fires_for_asof2.drop_duplicates(["slug", "ws_s_us"]),
        on=["slug", "ws_s_us"], how="left",
    )
    print(f"    btc_trend_slope_30m non-null: {df['btc_trend_slope_30m'].notna().sum()}")

    # 3. BTC hurst from master_gate (closest match)
    print("  Loading master_gate for BTC hurst_300s...")
    mg = pd.read_parquet(MG)
    btc_mg = mg[(mg.asset == "BTC")][["fire_us", "hurst_300s", "g_hurst_trending"]].copy()
    btc_mg.columns = ["fire_us", "btc_hurst_300s", "btc_g_hurst_trending"]
    btc_mg = btc_mg.sort_values("fire_us").drop_duplicates("fire_us").reset_index(drop=True)
    fires_for_asof3 = df[["slug", "ws_s_us"]].copy().sort_values("ws_s_us").reset_index(drop=True)
    fires_for_asof3 = pd.merge_asof(
        fires_for_asof3, btc_mg,
        left_on="ws_s_us", right_on="fire_us", direction="backward",
        tolerance=900_000_000,
    )
    fires_for_asof3.drop(columns=["fire_us"], errors="ignore", inplace=True)
    df = df.merge(
        fires_for_asof3.drop_duplicates(["slug", "ws_s_us"]),
        on=["slug", "ws_s_us"], how="left",
    )
    print(f"    btc_hurst_300s non-null: {df['btc_hurst_300s'].notna().sum()}")

    # ---- Path C gates ----
    # BTC mp_skew agrees with ETH direction (cross-asset signal)
    df["g_btc_mp_skew_with"] = (
        (is_up & (df["btc_mp_skew"] > 30)) | (~is_up & (df["btc_mp_skew"] < -30))
    ).astype(int)
    df["g_btc_mp_skew_strong"] = (
        (is_up & (df["btc_mp_skew"] > 60)) | (~is_up & (df["btc_mp_skew"] < -60))
    ).astype(int)
    # BTC mp_skew change leading ETH direction (BTC microprice momentum into our fire)
    df["g_btc_mp_change_with"] = (
        (is_up & (df["btc_mp_skew_change_500ms"] > 20)) | (~is_up & (df["btc_mp_skew_change_500ms"] < -20))
    ).astype(int)
    # BTC trend_slope_30m agrees with direction
    df["g_btc_trend_slope_with"] = (
        (is_up & (df["btc_trend_slope_30m"] > 0)) | (~is_up & (df["btc_trend_slope_30m"] < 0))
    ).astype(int)
    df["g_btc_trend_slope_strong_with"] = (
        (is_up & (df["btc_trend_slope_30m"] > 0.0001)) | (~is_up & (df["btc_trend_slope_30m"] < -0.0001))
    ).astype(int)
    # BTC hurst trending (regardless of direction)
    df["g_btc_hurst_trending"] = (df["btc_hurst_300s"].fillna(0).astype(float) > 0.55).astype(int)
    df["g_btc_hurst_strong_trending"] = (df["btc_hurst_300s"].fillna(0).astype(float) > 0.65).astype(int)
    # BTC trend_slope + ETH direction confluence (unanimity)
    df["g_btc_eth_trend_agree"] = (
        df["g_btc_trend_slope_with"] & df["g_trend_slope_with"].fillna(0).astype(int)
    ).astype(int)
    # BTC mp_skew + ETH mp_skew agree (unanimity at_fire & cross-asset)
    df["g_btc_eth_mp_skew_agree"] = (
        df["g_btc_mp_skew_with"] & df["g_mp_skew_with"].fillna(0).astype(int)
    ).astype(int)

    # ========================================================================
    # Path F — ETH 15m parent regime confluence
    # ========================================================================
    print("\n=== Path F: ETH 15m parent regime at ws_s ===")
    rg15 = pd.read_parquet(RG_15M)
    eth_rg15 = rg15[rg15.asset == "ETH"][[
        "ts_us", "regime_label", "regime_score", "trend_slope_30m",
        "tr_ema_stack_score", "adx_14",
    ]].copy()
    eth_rg15.columns = ["ts_us", "eth15m_regime_label", "eth15m_regime_score",
                         "eth15m_trend_slope_30m", "eth15m_tr_stack", "eth15m_adx_14"]
    eth_rg15 = eth_rg15.sort_values("ts_us").reset_index(drop=True)
    fires_for_asof4 = df[["slug", "ws_s_us"]].copy().sort_values("ws_s_us").reset_index(drop=True)
    fires_for_asof4 = pd.merge_asof(
        fires_for_asof4, eth_rg15,
        left_on="ws_s_us", right_on="ts_us", direction="backward",
        tolerance=900_000_000,
    )
    fires_for_asof4.drop(columns=["ts_us"], errors="ignore", inplace=True)
    df = df.merge(
        fires_for_asof4.drop_duplicates(["slug", "ws_s_us"]),
        on=["slug", "ws_s_us"], how="left",
    )
    print(f"    eth15m_regime_label non-null: {df['eth15m_regime_label'].notna().sum()}")

    # ---- Path F gates ----
    # Parent 15m regime label uses {ranging, trending_up, trending_dn}
    rl15 = df["eth15m_regime_label"]
    ts15 = df["eth15m_trend_slope_30m"]
    df["g_parent15m_trending"] = ((rl15 == "trending_up") | (rl15 == "trending_dn")).astype(int)
    df["g_parent15m_ranging"] = (rl15 == "ranging").astype(int)
    # Direction-aware: parent 15m trending UP and we go UP, or DN and DOWN
    df["g_parent15m_label_with"] = (
        (is_up & (rl15 == "trending_up")) | (~is_up & (rl15 == "trending_dn"))
    ).astype(int)
    # Direction-aware: parent 15m trend_slope_30m matches our direction (units are bps/min)
    df["g_parent15m_trend_with"] = (
        (is_up & (ts15 > 0)) | (~is_up & (ts15 < 0))
    ).astype(int)
    df["g_parent15m_trend_strong_with"] = (
        (is_up & (ts15 > 3.0)) | (~is_up & (ts15 < -3.0))
    ).astype(int)
    df["g_parent15m_trending_with"] = (
        df["g_parent15m_trending"] & df["g_parent15m_trend_with"]
    ).astype(int)
    # Parent 15m strong trend (adx>25 + trending_label_with)
    df["g_parent15m_strong_label_with"] = (
        df["g_parent15m_label_with"] & (df["eth15m_adx_14"].fillna(0) > 25)
    ).astype(int)

    # ========================================================================
    # Path H — Deeper Hurst variants
    # ========================================================================
    print("\n=== Path H: Deeper Hurst variants ===")
    # Hurst from master_gate_features (hurst_300s)
    # ETH hurst quantiles: q10=0.46, q25=0.50, q50=0.54, q75=0.58, q90=0.61
    h = df["hurst_300s"].fillna(0.5).astype(float)
    df["g_hurst_strong_trending_v7"] = (h > 0.58).astype(int)  # ~25% cov
    df["g_hurst_very_strong_trending"] = (h > 0.61).astype(int)  # ~10% cov
    df["g_hurst_reverting_v7"] = (h < 0.50).astype(int)  # ~25% cov
    df["g_hurst_extreme_reverting"] = (h < 0.46).astype(int)  # ~10% cov

    # Direction-aware hurst (hurst trending AND ribbon agrees with direction)
    df["g_hurst_trend_with"] = (
        df["g_hurst_trending"].fillna(0).astype(int) &
        df["g_trend_slope_with"].fillna(0).astype(int)
    ).astype(int)
    df["g_hurst_strong_trend_with"] = (
        df["g_hurst_strong_trending_v7"] & df["g_trend_slope_with"].fillna(0).astype(int)
    ).astype(int)
    # hurst_trending combined with mp_skew_with — direction-aware microstructure trend
    df["g_hurst_mp_trend_with"] = (
        df["g_hurst_trending"].fillna(0).astype(int) &
        df["g_mp_skew_with"].fillna(0).astype(int)
    ).astype(int)

    # ========================================================================
    # Path I — Deeper pre-window combos
    # ========================================================================
    print("\n=== Path I: Deeper PW combo gates ===")
    # Combine 2+ PW gates into composites
    # mp_skew@ws + f7@ws unanimity
    df["g_pw_mp_f7_unanimity"] = (
        df["g_mp_skew_at_ws_with"].fillna(0).astype(int) &
        df["g_f7_with"].fillna(0).astype(int)
    ).astype(int)
    # mp_skew@ws + markov unanimity
    df["g_pw_mp_markov_unanimity"] = (
        df["g_mp_skew_at_ws_with"].fillna(0).astype(int) &
        df["g_markov_with"].fillna(0).astype(int)
    ).astype(int)
    # f7@ws + cvd@ws unanimity
    df["g_pw_f7_cvd_unanimity"] = (
        df["g_f7_with"].fillna(0).astype(int) &
        df["g_cvd_with"].fillna(0).astype(int)
    ).astype(int)
    # Triple PW: f7 + mp_skew + markov
    df["g_pw_triple_unanimity"] = (
        df["g_f7_with"].fillna(0).astype(int) &
        df["g_mp_skew_at_ws_with"].fillna(0).astype(int) &
        df["g_markov_with"].fillna(0).astype(int)
    ).astype(int)
    # mp_skew@ws strong + f7@ws strong (deep PW conviction)
    df["g_pw_mp_strong_f7_strong"] = (
        df["g_mp_skew_at_ws_strong"].fillna(0).astype(int) &
        df["g_f7_strong_with"].fillna(0).astype(int)
    ).astype(int)
    # Pre-window choch/bos confluence with direction
    df["g_pw_break_with"] = (
        df["g_choch_with"].fillna(0).astype(int) |
        df["g_bos_with"].fillna(0).astype(int)
    ).astype(int)

    # ========================================================================
    # Cross-asset + parent-15m unanimity (3-source confirmation)
    # ========================================================================
    print("\n=== Combos: cross-asset + parent + ETH 5m unanimity ===")
    df["g_xa_3source_trend_with"] = (
        df["g_trend_slope_with"].fillna(0).astype(int) &
        df["g_btc_trend_slope_with"].fillna(0).astype(int) &
        df["g_parent15m_trend_with"].fillna(0).astype(int)
    ).astype(int)
    df["g_xa_btc_eth_mp_parent_agree"] = (
        df["g_btc_mp_skew_with"] &
        df["g_mp_skew_with"].fillna(0).astype(int) &
        df["g_parent15m_trend_with"]
    ).astype(int)

    # ========================================================================
    # Save
    # ========================================================================
    print(f"\nWriting -> {OUT}")
    df.to_parquet(OUT)
    print(f"  shape: {df.shape}")

    # Coverage of new V7 gates
    new_v7_gates = [
        "g_btc_mp_skew_with", "g_btc_mp_skew_strong", "g_btc_mp_change_with",
        "g_btc_trend_slope_with", "g_btc_trend_slope_strong_with",
        "g_btc_hurst_trending", "g_btc_hurst_strong_trending",
        "g_btc_eth_trend_agree", "g_btc_eth_mp_skew_agree",
        "g_parent15m_trending", "g_parent15m_ranging", "g_parent15m_label_with",
        "g_parent15m_trend_with", "g_parent15m_trend_strong_with",
        "g_parent15m_trending_with", "g_parent15m_strong_label_with",
        "g_hurst_strong_trending_v7", "g_hurst_very_strong_trending",
        "g_hurst_reverting_v7", "g_hurst_extreme_reverting",
        "g_hurst_trend_with", "g_hurst_strong_trend_with", "g_hurst_mp_trend_with",
        "g_pw_mp_f7_unanimity", "g_pw_mp_markov_unanimity", "g_pw_f7_cvd_unanimity",
        "g_pw_triple_unanimity", "g_pw_mp_strong_f7_strong", "g_pw_break_with",
        "g_xa_3source_trend_with", "g_xa_btc_eth_mp_parent_agree",
    ]
    print(f"\nNew V7 gates ({len(new_v7_gates)}):")
    for g in new_v7_gates:
        cov = df[g].fillna(0).astype(float).mean()
        print(f"  {g}: cov={cov*100:.2f}%")


if __name__ == "__main__":
    main()
