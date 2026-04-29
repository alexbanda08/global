"""
Phase 0.5a regression tests.

Guarantees:
  1. The uplifted engine's default path (`execution=None`) produces
     equity curves bit-identical to the pre-uplift golden master.
  2. `ExecutionConfig(mode="v1")` goes through the same code path with
     no observable behavior change.
  3. Non-v1 modes raise NotImplementedError until Phase 0.5b/c lands.
  4. `BacktestResult` exposes `fills`, `unfilled_orders`,
     `execution_metrics` with the correct shape even in v1 mode.
  5. `FeeSchedule` / `FEE_REGISTRY` behave per spec (registry lookup,
     custom registration, invalid-key error).

Run with either:
    & "py" -3.14 -m pytest strategy_lab/tests/test_engine_v1_compat.py -v
or directly:
    & "py" -3.14 strategy_lab/tests/test_engine_v1_compat.py
"""
from __future__ import annotations

import hashlib
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "strategy_lab"))

import engine  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "golden" / "v1_equity_curves.pkl"


# ---------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def btc_daily():
    return engine.load("BTCUSDT", "1d", "2022-01-01", "2024-01-01")


@pytest.fixture(scope="module")
def sma_signals(btc_daily):
    df = btc_daily
    f = df["close"].rolling(20).mean()
    s = df["close"].rolling(50).mean()
    le = (f > s) & (f.shift(1) <= s.shift(1))
    lx = (f < s) & (f.shift(1) >= s.shift(1))
    return le, lx


@pytest.fixture(scope="module")
def golden_baseline():
    if not GOLDEN.exists():
        pytest.skip(f"golden master not found: {GOLDEN}")
    with open(GOLDEN, "rb") as f:
        snap = pickle.load(f)
    snap.pop("_meta", None)
    return snap


def _eq_hash(eq: pd.Series) -> str:
    return hashlib.sha256(eq.to_numpy(dtype=np.float64).tobytes()).hexdigest()[:16]


# ---------------------------------------------------------------------
# 1. Golden-master regression
# ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "scenario,kwargs_builder",
    [
        ("sma_cross_no_stops",   lambda le, lx: dict(entries=le, exits=lx)),
        ("sma_cross_sl_only",    lambda le, lx: dict(entries=le, exits=lx, sl_stop=0.05)),
        ("sma_cross_tsl_only",   lambda le, lx: dict(entries=le, exits=lx, tsl_stop=0.05)),
        ("sma_cross_tp_only",    lambda le, lx: dict(entries=le, exits=lx, tp_stop=0.10)),
        ("sma_cross_both_sides", lambda le, lx: dict(entries=le, exits=lx,
                                                     short_entries=lx.copy(),
                                                     short_exits=le.copy())),
    ],
)
def test_v1_mode_matches_pre_uplift_baseline(
    btc_daily, sma_signals, golden_baseline, scenario, kwargs_builder,
):
    le, lx = sma_signals
    kwargs = kwargs_builder(le, lx)
    kwargs["label"] = scenario

    res = engine.run_backtest(btc_daily, **kwargs)
    eq_new = res.pf.value()
    eq_old = golden_baseline[scenario]["equity"]

    assert len(eq_new) == len(eq_old), "equity length changed"
    assert np.allclose(eq_new.to_numpy(), eq_old.to_numpy(), atol=1e-9), (
        f"{scenario}: equity diverged beyond 1e-9"
    )
    assert _eq_hash(eq_new) == golden_baseline[scenario]["equity_hash"], (
        f"{scenario}: equity hash changed — floats drifted even if within atol"
    )


def test_explicit_v1_execution_config_is_noop(btc_daily, sma_signals, golden_baseline):
    """Passing ExecutionConfig(mode='v1') must be identical to execution=None."""
    le, lx = sma_signals
    res_default = engine.run_backtest(btc_daily, entries=le, exits=lx,
                                      label="default")
    res_explicit = engine.run_backtest(btc_daily, entries=le, exits=lx,
                                       label="default",
                                       execution=engine.ExecutionConfig(mode="v1"))
    a = res_default.pf.value().to_numpy()
    b = res_explicit.pf.value().to_numpy()
    assert np.array_equal(a, b), "explicit v1 execution diverged from default"


# ---------------------------------------------------------------------
# 2. Phase 0.5a / 0.5b gate — only hybrid (0.5c) still refuses to run.
# ---------------------------------------------------------------------
@pytest.mark.parametrize("mode", ["hybrid"])
def test_unimplemented_modes_still_raise(btc_daily, sma_signals, mode):
    le, lx = sma_signals
    cfg = engine.ExecutionConfig(mode=mode)
    with pytest.raises(NotImplementedError, match="not implemented"):
        engine.run_backtest(btc_daily, entries=le, exits=lx, execution=cfg)


# ---------------------------------------------------------------------
# 3. BacktestResult shape contract
# ---------------------------------------------------------------------
def test_result_exposes_new_fields_in_v1_mode(btc_daily, sma_signals):
    le, lx = sma_signals
    res = engine.run_backtest(btc_daily, entries=le, exits=lx)

    assert hasattr(res, "fills")
    assert hasattr(res, "unfilled_orders")
    assert hasattr(res, "execution_metrics")

    # v1 mode should produce empty DataFrames with the spec columns.
    assert list(res.fills.columns) == [
        "ts", "side", "size", "price", "fee", "is_maker",
        "slippage_bps", "order_id", "parent_signal_ts",
    ]
    assert list(res.unfilled_orders.columns) == [
        "ts_posted", "side", "limit_price", "expired_at", "reason",
    ]
    assert len(res.fills) == 0
    assert len(res.unfilled_orders) == 0


def test_execution_metrics_has_required_keys(btc_daily, sma_signals):
    le, lx = sma_signals
    res = engine.run_backtest(btc_daily, entries=le, exits=lx)
    em = res.execution_metrics

    for key in (
        "maker_fill_pct", "taker_fill_pct",
        "unfilled_order_count", "unfilled_order_pct",
        "total_fee_paid", "fee_drag_pct_of_pnl",
        "avg_entry_slippage_bps", "avg_exit_slippage_bps",
        "avg_slippage_per_trade",
        "partial_fill_ratio", "avg_fills_per_order",
        "mode",
    ):
        assert key in em, f"execution_metrics missing key: {key}"

    # v1 defaults: no limit accounting yet.
    assert em["mode"] == "v1"
    assert em["maker_fill_pct"] == 0.0
    assert em["taker_fill_pct"] == 1.0
    assert em["unfilled_order_count"] == 0


# ---------------------------------------------------------------------
# 4. Fee registry
# ---------------------------------------------------------------------
def test_fee_registry_defaults_present():
    for key in ("binance_spot_legacy", "binance_spot", "bybit_spot",
                "bybit_perp", "hyperliquid"):
        assert key in engine.FEE_REGISTRY


def test_resolve_fee_schedule_accepts_string_or_object():
    by_str = engine.resolve_fee_schedule("bybit_perp")
    by_obj = engine.resolve_fee_schedule(by_str)
    assert by_str.maker_bps == 2.0
    assert by_str.taker_bps == 5.5
    assert by_obj is by_str


def test_resolve_fee_schedule_unknown_key_raises():
    with pytest.raises(KeyError, match="Unknown fee schedule"):
        engine.resolve_fee_schedule("does_not_exist_xyz")


def test_register_fee_schedule_round_trip():
    custom = engine.FeeSchedule("phase05a_test", 4.0, 7.5, notes="test only")
    engine.register_fee_schedule(custom)
    try:
        assert engine.resolve_fee_schedule("phase05a_test") is custom
    finally:
        engine.FEE_REGISTRY.pop("phase05a_test", None)


def test_execution_config_defaults():
    cfg = engine.ExecutionConfig()
    assert cfg.mode == "v1"
    assert cfg.fee_schedule == "binance_spot_legacy"
    assert cfg.slippage_bps == 5.0
    assert cfg.max_fill_pct_of_bar_volume == 0.10
    assert cfg.limit_valid_bars == 3


# ---------------------------------------------------------------------
# Allow direct python invocation as a smoke runner.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    rc = pytest.main([__file__, "-v", "--tb=short"])
    raise SystemExit(rc)
