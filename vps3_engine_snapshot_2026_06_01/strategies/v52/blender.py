"""V52 portfolio blender — 60/10/10/10/10 outer + 60/40 inner + inv-vol P3 (Phase 8.1 Task 10).

Per V52 spec §7 tree:
  V52_CHAMPION (total HL capital)
  ├── 60% V41 CHAMPION
  │   ├── 60% P3 (inv-vol, 500-bar rolling, daily recompute)
  │   │   ├── CCI_ETH_P3, STF_AVAX_P3, STF_SOL_P3
  │   └── 40% P5 (equal 1/3 each)
  │       ├── CCI_ETH_P5, LATBB_AVAX_P5, STF_SOL_P5
  ├── 10% MFI_SOL
  ├── 10% VP_LINK
  ├── 10% SVD_AVAX
  └── 10% MFI_ETH

10 stream-distinct (CCI_ETH_P3 + CCI_ETH_P5 share signal but are independent
positions; same for STF_SOL).

Edge cases:
  - σ=0 in P3 → equal-weight fallback within P3 + CRITICAL log (RESEARCH Insight f).
  - Missing stream → re-normalize survivors (per spec §7).
  - Single active stream in P3 → 100% weight to it.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# Outer weights (sum = 1.0)
OUTER_V41 = 0.60
OUTER_DIVERSIFIERS = 0.40  # split into 4 × 0.10
DIVERSIFIER_WEIGHT = 0.10

# Inner V41 split
INNER_P3 = 0.60
INNER_P5 = 0.40

# Stream membership
P3_STREAMS = ("CCI_ETH_P3", "STF_AVAX_P3", "STF_SOL_P3")
P5_STREAMS = ("CCI_ETH_P5", "LATBB_AVAX_P5", "STF_SOL_P5")
DIVERSIFIER_STREAMS = ("MFI_SOL", "VP_LINK", "SVD_AVAX", "MFI_ETH")


def compute_inv_vol_weights(
    returns_by_stream: dict[str, np.ndarray],
    window: int = 500,
) -> dict[str, float]:
    """Inverse-volatility weights, normalized to sum 1.0 over input streams.

    σ=0 fallback (RESEARCH Insight f): if any stream has zero stdev (no variance
    in last `window` bars), CRITICAL-log and return equal weights for ALL
    streams — robust to rare data hiccups; never NaN-propagates.
    """
    stream_ids = list(returns_by_stream.keys())
    if not stream_ids:
        return {}

    stdevs: dict[str, float] = {}
    for sid, rets in returns_by_stream.items():
        arr = np.asarray(rets, dtype=float)
        if len(arr) < 2:
            stdevs[sid] = 0.0
            continue
        # Use last `window` rows (or all if less)
        tail = arr[-window:] if len(arr) > window else arr
        sd = float(np.std(tail, ddof=1)) if len(tail) > 1 else 0.0
        stdevs[sid] = sd

    if any(sd <= 0.0 or not np.isfinite(sd) for sd in stdevs.values()):
        logger.critical(
            "v52.blender.zero_sigma_fallback",
            extra={
                "event": "v52.blender.zero_sigma_fallback",
                "stdevs": stdevs,
                "fallback": "equal_weight_all_streams",
            },
        )
        n = len(stream_ids)
        return {sid: 1.0 / n for sid in stream_ids}

    inv = {sid: 1.0 / sd for sid, sd in stdevs.items()}
    total = sum(inv.values())
    if total <= 0 or not np.isfinite(total):
        n = len(stream_ids)
        return {sid: 1.0 / n for sid in stream_ids}
    return {sid: w / total for sid, w in inv.items()}


def compute_stream_targets(
    portfolio_equity: float,
    p3_returns: dict[str, np.ndarray] | None = None,
    active_streams: set[str] | None = None,
    window: int = 500,
) -> dict[str, float]:
    """Compute per-stream target notional for daily rebalance.

    Algorithm:
      1. Compute P3 inv-vol weights (subset to active P3 streams).
      2. P5 = equal 1/N over active P5 streams.
      3. Diversifiers = equal 1/M × DIVERSIFIER_WEIGHT each.
      4. Outer split: 60% V41 (60% P3 + 40% P5) + 4 × 10% diversifiers.
      5. Re-normalize per spec §7 if any stream is missing/inactive.

    Returns dict[stream_id, target_notional]. Sum == portfolio_equity ± 1e-9
    (subject to inactive-survivor re-normalization).
    """
    if active_streams is None:
        active_streams = set(P3_STREAMS) | set(P5_STREAMS) | set(DIVERSIFIER_STREAMS)
    p3_returns = p3_returns or {}

    weights: dict[str, float] = {}

    # ----- V41 inner P3 (inv-vol) -----
    active_p3 = [s for s in P3_STREAMS if s in active_streams]
    if active_p3:
        p3_input = {sid: p3_returns.get(sid, np.array([])) for sid in active_p3}
        # If any P3 stream has empty returns, inv_vol falls back to equal-weight
        p3_norm = compute_inv_vol_weights(p3_input, window=window)
        for sid, w in p3_norm.items():
            weights[sid] = OUTER_V41 * INNER_P3 * w

    # ----- V41 inner P5 (equal) -----
    active_p5 = [s for s in P5_STREAMS if s in active_streams]
    if active_p5:
        per = 1.0 / len(active_p5)
        for sid in active_p5:
            weights[sid] = OUTER_V41 * INNER_P5 * per

    # ----- Diversifiers (each at 10% individually) -----
    active_div = [s for s in DIVERSIFIER_STREAMS if s in active_streams]
    for sid in active_div:
        weights[sid] = DIVERSIFIER_WEIGHT

    # ----- Re-normalize survivors so sum == 1.0 -----
    total = sum(weights.values())
    if total <= 0 or not np.isfinite(total):
        # No active streams at all
        return {}
    weights = {sid: w / total for sid, w in weights.items()}

    # ----- Sanity: weights sum to 1.0 -----
    assert abs(sum(weights.values()) - 1.0) < 1e-9, (
        f"V52 weights drift: sum={sum(weights.values())}"
    )
    for sid, w in weights.items():
        if not np.isfinite(w):
            raise AssertionError(f"V52 weight non-finite: {sid}={w}")

    return {sid: w * portfolio_equity for sid, w in weights.items()}


__all__ = [
    "DIVERSIFIER_STREAMS",
    "DIVERSIFIER_WEIGHT",
    "INNER_P3",
    "INNER_P5",
    "OUTER_DIVERSIFIERS",
    "OUTER_V41",
    "P3_STREAMS",
    "P5_STREAMS",
    "compute_inv_vol_weights",
    "compute_stream_targets",
]
