"""
Advanced bar-by-bar simulator supporting:

  * Initial SL (fraction of entry price, or per-bar series)
  * Three-level TP ladder (tp1/tp2/tp3 — each with level pct + close fraction)
  * Ratcheting SL:
        after TP1 hit  -> SL moves to breakeven (entry_px × (1 + slip_buffer))
        after TP2 hit  -> SL moves to TP1 price
  * Post-TP2 trailing stop (Chandelier-style, ATR-scaled distance)
  * Signal-based exit for any remaining position
  * Per-side maker fee + zero slip (limit-order model)

One position at a time per symbol.  Returns equity series + trade log
with sub-exit breakdown so we can later measure partial-exit capture.

This is intentionally separate from portfolio_audit.simulate() (which
only handles a single exit) so legacy V2-V7 strategies are untouched.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

FEE  = 0.00015   # Hyperliquid maker
SLIP = 0.0       # limit-order model


def _as_arr(x, n):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return np.full(n, float(x))
    if isinstance(x, pd.Series):
        return x.ffill().fillna(0).to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def simulate_advanced(df: pd.DataFrame,
                      entries: pd.Series,
                      exits: pd.Series | None = None,
                      sl_pct=None,
                      tp1_pct=None, tp1_frac: float = 0.40,
                      tp2_pct=None, tp2_frac: float = 0.30,
                      tp3_pct=None, tp3_frac: float = 0.30,
                      trail_pct=None,          # activates after TP2 hit
                      move_sl_on_tp1: bool = True,
                      move_sl_on_tp2: bool = True,
                      init: float = 10_000.0) -> tuple[pd.Series, list[dict]]:
    n = len(df)
    e_arr = np.asarray(entries.astype("boolean").shift(1).fillna(False), dtype=bool)
    if exits is None:
        x_arr = np.zeros(n, dtype=bool)
    else:
        x_arr = np.asarray(exits.astype("boolean").shift(1).fillna(False), dtype=bool)

    sl   = _as_arr(sl_pct,   n)
    tp1  = _as_arr(tp1_pct,  n)
    tp2  = _as_arr(tp2_pct,  n)
    tp3  = _as_arr(tp3_pct,  n)
    trail = _as_arr(trail_pct, n)

    op = df["open"].values
    hi = df["high"].values
    lo = df["low"].values
    cl = df["close"].values

    cash = init
    eq = np.empty(n); eq[0] = cash

    # Position state
    in_pos = False
    entry_idx = -1
    entry_p = 0.0
    remaining = 0.0     # shares remaining (of the full initial size)
    initial_size = 0.0
    sl_price = -np.inf
    tp1_price = tp2_price = tp3_price = np.inf
    tp1_hit = tp2_hit = tp3_hit = False
    peak = 0.0
    trail_price = -np.inf
    sub_exits = []      # list of (ts, reason, frac, px)

    trades = []

    def close_rest(i, px, reason):
        nonlocal cash, remaining, in_pos, entry_idx, entry_p, sub_exits
        nonlocal tp1_hit, tp2_hit, tp3_hit, peak, trail_price, initial_size
        nonlocal sl_price, tp1_price, tp2_price, tp3_price
        if remaining <= 0:
            return
        gross = remaining * px
        fee   = gross * FEE
        cash += gross - fee
        sub_exits.append({"ts": df.index[i], "reason": reason,
                          "frac": remaining / initial_size, "px": px,
                          "ret": (px / entry_p - 1)})
        # Finalise the trade record
        total_pnl = 0.0
        gross_exit_value = 0.0
        for s in sub_exits:
            sold = initial_size * s["frac"]
            total_pnl += sold * (s["px"] - entry_p)
            gross_exit_value += sold * s["px"]
        trade_ret = (gross_exit_value - initial_size * entry_p) / (initial_size * entry_p)
        trades.append({
            "entry_idx": entry_idx, "exit_idx": i,
            "entry_time": df.index[entry_idx], "exit_time": df.index[i],
            "entry_price": entry_p,
            "tp1_hit": tp1_hit, "tp2_hit": tp2_hit, "tp3_hit": tp3_hit,
            "final_reason": reason,
            "bars_held": i - entry_idx,
            "return": trade_ret,          # fractional return on the trade
            "n_sub_exits": len(sub_exits),
            "sub_exits": sub_exits.copy(),
        })
        # Reset
        remaining = 0.0; initial_size = 0.0
        in_pos = False; entry_p = 0.0; entry_idx = -1
        sl_price = -np.inf
        tp1_price = tp2_price = tp3_price = np.inf
        tp1_hit = tp2_hit = tp3_hit = False
        peak = 0.0; trail_price = -np.inf
        sub_exits = []

    def partial_close(i, px, reason, frac):
        nonlocal cash, remaining, sub_exits
        sold = initial_size * frac
        if sold > remaining + 1e-12:
            sold = remaining
        gross = sold * px
        fee = gross * FEE
        cash += gross - fee
        remaining -= sold
        sub_exits.append({"ts": df.index[i], "reason": reason,
                          "frac": frac, "px": px,
                          "ret": (px / entry_p - 1)})

    for i in range(n):
        # ---------- process exits first within bar ----------
        if in_pos:
            # update trail if active (post-TP2)
            if tp2_hit and trail is not None and trail[i] > 0:
                peak = max(peak, hi[i])
                cand = peak * (1 - trail[i])
                if cand > trail_price:
                    trail_price = cand

            # hard SL
            if sl_price > 0 and lo[i] <= sl_price:
                close_rest(i, sl_price, "SL")
            # trail stop (active only after TP2)
            elif tp2_hit and trail_price > 0 and lo[i] <= trail_price:
                close_rest(i, trail_price, "TRAIL")
            else:
                # TP1
                if not tp1_hit and tp1_price < np.inf and hi[i] >= tp1_price:
                    partial_close(i, tp1_price, "TP1", tp1_frac)
                    tp1_hit = True
                    if move_sl_on_tp1:
                        sl_price = max(sl_price, entry_p)  # move to breakeven
                # TP2
                if not tp2_hit and tp2_price < np.inf and hi[i] >= tp2_price:
                    partial_close(i, tp2_price, "TP2", tp2_frac)
                    tp2_hit = True
                    if move_sl_on_tp2:
                        sl_price = max(sl_price, tp1_price if tp1_price < np.inf else entry_p)
                    # initialise trail from TP2 level
                    peak = max(peak, hi[i])
                    if trail is not None and trail[i] > 0:
                        trail_price = peak * (1 - trail[i])
                # TP3
                if not tp3_hit and tp3_price < np.inf and hi[i] >= tp3_price:
                    # if no trailing is set, close the remainder here
                    if trail is None or (trail is not None and trail[i] == 0):
                        close_rest(i, tp3_price, "TP3")
                    else:
                        partial_close(i, tp3_price, "TP3", tp3_frac)
                        tp3_hit = True

                # signal-based exit (closes whatever remains)
                if in_pos and x_arr[i]:
                    close_rest(i, op[i], "SIG")

        # ---------- entries (after exits) ----------
        if not in_pos and e_arr[i] and i < n - 1:
            px = op[i] * (1 + SLIP)
            # Use all cash (single-position within this simulator per coin).
            size = cash / px
            cost = size * px
            fee  = cost * FEE
            cash -= (cost + fee)
            in_pos = True
            entry_idx = i
            entry_p   = px
            initial_size = size
            remaining    = size
            peak = px
            sub_exits = []
            # Set SL / TPs using per-bar series if provided
            if sl is not None and not np.isnan(sl[i]) and sl[i] > 0:
                sl_price = px * (1 - sl[i])
            if tp1 is not None and not np.isnan(tp1[i]) and tp1[i] > 0:
                tp1_price = px * (1 + tp1[i])
            if tp2 is not None and not np.isnan(tp2[i]) and tp2[i] > 0:
                tp2_price = px * (1 + tp2[i])
            if tp3 is not None and not np.isnan(tp3[i]) and tp3[i] > 0:
                tp3_price = px * (1 + tp3[i])
            tp1_hit = tp2_hit = tp3_hit = False
            trail_price = -np.inf

        # ---------- mark-to-market ----------
        eq[i] = cash + remaining * cl[i]

    # Close any open position at the end
    if in_pos:
        close_rest(n - 1, cl[-1], "EOD")
        eq[-1] = cash

    return pd.Series(eq, index=df.index, name="equity"), trades
