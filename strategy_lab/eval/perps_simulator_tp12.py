"""
TP1/TP2 partial-exit simulator variant.

Extends the canonical perps_simulator.simulate() with:
  * TP1: close `tp1_frac` of position at entry ± tp1_atr * ATR
  * Trail activates on remainder after TP1 is hit (tight_trail_atr)
  * TP2: close remainder at entry ± tp2_atr * ATR
  * SL still hard at entry ± sl_atr * ATR for both halves
  * max_hold time-stop for residual

This is a richer exit stack: banks partial wins early and rides trend on the
remainder, reducing give-back from trailing stops on full position.

Contract identical to perps_simulator.simulate():
  Returns (trades, equity_series).
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from .perps_simulator import atr, FEE_DEFAULT, SLIP_DEFAULT


def simulate_tp12(
    df: pd.DataFrame,
    long_entries: pd.Series,
    short_entries: pd.Series | None = None,
    tp1_atr: float = 3.0,
    tp2_atr: float = 10.0,
    tp1_frac: float = 0.5,
    sl_atr: float = 2.0,
    trail_atr: float | None = 6.0,       # pre-TP1 trail
    tight_trail_atr: float | None = 2.5, # post-TP1 trail (tighter)
    max_hold: int = 60,
    risk_per_trade: float = 0.03,
    leverage_cap: float = 3.0,
    size_mult=1.0,
    fee: float = FEE_DEFAULT,
    slip: float = SLIP_DEFAULT,
    init_cash: float = 10_000.0,
) -> tuple[list[dict], pd.Series]:
    op = df["open"].to_numpy(dtype=float); hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float);  cl = df["close"].to_numpy(dtype=float)
    at = atr(df)

    sig_l = long_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
    sig_s = (short_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
             if short_entries is not None else np.zeros(len(df), dtype=bool))
    if isinstance(size_mult, pd.Series):
        smult = size_mult.reindex(df.index).fillna(1.0).to_numpy(dtype=float)
    else:
        smult = np.full(len(df), float(size_mult))

    N = len(df); cash = init_cash
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = 0.0; sl = 0.0
    tp1 = 0.0; tp2 = 0.0
    tp1_hit = False
    total_size = 0.0     # original size at entry
    size_rem = 0.0       # remaining size after TP1
    entry_idx = 0; last_exit = -9999
    hh = 0.0; ll = 0.0
    trades: list[dict] = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx

            # Select active trail rule
            active_trail = tight_trail_atr if tp1_hit else trail_atr
            if active_trail is not None and np.isfinite(at[i]) and at[i] > 0:
                if pos == 1:
                    hh = max(hh, hi[i])
                    new_sl = hh - active_trail * at[i]
                    if new_sl > sl:
                        sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + active_trail * at[i]
                    if new_sl < sl:
                        sl = new_sl

            # ---- TP1 partial exit (fires only once) ----
            if not tp1_hit:
                if pos == 1 and hi[i] >= tp1:
                    ep = tp1 * (1 - slip)
                    slice_size = total_size * tp1_frac
                    pnl = (ep - entry_p) * 1
                    fee_cost = slice_size * (entry_p + ep) * fee
                    realized = slice_size * pnl - fee_cost
                    cash_before = cash; cash += realized
                    trades.append({
                        "ret": realized / max(cash_before, 1.0),
                        "realized": realized, "notional": slice_size * entry_p,
                        "reason": "TP1", "side": 1, "bars": held,
                        "entry": entry_p, "exit": ep,
                        "entry_idx": entry_idx, "exit_idx": i,
                        "slice": "tp1",
                    })
                    size_rem = total_size - slice_size
                    tp1_hit = True
                elif pos == -1 and lo[i] <= tp1:
                    ep = tp1 * (1 + slip)
                    slice_size = total_size * tp1_frac
                    pnl = (ep - entry_p) * -1
                    fee_cost = slice_size * (entry_p + ep) * fee
                    realized = slice_size * pnl - fee_cost
                    cash_before = cash; cash += realized
                    trades.append({
                        "ret": realized / max(cash_before, 1.0),
                        "realized": realized, "notional": slice_size * entry_p,
                        "reason": "TP1", "side": -1, "bars": held,
                        "entry": entry_p, "exit": ep,
                        "entry_idx": entry_idx, "exit_idx": i,
                        "slice": "tp1",
                    })
                    size_rem = total_size - slice_size
                    tp1_hit = True

            # ---- Full close of remainder: SL / TP2 / TIME ----
            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if   lo[i] <= sl:            ep, reason, exited = sl*(1-slip), "SL",  True
                elif hi[i] >= tp2:           ep, reason, exited = tp2*(1-slip),"TP2", True
                elif held >= max_hold:       ep, reason, exited = cl[i], "TIME", True
            else:
                if   hi[i] >= sl:            ep, reason, exited = sl*(1+slip), "SL",  True
                elif lo[i] <= tp2:           ep, reason, exited = tp2*(1+slip),"TP2", True
                elif held >= max_hold:       ep, reason, exited = cl[i], "TIME", True

            if exited:
                closing_size = size_rem if tp1_hit else total_size
                pnl = (ep - entry_p) * pos
                fee_cost = closing_size * (entry_p + ep) * fee
                realized = closing_size * pnl - fee_cost
                cash_before = cash; cash += realized
                trades.append({
                    "ret": realized / max(cash_before, 1.0),
                    "realized": realized, "notional": closing_size * entry_p,
                    "reason": reason, "side": pos, "bars": held,
                    "entry": entry_p, "exit": ep,
                    "entry_idx": entry_idx, "exit_idx": i,
                    "slice": "remainder" if tp1_hit else "full",
                })
                pos = 0; last_exit = i
                tp1_hit = False
                size_rem = 0.0
                eq[i] = cash
                continue

        # -- open new position --
        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]; take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep_new = op[i + 1] * (1 + slip * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0 and ep_new > 0:
                    risk_dollars = cash * risk_per_trade
                    stop_dist = sl_atr * at[i]
                    if stop_dist > 0:
                        size_risk = risk_dollars / stop_dist
                        size_cap  = (cash * leverage_cap) / ep_new
                        new_size  = min(size_risk, size_cap) * smult[i+1]
                        s_stop  = ep_new - sl_atr  * at[i] * direction
                        tp1_pr  = ep_new + tp1_atr * at[i] * direction
                        tp2_pr  = ep_new + tp2_atr * at[i] * direction
                        if new_size > 0 and np.isfinite(s_stop) and np.isfinite(tp2_pr):
                            pos = direction; entry_p = ep_new
                            sl = s_stop; tp1 = tp1_pr; tp2 = tp2_pr
                            total_size = new_size; size_rem = new_size
                            tp1_hit = False
                            entry_idx = i + 1
                            hh = ep_new; ll = ep_new

        # Mark-to-market
        if pos == 0:
            eq[i] = cash
        else:
            active_size = size_rem if tp1_hit else total_size
            eq[i] = cash + active_size * (cl[i] - entry_p) * pos

    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)
