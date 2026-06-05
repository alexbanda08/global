"""Top-level rails orchestrator (Phase 10 · Task 1 · RAIL-01..13).

This is the single integration point controllers use to evaluate all
applicable rails for a given scope. Individual rail pure functions live
under ``backend.app.engine.rails.rail_NN_*``; this module composes their
results into a ``RailDecision``.

Design (10-CONTEXT D-01 / D-12):

* ``RailContext`` carries every input every rail needs. Controllers
  build it from DB reads + in-memory state BEFORE calling
  ``check_all_rails``.
* ``check_all_rails(context, scope)`` dispatches on scope:

  - ``per_bar_sleeve`` — Rails 1, 2, 6, 8 (per-sleeve).
  - ``per_bar_portfolio`` — Rails 3, 4, 5, 9, 11a, 11b (portfolio).
  - ``pre_dispatch_engine`` — Rail 7 only (BarEngine pre-dispatch).

* Abs-$ thresholds come from env vars (see
  ``load_abs_dollar_thresholds``). Defaults: $5000 warn, $15000 kill.

**CLAUDE.md §7 invariant**: this module and every rail under
``backend.app.engine.rails`` must NOT contain a ``def kill(`` or
``async def kill(`` method. Rails REQUEST kill via
``RailAction.REQUEST_KILL``; the orchestrator / controllers write a
``trading.events(kind='kill_switch_requested')`` row that Phase 12's
consumer routes to the kill path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from backend.app.engine.rails.framework import (
    RailDecision,
    RailResult,
    compose_decision,
)
from backend.app.engine.rails.rail_01_per_position_sl import rail_01_per_position_sl
from backend.app.engine.rails.rail_02_sleeve_24h_dd import rail_02_sleeve_24h_dd
from backend.app.engine.rails.rail_03_portfolio_dd_15 import rail_03_portfolio_dd_15
from backend.app.engine.rails.rail_04_portfolio_dd_25 import rail_04_portfolio_dd_25
from backend.app.engine.rails.rail_05_portfolio_dd_30_kill import (
    rail_05_portfolio_dd_30_kill,
)
from backend.app.engine.rails.rail_06_funding_spike import rail_06_funding_spike
from backend.app.engine.rails.rail_07_exchange_outage import rail_07_exchange_outage
from backend.app.engine.rails.rail_08_concentration import rail_08_concentration
from backend.app.engine.rails.rail_09_correlation_kill import rail_09_correlation_kill
from backend.app.engine.rails.rail_11_abs_day_loss import (
    rail_11a_abs_day_loss_warn,
    rail_11b_abs_day_loss_kill,
)

# --- Env-var names for abs-$ thresholds (RAIL-11). ---------------------
# Documented in docs/RISK_RAILS.md; defaults are conservative for v0.1 at
# $100k equity. Operator can override per environment.
ENV_ABS_DAY_LOSS_WARN_USD = "RAIL_ABS_DAY_LOSS_WARN_USD"
ENV_ABS_DAY_LOSS_KILL_USD = "RAIL_ABS_DAY_LOSS_KILL_USD"

DEFAULT_ABS_DAY_LOSS_WARN_USD = Decimal("5000")
DEFAULT_ABS_DAY_LOSS_KILL_USD = Decimal("15000")


def load_abs_dollar_thresholds() -> tuple[Decimal, Decimal]:
    """Read abs-$ rail thresholds from env (RAIL-11 / 10-CONTEXT D-11).

    Returns ``(warn_usd, kill_usd)``. Env vars:

    * ``RAIL_ABS_DAY_LOSS_WARN_USD`` (default 5000)
    * ``RAIL_ABS_DAY_LOSS_KILL_USD`` (default 15000)

    Invalid / non-parseable values fall back to defaults (logged upstream
    when the controller constructs the context).
    """

    def _parse(name: str, default: Decimal) -> Decimal:
        raw = os.environ.get(name)
        if raw is None or raw.strip() == "":
            return default
        try:
            return Decimal(raw)
        except Exception:  # noqa: BLE001 — defensive env parse
            return default

    warn = _parse(ENV_ABS_DAY_LOSS_WARN_USD, DEFAULT_ABS_DAY_LOSS_WARN_USD)
    kill = _parse(ENV_ABS_DAY_LOSS_KILL_USD, DEFAULT_ABS_DAY_LOSS_KILL_USD)
    return warn, kill


@dataclass(frozen=True)
class RailContext:
    """Immutable input bundle for one ``check_all_rails`` call.

    Controllers populate this from DB reads + in-memory state BEFORE
    calling the orchestrator. Every rail reads only what it needs; the
    orchestrator routes by ``scope``.

    Attributes
    ----------
    portfolio_equity_snapshots_24h:
        Last 24h of portfolio-scope snapshots (oldest-first). Used by
        Rails 3/4/5 (DD ladder) + Rails 11a/11b (abs-$).
    sleeve_equity_snapshots_24h:
        Map of ``sleeve_id -> list[EquitySnapshot]`` (oldest-first). Used
        by Rail 2. For ``per_bar_sleeve`` scope, usually contains one key
        (the current sleeve).
    open_positions:
        List of open ``Position``-like rows across all sleeves. Used by
        Rails 1 + 8.
    portfolio_equity_usd:
        Current aggregate equity — denominator for Rail 8 concentration.
    funding_rates_by_coin:
        Map of ``coin -> 8h funding rate`` (Decimal). Used by Rail 6.
        Missing keys mean no spike data → Rail 6 returns fired=False.
    last_tick_at:
        Most-recent collector tick timestamp. Used by Rail 7.
    recent_sleeve_dd_firings_24h:
        Event rows with ``kind='rail_fired'`` and
        ``data.rail_id='rail_02_sleeve_24h_dd'`` in the last 24h. Used
        by Rail 9.
    current_mark_px_by_symbol:
        Mark price per symbol for Rail 8 notional aggregation.
    abs_warn_threshold_usd / abs_kill_threshold_usd:
        Abs-$ thresholds (RAIL-11). Loaded via ``load_abs_dollar_thresholds``.
    now:
        Reference "now" datetime. Usually ``bars[-1].close_time`` — avoids
        wall-clock drift in tests.
    current_sleeve_id:
        For ``per_bar_sleeve`` scope, the sleeve being evaluated. None
        for other scopes.
    last_bar:
        Last closed bar for Rail 1 (per-position SL check). None for
        scopes where Rail 1 doesn't run.
    barrier_params_by_position_id:
        Strategy-level barriers (tp/sl/max_hold) keyed by position id.
        Used by Rail 1.
    trail_state_by_position_id:
        Trail state for each position. Used by Rail 1.
    """

    portfolio_equity_snapshots_24h: tuple[Any, ...] = ()
    sleeve_equity_snapshots_24h: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    open_positions: tuple[Any, ...] = ()
    portfolio_equity_usd: Decimal = Decimal("0")
    funding_rates_by_coin: dict[str, Decimal] = field(default_factory=dict)
    last_tick_at: datetime | None = None
    recent_sleeve_dd_firings_24h: tuple[dict[str, Any], ...] = ()
    current_mark_px_by_symbol: dict[str, Decimal] = field(default_factory=dict)
    abs_warn_threshold_usd: Decimal = DEFAULT_ABS_DAY_LOSS_WARN_USD
    abs_kill_threshold_usd: Decimal = DEFAULT_ABS_DAY_LOSS_KILL_USD
    now: datetime | None = None
    current_sleeve_id: str | None = None
    last_bar: Any = None
    barrier_params_by_position_id: dict[Any, Any] = field(default_factory=dict)
    trail_state_by_position_id: dict[Any, Any] = field(default_factory=dict)


Scope = Literal["per_bar_sleeve", "per_bar_portfolio", "pre_dispatch_engine"]


def check_all_rails(
    *,
    context: RailContext,
    scope: Scope,
) -> RailDecision:
    """Run every rail applicable to ``scope`` and compose the decision.

    * ``per_bar_sleeve``: Rails 1 (per-position SL audit), 2 (sleeve
      24h DD), 6 (funding spike), 8 (concentration).
    * ``per_bar_portfolio``: Rails 3/4/5 (portfolio DD ladder), 9
      (correlation), 11a/11b (abs-$).
    * ``pre_dispatch_engine``: Rail 7 only (BarEngine pre-dispatch).

    Returns a ``RailDecision`` with composite action + entry-allow flags.
    Individual results are in ``decision.fired_rails``; non-fired results
    are dropped.
    """
    results: list[RailResult] = []

    if scope == "pre_dispatch_engine":
        if context.last_tick_at is not None and context.now is not None:
            results.append(
                rail_07_exchange_outage(
                    last_tick_at=context.last_tick_at,
                    now=context.now,
                )
            )
    elif scope == "per_bar_sleeve":
        # Rail 1: per-position SL audit. Only meaningful when the sleeve
        # has open positions AND a last_bar + barrier params are supplied.
        if context.last_bar is not None:
            sleeve_id = context.current_sleeve_id
            for pos in context.open_positions:
                if sleeve_id is not None and getattr(pos, "sleeve_id", None) not in (
                    sleeve_id,
                    None,
                ):
                    continue
                params = context.barrier_params_by_position_id.get(pos.position_id)
                trail = context.trail_state_by_position_id.get(pos.position_id)
                if params is None or trail is None:
                    continue
                results.append(
                    rail_01_per_position_sl(
                        position=params,
                        last_bar=context.last_bar,
                        trail_state=trail,
                        now=context.now or datetime.utcnow(),
                    )
                )

        # Rail 2: per-sleeve 24h DD.
        if context.current_sleeve_id is not None:
            snaps = context.sleeve_equity_snapshots_24h.get(
                context.current_sleeve_id, ()
            )
            if snaps:
                results.append(
                    rail_02_sleeve_24h_dd(
                        sleeve_id=context.current_sleeve_id,
                        sleeve_equity_snapshots_24h=snaps,
                    )
                )

        # Rail 6: funding spike — one check per coin in the sleeve's
        # universe. Callers populate ``funding_rates_by_coin`` with
        # coins they want evaluated.
        for coin, rate in context.funding_rates_by_coin.items():
            results.append(
                rail_06_funding_spike(coin=coin, funding_rate_8h=rate)
            )

        # Rail 8: concentration per coin — aggregates across ALL sleeves.
        if context.portfolio_equity_usd > 0 and context.open_positions:
            results.append(
                rail_08_concentration(
                    open_positions=context.open_positions,
                    portfolio_equity_usd=context.portfolio_equity_usd,
                    current_mark_px_by_symbol=context.current_mark_px_by_symbol,
                )
            )

    elif scope == "per_bar_portfolio":
        # Portfolio DD ladder — Rails 3 → 4 → 5.
        if context.portfolio_equity_snapshots_24h:
            results.append(
                rail_03_portfolio_dd_15(
                    portfolio_equity_snapshots_24h=context.portfolio_equity_snapshots_24h,
                    now=context.now or datetime.utcnow(),
                )
            )
            results.append(
                rail_04_portfolio_dd_25(
                    portfolio_equity_snapshots_24h=context.portfolio_equity_snapshots_24h,
                    now=context.now or datetime.utcnow(),
                )
            )
            results.append(
                rail_05_portfolio_dd_30_kill(
                    portfolio_equity_snapshots_24h=context.portfolio_equity_snapshots_24h,
                )
            )
            # Abs-$ rails share the same snapshot bundle.
            results.append(
                rail_11a_abs_day_loss_warn(
                    equity_snapshots_24h=context.portfolio_equity_snapshots_24h,
                    threshold_usd=context.abs_warn_threshold_usd,
                )
            )
            results.append(
                rail_11b_abs_day_loss_kill(
                    equity_snapshots_24h=context.portfolio_equity_snapshots_24h,
                    threshold_usd=context.abs_kill_threshold_usd,
                )
            )

        # Rail 9: correlation kill — 3+ unique sleeves hitting Rail 2 in 24h.
        results.append(
            rail_09_correlation_kill(
                recent_sleeve_dd_firings_24h=context.recent_sleeve_dd_firings_24h,
            )
        )

    return compose_decision(tuple(results))


def rail_event_payload(result: RailResult) -> dict[str, Any]:
    """Shape the ``data`` column for a ``trading.events(kind='rail_fired')`` row.

    Normalized across every rail so the supervisor + operator can query
    a single schema. RAIL-12.
    """
    return {
        "rail_id": result.rail_id.value,
        "severity": result.severity.value,
        "action": result.action.value,
        "payload": result.payload,
        "message": result.message,
    }


__all__ = [
    "DEFAULT_ABS_DAY_LOSS_KILL_USD",
    "DEFAULT_ABS_DAY_LOSS_WARN_USD",
    "ENV_ABS_DAY_LOSS_KILL_USD",
    "ENV_ABS_DAY_LOSS_WARN_USD",
    "RailContext",
    "Scope",
    "check_all_rails",
    "load_abs_dollar_thresholds",
    "rail_event_payload",
]
