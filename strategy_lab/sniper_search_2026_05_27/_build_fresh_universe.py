"""Build fresh OOS fire universe across FULL canonical window (Apr 24 -> May 26 2026).

Produces 6 per-asset/tf parquet files (+6 filtered variants) covering ~33d for proper
3-way train/val/lockbox splits.

Conventions (per CLAUDE.md, DO NOT VIOLATE):
  - ws_s = slot_start_us // 1e6 - window_s
  - LegacyConfig (2% on profit only)
  - chainlink outcome
  - L25 walk via engine_v2.fill_at_book, spread 0.02 BTC/ETH, 0.025 SOL
  - $25 notional
  - Sequential builds; gc.collect() between markets

Output:  data/v4/canonical/_results/_full_window_v3_2026_05_27/
  oos_fires_{ASSET}_{TF}_full_v3.parquet         (all 20 offsets / 19 offsets per existing impl)
  oos_fires_{ASSET}_{TF}_v3_fixed.parquet         (canonical offset grid only)
"""
from __future__ import annotations

import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

# ---------------------------------------------------------------------------
# Window override -- FULL canonical span
# ---------------------------------------------------------------------------
OOS_START_US = int(pd.Timestamp("2026-04-24T01:00:00Z").value // 1000)
OOS_END_US   = int(pd.Timestamp("2026-05-26T17:30:00Z").value // 1000)

# Monkey-patch the v2 module so its OOS_START_US/OOS_END_US are overridden BEFORE
# we import its functions (build_oos_one_asset_tf reads module globals).
import full_window_validation_v2 as fwv2  # noqa: E402
fwv2.OOS_START_US = OOS_START_US
fwv2.OOS_END_US = OOS_END_US

from full_window_validation_v2 import build_oos_one_asset_tf, ASSETS  # noqa: E402
from load import load_klines_asof  # noqa: E402

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results" / "_full_window_v3_2026_05_27"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CANONICAL_OFFSETS = {
    "5m":  {30, 60, 90, 120, 150, 180, 210, 240, 270},
    "15m": {60, 120, 240, 360, 480, 600, 720, 840},
}

# All 6 markets, ordered to fail-fast on smallest first (SOL 15m new)
MARKETS = [
    ("SOL", "15m"),
    ("BTC", "5m"),
    ("ETH", "5m"),
    ("SOL", "5m"),
    ("BTC", "15m"),
    ("ETH", "15m"),
]


def _log(msg: str) -> None:
    ts = pd.Timestamp.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _summary(df: pd.DataFrame, asset: str, tf: str) -> None:
    if df is None or df.empty:
        _log(f"  WARN: {asset} {tf} empty df")
        return
    dt_min = pd.to_datetime(df["fire_us"].min(), unit="us", utc=True)
    dt_max = pd.to_datetime(df["fire_us"].max(), unit="us", utc=True)
    off_counts = df["fire_offset_s"].value_counts().sort_index()
    _log(f"  rows={len(df):,}  span=[{dt_min:%Y-%m-%d %H:%M} .. {dt_max:%Y-%m-%d %H:%M}]  "
         f"won.mean={df['won'].mean():.4f}")
    _log(f"  offsets:")
    for off, n in off_counts.items():
        _log(f"    {off}s -> {n:,}")


def main() -> int:
    t_start = time.time()
    _log("=" * 70)
    _log(f"WINDOW: [{pd.Timestamp(OOS_START_US, unit='us', tz='UTC')} .. "
         f"{pd.Timestamp(OOS_END_US, unit='us', tz='UTC')}]")
    _log(f"OUT_DIR: {OUT_DIR}")
    _log("=" * 70)

    _log("Loading 1m binance-spot-ws klines per asset...")
    klines_1m: dict[str, tuple] = {}
    for a in ASSETS:
        e, c = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        klines_1m[a] = (e.astype("int64"), c.astype("float64"))
        _log(f"  {a}: {len(e):,} 1m bars loaded")

    results: list[dict] = []
    failures: list[str] = []
    for asset, tf in MARKETS:
        t0 = time.time()
        _log("=" * 70)
        _log(f"BUILD {asset} {tf}")
        _log("=" * 70)
        try:
            df = build_oos_one_asset_tf(asset, tf, klines_1m)
        except Exception as e:  # don't lose progress; log + continue
            _log(f"  ERROR building {asset} {tf}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failures.append(f"{asset} {tf}: {e}")
            gc.collect()
            continue

        if df is None or df.empty:
            _log(f"  ERROR: empty df for {asset} {tf}")
            failures.append(f"{asset} {tf}: empty")
            gc.collect()
            continue

        full_path = OUT_DIR / f"oos_fires_{asset}_{tf}_full_v3.parquet"
        df.to_parquet(full_path, index=False, compression="zstd")
        _log(f"  wrote {full_path.name} ({full_path.stat().st_size / 1024 / 1024:.1f} MB)")
        _summary(df, asset, tf)

        # Filtered variant w/ canonical offset grid
        canon = CANONICAL_OFFSETS[tf]
        fixed = df[df["fire_offset_s"].isin(canon)].copy()
        fixed_path = OUT_DIR / f"oos_fires_{asset}_{tf}_v3_fixed.parquet"
        fixed.to_parquet(fixed_path, index=False, compression="zstd")
        _log(f"  wrote {fixed_path.name} (rows={len(fixed):,}, "
             f"{fixed_path.stat().st_size / 1024 / 1024:.1f} MB)")

        results.append({
            "asset": asset, "tf": tf,
            "n_full": len(df),
            "n_fixed": len(fixed),
            "won_mean": float(df["won"].mean()),
            "dt_min": str(pd.to_datetime(df["fire_us"].min(), unit="us", utc=True)),
            "dt_max": str(pd.to_datetime(df["fire_us"].max(), unit="us", utc=True)),
            "build_s": time.time() - t0,
        })

        del df, fixed
        gc.collect()

    _log("=" * 70)
    _log("DONE")
    _log("=" * 70)
    for r in results:
        _log(f"  {r['asset']:3s} {r['tf']:3s}  full={r['n_full']:>9,}  "
             f"fixed={r['n_fixed']:>9,}  won={r['won_mean']:.4f}  "
             f"build={r['build_s']/60:.1f}min")
    if failures:
        _log("FAILURES:")
        for f in failures:
            _log(f"  {f}")
    summary_df = pd.DataFrame(results)
    summary_df.to_csv(OUT_DIR / "_build_summary.csv", index=False)
    _log(f"summary -> {OUT_DIR / '_build_summary.csv'}")
    _log(f"TOTAL RUNTIME: {(time.time()-t_start)/60:.1f} min")
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
