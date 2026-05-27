"""Augment per-fire parquets with QR Lite meta-features via causal merge_asof.

For each per-fire parquet, look up the last fully-closed QR bar where
  bar_start + tf_s * 1_000_000 <= fire_us
We use ts_lookup_us = fire_us - 1us, then asof-merge on QR's `bar_close_us`
(which equals bar_start + tf - 1us). This guarantees the matched QR bar
has closed BEFORE the fire instant.

Outputs:
  data/v4/canonical/_results/s15_with_qr.parquet      (5m fires + qr_5m)
  data/v4/canonical/_results/s6_with_qr.parquet       (5m fires + qr_5m)
  data/v4/canonical/_results/v15m_with_qr.parquet     (15m fires + qr_15m)
"""
from __future__ import annotations
import sys, time, os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
QR5 = RES / "qr_panel_5m.parquet"
QR15 = RES / "qr_panel_15m.parquet"

# Source per-fire parquets (rich variants with TA+Markov)
S15_SRC = RES / "s15_with_ta_and_markov.parquet"
S6_SRC = RES / "s6_with_ta.parquet"
V15M_SRC = RES / "v15m_with_ta_and_markov.parquet"

OUT_S15 = RES / "s15_with_qr.parquet"
OUT_S6 = RES / "s6_with_qr.parquet"
OUT_V15M = RES / "v15m_with_qr.parquet"

# QR feature columns we want on per-fire output
QR_COLS = [
    "bull_align", "ribbon_state",
    "bullish_emas", "bearish_emas", "ribbon_aligned",
    "ribbon_expanding", "current_spread",
    "bars_above", "bars_below", "price_consistent",
    "market_regime", "market_health",
    "volume_ratio", "momentum_consistency", "signal_confidence",
]


def overlay(fires: pd.DataFrame, qr_panel: pd.DataFrame, name: str, out_path: Path, tf_label: str):
    print(f"\n[{name}] (tf={tf_label})")
    t0 = time.time()
    fires = fires.copy()
    # ts_lookup_us = fire_us - 1us (so we strictly hit a bar that closed BEFORE fire)
    fires["_lookup_us"] = fires["fire_us"].astype("int64") - 1
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        f_a = fires[fires.asset == asset].sort_values("_lookup_us").reset_index(drop=True)
        if len(f_a) == 0:
            continue
        q_a = qr_panel[qr_panel.asset == asset].sort_values("bar_close_us").reset_index(drop=True)
        q_a = q_a.rename(columns={c: f"qr_{c}" for c in QR_COLS})
        q_a = q_a[["bar_close_us"] + [f"qr_{c}" for c in QR_COLS]]
        merged = pd.merge_asof(
            f_a, q_a,
            left_on="_lookup_us", right_on="bar_close_us",
            direction="backward",
            tolerance=20 * 60 * 1_000_000,  # 20 minutes max gap
        )
        parts.append(merged)
        nfin = int(merged["qr_ribbon_state"].notna().sum())
        print(f"  {asset}: fires={len(f_a):,}  non-null qr_state={nfin:,}")
    aug = pd.concat(parts, ignore_index=True)
    aug = aug.drop(columns=["_lookup_us"])
    aug.to_parquet(out_path, index=False, compression="zstd")
    print(f"  wrote {out_path.name} ({os.path.getsize(out_path)/1024/1024:.1f} MB) in {time.time()-t0:.1f}s")
    return aug


def main():
    print("[1] loading QR panels...")
    qr5 = pd.read_parquet(QR5)
    qr15 = pd.read_parquet(QR15)
    print(f"  qr5: {len(qr5):,} rows | qr15: {len(qr15):,} rows")

    print("\n[2] augmenting S1.5 (5m)...")
    s15 = pd.read_parquet(S15_SRC)
    overlay(s15, qr5, "S1.5", OUT_S15, "5m")

    print("\n[3] augmenting S6 (5m)...")
    s6 = pd.read_parquet(S6_SRC)
    overlay(s6, qr5, "S6", OUT_S6, "5m")

    print("\n[4] augmenting V15M (15m)...")
    v15m = pd.read_parquet(V15M_SRC)
    overlay(v15m, qr15, "V15M", OUT_V15M, "15m")

    print("\n[5] sample row (S1.5):")
    aug = pd.read_parquet(OUT_S15)
    sample = aug.iloc[2000]
    for c in ["asset", "fire_offset_s", "direction", "won", "pnl_legacy_usd",
              "qr_ribbon_state", "qr_market_regime", "qr_market_health",
              "qr_signal_confidence", "qr_volume_ratio", "qr_momentum_consistency"]:
        if c in sample.index:
            print(f"  {c}: {sample[c]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
