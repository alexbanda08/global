"""OB manipulation guard — DEFERRED for P3.

Cyclops Day 2:
    "Track OB score volatility over a 5s window. If score swings too hard,
     likely a liquidity grab spike — suppress entry."

This guard needs full L25 streaming snapshots for the slug over the 5s
window preceding fire_us. Our P2/P3/P4 runner reads only the single t+120
tier1 snapshot (lightweight). Wiring this guard requires:

  1. `load_orderbook_l25_streaming` with `slugs=batch` (multi-GB BTC parquet)
  2. Per-slug iteration over OB snapshots, computing imbalance score each
  3. Running max-min span over the 5s window

That's a substantial runner redesign + 5-10× memory usage. We are leaving
the function signature here so the runner can be extended later without
breaking the filter contract, but the implementation is a no-op pass.

When you actually wire this:
  - In runner.py, batch slugs (e.g. 200 at a time)
  - Call `load_orderbook_l25_streaming("btc", slugs=batch)`
  - Pass the relevant snapshots into this function for each fire
"""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from ..conventions import OB_VOLATILITY_THRESHOLD


def _imbalance_score(ap_l5_sizes: np.ndarray, bp_l5_sizes: np.ndarray) -> float:
    """Top-5 imbalance score in [-1, +1]. Same shape as axes/momentum.py."""
    bid_sum = float(np.nansum(bp_l5_sizes))
    ask_sum = float(np.nansum(ap_l5_sizes))
    total = bid_sum + ask_sum
    if total <= 0:
        return 0.0
    return max(-1.0, min(1.0, (bid_sum - ask_sum) / total))


def is_ob_manipulated(
    ob_snapshots_5s: Sequence[Tuple[np.ndarray, np.ndarray]] | None,
    threshold: float = OB_VOLATILITY_THRESHOLD,
) -> Tuple[bool, str]:
    """Return (should_skip, reason).

    `ob_snapshots_5s` is a list of (bid_l5_sizes, ask_l5_sizes) tuples.
    When None or shorter than 2, returns (False, 'insufficient_data') — the
    common case in our current runner since we don't load streaming OB yet.
    """
    if ob_snapshots_5s is None or len(ob_snapshots_5s) < 2:
        return False, "insufficient_data"
    scores = [_imbalance_score(asz, bsz) for bsz, asz in ob_snapshots_5s]
    span = max(scores) - min(scores)
    if span > threshold:
        return True, f"ob_manipulated_span{span:.3f}"
    return False, "ok"
