"""Per-market re-entry cooldown.

Cyclops Day 1+2 cheat-code log: the lock fires RIGHT AFTER the entry log,
BEFORE size/fill checks. Old bug: cooldown was set AFTER Kelly sizing, Kelly
blocked first, so 5 entries leaked into the same market in 6s.

In our backtest each (slug, ws_s) appears at most once so the lock is
effectively a no-op. It exists for the live-deploy path where the
controller might race or re-fire. We keep it here for parity with the
production spec and to cover the corner case where a future runner
double-fires the same slug.
"""

from __future__ import annotations

from typing import Dict

from ..conventions import REENTRY_COOLDOWN_SEC


class ReentryLock:
    """In-memory map: condition_id → unlock_ts_us (microseconds since epoch).

    Always call `lock()` IMMEDIATELY on the entry decision — even before
    fill or sizing — so any downstream pipeline retry sees the lock.
    """

    def __init__(self, cooldown_sec: int = REENTRY_COOLDOWN_SEC):
        self._locks: Dict[str, int] = {}
        self.cooldown_sec = int(cooldown_sec)
        self.n_blocked = 0          # telemetry counter

    def is_locked(self, condition_id: str, now_us: int) -> bool:
        unlock_us = self._locks.get(condition_id, 0)
        return unlock_us > int(now_us)

    def lock(self, condition_id: str, now_us: int) -> None:
        self._locks[condition_id] = int(now_us) + self.cooldown_sec * 1_000_000

    def block_if_locked(self, condition_id: str, now_us: int):
        """Convenience: returns (blocked, reason). Updates the telemetry
        counter so the runner can report per-session block stats."""
        if self.is_locked(condition_id, now_us):
            self.n_blocked += 1
            return True, f"reentry_locked_{self.cooldown_sec}s"
        return False, "ok"
