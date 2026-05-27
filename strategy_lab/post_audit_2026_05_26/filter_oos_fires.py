"""TASK 2 STEP 1: Filter oos_fires_*_v2_fixed parquets to canonical 9-offset grid.

Reads the existing oos_fires_{asset}_{tf}.parquet files (which contain 20 offsets)
and writes _v2_fixed variants with only the canonical 9 offsets for 5m and 8 for 15m.

This corrects Bug #1 (fire-count inflation) without requiring a full panel rebuild
- the filter is causal/conservative; it merely DROPS surplus fires that were not
present in the train/val universe.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
SRC_DIR = ROOT / "data" / "v4" / "canonical" / "_results" / "_full_window_2026_05_26"
OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results" / "_full_window_2026_05_26"

OFFSETS_5M = {30, 60, 90, 120, 150, 180, 210, 240, 270}
OFFSETS_15M = {60, 120, 240, 360, 480, 600, 720, 840}

PAIRS = [
    ("BTC", "5m", OFFSETS_5M),
    ("ETH", "5m", OFFSETS_5M),
    ("SOL", "5m", OFFSETS_5M),
    ("BTC", "15m", OFFSETS_15M),
    ("ETH", "15m", OFFSETS_15M),
    ("SOL", "15m", OFFSETS_15M),
]


def main():
    rows = []
    for asset, tf, offsets in PAIRS:
        src = SRC_DIR / f"oos_fires_{asset}_{tf}.parquet"
        out = OUT_DIR / f"oos_fires_{asset}_{tf}_v2_fixed.parquet"
        if not src.exists():
            print(f"[SKIP] {src.name} missing")
            continue
        t0 = time.time()
        df = pd.read_parquet(src)
        n_before = len(df)
        df["fire_offset_s"] = df["fire_offset_s"].astype(int)
        kept = df[df["fire_offset_s"].isin(offsets)].copy()
        n_after = len(kept)
        # Sanity: confirm offsets
        kept_offsets = sorted(kept["fire_offset_s"].unique())
        # Quick PnL/WR delta check
        pnl_before = float(df["pnl_legacy_usd"].sum())
        pnl_after = float(kept["pnl_legacy_usd"].sum())
        wr_before = float(df["won"].mean())
        wr_after = float(kept["won"].mean())
        kept.to_parquet(out, index=False, compression="zstd")
        rows.append({
            "asset": asset, "tf": tf,
            "n_before": n_before, "n_after": n_after,
            "ratio": n_before / max(n_after, 1),
            "pnl_before": pnl_before, "pnl_after": pnl_after,
            "pnl_inflation": pnl_before / max(pnl_after, 1e-9),
            "wr_before": wr_before, "wr_after": wr_after,
            "offsets_kept": str(kept_offsets),
        })
        print(f"  {asset} {tf}: {n_before:,} -> {n_after:,} fires, "
              f"pnl ${pnl_before:,.0f} -> ${pnl_after:,.0f}, "
              f"WR {wr_before:.3f} -> {wr_after:.3f}, "
              f"saved -> {out.name} ({time.time()-t0:.1f}s)")

    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "strategy_lab" / "post_audit_2026_05_26" / "oos_filter_summary.csv", index=False)
    print(f"\nTotal n inflation ratio: {df['n_before'].sum() / df['n_after'].sum():.2f}x")
    print(f"Total pnl inflation ratio: {df['pnl_before'].sum() / df['pnl_after'].sum():.2f}x")


if __name__ == "__main__":
    main()
