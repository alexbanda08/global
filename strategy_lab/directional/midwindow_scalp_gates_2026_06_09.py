"""Gate search on the mid-window lag-rebound scalp cache (2026-06-09).
Tests, per (asset,tf,offset): does buying the binance-leading cheap token and
book-exiting at +Delta produce a robust scalp, gated by lag/regime?

Fidelity scalp pnl: (sell-ev)*sh - 0.07*sh*ev*(1-ev) - 0.07*sh*sell*(1-sell).
Robustness: bootstrap CI + time walk-forward (3 folds) + DSR (n_trials = #gate combos).
"""
import sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
np.random.seed(0)
sys.path.insert(0, r"strategy_lab")
try:
    from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics as DSR
except Exception:
    DSR = None

C = pd.read_parquet(r"strategy_lab\directional\_results\midwindow_scalp_cache_2026_06_09.parquet")
DTS = [30, 45, 60, 90]
def sp(ev, sell, sh): return (sell-ev)*sh - 0.07*sh*ev*(1-ev) - 0.07*sh*sell*(1-sell)
def boot(v, nb=4000):
    if len(v) < 10: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))
def tstat(v): return v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if (len(v)>1 and v.std()>0) else np.nan

def best_scalp(d):
    ev, sh = d.entry_vwap.values, d.shares.values
    won = d.won.values.astype(bool)
    hold = np.where(won, sh*(1-ev)*(1-0.07*ev), -sh*ev)
    best = None
    for dt in DTS:
        sell = pd.to_numeric(d[f"bid_{dt}"], errors="coerce").values
        s = np.where(np.isfinite(sell), sp(ev, sell, sh), hold)
        if best is None or s.mean() > best[1]: best = (dt, s.mean(), s)
    return best  # (dt, mean, pnl_vec)

GATES = {
    "cheap": lambda d: d.entry_vwap < 0.55,
    "cheap+lag[3,12]": lambda d: (d.entry_vwap<0.55) & (d.abs_lag.between(3,12)),
    "cheap+lag>=3": lambda d: (d.entry_vwap<0.55) & (d.abs_lag>=3),
    "cheap+lag[3,12]+momalign": lambda d: (d.entry_vwap<0.55) & (d.abs_lag.between(3,12)) & (np.sign(d.lag_bps)==np.sign(d.mom30)),
    "cheap+lag[3,12]+hiRV": lambda d: (d.entry_vwap<0.55) & (d.abs_lag.between(3,12)) & (d.rv60>d.rv60.median()),
    "cheap+lag[3,12]+TOD": lambda d: (d.entry_vwap<0.55) & (d.abs_lag.between(3,12)) & (~d.hour.isin([12,17])),
}
rows = []
for (a, tf, off), d in C.groupby(["asset","tf","offset"]):
    for gname, gf in GATES.items():
        dd = d[gf(d)]
        if len(dd) < 25: continue
        dt, mean, pnl = best_scalp(dd)
        lo, hi = boot(pnl)
        # 3-fold time walk-forward sign-consistency
        dd2 = dd.sort_values("e_us"); folds = np.array_split(dd2.index.values, 3)
        wf = []
        for fi in folds:
            sub = dd2.loc[fi]
            _, m2, _ = best_scalp(sub); wf.append(m2)
        rows.append(dict(asset=a, tf=tf, offset=off, gate=gname, n=len(dd),
                         wr=round(100*dd.won.mean(),1), ev=round(dd.entry_vwap.mean(),3),
                         exit_dt=dt, scalp=round(mean,3), t=round(tstat(pnl),2),
                         lo=round(lo,3), hi=round(hi,3), pos=("Y" if lo>0 else "."),
                         wf_pos=sum(1 for x in wf if x>0), wf=[round(x,2) for x in wf]))
R = pd.DataFrame(rows).sort_values("scalp", ascending=False)
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 300)
R.to_csv(r"strategy_lab\directional\_results\midwindow_scalp_gates_2026_06_09.csv", index=False)
print(R.to_string(index=False))
print("\n=== ROBUST (scalp CI>0 AND walk-forward 3/3 positive) ===")
rob = R[(R.pos=="Y") & (R.wf_pos==3)]
print(rob.to_string(index=False) if len(rob) else "  NONE")
if DSR is not None and len(rob):
    for _, r in rob.iterrows():
        sh = r.scalp  # approx; DSR on the cell's sharpe
    print("\n(DSR on survivors: run per-cell on pnl vec next pass)")
