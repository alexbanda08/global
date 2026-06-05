"""Rails framework — enums + result / decision dataclasses (Phase 10, Task 1).

This module is IO-free and import-light. Every rail in this package
returns a ``RailResult``; the orchestrator composes fired results into a
single ``RailDecision`` that controllers route on.

See ``10-CONTEXT.md`` D-01 for the decision rationale. The key invariant
is CLAUDE.md §7: there is NO ``kill()`` method anywhere. Rails emit
``RailAction.REQUEST_KILL``; the orchestrator writes a
``trading.events(kind='kill_switch_requested')`` row; Phase 12 consumes
the request.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class RailId(StrEnum):
    """Stable identifier for each rail (RAIL-01..11).

    The string value matches the filename suffix under ``rails/`` so
    operators grepping logs can trace a rail firing back to its source
    module in one step.
    """

    PER_POSITION_SL = "rail_01_per_position_sl"
    SLEEVE_24H_DD = "rail_02_sleeve_24h_dd"
    PORTFOLIO_DD_15 = "rail_03_portfolio_dd_15"
    PORTFOLIO_DD_25 = "rail_04_portfolio_dd_25"
    PORTFOLIO_DD_30_KILL = "rail_05_portfolio_dd_30_kill"
    FUNDING_SPIKE = "rail_06_funding_spike"
    EXCHANGE_OUTAGE = "rail_07_exchange_outage"
    CONCENTRATION_40 = "rail_08_concentration_40"
    CORRELATION_KILL = "rail_09_correlation_kill"
    ABS_DAY_LOSS_WARN = "rail_11_abs_day_loss_warn"
    ABS_DAY_LOSS_KILL = "rail_11_abs_day_loss_kill"


class RailSeverity(StrEnum):
    """Three severity levels routed by controllers / alerting.

    * ``INFO`` — expected event (e.g. per-position SL hit on a closed bar).
    * ``WARN`` — sleeve / portfolio-level action (pause, halve risk).
    * ``CRITICAL`` — kill request; Phase 12 consumer routes to kill path.
    """

    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class RailAction(StrEnum):
    """What the controller must DO when a rail fires.

    Ordering in ``_ACTION_PRIORITY`` (below) implements the composite
    selection rule: most severe action wins when several rails fire on
    the same bar.

    Note: ``BLOCK_NEW_SHORT`` is symmetric with ``BLOCK_NEW_LONG`` —
    Rail 6 (funding spike) uses both (negative-spike symmetric case).
    """

    NONE = "none"
    CLOSE_POSITION = "close_position"
    PAUSE_SLEEVE = "pause_sleeve"
    HALVE_RISK = "halve_risk"
    HALVE_LEVERAGE = "halve_leverage"
    BLOCK_NEW_LONG = "block_new_long"
    BLOCK_NEW_SHORT = "block_new_short"
    CLOSE_ALL = "close_all"
    REFUSE_ENTRY = "refuse_entry"
    REQUEST_KILL = "request_kill"


# Priority for composite action selection: higher number = more severe.
# REQUEST_KILL wins over everything. CLOSE_ALL next. Then sleeve-level
# actions. BLOCK / REFUSE are entry-guards (do not halt existing work).
_ACTION_PRIORITY: dict[RailAction, int] = {
    RailAction.NONE: 0,
    RailAction.CLOSE_POSITION: 1,
    RailAction.BLOCK_NEW_LONG: 2,
    RailAction.BLOCK_NEW_SHORT: 2,
    RailAction.REFUSE_ENTRY: 3,
    RailAction.HALVE_RISK: 4,
    RailAction.HALVE_LEVERAGE: 5,
    RailAction.PAUSE_SLEEVE: 6,
    RailAction.CLOSE_ALL: 7,
    RailAction.REQUEST_KILL: 8,
}


def action_priority(action: RailAction) -> int:
    """Return the composite-priority rank for ``action``.

    Used by ``RailDecision`` to pick the most-severe action when several
    rails fire on the same bar. Exposed for tests.
    """
    return _ACTION_PRIORITY.get(action, 0)


class RailResult(BaseModel):
    """One rail's evaluation for one bar.

    ``fired=False`` rails still return a RailResult — the orchestrator
    drops them from the ``fired_rails`` list but callers may want to
    inspect every rail's payload for audit.

    Frozen + extra=forbid: rails must not invent new fields at call site.
    Payload is an opaque dict (rail-specific).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rail_id: RailId
    fired: bool
    severity: RailSeverity
    action: RailAction
    payload: dict[str, Any]
    message: str


class RailDecision(BaseModel):
    """Composite result of one full ``check_all_rails`` call.

    Controllers route on ``composite_action`` — the highest-priority
    action across all fired rails. ``allow_*`` flags are True unless a
    corresponding BLOCK / REFUSE rail fired. ``request_kill`` is True iff
    any fired rail has ``action == REQUEST_KILL``.

    ``fired_rails`` is a tuple (not list) for immutability.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fired_rails: tuple[RailResult, ...] = ()
    composite_action: RailAction = RailAction.NONE
    allow_new_entry: bool = True
    allow_long_entry: bool = True
    allow_short_entry: bool = True
    request_kill: bool = False


def compose_decision(results: tuple[RailResult, ...]) -> RailDecision:
    """Build a ``RailDecision`` from every rail's result.

    Filters out ``fired=False`` results; picks composite action by
    ``_ACTION_PRIORITY``; sets ``allow_*`` flags based on which BLOCK /
    REFUSE rails fired; sets ``request_kill`` if any fired rail is
    REQUEST_KILL.
    """
    fired = tuple(r for r in results if r.fired)
    if not fired:
        return RailDecision(
            fired_rails=(),
            composite_action=RailAction.NONE,
            allow_new_entry=True,
            allow_long_entry=True,
            allow_short_entry=True,
            request_kill=False,
        )

    # Composite: highest-priority action among fired.
    top_action = max(fired, key=lambda r: action_priority(r.action)).action

    # Entry guards — ANY fired BLOCK_NEW_LONG disables longs; same for shorts.
    # REFUSE_ENTRY blocks all new entries; PAUSE_SLEEVE / CLOSE_ALL / REQUEST_KILL
    # also implicitly block new entries (controller enforces via _paused).
    actions = {r.action for r in fired}
    allow_long = not (
        RailAction.BLOCK_NEW_LONG in actions
        or RailAction.REFUSE_ENTRY in actions
    )
    allow_short = not (
        RailAction.BLOCK_NEW_SHORT in actions
        or RailAction.REFUSE_ENTRY in actions
    )
    allow_new = RailAction.REFUSE_ENTRY not in actions

    request_kill = RailAction.REQUEST_KILL in actions

    return RailDecision(
        fired_rails=fired,
        composite_action=top_action,
        allow_new_entry=allow_new,
        allow_long_entry=allow_long,
        allow_short_entry=allow_short,
        request_kill=request_kill,
    )


__all__ = [
    "RailAction",
    "RailDecision",
    "RailId",
    "RailResult",
    "RailSeverity",
    "action_priority",
    "compose_decision",
]
