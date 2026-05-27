"""Deep stacking — TASK 1: Build feature matrix.

Start from `s6/s15/v15m_joined_all.parquet` (the hybrid_v1 baselines with R1 gates already
present + direction, outcome, pnl_legacy_usd, won). Join R3+R5 per-fire panels by
(slug, asset, fire_us, fire_offset_s) and add direction-aware gates.

R3+R5 candidate gates joined:
  Microprice (R5):       g_mp_no_extreme, g_mp_change_with, g_mp_skew_with
  Lee-Mykland (R5):      g_lm_high_stat, g_lm_extreme_against
  Hawkes (R5):           g_hawkes_imbalance_with
  Vol/Hurst (R3):        g_vol_expanding, g_vol_high, g_vol_contracting, g_hurst_trending
  Microstructure (R3):   g_imb5_strong_with, g_imb_change_with, g_queue_top_high,
                         g_book_slope_steep_against, g_microprice_with (alt name)
  AS (R5):               g_as_low_uncert (low uncertainty regime)

Output:
  data/v4/canonical/_results/deep_stack_panel_s6.parquet
  data/v4/canonical/_results/deep_stack_panel_s15.parquet
  data/v4/canonical/_results/deep_stack_panel_v15m.parquet
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_DIR = RES
OUT_DIR.mkdir(parents=True, exist_ok=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def dedupe_base(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """For S6, keep all definitions (D1/D2/D3/D4) as the original report does
    (this is the panel where the hybrid_v1 baselines were measured).
    For S15/v15m, no duplication exists.
    """
    n0 = len(df)
    log(f"  {name}: rows = {n0:,} (no dedupe — preserves report parity)")
    return df


def add_microprice_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Join microprice panel and add 3 R5 gates (direction-aware)."""
    mp = pd.read_parquet(RES / "microprice_panel.parquet")
    keep = ["asset", "slug", "fire_us", "fire_offset_s",
            "mp_skew", "mp_imbalance", "mp_weighted_skew",
            "mp_skew_change_500ms", "mp_up_dev_bps", "mp_dn_dev_bps"]
    mp = mp[keep].drop_duplicates(["asset", "slug", "fire_us", "fire_offset_s"], keep="first")
    df = df.merge(mp, on=["asset", "slug", "fire_us", "fire_offset_s"], how="left")
    log(f"  microprice joined: mp_skew nonnull = {df.mp_skew.notna().sum()}/{len(df)}")

    dir_up = (df["direction"] == "UP")
    dir_dn = (df["direction"] == "DOWN")
    # g_mp_no_extreme: |mp_skew| < 50 bps (tradability filter, universal)
    df["g_r5_mp_no_extreme"] = (df["mp_skew"].abs() < 50.0).fillna(False).astype("int8")
    # g_mp_change_with: mp_skew_change_500ms aligned with direction
    df["g_r5_mp_change_with"] = (
        ((df["mp_skew_change_500ms"] > 0) & dir_up) |
        ((df["mp_skew_change_500ms"] < 0) & dir_dn)
    ).fillna(False).astype("int8")
    # g_mp_skew_with: |mp_skew|>5 AND sign matches direction
    df["g_r5_mp_skew_with"] = (
        (df["mp_skew"].abs() > 5.0) &
        (((df["mp_skew"] > 0) & dir_up) | ((df["mp_skew"] < 0) & dir_dn))
    ).fillna(False).astype("int8")
    return df


def add_lm_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Join Lee-Mykland panel and add R5 gates."""
    lm5 = pd.read_parquet(RES / "lm_at_fires_5m.parquet")
    lm15 = pd.read_parquet(RES / "lm_at_fires_15m.parquet")
    lm = pd.concat([lm5, lm15], ignore_index=True)
    keep = ["asset", "slug", "fire_us", "fire_offset_s",
            "lm_L_stat_at_fire", "lm_last_jump_dir_extreme_120s", "lm_last_jump_dir_60s",
            "lm_n_jumps_in_last_300s", "lm_has_jump_60s"]
    lm = lm[keep].drop_duplicates(["asset", "slug", "fire_us", "fire_offset_s"], keep="first")
    df = df.merge(lm, on=["asset", "slug", "fire_us", "fire_offset_s"], how="left")
    log(f"  LM joined: L_stat nonnull = {df.lm_L_stat_at_fire.notna().sum()}/{len(df)}")

    dir_up = (df["direction"] == "UP")
    dir_dn = (df["direction"] == "DOWN")
    dir_sign = np.where(dir_up, 1, np.where(dir_dn, -1, 0))
    # g_lm_high_stat: L_stat > 5.97 (1% sig)
    df["g_r5_lm_high_stat"] = (df["lm_L_stat_at_fire"] > 5.97).fillna(False).astype("int8")
    # g_lm_extreme_against (KILL gate): bet AGAINST extreme jump
    df["g_r5_lm_extreme_against"] = (
        (df["lm_last_jump_dir_extreme_120s"] == -dir_sign) & (dir_sign != 0)
    ).astype("int8")
    # g_lm_recent_jump_with: recent jump dir aligns with bet dir within 60s
    df["g_r5_lm_recent_jump_with"] = (
        df["lm_has_jump_60s"].fillna(False) &
        (df["lm_last_jump_dir_60s"] == dir_sign) & (dir_sign != 0)
    ).astype("int8")
    return df


def add_hawkes_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Join Hawkes panel."""
    h = pd.read_parquet(RES / "vpin_hawkes_at_fires.parquet")
    keep = ["asset", "slug", "fire_us", "fire_offset_s",
            "hawkes_lambda_imbalance", "hawkes_lambda_total",
            "hawkes_recent_burst", "vpin_value", "vpin_zscore"]
    keep = [c for c in keep if c in h.columns]
    h = h[keep].drop_duplicates(["asset", "slug", "fire_us", "fire_offset_s"], keep="first")
    df = df.merge(h, on=["asset", "slug", "fire_us", "fire_offset_s"], how="left")
    log(f"  Hawkes joined: lambda_imb nonnull = {df.hawkes_lambda_imbalance.notna().sum()}/{len(df)}")

    dir_up = (df["direction"] == "UP")
    dir_dn = (df["direction"] == "DOWN")
    # g_hawkes_imbalance_with: lambda_imbalance sign aligns with bet
    df["g_r5_hawkes_imbalance_with"] = (
        ((df["hawkes_lambda_imbalance"] > 0.3) & dir_up) |
        ((df["hawkes_lambda_imbalance"] < -0.3) & dir_dn)
    ).fillna(False).astype("int8")
    return df


def add_volhurst_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Join vol/Hurst panel — R3 gates."""
    v5 = pd.read_parquet(RES / "vol_hurst_at_fire_5m.parquet")
    v15 = pd.read_parquet(RES / "vol_hurst_at_fire_15m.parquet")
    v = pd.concat([v5, v15], ignore_index=True)
    keep = ["asset", "slug", "fire_us", "fire_offset_s",
            "g_vol_low", "g_vol_med", "g_vol_high",
            "g_vol_expanding", "g_vol_contracting",
            "g_hurst_trending", "g_hurst_reverting", "g_rv_with"]
    keep = [c for c in keep if c in v.columns]
    v = v[keep].drop_duplicates(["asset", "slug", "fire_us", "fire_offset_s"], keep="first")
    df = df.merge(v, on=["asset", "slug", "fire_us", "fire_offset_s"], how="left")
    # rename to r3 prefix to avoid collision
    for c in ["g_vol_low", "g_vol_med", "g_vol_high", "g_vol_expanding", "g_vol_contracting",
              "g_hurst_trending", "g_hurst_reverting", "g_rv_with"]:
        if c in df.columns:
            df["g_r3_" + c[2:]] = df[c].fillna(0).astype("int8")
            df = df.drop(columns=[c])
    log(f"  Vol/Hurst joined: g_r3_vol_expanding sum = {df.get('g_r3_vol_expanding', pd.Series([0])).sum()}")
    return df


def add_micro_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Join microstructure panel — R3 directional gates."""
    ms = pd.read_parquet(RES / "microstructure_panel.parquet")
    keep = ["asset", "slug", "fire_us", "fire_offset_s",
            "up_imb1", "up_imb5", "up_imb25",
            "dn_imb1", "dn_imb5", "dn_imb25",
            "up_imb5_change_500ms", "dn_imb5_change_500ms",
            "up_queue_top_bid", "dn_queue_top_bid",
            "up_bid_slope", "up_ask_slope",
            "dn_bid_slope", "dn_ask_slope",
            "imb5_diff", "micro_dev_diff", "spread_diff", "depth_diff",
            "up_micro_dev_bps", "dn_micro_dev_bps"]
    keep = [c for c in keep if c in ms.columns]
    ms = ms[keep].drop_duplicates(["asset", "slug", "fire_us", "fire_offset_s"], keep="first")
    df = df.merge(ms, on=["asset", "slug", "fire_us", "fire_offset_s"], how="left")
    log(f"  microstructure joined: up_imb5 nonnull = {df.up_imb5.notna().sum()}/{len(df)}")

    dir_up = (df["direction"] == "UP")
    dir_dn = (df["direction"] == "DOWN")
    # g_imb5_strong_with: imb5 > 0.3 on our side
    df["g_r3_imb5_strong_with"] = (
        ((df["up_imb5"] > 0.3) & dir_up) | ((df["dn_imb5"] > 0.3) & dir_dn)
    ).fillna(False).astype("int8")
    # g_imb5_with (broader)
    df["g_r3_imb5_with"] = (
        ((df["up_imb5"] > 0.1) & dir_up) | ((df["dn_imb5"] > 0.1) & dir_dn)
    ).fillna(False).astype("int8")
    # g_imb_change_with
    df["g_r3_imb_change_with"] = (
        ((df["up_imb5_change_500ms"] > 0) & dir_up) | ((df["dn_imb5_change_500ms"] > 0) & dir_dn)
    ).fillna(False).astype("int8")
    # g_queue_top_high: above median on bet-side
    qmed_up = df["up_queue_top_bid"].median()
    qmed_dn = df["dn_queue_top_bid"].median()
    df["g_r3_queue_top_high"] = (
        ((df["up_queue_top_bid"] > qmed_up) & dir_up) | ((df["dn_queue_top_bid"] > qmed_dn) & dir_dn)
    ).fillna(False).astype("int8")
    # g_book_slope_steep_against: your-side book thick (book slope < 25%ile against)
    diff_up = df["up_bid_slope"] - df["up_ask_slope"]
    diff_dn = df["dn_bid_slope"] - df["dn_ask_slope"]
    q25_up = diff_up.quantile(0.25)
    q25_dn = diff_dn.quantile(0.25)
    df["g_r3_book_slope_steep_against"] = (
        ((diff_up < q25_up) & dir_up) | ((diff_dn < q25_dn) & dir_dn)
    ).fillna(False).astype("int8")
    return df


def add_as_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Avellaneda-Stoikov uncertainty gate."""
    ap = pd.read_parquet(RES / "as_panel.parquet")
    keep = ["asset", "tf", "slug", "fire_us",
            "as_uncertainty_norm_24h", "as_uncertainty_pct_24h", "as_skew"]
    keep = [c for c in keep if c in ap.columns]
    ap = ap[keep].drop_duplicates(["asset", "tf", "slug", "fire_us"], keep="first")
    df = df.merge(ap, on=["asset", "tf", "slug", "fire_us"], how="left")
    log(f"  AS joined: uncertainty nonnull = {df.as_uncertainty_norm_24h.notna().sum()}/{len(df)}")

    # g_as_low_uncert: bottom quartile of normed uncertainty (high conviction regime)
    df["g_r5_as_low_uncert"] = (df["as_uncertainty_norm_24h"] < 0.5).fillna(False).astype("int8")
    return df


def build_for_base(base_name: str, base_file: str, base_tf: str) -> pd.DataFrame:
    """Build deep-stack panel for one base sleeve frame."""
    log(f"=== Building {base_name} ===")
    df = pd.read_parquet(RES / base_file)
    log(f"  base loaded: {df.shape}")
    df = df.copy()
    if "tf" not in df.columns:
        df["tf"] = base_tf
    df = dedupe_base(df, base_name)

    # Need direction, outcome, pnl_legacy_usd, won
    needed = ["asset", "slug", "fire_us", "fire_offset_s", "tf",
              "direction", "outcome", "pnl_legacy_usd", "won"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise RuntimeError(f"{base_name} missing cols: {missing}")
    df = df[df.direction.isin(["UP", "DOWN"])].copy()
    df = df[df.pnl_legacy_usd.notna()].copy()
    log(f"  after direction/pnl filter: {len(df):,}")

    # Add R3+R5 gates
    df = add_microprice_gates(df)
    df = add_lm_gates(df)
    df = add_hawkes_gates(df)
    df = add_volhurst_gates(df)
    df = add_micro_gates(df)
    df = add_as_gates(df)

    # Summarize all gates
    all_gates = [c for c in df.columns if c.startswith("g_")]
    log(f"  total gates: {len(all_gates)}")
    new_gates = [c for c in df.columns if c.startswith("g_r3_") or c.startswith("g_r5_")]
    log(f"  new R3/R5 gates: {len(new_gates)}")
    for g in sorted(new_gates):
        s = int(df[g].sum())
        log(f"    {g:42s} = {s:5d} ({s/len(df)*100:5.1f}%)")
    return df


def main():
    log("DEEP STACKING — Build feature matrix")
    s6 = build_for_base("s6_5m", "s6_joined_all.parquet", "5m")
    s6.to_parquet(OUT_DIR / "deep_stack_panel_s6.parquet", index=False, compression="zstd")
    log(f"  wrote deep_stack_panel_s6.parquet: {len(s6):,} rows × {len(s6.columns)} cols")

    s15 = build_for_base("s15_5m", "s15_joined_all.parquet", "5m")
    s15.to_parquet(OUT_DIR / "deep_stack_panel_s15.parquet", index=False, compression="zstd")
    log(f"  wrote deep_stack_panel_s15.parquet: {len(s15):,} rows × {len(s15.columns)} cols")

    v15m = build_for_base("v15m_15m", "v15m_joined_all.parquet", "15m")
    v15m.to_parquet(OUT_DIR / "deep_stack_panel_v15m.parquet", index=False, compression="zstd")
    log(f"  wrote deep_stack_panel_v15m.parquet: {len(v15m):,} rows × {len(v15m.columns)} cols")


if __name__ == "__main__":
    main()
