"""
Validate the winning portfolio V2B_volume_breakout 4h @ 60/25/15.

Tests:
  1. Per-year performance breakdown (robustness across regimes)
  2. Parameter sensitivity grid (curve-fit check)
  3. Walk-forward: 2-year rolling Sharpe of the portfolio

Produces one CSV + printed summary per test.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

from strategy_lab import engine, portfolio
from strategy_lab.strategies_v2 import volume_breakout_v2

OUT = Path(__file__).resolve().parent / "results"

ALLOC = {"BTCUSDT": 0.60, "ETHUSDT": 0.25, "SOLUSDT": 0.15}
SYMS  = list(ALLOC.keys())
TF    = "4h"
START = "2018-01-01"
END   = "2026-04-01"


# ---------------------------------------------------------------------
# 1. Per-year breakdown
# ---------------------------------------------------------------------
def per_year_report():
    combo = {s: ("V2B_volume_breakout", TF) for s in SYMS}
    r = portfolio.run_combined(combo, allocation=ALLOC, tag="WINNER_full",
                               start=START, end=END)

    eq = pd.read_csv(OUT / "WINNER_full_equity.csv", index_col=0, parse_dates=True)
    bh = pd.read_csv(OUT / "WINNER_full_bh_equity.csv", index_col=0, parse_dates=True)

    strat_eq = eq["portfolio_equity"].copy()
    bh_eq    = bh["bh_equity"].copy()

    rows = []
    for year in range(2018, 2027):
        s = pd.Timestamp(f"{year}-01-01", tz="UTC")
        e = pd.Timestamp(f"{year}-12-31 23:59", tz="UTC")
        ey = strat_eq[(strat_eq.index >= s) & (strat_eq.index <= e)]
        by = bh_eq[(bh_eq.index >= s) & (bh_eq.index <= e)]
        if len(ey) < 10:
            continue

        ret = ey.iloc[-1] / ey.iloc[0] - 1.0
        bhr = by.iloc[-1] / by.iloc[0] - 1.0
        dd  = float(((ey / ey.cummax()) - 1.0).min())
        rows.append({
            "year":   year,
            "ret":    round(ret, 3),
            "dd":     round(dd, 3),
            "bh_ret": round(bhr, 3),
        })

    df = pd.DataFrame(rows)
    print("\n=== PER-YEAR PERFORMANCE (Winner: V2B 4h @ 60/25/15) ===")
    print(df.to_string(index=False))
    df.to_csv(OUT / "WINNER_per_year.csv", index=False)
    return df


# ---------------------------------------------------------------------
# 2. Parameter sensitivity grid
# ---------------------------------------------------------------------
def parameter_sensitivity():
    """Small grid to check whether winner is curve-fit or stable."""
    grid = list(itertools.product(
        [15, 20, 25, 30],        # don_len
        [1.3, 1.5, 1.8],         # vol_mult
        [150, 200, 250],         # regime_len
        [2.5, 3.5, 4.5],         # tsl_atr
    ))
    rows = []
    for don_len, vol_mult, regime_len, tsl_atr in grid:
        combo_fns = {}
        # pre-build with these params (via custom signal fn)
        cagrs, dds = [], []
        sub_returns = []
        for sym in SYMS:
            df = engine.load(sym, TF, START, END)
            sig = volume_breakout_v2(df, don_len=don_len, vol_mult=vol_mult,
                                     regime_len=regime_len, tsl_atr=tsl_atr)
            init = ALLOC[sym] * engine.TOTAL_CAPITAL
            res = engine.run_backtest(
                df,
                entries=sig["entries"], exits=sig["exits"],
                sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
                init_cash=init,
                label=f"V2B_{don_len}_{vol_mult}_{regime_len}_{tsl_atr}|{sym}",
            )
            eq = res.pf.value()
            sub_returns.append(eq)

        port = pd.concat(sub_returns, axis=1).ffill().fillna(method="bfill").sum(axis=1)
        pm = engine.portfolio_metrics(port)
        rows.append({
            "don_len": don_len, "vol_mult": vol_mult,
            "regime_len": regime_len, "tsl_atr": tsl_atr,
            "cagr": round(pm["cagr"], 3),
            "sharpe": round(pm["sharpe"], 3),
            "max_dd": round(pm["max_dd"], 3),
            "calmar": round(pm["calmar"], 3),
            "final": round(pm["final"], 0),
        })

    df = pd.DataFrame(rows).sort_values("calmar", ascending=False)
    df.to_csv(OUT / "WINNER_param_sensitivity.csv", index=False)
    print("\n=== PARAMETER SENSITIVITY GRID (108 combinations) ===")
    print(f"stability summary -> CAGR range: [{df.cagr.min():.2%}, {df.cagr.max():.2%}]")
    print(f"                    Calmar range: [{df.calmar.min():.2f}, {df.calmar.max():.2f}]")
    print(f"                    MaxDD range: [{df.max_dd.min():.2%}, {df.max_dd.max():.2%}]")
    print()
    print("TOP 10:")
    print(df.head(10).to_string(index=False))
    print()
    print("BOTTOM 5:")
    print(df.tail(5).to_string(index=False))
    return df


# ---------------------------------------------------------------------
# 3. Rolling 1-year Sharpe
# ---------------------------------------------------------------------
def rolling_year_sharpe():
    eq = pd.read_csv(OUT / "WINNER_full_equity.csv", index_col=0, parse_dates=True)["portfolio_equity"]
    rets = eq.pct_change().dropna()
    dt = rets.index.to_series().diff().median()
    bars_per_year = pd.Timedelta(days=365.25) / dt
    window = int(bars_per_year)
    rolling_sharpe = (rets.rolling(window).mean() / rets.rolling(window).std()) * np.sqrt(bars_per_year)
    rolling_sharpe = rolling_sharpe.dropna()
    print("\n=== ROLLING 1-YEAR SHARPE ===")
    print(f"  min:  {rolling_sharpe.min():.2f}")
    print(f"  25th: {rolling_sharpe.quantile(0.25):.2f}")
    print(f"  med:  {rolling_sharpe.median():.2f}")
    print(f"  75th: {rolling_sharpe.quantile(0.75):.2f}")
    print(f"  max:  {rolling_sharpe.max():.2f}")
    print(f"  % windows > 0: {(rolling_sharpe > 0).mean():.1%}")
    rolling_sharpe.to_csv(OUT / "WINNER_rolling_sharpe.csv")


if __name__ == "__main__":
    per_year_report()
    parameter_sensitivity()
    rolling_year_sharpe()
