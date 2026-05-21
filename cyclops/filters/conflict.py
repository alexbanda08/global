"""The conflict filter — the heart of the Cyclops architecture.

Cyclops manifesto (May 11):
    "The new one asks three independent questions and measures how much
     they agree. Trend, Levels, Momentum. If they disagree too much, the
     trade is skipped. That is the entire fix."

Rules (spec §4.6, verbatim):
  1. Each vote ∈ {-1, 0, +1}.
  2. If at least one positive AND at least one negative → conflict, skip.
  3. If ABSTAIN_LIMIT or more abstentions → not enough info, skip.
  4. Otherwise → fire in the direction of the non-zero votes.

No averaging. No weighted sum. Twenty lines decide the trade.
"""

from __future__ import annotations

from typing import Tuple

from ..conventions import ABSTAIN_LIMIT


def apply_conflict_filter(
    trend_vote: int,
    levels_vote: int,
    momentum_vote: int,
    abstain_limit: int = ABSTAIN_LIMIT,
    require_momentum_abstain: bool = False,
) -> Tuple[bool, str | None, str]:
    """Return (should_fire, signal_dir, reason).

    signal_dir is "Up" / "Down" when firing, None when skipping.
    reason is a short string suitable for telemetry / per-skip counters.

    `require_momentum_abstain`:
        Forensic ablation from P2: when momentum agrees with trend+levels,
        the trade goes WORSE (3-of-3 WR=41% vs 2-of-3 (+1,+1,0) WR=53%
        on n=251). Setting this True demotes momentum to a hard veto:
        fire only when momentum abstains AND trend+levels are coherent.
        Two-axis coherence with no abstention required (since we're already
        down to 2 axes; allowing 1-of-2 abstentions would fire on a single
        weak vote).
    """
    votes = (trend_vote, levels_vote, momentum_vote)

    if not all(v in (-1, 0, 1) for v in votes):
        raise ValueError(f"votes must each be in {{-1, 0, +1}}, got {votes}")

    if require_momentum_abstain:
        if momentum_vote != 0:
            return False, None, "momentum_engaged"
        active = (trend_vote, levels_vote)
        pos = sum(1 for v in active if v > 0)
        neg = sum(1 for v in active if v < 0)
        abst = sum(1 for v in active if v == 0)
        if pos > 0 and neg > 0:
            return False, None, f"conflict_pos{pos}_neg{neg}"
        if abst >= 1:
            return False, None, f"abstention_{abst}_of_2"
        direction = "Up" if pos >= 1 else "Down"
        return True, direction, "coherent_2of2"

    pos = sum(1 for v in votes if v > 0)
    neg = sum(1 for v in votes if v < 0)
    abst = sum(1 for v in votes if v == 0)

    if pos > 0 and neg > 0:
        return False, None, f"conflict_pos{pos}_neg{neg}"
    if abst >= abstain_limit:
        return False, None, f"abstention_{abst}"

    direction = "Up" if pos >= 1 else "Down"
    return True, direction, "coherent"
