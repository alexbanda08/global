"""F7 RSI agreement gate for Polymarket momo signals.

Per ``strategy_lab/reports/TV_AGENT_F7_RSI_FILTER_SPEC.md`` (2026-05-20):
skip a momo fire when the binance 1MIN RSI(14) at signal time disagrees
with the momo direction. Pure boolean helpers — no IO, no state.

Validated on 14 days of VPS3 shadow data (3,277 resolutions, 12 cells):

* Without F7: WR 49.65%, PnL −$1,966
* + F7 basic: WR 59.69%, PnL +$9,879   (+$846/day)
* 0 / 12 cells regress

Threshold variants (spec §1):

* ``basic`` — UP requires RSI > 50; DOWN requires RSI < 50. Filters
  ~31% of fires.
* ``extreme`` — UP requires RSI > 60; DOWN requires RSI < 40. Filters
  ~60% of fires; higher per-trade WR, smaller universe.

Gate placement: AFTER the strategy decides direction (``UP``/``DOWN``),
BEFORE the order is emitted. See spec §3 for the call-site pattern.

CLAUDE.md inv #4: pure boolean — no IO, no time.time(), no mutation.
"""
from __future__ import annotations

import math
from typing import Literal

__all__ = [
    "F7Mode",
    "f7_passes",
    "f7_basic_passes",
    "f7_extreme_passes",
    "decision_label",
]

#: F7 filter mode literal — operator-tunable per sleeve via aux.
F7Mode = Literal["off", "basic", "extreme"]

#: F7 basic thresholds (spec §1).
_F7_BASIC_UP_MIN: float = 50.0
_F7_BASIC_DOWN_MAX: float = 50.0

#: F7 extreme thresholds (spec §1).
_F7_EXTREME_UP_MIN: float = 60.0
_F7_EXTREME_DOWN_MAX: float = 40.0


def f7_basic_passes(signal: str, rsi_14: float) -> bool:
    """F7 basic agreement gate — UP requires RSI > 50; DOWN requires RSI < 50.

    Returns False (skip the fire) if:
        * RSI is NaN (warming up or stale → caller treats as ``"skip_nan_rsi"``)
        * UP signal but RSI ≤ 50 (disagreement)
        * DOWN signal but RSI ≥ 50 (disagreement)

    Boundary: equality at 50 SKIPS (per spec — ``<=`` for UP, ``>=`` for DOWN).
    """
    if not math.isfinite(rsi_14):
        return False
    if signal == "UP" and rsi_14 <= _F7_BASIC_UP_MIN:
        return False
    if signal == "DOWN" and rsi_14 >= _F7_BASIC_DOWN_MAX:
        return False
    return True


def f7_extreme_passes(signal: str, rsi_14: float) -> bool:
    """F7 extreme agreement gate — UP requires RSI > 60; DOWN requires RSI < 40.

    Tighter than basic: cuts roughly twice as many fires but pushes WR
    further. Designed for parallel A/B with basic.
    """
    if not math.isfinite(rsi_14):
        return False
    if signal == "UP" and rsi_14 <= _F7_EXTREME_UP_MIN:
        return False
    if signal == "DOWN" and rsi_14 >= _F7_EXTREME_DOWN_MAX:
        return False
    return True


def f7_passes(signal: str, rsi_14: float, mode: F7Mode = "off") -> bool:
    """Dispatch helper — pick the right gate by sleeve's configured F7 mode.

    Args:
        signal: ``"UP"`` or ``"DOWN"``. Other values return True
            (gate is a no-op for non-directional signals).
        rsi_14: Current RSI value or ``nan`` (warming up / stale).
        mode: Per-sleeve toggle:

            * ``"off"`` → always passes (baseline sleeves)
            * ``"basic"`` → ``f7_basic_passes``
            * ``"extreme"`` → ``f7_extreme_passes``

    Unknown modes default to ``"off"`` (fail-open — never silently
    block a baseline due to a config typo).
    """
    if mode == "off":
        return True
    if signal not in ("UP", "DOWN"):
        return True
    if mode == "basic":
        return f7_basic_passes(signal, rsi_14)
    if mode == "extreme":
        return f7_extreme_passes(signal, rsi_14)
    return True


def decision_label(signal: str, rsi_14: float, mode: F7Mode) -> str:
    """Human-readable label for the F7 decision (audit row payload).

    Returns one of:

    * ``"pass"`` — gate accepts (or mode is "off")
    * ``"skip_nan_rsi"`` — RSI is NaN (warmup/stale)
    * ``"skip_disagree_up_rsi=42.10"`` — UP signal vs low RSI
    * ``"skip_disagree_down_rsi=58.20"`` — DOWN signal vs high RSI
    """
    if mode == "off" or signal not in ("UP", "DOWN"):
        return "pass"
    if not math.isfinite(rsi_14):
        return "skip_nan_rsi"
    if f7_passes(signal, rsi_14, mode):
        return "pass"
    return f"skip_disagree_{signal.lower()}_rsi={rsi_14:.2f}"
