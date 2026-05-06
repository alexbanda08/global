"""Per-trade scalp simulator.

Two flavors:
  - simulate_two_target(): TP1 (50% out) → break-even-stop on remainder → TP2.
    Used by Bella Fade.
  - simulate_single_target(): single TP, stop, shot-clock timeout.
    Used by Offside.

Both consume a `signals` DataFrame (output of detect_*) and an OHLC `df`.
Returns (trades, equity_curve).

Convention: each trade risks `risk_per_trade` of CURRENT equity.
  qty = risk$ / (entry - stop)         (long)
  qty = risk$ / (stop - entry)         (short)
Position size capped by `leverage_cap × equity / entry_price`.
Fees applied per side (`fee_per_side`), slippage as a fraction of price.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

FEE_DEFAULT = 4.5e-4   # Hyperliquid taker
SLIP_DEFAULT = 1.5e-4  # 1.5bp slippage estimate
INIT_CAPITAL = 10_000.0


def simulate_two_target(
    df: pd.DataFrame,
    signals: pd.DataFrame,           # must have entry_idx, entry_price, stop, tp1, tp2, max_hold_bars
    risk_per_trade: float = 0.01,
    leverage_cap: float = 5.0,
    fee_per_side: float = FEE_DEFAULT,
    slip: float = SLIP_DEFAULT,
    init_cash: float = INIT_CAPITAL,
    side: int = 1,                   # +1 long, -1 short
    move_stop_to_be_after_tp1: bool = True,
) -> tuple[list[dict], pd.Series]:
    """Long/short scalp with TP1 (50%), break-even stop on remainder, TP2."""
    if len(signals) == 0:
        eq = pd.Series(init_cash, index=df.index)
        return [], eq

    n = len(df)
    op = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    idx = df.index

    eq = np.full(n, init_cash, dtype=float)
    cash = init_cash
    trades: list[dict] = []

    sigs = signals.sort_values("entry_idx")
    last_exit_i = -1

    for _, s in sigs.iterrows():
        i0 = int(s["entry_idx"])
        if i0 <= last_exit_i:
            continue  # overlap with previous in-flight trade
        entry = float(s["entry_price"])
        stop = float(s["stop"])
        tp1 = float(s["tp1"])
        tp2 = float(s["tp2"])
        max_hold = int(s["max_hold_bars"])
        if side == 1:
            risk_per_unit = entry - stop
        else:
            risk_per_unit = stop - entry
        if risk_per_unit <= 0:
            continue

        risk_dollars = cash * risk_per_trade
        qty_risk = risk_dollars / risk_per_unit
        qty_cap = (cash * leverage_cap) / entry
        qty = min(qty_risk, qty_cap)
        if qty <= 0:
            continue

        # Apply entry slippage
        entry_filled = entry * (1 + slip * side)

        # Walk forward bar-by-bar
        first_half_realized = False
        first_half_qty = qty * 0.5
        second_half_qty = qty - first_half_qty
        active_stop = stop
        bars_held = 0
        exits = []  # list of (bar_idx, exit_px, qty_part, reason)

        for j in range(i0 + 1, min(i0 + 1 + max_hold, n)):
            bars_held = j - i0
            h, l = hi[j], lo[j]
            if side == 1:
                # 1) Stop check (intra-bar)
                if l <= active_stop:
                    fill = active_stop * (1 - slip)
                    qty_left = (second_half_qty if first_half_realized else qty)
                    exits.append((j, fill, qty_left, "STOP"))
                    break
                # 2) TP1 check
                if not first_half_realized and h >= tp1:
                    fill = tp1 * (1 + slip * 0)  # limit fill, no slip benefit
                    exits.append((j, fill, first_half_qty, "TP1"))
                    first_half_realized = True
                    if move_stop_to_be_after_tp1:
                        active_stop = max(active_stop, entry_filled)
                # 3) TP2 check (only after TP1)
                if first_half_realized and h >= tp2:
                    fill = tp2
                    exits.append((j, fill, second_half_qty, "TP2"))
                    break
            else:
                # SHORT mirror
                if h >= active_stop:
                    fill = active_stop * (1 + slip)
                    qty_left = (second_half_qty if first_half_realized else qty)
                    exits.append((j, fill, qty_left, "STOP"))
                    break
                if not first_half_realized and l <= tp1:
                    fill = tp1
                    exits.append((j, fill, first_half_qty, "TP1"))
                    first_half_realized = True
                    if move_stop_to_be_after_tp1:
                        active_stop = min(active_stop, entry_filled)
                if first_half_realized and l <= tp2:
                    fill = tp2
                    exits.append((j, fill, second_half_qty, "TP2"))
                    break
        else:
            # Shot clock: time-stop at max_hold
            j = min(i0 + max_hold, n - 1)
            qty_left = (second_half_qty if first_half_realized else qty)
            exits.append((j, cl[j], qty_left, "TIME"))

        # Realize PnL from each exit leg
        total_realized = 0.0
        first_exit_idx = exits[0][0]
        last_exit_idx = exits[-1][0]
        for (j_x, fill_px, q_part, reason) in exits:
            pnl = (fill_px - entry_filled) * q_part * side
            fee_cost = q_part * (entry_filled + fill_px) * fee_per_side
            realized = pnl - fee_cost
            total_realized += realized

        cash += total_realized
        last_exit_i = last_exit_idx

        ret_pct = total_realized / max(cash - total_realized, 1.0)
        trades.append({
            "entry_time": idx[i0],
            "exit_time": idx[last_exit_idx],
            "side": side,
            "entry": entry_filled,
            "qty": qty,
            "stop": stop,
            "tp1": tp1,
            "tp2": tp2,
            "exits": exits,
            "first_reason": exits[0][3],
            "last_reason": exits[-1][3],
            "bars_held": last_exit_idx - i0,
            "realized": total_realized,
            "ret": ret_pct,
        })

        # Mark equity from i0 to last_exit_idx (linear)
        eq[i0:last_exit_idx + 1] = cash  # simplified — set to post-trade cash from entry
    # Forward-fill equity to end
    last = init_cash
    for i in range(n):
        if eq[i] != init_cash:
            last = eq[i]
        eq[i] = last
    eq_series = pd.Series(eq, index=idx, name="equity")
    return trades, eq_series


def simulate_single_target(
    df: pd.DataFrame,
    signals: pd.DataFrame,           # must have entry_idx, side, entry_price, stop, tp, max_hold_bars
    risk_per_trade: float = 0.01,
    leverage_cap: float = 5.0,
    fee_per_side: float = FEE_DEFAULT,
    slip: float = SLIP_DEFAULT,
    init_cash: float = INIT_CAPITAL,
) -> tuple[list[dict], pd.Series]:
    """Single TP / single stop / shot clock. Side comes from the signal."""
    if len(signals) == 0:
        eq = pd.Series(init_cash, index=df.index)
        return [], eq

    n = len(df)
    op = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    idx = df.index

    eq = np.full(n, init_cash, dtype=float)
    cash = init_cash
    trades: list[dict] = []

    sigs = signals.sort_values("entry_idx")
    last_exit_i = -1

    for _, s in sigs.iterrows():
        i0 = int(s["entry_idx"])
        if i0 <= last_exit_i:
            continue
        side = int(s["side"])
        entry = float(s["entry_price"])
        stop = float(s["stop"])
        tp = float(s["tp"])
        max_hold = int(s["max_hold_bars"])
        risk_per_unit = (entry - stop) if side == 1 else (stop - entry)
        if risk_per_unit <= 0:
            continue

        risk_dollars = cash * risk_per_trade
        qty = min(risk_dollars / risk_per_unit, (cash * leverage_cap) / entry)
        if qty <= 0:
            continue

        entry_filled = entry * (1 + slip * side)

        exit_idx = None
        exit_px = None
        reason = None
        for j in range(i0 + 1, min(i0 + 1 + max_hold, n)):
            h, l = hi[j], lo[j]
            if side == 1:
                if l <= stop:
                    exit_idx, exit_px, reason = j, stop * (1 - slip), "STOP"
                    break
                if h >= tp:
                    exit_idx, exit_px, reason = j, tp, "TP"
                    break
            else:
                if h >= stop:
                    exit_idx, exit_px, reason = j, stop * (1 + slip), "STOP"
                    break
                if l <= tp:
                    exit_idx, exit_px, reason = j, tp, "TP"
                    break
        if exit_idx is None:
            j = min(i0 + max_hold, n - 1)
            exit_idx, exit_px, reason = j, cl[j], "TIME"

        pnl = (exit_px - entry_filled) * qty * side
        fee_cost = qty * (entry_filled + exit_px) * fee_per_side
        realized = pnl - fee_cost
        cash += realized
        ret_pct = realized / max(cash - realized, 1.0)
        trades.append({
            "entry_time": idx[i0],
            "exit_time": idx[exit_idx],
            "side": side,
            "entry": entry_filled,
            "exit": exit_px,
            "qty": qty,
            "stop": stop,
            "tp": tp,
            "reason": reason,
            "bars_held": exit_idx - i0,
            "realized": realized,
            "ret": ret_pct,
        })
        eq[i0:exit_idx + 1] = cash
        last_exit_i = exit_idx

    last = init_cash
    for i in range(n):
        if eq[i] != init_cash:
            last = eq[i]
        eq[i] = last
    return trades, pd.Series(eq, index=idx, name="equity")


def trade_stats(trades: list[dict]) -> dict:
    if not trades:
        return dict(n=0, wr=0.0, avg_R=0.0, sum_pnl=0.0, pf=0.0, expectancy=0.0)
    rets = np.array([t["ret"] for t in trades])
    wins = rets > 0
    pf_num = rets[wins].sum() if wins.any() else 0.0
    pf_den = -rets[~wins].sum() if (~wins).any() else 0.0
    pf = pf_num / pf_den if pf_den > 0 else float("inf") if pf_num > 0 else 0.0
    sum_pnl = sum(t["realized"] for t in trades)
    return dict(
        n=len(trades),
        wr=float(wins.mean()),
        avg_R=float(rets.mean() * 100),  # avg return %
        expectancy=float(rets.mean()),
        sum_pnl=float(sum_pnl),
        pf=float(pf),
    )
