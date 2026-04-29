"""
Funding-aware simulator wrapper.

Wraps any simulator (canonical, V41 regime-adaptive, TP12, etc.) and accrues
per-bar Hyperliquid funding cost on open positions.

HL funding semantics:
  - Hourly funding settlement (4 settlements per 4h bar)
  - fundingRate is from longs' perspective: rate > 0 → longs pay shorts
  - P&L impact = -direction * notional * funding_per_bar

Strategy:
  1. Run the inner simulator to produce trades + equity (no funding)
  2. For each open-position bar, subtract funding cost from equity
  3. Re-derive cash trajectory by reapplying realized P&L minus funding

For correctness we monkey-add funding inside the per-trade ledger:
  - Funding is accrued bar-by-bar while position is open
  - At exit, funding total is netted into the trade's realized P&L
  - Equity series reflects funding-adjusted MTM at every bar

Implementation: re-implement the canonical loop with funding accrual.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from .perps_simulator import atr, FEE_DEFAULT, SLIP_DEFAULT


def simulate_with_funding(
    df: pd.DataFrame,
    long_entries: pd.Series,
    short_entries: pd.Series | None,
    funding_per_bar: pd.Series,         # SUM of hourly funding rates per 4h bar
    tp_atr: float = 10.0, sl_atr: float = 2.0,
    trail_atr: float | None = 6.0, max_hold: int = 60,
    risk_per_trade: float = 0.03, leverage_cap: float = 3.0,
    fee: float = FEE_DEFAULT, slip: float = SLIP_DEFAULT,
    init_cash: float = 10_000.0,
    size_mult=1.0,
    regime_labels: pd.Series | None = None,
    regime_exits: dict | None = None,
):
    """
    If `regime_labels` and `regime_exits` are provided, uses regime-adaptive
    exits (V41 style). Otherwise uses static (tp/sl/trail/max_hold) params.
    """
    op = df["open"].to_numpy(dtype=float); hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float);  cl = df["close"].to_numpy(dtype=float)
    at = atr(df)
    fund = funding_per_bar.reindex(df.index).fillna(0).to_numpy(dtype=float)

    sig_l = long_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
    sig_s = (short_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
             if short_entries is not None else np.zeros(len(df), dtype=bool))

    use_regime = regime_labels is not None and regime_exits is not None
    if use_regime:
        reg = regime_labels.reindex(df.index).ffill().fillna("MedVol").to_numpy(dtype=object)
    else:
        reg = None

    if isinstance(size_mult, pd.Series):
        smult = size_mult.reindex(df.index).fillna(1.0).to_numpy(dtype=float)
    else:
        smult = np.full(len(df), float(size_mult))

    N = len(df); cash = init_cash
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = 0.0; sl = 0.0; tp = 0.0
    size = 0.0; entry_idx = 0; last_exit = -9999
    hh = 0.0; ll = 0.0
    trade_sl_atr, trade_tp_atr, trade_trail_atr, trade_max_hold = sl_atr, tp_atr, trail_atr, max_hold
    trade_regime = "MedVol"
    funding_paid_this_trade = 0.0
    trades = []

    for i in range(1, N - 1):
        # Funding accrual on open positions
        if pos != 0:
            # Apply funding for this bar
            # Sign: pos=+1 (long) pays when fund>0; pos=-1 (short) receives when fund>0
            funding_pnl = -pos * size * cl[i] * fund[i]
            cash += funding_pnl
            funding_paid_this_trade += -funding_pnl  # positive number = cost to position

            held = i - entry_idx
            # Trailing
            if trade_trail_atr is not None and np.isfinite(at[i]) and at[i] > 0:
                if pos == 1:
                    hh = max(hh, hi[i])
                    new_sl = hh - trade_trail_atr * at[i]
                    if new_sl > sl: sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + trade_trail_atr * at[i]
                    if new_sl < sl: sl = new_sl

            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if   lo[i] <= sl:                 ep, reason, exited = sl*(1-slip), "SL",   True
                elif hi[i] >= tp:                 ep, reason, exited = tp*(1-slip), "TP",   True
                elif held >= trade_max_hold:      ep, reason, exited = cl[i],       "TIME", True
            else:
                if   hi[i] >= sl:                 ep, reason, exited = sl*(1+slip), "SL",   True
                elif lo[i] <= tp:                 ep, reason, exited = tp*(1+slip), "TP",   True
                elif held >= trade_max_hold:      ep, reason, exited = cl[i],       "TIME", True

            if exited:
                pnl = (ep - entry_p) * pos
                fee_cost = size * (entry_p + ep) * fee
                realized = size * pnl - fee_cost
                cash_before = cash; cash += realized
                trades.append({
                    "ret": realized / max(cash_before, 1.0),
                    "realized": realized,
                    "funding_cost": funding_paid_this_trade,
                    "reason": reason, "side": pos, "bars": held,
                    "entry": entry_p, "exit": ep,
                    "entry_idx": entry_idx, "exit_idx": i,
                    "regime": trade_regime,
                })
                pos = 0; last_exit = i
                funding_paid_this_trade = 0.0
                eq[i] = cash
                continue

        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]; take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep_new = op[i+1] * (1 + slip * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0 and ep_new > 0:
                    # Resolve exit params
                    if use_regime:
                        r_label = reg[i]
                        exit_tuple = regime_exits.get(r_label, regime_exits["MedVol"])
                        trade_sl_atr, trade_tp_atr, trade_trail_atr, trade_max_hold = exit_tuple
                        trade_regime = r_label
                    risk_dollars = cash * risk_per_trade
                    stop_dist = trade_sl_atr * at[i]
                    if stop_dist > 0:
                        size_risk = risk_dollars / stop_dist
                        size_cap  = (cash * leverage_cap) / ep_new
                        new_size  = min(size_risk, size_cap) * smult[i+1]
                        s_stop = ep_new - trade_sl_atr * at[i] * direction
                        t_stop = ep_new + trade_tp_atr * at[i] * direction
                        if new_size > 0 and np.isfinite(s_stop) and np.isfinite(t_stop):
                            pos = direction; entry_p = ep_new
                            sl = s_stop; tp = t_stop; size = new_size
                            entry_idx = i + 1; hh = ep_new; ll = ep_new
                            funding_paid_this_trade = 0.0

        eq[i] = cash if pos == 0 else cash + size * (cl[i] - entry_p) * pos

    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)
