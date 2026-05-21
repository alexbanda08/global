"""Sanity tests for the conventions module.

These are not strategy tests — they only verify that the constants we
encoded match the spec §4.1, that paths resolve, and that derived
relationships (e.g. ws_s arithmetic) are self-consistent.
"""

from __future__ import annotations

import pytest

from cyclops import conventions as C


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def test_root_exists():
    assert C.ROOT.exists(), f"ROOT path does not exist: {C.ROOT}"

def test_canonical_exists():
    assert C.CANONICAL.exists(), f"CANONICAL path does not exist: {C.CANONICAL}"

def test_canonical_has_load_module():
    assert (C.CANONICAL / "load.py").exists(), "canonical/load.py missing"


# ---------------------------------------------------------------------------
# Fill model
# ---------------------------------------------------------------------------

def test_notional_is_25():
    assert C.NOTIONAL_USD == 25.0

def test_fee_rate_is_legacy_2pct():
    # Phase 1 uses the legacy 2%-on-profit shortcut; engine_v2's real fee
    # curve is opt-in for later phases.
    assert C.FEE_RATE == 0.02


# ---------------------------------------------------------------------------
# Anchor convention
# ---------------------------------------------------------------------------

def test_window_5m_matches_canonical():
    assert C.WINDOW_S["5m"] == 300

def test_window_15m_matches_canonical():
    assert C.WINDOW_S["15m"] == 900

def test_fire_offset_matches_production():
    # Production momo controller fires at ws_s + 120s
    assert C.FIRE_OFFSET_S == 120


# ---------------------------------------------------------------------------
# Axis thresholds (Phase 1)
# ---------------------------------------------------------------------------

def test_trend_min_abs_in_range():
    assert 1 <= C.TREND_MIN_ABS <= 3

def test_levels_certainty_in_range():
    assert 0.0 < C.LEVELS_MIN_CERTAINTY < 0.5

def test_momentum_strength_in_range():
    assert 0.0 < C.MOMENTUM_MIN_STRENGTH < 1.0


# ---------------------------------------------------------------------------
# Conflict filter
# ---------------------------------------------------------------------------

def test_abstain_limit_is_2():
    # Spec §4.6: "If 2 or more abstentions → not enough info, skip"
    assert C.ABSTAIN_LIMIT == 2


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

def test_risk_thresholds_positive():
    assert C.MAX_DRAWDOWN_PCT > 0
    assert C.DAILY_LOSS_LIMIT_PCT > 0
    assert 0 < C.RECOVERY_RESUME_FACTOR <= 1


# ---------------------------------------------------------------------------
# Blowoff guard is regime-asymmetric (Cyclops Day 3)
# ---------------------------------------------------------------------------

def test_blowoff_guard_is_asymmetric():
    # The whole point of the Day-3 change: UP-blowoff blocks, DOWN-blowoff allows.
    assert C.BLOWOFF_GUARD_UP is True
    assert C.BLOWOFF_GUARD_DOWN is False


# ---------------------------------------------------------------------------
# Sleeve identity
# ---------------------------------------------------------------------------

def test_sleeve_id_format():
    # Must match TV-agent naming pattern from existing sleeves.
    assert C.SLEEVE_ID.startswith("poly_updown_")
    assert "cyclops" in C.SLEEVE_ID
    assert C.SLEEVE_ID.endswith("_v1")


# ---------------------------------------------------------------------------
# Sizing bounds
# ---------------------------------------------------------------------------

def test_sizing_bounds_sane():
    assert C.MIN_NOTIONAL_USD < C.NOTIONAL_USD < C.MAX_NOTIONAL_USD
