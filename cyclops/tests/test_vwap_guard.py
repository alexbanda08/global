"""Tests for the vwap pre-flight guard."""

from __future__ import annotations

import math

import pytest

from cyclops.filters.vwap_guard import is_vwap_too_low


def test_disabled_at_zero_threshold():
    skip, _ = is_vwap_too_low(0.10, threshold=0.0)
    assert skip is False


def test_disabled_at_negative_threshold():
    skip, _ = is_vwap_too_low(0.10, threshold=-1.0)
    assert skip is False


def test_skips_below_threshold():
    skip, reason = is_vwap_too_low(0.25, threshold=0.30)
    assert skip is True
    assert "vwap_guard" in reason
    assert "0.30" in reason


def test_passes_at_or_above_threshold():
    skip, reason = is_vwap_too_low(0.30, threshold=0.30)
    assert skip is False
    assert reason == "ok"
    skip, reason = is_vwap_too_low(0.45, threshold=0.30)
    assert skip is False


def test_nan_ask_l0_is_skipped():
    skip, reason = is_vwap_too_low(float("nan"), threshold=0.30)
    assert skip is True
    assert "missing" in reason


def test_none_ask_l0_is_skipped():
    skip, reason = is_vwap_too_low(None, threshold=0.30)
    assert skip is True
    assert "missing" in reason
