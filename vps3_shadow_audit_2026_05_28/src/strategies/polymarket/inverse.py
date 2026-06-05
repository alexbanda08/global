"""Phase 18.4 — Inverse sleeves (anti-edge shadow, paper-only).

Per ``strategy_lab/reports/TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md``
(2026-05-05) plus ``ANTI_EDGE_FINDINGS.md``: three biases identified in
V1 (volume) and V2 (sniper) shadow runs are negatively predictive — the
inverse fires 60-65%. These shadow sleeves test whether flipping the
signal in the bias windows produces the predicted hit rate.

Three inverse rules:
  - ``inverse_volume_night`` — wraps V1 volume mode. Flips signal when
    the bar window's UTC hour ∈ {1,2,3,4,5,9,10}. Applies to all (symbol,
    tf) pairs. Six sleeve_ids:
        poly_updown_{btc,eth,sol}_{5m,15m}_volume_INV_NIGHT
  - ``inverse_sol_sniper`` — wraps V2 sniper mode. Always flips, but only
    fires for (SOL, 5m). One sleeve_id:
        poly_updown_sol_5m_sniper_INV
  - ``inverse_sniper_down`` — wraps V2 sniper mode. Only flips DOWN base
    signals (UP base signals → silent). Only fires for (ETH, 5m). One
    sleeve_id:
        poly_updown_eth_5m_sniper_DOWN_INV

Outside its rule window, an inverse sleeve is silent — no audit row.
This isolates the test cell and avoids competing with the original.

Hedge-hold is hard-skipped on inverse sleeves regardless of
``TV_POLY_HEDGE_POLICY`` (Q5 confirmed 2026-05-05). See
``PolymarketUpdownController._maybe_hedge`` for the guard.

Activation flag: ``TV_INVERSE_SLEEVES_ENABLED=true`` (default ``false``).
With the flag off, ``engine/main.py`` does not import this module beyond
the controller's module-level type/helper imports — and zero inverse
controllers are constructed. See operator's Phase A guidance for the
flag-gating contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

# UTC hours where V1 volume mode shows negative predictive value (per
# ANTI_EDGE_FINDINGS.md / PER_SLEEVE_DETAIL_2026_05_01.md). Anchored to
# bar window_start, NOT server clock — must match the analysis cell
# which used ``EXTRACT(hour FROM at)`` where ``at`` was set at the
# controller's signal-evaluation time = bar-close time.
NIGHT_HOURS_UTC: frozenset[int] = frozenset({1, 2, 3, 4, 5, 9, 10})

# Inverse-mode names. Stable strings; the controller's strategy_mode
# Literal accepts any of these in addition to the 7 base modes.
InverseKind = Literal[
    "inverse_volume_night",
    "inverse_sol_sniper",
    "inverse_sniper_down",
]

INVERSE_KINDS: tuple[InverseKind, ...] = (
    "inverse_volume_night",
    "inverse_sol_sniper",
    "inverse_sniper_down",
)

# Inverse kind → underlying strategy class mode (volume or sniper).
# Drives ``_strategy_class_mode`` selection in the controller __init__.
INVERSE_BASE_MODE: dict[InverseKind, Literal["volume", "sniper"]] = {
    "inverse_volume_night": "volume",
    "inverse_sol_sniper": "sniper",
    "inverse_sniper_down": "sniper",
}

# Inverse kind → ``inverse_reason`` value written into the audit row's
# JSONB payload. Keeps downstream analysis SQL simple
# (``WHERE data->>'inverse_reason' = 'night_hour'``).
INVERSE_REASON: dict[InverseKind, str] = {
    "inverse_volume_night": "night_hour",
    "inverse_sol_sniper": "sol_sniper_full",
    "inverse_sniper_down": "eth_sniper_down_only",
}


def is_night_hour_utc(window_start_unix: int) -> bool:
    """Return ``True`` iff the bar window's UTC hour ∈ ``NIGHT_HOURS_UTC``.

    Args:
        window_start_unix: Unix timestamp (seconds since epoch) of the
            bar window opening. Caller MUST pass the bar-window time, NOT
            the server clock — the bias was computed against bar-window
            UTC hour.
    """
    hour = datetime.fromtimestamp(window_start_unix, tz=UTC).hour
    return hour in NIGHT_HOURS_UTC


def flip_signal(direction: str) -> str:
    """Return the opposite direction. Pass-through for ``NONE`` / unknown.

    UP ↔ DOWN. Anything else (e.g. ``"NONE"``) returns unchanged so
    callers can compose without special-casing.
    """
    if direction == "UP":
        return "DOWN"
    if direction == "DOWN":
        return "UP"
    return direction


def apply_inverse_filter(
    *,
    kind: InverseKind,
    symbol: str,
    tf: str,
    base_signal: str,
    window_start_unix: int,
) -> str:
    """Apply the inverse rule. Return flipped signal or ``"NONE"`` if silent.

    Returning ``"NONE"`` means the inverse sleeve does not fire on this
    window — the controller MUST suppress the audit row in that case
    (silence is by design; spec §1: "don't compete with the original").

    Args:
        kind: Which inverse rule to apply.
        symbol: TV symbol (BTC/ETH/SOL).
        tf: Timeframe (``"5m"`` | ``"15m"``).
        base_signal: The unflipped signal from the underlying strategy.
            ``"UP"`` | ``"DOWN"`` | ``"NONE"``.
        window_start_unix: Bar-window UTC time anchor (seconds since
            epoch) — same anchor used by the bias analysis.

    Returns:
        ``"UP"`` | ``"DOWN"`` if the inverse rule fires (flipped from
        ``base_signal``); ``"NONE"`` otherwise.
    """
    if base_signal == "NONE":
        return "NONE"
    sym_upper = symbol.upper()
    if kind == "inverse_volume_night":
        # All (symbol, tf) — gated by night-hour rule.
        if not is_night_hour_utc(window_start_unix):
            return "NONE"
        return flip_signal(base_signal)
    if kind == "inverse_sol_sniper":
        # SOL 5m only — always flip when base signal fires.
        if sym_upper != "SOL" or tf != "5m":
            return "NONE"
        return flip_signal(base_signal)
    if kind == "inverse_sniper_down":
        # ETH 5m only — flip DOWN base signals; UP base → silent.
        if sym_upper != "ETH" or tf != "5m":
            return "NONE"
        if base_signal != "DOWN":
            return "NONE"
        return flip_signal(base_signal)  # DOWN → UP
    # Unknown kind — fail-silent rather than raise (defensive; the
    # controller validates kind at __init__ time).
    return "NONE"


def inverse_sleeve_id(*, kind: InverseKind, symbol: str, tf: str) -> str:
    """Return the spec-fixed sleeve_id for an inverse sleeve.

    Naming (per Q4 — single sleeve_id per inverse rule, no outcome
    split, fixed suffix):
      - ``inverse_volume_night``  → ``poly_updown_{sym}_{tf}_volume_INV_NIGHT``
      - ``inverse_sol_sniper``    → ``poly_updown_{sym}_{tf}_sniper_INV``
      - ``inverse_sniper_down``   → ``poly_updown_{sym}_{tf}_sniper_DOWN_INV``
    """
    sym = symbol.lower()
    if kind == "inverse_volume_night":
        return f"poly_updown_{sym}_{tf}_volume_INV_NIGHT"
    if kind == "inverse_sol_sniper":
        return f"poly_updown_{sym}_{tf}_sniper_INV"
    if kind == "inverse_sniper_down":
        return f"poly_updown_{sym}_{tf}_sniper_DOWN_INV"
    raise ValueError(f"unknown inverse kind: {kind!r}")


def is_inverse_sleeve(sleeve_id: str) -> bool:
    """Return ``True`` iff ``sleeve_id`` matches inverse naming.

    Used by ``_maybe_hedge`` for the hard-skip guard (Q5) and by paper-
    only assertions. Matches:
      - ``..._volume_INV_NIGHT``  (ends with ``_INV_NIGHT``)
      - ``..._sniper_INV``        (ends with ``_INV``)
      - ``..._sniper_DOWN_INV``   (ends with ``_INV``)
    """
    return sleeve_id.endswith(("_INV", "_INV_NIGHT"))


__all__ = [
    "INVERSE_BASE_MODE",
    "INVERSE_KINDS",
    "INVERSE_REASON",
    "InverseKind",
    "NIGHT_HOURS_UTC",
    "apply_inverse_filter",
    "flip_signal",
    "inverse_sleeve_id",
    "is_inverse_sleeve",
    "is_night_hour_utc",
]
