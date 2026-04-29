"""
V12 hunt — pullback / squeeze / pattern entries across 6 coins 2022-2025.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab.strategies_v12 import STRATEGIES_V12
from strategy_lab.advanced_simulator import simulate_advanced
from strategy_lab import portfolio_audit as pa

COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","LINKUSDT","ADAUSDT","XRPUSDT"]
STARTS = {s:"2021-06-01" for s in COINS}
END = "2026-04-01"
OUT = Path(__file__).resolve().parent / "results"


def _metrics(eq):
    if len(eq) < 10 or eq.iloc[-1] <= 0: return {}
    rets = eq.pct_change().fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs,0.01)) - 1
    sh = (rets.mean() * pa.BARS_PER_YR) / (rets.std() * np.sqrt(pa.BARS_PER_YR) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"sharpe":round(float(sh),3), "cagr":round(float(cagr),4),
            "dd":round(dd,4), "calmar":round(cagr/abs(dd) if dd<0 else 0,3),
            "final":round(float(eq.iloc[-1]),0)}


def _yr_wr(trades, y):
    if not trades: return None
    tr = pd.DataFrame(trades); tr["year"] = pd.to_datetime(tr["exit_time"]).dt.year
    sub = tr[tr["year"]==y]
    if len(sub) < 2: return None
    return round(float((sub["return"]>0).mean()), 3)


def main():
    rows = []
    for sym in COINS:
        df = pa.load_ohlcv(sym, STARTS[sym], END)
        for name, fn in STRATEGIES_V12.items():
            sig = fn(df)
            eq, trades = simulate_advanced(df,
                entries=sig["entries"], exits=sig.get("exits"),
                sl_pct=sig.get("sl_pct"),
                tp1_pct=sig.get("tp1_pct"), tp1_frac=sig.get("tp1_frac",0.4),
                tp2_pct=sig.get("tp2_pct"), tp2_frac=sig.get("tp2_frac",0.3),
                tp3_pct=sig.get("tp3_pct"), tp3_frac=sig.get("tp3_frac",0.3),
                trail_pct=sig.get("trail_pct"),
                init=pa.INIT)
            tr_df = pd.DataFrame(trades) if trades else pd.DataFrame()
            wr_overall = float((tr_df["return"]>0).mean()) if len(tr_df) else 0
            pf = 0
            if len(tr_df):
                gw = tr_df.loc[tr_df["return"]>0,"return"].sum()
                gl = abs(tr_df.loc[tr_df["return"]<=0,"return"].sum())
                pf = round(float(gw/gl),3) if gl>0 else 0
            yrs = {y:_yr_wr(trades, y) for y in (2022,2023,2024,2025)}
            wr_min = min([v for v in yrs.values() if v is not None], default=0)
            m = _metrics(eq)
            row = {"coin":sym, "strategy":name, "n":len(trades),
                   "wr":round(wr_overall,3), "wr_min_yr":round(wr_min,3),
                   **{f"wr_{y-2000}":yrs[y] for y in (2022,2023,2024,2025)},
                   "pf":pf, **m}
            rows.append(row)
            print(f"  {sym}  {name:<24} n={len(trades):3d} wr={wr_overall*100:4.1f}% "
                  f"min={wr_min*100:4.1f}% pf={pf:.2f} sharpe={m.get('sharpe',0):.2f} "
                  f"cagr={m.get('cagr',0)*100:+5.1f}% dd={m.get('dd',0)*100:+5.1f}% "
                  f"final=${m.get('final',0):,.0f}", flush=True)

    df_all = pd.DataFrame(rows)
    df_all.to_csv(OUT / "v12_hunt.csv", index=False)
    print("\n=== PASSERS (wr_min_yr>=0.50, pf>1.1, final>10k) ===")
    p = df_all[(df_all["wr_min_yr"]>=0.50) & (df_all["pf"]>1.1) & (df_all["final"]>pa.INIT)]
    if len(p):
        print(p.sort_values(["wr_min_yr","sharpe"], ascending=[False,False]).to_string(index=False))
    else:
        print("  (none)")
    print("\n=== BEST PER COIN BY SHARPE (profitable only) ===")
    good = df_all[df_all["final"] > pa.INIT]
    if len(good):
        best = good.loc[good.groupby("coin")["sharpe"].idxmax()]
        print(best.to_string(index=False))


if __name__ == "__main__":
    main()
