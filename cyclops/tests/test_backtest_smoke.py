"""Smoke test for the P2 backtest runner.

Loads real canonical data and runs the pipeline on a small slice. Verifies
that the runner returns a structurally well-formed DataFrame and that fired
rows carry all required columns. We do NOT assert positive PnL here — the
verdict on edge belongs to the G1 gate in the CLI, not a unit test.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from cyclops.backtest.runner import run_backtest
from cyclops.conventions import SLEEVE_ID


SMOKE_SIZE = 50  # markets to evaluate (≈5 minutes of universe time)


@pytest.fixture(scope="module")
def df():
    return run_backtest(
        asset="BTC", timeframe="5m", max_markets=SMOKE_SIZE, verbose=False
    )


def test_smoke_evaluates_all_markets(df):
    assert len(df) == SMOKE_SIZE


def test_smoke_has_required_columns(df):
    expected = {
        "slug", "ws_s", "outcome_truth", "current_px",
        "trend_align", "v_trend", "v_levels", "v_momentum",
        "p_up_levels", "score_momentum",
        "fired", "skip_reason",
    }
    missing = expected - set(df.columns)
    assert not missing, f"missing columns: {missing}"


def test_smoke_votes_are_in_minus1_zero_plus1(df):
    for c in ("v_trend", "v_levels", "v_momentum"):
        bad = df[~df[c].isin({-1, 0, 1})]
        assert bad.empty, f"{c} has out-of-range values: {bad[c].unique()}"


def test_smoke_fired_rows_have_pnl(df):
    fired = df[df["fired"] == True]
    if fired.empty:
        pytest.skip("no fires in the smoke window — re-tune eps if this persists")
    for col in ("direction", "stake_usd", "shares", "won", "pnl_usd"):
        assert col in fired.columns
        assert fired[col].notna().all(), f"{col} has NaN among fires"


def test_smoke_skip_reasons_are_known(df):
    known = {
        "coherent",                # paired with fired=True
        "no_kline_asof", "no_l25_entry", "no_fill",
        "abstention_2", "abstention_3",
        # plus any conflict_posX_negY combination
    }
    for r in df["skip_reason"].dropna().unique():
        if r in known:
            continue
        assert r.startswith("conflict_pos"), f"unknown skip_reason: {r}"
