"""Measure fire-to-fire latency + pre-slot-start firing for wallets.

Two questions:
  1. What's the median ms between consecutive fires? (tells us required
     execution speed)
  2. Do wallets fire BEFORE slot_start? (offset_from_slot_start_s < 0 means
     pre-mint + pre-post is happening)
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

WALLETS = {
    "0xeebde7a0": "$344k/day",
    "0x04b6d7e9": "$212k/day",
    "0x89b5cdaa": "$10k/day",
    "0xf7f0b0b1": "$281/day",
}

for short, label in WALLETS.items():
    p = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / short / "fires_decoded.parquet"
    if not p.exists():
        continue
    f = pd.read_parquet(p)
    f = f.dropna(subset=["ts_us"]).sort_values("ts_us")

    print(f"\n=== {short}  {label}  (n={len(f):,} fires)")

    # === Q1: fire-to-fire latency ===
    f["ts_ms"] = f.ts_us // 1000
    # Per-slug: gaps between consecutive fires
    gaps_ms_all = []
    for slug, g in f.groupby("slug"):
        if len(g) < 2:
            continue
        diffs = g.ts_ms.diff().dropna().astype(int)
        gaps_ms_all.extend(diffs.tolist())
    gaps = pd.Series(gaps_ms_all)
    if len(gaps):
        print(f"  fire-to-fire gap (same slug, ms):")
        print(f"    median={gaps.median():.0f}  p25={gaps.quantile(0.25):.0f}  p75={gaps.quantile(0.75):.0f}  p10={gaps.quantile(0.10):.0f}  p90={gaps.quantile(0.90):.0f}")
        sub_500ms = (gaps < 500).mean() * 100
        sub_1s = (gaps < 1000).mean() * 100
        sub_5s = (gaps < 5000).mean() * 100
        print(f"    %gaps <500ms: {sub_500ms:.1f}%   <1s: {sub_1s:.1f}%   <5s: {sub_5s:.1f}%")

    # === Q2: offset from slot_start ===
    if "offset_from_slot_start_s" in f.columns:
        off = f.offset_from_slot_start_s.dropna()
        if len(off):
            print(f"  offset_from_slot_start_s (negative = pre-slot-start):")
            print(f"    median={off.median():.1f}s  p25={off.quantile(0.25):.1f}s  p75={off.quantile(0.75):.1f}s")
            print(f"    min={off.min():.1f}s  max={off.max():.1f}s")
            n_pre = (off < 0).sum()
            n_post_5m = (off > 300).sum()
            n_in_15m = ((off >= 0) & (off <= 900)).sum()
            print(f"    %fires PRE slot_start (offset<0):       {100*n_pre/len(off):.1f}% (n={n_pre})")
            print(f"    %fires WITHIN 0-15min window:          {100*n_in_15m/len(off):.1f}% (n={n_in_15m})")
            print(f"    %fires AFTER 5min into slug:           {100*n_post_5m/len(off):.1f}% (n={n_post_5m})")
