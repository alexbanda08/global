"""
Audit the Binance 1m parquet dataset:
  * row counts per (symbol, year)
  * first/last timestamp per symbol
  * continuity gaps (missing minutes) — total count + top 10 longest
  * any duplicate timestamps
  * sanity: no zero/negative prices

Prints a single compact report.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent / "data" / "binance" / "parquet"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def load(symbol: str) -> pd.DataFrame:
    files = sorted((ROOT / symbol / "1m").glob("year=*/part.parquet"))
    dfs = [pd.read_parquet(f, columns=["open_time", "open", "high", "low", "close", "volume"])
           for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("open_time").reset_index(drop=True)
    return df


def audit(symbol: str) -> None:
    df = load(symbol)
    print(f"\n=== {symbol} ===")
    print(f"  rows:   {len(df):>12,}")
    print(f"  first:  {df['open_time'].iloc[0]}")
    print(f"  last:   {df['open_time'].iloc[-1]}")

    # Duplicates
    dups = int(df["open_time"].duplicated().sum())
    print(f"  dupes:  {dups}")

    # Sanity — zero or negative prices
    bad = int(((df[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum())
    print(f"  bad_prices: {bad}")

    # Expected minute grid vs actual
    expected = pd.date_range(df["open_time"].iloc[0],
                             df["open_time"].iloc[-1],
                             freq="1min", tz="UTC")
    missing = expected.difference(df["open_time"])
    pct = 100.0 * len(missing) / len(expected)
    print(f"  expected_bars: {len(expected):>12,}")
    print(f"  missing_bars:  {len(missing):>12,}  ({pct:.3f}%)")

    if len(missing) == 0:
        print("  gap_runs: (none)")
        return

    # Cluster missing minutes into contiguous runs
    s = pd.Series(missing).sort_values().reset_index(drop=True)
    delta = s.diff().dt.total_seconds().fillna(60)
    run_id = (delta > 60).cumsum()
    runs = (pd.DataFrame({"ts": s, "rid": run_id})
              .groupby("rid")
              .agg(start=("ts", "min"), end=("ts", "max"), n=("ts", "size"))
              .reset_index(drop=True))
    runs["minutes"] = runs["n"]
    runs["hours"]   = (runs["n"] / 60).round(2)

    print(f"  gap_runs_total: {len(runs)}")
    print("  top 10 longest:")
    top = runs.sort_values("minutes", ascending=False).head(10)
    for _, r in top.iterrows():
        print(f"    {r['start']} → {r['end']}   "
              f"{int(r['minutes']):>5} min ({r['hours']:>6} h)")


def main() -> int:
    print(f"Data root: {ROOT}")
    for s in SYMBOLS:
        audit(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
