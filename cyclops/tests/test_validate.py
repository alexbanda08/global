"""Smoke tests for the validation battery — small synthetic inputs only.

Real-data results land in the P5 report; here we just ensure the math
returns sensible JSON-serialisable verdicts on edge cases.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cyclops.validate.permutation import permutation_test
from cyclops.validate.bootstrap import bootstrap_mean_ci
from cyclops.validate.walkforward import walkforward_test


# ---------------------------------------------------------------------------
# Permutation
# ---------------------------------------------------------------------------

def _synthetic_trades(n: int, wr: float, ws_offset: int = 0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    direction = rng.choice(["Up", "Down"], size=n)
    outcome = direction.copy()
    flip = rng.random(n) > wr
    outcome[flip] = np.where(direction[flip] == "Up", "Down", "Up")
    stake = np.full(n, 25.0)
    shares = np.full(n, 50.0)  # implies vwap 0.5 → +$24.50 on win, -$25 on loss
    won = (direction == outcome)
    payoff = shares - stake
    pnl = np.where(won, payoff * 0.98, -stake)
    ws_s = 1_777_000_000 + ws_offset + np.arange(n) * 60
    return pd.DataFrame({
        "direction": direction, "outcome_truth": outcome,
        "shares": shares, "stake_usd": stake,
        "won": won, "pnl_usd": pnl, "ws_s": ws_s,
    })


def test_permutation_pass_on_strong_edge():
    df = _synthetic_trades(n=300, wr=0.65, seed=1)
    res = permutation_test(df, n_permutations=200, seed=42)
    assert res["n_trades"] == 300
    assert res["observed_mean_pnl"] > 0
    assert res["p_value"] < 0.05


def test_permutation_fail_on_no_edge():
    df = _synthetic_trades(n=300, wr=0.50, seed=2)
    res = permutation_test(df, n_permutations=200, seed=42)
    # WR=50% with avg vwap 0.5 → roughly zero mean PnL → p around 0.5.
    assert res["p_value"] > 0.05


def test_permutation_empty_trades_returns_nan():
    res = permutation_test(pd.DataFrame(), n_permutations=10)
    assert res["n_trades"] == 0


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def test_bootstrap_lower_ci_above_zero_for_strong_signal():
    df = _synthetic_trades(n=400, wr=0.70, seed=3)
    res = bootstrap_mean_ci(df, n_boot=2000, seed=42)
    assert res["ci_lower"] > 0
    assert res["ci_lower"] < res["observed_mean_pnl"] < res["ci_upper"]


def test_bootstrap_lower_ci_below_zero_for_breakeven():
    df = _synthetic_trades(n=200, wr=0.50, seed=4)
    res = bootstrap_mean_ci(df, n_boot=2000, seed=42)
    assert res["ci_lower"] < 0 or abs(res["observed_mean_pnl"]) < 1.0


# ---------------------------------------------------------------------------
# Walkforward
# ---------------------------------------------------------------------------

def test_walkforward_returns_pass_for_consistent_positive_strategy():
    # Spread the 600 trades across 21 days so we get plenty of test windows.
    df = _synthetic_trades(n=600, wr=0.70, seed=5)
    df["ws_s"] = 1_777_000_000 + np.linspace(0, 21 * 86400 - 1, len(df)).astype(int)
    res = walkforward_test(df, train_days=5, test_days=2)
    assert res["n_windows"] >= 4
    assert res["verdict"] == "PASS"


def test_walkforward_handles_empty():
    res = walkforward_test(pd.DataFrame())
    assert res["n_windows"] == 0
    assert res["verdict"] == "no_trades"
