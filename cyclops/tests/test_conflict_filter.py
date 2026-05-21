"""Exhaustive tests for the conflict filter.

27 possible (trend, levels, momentum) vote tuples ∈ {-1, 0, +1}^3.
We assert the outcome of every tuple — this filter is small enough that
exhaustive coverage costs nothing and protects against subtle off-by-one
bugs in pos/neg/abst counting.
"""

from __future__ import annotations

import itertools

import pytest

from cyclops.conventions import ABSTAIN_LIMIT
from cyclops.filters.conflict import apply_conflict_filter


# ---------------------------------------------------------------------------
# Coherent fires
# ---------------------------------------------------------------------------

def test_all_three_up_fires_up():
    fire, direction, reason = apply_conflict_filter(1, 1, 1)
    assert fire is True
    assert direction == "Up"
    assert reason == "coherent"


def test_all_three_down_fires_down():
    fire, direction, reason = apply_conflict_filter(-1, -1, -1)
    assert fire is True
    assert direction == "Down"
    assert reason == "coherent"


def test_two_up_one_abstain_fires_up():
    fire, direction, reason = apply_conflict_filter(1, 1, 0)
    assert fire is True
    assert direction == "Up"
    assert reason == "coherent"


def test_two_down_one_abstain_fires_down():
    fire, direction, reason = apply_conflict_filter(-1, 0, -1)
    assert fire is True
    assert direction == "Down"
    assert reason == "coherent"


# ---------------------------------------------------------------------------
# Conflict skips (pos and neg both present)
# ---------------------------------------------------------------------------

def test_one_up_one_down_one_abstain_is_conflict():
    fire, direction, reason = apply_conflict_filter(1, -1, 0)
    assert fire is False
    assert direction is None
    assert "conflict" in reason


def test_two_up_one_down_is_conflict():
    fire, direction, reason = apply_conflict_filter(1, 1, -1)
    assert fire is False
    assert direction is None
    assert reason == "conflict_pos2_neg1"


def test_two_down_one_up_is_conflict():
    fire, direction, reason = apply_conflict_filter(-1, -1, 1)
    assert fire is False
    assert direction is None
    assert reason == "conflict_pos1_neg2"


# ---------------------------------------------------------------------------
# Abstention skips
# ---------------------------------------------------------------------------

def test_two_abstain_one_up_skips_abstention():
    fire, direction, reason = apply_conflict_filter(1, 0, 0)
    assert fire is False
    assert direction is None
    assert reason == f"abstention_{ABSTAIN_LIMIT}"


def test_all_abstain_skips_abstention():
    fire, direction, reason = apply_conflict_filter(0, 0, 0)
    assert fire is False
    assert direction is None
    assert reason == "abstention_3"


def test_two_abstain_one_down_skips_abstention():
    fire, direction, reason = apply_conflict_filter(0, -1, 0)
    assert fire is False
    assert direction is None
    assert reason == f"abstention_{ABSTAIN_LIMIT}"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def test_invalid_vote_raises():
    with pytest.raises(ValueError):
        apply_conflict_filter(2, 0, 0)
    with pytest.raises(ValueError):
        apply_conflict_filter(0, -2, 0)


# ---------------------------------------------------------------------------
# Exhaustive enumeration over all 27 tuples
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("votes", list(itertools.product((-1, 0, 1), repeat=3)))
def test_exhaustive_truth_table(votes):
    pos = sum(1 for v in votes if v > 0)
    neg = sum(1 for v in votes if v < 0)
    abst = sum(1 for v in votes if v == 0)

    fire, direction, _reason = apply_conflict_filter(*votes)

    if pos > 0 and neg > 0:
        assert fire is False and direction is None
    elif abst >= ABSTAIN_LIMIT:
        assert fire is False and direction is None
    else:
        assert fire is True
        if pos >= 1:
            assert direction == "Up"
        else:
            assert direction == "Down"


# ---------------------------------------------------------------------------
# require_momentum_abstain ablation branch
# ---------------------------------------------------------------------------

def test_momentum_engaged_skips_when_required_to_abstain():
    fire, direction, reason = apply_conflict_filter(
        1, 1, 1, require_momentum_abstain=True
    )
    assert fire is False
    assert direction is None
    assert reason == "momentum_engaged"


def test_two_axis_coherent_up_fires_when_momentum_abstains():
    fire, direction, reason = apply_conflict_filter(
        1, 1, 0, require_momentum_abstain=True
    )
    assert fire is True
    assert direction == "Up"
    assert reason == "coherent_2of2"


def test_two_axis_coherent_down_fires_when_momentum_abstains():
    fire, direction, reason = apply_conflict_filter(
        -1, -1, 0, require_momentum_abstain=True
    )
    assert fire is True
    assert direction == "Down"
    assert reason == "coherent_2of2"


def test_one_axis_abstaining_skips_in_2of2_mode():
    fire, direction, reason = apply_conflict_filter(
        1, 0, 0, require_momentum_abstain=True
    )
    assert fire is False
    assert direction is None
    assert "abstention" in reason


def test_trend_levels_conflict_skips_in_2of2_mode():
    fire, direction, reason = apply_conflict_filter(
        1, -1, 0, require_momentum_abstain=True
    )
    assert fire is False
    assert direction is None
    assert "conflict" in reason


@pytest.mark.parametrize("votes", list(itertools.product((-1, 0, 1), repeat=3)))
def test_exhaustive_truth_table_with_momentum_abstain_required(votes):
    trend_v, levels_v, momentum_v = votes
    fire, direction, _reason = apply_conflict_filter(
        *votes, require_momentum_abstain=True
    )
    if momentum_v != 0:
        assert fire is False
        return
    pair_pos = (trend_v > 0) + (levels_v > 0)
    pair_neg = (trend_v < 0) + (levels_v < 0)
    pair_abs = (trend_v == 0) + (levels_v == 0)
    if pair_pos > 0 and pair_neg > 0:
        assert fire is False
    elif pair_abs >= 1:
        assert fire is False
    else:
        assert fire is True
        assert direction == ("Up" if pair_pos >= 1 else "Down")
