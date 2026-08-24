"""
R7 — drop the orphaned pre-retention block from the HL 4h store.

Found in R1: BTC/ETH/SOL/AVAX/LINK each carry ~180 bars of April 2023 with
volume == 0.0 on EVERY bar, then a 10-month hole, then 20 partial bars in Feb 2024,
then continuous data from 2024-03. The HL API returns EMPTY for anything before
2024-03 (probed in _r0), so that early block cannot be repaired or extended.

Why it must go:
  * volume == 0 silently breaks every volume-dependent signal (V45 volume filter,
    MFI, volume-profile, signed-vol divergence) and the HMM's vol_ratio feature.
  * a disconnected 10-month-stale block still seeds EMA200 / SuperTrend warmup at
    the start of the real data, so the first months of real bars inherit prices
    from a different market.

Keeps a .bak of each file. Idempotent.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from strategy_lab.ingest_hyperliquid import KLINE_DIR, INTERVAL

MAX_GAP = pd.Timedelta("48h")   # a hole bigger than this ends the orphan prefix


def main():
    for d in sorted(KLINE_DIR.iterdir()):
        p = d / f"{INTERVAL}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p).sort_index()
        n0 = len(df)
        gaps = df.index.to_series().diff()
        big = gaps[gaps > MAX_GAP]
        if big.empty:
            print(f"{d.name:5s} n={n0:5d} contiguous, no orphan prefix — unchanged")
            continue
        cut = big.index[-1]                      # start of the final contiguous run
        keep = df[df.index >= cut]
        dropped = df[df.index < cut]
        zv = int((dropped.volume == 0).sum())
        p.rename(p.with_suffix(".parquet.bak"))
        keep.to_parquet(p)
        print(f"{d.name:5s} n={n0:5d} -> {len(keep):5d}  dropped {len(dropped)} bars "
              f"before {cut:%Y-%m-%d} ({zv} of them zero-volume)  bak kept")


if __name__ == "__main__":
    main()
