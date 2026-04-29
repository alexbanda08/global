"""
V41 Regime-Adaptive Exit Simulator
===================================
Same entry contract as canonical simulate() — but TP/SL/trail/max_hold are
set PER ENTRY based on the regime label at that bar.

The entry signals are unchanged (consumer plugs in any V30 strategy's
long_entries/short_entries). Only the exit stack adapts to regime.

Regime-specific exit profiles (rationale):
  LowVol   : tight SL (1.5x ATR), loose TP (12x), long trail (8x), longer hold (80)
             -> ride quiet steady trends
  MedLowVol: SL 1.8, TP 11, trail 7, hold 70
  MedVol   : SL 2.0, TP 10, trail 6, hold 60  (== canonical EXIT_4H)
  MedHighVol: SL 2.3, TP 8, trail 4, hold 40
  HighVol  : SL 2.5, TP 6, trail 2.5, hold 24
             -> fast moves, bank profits before reversion
  Uncertain/Warming: canonical exits

The idea: in LowVol we give trades room to breathe; in HighVol we bank quickly
because reversion risk is higher.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from .perps_simulator import atr, FEE_DEFAULT, SLIP_DEFAULT


# Per-regime exit profiles: (sl_atr, tp_atr, trail_atr, max_hold)
REGIME_EXITS_4H = {
    "LowVol":      (1.5, 12.0, 8.0, 80),
    "MedLowVol":   (1.8, 11.0, 7.0, 70),
    "MedVol":      (2.0, 10.0, 6.0, 60),
    "MedHighVol":  (2.3,  8.0, 4.0, 40),
    "HighVol":     (2.5,  6.0, 2.5, 24),
    "Uncertain":   (2.0, 10.0, 6.0, 60),
    "Warming":     (2.0, 10.0, 6.0, 60),
}


def simulate_adaptive_exit(
    df: pd.DataFrame,
    long_entries: pd.Series,
    short_entries: pd.Series | None,
    regime_labels: pd.Series,
    regime_exits: dict = None,
    size_mult=1.0,
    risk_per_trade: float = 0.03,
    leverage_cap: float = 3.0,
    fee: float = FEE_DEFAULT,
    slip: float = SLIP_DEFAULT,
    init_cash: float = 10_000.0,
) -> tuple[list[dict], pd.Series]:
    """
    Canonical simulator + per-bar regime-dependent exit params.
    At entry, looks up the regime label for that bar and fixes the trade's
    TP/SL/trail/max_hold for its lifetime.
    """
    if regime_exits is None:
        regime_exits = REGIME_EXITS_4H

    op = df["open"].to_numpy(dtype=float); hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float);  cl = df["close"].to_numpy(dtype=float)
    at = atr(df)

    sig_l = long_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
    sig_s = (short_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
             if short_entries is not None else np.zeros(len(df), dtype=bool))
    reg = regime_labels.reindex(df.index).ffill().fillna("MedVol").to_numpy(dtype=object)

    if isinstance(size_mult, pd.Series):
        smult = size_mult.reindex(df.index).fillna(1.0).to_numpy(dtype=float)
    else:
        smult = np.full(len(df), float(size_mult))

    N = len(df); cash = init_cash
    eq = np.empty(N); eq[0] = cash
    pos = 0; entry_p = 0.0
    sl = 0.0; tp = 0.0
    trade_sl_atr = 2.0; trade_tp_atr = 10.0
    trade_trail_atr = 6.0; trade_max_hold = 60
    trade_regime = "MedVol"
    size = 0.0; entry_idx = 0; last_exit = -9999
    hh = 0.0; ll = 0.0
    trades: list[dict] = []

    for i in range(1, N - 1):
        if pos != 0:
            held = i - entry_idx

            # trailing stop using TRADE's trail param
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
                if   lo[i] <= sl:           ep, reason, exited = sl*(1-slip), "SL",  True
                elif hi[i] >= tp:           ep, reason, exited = tp*(1-slip), "TP",  True
                elif held >= trade_max_hold: ep, reason, exited = cl[i], "TIME", True
            else:
                if   hi[i] >= sl:           ep, reason, exited = sl*(1+slip), "SL",  True
                elif lo[i] <= tp:           ep, reason, exited = tp*(1+slip), "TP",  True
                elif held >= trade_max_hold: ep, reason, exited = cl[i], "TIME", True

            if exited:
                pnl = (ep - entry_p) * pos
                fee_cost = size * (entry_p + ep) * fee
                realized = size * pnl - fee_cost
                cash_before = cash; cash += realized
                trades.append({
                    "ret": realized / max(cash_before, 1.0),
                    "realized": realized,
                    "reason": reason, "side": pos, "bars": held,
                    "entry": entry_p, "exit": ep,
                    "entry_idx": entry_idx, "exit_idx": i,
                    "regime": trade_regime,
                })
                pos = 0; last_exit = i
                eq[i] = cash
                continue

        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]; take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep_new = op[i+1] * (1 + slip * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0 and ep_new > 0:
                    # Resolve regime-specific exit params
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

        eq[i] = cash if pos == 0 else cash + size * (cl[i] - entry_p) * pos

    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)
