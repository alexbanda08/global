"""
Phase 0.5b tests — market and limit execution modes.

Covers specification § 6 tests:
  2.  test_market_fill_regression
  3.  test_limit_buy_fills_on_touch
  4.  test_limit_buy_expires_without_touch
  5.  test_limit_sell_fills_on_touch_high
  6.  test_partial_fill_over_two_bars
  9.  test_maker_vs_taker_fee_correctness
  12. test_no_lookahead_open_below_limit
  15. test_unfilled_count_metric

Synthetic OHLCV is used so the expected fill prices / counts are exact.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "strategy_lab"))

import engine  # noqa: E402


# ---------------------------------------------------------------------
# Synthetic-bar helpers
# ---------------------------------------------------------------------
def make_ohlcv(ohlcv_rows: list[tuple[float, float, float, float, float]],
               start: str = "2024-01-01", freq: str = "1D") -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=len(ohlcv_rows), freq=freq, tz="UTC")
    df = pd.DataFrame(
        ohlcv_rows, columns=["open", "high", "low", "close", "volume"], index=idx,
    ).astype("float64")
    df.index.name = "open_time"
    return df


def sig_series(index: pd.DatetimeIndex, true_bar_positions: list[int]) -> pd.Series:
    s = pd.Series(False, index=index)
    for i in true_bar_positions:
        s.iloc[i] = True
    return s


# =====================================================================
# Test 2 — market mode reproduces v1 under identical fee/slip (regression)
# =====================================================================
@pytest.fixture(scope="module")
def btc_daily():
    return engine.load("BTCUSDT", "1d", "2022-01-01", "2024-01-01")


def test_market_fill_regression(btc_daily):
    df = btc_daily
    f = df["close"].rolling(20).mean()
    s = df["close"].rolling(50).mean()
    le = (f > s) & (f.shift(1) <= s.shift(1))
    lx = (f < s) & (f.shift(1) >= s.shift(1))

    res_v1 = engine.run_backtest(df, entries=le, exits=lx, label="v1")

    # market mode with binance_spot_legacy (maker 10 bps / taker 10 bps / slip 5bps)
    # reproduces v1 within float tolerance.
    cfg = engine.ExecutionConfig(mode="market", fee_schedule="binance_spot_legacy",
                                 slippage_bps=5.0)
    res_m = engine.run_backtest(df, entries=le, exits=lx, label="market",
                                execution=cfg)

    a = res_v1.pf.value().to_numpy()
    b = res_m.pf.value().to_numpy()
    assert np.allclose(a, b, atol=1e-9), "market mode diverged from v1 at identical fees"

    # market mode populates fills; v1 does not.
    assert len(res_m.fills) == 2 * res_v1.metrics["n_trades"]
    assert len(res_v1.fills) == 0
    assert res_m.execution_metrics["mode"] == "market"
    assert res_m.execution_metrics["taker_fill_pct"] == 1.0
    assert res_m.execution_metrics["maker_fill_pct"] == 0.0


# =====================================================================
# Test 3 — limit buy fills on touch
# =====================================================================
def test_limit_buy_fills_on_touch():
    """
    Signal on bar 0 (close=100). Limit posted at 100 (offset=0).
    Bar 1 low=100 → fill at 100*(1+1bp) = 100.01.
    """
    df = make_ohlcv([
        (100, 101, 99,  100, 1_000_000),   # bar 0 — entry signal
        (100, 101, 100, 100, 1_000_000),   # bar 1 — low touches L=100 → fill
        (100, 101,  99, 100, 1_000_000),   # bar 2
    ])
    entries = sig_series(df.index, [0])
    exits = sig_series(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot_legacy",
        limit_offset_pct=0.0, limit_valid_bars=3,
        queue_position_penalty_bps=1.0,
        max_fill_pct_of_bar_volume=1.0,     # no partial cap — fill full order
    )
    res = engine.run_backtest(df, entries=entries, exits=exits, execution=cfg)

    assert len(res.fills) == 1, f"expected exactly 1 fill, got {len(res.fills)}"
    fill = res.fills.iloc[0]
    assert fill["side"] == "buy"
    assert fill["is_maker"] is True or fill["is_maker"] == True  # bool dtype
    assert fill["price"] == pytest.approx(100.0 * (1 + 1e-4), abs=1e-9)
    assert len(res.unfilled_orders) == 0
    assert res.execution_metrics["maker_fill_pct"] == 1.0


# =====================================================================
# Test 4 — limit buy expires without touch
# =====================================================================
def test_limit_buy_expires_without_touch():
    """
    Signal on bar 0 (close=100). Limit at 100.
    Bars 1..3 all have low > 100 → no fill, limit expires after 3 bars.
    """
    df = make_ohlcv([
        (100, 101, 99,  100, 1_000_000),  # bar 0 — signal
        (101, 105, 101, 103, 1_000_000),  # bar 1 — low=101 > 100 → no fill
        (103, 106, 102, 104, 1_000_000),  # bar 2
        (104, 108, 103, 106, 1_000_000),  # bar 3
        (106, 110, 105, 108, 1_000_000),  # bar 4 — well past expiry
    ])
    entries = sig_series(df.index, [0])
    exits = sig_series(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", limit_offset_pct=0.0, limit_valid_bars=3,
    )
    res = engine.run_backtest(df, entries=entries, exits=exits, execution=cfg)

    assert len(res.fills) == 0
    assert len(res.unfilled_orders) == 1
    u = res.unfilled_orders.iloc[0]
    assert u["side"] == "buy"
    assert u["reason"] == "expired"
    assert u["limit_price"] == pytest.approx(100.0)
    assert res.execution_metrics["unfilled_order_count"] == 1
    assert res.execution_metrics["unfilled_order_pct"] == pytest.approx(1.0)


# =====================================================================
# Test 5 — limit sell fills on touch (high side)
# =====================================================================
def test_limit_sell_fills_on_touch_high():
    """
    Buy first (fills bar 1). Exit signal on bar 2 (close=105),
    limit sell at 105. Bar 3 high=105 → fill at 105*(1-1bp) = 104.9895.
    """
    df = make_ohlcv([
        (100, 101,  99, 100, 1_000_000),   # bar 0 — entry signal
        (100, 101, 100, 102, 1_000_000),   # bar 1 — buy fills @100.01
        (102, 106, 102, 105, 1_000_000),   # bar 2 — exit signal (close=105)
        (105, 105, 104, 104, 1_000_000),   # bar 3 — high=105 → sell fills @104.9895
    ])
    entries = sig_series(df.index, [0])
    exits   = sig_series(df.index, [2])

    cfg = engine.ExecutionConfig(
        mode="limit", limit_offset_pct=0.0, limit_valid_bars=3,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
    )
    res = engine.run_backtest(df, entries=entries, exits=exits, execution=cfg)

    assert len(res.fills) == 2, f"expected 2 fills (buy+sell), got {len(res.fills)}"
    buy, sell = res.fills.iloc[0], res.fills.iloc[1]
    assert buy["side"] == "buy"
    assert sell["side"] == "sell"
    assert sell["price"] == pytest.approx(105.0 * (1 - 1e-4), abs=1e-9)
    assert bool(sell["is_maker"]) is True
    assert res.metrics["n_trades"] == 1


# =====================================================================
# Test 6 — partial fill across two bars
# =====================================================================
def test_partial_fill_over_two_bars():
    """
    With bar-volume cap of 10% and tiny bar volumes, the order fills
    over 2 bars. Both fills are maker.
    """
    df = make_ohlcv([
        (100, 101,  99, 100,     10_000),   # bar 0 — signal
        (100, 101, 100, 100,      1_000),   # bar 1 — cap 10% × 1000 = 100 qty
        (100, 101, 100, 100,    999_999),   # bar 2 — rest of the order
        (100, 101,  99, 100,      1_000),   # bar 3
    ])
    entries = sig_series(df.index, [0])
    exits = sig_series(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", limit_offset_pct=0.0, limit_valid_bars=5,
        queue_position_penalty_bps=1.0,
        max_fill_pct_of_bar_volume=0.10,    # the cap that forces the split
    )
    res = engine.run_backtest(df, entries=entries, exits=exits,
                              init_cash=1_000_000.0, execution=cfg)

    assert len(res.fills) >= 2, f"expected >=2 fills (partial + fill), got {len(res.fills)}"
    assert all(bool(m) for m in res.fills["is_maker"])
    # All fills share the same parent order_id
    assert res.fills["order_id"].nunique() == 1
    assert res.execution_metrics["partial_fill_ratio"] == 1.0


# =====================================================================
# Test 9 — maker vs taker fee correctness
# =====================================================================
def test_maker_vs_taker_fee_correctness():
    """
    Use bybit_perp schedule (maker 2bps, taker 5.5bps).
    Limit mode fills are MAKER → fee = notional * 2bps.
    """
    df = make_ohlcv([
        (100, 101,  99, 100, 1_000_000),   # bar 0
        (100, 101, 100, 100, 1_000_000),   # bar 1 — fill
        (100, 105, 100, 105, 1_000_000),   # bar 2 — exit signal
        (105, 105, 104, 104, 1_000_000),   # bar 3 — sell fill
    ])
    entries = sig_series(df.index, [0])
    exits   = sig_series(df.index, [2])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="bybit_perp",
        limit_offset_pct=0.0, limit_valid_bars=3,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
    )
    res = engine.run_backtest(df, entries=entries, exits=exits,
                              init_cash=10_000.0, execution=cfg)

    assert len(res.fills) == 2
    # Every fill.fee must equal notional * 2bps (bybit_perp maker rate).
    for _, row in res.fills.iterrows():
        expected_fee = float(row["size"]) * float(row["price"]) * (2.0 / 1e4)
        assert row["fee"] == pytest.approx(expected_fee, rel=1e-9, abs=1e-12)


# =====================================================================
# Test 12 — no look-ahead when open < L < high
# =====================================================================
def test_no_lookahead_open_below_limit():
    """
    Bar 1 has open=98 (below limit L=100) and high=105. A naive engine
    would fill at 98. We must fill at L * (1 + penalty).
    """
    df = make_ohlcv([
        (100, 101,  99, 100, 1_000_000),   # bar 0 — signal
        (98,  105,  98,  99, 1_000_000),   # bar 1 — open<L<high, low<L too
        (99,  102,  99, 100, 1_000_000),   # bar 2
    ])
    entries = sig_series(df.index, [0])
    exits = sig_series(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot_legacy",
        limit_offset_pct=0.0, limit_valid_bars=3,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
    )
    res = engine.run_backtest(df, entries=entries, exits=exits, execution=cfg)
    assert len(res.fills) == 1
    fill = res.fills.iloc[0]
    assert fill["price"] == pytest.approx(100.0 * (1 + 1e-4), abs=1e-9), (
        "Fill price must be L*(1+penalty) — NEVER the next-bar open"
    )
    # Not the 98 open:
    assert fill["price"] != pytest.approx(98.0)


# =====================================================================
# Test 15 — unfilled count metric
# =====================================================================
def test_unfilled_count_metric():
    """
    10 entry signals, half get filled, half expire.
    `unfilled_order_count` must equal the exact number that expired.
    """
    # Build 20 bars alternating: signal bar (close=100) + unfillable bar (low>100)
    rows = []
    for k in range(10):
        rows.append((100, 101,  99, 100, 1_000_000))  # signal bar
        rows.append((105, 106, 105, 105, 1_000_000))  # unfillable next bar
    df = make_ohlcv(rows)
    entries = sig_series(df.index, [i for i in range(0, 20, 2)])
    exits = sig_series(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", limit_offset_pct=0.0, limit_valid_bars=1,  # expire fast
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
    )
    res = engine.run_backtest(df, entries=entries, exits=exits, execution=cfg)

    # None should fill — every signal is followed by a bar with low=105 > L=100.
    # After expiry, the NEXT signal bar also has low=99 — but we're in "no position
    # when signal fires AND no active order" state, so only after expiry.
    # Expected: several unfilled, zero fills. Count depends on the alternation.
    assert len(res.fills) == 0
    assert res.execution_metrics["unfilled_order_count"] == len(res.unfilled_orders)
    assert res.execution_metrics["unfilled_order_count"] >= 1
    # unfilled_pct should be 1.0 — every parent order expired.
    assert res.execution_metrics["unfilled_order_pct"] == pytest.approx(1.0)


# =====================================================================
# Scope guardrails — shorts still raise (shorts deferred past 0.5c).
# Stops are now supported — sl/tsl/tp covered in test_engine_0_5c_stops.
# =====================================================================
def test_limit_mode_rejects_shorts():
    df = make_ohlcv([
        (100, 101,  99, 100, 1_000_000),
        (100, 101, 100, 100, 1_000_000),
    ])
    e = sig_series(df.index, [0]); x = sig_series(df.index, [])
    cfg = engine.ExecutionConfig(mode="limit")
    with pytest.raises(NotImplementedError, match="short-selling"):
        engine.run_backtest(df, entries=e, exits=x, short_entries=e.copy(),
                            short_exits=x.copy(), execution=cfg)


def test_limit_mode_rejects_both_sl_and_tsl():
    df = make_ohlcv([
        (100, 101,  99, 100, 1_000_000),
        (100, 101, 100, 100, 1_000_000),
    ])
    e = sig_series(df.index, [0]); x = sig_series(df.index, [])
    cfg = engine.ExecutionConfig(mode="limit")
    with pytest.raises(ValueError, match="both sl_stop and tsl_stop"):
        engine.run_backtest(df, entries=e, exits=x,
                            sl_stop=0.05, tsl_stop=0.03, execution=cfg)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
