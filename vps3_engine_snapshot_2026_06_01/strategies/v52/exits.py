"""V52 exits — canonical EXIT_4H + V41 regime-adaptive + V45 vol filter (Phase 8.1 Task 7).

Mirrors `backend/app/eval/perps_simulator.py:102-180` (long+short exit branches)
and `perps_simulator_adaptive_exit.py:138-149` (regime lookup table).

CRITICAL invariants:
  - Short-side trailing stop has `ll > 0` guard (perps_simulator.py:110) —
    handles the bar-0 case where `ll` is uninitialized. Copy verbatim.
  - Regime exit params are CAPTURED at entry; never re-read mid-trade.
  - GMM.predict() returns INTS; the regime-exit dict keys are STRINGS.
    `label_map: dict[int, str]` is provided here as a helper.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.app.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H

# Default canonical 4h exit profile == REGIME_EXITS_4H["MedVol"]
EXIT_4H_DEFAULT = (2.0, 10.0, 6.0, 60)


@dataclass
class ExitParams:
    sl_atr: float
    tp_atr: float
    trail_atr: float | None
    max_hold: int


@dataclass
class EntryState:
    direction: int  # +1 long, -1 short
    entry_price: float
    sl: float
    tp: float
    hh: float
    ll: float
    entry_idx: int
    params: ExitParams


@dataclass
class ExitAction:
    exited: bool
    exit_price: float = 0.0
    reason: str = ""
    new_sl: float | None = None  # ratchet update only (no exit)


def _trail_ratchet(state: EntryState, hi: float, lo: float, atr_now: float) -> float:
    """Returns updated SL (caller assigns). NO exit logic here."""
    sl = state.sl
    if state.params.trail_atr is None or not np.isfinite(atr_now) or atr_now <= 0:
        return sl
    if state.direction == 1:
        state.hh = max(state.hh, hi)
        new_sl = state.hh - state.params.trail_atr * atr_now
        if new_sl > sl:
            return new_sl
        return sl
    # short side — note `ll > 0` guard from perps_simulator.py:110 (load-bearing)
    state.ll = min(state.ll, lo) if state.ll > 0 else lo
    new_sl = state.ll + state.params.trail_atr * atr_now
    if new_sl < sl:
        return new_sl
    return sl


def exit_4h_canonical(
    state: EntryState,
    bar: dict[str, float],
    bar_idx: int,
    atr_now: float,
    slip: float = 0.0003,
) -> ExitAction:
    """Per perps_simulator.py:102-180 long+short branches."""
    state.sl = _trail_ratchet(state, bar["high"], bar["low"], atr_now)
    held = bar_idx - state.entry_idx
    hi, lo, cl = bar["high"], bar["low"], bar["close"]

    if state.direction == 1:
        if lo <= state.sl:
            return ExitAction(True, state.sl * (1 - slip), "SL")
        if hi >= state.tp:
            return ExitAction(True, state.tp * (1 - slip), "TP")
        if held >= state.params.max_hold:
            return ExitAction(True, cl, "TIME")
    else:
        if hi >= state.sl:
            return ExitAction(True, state.sl * (1 + slip), "SL")
        if lo <= state.tp:
            return ExitAction(True, state.tp * (1 + slip), "TP")
        if held >= state.params.max_hold:
            return ExitAction(True, cl, "TIME")

    return ExitAction(False, new_sl=state.sl)


def regime_params_for_label(
    label: str, table: dict[str, tuple[float, float, float, int]] | None = None
) -> ExitParams:
    """Lookup regime → ExitParams; defaults to MedVol per adaptive:138."""
    src = table or REGIME_EXITS_4H
    sl, tp, trail, hold = src.get(label, src["MedVol"])
    return ExitParams(sl_atr=sl, tp_atr=tp, trail_atr=trail, max_hold=int(hold))


def exit_v41_regime_adaptive(
    state: EntryState,
    bar: dict[str, float],
    bar_idx: int,
    atr_now: float,
    slip: float = 0.0003,
) -> ExitAction:
    """V41 regime-adaptive exit. Regime is FROZEN at entry — caller wires
    `state.params` from `regime_params_for_label(label)` BEFORE entry.
    Body identical to canonical EXIT_4H using `state.params`.
    """
    return exit_4h_canonical(state, bar, bar_idx, atr_now, slip=slip)


def exit_v45_volume_filter(
    state: EntryState,
    bar: dict[str, float],
    bar_idx: int,
    atr_now: float,
    volume_above_median: bool,
    slip: float = 0.0003,
) -> ExitAction:
    """V45 — gates the SuperTrend exit signal on volume confirmation.

    For now, the V45 logic only modifies entries (sig_supertrend_flip's
    `with_vol_filter`); on the EXIT side we run canonical EXIT_4H. This
    placeholder is reserved for future V45 exit-side gating.
    """
    _ = volume_above_median  # reserved for future gating
    return exit_4h_canonical(state, bar, bar_idx, atr_now, slip=slip)


def label_map_from_int_predictions(
    int_to_string: dict[int, str],
) -> dict[int, str]:
    """Identity helper for the GMM.predict() int → adaptive-table string
    bridge. Document-level: the GMM emits ints (cluster index), the
    adaptive REGIME_EXITS_4H table is keyed on strings. Callers MUST map
    at the classifier call-site, NOT inside the exit module (keeps exits pure).
    """
    return dict(int_to_string)


__all__ = [
    "EXIT_4H_DEFAULT",
    "EntryState",
    "ExitAction",
    "ExitParams",
    "exit_4h_canonical",
    "exit_v41_regime_adaptive",
    "exit_v45_volume_filter",
    "label_map_from_int_predictions",
    "regime_params_for_label",
]
