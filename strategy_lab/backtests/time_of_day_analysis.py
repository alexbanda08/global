"""
Time-of-day + offset_from_slot_start patterns per wallet.

For each wallet's fills:
  - UTC hour distribution (do they trade certain hours?)
  - Offset-from-slot-start distribution (early/mid/late slug timing)
  - Maker fill rate by hour / offset
  - PnL per slug bucketed by hour
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WCACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
OUT = ROOT / "strategy_lab" / "backtests"
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

WALLETS = ["0x04b6d7e9", "0xeebde7a0", "0x89b5cdaa", "0xcfb103c3", "0xce25e214"]


def analyze(w: str):
    p = WCACHE / w / "fills.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df = df[df["mc"].isin(["updown_5m", "updown_15m"])]
    if df.empty:
        return None
    df["ts_dt"] = pd.to_datetime(df["ts_s"], unit="s", utc=True)
    df["hour"] = df["ts_dt"].dt.hour
    df["dow"] = df["ts_dt"].dt.dayofweek

    # Per-hour stats
    by_hour = df.groupby("hour").agg(
        n_fills=("size", "count"),
        n_slugs=("slug", "nunique"),
        median_size=("size", "median"),
        maker_pct=("is_maker", "mean"),
        sell_pct=("side", lambda s: (s == "SELL").mean() * 100),
    ).reset_index()
    by_hour["maker_pct"] = by_hour["maker_pct"] * 100

    # Per-offset bucket
    df["offset_bucket"] = pd.cut(df["offset_from_slot_start_s"],
                                   bins=[-100, 0, 30, 60, 120, 180, 240, 300, 600, 1000],
                                   labels=["<0", "0-30", "30-60", "60-120", "120-180",
                                           "180-240", "240-300", "300-600", "600-1000"])
    by_off = df.groupby("offset_bucket", observed=True).agg(
        n_fills=("size", "count"),
        median_size=("size", "median"),
        maker_pct=("is_maker", "mean"),
    ).reset_index()
    by_off["maker_pct"] = by_off["maker_pct"] * 100
    by_off["pct_of_fills"] = by_off["n_fills"] / by_off["n_fills"].sum() * 100

    return {"wallet": w, "by_hour": by_hour, "by_offset": by_off}


def main():
    print("\n" + "=" * 100)
    print("TIME-OF-DAY + OFFSET ANALYSIS PER WALLET")
    print("=" * 100)

    all_hour_rows = []
    all_off_rows = []
    for w in WALLETS:
        result = analyze(w)
        if not result:
            continue
        print(f"\n=== {w} ===")
        print("\nHourly distribution (UTC):")
        cols = ["hour", "n_fills", "n_slugs", "median_size", "maker_pct", "sell_pct"]
        print(result["by_hour"][cols].to_string(index=False))
        result["by_hour"]["wallet"] = w
        all_hour_rows.append(result["by_hour"])

        print("\nOffset_from_slot_start distribution:")
        cols = ["offset_bucket", "n_fills", "pct_of_fills", "median_size", "maker_pct"]
        print(result["by_offset"][cols].to_string(index=False))
        result["by_offset"]["wallet"] = w
        all_off_rows.append(result["by_offset"])

    if all_hour_rows:
        pd.concat(all_hour_rows, ignore_index=True).to_csv(
            OUT / "_time_of_day_hourly.csv", index=False
        )
    if all_off_rows:
        pd.concat(all_off_rows, ignore_index=True).to_csv(
            OUT / "_time_of_day_offset.csv", index=False
        )


if __name__ == "__main__":
    main()
