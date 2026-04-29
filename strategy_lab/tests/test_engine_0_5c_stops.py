"""
Phase 0.5c — stops (sl / tsl / tp) inside limit mode.

Rules under test:
  * While in position, each bar evaluates:
      - sl_stop  — fixed stop at entry * (1 - sl_pct). Hit when low <= stop.
      - tsl_stop — trailing stop at highest-high-since-entry * (1 - tsl_pct).
      - tp_stop  — fixed target at entry * (1 + tp_pct). Hit when high >= tp.
  * On hit: any resting sell limit is cancelled (unfilled, reason=stop_override),
    and the position market-closes at stop/tp level * (1 - slip_bps/1e4).
  * Stop-hit fills carry taker fees (fs.taker_bps), is_maker=False.
  * Tie-break: if both stop and tp could trigger the same bar, stop wins
    (conservative — worst case for the strategy).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "strategy_lab"))

import engine  # noqa: E402


def make_ohlcv(rows, start="2024-01-01", freq="1D"):
    idx = pd.date_range(start=start, periods=len(rows), freq=freq, tz="UTC")
    return pd.DataFrame(rows, columns=["open","high","low","close","volume"],
                        index=idx).astype("float64")

def sig(index, positions):
    s = pd.Series(False, index=index)
    for p in positions: s.iloc[p] = True
    return s


# =====================================================================
# sl_stop — fixed stop fires when price dips 5% below entry
# =====================================================================
def test_limit_sl_stop_fires_on_downside_breach():
    """
    Entry bar 0 → fills bar 1 at 100.01. Entry price = 100.01, sl=5% → stop at 95.01.
    Bar 3 low=94 breaches stop → market-close at 95.01 * (1-5bps slip) = 94.9625.
    Stop fill tagged is_maker=False, fee at taker rate.
    """
    df = make_ohlcv([
        (100, 101, 99,  100, 1_000_000),  # bar 0 — entry signal
        (100, 101, 100, 100, 1_000_000),  # bar 1 — buy fill @ 100.01
        (100, 102, 99,   99, 1_000_000),  # bar 2 — holds
        (100, 101, 94,   95, 1_000_000),  # bar 3 — low=94 breaches stop 95.01
        (95,   96, 94,   95, 1_000_000),  # bar 4 — already exited
    ])
    e = sig(df.index, [0]); x = sig(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot_legacy",
        limit_offset_pct=0.0, limit_valid_bars=3,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(df, entries=e, exits=x,
                              sl_stop=0.05, execution=cfg)

    assert len(res.fills) == 2, f"expected entry + stop exit, got {len(res.fills)}"
    stop_fill = res.fills.iloc[-1]
    assert stop_fill["side"] == "sell"
    assert bool(stop_fill["is_maker"]) is False
    assert stop_fill["order_id"].endswith("-sl_stop")
    expected_px = 100.01 * (1.0 - 0.05) * (1.0 - 5e-4)   # 95.0095 * 0.9995
    assert stop_fill["price"] == pytest.approx(expected_px, abs=1e-9)
    # Taker fee = notional * 10 bps (binance_spot_legacy taker).
    expected_fee = stop_fill["size"] * stop_fill["price"] * 10 / 1e4
    assert stop_fill["fee"] == pytest.approx(expected_fee, rel=1e-9)
    # Maker/taker split: 1 maker entry + 1 taker stop = 50/50.
    assert res.execution_metrics["maker_fill_pct"] == pytest.approx(0.5)
    assert res.metrics["n_trades"] == 1


# =====================================================================
# tp_stop — fixed profit target fires when price rallies +4%
# =====================================================================
def test_limit_tp_stop_fires_on_upside_breach():
    """
    Entry bar 0 → fills bar 1 at 100.01. tp=4% → target at 104.0104.
    Bar 2 high=105 → tp hits, exit at 104.0104 * (1-5bps).
    """
    df = make_ohlcv([
        (100, 101, 99,  100, 1_000_000),  # bar 0 — entry signal
        (100, 101, 100, 100, 1_000_000),  # bar 1 — buy fill @ 100.01
        (100, 105, 100, 103, 1_000_000),  # bar 2 — high=105 breaches tp 104.01
        (103, 104, 102, 103, 1_000_000),  # bar 3 — already exited
    ])
    e = sig(df.index, [0]); x = sig(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot_legacy",
        limit_offset_pct=0.0, limit_valid_bars=3,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(df, entries=e, exits=x,
                              tp_stop=0.04, execution=cfg)

    assert len(res.fills) == 2
    tp_fill = res.fills.iloc[-1]
    assert tp_fill["side"] == "sell"
    assert bool(tp_fill["is_maker"]) is False
    assert tp_fill["order_id"].endswith("-tp_stop")
    expected_px = 100.01 * 1.04 * (1.0 - 5e-4)
    assert tp_fill["price"] == pytest.approx(expected_px, abs=1e-9)


# =====================================================================
# tsl_stop — trailing stop ratchets with peak high
# =====================================================================
def test_limit_tsl_stop_trails_and_fires():
    """
    tsl=5%.
      Bar 1 entry fill @ 100.01; initial TSL = 101 (bar-1 high) * 0.95 = 95.95.
      Bar 2 high=110 ⇒ peak=110, TSL = 104.5.
      Bar 3 low=103 → 103 <= 104.5 → trailing stop hits.
    """
    df = make_ohlcv([
        (100, 101, 99,  100, 1_000_000),  # bar 0 — entry signal
        (100, 101, 100, 100, 1_000_000),  # bar 1 — buy fill, peak=101
        (100, 110, 100, 108, 1_000_000),  # bar 2 — peak moves to 110
        (108, 108, 103, 104, 1_000_000),  # bar 3 — low=103 hits TSL at 104.5
        (104, 105, 103, 104, 1_000_000),  # bar 4 — already exited
    ])
    e = sig(df.index, [0]); x = sig(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot_legacy",
        limit_offset_pct=0.0, limit_valid_bars=5,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(df, entries=e, exits=x,
                              tsl_stop=0.05, execution=cfg)

    assert len(res.fills) == 2
    tsl_fill = res.fills.iloc[-1]
    assert tsl_fill["order_id"].endswith("-tsl_stop")
    assert bool(tsl_fill["is_maker"]) is False
    # Peak high at time of trigger = 110, TSL level = 110 * 0.95 = 104.5.
    expected_px = 110.0 * 0.95 * (1.0 - 5e-4)
    assert tsl_fill["price"] == pytest.approx(expected_px, abs=1e-9)
    assert res.metrics["n_trades"] == 1
    assert res.metrics["total_return"] > 0, "TSL should lock in a profit here"


# =====================================================================
# Stop overrides resting exit limit
# =====================================================================
def test_stop_cancels_resting_exit_limit():
    """
    Entry fills bar 1 @ 100.01. Exit signal bar 2 posts a sell limit at 99.
    Bar 3 high=98 so the limit cannot fill; low=94 breaches sl → stop fires
    and cancels the still-resting exit limit (unfilled, reason=stop_override).
    """
    df = make_ohlcv([
        (100, 101, 99,  100, 1_000_000),  # bar 0 — entry signal
        (100, 101, 100, 100, 1_000_000),  # bar 1 — buy fill
        (100, 101,  99,  99, 1_000_000),  # bar 2 — exit signal (limit posted at 99)
        (96,   98,  94,  95, 1_000_000),  # bar 3 — high=98 < L=99 (no limit fill);
                                          #          low=94 ≤ stop 95.0095 → fire
    ])
    e = sig(df.index, [0]); x = sig(df.index, [2])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot_legacy",
        limit_offset_pct=0.0, limit_valid_bars=5,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(df, entries=e, exits=x,
                              sl_stop=0.05, execution=cfg)

    # Entry fill + stop-out fill = 2 fills. The exit limit should have been
    # cancelled before it ever filled on bar 3 (where high=100 >= exit L=99).
    # Therefore the exit order shows up as unfilled with stop_override.
    assert any(r["reason"] == "stop_override" for _, r in res.unfilled_orders.iterrows()), \
        f"expected stop_override in unfilled, got {res.unfilled_orders['reason'].tolist()}"
    # The stop fire must mark a taker fill.
    final = res.fills.iloc[-1]
    assert bool(final["is_maker"]) is False
    assert final["order_id"].endswith("-sl_stop")


# =====================================================================
# sl + tp together — both set; sl hit first wins.
# =====================================================================
def test_sl_and_tp_both_set_stop_wins_on_conflict():
    """
    Bar 2 has both low=93 (< sl 95.01) AND high=106 (> tp 104.01). Stop wins.
    """
    df = make_ohlcv([
        (100, 101, 99,  100, 1_000_000),  # bar 0 — entry
        (100, 101, 100, 100, 1_000_000),  # bar 1 — buy fill
        (100, 106, 93,  100, 1_000_000),  # bar 2 — BOTH hit; stop wins
        (100, 105, 99,  101, 1_000_000),  # bar 3
    ])
    e = sig(df.index, [0]); x = sig(df.index, [])

    cfg = engine.ExecutionConfig(
        mode="limit", fee_schedule="binance_spot_legacy",
        limit_offset_pct=0.0, limit_valid_bars=5,
        queue_position_penalty_bps=1.0, max_fill_pct_of_bar_volume=1.0,
        slippage_bps=5.0,
    )
    res = engine.run_backtest(df, entries=e, exits=x,
                              sl_stop=0.05, tp_stop=0.04, execution=cfg)

    stop_fill = res.fills.iloc[-1]
    assert stop_fill["order_id"].endswith("-sl_stop"), \
        f"stop should win tie, got {stop_fill['order_id']}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
