"""Phase 18 trader-write queue + apply (TRDR-01..06; SAFE-TRDR-01).

Two functions live here:

1. ``queue_trader_write`` — agent-callable choke-point. Validates
   SAFE-TRDR-01 hard rules **at the code level** (CLAUDE.md inv #11)
   BEFORE any DB write. On pass, redacts ``justification`` +
   ``prompt_response`` via :pyfunc:`redact_for_agent_context`
   (CLAUDE.md inv #9 + PITFALLS row 12) and INSERTs a row into
   ``trading.supervisor_audit``.

2. ``apply_pending_trader_writes`` — invoked by the BarEngine on each
   bar wake (BEFORE strategy evaluation — CLAUDE.md inv #12 race
   protection). Pulls live (NOT shadow) audit rows whose
   ``requested_at <= bar_boundary_ts``, dispatches to per-tool
   handlers, stamps ``applied_at``. Per-row failures are recorded in
   the row's ``error`` column but do not abort the loop.

Mode handling (CONTEXT D-04 + D-05):

* ``mode='shadow'`` rows accumulate during the 7-day shadow window.
  They are FROZEN — the apply query filters ``WHERE mode='live'`` so
  shadow rows are never selected. Day-8 cutover is clean: trader
  starts emitting fresh ``mode='live'`` rows.
* ``mode='live'`` rows are pulled with ``FOR UPDATE SKIP LOCKED`` so
  multiple BarEngine wake calls in flight (race during a bar boundary
  cluster) do not double-apply.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal

import asyncpg

from backend.app.engine.exceptions import (
    OutsideSleeveManifest,
    RateLimitExceeded,
    TierEscalationForbidden,
)
from backend.app.services.redact_for_display import redact_for_agent_context

# Re-export for SAFE-TRDR-01 tests. The tests assert on
# ``backend.app.engine.trader_writes.TRADER_TOOLS`` and
# ``SUPERVISOR_TOOLS`` directly to keep their imports flat.
from backend.app.supervisor.tools.supervisor import SUPERVISOR_TOOLS  # noqa: F401
from backend.app.supervisor.tools.trader import (
    _TRADER_ARG_MODELS,
    TRADER_TOOLS,
)

__all__ = [
    "ALLOWED_SLEEVES",
    "OutsideSleeveManifest",
    "RateLimitExceeded",
    "SUPERVISOR_TOOLS",
    "TRADER_TOOLS",
    "TierEscalationForbidden",
    "apply_pending_trader_writes",
    "queue_trader_write",
]


log = logging.getLogger(__name__)


# Per CONTEXT D-04 wk1 sizing — manifest of pre-approved sleeve_ids.
# Frozen so a runaway agent cannot mutate it via attribute assignment.
ALLOWED_SLEEVES: frozenset[str] = frozenset(
    {
        "USER-DOGE",
        "USER-ETH",
        "USER-SOL",
        "USER-LINK",
        "USER-AVAX",
        "XSM",
    }
)


# ---------------------------------------------------------------------------
# queue_trader_write — agent-callable; runs SAFE-TRDR-01 hard checks.
# ---------------------------------------------------------------------------


async def queue_trader_write(
    *,
    pool: asyncpg.Pool,
    tool_name: str,
    args: dict[str, Any],
    justification: str,
    prompt_response: dict[str, Any] | None,
    mode: Literal["shadow", "live"],
) -> str:
    """Validate SAFE-TRDR-01 hard rules, redact, then INSERT a supervisor_audit row.

    Returns the inserted row's UUID (as a string).

    Validation order (fail fast — DB write is the LAST step):

    1. Tool name must be in ``_TRADER_ARG_MODELS`` (whitelist).
    2. Pydantic model parses args (raises ``ValidationError``).
    3. ``set_tier(AGGRESSIVE)`` → ``TierEscalationForbidden`` (defense-in-depth;
       Pydantic ``Literal`` already rejects, but a forged dict could route here).
    4. ``sleeve_id`` (if present) must be in ``ALLOWED_SLEEVES``.
    5. Multiplier / fraction range re-asserted (defense-in-depth).
    6. Rate caps enforced for enable/disable (10/24h combined; 3/h enable).
    7. Redact ``justification`` + ``prompt_response`` string fields.
    8. INSERT.

    All raises happen BEFORE the INSERT so a violation never leaves a
    partial row behind. Caller may catch ``SafeTrdrViolation`` for a
    uniform error path (alerting, retry-policy decisions).
    """
    # 1. Whitelist tool name.
    if tool_name not in _TRADER_ARG_MODELS:
        raise ValueError(f"unknown trader tool: {tool_name!r}")

    # 2. Pydantic validation. Raises ``ValidationError`` on type / range / regex.
    Model = _TRADER_ARG_MODELS[tool_name]  # noqa: N806 — Pydantic class assignment.
    parsed = Model(**args)

    # 3. AGGRESSIVE tier code-lock (CONTEXT D-03 + CLAUDE.md inv #11).
    if tool_name == "set_tier":
        # parsed.tier is Literal["SAFE","BALANCED"] in normal flow; defense-in-depth
        # against a bypass that constructed the model from a forged dict.
        tier_value = getattr(parsed, "tier", None)
        if tier_value == "AGGRESSIVE":
            raise TierEscalationForbidden(
                "AGGRESSIVE tier code-locked in v0.1; operator migration required (CONTEXT D-03)"
            )

    # 4. Sleeve manifest whitelist (CONTEXT D-04).
    sleeve = getattr(parsed, "sleeve_id", None)
    if sleeve is not None and sleeve not in ALLOWED_SLEEVES:
        raise OutsideSleeveManifest(
            f"sleeve {sleeve!r} not in pre-approved manifest {sorted(ALLOWED_SLEEVES)}"
        )

    # 5. Range re-assertions (defense-in-depth — Pydantic ``Field(ge=, le=)``
    #    already enforces; an attacker who bypasses parsing would be caught
    #    here. Cheap to keep.).
    if tool_name == "adjust_sleeve_leverage":
        m = getattr(parsed, "multiplier", None)
        if m is None or not (0.25 <= m <= 1.0):
            raise ValueError(f"multiplier {m!r} outside [0.25, 1.0]")
    if tool_name == "adjust_risk_per_trade":
        f_ = getattr(parsed, "fraction", None)
        if f_ is None or not (0.25 <= f_ <= 1.0):
            raise ValueError(f"fraction {f_!r} outside [0.25, 1.0]")

    # 6. Rate caps (CONTEXT 2.3 hard limits).
    #
    #    Counted per ``mode`` so a chatty shadow week doesn't lock out the
    #    operator at Day 8 cutover (live cap starts at 0). ``requested_at``
    #    interval is computed by the DB so freezegun-based tests still work
    #    when they freeze ``datetime.now()`` in Python land — ``now()`` here
    #    is the Postgres ``now()`` which freezegun does NOT touch.
    if tool_name in ("enable_strategy", "disable_strategy"):
        async with pool.acquire() as conn:
            day_count = await conn.fetchval(
                """SELECT count(*) FROM trading.supervisor_audit
                   WHERE role = 'trader'
                     AND tool_name IN ('enable_strategy', 'disable_strategy')
                     AND mode = $1
                     AND requested_at >= now() - interval '24 hours'""",
                mode,
            )
            if day_count >= 10:
                raise RateLimitExceeded(
                    f"{tool_name}: 10/24h cap reached (count={day_count})"
                )
            if tool_name == "enable_strategy":
                hour_count = await conn.fetchval(
                    """SELECT count(*) FROM trading.supervisor_audit
                       WHERE role = 'trader'
                         AND tool_name = 'enable_strategy'
                         AND mode = $1
                         AND requested_at >= now() - interval '1 hour'""",
                    mode,
                )
                if hour_count >= 3:
                    raise RateLimitExceeded(
                        f"enable_strategy: 3/hour cap reached (count={hour_count})"
                    )

    # 7. Redact free-text fields (CLAUDE.md inv #9 — choke-point for agent re-ingestion).
    redacted_just = redact_for_agent_context(justification)
    redacted_pr: dict[str, Any] | None = None
    if prompt_response is not None:
        redacted_pr = {
            k: redact_for_agent_context(v) if isinstance(v, str) else v
            for k, v in prompt_response.items()
        }

    # 8. INSERT. Parameterized — no SQL injection surface.
    async with pool.acquire() as conn:
        row_id = await conn.fetchval(
            """INSERT INTO trading.supervisor_audit
                 (role, tool_name, args, mode, justification, prompt_response)
               VALUES ('trader', $1, $2::jsonb, $3, $4, $5::jsonb)
               RETURNING id""",
            tool_name,
            json.dumps(args),
            mode,
            redacted_just,
            json.dumps(redacted_pr) if redacted_pr is not None else None,
        )
    return str(row_id)


# ---------------------------------------------------------------------------
# Per-tool handlers — invoked by ``apply_pending_trader_writes``.
# ---------------------------------------------------------------------------
#
# Handlers run inside the apply transaction. They MUST be idempotent or
# recoverable — a handler exception is caught, logged, and persisted to
# the audit row's ``error`` column; ``applied_at`` is still stamped so
# the row is not retried on the next bar (CONTEXT D-04 — single-table
# audit log + queue; the operator reviews ``error`` rows in the UI).
#
# Plan 18-02 lands the SAFETY-CRITICAL choke-point (queue) + the
# APPLY skeleton; per-tool *side-effect tables* (engine.tier_state,
# trading.bots.status, etc.) are wired in plan 18-04 / future. Today's
# handlers write a ``trading.events`` audit row capturing the apply so
# the engine layer can listen via PG LISTEN once side-effect tables
# land — and so the apply transaction commits cleanly with a
# greppable record of every applied write.


async def _emit_apply_event(
    conn: asyncpg.Connection,
    *,
    tool_name: str,
    args_json: str,
) -> None:
    """Write a ``trading.events`` row capturing one applied trader write.

    Best-effort — caller's transaction owns the commit. The kind
    ``trader_write_applied`` is the canonical audit signal; a downstream
    listener (Plan 18-04+) can subscribe via PG LISTEN to fan changes
    into engine.tier_state, trading.bots, etc.
    """
    await conn.execute(
        "INSERT INTO trading.events (at, kind, data) "
        "VALUES (now(), 'trader_write_applied', $1::jsonb)",
        json.dumps({"tool": tool_name, "args": json.loads(args_json)}),
    )


async def _h_enable_strategy(
    conn: asyncpg.Connection, *, sleeve_id: str, reason: str
) -> None:
    """Re-enable a sleeve. Records the apply via ``trading.events``.

    Side-effect table wiring (e.g., ``trading.bots`` status flip) lands in
    Plan 18-04 once the bots table schema is finalized. For now we record
    the applied event so the operator UI can show "enable_strategy
    applied at <bar_boundary>" without inventing a column.
    """
    await _emit_apply_event(
        conn,
        tool_name="enable_strategy",
        args_json=json.dumps({"sleeve_id": sleeve_id, "reason": reason[:200]}),
    )


async def _h_disable_strategy(
    conn: asyncpg.Connection, *, sleeve_id: str, reason: str
) -> None:
    """Pause a sleeve. Records the apply via ``trading.events`` (Plan 18-04 wires bots)."""
    await _emit_apply_event(
        conn,
        tool_name="disable_strategy",
        args_json=json.dumps({"sleeve_id": sleeve_id, "reason": reason[:200]}),
    )


async def _h_set_tier(conn: asyncpg.Connection, *, tier: str, reason: str) -> None:
    """Switch tier. Defense-in-depth: AGGRESSIVE rejected here too.

    The queue rejects AGGRESSIVE before INSERT (TierEscalationForbidden),
    but if a forged audit row reached the apply layer (DB tampering) we
    re-validate. ``operator_note`` on supervisor_config records the
    change for operator review; the actual engine tier flag flow lands
    in plan 18-04 via ``engine.tier_state``.
    """
    if tier == "AGGRESSIVE":
        raise TierEscalationForbidden("AGGRESSIVE blocked at apply time (defense-in-depth)")
    await conn.execute(
        "UPDATE trading.supervisor_config "
        "SET operator_note = $1, last_updated_at = now(), last_updated_by = 'trader' "
        "WHERE id = 1",
        f"tier set to {tier} by trader: {reason[:160]}",
    )
    await _emit_apply_event(
        conn,
        tool_name="set_tier",
        args_json=json.dumps({"tier": tier, "reason": reason[:200]}),
    )


async def _h_adjust_sleeve_leverage(
    conn: asyncpg.Connection,
    *,
    sleeve_id: str,
    multiplier: float,
    reason: str,
) -> None:
    """Scale a sleeve's leverage. Defense-in-depth range re-check; records via events."""
    if not (0.25 <= multiplier <= 1.0):
        raise ValueError(f"defense-in-depth: multiplier {multiplier} out of range")
    await _emit_apply_event(
        conn,
        tool_name="adjust_sleeve_leverage",
        args_json=json.dumps(
            {"sleeve_id": sleeve_id, "multiplier": multiplier, "reason": reason[:200]}
        ),
    )


async def _h_adjust_risk_per_trade(
    conn: asyncpg.Connection,
    *,
    sleeve_id: str,
    fraction: float,
    reason: str,
) -> None:
    """Scale a sleeve's risk-per-trade. Defense-in-depth range re-check."""
    if not (0.25 <= fraction <= 1.0):
        raise ValueError(f"defense-in-depth: fraction {fraction} out of range")
    await _emit_apply_event(
        conn,
        tool_name="adjust_risk_per_trade",
        args_json=json.dumps(
            {"sleeve_id": sleeve_id, "fraction": fraction, "reason": reason[:200]}
        ),
    )


_HANDLERS = {
    "enable_strategy": _h_enable_strategy,
    "disable_strategy": _h_disable_strategy,
    "set_tier": _h_set_tier,
    "adjust_sleeve_leverage": _h_adjust_sleeve_leverage,
    "adjust_risk_per_trade": _h_adjust_risk_per_trade,
}


# ---------------------------------------------------------------------------
# apply_pending_trader_writes — BarEngine bar-wake hook (CLAUDE.md inv #12).
# ---------------------------------------------------------------------------


async def apply_pending_trader_writes(
    pool: asyncpg.Pool,
    bar_boundary_ts: datetime,
) -> int:
    """Apply queued live trader-writes whose ``requested_at <= bar_boundary_ts``.

    Returns: count of rows attempted (regardless of per-row success/failure).

    Caller contract — CLAUDE.md inv #12: the BarEngine MUST call this
    BEFORE strategy evaluation on each wake. A trader write that lands
    mid-bar has ``applied_at`` stamped at the NEXT bar boundary (not at
    ``requested_at``). The mid-bar race test in
    ``backend/tests/security/test_trader_constraints.py`` pins this.

    Shadow rows are FROZEN (CONTEXT D-05): the SELECT filters
    ``WHERE mode = 'live'``. Shadow rows therefore stay forever
    ``applied_at IS NULL`` and are never selected here.

    Per-row failure handling: a handler exception does NOT abort the
    loop. The exception's repr is persisted to the row's ``error``
    column and ``applied_at`` is stamped — the row is consumed and not
    retried on the next bar. Operator reviews error rows via the UI.

    Concurrency: ``FOR UPDATE SKIP LOCKED`` — multiple BarEngine wake
    calls in flight (during a bar-boundary cluster) cannot double-apply.
    """
    attempted = 0
    async with pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            """SELECT id, role, tool_name, args
                   FROM trading.supervisor_audit
                   WHERE mode = 'live'
                     AND applied_at IS NULL
                     AND requested_at <= $1
                   ORDER BY requested_at
                   FOR UPDATE SKIP LOCKED""",
            bar_boundary_ts,
        )
        for row in rows:
            attempted += 1
            tool_name = row["tool_name"]
            raw_args = row["args"]
            args = (
                json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            )
            try:
                handler = _HANDLERS.get(tool_name)
                if handler is None:
                    raise ValueError(f"no handler for trader tool {tool_name!r}")
                await handler(conn, **args)
                await conn.execute(
                    "UPDATE trading.supervisor_audit SET applied_at = now() WHERE id = $1",
                    row["id"],
                )
            except Exception as e:  # noqa: BLE001 — per-row isolation; loop must continue.
                log.exception(
                    "trader_writes.apply_failed",
                    extra={
                        "event": "trader_writes.apply_failed",
                        "row_id": str(row["id"]),
                        "tool_name": tool_name,
                    },
                )
                await conn.execute(
                    "UPDATE trading.supervisor_audit "
                    "SET applied_at = now(), error = $1 WHERE id = $2",
                    repr(e)[:1000],
                    row["id"],
                )
    return attempted
