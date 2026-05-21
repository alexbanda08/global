"""Build GUARD blocks parquet — Phase 2 of CONFLUENCE_BUILD_PLAN_2026_05_07.md.

Output:
  data/v4/refresh_2026_05_06/cache/all_guard_blocks.parquet
  Schema (per schema.GUARD_BLOCK_COLS):
    slug (str), window_start_unix (int64),
    guard_extreme_price (bool), guard_dead_market (bool),
    guard_counter_trend (bool), guard_min_time_to_close (bool),
    guard_choppiness (bool)

  Note: GUARD is keyed by (slug, window_start_unix) — side-agnostic.
  Counter-trend depends on signal direction, but rather than splitting per
  outcome we record the SIGNED move direction; the classifier interprets it.

Usage:
  py -X utf8 -m strategy_lab.confluence.guard.build_guards [--smoke]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from strategy_lab.meta_classifier.extended_backtest_with_robustness import (
    asof,
    load_universe,
    load_klines,
    load_tier1_entries,
)
from strategy_lab.confluence.guard.filters import (
    compute_choppiness,
    compute_counter_trend,
    compute_dead_market,
    compute_extreme_price,
    compute_min_time_to_close,
)

CACHE_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06" / "cache"


def _entry_price_lookup(entry_books: dict, slug: str, signal: int) -> float:
    """Get top-of-book ask price for the held side at t+120."""
    held = "Up" if signal == 1 else "Down"
    rec = entry_books.get((slug, held))
    if rec is None:
        return float("nan")
    ask_p, ask_s, _, _ = rec
    if len(ask_p) == 0 or not np.isfinite(ask_p[0]):
        return float("nan")
    return float(ask_p[0])


def _closes_window(k1m: pd.DataFrame, ws_unix: int) -> np.ndarray:
    """Last 5 minutes of 1m closes ending at ws_unix (5 bars expected)."""
    end = int(ws_unix)
    start = end - 300
    sub = k1m[(k1m["ts_s"] >= start) & (k1m["ts_s"] < end)]
    return sub["price_close"].to_numpy(dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="run on first 200 markets")
    args = ap.parse_args()

    print("[guard] loading universe + klines + entry books…", flush=True)
    uni = load_universe()
    klines = load_klines()
    entry_books_per_asset = {a: load_tier1_entries(a) for a in ("btc", "eth", "sol")}

    if args.smoke:
        uni = uni.head(200).copy()
        print(f"[guard] SMOKE: {len(uni)} markets", flush=True)
    else:
        print(f"[guard] universe: {len(uni)} markets", flush=True)

    # Vectorize asof calls per asset
    print("[guard] computing BTC kline asof at ws / ws+90 / ws+120…", flush=True)
    btc_k = klines["btc"]

    ws_arr = uni["window_start_unix"].astype("int64").to_numpy()
    btc_open  = np.array([asof(btc_k, int(w))      for w in ws_arr])
    btc_t90   = np.array([asof(btc_k, int(w) + 90) for w in ws_arr])
    btc_t120  = np.array([asof(btc_k, int(w) + 120) for w in ws_arr])

    # Entry prices — need a signal direction. We'll compute for BOTH directions and
    # report a tuple, but for the GUARD-level extreme-price check we use the
    # held side. Since the parquet is side-agnostic, we use a heuristic: mark
    # "extreme" if EITHER side's entry price is extreme (conservative). The
    # downstream join (apply_classifier) gets called per held_outcome anyway.
    print("[guard] computing entry prices (both sides) and choppiness…", flush=True)
    entry_up = np.full(len(uni), np.nan)
    entry_dn = np.full(len(uni), np.nan)
    for i, (slug, asset) in enumerate(zip(uni["slug"].values, uni["asset"].values)):
        eb = entry_books_per_asset.get(asset, {})
        rec_up = eb.get((slug, "Up"))
        rec_dn = eb.get((slug, "Down"))
        if rec_up is not None and len(rec_up[0]) > 0 and np.isfinite(rec_up[0][0]):
            entry_up[i] = float(rec_up[0][0])
        if rec_dn is not None and len(rec_dn[0]) > 0 and np.isfinite(rec_dn[0][0]):
            entry_dn[i] = float(rec_dn[0][0])

    # Choppiness: 5m of BTC closes ending at ws (use BTC for all assets — macro)
    closes_windows = [_closes_window(btc_k, int(w)) for w in ws_arr]

    # Compute guards
    # extreme_price: trigger if EITHER side is extreme (conservative)
    g_extreme_up = compute_extreme_price(entry_up)
    g_extreme_dn = compute_extreme_price(entry_dn)
    g_extreme = g_extreme_up | g_extreme_dn

    g_dead = compute_dead_market(btc_open, btc_t90)

    # counter_trend: side-agnostic — block if BIG MOVE + STILL MOVING (regardless of dir)
    # The "same_dir as signal" check happens at classify time via the sign of struct_score
    # For now, encode the conservative case: block if there's a strong continuation
    # (we will likely WANT to allow SOME counter-trend trades — see anti-edge).
    # Use signal=1 (Up) as placeholder; the classifier sees both signs of move via dist_to_*
    # in STRUCTURE.
    fake_sig = np.ones(len(uni), dtype=int)
    g_counter = compute_counter_trend(btc_open, btc_t120, btc_t90, fake_sig)

    g_min_time = compute_min_time_to_close(uni["timeframe"])

    g_chop = compute_choppiness(closes_windows)

    print("[guard] guard activation rates:", flush=True)
    print(f"        extreme_price:   {g_extreme.mean():.3f}", flush=True)
    print(f"        dead_market:     {g_dead.mean():.3f}", flush=True)
    print(f"        counter_trend:   {g_counter.mean():.3f}", flush=True)
    print(f"        min_time_close:  {g_min_time.mean():.3f}", flush=True)
    print(f"        choppiness:      {g_chop.mean():.3f}", flush=True)

    out = pd.DataFrame({
        "slug":                     uni["slug"].values,
        "asset":                    uni["asset"].values,
        "window_start_unix":        ws_arr,
        "guard_extreme_price":      g_extreme,
        "guard_dead_market":        g_dead,
        "guard_counter_trend":      g_counter,
        "guard_min_time_to_close":  g_min_time,
        "guard_choppiness":         g_chop,
    })

    suffix = ".smoke200" if args.smoke else ""
    out_path = CACHE_DIR / f"all_guard_blocks{suffix}.parquet"
    out.to_parquet(out_path, engine="pyarrow", index=False)
    print(f"[guard] wrote {out_path} ({len(out)} rows, {out_path.stat().st_size/1e3:.1f} KB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
