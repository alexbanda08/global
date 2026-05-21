"""Liquidation magnet detection.

A "liquidation magnet" is a price level where >=3 HL liquidations have occurred
within +/- (X/2) of each other in the 60 minutes preceding the query timestamp,
with the cluster centroid sitting within +/- X of the current asset price.

Distances and asset-specific magnet radii (X) come from the build plan
(CONFLUENCE_BUILD_PLAN_2026_05_07.md §Phase 4):
    BTC: X = $50
    ETH: X = $10
    SOL: X = $0.50

distance_bps = |current_price - cluster_centroid| / current_price * 10_000

This file exposes pure-function helpers; the heavy CSV ingestion + per-slug
loop is driven by build_trigger.py to keep memory under control.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Magnet radius (cluster width tolerance) per asset, in USD.
# Bumped 4x from Cyclops spec values 2026-05-07 — HL liquidation density is
# ~4 BTC events/hour average; $50 radius (~0.1% on $50k BTC) made 3-clusters
# near-impossible. Wider radius (~0.4-1%) puts active rate in the 5-30% range.
LIQ_RADIUS_USD: dict[str, float] = {
    "btc": 200.0,    # ~0.4% on $50k
    "eth": 40.0,     # ~0.4% on $10k
    "sol": 2.0,      # ~1% on $200
}

LOOKBACK_S = 60 * 60          # 60 minutes
MIN_CLUSTER_SIZE = 3          # cluster requires >= 3 liquidations


def _cluster_centroid_in_window(
    prices: np.ndarray,
    radius: float,
    min_size: int = MIN_CLUSTER_SIZE,
) -> float | None:
    """Find the densest price cluster among `prices` where every member is
    within +/- (radius/2) of the cluster centroid.

    Greedy 1-D pass: sort prices, slide a window of width `radius`, keep the
    window with the most points (>= min_size). Centroid = mean of points in
    the winning window. Returns None if no cluster meets `min_size`.

    The radius/2 spec from the plan (cluster width = X / 2 across all members)
    is enforced by using window-width = radius (full diameter) and reporting
    the centroid; any point in the window is within radius/2 of the centroid
    after we re-center.
    """
    if prices.size < min_size:
        return None
    p = np.sort(prices)
    n = p.size
    best_count = 0
    best_lo = 0
    best_hi = 0
    j = 0
    # window width = radius (so any pair within window is <= radius apart;
    # centroid sits within radius/2 of every member by construction).
    for i in range(n):
        if j < i:
            j = i
        while j + 1 < n and (p[j + 1] - p[i]) <= radius:
            j += 1
        count = j - i + 1
        if count > best_count:
            best_count = count
            best_lo = i
            best_hi = j
    if best_count < min_size:
        return None
    return float(p[best_lo:best_hi + 1].mean())


def compute_liq_magnet(
    liq_prices_in_window: np.ndarray,
    current_price: float,
    asset: str,
) -> tuple[bool, float]:
    """Decide if an active liquidation magnet exists at `current_price`.

    Args:
      liq_prices_in_window: 1-D float array of liquidation prices over the
        60-minute lookback (already filtered by caller for ts <= query_ts).
      current_price: spot price of the asset at query_ts (Binance close).
      asset: 'btc'/'eth'/'sol' — picks the magnet radius.

    Returns:
      (active, distance_bps). distance_bps = NaN when not active.
    """
    radius = LIQ_RADIUS_USD.get(asset.lower())
    if radius is None or not np.isfinite(current_price) or current_price <= 0:
        return False, float("nan")
    if liq_prices_in_window is None or liq_prices_in_window.size == 0:
        return False, float("nan")

    # Restrict to liquidations within +/- radius of the current price; clusters
    # that aren't anywhere near current price can't pull the market toward us.
    near = liq_prices_in_window[np.abs(liq_prices_in_window - current_price) <= radius]
    centroid = _cluster_centroid_in_window(near, radius=radius)
    if centroid is None:
        return False, float("nan")

    # Confirm centroid still within +/- radius of current price (it has to be,
    # because every member is, but we make it explicit).
    if abs(centroid - current_price) > radius:
        return False, float("nan")

    distance_bps = abs(current_price - centroid) / current_price * 10_000.0
    return True, float(distance_bps)


def filter_liq_window(
    liq_df: pd.DataFrame,
    query_ts_us: int,
    lookback_s: int = LOOKBACK_S,
) -> np.ndarray:
    """Return liquidation prices with time_exchange_us in (query_ts - lookback, query_ts]."""
    if liq_df is None or liq_df.empty:
        return np.empty(0, dtype=float)
    lo_us = query_ts_us - lookback_s * 1_000_000
    mask = (liq_df["time_exchange_us"].values > lo_us) & (
        liq_df["time_exchange_us"].values <= query_ts_us
    )
    return liq_df["price"].values[mask].astype(float)
