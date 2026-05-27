"""Compute direction/PnL + R2 & R3 gates over full 32d window.

R2 part (May 1-21): use existing v15m_with_ta_and_markov + traders_reality_1s + range_filter
Lockbox part (May 22-25): build from hybrid_fire_universe_15m_lockbox + regime_panel_15m

Both portions share the same gate names from regime_panel (TR stack, ribbon, BB,
ADX, vol expansion, regime label) PLUS raw dev/vwap zones. R2 gets extra gates
(RF, F7, Markov, CVD, cross-asset) — but for the FINAL deployable verdict, we
test on the common subset.

Output: data/v4/canonical/_results/sleeve_hunt_15m_full_features.parquet
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

NOTIONAL = 25.0


def compute_pnl_direction(df_uni: pd.DataFrame) -> pd.DataFrame:
    """Given fire universe (with up_vwap/dn_vwap, outcome), derive direction & PnL.

    Direction: from vwap_since_open_bps sign (proxy for S7 momentum rule).
    PnL: legacy 2%-on-profit-only fee model.
    """
    d = df_uni.copy()
    d["direction"] = np.where(d["vwap_since_open_bps"].fillna(0) >= 0, "UP", "DOWN")
    d["entry_vwap"] = np.where(d["direction"] == "UP", d["up_vwap"], d["dn_vwap"])
    d["won"] = ((d["direction"] == "UP") & (d["outcome"] == "Up")) | \
               ((d["direction"] == "DOWN") & (d["outcome"] == "Down"))
    shares = NOTIONAL / d["entry_vwap"]
    gross = np.where(d["won"], shares * (1.0 - d["entry_vwap"]), -NOTIONAL)
    fee = np.where(gross > 0, 0.02 * gross, 0.0)
    d["pnl_legacy_usd"] = gross - fee
    d["dev_bps"] = d["vwap_since_open_bps"]
    d["abs_dev_bps"] = d["dev_bps"].abs()
    fill_ok = np.where(d["direction"] == "UP", d["up_fill_ok"], d["dn_fill_ok"])
    d = d[fill_ok].copy()
    d = d[(d["entry_vwap"] > 0) & (d["entry_vwap"] < 1.0)].copy()
    return d


def asof_join_regime_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Asof-join 15m regime_panel_15m onto each fire (per-asset, backward to fire_us)."""
    p = RES / "regime_panel_15m.parquet"
    if not p.exists():
        return df
    panel = pd.read_parquet(p)
    # rename to avoid clash
    rename_map = {}
    for c in panel.columns:
        if c in df.columns and c not in ("asset", "ts_us"):
            rename_map[c] = f"rp_{c}"
    panel = panel.rename(columns=rename_map)
    panel = panel.sort_values(["asset", "ts_us"])
    parts = []
    for asset, sub in df.groupby("asset", sort=False):
        psub = panel[panel["asset"] == asset].sort_values("ts_us")
        if psub.empty:
            parts.append(sub)
            continue
        ssub = sub.sort_values("fire_us")
        merged = pd.merge_asof(ssub, psub.drop(columns=["asset"]),
                                left_on="fire_us", right_on="ts_us",
                                direction="backward",
                                tolerance=int(60*60*1_000_000))  # 1h
        parts.append(merged)
    return pd.concat(parts, ignore_index=False).sort_index()


def add_regime_gates(d: pd.DataFrame) -> pd.DataFrame:
    """Build gates from regime_panel_15m columns (common to R2 & lockbox)."""
    d = d.copy()
    dir_up = (d["direction"] == "UP")
    dir_dn = (d["direction"] == "DOWN")

    # ADX strength
    if "adx_14" in d.columns:
        d["g_adx_strong"] = d["adx_14"] >= 25
        d["g_adx_strong_25"] = d["adx_14"] >= 25
        d["g_adx_extreme"] = d["adx_14"] >= 35
    # DI direction
    if "plus_di_14" in d.columns and "minus_di_14" in d.columns:
        d["g_di_with"] = ((d["plus_di_14"] > d["minus_di_14"]) & dir_up) | \
                          ((d["minus_di_14"] > d["plus_di_14"]) & dir_dn)
    # TR EMA stack (5-bar EMA stack alignment), -2..+2
    if "tr_ema_stack_score" in d.columns:
        d["g_tr_stack_with"] = ((d["tr_ema_stack_score"] >= 1) & dir_up) | \
                                ((d["tr_ema_stack_score"] <= -1) & dir_dn)
        d["g_tr_stack_full_with"] = ((d["tr_ema_stack_score"] == 2) & dir_up) | \
                                     ((d["tr_ema_stack_score"] == -2) & dir_dn)
    # Ribbon
    if "ribbon_alignment_pct" in d.columns:
        d["g_ribbon_high_align"] = d["ribbon_alignment_pct"] >= 0.8
        d["g_ribbon_med_align"] = d["ribbon_alignment_pct"] >= 0.6
    # BB width — compression / expansion
    if "bb_width_60s" in d.columns:
        med = d["bb_width_60s"].median()
        d["g_bb_compressed"] = d["bb_width_60s"] < (med * 0.6)
        d["g_bb_wide"] = d["bb_width_60s"] > (med * 1.4)
    # Realized vol — expansion regime
    if "realized_vol_60m" in d.columns:
        rv = d["realized_vol_60m"]
        med = rv.median()
        d["g_vol_high"] = rv > (med * 1.3)
        d["g_vol_low"] = rv < (med * 0.7)
        d["g_vol_expanding"] = rv > rv.rolling(20, min_periods=5).median().bfill().fillna(med)
    # Range compression
    if "range_compression" in d.columns:
        d["g_range_compressed"] = d["range_compression"] < d["range_compression"].quantile(0.3)
    # Trend slope
    if "trend_slope_30m" in d.columns:
        d["g_trend_slope_with"] = ((d["trend_slope_30m"] > 0) & dir_up) | \
                                    ((d["trend_slope_30m"] < 0) & dir_dn)
        d["g_trend_slope_strong_with"] = ((d["trend_slope_30m"] > d["trend_slope_30m"].abs().quantile(0.7)) & dir_up) | \
                                            ((d["trend_slope_30m"] < -d["trend_slope_30m"].abs().quantile(0.7)) & dir_dn)
    # Regime label
    if "regime_label" in d.columns:
        s = d["regime_label"].astype(str)
        d["g_regime_trend"] = s.str.contains("trend", case=False, na=False)
        d["g_regime_range"] = s.str.contains("range", case=False, na=False)
        d["g_regime_vol"] = s.str.contains("vol", case=False, na=False)
    return d


def add_dev_vwap_gates(d: pd.DataFrame) -> pd.DataFrame:
    """Raw fire-level dev/vwap zone gates."""
    d = d.copy()
    dir_up = (d["direction"] == "UP")
    dir_dn = (d["direction"] == "DOWN")
    if "abs_dev_bps" not in d.columns:
        d["abs_dev_bps"] = d["dev_bps"].abs() if "dev_bps" in d.columns else 0.0
    d["g_dev_5_10"] = (d["abs_dev_bps"] >= 5.0) & (d["abs_dev_bps"] < 10.0)
    d["g_dev_10_15"] = (d["abs_dev_bps"] >= 10.0) & (d["abs_dev_bps"] < 15.0)
    d["g_dev_15_20"] = (d["abs_dev_bps"] >= 15.0) & (d["abs_dev_bps"] < 20.0)
    d["g_dev_20_30"] = (d["abs_dev_bps"] >= 20.0) & (d["abs_dev_bps"] < 30.0)
    d["g_dev_30_plus"] = d["abs_dev_bps"] >= 30.0
    d["g_dev_ge_10"] = d["abs_dev_bps"] >= 10.0
    d["g_dev_ge_15"] = d["abs_dev_bps"] >= 15.0
    d["g_dev_ge_20"] = d["abs_dev_bps"] >= 20.0
    d["g_dev_extreme"] = (d["abs_dev_bps"] > 15.0)  # already direction-aligned per S7 rule
    d["g_within_dev"] = (d["abs_dev_bps"] > 5.0)

    d["g_vwap_low"] = d["entry_vwap"] < 0.55
    d["g_vwap_55_70"] = (d["entry_vwap"] >= 0.55) & (d["entry_vwap"] < 0.70)
    d["g_vwap_70_85"] = (d["entry_vwap"] >= 0.70) & (d["entry_vwap"] < 0.85)
    d["g_vwap_le_70"] = d["entry_vwap"] < 0.70
    d["g_vwap_ge_50_le_85"] = (d["entry_vwap"] >= 0.50) & (d["entry_vwap"] < 0.85)
    d["g_vwap_ge_30"] = d["entry_vwap"] >= 0.30
    return d


def build_r2_panel() -> pd.DataFrame:
    """R2 panel — start from sleeve_hunt_15m_features (has all 24 R2 gates already)
    + augment with regime_panel_15m gates so it shares common gate set with lockbox."""
    print("[R2] loading sleeve_hunt_15m_features (May 1-21)...")
    r2 = pd.read_parquet(RES / "sleeve_hunt_15m_features.parquet")
    print(f"  R2 features: {r2.shape}")
    print("[R2] asof-joining regime_panel_15m...")
    r2 = asof_join_regime_panel(r2)
    r2 = add_regime_gates(r2)
    r2["window"] = "R2_train_val"
    return r2


def build_lockbox_panel() -> pd.DataFrame:
    """Lockbox panel — May 22-25 from hybrid_fire_universe_15m_lockbox."""
    print("[Lockbox] loading hybrid_fire_universe_15m_lockbox (May 22-25)...")
    lb = pd.read_parquet(RES / "hybrid_fire_universe_15m_lockbox.parquet")
    print(f"  raw universe: {lb.shape}")
    lb = compute_pnl_direction(lb)
    print(f"  after direction/PnL filter: {lb.shape}")
    lb = add_dev_vwap_gates(lb)
    print("[Lockbox] asof-joining regime_panel_15m...")
    lb = asof_join_regime_panel(lb)
    lb = add_regime_gates(lb)
    lb["window"] = "lockbox"
    return lb


def main():
    print("="*80)
    print("SLEEVE HUNT 15M V2 — FULL FEATURE PANEL BUILD")
    print("="*80)
    t0 = time.time()

    r2 = build_r2_panel()
    lb = build_lockbox_panel()

    # Concat — keep common gates + key cols. Pad missing on R2/lockbox.
    keep_keys = ["slug", "asset", "fire_us", "fire_offset_s", "direction",
                  "entry_vwap", "dev_bps", "abs_dev_bps", "pnl_legacy_usd",
                  "outcome", "won", "window"]
    g_cols_r2 = sorted([c for c in r2.columns if c.startswith("g_")])
    g_cols_lb = sorted([c for c in lb.columns if c.startswith("g_")])
    common_g = sorted(set(g_cols_r2) & set(g_cols_lb))
    print(f"\nR2 gates: {len(g_cols_r2)}, Lockbox gates: {len(g_cols_lb)}, common: {len(common_g)}")
    print(f"R2-only gates ({len(set(g_cols_r2)-set(g_cols_lb))}):")
    print("   ", sorted(set(g_cols_r2)-set(g_cols_lb)))
    print(f"Lockbox-only gates ({len(set(g_cols_lb)-set(g_cols_r2))}):")
    print("   ", sorted(set(g_cols_lb)-set(g_cols_r2)))

    # Concat, keeping R2 cols (lockbox missing R2-only gets NaN/False)
    all_cols = sorted(set(keep_keys + g_cols_r2 + g_cols_lb))
    for c in all_cols:
        if c not in r2.columns:
            r2[c] = False if c.startswith("g_") else np.nan
        if c not in lb.columns:
            lb[c] = False if c.startswith("g_") else np.nan
    keep = [c for c in all_cols if c in r2.columns and c in lb.columns]
    full = pd.concat([r2[keep], lb[keep]], ignore_index=True)
    print(f"\nFull panel: {full.shape}")
    print(f"by window: {full['window'].value_counts().to_dict()}")
    ts = pd.to_datetime(full["fire_us"], unit="us", utc=True)
    print(f"time span: {ts.min()} -> {ts.max()}")
    print(f"days span: {(ts.max() - ts.min()).total_seconds() / 86400.0:.2f}")
    # per (asset, fire_offset_s)
    print("\nfire counts per (asset, fire_offset_s):")
    print(full.groupby(["asset", "fire_offset_s"]).size().unstack(fill_value=0))

    out_path = RES / "sleeve_hunt_15m_full_features.parquet"
    full.to_parquet(out_path, index=False, compression="zstd")
    print(f"\nSaved {out_path}: {full.shape}, elapsed {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
