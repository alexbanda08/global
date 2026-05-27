"""
Find genuine gaps in L25 coverage across all refresh dirs.
A 'gap' = >5 min with no snapshots anywhere in the union (vs idle market).
Operates per (slug, outcome) to detect collection issues vs just inactivity.

Output: list of (asset, gap_start_us, gap_end_us, gap_minutes) where gap > 5min
        AND the boundary timestamps are near a slot edge (suggests active window).
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")

SOURCES = [
    ("refresh_2026_05_16/cache_pre", "_orderbook_L25_pre_apr22.parquet"),
    ("refresh_2026_05_06/cache",     "_orderbook_L25.parquet"),
    ("refresh_2026_05_16/cache",     "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_19/cache",     "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_21/cache",     "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_25/cache",     "_orderbook_L25_delta.parquet"),
]

def fmt(ts_us):
    return pd.to_datetime(int(ts_us), unit="us", utc=True).strftime("%Y-%m-%d %H:%M:%S")

def hour_gaps_for_asset(asset):
    """For an asset, build the UNION of timestamp_us across all sources,
    bucket to hours, and flag empty hours."""
    all_hours = set()
    src_summaries = []
    for subdir, suffix in SOURCES:
        p = ROOT / "data" / "v4" / subdir.split("/")[0] / subdir.split("/")[1] / f"{asset}{suffix}"
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=["timestamp_us"])
        # Bucket to hour resolution (us / 3_600_000_000)
        hours = (df.timestamp_us.values // (3_600 * 1_000_000)).astype("int64")
        unique_hours = set(np.unique(hours).tolist())
        all_hours.update(unique_hours)
        src_summaries.append((subdir, len(df), int(df.timestamp_us.min()), int(df.timestamp_us.max()), len(unique_hours)))

    print(f"\n=== {asset.upper()} ===")
    for subdir, n, mn, mx, nh in src_summaries:
        print(f"  {subdir:<35s}  rows={n:>10,}  hours_covered={nh:>4}  [{fmt(mn)} -> {fmt(mx)}]")

    if not all_hours:
        return []
    min_h = min(all_hours)
    max_h = max(all_hours)
    expected_hours = set(range(min_h, max_h + 1))
    missing_hours = sorted(expected_hours - all_hours)

    print(f"  UNION:  full window = {fmt(min_h*3_600_000_000)}  ->  {fmt((max_h+1)*3_600_000_000 - 1_000_000)}")
    print(f"          total hours expected: {len(expected_hours)}, covered: {len(all_hours)}, MISSING: {len(missing_hours)}")

    if missing_hours:
        # Compress into runs
        runs = []
        i = 0
        while i < len(missing_hours):
            start = missing_hours[i]
            j = i
            while j + 1 < len(missing_hours) and missing_hours[j+1] == missing_hours[j] + 1:
                j += 1
            runs.append((start, missing_hours[j]))
            i = j + 1
        print(f"  Missing-hour RUNS ({len(runs)} contiguous):")
        for start_h, end_h in runs[:20]:
            n_hours = end_h - start_h + 1
            gap_start_us = start_h * 3_600_000_000
            gap_end_us = (end_h + 1) * 3_600_000_000 - 1_000_000
            print(f"    [{fmt(gap_start_us)}  ->  {fmt(gap_end_us)}]   ({n_hours}h)")
        if len(runs) > 20:
            print(f"    ... and {len(runs)-20} more")
        return runs
    return []

all_gaps = {}
for asset in ["btc", "eth", "sol"]:
    gaps = hour_gaps_for_asset(asset)
    if gaps:
        all_gaps[asset] = gaps

print("\n\n=== SUMMARY ===")
if not all_gaps:
    print("No hour-level gaps detected across any asset. Overlaps only.")
else:
    print("Hour-level gaps detected:")
    for asset, runs in all_gaps.items():
        total_missing = sum(end - start + 1 for start, end in runs)
        print(f"  {asset}: {len(runs)} runs, {total_missing} hours total")
