"""Overlay TA indicators on S1.5 + S6 per-fire data via merge_asof.

Produces augmented parquets:
  data/v4/canonical/_results/s15_with_ta.parquet
  data/v4/canonical/_results/s6_with_ta.parquet
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TA = ROOT / "data" / "v4" / "canonical" / "_results" / "ta_indicators_1s.parquet"
S15 = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_slot_anchored_5m_per_fire.parquet"
S6 = ROOT / "data" / "v4" / "canonical" / "_results" / "spike_entry_5m_per_fire.parquet"
OUT_S15 = ROOT / "data" / "v4" / "canonical" / "_results" / "s15_with_ta.parquet"
OUT_S6 = ROOT / "data" / "v4" / "canonical" / "_results" / "s6_with_ta.parquet"


def overlay(fires, ta, name, out_path):
    print(f"\n[{name}]")
    print(f"  loading...")
    t0 = time.time()
    fires["ts_us"] = fires["fire_us"].astype("int64")
    fires_sorted = fires.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    print(f"  {len(fires_sorted):,} fires; running merge_asof per asset...")
    out_parts = []
    ta_cols = [c for c in ta.columns if c not in ("asset", "ts_us")]
    for asset in ("BTC", "ETH", "SOL"):
        f_a = fires_sorted[fires_sorted.asset == asset].copy()
        t_a = ta[ta.asset == asset].copy()
        merged = pd.merge_asof(
            f_a.sort_values("ts_us"),
            t_a.sort_values("ts_us")[["ts_us"] + ta_cols],
            on="ts_us", direction="backward", tolerance=10_000_000,  # 10s tolerance
        )
        out_parts.append(merged)
        print(f"    {asset}: {len(f_a):,} fires merged; non-null ribbon: {merged.ribbon_color.notna().sum():,}")
    augmented = pd.concat(out_parts, ignore_index=True)
    print(f"  augmented rows: {len(augmented):,} in {time.time()-t0:.1f}s")
    augmented.to_parquet(out_path, index=False, compression="zstd")
    print(f"  wrote {out_path}")
    return augmented


def main():
    print("[1] loading TA indicators...")
    t0 = time.time()
    ta = pd.read_parquet(TA)
    print(f"  {len(ta):,} rows in {time.time()-t0:.1f}s")

    print("[2] S1.5 overlay...")
    s15 = pd.read_parquet(S15)
    overlay(s15, ta, "S1.5", OUT_S15)

    print("\n[3] S6 overlay...")
    s6 = pd.read_parquet(S6)
    overlay(s6, ta, "S6", OUT_S6)

    print("\n[4] sample augmented S1.5 row:")
    aug = pd.read_parquet(OUT_S15)
    sample = aug.iloc[1000]
    for c in ["asset","fire_offset_s","direction","won","pnl_legacy_usd",
              "ribbon_color","ribbon_alignment_pct","ribbon_compression_bps",
              "ribbon_lead_slope_bps","ribbon_lead_vs_ref_bps",
              "stoch_k_60s","stoch_d_60s","bb_pos_60s","mfi_60s","cci_60s"]:
        if c in sample.index:
            print(f"  {c}: {sample[c]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
