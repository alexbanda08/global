"""
Fast TV-style detailed metric extractor.

Replaces the slow groupby-based version. All trade/equity stats are
vectorised numpy ops — runs in seconds on 18k-bar equity curves.

Emits JSON to strategy_lab/results/detailed_tv_metrics.json with per-asset
fields matching the TradingView Strategy Tester "Performance" layout.
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

from strategy_lab import engine
from strategy_lab.strategies_v2 import STRATEGIES_V2
from strategy_lab.strategies_v3 import STRATEGIES_V3
from strategy_lab.strategies_v4 import STRATEGIES_V4

ALL = {**STRATEGIES_V2, **STRATEGIES_V3, **STRATEGIES_V4}
OUT = Path(__file__).resolve().parent / "results"

WINNERS = {
    "BTCUSDT": ("V4C_range_kalman",    "4h"),
    "ETHUSDT": ("V3B_adx_gate",        "4h"),
    "SOLUSDT": ("V2B_volume_breakout", "4h"),
}
INIT = 10_000.0
START, END = "2018-01-01", "2026-04-01"


def _consec(pnl: np.ndarray):
    mw = cw = ml = cl = 0
    for p in pnl:
        if p > 0:
            cw += 1; cl = 0
        elif p < 0:
            cl += 1; cw = 0
        else:
            cw = cl = 0
        mw = max(mw, cw); ml = max(ml, cl)
    return mw, ml


def _dd_stats(eq: np.ndarray):
    """Vectorised: max DD and average DD depth + duration over episodes.
       Episodes = contiguous stretches where equity < running peak."""
    peak = np.maximum.accumulate(eq)
    dd   = eq / peak - 1.0                     # <= 0
    in_dd = dd < 0
    if not in_dd.any():
        return dict(max_dd_pct=0.0, max_dd_usd=0.0,
                    avg_dd_pct=0.0, avg_dd_usd=0.0,
                    n_episodes=0, avg_dd_bars=0.0)
    # Episode ids: increment at each new peak
    ep_id = np.cumsum(~in_dd)                  # each "above-peak" starts new ep
    mask  = in_dd
    ids   = ep_id[mask]
    # Find min dd and duration per episode
    uniq, first_idx, counts = np.unique(ids, return_index=True, return_counts=True)
    depths_pct = np.minimum.reduceat(dd[mask], first_idx)
    depths_usd = np.maximum.reduceat((peak - eq)[mask], first_idx)
    return dict(
        max_dd_pct = float(depths_pct.min()),
        max_dd_usd = float(depths_usd.max()),
        avg_dd_pct = float(depths_pct.mean()),
        avg_dd_usd = float(depths_usd.mean()),
        n_episodes = int(len(uniq)),
        avg_dd_bars = float(counts.mean()),
    )


def _ru_stats(eq: np.ndarray):
    trough = np.minimum.accumulate(eq)
    ru     = eq / trough - 1.0
    mask   = ru > 0
    if not mask.any():
        return dict(max_ru_pct=0.0, max_ru_usd=0.0,
                    avg_ru_pct=0.0, avg_ru_usd=0.0,
                    n_episodes=0, avg_ru_bars=0.0)
    ep_id = np.cumsum(~mask)
    ids = ep_id[mask]
    uniq, first_idx, counts = np.unique(ids, return_index=True, return_counts=True)
    peaks_pct = np.maximum.reduceat(ru[mask], first_idx)
    peaks_usd = np.maximum.reduceat((eq - trough)[mask], first_idx)
    return dict(
        max_ru_pct = float(peaks_pct.max()),
        max_ru_usd = float(peaks_usd.max()),
        avg_ru_pct = float(peaks_pct.mean()),
        avg_ru_usd = float(peaks_usd.mean()),
        n_episodes = int(len(uniq)),
        avg_ru_bars = float(counts.mean()),
    )


def extract(sym: str, strat: str, tf: str) -> dict:
    df = engine.load(sym, tf, START, END)
    sig = ALL[strat](df)
    res = engine.run_backtest(
        df,
        entries=sig["entries"], exits=sig["exits"],
        short_entries=sig.get("short_entries"),
        short_exits=sig.get("short_exits"),
        sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
        init_cash=INIT, label=f"{strat}|{sym}",
    )
    pf = res.pf
    tr = pf.trades.records_readable
    tr = tr.rename(columns=lambda c: c.strip())

    pnl_usd = tr["PnL"].astype(float).values
    pnl_pct = tr["Return"].astype(float).values
    size    = tr["Size"].astype(float).values
    ep_idx  = tr["Entry Idx"].astype(int).values
    ex_idx  = tr["Exit Idx"].astype(int).values
    entry_p = tr["Avg Entry Price"].astype(float).values
    dur     = ex_idx - ep_idx

    wins_m, loss_m, be_m = pnl_usd > 0, pnl_usd < 0, pnl_usd == 0
    wins, losses         = pnl_usd[wins_m], pnl_usd[loss_m]
    wins_pct, losses_pct = pnl_pct[wins_m], pnl_pct[loss_m]

    gp, gl = float(wins.sum()), float(losses.sum())
    net    = float(pnl_usd.sum())

    # Commissions = 2 * fee * |entry_value|  (enter + exit, exit value ≈ entry for small bars)
    commissions = float(engine.FEE * 2 * np.abs(entry_p * size).sum())

    eq_v = pf.value().values.astype(float)
    dd  = _dd_stats(eq_v)
    ru  = _ru_stats(eq_v)

    mcw, mcl = _consec(pnl_usd)
    n = len(pnl_usd)

    return dict(
        symbol=sym, strategy=strat, timeframe=tf,
        period=f"{START} -> {END}",
        initial_capital=INIT,
        final_equity=float(eq_v[-1]),
        total_pnl_usd=float(eq_v[-1] - INIT),
        total_pnl_pct=float(eq_v[-1] / INIT - 1),
        cagr=res.metrics["cagr"],
        sharpe=res.metrics["sharpe"],
        sortino=res.metrics["sortino"],
        calmar=res.metrics["calmar"],

        n_trades=int(n),
        n_wins=int(wins_m.sum()),
        n_losses=int(loss_m.sum()),
        n_break_even=int(be_m.sum()),
        win_rate=float(wins_m.mean()) if n else 0.0,
        loss_rate=float(loss_m.mean()) if n else 0.0,
        profit_factor=(gp / abs(gl)) if gl else 0.0,
        commissions_usd=commissions,
        gross_profit_usd=gp,
        gross_loss_usd=gl,

        avg_win_usd=float(wins.mean())   if wins.size   else 0.0,
        avg_win_pct=float(wins_pct.mean())   if wins_pct.size   else 0.0,
        avg_loss_usd=float(losses.mean()) if losses.size else 0.0,
        avg_loss_pct=float(losses_pct.mean()) if losses_pct.size else 0.0,
        avg_pnl_usd=float(pnl_usd.mean()) if n else 0.0,
        avg_pnl_pct=float(pnl_pct.mean()) if n else 0.0,
        win_loss_ratio=(float(wins.mean()) / abs(float(losses.mean())))
                        if wins.size and losses.size and losses.mean() != 0 else 0.0,

        largest_win_usd=float(wins.max())  if wins.size else 0.0,
        largest_win_pct=float(wins_pct.max())  if wins_pct.size else 0.0,
        largest_loss_usd=float(abs(losses.min())) if losses.size else 0.0,
        largest_loss_pct=float(abs(losses_pct.min())) if losses_pct.size else 0.0,
        largest_win_of_gross=(float(wins.max()) / gp) if gp and wins.size else 0.0,
        largest_loss_of_gross=(float(abs(losses.min())) / abs(gl)) if gl and losses.size else 0.0,

        avg_bars_all=float(dur.mean()) if n else 0.0,
        avg_bars_win=float(dur[wins_m].mean())   if wins_m.any()   else 0.0,
        avg_bars_loss=float(dur[loss_m].mean()) if loss_m.any()   else 0.0,
        max_consec_wins=int(mcw),
        max_consec_losses=int(mcl),

        max_dd_close_pct=dd["max_dd_pct"],
        max_dd_close_usd=dd["max_dd_usd"],
        avg_dd_pct=dd["avg_dd_pct"],
        avg_dd_usd=dd["avg_dd_usd"],
        n_dd_episodes=dd["n_episodes"],
        avg_dd_bars=dd["avg_dd_bars"],

        max_ru_close_pct=ru["max_ru_pct"],
        max_ru_close_usd=ru["max_ru_usd"],
        avg_ru_pct=ru["avg_ru_pct"],
        avg_ru_usd=ru["avg_ru_usd"],
        n_ru_episodes=ru["n_episodes"],
        avg_ru_bars=ru["avg_ru_bars"],

        account_size_required=dd["max_dd_usd"],
        return_on_asr=(net / dd["max_dd_usd"]) if dd["max_dd_usd"] else 0.0,
        net_profit_over_largest_loss=(net / float(abs(losses.min()))) if losses.size else 0.0,
    )


def main():
    out = {}
    for sym, (strat, tf) in WINNERS.items():
        rep = extract(sym, strat, tf)
        out[sym] = rep
        print(f"{sym}  n={rep['n_trades']}  W={rep['n_wins']}/{rep['n_losses']}  "
              f"PF={rep['profit_factor']:.2f}  "
              f"avgW={rep['avg_win_pct']*100:+.2f}%  avgL={rep['avg_loss_pct']*100:+.2f}%  "
              f"DD={rep['max_dd_close_pct']*100:+.2f}%  "
              f"final=${rep['final_equity']:,.0f}")
    (OUT / "detailed_tv_metrics.json").write_text(json.dumps(out, default=str, indent=2))
    print("Saved detailed_tv_metrics.json")


if __name__ == "__main__":
    main()
