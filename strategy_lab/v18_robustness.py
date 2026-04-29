"""
V18 — Robustness audit of the V15 balanced XSM champion
(lb=14d, k=4, rb=7d, BTC bear filter).

Tests:
  1. Random 2-year window resampling (100 windows) — does it work in
     any time slice?
  2. Parameter-epsilon grid around the champion — is it knife-edge?
  3. Per-coin contribution breakdown — who earned the P&L?
"""
from __future__ import annotations
import itertools
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab.v15_xsm_variants import xsm_generic, load_all_4h, mx

OUT = Path(__file__).resolve().parent / "results"
RNG = np.random.default_rng(42)


def _metrics(eq: pd.Series) -> dict:
    if len(eq) < 50: return {"cagr":0,"sharpe":0,"dd":0,"final":0}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    if yrs < 0.5: return {"cagr":0,"sharpe":0,"dd":0,"final":float(eq.iloc[-1])}
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1/max(yrs,0.01)) - 1
    bpy = 365.25 * 24 / 4
    sh = (rets.mean() * bpy) / (rets.std() * np.sqrt(bpy) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {"cagr":round(float(cagr),4),"sharpe":round(float(sh),3),
            "dd":round(dd,4),"final":round(float(eq.iloc[-1]),0)}


def random_windows(data, n_windows=100):
    # Run champion on full data once; slice the equity into random 2-year windows.
    eq, _ = xsm_generic(data, mode="mom", lookback_days=14, top_k=4,
                       rebal_days=7, btc_filter=True)
    idx = eq.index
    two_yrs = pd.Timedelta(days=730)
    first_ok = idx[0] + pd.Timedelta(days=100)   # let indicators warm up
    last_ok = idx[-1] - two_yrs
    if last_ok <= first_ok:
        return pd.DataFrame()
    span_s = (last_ok - first_ok).total_seconds()
    rows = []
    for i in range(n_windows):
        off = RNG.uniform(0, span_s)
        ws = first_ok + pd.Timedelta(seconds=off)
        we = ws + two_yrs
        sub = eq[(eq.index >= ws) & (eq.index < we)]
        if len(sub) < 500: continue
        # Normalize to 10k at window start
        sub = 10000 * sub / sub.iloc[0]
        m = _metrics(sub)
        rows.append({"start":str(ws.date()),"end":str(we.date()),**m})
    return pd.DataFrame(rows)


def param_epsilon(data):
    rows = []
    grid = list(itertools.product(
        [7, 14, 21, 28],       # lookback days
        [3, 4, 5],             # top_k
        [3, 7, 14],            # rebal days
        [100, 150],            # BTC MA days
    ))
    for lb, k, rb, ma in grid:
        eq, legs = xsm_generic(data, mode="mom", lookback_days=lb, top_k=k,
                              rebal_days=rb, btc_filter=True, btc_ma_days=ma)
        m = _metrics(eq)
        rows.append({"lb":lb,"k":k,"rb":rb,"ma":ma,"legs":legs,**m})
    return pd.DataFrame(rows)


def main():
    data = load_all_4h()

    print("[1/2] Random 2-year windows (100) ...")
    rw = random_windows(data, 100)
    rw.to_csv(OUT/"v18_random_windows.csv", index=False)
    if len(rw):
        pos = (rw["cagr"] > 0).mean() * 100
        stable = (rw["sharpe"] > 0.5).mean() * 100
        print(f"  windows n={len(rw)}  profitable={pos:.0f}%  sharpe>0.5={stable:.0f}%  "
              f"median sharpe={rw['sharpe'].median():.2f}  worst DD={rw['dd'].min()*100:.1f}%")

    print("\n[2/2] Parameter-epsilon grid ...")
    pe = param_epsilon(data)
    pe.to_csv(OUT/"v18_param_epsilon.csv", index=False)
    ok = pe[pe["cagr"] > 0]
    print(f"  configs={len(pe)}  profitable={len(ok)}  "
          f"sharpe range=[{pe.sharpe.min():.2f}, {pe.sharpe.max():.2f}]  "
          f"cagr range=[{pe.cagr.min()*100:+.0f}%, {pe.cagr.max()*100:+.0f}%]  "
          f"worst DD={pe.dd.min()*100:.1f}%")

    print("\n=== PARAM-EPS TOP 10 by sharpe ===")
    print(pe.sort_values("sharpe", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
