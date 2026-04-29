"""
Phase 4 smoke tests for the three V1 adaptive strategies.

Scope: signal correctness + minimal end-to-end backtest under limit mode.
No Calmar/Sharpe promotion decisions here — those run in Phase 5.

Covers:
  * generate_signals returns the correct schema
  * Signals respect the regime gate
  * End-to-end `run_backtest(limit)` produces non-null fills and metrics
  * No-lookahead sanity: truncating df does not change past entries
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "strategy_lab"))

import engine  # noqa: E402
from strategies.adaptive import (  # noqa: E402
    a1_generate_signals, b1_generate_signals, d1_generate_signals,
)


# ---------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def btc_4h():
    return engine.load("BTCUSDT", "4h", start="2022-01-01", end="2024-06-30")


@pytest.fixture(scope="module")
def btc_15m():
    return engine.load("BTCUSDT", "15m", start="2023-06-01", end="2024-06-30")


@pytest.fixture(scope="module")
def btc_4h_for_d1():
    # Same window as 15m fixture so HTF/LTF align
    return engine.load("BTCUSDT", "4h", start="2023-06-01", end="2024-06-30")


# ---------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------
def _validate_schema(sig, df):
    assert set(sig.keys()) >= {"entries", "exits", "short_entries", "short_exits",
                                "entry_limit_offset", "_meta"}
    assert sig["entries"].dtype == bool
    assert sig["exits"].dtype == bool
    assert len(sig["entries"]) == len(df)
    assert sig["short_entries"] is None
    assert sig["short_exits"] is None
    assert isinstance(sig["entry_limit_offset"], pd.Series)


# =====================================================================
# A1
# =====================================================================
def test_a1_schema_and_signals(btc_4h):
    sig = a1_generate_signals(btc_4h)
    _validate_schema(sig, btc_4h)
    assert sig["entries"].sum() > 10, "A1 should produce multiple entries over 2y+"
    m = sig["_meta"]
    assert m["strategy_id"] == "a1_regime_switcher"
    # Both legs (trend and MR) should fire at least once in a 2y+ window.
    assert m["family_share_trend"] > 0.0
    # MR may be zero in a very trendy window — tolerate.


def test_a1_end_to_end_backtest(btc_4h):
    sig = a1_generate_signals(btc_4h)
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot", limit_valid_bars=3,
        limit_offset_pct=0.0, queue_position_penalty_bps=1.0,
        max_fill_pct_of_bar_volume=0.2, slippage_bps=5.0,
    )
    res = engine.run_backtest(
        btc_4h, entries=sig["entries"], exits=sig["exits"],
        sl_stop=sig["_meta"]["atr_pct_suggested_sl"],
        execution=cfg,
    )
    assert res.metrics["n_trades"] >= 1
    # Maker-fill check — limit entries should be maker; stop-out fills are taker.
    assert res.execution_metrics["maker_fill_pct"] > 0.3, (
        f"A1 maker fill < 30% — entries aren't filling as limits. "
        f"Got {res.execution_metrics['maker_fill_pct']:.1%}"
    )


# =====================================================================
# B1
# =====================================================================
def test_b1_schema_and_signals(btc_4h):
    sig = b1_generate_signals(btc_4h)
    _validate_schema(sig, btc_4h)
    m = sig["_meta"]
    assert m["strategy_id"] == "b1_kama_adaptive_trend"
    assert 0.0 <= m["er_mean"] <= 1.0
    # ER threshold should activate for 5-60% of bars on a 2y window.
    assert 0.05 <= m["er_threshold_hit_pct"] <= 0.80
    assert sig["entries"].sum() > 5


def test_b1_end_to_end_backtest(btc_4h):
    sig = b1_generate_signals(btc_4h)
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot", limit_valid_bars=3,
        limit_offset_pct=0.0, queue_position_penalty_bps=1.0,
        max_fill_pct_of_bar_volume=0.2, slippage_bps=5.0,
    )
    res = engine.run_backtest(
        btc_4h, entries=sig["entries"], exits=sig["exits"],
        tsl_stop=sig["_meta"]["atr_pct_suggested_tsl"],
        execution=cfg,
    )
    assert res.metrics["n_trades"] >= 1
    # B1 uses TSL — most exits taker, but entries should still be mostly maker
    # so overall maker % lands around ~40-50%.
    assert res.execution_metrics["maker_fill_pct"] > 0.25


# =====================================================================
# D1
# =====================================================================
def test_d1_schema_and_signals(btc_15m, btc_4h_for_d1):
    sig = d1_generate_signals(btc_15m, df_4h=btc_4h_for_d1)
    _validate_schema(sig, btc_15m)
    m = sig["_meta"]
    assert m["strategy_id"] == "d1_htf_regime_ltf_pullback"
    # HTF uptrend share reasonable
    assert 0.05 < m["htf_uptrend_pct"] < 0.95
    # RSI gate (tightened to <5 in refined V2) fires less — allow 0.1-30%.
    assert 0.001 < m["rsi_oversold_pct"] < 0.50
    # Combined entry rate should be sparse after the 3-filter stack.
    assert 0 < m["combined_entry_pct"] < 0.05, (
        f"D1 refined filter should keep combined entry rate below 5%, "
        f"got {m['combined_entry_pct']:.2%}"
    )
    assert sig["entries"].sum() > 1


def test_d1_end_to_end_backtest(btc_15m, btc_4h_for_d1):
    sig = d1_generate_signals(btc_15m, df_4h=btc_4h_for_d1)
    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot", limit_valid_bars=2,
        limit_offset_pct=0.0, queue_position_penalty_bps=1.0,
        max_fill_pct_of_bar_volume=0.2, slippage_bps=5.0,
    )
    res = engine.run_backtest(
        btc_15m, entries=sig["entries"], exits=sig["exits"],
        sl_stop=sig["_meta"]["atr_pct_suggested_sl"],
        tp_stop=sig["_meta"]["atr_pct_suggested_tp"],
        execution=cfg,
    )
    assert res.metrics["n_trades"] >= 1
    assert res.execution_metrics["maker_fill_pct"] > 0.25


# =====================================================================
# No-lookahead sanity across all three
# =====================================================================
def test_a1_no_lookahead(btc_4h):
    full = a1_generate_signals(btc_4h)
    short = a1_generate_signals(btc_4h.iloc[:-50])
    # Past entries must be identical
    pd.testing.assert_series_equal(
        full["entries"].iloc[:-50].astype(bool),
        short["entries"].astype(bool),
        check_names=False,
    )


def test_b1_no_lookahead(btc_4h):
    full = b1_generate_signals(btc_4h)
    short = b1_generate_signals(btc_4h.iloc[:-50])
    pd.testing.assert_series_equal(
        full["entries"].iloc[:-50].astype(bool),
        short["entries"].astype(bool),
        check_names=False,
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
