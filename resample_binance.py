"""
Resample 1m Binance parquet into {5m, 15m, 1h, 4h, 1d} parquet files.

Input : data/binance/parquet/{SYMBOL}/1m/year=YYYY/part.parquet
Output: data/binance/parquet/{SYMBOL}/{TF}/year=YYYY/part.parquet

Aggregation rules (standard OHLCV):
  open            → first
  high            → max
  low             → min
  close           → last
  volume          → sum
  quote_volume    → sum
  trades          → sum
  taker_buy_base  → sum
  taker_buy_quote → sum

Uses left-closed, left-labeled bins so bar timestamp = bar START
(same convention Binance uses in klines).

Idempotent: regenerates only if the 1m source year is newer than the
target year parquet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent / "data" / "binance" / "parquet"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Pandas freq strings — 'min', 'h', 'D' to avoid future-deprecation warnings.
TIMEFRAMES: dict[str, str] = {
    "5m":  "5min",
    "15m": "15min",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1D",
}

AGG = {
    "open":            "first",
    "high":            "max",
    "low":             "min",
    "close":           "last",
    "volume":          "sum",
    "quote_volume":    "sum",
    "trades":          "sum",
    "taker_buy_base":  "sum",
    "taker_buy_quote": "sum",
}


def resample_year(symbol: str, tf: str, freq: str, year: int) -> int:
    src = ROOT / symbol / "1m" / f"year={year}" / "part.parquet"
    if not src.exists():
        return 0

    dst_dir = ROOT / symbol / tf / f"year={year}"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "part.parquet"

    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return 0  # up to date

    # Include prior year tail so multi-day/hour buckets that span year boundary
    # are computed correctly; we'll trim to year at the end.
    prev_src = ROOT / symbol / "1m" / f"year={year-1}" / "part.parquet"
    frames = []
    if prev_src.exists() and freq in {"4h", "1D"}:
        frames.append(pd.read_parquet(prev_src).tail(2500))  # ~2 days
    frames.append(pd.read_parquet(src))
    df = pd.concat(frames, ignore_index=True)

    df = df.set_index("open_time").sort_index()
    out = df.resample(freq, label="left", closed="left").agg(AGG).dropna(subset=["open"])
    out = out[out.index.year == year].reset_index()
    out = out.rename(columns={"open_time": "open_time"})

    out.to_parquet(dst, engine="pyarrow", compression="zstd", index=False)
    return len(out)


def main() -> int:
    total = 0
    for sym in SYMBOLS:
        years = sorted(int(p.name.split("=")[1])
                       for p in (ROOT / sym / "1m").glob("year=*"))
        for tf, freq in TIMEFRAMES.items():
            sym_rows = 0
            for y in years:
                sym_rows += resample_year(sym, tf, freq, y)
            if sym_rows:
                print(f"  {sym} {tf}: +{sym_rows:,} rows across {len(years)} years")
                total += sym_rows
    print(f"Total rows written: {total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
