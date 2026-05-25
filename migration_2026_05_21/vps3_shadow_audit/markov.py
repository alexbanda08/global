"""Markov-style regime labeler (Phase 34 — m5va gate companion).

Per ``strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md``
§2.3: classify the current bar window into Bear/Sideways/Bull tertile based
on its log return vs the prior 14-day distribution of same-window-length log
returns.

The classifier is "Markov-flavored" in name only — it's a stateless tertile
classifier on rolling returns. No transition matrix, no Viterbi, no HMM.
The label moniker stays for downstream-audit / dashboard-display consistency
with the spec.

CLAUDE.md inv #4: pure function — no IO, no time.time(), no mutation.
Caller passes the prepared arrays; we return -1/0/1/2.
"""
from __future__ import annotations

import math

import numpy as np

__all__ = ["label_regime_vol_adaptive"]


def label_regime_vol_adaptive(
    closes_window: np.ndarray,
    rolling_returns_14d: np.ndarray,
) -> int:
    """Return regime label for the current bar.

    Args:
        closes_window: ``length window_bars + 1`` chronological closes ending
            at the current bar close. Must be finite; closes_window[0] > 0.
        rolling_returns_14d: signed log returns over the prior 14 days at
            the SAME ``window_bars`` span. NaN entries are filtered before
            quantile compute.

    Returns:
        ``2`` (Bull) — current ret > 66th-percentile of prior 14d distribution
        ``1`` (Sideways) — current ret between 33rd + 66th percentiles
        ``0`` (Bear) — current ret < 33rd-percentile
        ``-1`` (warmup/unknown) — rolling_returns_14d has < 100 finite samples
            OR closes_window invalid (non-finite, non-positive anchor)

    Implementation note: ``np.quantile`` over ~4032 5MIN samples is < 5ms.
    Per-cell cache at the controller layer (spec §3.3) keeps Markov compute
    O(1) across HOLD/HEDGE/SELL clones of the same (sym, ws_s).
    """
    if len(rolling_returns_14d) < 100:
        return -1
    valid = rolling_returns_14d[np.isfinite(rolling_returns_14d)]
    if len(valid) < 100:
        return -1
    if len(closes_window) < 2:
        return -1
    first = float(closes_window[0])
    last = float(closes_window[-1])
    if not (math.isfinite(first) and math.isfinite(last) and first > 0):
        return -1
    ret = math.log(last / first)
    q33, q66 = np.quantile(valid, [1.0 / 3.0, 2.0 / 3.0])
    if ret < q33:
        return 0
    if ret > q66:
        return 2
    return 1
