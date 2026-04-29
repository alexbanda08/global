"""
V8 hunt — evaluate the SuperTrend/HMA/Vol-Donchian family with multi-TP ladder
on the 6-coin universe, across 2022-2025.

Compares results against the current portfolio candidates.
Also reports partial-exit capture: how often TP1 / TP2 / TP3 hit.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab.strategies_v8 import STRATEGIES_V8
from strategy_lab.strategies_v9 import STRATEGIES_V9
from strategy_lab.advanced_simulator import simulate_advanced
from strategy_lab import portfolio_audit as pa   # for load_ohlcv + BARS_PER_YR

ALL_CANDIDATES = {**STRATEGIES_V8, **STRATEGIES_V9}

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","LINKUSDT","ADAUSDT","XRPUSDT"]
STARTS = {
    "BTCUSDT": "2021-06-01", "ETHUSDT": "2021-06-01", "SOLUSDT": "2021-06-01",
    "LINKUSDT": "2021-06-01", "ADAUSDT": "2021-06-01", "XRPUSDT": "2021-06-01",
}
END_GLOBAL = "2026-04-01"
OUT = Path(__file__).resolve().parent / "results"


def _metrics(eq: pd.Series) -> dict:
    if len(eq) < 20 or eq.iloc[-1] <= 0:
        return {"sharpe":0,"cagr":0,"dd":0,"calmar":0,"final":float(eq.iloc[-1] if len(eq) else 0)}
    rets = eq.pct_change().fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs,0.01)) - 1
    sharpe = (rets.mean() * pa.BARS_PER_YR) / (rets.std() * np.sqrt(pa.BARS_PER_YR) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"sharpe":round(float(sharpe),3),"cagr":round(float(cagr),4),
            "dd":round(dd,4),"calmar":round(cagr/abs(dd) if dd<0 else 0,3),
            "final":round(float(eq.iloc[-1]),0)}


def per_year_win_rate(trades: list[dict]) -> dict:
    if not trades: return {}
    tr = pd.DataFrame(trades)
    tr["year"] = pd.to_datetime(tr["exit_time"]).dt.year
    out = {}
    for y in (2022,2023,2024,2025):
        sub = tr[tr["year"] == y]
        if len(sub) < 2:
            out[y] = None
        else:
            out[y] = {"n": int(len(sub)),
                      "wr": round(float((sub["return"]>0).mean()),3)}
    return out


def tp_hit_stats(trades: list[dict]) -> dict:
    if not trades: return {}
    tr = pd.DataFrame(trades)
    return {
        "tp1_rate": round(float(tr["tp1_hit"].mean()),3),
        "tp2_rate": round(float(tr["tp2_hit"].mean()),3),
        "tp3_rate": round(float(tr["tp3_hit"].mean()),3),
    }


def main():
    all_rows = []
    for sym in COINS:
        df = pa.load_ohlcv(sym, STARTS[sym], END_GLOBAL)
        for name, fn in ALL_CANDIDATES.items():
            try:
                sig = fn(df)
                eq, trades = simulate_advanced(
                    df,
                    entries=sig["entries"], exits=sig["exits"],
                    sl_pct=sig.get("sl_pct"),
                    tp1_pct=sig.get("tp1_pct"), tp1_frac=sig.get("tp1_frac", 0.4),
                    tp2_pct=sig.get("tp2_pct"), tp2_frac=sig.get("tp2_frac", 0.3),
                    tp3_pct=sig.get("tp3_pct"), tp3_frac=sig.get("tp3_frac", 0.3),
                    trail_pct=sig.get("trail_pct"),
                    init=pa.INIT,
                )
            except Exception as e:
                print(f"  {sym} {name}: error {e}")
                continue

            m  = _metrics(eq)
            yr = per_year_win_rate(trades)
            tp = tp_hit_stats(trades)
            wr_overall = float((pd.DataFrame(trades)["return"]>0).mean()) if trades else 0.0
            tr = pd.DataFrame(trades) if trades else pd.DataFrame()
            pf = 0.0
            if len(tr):
                gw = tr.loc[tr["return"]>0, "return"].sum()
                gl = abs(tr.loc[tr["return"]<=0, "return"].sum())
                pf = round(float(gw/gl), 3) if gl > 0 else 0.0
            wr_min = min([y_stats["wr"] for y_stats in yr.values() if y_stats], default=0)

            row = {
                "coin": sym, "strategy": name,
                "n_trades": len(trades),
                "wr_overall": round(wr_overall,3),
                "wr_min_yr": round(wr_min,3),
                **{f"wr_{yy-2000}": (yr.get(yy) or {}).get("wr") for yy in (2022,2023,2024,2025)},
                **{f"n_{yy-2000}":  (yr.get(yy) or {}).get("n")  for yy in (2022,2023,2024,2025)},
                "pf": pf,
                "tp1_rate": tp.get("tp1_rate"),
                "tp2_rate": tp.get("tp2_rate"),
                "tp3_rate": tp.get("tp3_rate"),
                **m,
            }
            all_rows.append(row)
            print(f"  {sym}  {name:<24} n={len(trades):4d} "
                  f"wr={wr_overall*100:4.1f}% min_yr={wr_min*100:4.1f}% "
                  f"pf={pf:.2f} sharpe={m['sharpe']:.2f} cagr={m['cagr']*100:+5.1f}% "
                  f"dd={m['dd']*100:5.1f}% final=${m['final']:,.0f}  "
                  f"TP1/2/3={tp.get('tp1_rate',0)*100:.0f}/{tp.get('tp2_rate',0)*100:.0f}/{tp.get('tp3_rate',0)*100:.0f}%",
                  flush=True)

    df_all = pd.DataFrame(all_rows)
    df_all.to_csv(OUT / "v8_hunt.csv", index=False)
    # Save trade logs per winner for later analysis
    print("\n=== PASSERS: min-year WR >= 50% AND PF > 1.1 AND final > init ===")
    passers = df_all[(df_all["wr_min_yr"] >= 0.50) & (df_all["pf"] > 1.1) & (df_all["final"] > pa.INIT)]
    passers = passers.sort_values(["wr_min_yr","sharpe"], ascending=[False,False])
    print(passers[["coin","strategy","n_trades","wr_overall","wr_min_yr",
                   "wr_22","wr_23","wr_24","wr_25","pf","sharpe","cagr","dd","final",
                   "tp1_rate","tp2_rate","tp3_rate"]].to_string(index=False))

    print("\n=== BEST PER COIN (by sharpe) ===")
    best = df_all.loc[df_all.groupby("coin")["sharpe"].idxmax()]
    print(best[["coin","strategy","wr_overall","wr_min_yr","pf","sharpe","cagr","dd","final"]].to_string(index=False))


if __name__ == "__main__":
    main()
