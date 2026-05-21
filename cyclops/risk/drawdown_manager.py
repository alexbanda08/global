"""P4: drawdown + daily-loss risk manager with balance-recovery resume.

Faithful implementation of spec §4.13. Three rules:

  1. Peak drawdown halt — if balance falls ≥ MAX_DRAWDOWN_PCT% from session
     peak, halt. Resume only after balance climbs back to
     `peak * (1 - RECOVERY_RESUME_FACTOR * MAX_DRAWDOWN_PCT / 100)`
     (half-way back to peak by default).

  2. Daily loss halt — if balance falls ≥ DAILY_LOSS_LIMIT_PCT% from the
     start-of-day balance, halt for the rest of the UTC day.

  3. UTC midnight roll — `day_start_balance` snapshots whenever a new UTC
     day starts. Daily-halt cleared at the same instant.

The manager is purely event-driven: every call to `update(balance, ts)`
refreshes state; every call to `is_halted(balance)` returns the current
verdict. No timers, no async.
"""

from __future__ import annotations

from typing import Tuple

from ..conventions import (
    DAILY_LOSS_LIMIT_PCT,
    MAX_DRAWDOWN_PCT,
    RECOVERY_RESUME_FACTOR,
)


class DrawdownManager:
    def __init__(
        self,
        start_balance: float,
        max_drawdown_pct: float = MAX_DRAWDOWN_PCT,
        daily_loss_limit_pct: float = DAILY_LOSS_LIMIT_PCT,
        recovery_factor: float = RECOVERY_RESUME_FACTOR,
    ):
        self.start_balance = float(start_balance)
        self.peak = float(start_balance)
        self.day_start_balance = float(start_balance)
        self.day_start_ts: int | None = None
        self.max_dd_pct = float(max_drawdown_pct)
        self.daily_loss_pct = float(daily_loss_limit_pct)
        self.recovery_factor = float(recovery_factor)
        self._halted_until_recovery_to: float | None = None
        self._daily_halt_active = False
        # Telemetry
        self.n_pauses_drawdown = 0
        self.n_pauses_daily = 0

    def update(self, current_balance: float, now_ts_s: int) -> None:
        """Refresh peak + roll day if UTC midnight crossed."""
        if current_balance > self.peak:
            self.peak = float(current_balance)
        day = int(now_ts_s) // 86400
        if self.day_start_ts is None or day != self.day_start_ts:
            self.day_start_ts = day
            self.day_start_balance = float(current_balance)
            self._daily_halt_active = False  # new day → clear daily halt

    def is_halted(self, current_balance: float) -> Tuple[bool, str]:
        """Return (halted, reason). Reason is "ok" when not halted."""
        # 1. Drawdown-recovery wait
        if self._halted_until_recovery_to is not None:
            if current_balance >= self._halted_until_recovery_to:
                self._halted_until_recovery_to = None
            else:
                return True, "drawdown_recovery_pending"

        # 2. Hard drawdown trigger
        if self.peak > 0:
            dd_pct = (self.peak - current_balance) / self.peak * 100
            if dd_pct >= self.max_dd_pct:
                self._halted_until_recovery_to = self.peak * (
                    1 - self.recovery_factor * self.max_dd_pct / 100
                )
                self.n_pauses_drawdown += 1
                return True, f"max_drawdown_{dd_pct:.2f}pct"

        # 3. Daily loss
        if self._daily_halt_active:
            return True, "daily_loss_locked"
        if self.day_start_balance > 0:
            day_loss_pct = (
                (self.day_start_balance - current_balance) / self.day_start_balance * 100
            )
            if day_loss_pct >= self.daily_loss_pct:
                self._daily_halt_active = True
                self.n_pauses_daily += 1
                return True, f"daily_loss_{day_loss_pct:.2f}pct"

        return False, "ok"

    def stats(self) -> dict:
        return {
            "start_balance": self.start_balance,
            "peak": self.peak,
            "n_pauses_drawdown": self.n_pauses_drawdown,
            "n_pauses_daily": self.n_pauses_daily,
        }
