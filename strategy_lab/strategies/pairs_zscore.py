"""
Pairs / spread strategy — z-score mean-reversion on two-asset ratios.

Design:
  - ratio_t = price_A_t / price_B_t  (e.g. ETH / BTC)
  - log_ratio = log(ratio)
  - z = (log_ratio - mean_n) / std_n   over rolling N bars (causal)
  - Entry:
      z <= -z_in   => LONG  spread = +1 unit A,  -1 unit B  (ratio cheap)
      z >= +z_in   => SHORT spread = -1 unit A,  +1 unit B  (ratio rich)
  - Exit:
      |z| <= z_exit                              -> normal exit (mean reversion)
      |z| >= z_stop  in opposite direction       -> stop-out (regime break)
      held >= max_hold                           -> time stop

Per-bar PnL of an open position:
  pnl_4h = side * ( log(P_A_t / P_A_entry) - log(P_B_t / P_B_entry) )
  i.e. dollar-neutral. Trade pnl is realized at exit only (mark-to-market
  used for max-hold tracking + DD calc).

Returns: (trades_list, equity_series).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

FEE_DEFAULT = 0.0006   # 6 bps round-trip per leg (HL taker)
SLIP_DEFAULT = 0.0002  # 2 bps slippage per leg


def _rolling_z(s: pd.Series, n: int) -> pd.Series:
    mu = s.rolling(n, min_periods=n).mean()
    sd = s.rolling(n, min_periods=n).std()
    z = (s - mu) / sd
    return z.replace([np.inf, -np.inf], np.nan)


def simulate_pair(
    df_a: pd.DataFrame, df_b: pd.DataFrame,
    z_win: int = 100,
    z_in: float = 2.0,
    z_exit: float = 0.5,
    z_stop: float = 4.0,
    max_hold: int = 120,
    risk_per_trade: float = 0.03,
    init_cash: float = 10_000.0,
    fee: float = FEE_DEFAULT,
    slip: float = SLIP_DEFAULT,
) -> tuple[list[dict], pd.Series, dict]:
    """Run a z-score pair backtest on aligned 4h bars.

    Sizing: each leg sized at risk_per_trade * cash on entry, dollar-neutral
    (equal $ on each side). Cost per round-trip = 2 * (fee + slip) (4 legs total).
    """
    a = df_a["close"].astype(float)
    b = df_b["close"].astype(float)
    common = a.index.intersection(b.index)
    a = a.reindex(common); b = b.reindex(common)

    log_ratio = np.log(a / b)
    z = _rolling_z(log_ratio, z_win)

    # Pre-compute log returns for fast PnL
    la = np.log(a.values); lb = np.log(b.values)
    zv = z.values
    N = len(common)

    eq = np.empty(N); eq[0] = init_cash
    cash = init_cash
    pos = 0          # 0 / +1 long-spread / -1 short-spread
    entry_la = 0.0; entry_lb = 0.0
    entry_idx = 0
    notional = 0.0    # dollar leg size at entry
    trades: list[dict] = []

    for i in range(1, N):
        # mark-to-market unrealized
        if pos != 0:
            spread_ret = pos * ((la[i] - entry_la) - (lb[i] - entry_lb))
            mark = cash + notional * spread_ret
        else:
            mark = cash
        eq[i] = mark

        # Open / close decisions on close of bar i, executed next bar would
        # need lookahead — we use bar-i prices for exit fills (close-on-trigger),
        # which matches existing perps_simulator convention. For more
        # conservatism replace with open[i+1] fills.
        if pos != 0:
            held = i - entry_idx
            cur_z = zv[i]
            do_exit = False
            reason = None
            if not np.isnan(cur_z):
                if pos == 1 and cur_z >= -z_exit:
                    do_exit, reason = True, "tp_meanrev"
                elif pos == -1 and cur_z <= z_exit:
                    do_exit, reason = True, "tp_meanrev"
                elif pos == 1 and cur_z <= -z_stop:
                    do_exit, reason = True, "stop_extreme"
                elif pos == -1 and cur_z >= z_stop:
                    do_exit, reason = True, "stop_extreme"
            if held >= max_hold:
                do_exit, reason = True, "time_stop"

            if do_exit:
                spread_ret = pos * ((la[i] - entry_la) - (lb[i] - entry_lb))
                cost = 4 * (fee + slip)  # 2 legs in + 2 legs out
                pnl_dollar = notional * (spread_ret - cost)
                cash = cash + pnl_dollar
                trades.append({
                    "entry_idx": int(entry_idx),
                    "exit_idx":  int(i),
                    "side":      int(pos),
                    "ret":       float(spread_ret - cost),
                    "pnl":       float(pnl_dollar),
                    "held":      int(held),
                    "reason":    reason,
                })
                pos = 0
                eq[i] = cash

        if pos == 0 and i < N - 1:
            cur_z = zv[i]
            if not np.isnan(cur_z):
                if cur_z <= -z_in:
                    pos = 1
                    entry_la = la[i]; entry_lb = lb[i]
                    entry_idx = i
                    notional = risk_per_trade * cash
                elif cur_z >= z_in:
                    pos = -1
                    entry_la = la[i]; entry_lb = lb[i]
                    entry_idx = i
                    notional = risk_per_trade * cash

    eq_s = pd.Series(eq, index=common)
    diag = {
        "n_trades":      len(trades),
        "n_long":        sum(1 for t in trades if t["side"] == 1),
        "n_short":       sum(1 for t in trades if t["side"] == -1),
        "wins":          sum(1 for t in trades if t["ret"] > 0),
        "wr":            (sum(1 for t in trades if t["ret"] > 0) / max(len(trades), 1)),
        "avg_ret":       float(np.mean([t["ret"] for t in trades])) if trades else 0.0,
        "avg_held":      float(np.mean([t["held"] for t in trades])) if trades else 0.0,
        "z_distribution_min": float(np.nanmin(zv)),
        "z_distribution_max": float(np.nanmax(zv)),
    }
    return trades, eq_s, diag
