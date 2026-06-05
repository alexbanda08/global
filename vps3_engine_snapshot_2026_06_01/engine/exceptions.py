"""Phase 18 SAFE-TRDR-01 hard-enforcement exceptions (CLAUDE.md inv #11).

These exceptions are raised by ``backend.app.engine.trader_writes`` BEFORE
any DB write when an agent-issued tool call violates a SAFE-TRDR-01 rule.
Per CLAUDE.md inv #11 the "Never allowed" rule set is enforced here at
the code level — NOT in agent prompts.

Hierarchy::

    SafeTrdrViolation
    ├── TierEscalationForbidden       — set_tier('AGGRESSIVE')          (CONTEXT D-03)
    ├── OutsideSleeveManifest         — sleeve_id not in ALLOWED_SLEEVES (CONTEXT D-04)
    ├── OrderPlacementForbidden       — defense-in-depth on order tools  (SAFE-TRDR-01)
    ├── RailMutationForbidden         — defense-in-depth on rail tools   (SAFE-TRDR-01)
    └── RateLimitExceeded             — 10/24h enable+disable, 3/hr enable (CONTEXT 2.3)
"""
from __future__ import annotations


class SafeTrdrViolation(Exception):  # noqa: N818 — domain term "Violation" is the audit-log noun used in CONTEXT/PITFALLS.
    """Base for all SAFE-TRDR-01 hard-rule violations.

    Catch this if you want to handle every trader-write violation
    uniformly (e.g., for alerting). Per-rule subclasses below let
    callers branch on specific violation types.
    """


class TierEscalationForbidden(SafeTrdrViolation):
    """Raised when trader attempts ``set_tier('AGGRESSIVE')`` (CONTEXT D-03).

    AGGRESSIVE tier is code-locked in v0.1; operator-driven config
    migration is required to unlock it. The Pydantic ``Literal``
    enum on ``SetTierArgs`` rejects the value at parse time too —
    this exception is the second line of defense.
    """


class OutsideSleeveManifest(SafeTrdrViolation):
    """Raised when trader targets a ``sleeve_id`` not in ``ALLOWED_SLEEVES``.

    Per CONTEXT D-04 the wk1 sleeve manifest is fixed: 5 HL USER sleeves
    + 1 XSM sleeve. Any other sleeve_id (typos, hallucinations, prompt
    injection) is rejected before the audit row is written.
    """


class OrderPlacementForbidden(SafeTrdrViolation):
    """Raised if a trader tool somehow tries to call into the venue order path.

    SAFE-TRDR-01 forbids the trader from placing orders directly. The
    primary defense is that ``TRADER_TOOLS`` does NOT expose any order
    tools at all — this exception is reserved for defense-in-depth
    paths that may be added if a code review surfaces a leak.
    """


class RailMutationForbidden(SafeTrdrViolation):
    """Raised if a trader tool attempts to mutate engine.risk_guardrails thresholds.

    SAFE-TRDR-01 forbids the trader from touching risk-rail config.
    Same posture as ``OrderPlacementForbidden``: primary defense is
    surface-area minimization in ``TRADER_TOOLS``.
    """


class RateLimitExceeded(SafeTrdrViolation):
    """Raised when 24h or 1h rate caps are reached.

    Per CONTEXT 2.3 hard caps:

    * ``enable_strategy`` + ``disable_strategy`` combined: ≤10 in any
      rolling 24h window.
    * ``enable_strategy`` alone: ≤3 in any rolling 1h window.

    Counted from rows already in ``trading.supervisor_audit`` for the
    same ``mode`` (shadow caps and live caps tracked separately so a
    chatty shadow week doesn't lock out the operator at Day 8 cutover).
    """
