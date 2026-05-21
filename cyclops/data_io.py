"""Thin wrappers over data/v4/canonical/load.py.

Only purpose: insulate cyclops/ from canonical path changes. If the canonical
API shifts, this file is the one place to edit.

All loaders return UTC-microsecond timestamps (`*_us` columns).
Outcomes are chainlink-derived. Signals come from binance-spot-ws.
See CLAUDE.md and data/v4/canonical/README.md for full conventions.
"""

from __future__ import annotations

import sys
from typing import Iterable

import numpy as np
import pandas as pd

from .conventions import CANONICAL

sys.path.insert(0, str(CANONICAL))

# Re-export canonical primitives. `# noqa: E402` — sys.path manipulation must
# happen before this import; that's the entire reason for this file.
from load import (  # noqa: E402
    load_resolutions,
    load_klines,
    load_klines_asof,
    load_chainlink_rtds,
    load_chainlink_asof,
    load_orderbook_l25_streaming,
    load_tier1_entries,
    load_trades,
    asof_strict,
    slug_to_ws_s,
    add_ws_s,
    ret_2m_at_ws,
)

__all__ = [
    "load_resolutions",
    "load_klines",
    "load_klines_asof",
    "load_chainlink_rtds",
    "load_chainlink_asof",
    "load_orderbook_l25_streaming",
    "load_tier1_entries",
    "load_trades",
    "asof_strict",
    "slug_to_ws_s",
    "add_ws_s",
    "ret_2m_at_ws",
    "load_btc_universe",
    "load_universe",
    "resample_bars",
    "load_resampled_kline_arrays",
    "load_signal_streams",
]


def resample_bars(klines_1m: pd.DataFrame, period_s: int) -> dict:
    """Resample a canonical 1MIN klines DataFrame to bars of `period_s` seconds.

    Returns a dict of numpy arrays:
      end_us, open, high, low, close, volume

    Causal — only emits buckets that have all `period_s // 60` underlying
    minutes. Partial buckets at the leading edge are dropped to avoid
    silently leaking the active bar into a backtest.
    """
    if klines_1m.empty:
        empty_i = np.array([], dtype="int64")
        empty_f = np.array([], dtype="float64")
        return {"end_us": empty_i, "open": empty_f, "high": empty_f,
                "low": empty_f, "close": empty_f, "volume": empty_f}
    if period_s % 60 != 0:
        raise ValueError("period_s must be a multiple of 60s (canonical bars are 1MIN)")
    bars_per_bucket = period_s // 60

    df = klines_1m[["time_period_start_us", "price_open", "price_high",
                    "price_low", "price_close", "volume_traded"]].copy()
    df["bucket"] = df["time_period_start_us"] // (period_s * 1_000_000)
    counts = df.groupby("bucket").size()
    full = counts[counts == bars_per_bucket].index
    df = df[df["bucket"].isin(full)]

    g = df.groupby("bucket", sort=True)
    bucket_start_us = g["time_period_start_us"].min()
    end_us = (bucket_start_us + period_s * 1_000_000).astype("int64").values
    return {
        "end_us": end_us,
        "open":   g["price_open"].first().values.astype("float64"),
        "high":   g["price_high"].max().values.astype("float64"),
        "low":    g["price_low"].min().values.astype("float64"),
        "close":  g["price_close"].last().values.astype("float64"),
        "volume": g["volume_traded"].sum().values.astype("float64"),
    }


def load_resampled_kline_arrays(asset: str, source: str = "binance-spot-ws") -> dict:
    """Load 1MIN canonical klines once, pre-resample to {"1m","5m","15m","1h"}."""
    one_min = load_klines(asset, source, "1MIN")
    return {
        "1m":  resample_bars(one_min, period_s=60),
        "5m":  resample_bars(one_min, period_s=300),
        "15m": resample_bars(one_min, period_s=900),
        "1h":  resample_bars(one_min, period_s=3600),
    }


def load_universe(asset: str, timeframe: str = "5m") -> pd.DataFrame:
    """Load the chainlink-resolved binary-market universe for one (asset, tf)
    pair, with ws_s already attached.

    Returned columns include: slug, asset, timeframe, outcome, ws_s, plus the
    standard canonical fields. Use ws_s + 120 as the fire timestamp.
    """
    res = load_resolutions(assets=[asset.upper()], timeframes=[timeframe])
    res = add_ws_s(res)
    return res


def load_btc_universe() -> pd.DataFrame:
    """Convenience: BTC 5m universe (the spec's Phase 1 target)."""
    return load_universe("BTC", "5m")


def load_signal_streams(
    asset: str,
    slugs: set,
    outcome: str = "Up",
    verbose: bool = True,
) -> tuple[dict, dict]:
    """Load streaming L25 OB + Polymarket trades for the given slugs, ONE side.

    Returns:
      ob_by_slug: dict[slug] -> (ts_us[N], ap[N,25], asz[N,25], bp[N,25], bsz[N,25])
      trades_by_slug: dict[slug] -> {ts_us, price, size, side} numpy arrays

    Memory: the L25 loader streams batches and 1Hz-subsamples internally;
    trades are loaded as one parquet then filtered. Filtering to a single
    outcome (default 'Up') keeps RAM bounded at ~ half the raw footprint.
    """
    slug_set = set(slugs)
    if verbose:
        print(f"[streams] loading L25 OB for {len(slug_set)} slugs ({outcome} side) ...")
    ob_raw = load_orderbook_l25_streaming(asset.lower(), slugs=slug_set)
    ob_by_slug = {sl: v for (sl, oc), v in ob_raw.items() if oc == outcome}
    del ob_raw
    if verbose:
        print(f"[streams]   got {len(ob_by_slug)} (slug, {outcome}) OB groups")
        print(f"[streams] loading trades parquet ...")

    tr = load_trades(asset.lower())
    if verbose:
        print(f"[streams]   raw trades n={len(tr)}; filtering to {outcome} + universe ...")
    tr = tr[(tr["outcome"] == outcome) & (tr["slug"].isin(slug_set))]
    cols = ["timestamp_us", "slug", "price", "size", "side"]
    tr = tr[cols].copy()
    tr["ts_us"] = tr["timestamp_us"].astype("int64")
    # Pre-convert side to signed flow per spec §4.5: buy=+1, sell=-1.
    tr["side_sign"] = np.where(tr["side"].values == "buy", 1, -1).astype("int8")

    trades_by_slug: dict = {}
    for sl, g in tr.groupby("slug", sort=False):
        g_sorted = g.sort_values("ts_us")
        trades_by_slug[sl] = {
            "ts_us": g_sorted["ts_us"].values.astype("int64"),
            "size": g_sorted["size"].values.astype("float64"),
            "side_sign": g_sorted["side_sign"].values.astype("int8"),
        }
    if verbose:
        print(f"[streams]   got {len(trades_by_slug)} slugs with trades")
    return ob_by_slug, trades_by_slug
