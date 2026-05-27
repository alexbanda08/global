"""V8 ETH 5m universe build.

Extends V7 with:
- Path J: SOL cross-asset (trend_slope_30m, regime_label_5m, mp_skew) for 2-asset and 3-asset confluence
- Path K: TOD buckets (asia_morning, european_morning, us_afternoon, us_evening)
- Path Q: ETH 15m parent fire signals (only fire 5m if a v3 15m fire on same slot voted same direction)
- Path L: 1h grandparent regime via resampling 15m regime (use last 4-bar trend_slope mean as proxy)
- Path O: HL liquidation cascade / funding gates already in V7 master_gate

Inputs:
- V7 universe (133,497 fires, ETH 5m, full 32.7d)
- regime_panel_5m_v2_fixed: SOL trend_slope_30m / regime_label / adx
- regime_panel_15m_v2_fixed: SOL 15m & ETH 15m for grandparent proxy + parent regime
- v3 ETH 15m fires for Path Q (only the fires_with_gates derived signal)

Output: data/v4/canonical/_results/_sniper_eth5m_v8_universe.parquet
"""

import os
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
V7_UNIV = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v7_universe.parquet")
RG_5M = os.path.join(ROOT, r"data\v4\canonical\_results\regime_panel_5m_v2_fixed.parquet")
RG_15M = os.path.join(ROOT, r"data\v4\canonical\_results\regime_panel_15m_v2_fixed.parquet")
ETH_15M_FIRES = os.path.join(ROOT, r"data\v4\canonical\_results\_full_window_v3_2026_05_27\oos_fires_ETH_15m_full_v3.parquet")
MP = os.path.join(ROOT, r"data\v4\canonical\_results\microprice_panel.parquet")

OUT = os.path.join(ROOT, r"data\v4\canonical\_results\_sniper_eth5m_v8_universe.parquet")


def asof_join(left: pd.DataFrame, right: pd.DataFrame, left_key: str, right_key: str, tol_us: int = 900_000_000) -> pd.DataFrame:
    """As-of backward merge with `slug` already preserved on left."""
    keep_keys = list(left.columns)
    out = pd.merge_asof(
        left.sort_values(left_key).reset_index(drop=True),
        right.sort_values(right_key).reset_index(drop=True),
        left_on=left_key, right_on=right_key,
        direction="backward", tolerance=tol_us,
    )
    if right_key != left_key and right_key in out.columns:
        out = out.drop(columns=[right_key])
    return out


def main():
    print(f"Loading V7 universe {V7_UNIV} ...")
    df = pd.read_parquet(V7_UNIV)
    print(f"  shape: {df.shape}")

    assert "ws_s_us" in df.columns and "slug" in df.columns
    is_up = (df["direction"] == "UP")

    # ========================================================================
    # Path J — SOL cross-asset + 2-asset / 3-asset confluence
    # ========================================================================
    print("\n=== Path J: SOL cross-asset for 2-asset/3-asset confluence ===")

    # 1. SOL trend_slope_30m & regime + adx_14 from 5m regime panel
    rg5 = pd.read_parquet(RG_5M)
    sol_rg5 = rg5[rg5.asset == "SOL"][[
        "ts_us", "regime_label", "trend_slope_30m", "tr_ema_stack_score", "adx_14", "regime_score",
    ]].copy()
    sol_rg5.columns = ["ts_us", "sol_regime_label_5m", "sol_trend_slope_30m",
                       "sol_tr_stack", "sol_adx_14", "sol_regime_score_5m"]
    sol_rg5 = sol_rg5.sort_values("ts_us").reset_index(drop=True)

    fires_keys = df[["slug", "ws_s_us"]].sort_values("ws_s_us").reset_index(drop=True)
    fires_keys = pd.merge_asof(
        fires_keys, sol_rg5,
        left_on="ws_s_us", right_on="ts_us", direction="backward",
        tolerance=900_000_000,
    ).drop(columns=["ts_us"])
    df = df.merge(fires_keys.drop_duplicates(["slug", "ws_s_us"]),
                  on=["slug", "ws_s_us"], how="left")
    print(f"    sol_trend_slope_30m non-null: {df['sol_trend_slope_30m'].notna().sum()}")

    # 2. SOL mp_skew from microprice panel
    mp_all = pd.read_parquet(MP)
    sol_mp = mp_all[mp_all.asset == "SOL"][["fire_us", "mp_skew", "mp_imbalance"]].copy()
    sol_mp.columns = ["fire_us", "sol_mp_skew", "sol_mp_imbalance"]
    sol_mp = sol_mp.sort_values("fire_us").drop_duplicates("fire_us").reset_index(drop=True)
    fires_keys2 = df[["slug", "ws_s_us"]].sort_values("ws_s_us").reset_index(drop=True)
    fires_keys2 = pd.merge_asof(
        fires_keys2, sol_mp,
        left_on="ws_s_us", right_on="fire_us", direction="backward",
        tolerance=900_000_000,
    ).drop(columns=["fire_us"])
    df = df.merge(fires_keys2.drop_duplicates(["slug", "ws_s_us"]),
                  on=["slug", "ws_s_us"], how="left")
    print(f"    sol_mp_skew non-null: {df['sol_mp_skew'].notna().sum()}")

    # ---- Path J gates ----
    # Single-asset SOL trend agreement
    df["g_sol_trend_slope_with"] = (
        (is_up & (df["sol_trend_slope_30m"] > 0)) | (~is_up & (df["sol_trend_slope_30m"] < 0))
    ).astype(int)
    df["g_sol_trend_slope_strong_with"] = (
        (is_up & (df["sol_trend_slope_30m"] > 0.0001)) | (~is_up & (df["sol_trend_slope_30m"] < -0.0001))
    ).astype(int)
    df["g_sol_mp_skew_with"] = (
        (is_up & (df["sol_mp_skew"] > 30)) | (~is_up & (df["sol_mp_skew"] < -30))
    ).astype(int)

    # 2-asset confluence (BTC + SOL → ETH)
    # G_2A_BTC_SOL: BTC trend AND SOL trend both agree with ETH direction
    df["g_2a_btc_sol_trend_with"] = (
        df["g_btc_trend_slope_with"].fillna(0).astype(int) &
        df["g_sol_trend_slope_with"].fillna(0).astype(int)
    ).astype(int)
    # Strong variant
    df["g_2a_btc_sol_trend_strong_with"] = (
        df["g_btc_trend_slope_strong_with"].fillna(0).astype(int) &
        df["g_sol_trend_slope_strong_with"].fillna(0).astype(int)
    ).astype(int)
    # 2-asset mp_skew unanimity (BTC + SOL micro both agree)
    df["g_2a_btc_sol_mp_with"] = (
        df["g_btc_mp_skew_with"].fillna(0).astype(int) &
        df["g_sol_mp_skew_with"].fillna(0).astype(int)
    ).astype(int)

    # 3-asset confluence: BTC + SOL + ETH (self) all agree
    df["g_3a_unanimity_trend"] = (
        df["g_btc_trend_slope_with"].fillna(0).astype(int) &
        df["g_sol_trend_slope_with"].fillna(0).astype(int) &
        df["g_trend_slope_with"].fillna(0).astype(int)
    ).astype(int)
    # Strong 3-asset (slope > threshold for all)
    df["g_3a_strong_unanimity_trend"] = (
        df["g_btc_trend_slope_strong_with"].fillna(0).astype(int) &
        df["g_sol_trend_slope_strong_with"].fillna(0).astype(int) &
        df["g_trend_slope_with"].fillna(0).astype(int)
    ).astype(int)
    # 3-asset trend+mp (RF + microprice + trend all unanimous, V8 brief J)
    df["g_3a_unanimity_full"] = (
        df["g_3a_unanimity_trend"] &
        df["g_btc_mp_skew_with"].fillna(0).astype(int) &
        df["g_sol_mp_skew_with"].fillna(0).astype(int) &
        df["g_mp_skew_with"].fillna(0).astype(int)
    ).astype(int)

    # ========================================================================
    # Path K — TOD specialization
    # ========================================================================
    print("\n=== Path K: TOD buckets ===")
    hour_of_day = pd.to_datetime(df["fire_us"], unit="us", utc=True).dt.hour
    df["hod"] = hour_of_day.astype(int)
    df["g_tod_asia_morning"] = (hour_of_day < 7).astype(int)                # 00-07 UTC
    df["g_tod_european_morning"] = ((hour_of_day >= 7) & (hour_of_day < 13)).astype(int)
    df["g_tod_us_afternoon"] = ((hour_of_day >= 13) & (hour_of_day < 19)).astype(int)
    df["g_tod_us_evening"] = (hour_of_day >= 19).astype(int)
    # Per V8 brief: also test pairwise unions
    df["g_tod_europe_us_window"] = ((hour_of_day >= 7) & (hour_of_day < 19)).astype(int)
    df["g_tod_outside_us_close"] = ((hour_of_day < 19) | (hour_of_day < 7)).astype(int)
    # Power hour and similar
    df["g_tod_us_open"] = ((hour_of_day >= 13) & (hour_of_day < 15)).astype(int)
    df["g_tod_us_close"] = ((hour_of_day >= 19) & (hour_of_day < 21)).astype(int)

    # ========================================================================
    # Path Q — 5m + 15m confluence (only fire ETH 5m if ETH 15m parent fired same dir on same slot)
    # ========================================================================
    print("\n=== Path Q: ETH 5m + 15m confluence ===")
    eth15 = pd.read_parquet(ETH_15M_FIRES)
    print(f"   ETH 15m v3 fires: {len(eth15)} rows")
    # 15m slot the 5m fire belongs to: floor(ws_s / 900) * 900
    # For Path Q we look for a 15m fire whose slot_start <= ws_s_5m < slot_end and direction matches
    # Approach: for each 5m fire, lookup 15m fires whose slot covers the 5m ws_s.
    # Build keyed index on 15m slot_start_us. slot_end_us = slot_start_us + 900_000_000 - 1 for 15m
    # For each 5m fire, slot15_start = (ws_s // 900) * 900
    sec_to_us = 1_000_000
    df["slot15_start_s"] = (df["ws_s"] // 900) * 900
    df["slot15_start_us"] = df["slot15_start_s"].astype("int64") * sec_to_us

    eth15["slot15_start_us"] = eth15["slot_start_us"].astype("int64")
    # For each 15m slot, aggregate the directions that were fired (since multiple offsets per slot, we can have multiple fires)
    e15_per_slot = (eth15.groupby(["slot15_start_us", "direction"]).size()
                    .unstack(fill_value=0).reset_index())
    if "UP" not in e15_per_slot.columns:
        e15_per_slot["UP"] = 0
    if "DOWN" not in e15_per_slot.columns:
        e15_per_slot["DOWN"] = 0
    e15_per_slot.columns = [c if c == "slot15_start_us" else f"eth15m_n_{c}" for c in e15_per_slot.columns]
    df = df.merge(e15_per_slot, on="slot15_start_us", how="left")
    df["eth15m_n_UP"] = df["eth15m_n_UP"].fillna(0).astype(int)
    df["eth15m_n_DOWN"] = df["eth15m_n_DOWN"].fillna(0).astype(int)

    df["g_q_15m_agrees"] = (
        (is_up & (df["eth15m_n_UP"] > df["eth15m_n_DOWN"]) & (df["eth15m_n_UP"] > 0)) |
        (~is_up & (df["eth15m_n_DOWN"] > df["eth15m_n_UP"]) & (df["eth15m_n_DOWN"] > 0))
    ).astype(int)
    df["g_q_15m_unanimous"] = (
        (is_up & (df["eth15m_n_UP"] > 0) & (df["eth15m_n_DOWN"] == 0)) |
        (~is_up & (df["eth15m_n_DOWN"] > 0) & (df["eth15m_n_UP"] == 0))
    ).astype(int)

    # Also: 15m WIN context — direction the 15m sub fires would have realized
    # (post-hoc oracle, use cautiously — gate looks back through the realized outcome to check if 15m fires on same slot WON)
    # For Path Q we should NOT use realized wins (lookahead); use only fire direction
    print(f"    g_q_15m_agrees cov: {df['g_q_15m_agrees'].mean()*100:.2f}%")
    print(f"    g_q_15m_unanimous cov: {df['g_q_15m_unanimous'].mean()*100:.2f}%")

    # ========================================================================
    # Path L — 1h grandparent proxy (rolling 4-bar mean of 15m trend_slope_30m)
    # ========================================================================
    print("\n=== Path L: 1h grandparent proxy via 15m rolling ===")
    eth_rg15 = pd.read_parquet(RG_15M)
    eth_rg15 = eth_rg15[eth_rg15.asset == "ETH"][["ts_us", "trend_slope_30m", "regime_label", "adx_14"]].sort_values("ts_us").reset_index(drop=True)
    eth_rg15["trend_slope_4bar"] = eth_rg15["trend_slope_30m"].rolling(4, min_periods=2).mean()
    eth_rg15["adx_4bar"] = eth_rg15["adx_14"].rolling(4, min_periods=2).mean()
    eth_rg15_to_join = eth_rg15[["ts_us", "trend_slope_4bar", "adx_4bar"]].copy()
    eth_rg15_to_join.columns = ["ts_us", "eth_grandparent_trend_slope", "eth_grandparent_adx"]

    fires_keys3 = df[["slug", "ws_s_us"]].sort_values("ws_s_us").reset_index(drop=True)
    fires_keys3 = pd.merge_asof(
        fires_keys3, eth_rg15_to_join,
        left_on="ws_s_us", right_on="ts_us", direction="backward",
        tolerance=900_000_000,
    ).drop(columns=["ts_us"])
    df = df.merge(fires_keys3.drop_duplicates(["slug", "ws_s_us"]),
                  on=["slug", "ws_s_us"], how="left")
    print(f"    eth_grandparent_trend_slope non-null: {df['eth_grandparent_trend_slope'].notna().sum()}")

    df["g_grandparent_trend_with"] = (
        (is_up & (df["eth_grandparent_trend_slope"] > 0)) |
        (~is_up & (df["eth_grandparent_trend_slope"] < 0))
    ).astype(int)
    df["g_grandparent_strong_trend_with"] = (
        (is_up & (df["eth_grandparent_trend_slope"] > 2.0)) |
        (~is_up & (df["eth_grandparent_trend_slope"] < -2.0))
    ).astype(int)
    # MTF: 5m + 15m + 1h-proxy all agree direction
    df["g_l_mtf_unanimity"] = (
        df["g_trend_slope_with"].fillna(0).astype(int) &
        df["g_parent15m_trend_with"].fillna(0).astype(int) &
        df["g_grandparent_trend_with"].fillna(0).astype(int)
    ).astype(int)

    # ========================================================================
    # Save
    # ========================================================================
    print(f"\nWriting -> {OUT}")
    df.to_parquet(OUT)
    print(f"  shape: {df.shape}")

    # Coverage of new V8 gates
    new_v8_gates = [
        "g_sol_trend_slope_with", "g_sol_trend_slope_strong_with", "g_sol_mp_skew_with",
        "g_2a_btc_sol_trend_with", "g_2a_btc_sol_trend_strong_with", "g_2a_btc_sol_mp_with",
        "g_3a_unanimity_trend", "g_3a_strong_unanimity_trend", "g_3a_unanimity_full",
        "g_tod_asia_morning", "g_tod_european_morning", "g_tod_us_afternoon", "g_tod_us_evening",
        "g_tod_europe_us_window", "g_tod_us_open", "g_tod_us_close",
        "g_q_15m_agrees", "g_q_15m_unanimous",
        "g_grandparent_trend_with", "g_grandparent_strong_trend_with", "g_l_mtf_unanimity",
    ]
    print(f"\nNew V8 gates ({len(new_v8_gates)}):")
    for g in new_v8_gates:
        cov = df[g].fillna(0).astype(float).mean()
        print(f"  {g}: cov={cov*100:.2f}%")


if __name__ == "__main__":
    main()
