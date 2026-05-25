"""Pre-placement gate stack for Polymarket shadow sleeves (Phase 34).

Per ``strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md``:
three pure-function gates that run AFTER the underlying strategy ``signal()``
returns UP/DOWN AND AFTER F7 (when active) BUT BEFORE qty/token-id/place.

* ``hod`` — Hour-of-Day Top-8 (per cell, UTC hours)
* ``mtf2`` — Multi-Timeframe confluence (binance 15m + 1h same-source as momo)
* ``m5va`` — Markov regime w20 × 5m × vol-adaptive (Bear/Sideways/Bull)

Backtest evidence (28d Apr 22 - May 21): see spec §11. Gates lift WR by
3-15pp at the cost of 60-90% fewer fires per sleeve.

CLAUDE.md inv #4: pure helpers — no IO, no time.time() inside the gate, no
mutation. The CONTROLLER is responsible for populating ``aux`` from the
``BarContext`` and for clocking the fire decision time.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Iterable

__all__ = [
    "HOD_TOP8_BY_CELL",
    "hod_passes",
    "mtf2_passes",
    "markov_passes",
    "decision_label_hod",
    "decision_label_mtf2",
    "decision_label_markov",
]

# ─── Section 2.1 — Hour-of-Day Top-8 by (strategy, cell) ────────────────────
# UTC hours, 0-indexed. Source: 28-day backtest sum$ per (strategy, cell).
# Refresh monthly (spec §6) via strategy_lab/markov_filter/_recompute_hod_top8.py.
# DO NOT auto-update — operator review gate prevents bad-month outliers.
HOD_TOP8_BY_CELL: dict[tuple[str, str], tuple[int, ...]] = {
    ("sniper",  "sol_5m"):  (0, 1, 2, 4, 8, 15, 19, 23),
    ("sniper",  "eth_15m"): (0, 6, 7, 9, 13, 14, 19, 22),
    ("momo",    "btc_15m"): (0, 1, 3, 5, 9, 14, 16, 20),    # momo = v1
    ("sniper",  "btc_15m"): (0, 3, 10, 11, 12, 13, 14, 15),
    ("sniper",  "btc_5m"):  (0, 1, 3, 5, 12, 15, 19, 21),
    ("momo_v2", "btc_5m"):  (0, 2, 5, 6, 10, 12, 21, 23),
    ("momo_v2", "btc_15m"): (1, 11, 12, 16, 18, 20, 21, 22),
    ("momo_v2", "sol_5m"):  (4, 5, 6, 8, 10, 12, 14, 17),
    ("momo_v2", "eth_15m"): (0, 5, 8, 12, 16, 17, 20, 22),
    ("momo_v2", "sol_15m"): (1, 2, 5, 12, 13, 16, 17, 21),
    ("sniper",  "eth_5m"):  (0, 2, 11, 13, 14, 17, 20, 21),
}


# ─── Section 2.1 — HoD gate ─────────────────────────────────────────────────
def hod_passes(fire_unix_s: int, allowed_hours: Iterable[int]) -> bool:
    """Return True if UTC hour of ``fire_unix_s`` is in ``allowed_hours``.

    Args:
        fire_unix_s: seconds since epoch of the controller's fire decision
            moment. CONTROLLER reads ``int(time.time())`` and passes here —
            this function MUST NOT call ``time.time()`` itself (purity).
        allowed_hours: iterable of UTC hours in [0, 23]. Empty iterable
            blocks all fires (fail-closed for un-configured cells).

    No local-time, ever (spec §7). Anchor to UTC.
    """
    hour = datetime.fromtimestamp(int(fire_unix_s), tz=UTC).hour
    return hour in set(allowed_hours)


# ─── Section 2.2 — MTF2 confluence gate ─────────────────────────────────────
def mtf2_passes(signal: str, ret_15m: float, ret_1h: float) -> bool:
    """Both binance 15m + 1h log returns must match the signal direction.

    Args:
        signal: ``"UP"`` | ``"DOWN"`` | other. Other returns True (no-op).
        ret_15m: log(close@fire_us / close@(fire_us - 900s)). NaN → False.
        ret_1h:  log(close@fire_us / close@(fire_us - 3600s)). NaN → False.

    The 15m + 1h closes MUST come from the SAME binance-spot-ws kline source
    as the existing momo signal pipeline (no source mismatch — spec §7).
    """
    if signal not in ("UP", "DOWN"):
        return True
    if not (math.isfinite(ret_15m) and math.isfinite(ret_1h)):
        return False
    if signal == "UP":
        return ret_15m > 0 and ret_1h > 0
    return ret_15m < 0 and ret_1h < 0


# ─── Section 2.3 — Markov regime gate ───────────────────────────────────────
def markov_passes(signal: str, regime: int) -> bool:
    """Regime label: 0=Bear, 1=Sideways, 2=Bull, -1=warmup/unknown.

    UP requires Bull (2); DOWN requires Bear (0). Sideways and warmup
    BLOCK the fire (fail-closed — never silently let through during cold-start
    or quantile-warmup window).
    """
    if signal == "UP":
        return regime == 2
    if signal == "DOWN":
        return regime == 0
    return True  # non-directional signal → gate is no-op


# ─── Audit decision labels (for trading.events payload) ─────────────────────
def decision_label_hod(
    signal: str, fire_unix_s: int, allowed_hours: Iterable[int]
) -> str:
    """Human-readable label for HoD gate decision (audit row payload).

    Returns ``"pass"`` or ``"skip_hod_hour=NN_allowed=[...]"``.
    """
    if signal not in ("UP", "DOWN"):
        return "pass"  # non-directional — gate skipped at controller level
    hour = datetime.fromtimestamp(int(fire_unix_s), tz=UTC).hour
    if hour in set(allowed_hours):
        return "pass"
    return f"skip_hod_hour={hour}_allowed={sorted(set(allowed_hours))}"


def decision_label_mtf2(signal: str, ret_15m: float, ret_1h: float) -> str:
    """Label for MTF2 gate. Returns ``"pass"`` or specific skip reason."""
    if signal not in ("UP", "DOWN"):
        return "pass"
    if not (math.isfinite(ret_15m) and math.isfinite(ret_1h)):
        return "skip_mtf2_nan"
    if mtf2_passes(signal, ret_15m, ret_1h):
        return "pass"
    return f"skip_mtf2_disagree_{signal.lower()}_r15={ret_15m:+.5f}_r1h={ret_1h:+.5f}"


def decision_label_markov(signal: str, regime: int) -> str:
    """Label for Markov gate. Returns ``"pass"`` or specific skip reason."""
    if signal not in ("UP", "DOWN"):
        return "pass"
    if regime == -1:
        return "skip_markov_warmup"
    if markov_passes(signal, regime):
        return "pass"
    return f"skip_markov_disagree_{signal.lower()}_regime={regime}"
