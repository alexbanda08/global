"""raw_orderbook_l25 — canonical loader for the 2026-05-06 raw VPS2 pull.

Reads gzipped CSVs at data/v4/refresh_2026_05_06/{asset}_orderbook_raw_L25.csv.gz
and exposes a uniform asof-lookup API matching the existing book_walk.book_walk_fill
signature, so existing engines can drop in unchanged with LEVELS=25.

Data file format (109 columns):
    timestamp_us, local_timestamp_us, exchange, market_id, slug, asset_id, outcome,
    bid_price_0..bid_price_24, bid_size_0..bid_size_24,
    ask_price_0..ask_price_24, ask_size_0..ask_size_24,
    outcome_id, source

Typical sizes (refresh 2026-05-06):
    BTC: 28.06M rows, 2.5 GB gz
    ETH: 5.32M rows, 520 MB gz
    SOL: 2.32M rows, 226 MB gz

Usage (typical):
    from strategy_lab.loaders.raw_orderbook_l25 import (
        load_orderbook_l25_raw, load_trades_raw, book_at,
    )

    # 1) Load filtered to specific slugs (recommended)
    ob = load_orderbook_l25_raw("btc", slugs={"btc-updown-5m-1777824000", ...})

    # 2) Asof lookup → drop into book_walk_fill unchanged
    asks_p, asks_s = book_at(ob, slug, outcome_id=0, ts_us=signal_ts_us, side="ask")
    vwap, shares, usd, levels, underfilled = book_walk_fill(asks_p, asks_s, 25.0, "buy")

Memory:
    Full BTC orderbook in memory ~6 GB (pandas overhead ~2x raw).
    Always pass slugs= or chunk-stream when working on a subset.
"""
from __future__ import annotations

import gzip
from bisect import bisect_right
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

LEVELS = 25  # ← bumped from L10

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06"

ASSETS = ("btc", "eth", "sol")

_BID_PRICE_COLS = [f"bid_price_{i}" for i in range(LEVELS)]
_BID_SIZE_COLS = [f"bid_size_{i}" for i in range(LEVELS)]
_ASK_PRICE_COLS = [f"ask_price_{i}" for i in range(LEVELS)]
_ASK_SIZE_COLS = [f"ask_size_{i}" for i in range(LEVELS)]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def orderbook_path(asset: str) -> Path:
    asset = asset.lower()
    if asset not in ASSETS:
        raise ValueError(f"asset must be one of {ASSETS}, got {asset!r}")
    return DATA_DIR / f"{asset}_orderbook_raw_L25.csv.gz"


def trades_path(asset: str) -> Path:
    asset = asset.lower()
    if asset not in ASSETS:
        raise ValueError(f"asset must be one of {ASSETS}, got {asset!r}")
    return DATA_DIR / f"{asset}_trades_raw.csv.gz"


def _orderbook_dtypes() -> dict:
    """Explicit dtypes for the 109-col L25 orderbook CSV.
    Reduces memory ~3x vs default object inference and avoids OOM on chunk reads.
    """
    d: dict = {
        "timestamp_us": "int64",
        "local_timestamp_us": "Int64",
        "exchange": "category",
        "market_id": "string",
        "slug": "category",
        "asset_id": "string",
        "outcome": "category",
        "outcome_id": "int8",
        "source": "category",
    }
    for i in range(LEVELS):
        d[f"bid_price_{i}"] = "float32"
        d[f"bid_size_{i}"] = "float32"
        d[f"ask_price_{i}"] = "float32"
        d[f"ask_size_{i}"] = "float32"
    return d


def _trades_dtypes() -> dict:
    return {
        "timestamp_us": "int64",
        "local_timestamp_us": "Int64",
        "exchange": "category",
        "market_id": "string",
        "slug": "category",
        "asset_id": "string",
        "outcome": "category",
        "price": "float32",
        "size": "float32",
        "side": "category",
        "trade_id": "string",
        "origin_asset_id": "string",
        "outcome_id": "int8",
        "source": "category",
    }


def parquet_path(asset: str) -> Path:
    """Path to pre-built parquet cache (created by prebuild_l25_parquet.py)."""
    asset = asset.lower()
    return DATA_DIR / "cache" / f"{asset}_orderbook_L25.parquet"


def trades_parquet_path(asset: str) -> Path:
    asset = asset.lower()
    return DATA_DIR / "cache" / f"{asset}_trades.parquet"


def load_orderbook_l25_raw(
    asset: str,
    slugs: Iterable[str] | None = None,
    chunksize: int = 100_000,
    sort: bool = True,
    prefer_parquet: bool = True,
) -> pd.DataFrame:
    """Load L25 orderbook for one asset, optionally filtered to slug list.

    Loads from pre-built parquet cache if it exists (FAST: row-group filter,
    seconds). Falls back to streaming the gz CSV (SLOW: full scan, minutes).

    Args:
        asset: 'btc' | 'eth' | 'sol'
        slugs: optional set of slugs to keep — STRONGLY recommended.
        chunksize: rows per chunk for csv-gz fallback (default 100k).
        sort: if True, returns DataFrame sorted by
              (slug, outcome_id, timestamp_us) — required for asof lookups.
        prefer_parquet: use parquet cache if available (default True).
    """
    pq_path = parquet_path(asset)
    if prefer_parquet and pq_path.exists():
        return _load_orderbook_from_parquet(pq_path, slugs=slugs, sort=sort)

    # Fallback: stream the gz CSV
    path = orderbook_path(asset)
    if not path.exists():
        raise FileNotFoundError(f"orderbook raw L25 not found: {path}")

    slug_set = set(slugs) if slugs is not None else None
    chunks: list[pd.DataFrame] = []
    dtypes = _orderbook_dtypes()
    reader = pd.read_csv(path, chunksize=chunksize, dtype=dtypes, engine="c")
    for chunk in reader:
        if slug_set is not None:
            chunk = chunk[chunk["slug"].isin(slug_set)]
        if len(chunk):
            chunks.append(chunk)

    if not chunks:
        return pd.read_csv(path, nrows=0, dtype=dtypes)

    df = pd.concat(chunks, ignore_index=True)
    if sort:
        df = df.sort_values(["slug", "outcome_id", "timestamp_us"], kind="mergesort")
        df.reset_index(drop=True, inplace=True)
    return df


def _load_orderbook_from_parquet(
    pq_path: Path,
    slugs: Iterable[str] | None,
    sort: bool,
) -> pd.DataFrame:
    """Fast parquet load with optional slug-list filter."""
    import pyarrow.parquet as pq

    if slugs is not None:
        slug_list = list(slugs)
        # pyarrow accepts list of slugs in `filters` arg with 'in' operator
        filters = [("slug", "in", slug_list)]
        table = pq.read_table(pq_path, filters=filters)
    else:
        table = pq.read_table(pq_path)
    df = table.to_pandas()
    if sort:
        df = df.sort_values(["slug", "outcome_id", "timestamp_us"], kind="mergesort")
        df.reset_index(drop=True, inplace=True)
    return df


def load_trades_raw(
    asset: str,
    slugs: Iterable[str] | None = None,
    chunksize: int = 200_000,
    sort: bool = True,
) -> pd.DataFrame:
    """Stream gzipped trades_v2 raw CSV → DataFrame (filtered).

    Same args/contract as load_orderbook_l25_raw. Schema (14 cols):
        timestamp_us, local_timestamp_us, exchange, market_id, slug, asset_id,
        outcome, price, size, side, trade_id, origin_asset_id, outcome_id, source

    side ∈ {'buy', 'sell'} for CVD / aggressor computations.
    """
    path = trades_path(asset)
    if not path.exists():
        raise FileNotFoundError(f"trades raw not found: {path}")

    slug_set = set(slugs) if slugs is not None else None
    dtypes = _trades_dtypes()
    chunks: list[pd.DataFrame] = []
    reader = pd.read_csv(path, chunksize=chunksize, dtype=dtypes, engine="c")
    for chunk in reader:
        if slug_set is not None:
            chunk = chunk[chunk["slug"].isin(slug_set)]
        if len(chunk):
            chunks.append(chunk)

    if not chunks:
        return pd.read_csv(path, nrows=0, dtype=dtypes)

    df = pd.concat(chunks, ignore_index=True)
    if sort:
        df = df.sort_values(["slug", "outcome_id", "timestamp_us"], kind="mergesort")
        df.reset_index(drop=True, inplace=True)
    return df


# ---------------------------------------------------------------------------
# Indexed lookup (asof)
# ---------------------------------------------------------------------------

class OrderbookIndex:
    """Fast asof lookup over a pre-sorted L25 DataFrame.

    Indexes (slug, outcome_id) → (timestamps[], row_indices[]).
    Lookup is O(log n) per call (binary search).

    Usage:
        ob_df = load_orderbook_l25_raw('btc', slugs={...})
        idx = OrderbookIndex(ob_df)
        prices, sizes = idx.book_at(slug, outcome_id, ts_us, side='ask')
    """

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        # Group: per (slug, outcome_id) -> sorted np.array of ts + row indices
        self._groups: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
        for (slug, oid), g in df.groupby(["slug", "outcome_id"], sort=False, observed=True):
            ts = g["timestamp_us"].to_numpy()
            ridx = g.index.to_numpy()
            self._groups[(slug, int(oid))] = (ts, ridx)

    # --- Core asof lookup ------------------------------------------------

    def asof_row(self, slug: str, outcome_id: int, ts_us: int) -> int | None:
        """Return DataFrame row index for the latest snap with timestamp <= ts_us.
        Returns None if no snapshot exists at or before ts_us for this key."""
        key = (slug, int(outcome_id))
        g = self._groups.get(key)
        if g is None:
            return None
        ts, ridx = g
        # bisect_right returns insertion point — last index with ts <= ts_us is pos-1
        pos = np.searchsorted(ts, int(ts_us), side="right")
        if pos == 0:
            return None
        return int(ridx[pos - 1])

    def book_at(
        self,
        slug: str,
        outcome_id: int,
        ts_us: int,
        side: str = "ask",
    ) -> tuple[list[float], list[float]] | tuple[None, None]:
        """Return (prices, sizes) at or before ts_us for the requested side.

        Drop-in compatible with strategy_lab.book_walk.book_walk_fill:
            prices, sizes = idx.book_at(slug, oid, ts, side='ask')
            vwap, shares, usd, levels, under = book_walk_fill(prices, sizes, 25.0, 'buy')

        Args:
            side: 'ask' or 'bid'. ASK levels are ascending price (best ask first);
                  BID levels are descending price (best bid first).

        Returns:
            (prices_25, sizes_25) — 25-element lists. NaN entries for empty levels.
            (None, None) if no snapshot found at/before ts_us.
        """
        if side not in ("ask", "bid"):
            raise ValueError(f"side must be 'ask' or 'bid', got {side!r}")
        ridx = self.asof_row(slug, outcome_id, ts_us)
        if ridx is None:
            return None, None
        row = self._df.iloc[ridx]
        if side == "ask":
            prices = row[_ASK_PRICE_COLS].to_list()
            sizes = row[_ASK_SIZE_COLS].to_list()
        else:
            prices = row[_BID_PRICE_COLS].to_list()
            sizes = row[_BID_SIZE_COLS].to_list()
        return prices, sizes

    def book_at_with_ts(
        self,
        slug: str,
        outcome_id: int,
        ts_us: int,
        side: str = "ask",
    ) -> tuple[list[float] | None, list[float] | None, int | None]:
        """Same as book_at but also returns the actual snapshot ts_us used.

        Useful for telemetry — staleness = query_ts_us - snap_ts_us.
        """
        ridx = self.asof_row(slug, outcome_id, ts_us)
        if ridx is None:
            return None, None, None
        row = self._df.iloc[ridx]
        snap_ts = int(row["timestamp_us"])
        if side == "ask":
            return row[_ASK_PRICE_COLS].to_list(), row[_ASK_SIZE_COLS].to_list(), snap_ts
        return row[_BID_PRICE_COLS].to_list(), row[_BID_SIZE_COLS].to_list(), snap_ts

    # --- Range scans (for liquidity envelope checks) ---------------------

    def snaps_between(
        self,
        slug: str,
        outcome_id: int,
        from_ts_us: int,
        to_ts_us: int,
    ) -> pd.DataFrame:
        """Return all snapshots for (slug, outcome_id) within [from, to] inclusive.

        Useful to scan the entire intra-window book evolution — e.g. find the
        first ts where the opposite-side ask book becomes non-empty after a
        rev_bp trigger.
        """
        key = (slug, int(outcome_id))
        g = self._groups.get(key)
        if g is None:
            return self._df.iloc[0:0]
        ts, ridx = g
        lo = int(np.searchsorted(ts, int(from_ts_us), side="left"))
        hi = int(np.searchsorted(ts, int(to_ts_us), side="right"))
        if lo >= hi:
            return self._df.iloc[0:0]
        return self._df.iloc[ridx[lo:hi]]

    # --- Diagnostics ------------------------------------------------------

    def slugs(self) -> set[str]:
        return {slug for slug, _ in self._groups}

    def coverage(self, slug: str, outcome_id: int) -> dict | None:
        """Return summary stats about coverage of one (slug, outcome_id):
        n_snaps, ts_min, ts_max, span_seconds."""
        g = self._groups.get((slug, int(outcome_id)))
        if g is None:
            return None
        ts, _ = g
        if len(ts) == 0:
            return None
        return {
            "n_snaps": int(len(ts)),
            "ts_min": int(ts[0]),
            "ts_max": int(ts[-1]),
            "span_seconds": float((ts[-1] - ts[0]) / 1e6),
        }


# ---------------------------------------------------------------------------
# Convenience: liquidity feasibility check
# ---------------------------------------------------------------------------

def has_liquidity(
    prices: list[float] | None,
    sizes: list[float] | None,
    notional_usd: float,
    side: str,
    fill_ratio: float = 0.95,
) -> bool:
    """Quick check: would book_walk_fill achieve at least fill_ratio of the target?

    Doesn't run the full simulator — just sums up the available USD across all
    25 levels (for buy) or shares × prices (for sell). Useful for HEDGE-feasible
    / SELL-feasible filtering before invoking the full book-walk.

    Returns True iff the available USD on this side is >= notional * fill_ratio.
    """
    if prices is None or sizes is None:
        return False
    avail_usd = 0.0
    for p, s in zip(prices, sizes):
        if p is None or s is None:
            continue
        try:
            p = float(p)
            s = float(s)
        except (TypeError, ValueError):
            continue
        if not (np.isfinite(p) and np.isfinite(s)) or p <= 0 or s <= 0:
            continue
        avail_usd += p * s
    return avail_usd >= float(notional_usd) * float(fill_ratio)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def _smoke(asset: str = "sol", n_slugs: int = 3) -> None:
    """Smoke test. Loads first n slugs of an asset and prints coverage."""
    print(f"=== smoke: {asset} ===")
    # Load tiny slug list first by streaming the head and grabbing distinct slugs.
    with gzip.open(orderbook_path(asset), "rt") as fh:
        header = fh.readline().rstrip("\n").split(",")
        slug_idx = header.index("slug")
        seen: set[str] = set()
        for line in fh:
            parts = line.split(",", slug_idx + 2)
            slug = parts[slug_idx]
            seen.add(slug)
            if len(seen) >= n_slugs:
                break
    print(f"sample slugs: {sorted(seen)}")

    ob = load_orderbook_l25_raw(asset, slugs=seen)
    print(f"loaded {len(ob):,} rows for {len(seen)} slugs")

    idx = OrderbookIndex(ob)
    for s in seen:
        for oid in (0, 1):
            cov = idx.coverage(s, oid)
            if cov is None:
                continue
            print(f"  {s} oid={oid}: {cov}")
            mid_ts = (cov["ts_min"] + cov["ts_max"]) // 2
            asks_p, asks_s = idx.book_at(s, oid, mid_ts, side="ask")
            print(f"    ask top5 px: {asks_p[:5]}")
            print(f"    ask top5 sz: {asks_s[:5]}")
            print(f"    has_liquidity($25): {has_liquidity(asks_p, asks_s, 25.0, 'ask')}")


if __name__ == "__main__":
    import sys
    _smoke(sys.argv[1] if len(sys.argv) > 1 else "sol")
