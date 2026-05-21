"""Q3: short-timeframe orderbook + trade momentum (Polymarket-side).

Composite of three normalized features on the *held* outcome side:

  imb_l5        = (sum bid_size[0..4] - sum ask_size[0..4]) / total          (latest snapshot)
  cvd_1m        = Σ size · sign(buy=+1, sell=-1)   / MOMENTUM_CVD_CAP_USD    (last 60s)
  aggressor_30s = (buy_size_30s - sell_size_30s)  / total_30s                (last 30s)

  score = W_IMB · imb_l5  +  W_CVD · cvd_1m  +  W_AGG · aggressor_30s

Each feature is bounded in [-1, +1] (clipped if needed) so the composite
stays in [-1, +1]. The vote uses MOMENTUM_MIN_STRENGTH from conventions.

The function is pure. Caller supplies pre-sliced OB snapshots and trades
for the held side over the relevant window ending at fire_us.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from ..conventions import (
    MOMENTUM_AGGRESSOR_WINDOW_S,
    MOMENTUM_CVD_CAP_USD,
    MOMENTUM_MIN_STRENGTH,
    MOMENTUM_W_AGGRESSOR_30S,
    MOMENTUM_W_CVD_1M,
    MOMENTUM_W_IMBALANCE_L5,
    MOMENTUM_WINDOW_S,
)

# OB snapshot bundle, matching load_orderbook_l25_streaming output sliced per side:
#   ts_us[N], ask_p[N, 25], ask_sz[N, 25], bid_p[N, 25], bid_sz[N, 25]
ObBundle = Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def _imbalance_l5(ob: ObBundle, fire_us: int) -> float:
    """Top-5-level imbalance on the most recent snapshot at-or-before fire_us."""
    ts_us, _ap, asz, _bp, bsz = ob
    if ts_us.size == 0:
        return 0.0
    idx = int(np.searchsorted(ts_us, int(fire_us), side="right")) - 1
    if idx < 0:
        return 0.0
    bid_sum = float(np.nansum(bsz[idx, :5]))
    ask_sum = float(np.nansum(asz[idx, :5]))
    total = bid_sum + ask_sum
    if total <= 0:
        return 0.0
    return _clip((bid_sum - ask_sum) / total)


def _cvd_window(
    trades_ts_us: np.ndarray,
    trades_size_usd: np.ndarray,
    trades_side: np.ndarray,
    fire_us: int,
    window_s: int,
    cap_usd: float,
) -> Tuple[float, float, float]:
    """Return (cvd_usd, buy_usd, sell_usd) over the window ending at fire_us.

    `side` array: +1 = buy/taker-up, -1 = sell/taker-down, 0 = unknown.
    """
    if trades_ts_us.size == 0:
        return 0.0, 0.0, 0.0
    lo_us = int(fire_us) - window_s * 1_000_000
    mask = (trades_ts_us > lo_us) & (trades_ts_us <= int(fire_us))
    if not mask.any():
        return 0.0, 0.0, 0.0
    s = trades_size_usd[mask]
    d = trades_side[mask]
    buy_usd = float(s[d > 0].sum())
    sell_usd = float(s[d < 0].sum())
    cvd_usd = buy_usd - sell_usd
    return cvd_usd, buy_usd, sell_usd


def compute_momentum_score(
    ob: ObBundle,
    trades_ts_us: Optional[np.ndarray],
    trades_size_usd: Optional[np.ndarray],
    trades_side: Optional[np.ndarray],
    fire_us: int,
) -> float:
    """Composite momentum score in [-1, +1] on the held side at fire_us.

    If trades arrays are None (or empty), the trade-based features fall back
    to 0 — the score then reduces to the L5 imbalance term (× its weight),
    which is still informative.
    """
    imb = _imbalance_l5(ob, fire_us)

    if trades_ts_us is None or trades_size_usd is None or trades_side is None:
        cvd_norm = 0.0
        agg = 0.0
    else:
        cvd_usd, _b1, _s1 = _cvd_window(
            trades_ts_us, trades_size_usd, trades_side,
            fire_us, MOMENTUM_WINDOW_S, MOMENTUM_CVD_CAP_USD,
        )
        cvd_norm = _clip(cvd_usd / MOMENTUM_CVD_CAP_USD)

        _cvd2, b30, s30 = _cvd_window(
            trades_ts_us, trades_size_usd, trades_side,
            fire_us, MOMENTUM_AGGRESSOR_WINDOW_S, MOMENTUM_CVD_CAP_USD,
        )
        total_30 = b30 + s30
        agg = _clip((b30 - s30) / total_30) if total_30 > 0 else 0.0

    score = (
        MOMENTUM_W_IMBALANCE_L5 * imb
        + MOMENTUM_W_CVD_1M * cvd_norm
        + MOMENTUM_W_AGGRESSOR_30S * agg
    )
    return _clip(score)


def momentum_vote(score: float, threshold: float = MOMENTUM_MIN_STRENGTH) -> int:
    """Collapse momentum score to a {-1, 0, +1} axis vote."""
    if score >= threshold:
        return 1
    if score <= -threshold:
        return -1
    return 0
