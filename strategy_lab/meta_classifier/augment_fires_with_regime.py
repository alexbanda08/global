"""Augment per-fire parquets with regime features via causal merge_asof at fire_us - 1s.

Adds: regime_label (str), regime_score (float -1..+1), adx_14, realized_vol_60m,
      tr_ema_stack_score, ribbon_alignment_pct_regime (renamed to avoid collisions).

Inputs:
  - data/v4/canonical/_results/hybrid_features_5m.parquet
  - data/v4/canonical/_results/hybrid_features_15m.parquet
  - data/v4/canonical/_results/s15_with_ta_and_markov.parquet  (5m S1.5)
  - data/v4/canonical/_results/v15m_with_ta_and_markov.parquet (15m S7)
  - data/v4/canonical/_results/s6_with_ta.parquet              (5m S6)
  - data/v4/canonical/_results/hybrid_gate_search_per_fire.parquet

Outputs to same names with `_regime` suffix.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES  = ROOT / "data" / "v4" / "canonical" / "_results"

REGIME_PANEL_5M  = RES / "regime_panel_5m.parquet"
REGIME_PANEL_15M = RES / "regime_panel_15m.parquet"

# Window: Apr 30 → May 22 2026
WIN_START_US = int(dt.datetime(2026, 4, 30, tzinfo=dt.timezone.utc).timestamp() * 1e6)
WIN_END_US   = int(dt.datetime(2026, 5, 23, tzinfo=dt.timezone.utc).timestamp() * 1e6)


def asof_join_regime(fires: pd.DataFrame, panel_5m: pd.DataFrame, panel_15m: pd.DataFrame,
                     tf_default: str | None = None) -> pd.DataFrame:
    """Causal asof at fire_us - 1s; per asset & per timeframe."""
    out_chunks = []
    for asset in fires["asset"].dropna().unique():
        for tf in fires["tf"].dropna().unique() if "tf" in fires.columns else [tf_default]:
            if tf is None:
                continue
            sub = fires[(fires["asset"] == asset)]
            if "tf" in sub.columns:
                # Some files store tf like 's6_5m' / 's15_5m' — map.
                if tf and "tf" in fires.columns:
                    sub = sub[sub["tf"] == tf]
            if sub.empty:
                continue
            # Determine which regime panel to use based on tf suffix
            tf_str = str(tf)
            if "15m" in tf_str:
                panel = panel_15m[panel_15m["asset"] == asset].copy()
            else:
                panel = panel_5m[panel_5m["asset"] == asset].copy()
            # Causal: fire_us - 1s
            sub = sub.copy()
            sub["_fire_lookup_us"] = (sub["fire_us"].astype("int64") - 1_000_000)
            sub = sub.sort_values("_fire_lookup_us")
            # Use bar_end_us if present, else recompute end from ts_us
            if "bar_end_us" in panel.columns:
                panel["_asof_us"] = panel["bar_end_us"].astype("int64")
            else:
                tf_min = 15 if "15m" in tf_str else 5
                panel["_asof_us"] = panel["ts_us"].astype("int64") + tf_min * 60_000_000 - 1
            keep = ["_asof_us", "regime_label", "regime_score", "adx_14",
                    "realized_vol_60m", "tr_ema_stack_score", "ribbon_alignment_pct",
                    "range_compression", "trend_slope_30m", "bb_width_60s"]
            panel = panel[[c for c in keep if c in panel.columns]].sort_values("_asof_us")
            merged = pd.merge_asof(
                sub, panel,
                left_on="_fire_lookup_us", right_on="_asof_us",
                direction="backward",
                tolerance=20 * 60_000_000,  # 20 min tolerance
            )
            # Rename ribbon_alignment_pct (avoid collision with fire-level ribbon_alignment_pct)
            if "ribbon_alignment_pct" in merged.columns:
                merged = merged.rename(columns={"ribbon_alignment_pct": "ribbon_alignment_pct_regime"})
            out_chunks.append(merged)
    if not out_chunks:
        return fires.copy()
    return pd.concat(out_chunks, ignore_index=True)


def _detect_tf(df: pd.DataFrame, default_tf: str) -> pd.DataFrame:
    """Ensure df has a `tf` column with '5m' or '15m' (string suffix)."""
    out = df.copy()
    if "tf" not in out.columns:
        out["tf"] = default_tf
    # Normalize: hybrid_gate_search has 's6_5m' style values — keep raw but join by suffix
    return out


def augment_hybrid_features():
    panel_5m  = pd.read_parquet(REGIME_PANEL_5M)
    panel_15m = pd.read_parquet(REGIME_PANEL_15M)

    for src, out_name, default_tf in [
        (RES / "hybrid_features_5m.parquet",  "hybrid_features_5m_regime.parquet",  "5m"),
        (RES / "hybrid_features_15m.parquet", "hybrid_features_15m_regime.parquet", "15m"),
    ]:
        if not src.exists():
            print("missing:", src); continue
        df = pd.read_parquet(src)
        df = _detect_tf(df, default_tf)
        df = df[(df["fire_us"] >= WIN_START_US) & (df["fire_us"] < WIN_END_US)]
        print(f"{src.name}: {len(df):,} rows after window filter")
        merged = asof_join_regime(df, panel_5m, panel_15m, tf_default=default_tf)
        nonnull = merged["regime_label"].notna().sum()
        print(f"  regime joined: {nonnull:,}/{len(merged):,}")
        out_path = RES / out_name
        merged.to_parquet(out_path, compression="snappy", index=False)
        print("  wrote:", out_path)
        print("  regime dist:")
        print(merged.groupby(["asset", "regime_label"]).size().unstack(fill_value=0))
        print()


def augment_base_sleeves():
    panel_5m  = pd.read_parquet(REGIME_PANEL_5M)
    panel_15m = pd.read_parquet(REGIME_PANEL_15M)
    for src, out_name, default_tf in [
        (RES / "s15_with_ta_and_markov.parquet",   "s15_with_ta_and_markov_regime.parquet",   "5m"),
        (RES / "v15m_with_ta_and_markov.parquet",  "v15m_with_ta_and_markov_regime.parquet",  "15m"),
        (RES / "s6_with_ta.parquet",               "s6_with_ta_regime.parquet",               "5m"),
    ]:
        if not src.exists():
            print("missing:", src); continue
        df = pd.read_parquet(src)
        df = _detect_tf(df, default_tf)
        df = df[(df["fire_us"] >= WIN_START_US) & (df["fire_us"] < WIN_END_US)]
        print(f"{src.name}: {len(df):,} rows after window")
        merged = asof_join_regime(df, panel_5m, panel_15m, tf_default=default_tf)
        out_path = RES / out_name
        merged.to_parquet(out_path, compression="snappy", index=False)
        print(f"  wrote: {out_path}")
        if "regime_label" in merged.columns:
            print("  regime dist:")
            print(merged.groupby(["asset", "regime_label"]).size().unstack(fill_value=0))
        print()


def augment_gate_search_per_fire():
    """The gate_search_per_fire file has tf values like 's6_5m','s15_5m','s15_15m'.
    Map them then join."""
    src = RES / "hybrid_gate_search_per_fire.parquet"
    if not src.exists():
        print("missing:", src); return
    panel_5m  = pd.read_parquet(REGIME_PANEL_5M)
    panel_15m = pd.read_parquet(REGIME_PANEL_15M)
    df = pd.read_parquet(src)
    df = df[(df["fire_us"] >= WIN_START_US) & (df["fire_us"] < WIN_END_US)]
    df["tf_suffix"] = df["tf"].astype(str).str.extract(r"(15m|5m)$")[0]
    print(f"gate_search_per_fire: {len(df):,} rows post-window")
    print("  tf suffix dist:")
    print(df.groupby(["tf", "tf_suffix"]).size())

    out_chunks = []
    for asset in df["asset"].dropna().unique():
        for tf_suffix in df["tf_suffix"].dropna().unique():
            sub = df[(df["asset"] == asset) & (df["tf_suffix"] == tf_suffix)].copy()
            if sub.empty:
                continue
            panel = (panel_15m if tf_suffix == "15m" else panel_5m)
            panel = panel[panel["asset"] == asset].copy()
            sub["_fire_lookup_us"] = (sub["fire_us"].astype("int64") - 1_000_000)
            sub = sub.sort_values("_fire_lookup_us")
            tf_min = 15 if tf_suffix == "15m" else 5
            panel["_asof_us"] = panel["ts_us"].astype("int64") + tf_min * 60_000_000 - 1
            keep = ["_asof_us", "regime_label", "regime_score", "adx_14",
                    "realized_vol_60m", "tr_ema_stack_score", "ribbon_alignment_pct",
                    "range_compression", "trend_slope_30m", "bb_width_60s"]
            panel = panel[[c for c in keep if c in panel.columns]].sort_values("_asof_us")
            merged = pd.merge_asof(
                sub, panel,
                left_on="_fire_lookup_us", right_on="_asof_us",
                direction="backward",
                tolerance=20 * 60_000_000,
            )
            if "ribbon_alignment_pct" in merged.columns:
                merged = merged.rename(columns={"ribbon_alignment_pct": "ribbon_alignment_pct_regime"})
            out_chunks.append(merged)
    out = pd.concat(out_chunks, ignore_index=True)
    out_path = RES / "hybrid_gate_search_per_fire_regime.parquet"
    out.to_parquet(out_path, compression="snappy", index=False)
    print(f"wrote: {out_path}")
    print("regime dist:")
    print(out.groupby(["asset", "regime_label"]).size().unstack(fill_value=0))


if __name__ == "__main__":
    print("=== Augment hybrid features ===")
    augment_hybrid_features()
    print("=== Augment base sleeves ===")
    augment_base_sleeves()
    print("=== Augment gate_search per-fire ===")
    augment_gate_search_per_fire()
