"""
V10 hunt — orderflow strategies on BTC/ETH/SOL (2022-2025).

V10 requires Binance futures metrics / funding / liquidations which we only
have for the 3 majors; LINK/ADA/XRP stay on their current strategies.

Compares V10 variants against the baseline V3B/V4C for the same coin.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab.strategies_v10 import STRATEGIES_V10
from strategy_lab.advanced_simulator import simulate_advanced
from strategy_lab import portfolio_audit as pa

COINS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
STARTS = {"BTCUSDT": "2021-06-01", "ETHUSDT": "2021-06-01", "SOLUSDT": "2021-06-01"}
END    = "2026-04-01"
OUT    = Path(__file__).resolve().parent / "results"


def _metrics(eq: pd.Series) -> dict:
    if len(eq) < 10 or eq.iloc[-1] <= 0:
        return {"sharpe": 0, "cagr": 0, "dd": 0, "calmar": 0,
                "final": float(eq.iloc[-1] if len(eq) else 0)}
    rets = eq.pct_change().fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    sharpe = (rets.mean() * pa.BARS_PER_YR) / (rets.std() * np.sqrt(pa.BARS_PER_YR) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"sharpe": round(float(sharpe), 3), "cagr": round(float(cagr), 4),
            "dd": round(dd, 4),
            "calmar": round(cagr / abs(dd) if dd < 0 else 0, 3),
            "final": round(float(eq.iloc[-1]), 0)}


def _year_stats(trades, year):
    if not trades: return {}
    tr = pd.DataFrame(trades); tr["year"] = pd.to_datetime(tr["exit_time"]).dt.year
    sub = tr[tr["year"] == year]
    if len(sub) < 2: return {"n": int(len(sub)), "wr": None}
    return {"n": int(len(sub)), "wr": round(float((sub["return"] > 0).mean()), 3)}


def main():
    rows = []
    for sym in COINS:
        df = pa.load_ohlcv(sym, STARTS[sym], END)
        for name, fn in STRATEGIES_V10.items():
            try:
                sig = fn(df, sym)
            except FileNotFoundError as e:
                print(f"  {sym} {name}: missing data ({e})"); continue
            eq, trades = simulate_advanced(df,
                entries=sig["entries"], exits=sig.get("exits"),
                sl_pct=sig.get("sl_pct"),
                tp1_pct=sig.get("tp1_pct"), tp1_frac=sig.get("tp1_frac", 0.4),
                tp2_pct=sig.get("tp2_pct"), tp2_frac=sig.get("tp2_frac", 0.3),
                tp3_pct=sig.get("tp3_pct"), tp3_frac=sig.get("tp3_frac", 0.3),
                trail_pct=sig.get("trail_pct"),
                init=pa.INIT)
            yr = {y: _year_stats(trades, y) for y in (2022, 2023, 2024, 2025)}
            tr_df = pd.DataFrame(trades) if trades else pd.DataFrame()
            wr_overall = float((tr_df["return"] > 0).mean()) if len(tr_df) else 0.0
            pf = 0.0
            if len(tr_df):
                gw = tr_df.loc[tr_df["return"] > 0, "return"].sum()
                gl = abs(tr_df.loc[tr_df["return"] <= 0, "return"].sum())
                pf = round(float(gw / gl), 3) if gl > 0 else 0.0
            wr_min = min([y["wr"] for y in yr.values() if y.get("wr")], default=0)
            m = _metrics(eq)
            row = {"coin": sym, "strategy": name, "n_trades": len(trades),
                   "wr_overall": round(wr_overall, 3), "wr_min_yr": round(wr_min, 3),
                   "pf": pf,
                   **{f"wr_{y - 2000}": yr[y].get("wr") for y in (2022, 2023, 2024, 2025)},
                   **{f"n_{y - 2000}":  yr[y].get("n")  for y in (2022, 2023, 2024, 2025)},
                   **m,
                   "tp1_rate": round(float(pd.DataFrame(trades)["tp1_hit"].mean()), 3) if trades else 0,
                   "tp2_rate": round(float(pd.DataFrame(trades)["tp2_hit"].mean()), 3) if trades else 0,
                   "tp3_rate": round(float(pd.DataFrame(trades)["tp3_hit"].mean()), 3) if trades else 0,
                   }
            rows.append(row)
            print(f"  {sym}  {name:<24} n={len(trades):4d} "
                  f"wr={wr_overall*100:4.1f}% min_yr={wr_min*100:4.1f}% "
                  f"pf={pf:.2f} sharpe={m['sharpe']:.2f} cagr={m['cagr']*100:+6.1f}% "
                  f"dd={m['dd']*100:+5.1f}% final=${m['final']:,.0f}", flush=True)

    df_all = pd.DataFrame(rows)
    df_all.to_csv(OUT / "v10_hunt.csv", index=False)

    print("\n=== CANDIDATES: min-yr WR >= 50%, PF > 1.1, final > 10k ===")
    passers = df_all[(df_all["wr_min_yr"] >= 0.50) & (df_all["pf"] > 1.1) & (df_all["final"] > pa.INIT)]
    passers = passers.sort_values(["wr_min_yr", "sharpe"], ascending=[False, False])
    if len(passers):
        print(passers[["coin","strategy","n_trades","wr_overall","wr_min_yr",
                       "wr_22","wr_23","wr_24","wr_25","pf","sharpe","cagr","dd","final"]].to_string(index=False))
    else:
        print("  (none)")

    print("\n=== BEST PER COIN (by sharpe, among profitable) ===")
    good = df_all[df_all["final"] > pa.INIT]
    if len(good):
        best = good.loc[good.groupby("coin")["sharpe"].idxmax()]
        print(best[["coin","strategy","n_trades","wr_overall","pf","sharpe","cagr","dd","final"]].to_string(index=False))
    else:
        print("  (all unprofitable)")


if __name__ == "__main__":
    main()
