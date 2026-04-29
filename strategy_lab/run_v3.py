"""
V3 optimization runner:
  * Run each V3 variant as a portfolio (same 60/25/15 allocation, 4h, same period)
  * Record IS/OOS metrics using the same walk-forward split as V2B
  * Compare against V2B baseline
"""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
from strategy_lab import engine
from strategy_lab.strategies_v2 import volume_breakout_v2
from strategy_lab.strategies_v3 import STRATEGIES_V3

OUT = Path(__file__).resolve().parent / "results"
ALLOC = {"BTCUSDT": 0.60, "ETHUSDT": 0.25, "SOLUSDT": 0.15}
TF    = "4h"


def portfolio_run(fn, params, start, end):
    sub_eqs = []
    trades  = 0
    for sym, w in ALLOC.items():
        df = engine.load(sym, TF, start, end)
        sig = fn(df, **params)
        init = w * engine.TOTAL_CAPITAL
        res = engine.run_backtest(
            df,
            entries=sig["entries"], exits=sig["exits"],
            short_entries=sig.get("short_entries"),
            short_exits=sig.get("short_exits"),
            sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
            init_cash=init, label=sym,
        )
        sub_eqs.append(res.pf.value().rename(sym))
        trades += int(res.metrics["n_trades"])
    port = pd.concat(sub_eqs, axis=1).ffill().fillna(method="bfill").sum(axis=1)
    m = engine.portfolio_metrics(port)
    m["trades"] = trades
    return m


def main():
    runs = [("V2B_baseline", volume_breakout_v2, {})]
    for name, fn in STRATEGIES_V3.items():
        runs.append((name, fn, {}))

    rows = []
    for name, fn, params in runs:
        full = portfolio_run(fn, params, "2018-01-01", "2026-04-01")
        is_m = portfolio_run(fn, params, "2018-01-01", "2023-01-01")
        oos  = portfolio_run(fn, params, "2023-01-01", "2026-04-01")

        rows.append({
            "variant": name,
            "full_cagr":   full["cagr"],
            "full_sharpe": full["sharpe"],
            "full_maxdd":  full["max_dd"],
            "full_calmar": full["calmar"],
            "full_final":  full["final"],
            "full_trades": full["trades"],

            "is_cagr":    is_m["cagr"],
            "is_sharpe":  is_m["sharpe"],
            "is_maxdd":   is_m["max_dd"],
            "is_calmar":  is_m["calmar"],

            "oos_cagr":   oos["cagr"],
            "oos_sharpe": oos["sharpe"],
            "oos_maxdd":  oos["max_dd"],
            "oos_calmar": oos["calmar"],
        })
        print(f"  {name:20s}  full CAGR={full['cagr']:.2%}  DD={full['max_dd']:.2%}  "
              f"Calmar={full['calmar']:.2f}  OOS Sharpe={oos['sharpe']:.2f}  trades={full['trades']}")

    df = pd.DataFrame(rows)
    for c in df.columns:
        if c == "variant": continue
        if c.endswith(("_trades",)): continue
        df[c] = df[c].round(3)
    df.to_csv(OUT / "V3_comparison.csv", index=False)
    print("\n=== V3 COMPARISON ===")
    print(df.to_string(index=False))

    # Pick winner by OOS Calmar
    winner = df.sort_values("oos_calmar", ascending=False).iloc[0]
    print(f"\nOOS-best variant: {winner['variant']}  "
          f"OOS Calmar={winner['oos_calmar']:.2f}  "
          f"Full CAGR={winner['full_cagr']:.2%}  "
          f"Full MaxDD={winner['full_maxdd']:.2%}")

    (OUT / "V3_winner.json").write_text(winner.to_json(indent=2))


if __name__ == "__main__":
    main()
