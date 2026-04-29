"""
Per-asset independent-portfolio report.

Each of BTC/ETH/SOL runs its OWN best strategy with $10k — no capital
sharing. Produces:
  * per-asset equity CSVs
  * combined 3-sub-portfolio equity + DD
  * walk-forward IS/OOS for each asset winner
  * per-asset per-year breakdown
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
WF_CUT = "2023-01-01"


def backtest(sym, strat, tf, start, end, init=INIT):
    df = engine.load(sym, tf, start, end)
    fn = ALL[strat]
    sig = fn(df)
    res = engine.run_backtest(
        df,
        entries=sig["entries"], exits=sig["exits"],
        short_entries=sig.get("short_entries"),
        short_exits=sig.get("short_exits"),
        sl_stop=sig.get("sl_stop"),
        tsl_stop=sig.get("tsl_stop"),
        init_cash=init,
        label=f"{strat}|{sym}|{tf}",
    )
    return res


def main():
    report = {"per_asset": {}, "combined": None, "walkforward": {}, "winners": WINNERS}

    eqs = []
    bhs = []

    for sym, (strat, tf) in WINNERS.items():
        res = backtest(sym, strat, tf, START, END)
        eq = res.pf.value()
        report["per_asset"][sym] = {
            "strategy": strat, "tf": tf,
            **{k: round(v, 4) if isinstance(v, float) else v
               for k, v in res.metrics.items() if k != "label"},
            "init": INIT,
        }
        eq.to_csv(OUT / f"V4_{sym}_equity.csv")
        eqs.append(eq.rename(sym))

        # BH benchmark for this asset alone ($10k each)
        df = engine.load(sym, tf, START, END)
        bh = df["close"].reindex_like(eq)
        bh = (bh / bh.iloc[0]) * INIT
        bhs.append(bh.rename(sym))

        # Walk-forward IS/OOS for this asset (frozen params)
        is_r  = backtest(sym, strat, tf, START, WF_CUT)
        oos_r = backtest(sym, strat, tf, WF_CUT, END)
        report["walkforward"][sym] = {
            "IS":  {k: round(v, 4) if isinstance(v, float) else v for k, v in is_r.metrics.items()  if k != "label"},
            "OOS": {k: round(v, 4) if isinstance(v, float) else v for k, v in oos_r.metrics.items() if k != "label"},
        }

    # Combined sub-portfolios (simple sum of the three independent curves)
    combined = pd.concat(eqs, axis=1).ffill().fillna(method="bfill")
    combined["total_equity"] = combined.sum(axis=1)
    combined.to_csv(OUT / "V4_combined_equity.csv")

    bh_combined = pd.concat(bhs, axis=1).ffill().fillna(method="bfill")
    bh_combined["total_equity"] = bh_combined.sum(axis=1)
    bh_combined.to_csv(OUT / "V4_bh_combined_equity.csv")

    report["combined"]    = engine.portfolio_metrics(combined["total_equity"],
                                                     total_capital=3 * INIT)
    report["bh_combined"] = engine.portfolio_metrics(bh_combined["total_equity"],
                                                     total_capital=3 * INIT)
    (OUT / "V4_per_asset_report.json").write_text(json.dumps(report, default=str, indent=2))

    # Per-year per-asset
    per_year = []
    for sym, eq in zip(WINNERS, eqs):
        for yr in range(2018, 2027):
            s = pd.Timestamp(f"{yr}-01-01", tz="UTC")
            e = pd.Timestamp(f"{yr}-12-31 23:59", tz="UTC")
            segment = eq[(eq.index >= s) & (eq.index <= e)]
            if len(segment) < 10:
                continue
            per_year.append({
                "symbol": sym, "year": yr,
                "ret": round(segment.iloc[-1] / segment.iloc[0] - 1, 3),
                "dd":  round(float(((segment / segment.cummax()) - 1).min()), 3),
            })
    pd.DataFrame(per_year).to_csv(OUT / "V4_per_year_per_asset.csv", index=False)

    # ---- console ----
    print("================================================================")
    print("  PER-ASSET INDEPENDENT PORTFOLIOS — $10,000 each")
    print("================================================================")
    for sym, m in report["per_asset"].items():
        print(f"{sym}  ({m['strategy']} @ {m['tf']})")
        print(f"   init ${m['init']:,.0f}  ->  final ${m['final_equity']:,.0f}")
        print(f"   CAGR={m['cagr']:.2%}  Sharpe={m['sharpe']:.2f}  "
              f"DD={m['max_dd']:.2%}  Calmar={m['calmar']:.2f}  "
              f"Trades={m['n_trades']}  Win%={m['win_rate']:.1%}")
        bh = m.get("bh_return", 0)
        print(f"   BH return: {bh:.2%}   BH final: ${INIT * (1 + bh):,.0f}")
        print()

    c  = report["combined"]
    bc = report["bh_combined"]
    print("---- COMBINED 3 x $10k sub-portfolios = $30k ----")
    print(f"Final:  ${c['final']:,.0f}   (from $30,000)")
    print(f"CAGR:   {c['cagr']:.2%}")
    print(f"Sharpe: {c['sharpe']:.2f}")
    print(f"MaxDD:  {c['max_dd']:.2%}")
    print(f"Calmar: {c['calmar']:.2f}")
    print()
    print(f"BH (3 x $10k split equally): final ${bc['final']:,.0f}  "
          f"CAGR {bc['cagr']:.2%}  DD {bc['max_dd']:.2%}")

    print()
    print("---- WALK-FORWARD (IS 2018-2022 / OOS 2023-2026) ----")
    for sym in WINNERS:
        w = report["walkforward"][sym]
        print(f"{sym:8s} IS  CAGR={w['IS']['cagr']:>7.2%}  Sharpe={w['IS']['sharpe']:>4.2f}  DD={w['IS']['max_dd']:>7.2%}")
        print(f"{sym:8s} OOS CAGR={w['OOS']['cagr']:>7.2%}  Sharpe={w['OOS']['sharpe']:>4.2f}  DD={w['OOS']['max_dd']:>7.2%}")


if __name__ == "__main__":
    main()
