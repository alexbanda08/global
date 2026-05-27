"""Overlay Traders Reality panel onto S1.5 / S6 / s15+markov per-fire parquets.

Outputs:
  data/v4/canonical/_results/s15_with_tr.parquet
  data/v4/canonical/_results/s6_with_tr.parquet
  data/v4/canonical/_results/s15_with_ta_markov_tr.parquet
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TR = ROOT / "data" / "v4" / "canonical" / "_results" / "traders_reality_1s.parquet"

S15 = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_slot_anchored_5m_per_fire.parquet"
S6 = ROOT / "data" / "v4" / "canonical" / "_results" / "spike_entry_5m_per_fire.parquet"
S15_TA_MARKOV = ROOT / "data" / "v4" / "canonical" / "_results" / "s15_with_ta_and_markov.parquet"

OUT_S15 = ROOT / "data" / "v4" / "canonical" / "_results" / "s15_with_tr.parquet"
OUT_S6 = ROOT / "data" / "v4" / "canonical" / "_results" / "s6_with_tr.parquet"
OUT_S15_TM = ROOT / "data" / "v4" / "canonical" / "_results" / "s15_with_ta_markov_tr.parquet"


def overlay(fires: pd.DataFrame, tr: pd.DataFrame, name: str, out_path: Path) -> pd.DataFrame:
    print(f"\n[{name}]")
    t0 = time.time()
    # Causal: subtract 1s from fire_us so we only see the bar that ended BEFORE fire.
    fires = fires.copy()
    fires["ts_us"] = (fires["fire_us"].astype("int64") - 1_000_000)
    fires_sorted = fires.sort_values(["asset", "ts_us"]).reset_index(drop=True)

    # Pre-drop overlapping cols on fires side (asset+ts_us are merge keys; keep them)
    tr_cols = [c for c in tr.columns if c not in ("asset", "ts_us")]
    # Avoid duplicating any name fires already has (e.g. close)
    drop_dups = [c for c in tr_cols if c in fires_sorted.columns]
    if drop_dups:
        # Suffix tr cols to avoid collision
        rename_map = {c: f"tr_{c}" if not c.startswith("tr_") else c for c in drop_dups}
        # Only rename for collisions
        tr = tr.rename(columns=rename_map)
        tr_cols = [c for c in tr.columns if c not in ("asset", "ts_us")]

    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        f_a = fires_sorted[fires_sorted.asset == asset].copy()
        if len(f_a) == 0:
            continue
        t_a = tr[tr.asset == asset][["ts_us"] + tr_cols].sort_values("ts_us")
        merged = pd.merge_asof(
            f_a.sort_values("ts_us"),
            t_a,
            on="ts_us",
            direction="backward",
            tolerance=10_000_000,
        )
        parts.append(merged)
        non_null = merged["tr_ema_stack_score"].notna().sum() if "tr_ema_stack_score" in merged.columns else 0
        print(f"  {asset}: {len(f_a):,} fires merged; non-null stack_score: {non_null:,}")
    augmented = pd.concat(parts, ignore_index=True)
    print(f"  total rows: {len(augmented):,} in {time.time()-t0:.1f}s")
    augmented.to_parquet(out_path, index=False, compression="zstd")
    print(f"  wrote {out_path}  ({os.path.getsize(out_path)/1024/1024:.1f} MB)")
    return augmented


def main():
    print("[1] loading TR panel...")
    t0 = time.time()
    tr = pd.read_parquet(TR)
    print(f"  {len(tr):,} rows in {time.time()-t0:.1f}s, cols={len(tr.columns)}")

    for src, out in [(S15, OUT_S15), (S6, OUT_S6), (S15_TA_MARKOV, OUT_S15_TM)]:
        if not src.exists():
            print(f"  SKIP missing: {src}")
            continue
        print(f"\n[load] {src.name}")
        fires = pd.read_parquet(src)
        print(f"  {len(fires):,} fires, cols={len(fires.columns)}")
        overlay(fires, tr, src.stem, out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
