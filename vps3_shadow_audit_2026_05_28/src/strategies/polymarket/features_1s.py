"""Per-fire 1s-derived features for Phase 36 shadow sleeves.

Pure helpers that read a sequence of ``(ts_us, close, vol, taker_buy_quote,
quote_volume)`` tuples — the same shape stored by
:class:`backend.app.strategies.polymarket.vwap_store.Vwap15mStore` — and
return scalar features used by:

* ``VwapKellyEnsembleStrategy`` (S4 / S8 rules + Kelly tier)
* ``PrewindowS3Strategy`` (S3 rule at slot_start − 60 s)
* ``PrewindowS4Strategy`` (S4 rule at slot_start − 120 s)

CLAUDE.md inv #4: pure functions — no IO, no ``time.time()``, no mutation.
Callers pass the bars + anchor timestamp and get scalars back.

Spec: ``strategy_lab/reports/SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md``.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Iterable

__all__ = [
    "cvd_window",
    "cvd_agree",
    "macd_hist",
    "macd_agree",
    "rvol_window",
    "fair_up",
    "fair_edge_bp",
    "sigma_per_sqrt_sec_15m",
]


# ─── CVD ─────────────────────────────────────────────────────────────────────
def cvd_window(
    bars: Sequence[tuple[int, float, float, float, float]],
    anchor_us: int,
    window_s: int,
) -> float | None:
    """Cumulative volume delta over the last ``window_s`` seconds at-or-before
    ``anchor_us``.

    Per the spec: ``CVD = Σ (2·taker_buy_quote − quote_volume)`` over the
    selected bars. Positive = net buyer aggression; negative = net seller.

    Returns ``None`` if no bars fall in the window.
    """
    if window_s <= 0:
        return None
    from_us = anchor_us - window_s * 1_000_000
    accum = 0.0
    found = 0
    for entry in bars:
        ts_us = entry[0]
        if ts_us < from_us:
            continue
        if ts_us > anchor_us:
            break
        taker_buy_quote = entry[3] if len(entry) > 3 else 0.0
        quote_volume = entry[4] if len(entry) > 4 else 0.0
        accum += 2.0 * taker_buy_quote - quote_volume
        found += 1
    if found == 0:
        return None
    return accum


def cvd_agree(cvd_value: float | None, direction: str) -> bool:
    """True iff ``cvd_value`` sign agrees with ``direction``.

    ``direction`` must be ``"UP"`` or ``"DOWN"``. NaN / None / zero CVD
    fails (no agreement signal). Used by Sleeve #1 / #8 / #9 to enforce
    the ``cvd_agree_30s`` / ``cvd_agree_60s`` rule components.
    """
    if cvd_value is None or not math.isfinite(cvd_value):
        return False
    if direction == "UP":
        return cvd_value > 0
    if direction == "DOWN":
        return cvd_value < 0
    return False


# ─── MACD ────────────────────────────────────────────────────────────────────
def _ema(values: Sequence[float], span: int) -> list[float]:
    """Exponential moving average with the conventional 2/(span+1) alpha."""
    if not values or span <= 0:
        return []
    alpha = 2.0 / (span + 1.0)
    out: list[float] = []
    prev = values[0]
    for v in values:
        prev = alpha * v + (1.0 - alpha) * prev
        out.append(prev)
    return out


def macd_hist(
    closes: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> float | None:
    """MACD histogram at the most recent close. Standard (12, 26, 9) params.

    Returns ``None`` when there are fewer than ``slow + signal`` finite
    closes — the caller treats that as warmup (gate fails closed).
    """
    finite = [float(c) for c in closes if c is not None and math.isfinite(float(c))]
    if len(finite) < slow + signal:
        return None
    ema_fast = _ema(finite, fast)
    ema_slow = _ema(finite, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    sig_line = _ema(macd_line[-signal * 4 :] if len(macd_line) > signal * 4 else macd_line, signal)
    if not sig_line:
        return None
    hist = macd_line[-1] - sig_line[-1]
    return hist if math.isfinite(hist) else None


def macd_agree(hist: float | None, direction: str) -> bool:
    """True iff ``hist`` sign agrees with ``direction``."""
    if hist is None or not math.isfinite(hist):
        return False
    if direction == "UP":
        return hist > 0
    if direction == "DOWN":
        return hist < 0
    return False


# ─── Relative volume ────────────────────────────────────────────────────────
def rvol_window(
    bars: Sequence[tuple[int, float, float, float, float]],
    anchor_us: int,
    short_s: int = 30,
    long_s: int = 300,
) -> float | None:
    """Realized volume ratio: ``vol(last short_s) / mean_vol_per_short_s(last long_s)``.

    Per the spec ``rvol_30_300 > 1.2`` is the activity filter for the S8
    momentum rule. ``mean_vol_per_short_s`` = ``sum(long_s) / (long_s/short_s)``.

    Returns ``None`` when either window is empty or has zero volume.
    """
    if short_s <= 0 or long_s <= 0 or long_s < short_s:
        return None
    short_from = anchor_us - short_s * 1_000_000
    long_from = anchor_us - long_s * 1_000_000
    short_vol = 0.0
    long_vol = 0.0
    short_n = 0
    long_n = 0
    for entry in bars:
        ts_us = entry[0]
        if ts_us > anchor_us:
            break
        vol = entry[2]
        if ts_us >= short_from:
            short_vol += vol
            short_n += 1
        if ts_us >= long_from:
            long_vol += vol
            long_n += 1
    if long_n == 0 or short_n == 0:
        return None
    # Mean volume per short_s-second window across the long_s span.
    buckets = max(1.0, long_s / short_s)
    mean_short = long_vol / buckets
    if mean_short <= 0:
        return None
    return short_vol / mean_short


# ─── Sigma — realized 1s volatility over 15m anchored window ────────────────
def sigma_per_sqrt_sec_15m(
    bars: Sequence[tuple[int, float, float, float, float]],
    anchor_us: int,
) -> float | None:
    """std(log_rets) of 1s closes over the prior 900 s ending at ``anchor_us``.

    Used by ``fair_up`` to scale the (s_now / strike) z-score by tau. Returns
    ``None`` if fewer than 30 returns can be computed.
    """
    from_us = anchor_us - 900 * 1_000_000
    closes: list[tuple[int, float]] = []
    for entry in bars:
        ts_us, close = entry[0], entry[1]
        if ts_us < from_us:
            continue
        if ts_us > anchor_us:
            break
        if math.isfinite(close) and close > 0:
            closes.append((ts_us, close))
    if len(closes) < 31:
        return None
    rets: list[float] = []
    for i in range(1, len(closes)):
        try:
            r = math.log(closes[i][1] / closes[i - 1][1])
            if math.isfinite(r):
                rets.append(r)
        except (ValueError, ArithmeticError):
            continue
    if len(rets) < 30:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    if var <= 0:
        return None
    return math.sqrt(var)


# ─── Fair-value (norm.cdf approx without scipy) ──────────────────────────────
def _norm_cdf(z: float) -> float:
    """Abramowitz-Stegun 7.1.26 — accurate to ~7.5e-8 for |z| < 8."""
    # erf via series (math.erf is built-in).
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def fair_up(
    s_now: float,
    strike: float,
    sigma_per_sqrt_sec: float,
    tau_s: float,
) -> float | None:
    """Probability that Up resolves given a Bachelier-style random walk.

    ``z = log(s_now / strike) / (sigma · sqrt(tau_s))``. P(Up) = N(z).
    Returns ``None`` when any input is non-finite, ``sigma <= 0``, or
    ``tau_s <= 0`` (e.g., post-slot-close).
    """
    if (
        not math.isfinite(s_now)
        or not math.isfinite(strike)
        or not math.isfinite(sigma_per_sqrt_sec)
        or not math.isfinite(tau_s)
        or s_now <= 0
        or strike <= 0
        or sigma_per_sqrt_sec <= 0
        or tau_s <= 0
    ):
        return None
    try:
        z = math.log(s_now / strike) / (sigma_per_sqrt_sec * math.sqrt(tau_s))
    except (ValueError, ArithmeticError):
        return None
    return _norm_cdf(z)


def fair_edge_bp(
    fair_up_value: float | None,
    entry_vwap: float | None,
    direction: str,
) -> float | None:
    """``fair_edge_bp = (model_prob - entry_vwap) × 10_000``.

    For UP: model prob is ``fair_up``; for DOWN: ``1 - fair_up``. Positive
    means the FV model thinks our bet has +X bp of expected edge over the
    Polymarket entry price.
    """
    if (
        fair_up_value is None
        or entry_vwap is None
        or not math.isfinite(fair_up_value)
        or not math.isfinite(entry_vwap)
    ):
        return None
    if direction == "UP":
        return (fair_up_value - entry_vwap) * 10_000.0
    if direction == "DOWN":
        return ((1.0 - fair_up_value) - entry_vwap) * 10_000.0
    return None
