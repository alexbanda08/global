"""Tier classifier — combines layer scores + guard blocks into a tier decision.

Mapping per Cyclops spec (TRADINGVENUE_VS_CYCLOPS_2026_05_06.md §2):
  GOLD   = STRUCTURE + FLOW + TRIGGER aligned, both scores >= 0.50  → fair_prob 0.72, size 2.0%
  SILVER = STRUCTURE + FLOW aligned, struct >= 0.30, flow >= 0.40  → fair_prob 0.64, size 1.5%
  BRONZE = FLOW + TRIGGER aligned, flow >= 0.40                    → fair_prob 0.54, size 1.0%
  SKIP   = anything else, OR any guard block fired

Phase 0: this is the canonical version — Phases 1-4 only need to populate the
inputs (structure_score, flow_score, trigger_active, guard_blocks). Logic stays
fixed unless G3 (tier separation) gate fails in Phase 5.
"""
from __future__ import annotations

from typing import Iterable

from strategy_lab.confluence.schema import SKIP, TierResult


# Threshold constants — tuned in Phase 5 (G3 gate); current values from Cyclops doc
GOLD_STRUCT_MIN  = 0.50
GOLD_FLOW_MIN    = 0.50
SILVER_STRUCT_MIN = 0.30
SILVER_FLOW_MIN  = 0.40
BRONZE_FLOW_MIN  = 0.40

GOLD_FAIR_PROB   = 0.72
SILVER_FAIR_PROB = 0.64
BRONZE_FAIR_PROB = 0.54

GOLD_SIZE_PCT    = 0.020
SILVER_SIZE_PCT  = 0.015
BRONZE_SIZE_PCT  = 0.010


def classify(
    structure_score: float | None,
    flow_score: float | None,
    trigger_active: bool | None,
    guard_blocks: Iterable[str] = (),
) -> TierResult:
    """Return the tier decision dict.

    Args:
      structure_score: STRUCTURE composite in [-1, +1]; None if STRUCTURE module
                       not yet built (Phase 0 → always None → all SKIP).
      flow_score:      FLOW composite in [-1, +1]; sign indicates direction.
      trigger_active:  bool from TRIGGER module; True = trigger fired.
      guard_blocks:    iterable of guard names that blocked this trade.

    Returns: TierResult dict (see schema.py).
    """
    # Hard guard wins — even GOLD-eligible trades skip if a guard fires.
    blocks = tuple(guard_blocks)
    if blocks:
        return {
            "tier": "SKIP",
            "fair_prob": None,
            "size_pct": 0.0,
            "skip_reasons": blocks,
        }

    # Missing-feature SKIP — Phase 0 lands here for everything.
    if structure_score is None or flow_score is None or trigger_active is None:
        return {
            "tier": "SKIP",
            "fair_prob": None,
            "size_pct": 0.0,
            "skip_reasons": ("missing_features",),
        }

    s_align = structure_score >= SILVER_STRUCT_MIN
    f_align = flow_score >= SILVER_FLOW_MIN
    t_active = bool(trigger_active)

    # GOLD: all three layers aligned with high confidence
    if (s_align and f_align and t_active
            and structure_score >= GOLD_STRUCT_MIN
            and flow_score >= GOLD_FLOW_MIN):
        return {
            "tier": "GOLD",
            "fair_prob": GOLD_FAIR_PROB,
            "size_pct": GOLD_SIZE_PCT,
            "skip_reasons": (),
        }

    # SILVER: STRUCTURE + FLOW aligned (no trigger required)
    if (s_align and f_align
            and structure_score >= SILVER_STRUCT_MIN
            and flow_score >= SILVER_FLOW_MIN):
        return {
            "tier": "SILVER",
            "fair_prob": SILVER_FAIR_PROB,
            "size_pct": SILVER_SIZE_PCT,
            "skip_reasons": (),
        }

    # BRONZE: FLOW + TRIGGER (no STRUCTURE required)
    if f_align and t_active and flow_score >= BRONZE_FLOW_MIN:
        return {
            "tier": "BRONZE",
            "fair_prob": BRONZE_FAIR_PROB,
            "size_pct": BRONZE_SIZE_PCT,
            "skip_reasons": (),
        }

    return SKIP


def stake_usd(tier_result: TierResult, bankroll_usd: float) -> float:
    """Convert tier decision to absolute USD stake.

    Bankroll comes from sleeve config; size_pct from tier. Final stake is
    further capped by dynamic-sizing logic (§5 of NEXT_SESSION_START_HERE)
    enforced in the simulator wrapper, not here.
    """
    return float(bankroll_usd) * float(tier_result.get("size_pct", 0.0))
