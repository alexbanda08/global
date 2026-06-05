"""Risk rails package (Phase 10, RAIL-01..13).

One file per rail under this package, plus a ``framework`` module that
defines the shared enums + result / decision dataclasses. The top-level
orchestrator ``check_all_rails`` lives in
``backend.app.engine.risk_guardrails`` (one level up).

Design invariants (CLAUDE.md §5, §7):

* Rails are PURE FUNCTIONS. Every argument is keyword-only; no IO, no
  side effects. Integration glue (DB reads, event writes) happens in the
  orchestrator / controllers, NOT inside rails.
* Boundary semantics are strict ``>``: a rail at 8% threshold fires at
  8.01%, NOT at exactly 8.00%.
* Kill-switch is NEVER a directly callable method. Rails emit
  ``RailAction.REQUEST_KILL`` + the orchestrator writes a
  ``trading.events(kind='kill_switch_requested')`` row. No ``def kill(``
  anywhere under this package.
"""
from __future__ import annotations

from backend.app.engine.rails.framework import (
    RailAction,
    RailDecision,
    RailId,
    RailResult,
    RailSeverity,
)

__all__ = [
    "RailAction",
    "RailDecision",
    "RailId",
    "RailResult",
    "RailSeverity",
]
