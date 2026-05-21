"""
Build comprehensive per-slug feature table for BTC updown slugs.

For every BTC 5m + 15m slug in the canonical window, compute:
  - Opening book features (earliest L25 snapshot per outcome)
  - Binance leading features (ret/vol over 60s/120s leading into slot_start)
  - Time features (hour_utc, weekday, minute_in_hour, slot_offset_in_hour)
  - Slug metadata (tf, asset, slot_start_s)

Output: strategy_lab/backtests/_per_slug_features_btc.csv

Usage:
    py -3 -X utf8 strategy_lab/backtests/build_slug_features.py [--asset btc]
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"
OUT_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines_asof, load_resolutions, asof_strict  # noqa: E402

L25_SOURCES = {
    "btc": [
        ROOT / "data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet",
        ROOT / "data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet",
    ],
    "eth": [
        ROOT / "data/v4/refresh_2026_05_06/cache/eth_orderbook_L25.parquet",
        ROOT / "data/v4/refresh_2026_05_16/cache/eth_orderbook_L25_delta.parquet",
    ],
    "sol": [
        ROOT / "data/v4/refresh_2026_05_06/cache/sol_orderbook_L25.parquet",
        ROOT / "data/v4/refresh_2026_05_16/cache/sol_orderbook_L25_delta.parquet",
    ],
}


def get_open_books(asset: str) -> pd.DataFrame:
    """Earliest L25 snapshot per (slug, outcome) for given asset."""
    asset_l = asset.lower()
    parts = []
    for src in L25_SOURCES[asset_l]:
        if not src.exists():
            continue
        pf = pq.ParquetFile(str(src))
        for rg_idx in range(pf.metadata.num_row_groups):
            try:
                rg = pf.read_row_group(rg_idx, columns=[
                    "timestamp_us", "slug", "outcome",
                    "bid_price_0", "bid_size_0",
                    "ask_price_0", "ask_size_0",
                ])
            except Exception:
                continue
            df = rg.to_pandas()
            df = df[df["slug"].str.startswith(f"{asset_l}-updown-")]
            if df.empty:
                continue
            parts.append(df)
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values("timestamp_us").drop_duplicates(["slug", "outcome"], keep="first")
    return df


def book_features(open_books: pd.DataFrame) -> pd.DataFrame:
    """Pivot open books → per-slug feature columns."""
    if open_books.empty:
        return pd.DataFrame()
    pivot = open_books.pivot_table(
        index="slug",
        columns="outcome",
        values=["bid_price_0", "ask_price_0", "bid_size_0", "ask_size_0", "timestamp_us"],
        aggfunc="first",
    )
    pivot.columns = [f"{a}_{b.lower()}" for a, b in pivot.columns]
    pivot = pivot.reset_index()

    # Core book features
    pivot["sum_bids"] = pivot["bid_price_0_up"] + pivot["bid_price_0_down"]
    pivot["sum_asks"] = pivot["ask_price_0_up"] + pivot["ask_price_0_down"]
    pivot["spread_up"] = pivot["ask_price_0_up"] - pivot["bid_price_0_up"]
    pivot["spread_dn"] = pivot["ask_price_0_down"] - pivot["bid_price_0_down"]
    pivot["mid_up"] = (pivot["bid_price_0_up"] + pivot["ask_price_0_up"]) / 2
    pivot["mid_dn"] = (pivot["bid_price_0_down"] + pivot["ask_price_0_down"]) / 2
    pivot["mid_diff"] = pivot["mid_up"] - pivot["mid_dn"]
    pivot["depth_up"] = pivot["bid_size_0_up"] + pivot["ask_size_0_up"]
    pivot["depth_dn"] = pivot["bid_size_0_down"] + pivot["ask_size_0_down"]
    pivot["depth_tot"] = pivot["depth_up"] + pivot["depth_dn"]
    pivot["depth_imb"] = (pivot["depth_up"] - pivot["depth_dn"]) / pivot["depth_tot"].clip(lower=1)

    # Earliest book observation time per slug (max of up/down first-event)
    pivot["open_book_us"] = pivot[["timestamp_us_up", "timestamp_us_down"]].max(axis=1)

    return pivot


def add_slug_metadata(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Add slot_start_s, tf, asset, time features from slug."""
    df = df.copy()
    df["slot_start_s"] = df["slug"].str.rsplit("-", n=1).str[-1].astype("int64")
    df["tf"] = df["slug"].str.extract(r"-(\d+m)-")[0]
    df["asset"] = asset.upper()
    df["window_s"] = df["tf"].map({"5m": 300, "15m": 900}).fillna(300).astype("int64")
    # ws_s = slot_start - window_s (production anchor, per CLAUDE.md)
    df["ws_s"] = df["slot_start_s"] - df["window_s"]
    df["fire_s"] = df["ws_s"] + 120  # production fire_us
    df["hour_utc"] = ((df["slot_start_s"] // 3600) % 24).astype(int)
    df["weekday"] = pd.to_datetime(df["slot_start_s"], unit="s", utc=True).dt.weekday
    df["min_in_hour"] = ((df["slot_start_s"] % 3600) // 60).astype(int)
    # For 5m slugs: offset 0..55 in 5m steps; for 15m: 0/15/30/45
    df["slot_offset_min"] = df["min_in_hour"].copy()
    return df


def add_binance_features(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    """Add binance 1m kline-based leading features at ws_s anchor.

    We anchor on ws_s (= slot_start - window) — the production signal anchor.
    Features:
      ret_60s, ret_120s : log-return ending at ws_s
      abs_ret_60s, abs_ret_120s : magnitudes (vol proxy)
      vol_5m : stdev of 1m log-returns over 5 bars ending at ws_s
      vol_10m : same over 10 bars
    """
    end_us, close = load_klines_asof(asset.upper(), "binance-spot-ws", "1MIN")
    if len(end_us) == 0:
        for col in ["ret_60s", "ret_120s", "abs_ret_60s", "abs_ret_120s", "vol_5m", "vol_10m"]:
            df[col] = np.nan
        return df

    # All ws_s values
    ws_us = (df["ws_s"].values.astype("int64") * 1_000_000)

    # Build vectorized lookups via searchsorted
    # asof_strict equivalent: idx = bisect_right(end_us, target) - 1
    def asof_vec(target_us_arr: np.ndarray) -> np.ndarray:
        idx = np.searchsorted(end_us, target_us_arr, side="right") - 1
        out = np.full(len(target_us_arr), np.nan, dtype="float64")
        mask = idx >= 0
        out[mask] = close[idx[mask]]
        return out

    p_now = asof_vec(ws_us)
    p_60 = asof_vec(ws_us - 60 * 1_000_000)
    p_120 = asof_vec(ws_us - 120 * 1_000_000)
    p_300 = asof_vec(ws_us - 300 * 1_000_000)
    p_600 = asof_vec(ws_us - 600 * 1_000_000)

    df["binance_close_at_ws"] = p_now
    with np.errstate(invalid="ignore", divide="ignore"):
        df["ret_60s"] = np.log(p_now / p_60)
        df["ret_120s"] = np.log(p_now / p_120)
        df["abs_ret_60s"] = np.abs(df["ret_60s"])
        df["abs_ret_120s"] = np.abs(df["ret_120s"])
        # 5m / 10m realized vol = stdev of 1m log-rets over n bars
        # Approximation: use rolling std over the closest available bars per ws_s
        # Build by finding idx of bar ending nearest each ws_s and slicing.

    # Vol: realized std of 1m log-returns over N bars ending at ws_s
    n_total = len(end_us)
    log_rets_1m = np.full(n_total, np.nan, dtype="float64")
    log_rets_1m[1:] = np.log(close[1:] / close[:-1])

    def rolling_std_at(target_us_arr: np.ndarray, n_bars: int) -> np.ndarray:
        out = np.full(len(target_us_arr), np.nan, dtype="float64")
        idx = np.searchsorted(end_us, target_us_arr, side="right") - 1
        for i, j in enumerate(idx):
            if j < n_bars:
                continue
            window = log_rets_1m[j - n_bars + 1: j + 1]
            if np.isnan(window).any():
                continue
            out[i] = window.std()
        return out

    df["vol_5m"] = rolling_std_at(ws_us, 5)
    df["vol_10m"] = rolling_std_at(ws_us, 10)

    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="btc", choices=["btc", "eth", "sol"])
    ap.add_argument("--out-suffix", default="")
    args = ap.parse_args()

    asset = args.asset.lower()
    print(f"[1/4] Loading L25 open-books for {asset.upper()} ...")
    t0 = time.time()
    open_books = get_open_books(asset)
    print(f"      {len(open_books)} open-book rows in {time.time()-t0:.1f}s")
    if open_books.empty:
        print("ERROR: no open-book data")
        return

    print(f"[2/4] Computing book features ...")
    t0 = time.time()
    feats = book_features(open_books)
    feats = add_slug_metadata(feats, asset)
    print(f"      {len(feats)} unique slugs in {time.time()-t0:.1f}s")

    # Filter to canonical resolution window (avoid pre-Apr22 slugs)
    print(f"[3/4] Filtering to canonical resolution window ...")
    res = load_resolutions([asset.upper()])
    resolved_slugs = set(res["slug"].unique())
    before = len(feats)
    feats = feats[feats["slug"].isin(resolved_slugs)].copy()
    feats["resolved"] = True
    # Also tag outcome from canonical
    res_map = res.set_index("slug")["outcome"].to_dict()
    feats["outcome_truth"] = feats["slug"].map(res_map)
    print(f"      {before} → {len(feats)} slugs after canonical filter")

    print(f"[4/4] Adding binance leading features ...")
    t0 = time.time()
    feats = add_binance_features(feats, asset)
    print(f"      done in {time.time()-t0:.1f}s")

    # Final column order
    cols_keep = [
        "slug", "asset", "tf", "slot_start_s", "ws_s", "fire_s",
        "hour_utc", "weekday", "min_in_hour", "slot_offset_min",
        "outcome_truth",
        # book
        "sum_bids", "sum_asks", "spread_up", "spread_dn",
        "mid_up", "mid_dn", "mid_diff",
        "depth_up", "depth_dn", "depth_tot", "depth_imb",
        "bid_price_0_up", "ask_price_0_up", "bid_size_0_up", "ask_size_0_up",
        "bid_price_0_down", "ask_price_0_down", "bid_size_0_down", "ask_size_0_down",
        "open_book_us",
        # binance
        "binance_close_at_ws", "ret_60s", "ret_120s",
        "abs_ret_60s", "abs_ret_120s", "vol_5m", "vol_10m",
    ]
    cols_keep = [c for c in cols_keep if c in feats.columns]
    feats = feats[cols_keep]

    suffix = f"_{args.out_suffix}" if args.out_suffix else ""
    out = OUT_DIR / f"_per_slug_features_{asset}{suffix}.csv"
    feats.to_csv(out, index=False)
    print(f"\nWrote {out}")
    print(f"  rows: {len(feats)}")
    print(f"  cols: {len(cols_keep)}")
    print(f"\nFeature summary:")
    print(feats[["tf", "hour_utc", "vol_5m", "abs_ret_120s", "depth_imb"]].describe().round(4).to_string())
    print(f"\nTF counts:")
    print(feats["tf"].value_counts().to_string())


if __name__ == "__main__":
    main()
