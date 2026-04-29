"""
Final report for the winning strategy.

Winner: V2B_volume_breakout on BTC/ETH/SOL 4h
Params (walk-forward selected on 2018-2022, tested 2023-2026):
  don_len=30, vol_mult=1.3, regime_len=150, tsl_atr=4.5
  + default atr_len=14, sl_atr=2.0, vol_avg=20
Allocation: BTC=60%, ETH=25%, SOL=15% (risk-adjusted)
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from strategy_lab import engine
from strategy_lab.strategies_v2 import volume_breakout_v2

OUT = Path(__file__).resolve().parent / "results"
ALLOC = {"BTCUSDT": 0.60, "ETHUSDT": 0.25, "SOLUSDT": 0.15}
TF = "4h"
START, END = "2018-01-01", "2026-04-01"
FINAL_PARAMS = dict(don_len=30, vol_mult=1.3, regime_len=150, tsl_atr=4.5)


def main():
    report = {"params": FINAL_PARAMS, "allocation": ALLOC, "timeframe": TF,
              "period": [START, END], "per_asset": {}, "portfolio": None, "bh": None}

    sub_eqs = []
    bh_eqs  = []
    for sym, w in ALLOC.items():
        df = engine.load(sym, TF, START, END)
        sig = volume_breakout_v2(df, **FINAL_PARAMS)
        init = w * engine.TOTAL_CAPITAL
        res = engine.run_backtest(
            df,
            entries=sig["entries"], exits=sig["exits"],
            sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
            init_cash=init, label=sym,
        )
        report["per_asset"][sym] = {
            **{k: round(v, 4) if isinstance(v, float) else v
               for k, v in res.metrics.items() if k != "label"},
            "initial": init,
        }
        sub_eqs.append(res.pf.value().rename(sym))

        bh = df["close"].reindex_like(res.pf.value())
        bh = (bh / bh.iloc[0]) * init
        bh_eqs.append(bh.rename(sym))

    port = pd.concat(sub_eqs, axis=1).ffill().fillna(method="bfill")
    port["portfolio_equity"] = port.sum(axis=1)
    bh_port = pd.concat(bh_eqs, axis=1).ffill().fillna(method="bfill")
    bh_port["bh_equity"] = bh_port.sum(axis=1)

    report["portfolio"] = engine.portfolio_metrics(port["portfolio_equity"])
    report["bh"]        = engine.portfolio_metrics(bh_port["bh_equity"])

    # Save CSVs
    port.to_csv(OUT / "FINAL_portfolio_equity.csv")
    bh_port.to_csv(OUT / "FINAL_bh_equity.csv")
    (OUT / "FINAL_report.json").write_text(json.dumps(report, default=str, indent=2))

    # Printable summary
    print("================================================================")
    print("  WINNING STRATEGY — FINAL REPORT")
    print("================================================================")
    print(f"Strategy  : V2B Volume Breakout (trend + volume spike + regime)")
    print(f"Timeframe : {TF}")
    print(f"Period    : {START} -> {END}")
    print(f"Capital   : ${engine.TOTAL_CAPITAL:,.0f}")
    print(f"Allocation: " +
          ", ".join(f"{s}={w:.0%}" for s, w in ALLOC.items()))
    print(f"Params    : {FINAL_PARAMS}")
    print()
    print("---- PER-ASSET BACKTEST ----")
    fmt_row = "{sym:10s} init=${init:<6,.0f}  CAGR={cagr:>7.2%}  Sharpe={sr:>5.2f}  DD={dd:>7.2%}  Trades={n:>4d}  WinRate={wr:>6.2%}  BH={bh:>7.2%}"
    for sym, m in report["per_asset"].items():
        print(fmt_row.format(sym=sym, init=m["initial"], cagr=m["cagr"],
                             sr=m["sharpe"], dd=m["max_dd"], n=m["n_trades"],
                             wr=m["win_rate"], bh=m["bh_return"]))

    p = report["portfolio"]
    b = report["bh"]
    print()
    print("---- PORTFOLIO ----")
    print(f"Total Return : {p['total_return']:.2%}")
    print(f"CAGR         : {p['cagr']:.2%}")
    print(f"Sharpe       : {p['sharpe']:.2f}")
    print(f"Sortino      : {p['sortino']:.2f}")
    print(f"Max Drawdown : {p['max_dd']:.2%}")
    print(f"Calmar       : {p['calmar']:.2f}")
    print(f"Final Equity : ${p['final']:,.0f}  (from ${engine.TOTAL_CAPITAL:,.0f})")
    print()
    print("---- BUY & HOLD BENCHMARK (same allocation) ----")
    print(f"Total Return : {b['total_return']:.2%}")
    print(f"CAGR         : {b['cagr']:.2%}")
    print(f"Sharpe       : {b['sharpe']:.2f}")
    print(f"Max Drawdown : {b['max_dd']:.2%}")
    print(f"Calmar       : {b['calmar']:.2f}")
    print(f"Final Equity : ${b['final']:,.0f}")
    print()
    print("---- RELATIVE ----")
    print(f"Equity  ratio (strat / BH) : {p['final']/b['final']:.2f}x")
    print(f"DD      ratio (strat / BH) : {p['max_dd']/b['max_dd']:.2f}x  (lower is better)")
    print(f"Calmar  ratio              : {p['calmar']/b['calmar']:.2f}x  (higher is better)")


if __name__ == "__main__":
    main()
