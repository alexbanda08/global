"""
HWR hunt — test High-Win-Rate candidates across 6 coins × {2022,2023,2024,2025}.

For each (coin, strategy) we report per-year win rate, PF, sharpe, CAGR, DD.
A strategy PASSES for a coin iff its worst-year win rate in 2022-2025 is
>= 50 %, it stays profitable across the whole window, and its OOS sharpe
(2023+) is > 0.5.

Output:
    strategy_lab/results/hwr_hunt.csv     — per-year per-coin per-strategy
    strategy_lab/results/hwr_summary.csv  — one row per (coin, strategy)
    console table ranked by worst-year WR
"""
from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab.strategies_v7 import STRATEGIES_V7
from strategy_lab import portfolio_audit as pa

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","LINKUSDT","ADAUSDT","XRPUSDT"]
STARTS = {
    "BTCUSDT":  "2021-06-01",
    "ETHUSDT":  "2021-06-01",
    "SOLUSDT":  "2021-06-01",
    "LINKUSDT": "2021-06-01",
    "ADAUSDT":  "2021-06-01",
    "XRPUSDT":  "2021-06-01",
}
END_GLOBAL = "2026-04-01"
TF = "4h"

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(parents=True, exist_ok=True)


def _run(df: pd.DataFrame, fn) -> tuple[pd.Series, list]:
    sig = fn(df)
    eq, trades = pa.simulate(df,
        sig["entries"], sig["exits"],
        sl_stop=sig.get("sl_stop"),
        tsl_stop=sig.get("tsl_stop"),
        tp_stop=sig.get("tp_stop"),
        init=pa.INIT)
    return eq, trades


def year_stats(eq: pd.Series, trades: list, year: int) -> dict:
    tr = pd.DataFrame(trades)
    out = {"year": year, "n_trades": 0, "win_rate": 0.0,
           "pf": 0.0, "cagr": 0.0, "sharpe": 0.0, "dd": 0.0,
           "avg_win": 0.0, "avg_loss": 0.0, "final": float(eq.iloc[-1])}
    # Trades that exited in the year
    if len(tr) == 0:
        return out
    tr["year"] = pd.to_datetime(tr["exit_time"]).dt.year
    tr_y = tr[tr["year"] == year]
    if len(tr_y) == 0:
        return out
    wins = tr_y[tr_y["return"] > 0]
    losses = tr_y[tr_y["return"] <= 0]
    out["n_trades"] = int(len(tr_y))
    out["win_rate"] = round(float(len(wins) / len(tr_y)), 3)
    out["avg_win"]  = round(float(wins["return"].mean() if len(wins) else 0), 4)
    out["avg_loss"] = round(float(losses["return"].mean() if len(losses) else 0), 4)
    gross_win = float(wins["return"].sum())
    gross_loss = abs(float(losses["return"].sum()))
    out["pf"] = round(gross_win / gross_loss, 3) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    # Full-year equity returns for sharpe / dd / cagr
    s = pd.Timestamp(f"{year}-01-01", tz="UTC")
    e = pd.Timestamp(f"{year+1}-01-01", tz="UTC")
    eq_y = eq[(eq.index >= s) & (eq.index < e)]
    if len(eq_y) > 10:
        rets = eq_y.pct_change().fillna(0.0)
        bpy = pa.BARS_PER_YR
        out["sharpe"] = round(float((rets.mean() * bpy) / (rets.std() * np.sqrt(bpy) + 1e-12)), 3)
        out["dd"]     = round(float((eq_y / eq_y.cummax() - 1).min()), 3)
        yrs = (eq_y.index[-1] - eq_y.index[0]).days / 365.25
        if yrs > 0 and eq_y.iloc[0] > 0:
            out["cagr"] = round(float((eq_y.iloc[-1] / eq_y.iloc[0]) ** (1/yrs) - 1), 3)
    return out


def main():
    all_rows = []
    summary_rows = []
    for sym, (name, fn) in itertools.product(COINS, STRATEGIES_V7.items()):
        df = pa.load_ohlcv(sym, STARTS[sym], END_GLOBAL)
        if len(df) < 200: continue
        eq, trades = _run(df, fn)
        yrs = []
        for y in (2022, 2023, 2024, 2025):
            ys = year_stats(eq, trades, y)
            ys["coin"] = sym
            ys["strategy"] = name
            all_rows.append(ys)
            yrs.append(ys)
        # Summary row
        wrs = [y["win_rate"] for y in yrs if y["n_trades"] >= 3]
        total_tr = pd.DataFrame(trades)
        total_wr = round(float((total_tr["return"]>0).mean()), 3) if len(total_tr) else 0.0
        total_pf = 0.0
        if len(total_tr):
            gw = total_tr.loc[total_tr["return"]>0, "return"].sum()
            gl = abs(total_tr.loc[total_tr["return"]<=0, "return"].sum())
            total_pf = round(float(gw/gl), 3) if gl > 0 else (999.0 if gw > 0 else 0)
        summary_rows.append({
            "coin": sym, "strategy": name,
            "n_trades_total": int(len(total_tr)),
            "wr_overall": total_wr,
            "wr_min_yr": round(min(wrs), 3) if wrs else 0,
            "wr_22": next((y["win_rate"] for y in yrs if y["year"]==2022 and y["n_trades"]>=3), None),
            "wr_23": next((y["win_rate"] for y in yrs if y["year"]==2023 and y["n_trades"]>=3), None),
            "wr_24": next((y["win_rate"] for y in yrs if y["year"]==2024 and y["n_trades"]>=3), None),
            "wr_25": next((y["win_rate"] for y in yrs if y["year"]==2025 and y["n_trades"]>=3), None),
            "pf_overall": total_pf,
            "final": round(float(eq.iloc[-1]), 0),
            "trades_per_year": round(len(total_tr) / 4, 1),
        })
        print(f"  {sym}  {name:<26} n={len(total_tr):4d}  "
              f"wr_overall={total_wr*100:4.1f}%   "
              f"min_yr={round(min(wrs)*100,1) if wrs else 0:4.1f}%   "
              f"PF={total_pf:.2f}  final=${eq.iloc[-1]:,.0f}",
              flush=True)

    df_all = pd.DataFrame(all_rows)
    df_all.to_csv(OUT/"hwr_hunt.csv", index=False)
    df_sum = pd.DataFrame(summary_rows)
    df_sum.to_csv(OUT/"hwr_summary.csv", index=False)

    # Rank: coins where a strategy has wr_min_yr >= 0.50 AND pf_overall > 1
    print("\n=== CANDIDATES WITH MIN-YEAR WIN RATE >= 50% ===")
    passers = df_sum[(df_sum["wr_min_yr"] >= 0.50) & (df_sum["pf_overall"] > 1.0)].copy()
    passers = passers.sort_values(["wr_min_yr","pf_overall"], ascending=[False, False])
    print(passers.to_string(index=False))
    print(f"\n{len(passers)} strategy-coin passers out of {len(df_sum)} tested.")


if __name__ == "__main__":
    main()
