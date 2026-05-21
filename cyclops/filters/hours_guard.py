"""Time-of-day / day-of-week trading window.

Cyclops Day 3:
    "Bitcoin moves when institutions move. Weekday hours only.
     Weekends fully off. Bot stays running, only entries blocked."

Defaults from spec §4.1: 13:00-21:00 UTC, weekends off. These were a
placeholder — the spec §13 open question #2 says to run a per-hour PnL
split BEFORE setting these vars. Treat the defaults as a starting point,
not a verified optimum.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Tuple

from ..conventions import (
    PAUSE_WINDOWS_UTC,
    TRADING_START_UTC,
    TRADING_STOP_UTC,
    WEEKEND_OFF,
)


def is_trading_hour(
    ts_utc_seconds: int,
    start_utc: float = TRADING_START_UTC,
    stop_utc: float = TRADING_STOP_UTC,
    pause_windows: Iterable[Tuple[float, float]] = (),
    weekend_off: bool = WEEKEND_OFF,
) -> Tuple[bool, str]:
    """Return (allowed, reason).

    `start_utc` / `stop_utc` accept fractional hours (e.g. 8.75 = 08:45).
    `pause_windows` is a list of (lo, hi) ranges within which entries are
    blocked even during trading hours (e.g. lunch pause).
    """
    if start_utc <= 0 and stop_utc >= 24 and not weekend_off and not pause_windows:
        return True, "guard_disabled"

    dt = datetime.fromtimestamp(int(ts_utc_seconds), tz=timezone.utc)
    if weekend_off and dt.weekday() >= 5:
        return False, f"weekend_{dt.weekday()}"
    hour_frac = dt.hour + dt.minute / 60 + dt.second / 3600
    if hour_frac < start_utc:
        return False, f"pre_open_{hour_frac:.2f}<{start_utc:.2f}"
    if hour_frac >= stop_utc:
        return False, f"post_close_{hour_frac:.2f}>={stop_utc:.2f}"
    for lo, hi in pause_windows:
        if lo <= hour_frac < hi:
            return False, f"pause_{lo:.2f}_{hi:.2f}"
    return True, "ok"
