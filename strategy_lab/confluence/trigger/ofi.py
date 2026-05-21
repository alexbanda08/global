"""Order Flow Imbalance (OFI) over the 30s ending at query_ts.

Computed on the held-outcome trade stream:

    raw_ofi = sum(size if side == 'buy' else -size, for trades in [ws+90, ws+120])
    abs_vol = sum(size,                                     for trades in [ws+90, ws+120])
    ofi_30s = raw_ofi / (abs_vol + epsilon)        # in [-1, +1]

A normalized output keeps the magnitude comparable across slugs with very
different volume regimes — `trigger_active` checks |ofi_30s| > 0.30 with a
sign aligned with the held side.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OFI_WINDOW_S = 30
OFI_EPSILON = 1e-9


def compute_ofi_30s(
    trades_df: pd.DataFrame,
    query_ts_us: int,
    window_s: int = OFI_WINDOW_S,
) -> float:
    """Normalized OFI over the last `window_s` seconds ending at query_ts.

    Args:
      trades_df: pre-filtered to slug + held outcome side. Must have columns
        `timestamp_us` (int), `size` (float), `side` ('buy'/'sell').
      query_ts_us: feature timestamp in microseconds.
      window_s: lookback in seconds (default 30).

    Returns:
      ofi normalized to [-1, +1]. 0.0 when window has no trades.
    """
    if trades_df is None or trades_df.empty:
        return 0.0
    lo_us = query_ts_us - window_s * 1_000_000
    ts = trades_df["timestamp_us"].values
    mask = (ts > lo_us) & (ts <= query_ts_us)
    if not mask.any():
        return 0.0
    sizes = trades_df["size"].values[mask].astype(float)
    sides = trades_df["side"].values[mask]
    signed = np.where(sides == "buy", sizes, -sizes)
    raw = float(signed.sum())
    abs_vol = float(np.abs(sizes).sum())
    if abs_vol <= 0:
        return 0.0
    val = raw / (abs_vol + OFI_EPSILON)
    if val > 1.0:
        val = 1.0
    elif val < -1.0:
        val = -1.0
    return val
