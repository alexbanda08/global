"""
Canonical per-bar perps simulator — ported verbatim from
`reports/DEPLOYMENT_BLUEPRINT.md` (the reference implementation that
produced every V22/V25/V28/V29/V30 report number).

This REPLACES vbt.Portfolio.from_signals for perps-parity runs. vbt
cannot natively simulate:
  * ATR-risk position sizing (per-bar dollar-risk / stop-distance)
  * Trailing-stop ratchet that updates on highest_high since entry
  * 2-bar cooldown between trades
  * One-position-at-a-time serial semantics
  * Both-side LS using long_entries + short_entries as two event streams
"""
from __future__ import annotations

import numpy as np
import pandas as pd


FEE_DEFAULT      = 0.00045      # Hyperliquid taker fee per fill
SLIP_DEFAULT     = 0.0003       # 3 bps slippage
FUNDING_APR      = 0.08         # 8% annualized funding drag (informational)
INIT_CAPITAL     = 10_000.0


def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    """Wilder-smoothed ATR, returned as numpy array aligned to df.index."""
    high = df["high"].to_numpy(dtype=float)
    low  = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    if len(tr) < n:
        return out
    alpha = 1.0 / n
    out[n-1] = np.nanmean(tr[:n])
    for i in range(n, len(tr)):
        out[i] = (1 - alpha) * out[i-1] + alpha * tr[i]
    return out


def simulate(
    df: pd.DataFrame,
    long_entries: pd.Series,
    short_entries: pd.Series | None = None,
    tp_atr: float = 5.0,
    sl_atr: float = 2.0,
    trail_atr: float | None = 3.5,
    max_hold: int = 72,
    risk_per_trade: float = 0.03,
    leverage_cap: float = 3.0,
    fee: float = FEE_DEFAULT,
    slip: float = SLIP_DEFAULT,
    init_cash: float = INIT_CAPITAL,
) -> tuple[list[dict], pd.Series]:
    """
    Per-bar simulator — DEPLOYMENT_BLUEPRINT.md section 3.2 verbatim.

    * Next-bar-open fills (no look-ahead)
    * ATR-risk position sizing: size = min(risk$/stopDist, lev*cash/px)
    * Hard stop at entry ± sl_atr*ATR
    * Take-profit at entry ± tp_atr*ATR
    * Trailing stop: peak(high) - trail_atr*ATR (ratcheting only)
    * Time stop at bar index >= entry_idx + max_hold
    * Cooldown: 2 bars after any exit before re-entry
    * One position at a time

    Returns (trades, equity_series).
    """
    op = df["open"].to_numpy(dtype=float)
    hi = df["high"].to_numpy(dtype=float)
    lo = df["low"].to_numpy(dtype=float)
    cl = df["close"].to_numpy(dtype=float)
    at = atr(df)

    sig_l = long_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
    if short_entries is not None:
        sig_s = short_entries.reindex(df.index).fillna(False).to_numpy(dtype=bool)
    else:
        sig_s = np.zeros(len(df), dtype=bool)

    N = len(df)
    cash = init_cash
    eq = np.empty(N); eq[0] = cash
    pos = 0
    entry_p = 0.0
    sl = 0.0
    tp = 0.0
    size = 0.0
    entry_idx = 0
    last_exit = -9999
    hh = 0.0
    ll = 0.0
    trades: list[dict] = []

    for i in range(1, N - 1):
        # -- manage open position --
        if pos != 0:
            held = i - entry_idx

            # Trailing stop ratchet
            if trail_atr is not None and np.isfinite(at[i]) and at[i] > 0:
                if pos == 1:
                    hh = max(hh, hi[i])
                    new_sl = hh - trail_atr * at[i]
                    if new_sl > sl:
                        sl = new_sl
                else:
                    ll = min(ll, lo[i]) if ll > 0 else lo[i]
                    new_sl = ll + trail_atr * at[i]
                    if new_sl < sl:
                        sl = new_sl

            # Exit check
            exited = False; ep = 0.0; reason = ""
            if pos == 1:
                if lo[i] <= sl:
                    ep = sl * (1 - slip); reason = "SL"; exited = True
                elif hi[i] >= tp:
                    ep = tp * (1 - slip); reason = "TP"; exited = True
                elif held >= max_hold:
                    ep = cl[i]; reason = "TIME"; exited = True
            else:
                if hi[i] >= sl:
                    ep = sl * (1 + slip); reason = "SL"; exited = True
                elif lo[i] <= tp:
                    ep = tp * (1 + slip); reason = "TP"; exited = True
                elif held >= max_hold:
                    ep = cl[i]; reason = "TIME"; exited = True

            if exited:
                pnl = (ep - entry_p) * pos
                fee_cost = size * (entry_p + ep) * fee
                realized = size * pnl - fee_cost
                notional = size * entry_p
                eq_at_entry = cash
                cash += realized
                ret = realized / max(eq_at_entry, 1.0)
                trades.append({
                    "ret": ret, "realized": realized, "notional": notional,
                    "reason": reason, "side": pos, "bars": held,
                    "entry": entry_p, "exit": ep,
                    "entry_idx": entry_idx, "exit_idx": i,
                })
                pos = 0; last_exit = i
                eq[i] = cash
                continue

        # -- open new position --
        if pos == 0 and (i - last_exit) > 2 and i + 1 < N:
            take_long = sig_l[i]
            take_short = sig_s[i]
            if take_long or take_short:
                direction = 1 if take_long else -1
                ep_new = op[i + 1] * (1 + slip * direction)
                if np.isfinite(at[i]) and at[i] > 0 and cash > 0 and ep_new > 0:
                    risk_dollars = cash * risk_per_trade
                    stop_dist = sl_atr * at[i]
                    if stop_dist > 0:
                        size_risk = risk_dollars / stop_dist
                        size_cap = (cash * leverage_cap) / ep_new
                        new_size = min(size_risk, size_cap)
                        s_stop = ep_new - sl_atr * at[i] * direction
                        t_stop = ep_new + tp_atr * at[i] * direction
                        if new_size > 0 and np.isfinite(s_stop) and np.isfinite(t_stop):
                            pos = direction
                            entry_p = ep_new; sl = s_stop; tp = t_stop
                            size = new_size
                            entry_idx = i + 1
                            hh = ep_new; ll = ep_new

        # Mark-to-market
        if pos == 0:
            eq[i] = cash
        else:
            eq[i] = cash + size * (cl[i] - entry_p) * pos

    eq[-1] = eq[-2]
    return trades, pd.Series(eq, index=df.index)


def compute_metrics(label: str, equity: pd.Series, trades: list[dict],
                    bars_per_year: float) -> dict:
    """Extract Sharpe / Calmar / MDD / CAGR / win-rate from simulate() output."""
    n = len(trades)
    if n < 2:
        return {"label": label, "n_trades": n, "sharpe": 0.0, "cagr": 0.0,
                "max_dd": 0.0, "calmar": 0.0, "win_rate": 0.0,
                "final_equity": float(equity.iloc[-1]) if len(equity) else INIT_CAPITAL}
    rets = equity.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sharpe = (mu / sd) * np.sqrt(bars_per_year) if sd > 0 else 0.0
    peak = equity.cummax()
    mdd = float((equity / peak - 1.0).min())
    years = (equity.index[-1] - equity.index[0]).total_seconds() / (365.25 * 86400)
    total = float(equity.iloc[-1] / equity.iloc[0]) - 1.0
    cagr = (1 + total) ** (1 / max(years, 1e-6)) - 1.0
    calmar = cagr / abs(mdd) if mdd != 0 else 0.0
    win_rate = sum(1 for t in trades if t.get("ret", 0) > 0) / n

    # Per-year breakdown
    per_year = {}
    for yr in sorted(set(equity.index.year)):
        eq_y = equity[equity.index.year == yr]
        if len(eq_y) < 30:
            continue
        r = eq_y.pct_change().dropna()
        sd_y = float(r.std())
        s = (float(r.mean()) / sd_y) * np.sqrt(bars_per_year) if sd_y > 0 else 0.0
        per_year[int(yr)] = {
            "sharpe": round(s, 3),
            "return": round(float(eq_y.iloc[-1] / eq_y.iloc[0] - 1), 4),
        }

    return {
        "label": label, "n_trades": n,
        "sharpe": round(sharpe, 3), "cagr": round(cagr, 4),
        "max_dd": round(mdd, 4), "calmar": round(calmar, 3),
        "win_rate": round(win_rate, 3),
        "final_equity": round(float(equity.iloc[-1]), 2),
        "per_year": per_year,
    }
