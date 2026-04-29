"""
Final report for V3E (score >= 2-of-3 trend validators).

Winner: V3E_score2of3 on BTC/ETH/SOL 4h
  Base (V2B) params:       don_len=30, vol_avg=20, vol_mult=1.3,
                           regime_len=150, atr_len=14, tsl_atr=4.5
  Trend validators (>= 2/3 must be true on entry bar):
    G1: HTF 1d 200-EMA rising
    G2: ADX(14) > 20
    G3: SMA(close, 50) rising
Allocation: BTC 60% / ETH 25% / SOL 15%, $10,000 demo
"""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from strategy_lab import engine
from strategy_lab.strategies_v3 import v3e_score2of3

OUT = Path(__file__).resolve().parent / "results"
ALLOC = {"BTCUSDT": 0.60, "ETHUSDT": 0.25, "SOLUSDT": 0.15}
TF = "4h"
START, END = "2018-01-01", "2026-04-01"


def main():
    report = {"variant": "V3E_score2of3", "allocation": ALLOC, "timeframe": TF,
              "period": [START, END], "per_asset": {}, "portfolio": None, "bh": None}

    sub_eqs, bh_eqs = [], []
    for sym, w in ALLOC.items():
        df = engine.load(sym, TF, START, END)
        sig = v3e_score2of3(df)
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

    port.to_csv(OUT / "V3E_portfolio_equity.csv")
    bh_port.to_csv(OUT / "V3E_bh_equity.csv")
    (OUT / "V3E_report.json").write_text(json.dumps(report, default=str, indent=2))

    # Per-year breakdown
    strat_eq = port["portfolio_equity"]
    bh_eq = bh_port["bh_equity"]
    rows = []
    for yr in range(2018, 2027):
        s = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        e = pd.Timestamp(f"{yr}-12-31 23:59", tz="UTC")
        ey = strat_eq[(strat_eq.index >= s) & (strat_eq.index <= e)]
        by = bh_eq[(bh_eq.index >= s) & (bh_eq.index <= e)]
        if len(ey) < 10:
            continue
        rows.append({
            "year":    yr,
            "ret":     round(ey.iloc[-1] / ey.iloc[0] - 1, 3),
            "dd":      round(float(((ey / ey.cummax()) - 1).min()), 3),
            "bh_ret":  round(by.iloc[-1] / by.iloc[0] - 1, 3),
        })
    pd.DataFrame(rows).to_csv(OUT / "V3E_per_year.csv", index=False)

    # Console dump
    p = report["portfolio"]; b = report["bh"]
    print("================================================================")
    print("  WINNING STRATEGY v3 — V3E_score2of3 — FINAL REPORT")
    print("================================================================")
    print(f"Timeframe : {TF}   Period: {START} -> {END}")
    print(f"Capital   : ${engine.TOTAL_CAPITAL:,.0f}")
    print(f"Allocation: " + ", ".join(f"{s}={int(w*100)}%"
                                      for s,w in ALLOC.items()))
    print()
    print("---- PER-ASSET ----")
    row = "{sym:10s} init=${init:<6,.0f}  CAGR={cagr:>7.2%}  Sharpe={sr:>5.2f}  DD={dd:>7.2%}  Trades={n:>4d}  WinRate={wr:>6.2%}  BH={bh:>7.2%}"
    for sym, m in report["per_asset"].items():
        print(row.format(sym=sym, init=m["initial"], cagr=m["cagr"],
                         sr=m["sharpe"], dd=m["max_dd"], n=m["n_trades"],
                         wr=m["win_rate"], bh=m["bh_return"]))

    print()
    print("---- PORTFOLIO ----")
    print(f"Total Return : {p['total_return']:.2%}")
    print(f"CAGR         : {p['cagr']:.2%}")
    print(f"Sharpe       : {p['sharpe']:.2f}")
    print(f"Sortino      : {p['sortino']:.2f}")
    print(f"Max Drawdown : {p['max_dd']:.2%}")
    print(f"Calmar       : {p['calmar']:.2f}")
    print(f"Final Equity : ${p['final']:,.0f}")
    print()
    print("---- BUY & HOLD ----")
    print(f"CAGR={b['cagr']:.2%}  Sharpe={b['sharpe']:.2f}  "
          f"DD={b['max_dd']:.2%}  Final=${b['final']:,.0f}")
    print()
    print("---- V2B vs V3E (full period) ----")
    print("  V2B: CAGR 42.43%  Sharpe 1.21  DD -31.02%  Calmar 1.37  Final $184,787")
    print(f"  V3E: CAGR {p['cagr']:.2%}  Sharpe {p['sharpe']:.2f}  "
          f"DD {p['max_dd']:.2%}  Calmar {p['calmar']:.2f}  "
          f"Final ${p['final']:,.0f}")


if __name__ == "__main__":
    main()
