"""Rigorous pass on the mid-window scalp cache: separate TRUE within-window scalps
(exit < slot_end -> real book-sell) from HOLD-fallback (exit past slot end -> not a
scalp, favorite-longshot). DSR-deflate the within-window survivors.
"""
import sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
np.random.seed(0)
sys.path.insert(0, r"strategy_lab")
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics as DSR

C = pd.read_parquet(r"strategy_lab\directional\_results\midwindow_scalp_cache_2026_06_09.parquet")
WIN = {"5m": 300, "15m": 900}
DTS = [30, 45, 60, 90]
def sp(ev, sell, sh): return (sell-ev)*sh - 0.07*sh*ev*(1-ev) - 0.07*sh*sell*(1-sell)
def boot(v, nb=4000):
    if len(v) < 10: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))
def tstat(v): return v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if (len(v)>1 and v.std()>0) else np.nan

GATES = {
    "cheap+lag[3,12]": lambda d: (d.entry_vwap<0.55)&(d.abs_lag.between(3,12)),
    "cheap+lag[3,12]+momalign": lambda d: (d.entry_vwap<0.55)&(d.abs_lag.between(3,12))&(np.sign(d.lag_bps)==np.sign(d.mom30)),
    "cheap+lag>=3+momalign": lambda d: (d.entry_vwap<0.55)&(d.abs_lag>=3)&(np.sign(d.lag_bps)==np.sign(d.mom30)),
}
# Only WITHIN-WINDOW scalps: require a real book-sell at a fixed exit_dt with exit<slot_end.
rows = []; n_trials = 0
for (a, tf, off), d in C.groupby(["asset","tf","offset"]):
    win = WIN[tf]
    valid_dts = [dt for dt in DTS if off + dt <= win - 5]   # exit strictly inside window
    if not valid_dts: continue
    for gname, gf in GATES.items():
        dd = d[gf(d)].copy()
        if len(dd) < 30: continue
        ev, sh, won = dd.entry_vwap.values, dd.shares.values, dd.won.values.astype(bool)
        # require a real fill at the chosen exit_dt (NO hold fallback) -> drop NaN rows
        for dt in valid_dts:
            n_trials += 1
            sell = pd.to_numeric(dd[f"bid_{dt}"], errors="coerce").values
            ok = np.isfinite(sell)
            if ok.sum() < 30: continue
            pnl = sp(ev[ok], sell[ok], sh[ok])
            lo, hi = boot(pnl)
            rows.append(dict(asset=a, tf=tf, offset=off, gate=gname, exit_dt=dt,
                             n=int(ok.sum()), fillrate=round(ok.mean(),2),
                             wr=round(100*won[ok].mean(),1), ev=round(ev[ok].mean(),3),
                             scalp=round(pnl.mean(),3), t=round(tstat(pnl),2),
                             lo=round(lo,3), hi=round(hi,3), pos=("Y" if lo>0 else ".")))
R = pd.DataFrame(rows).sort_values("scalp", ascending=False)
pd.set_option("display.width",240,"display.max_columns",40,"display.max_rows",200)
print(f"within-window scalp cells tested (n_trials approx) = {n_trials}\n")
surv = R[R.pos=="Y"].copy()
print("=== WITHIN-WINDOW scalp cells with bootstrap CI>0 ===")
print(surv.to_string(index=False) if len(surv) else "  NONE")
# DSR-deflate each survivor (n_trials = total cells searched, conservative variance)
if len(surv):
    print("\n=== DSR (deflated, n_trials =", n_trials, ", variance_trials=0.04 conservative) ===")
    for _, r in surv.iterrows():
        sh_obs = r.t / np.sqrt(r.n)  # per-trade sharpe = t/sqrt(n)
        res = DSR(observed_sharpe=sh_obs, n_samples=int(r.n), n_trials=n_trials,
                  variance_trials=0.04, frequency="daily", periods_per_year=365)
        print(f"  {r.asset} {r.tf} off{r.offset} {r.gate} x{r.exit_dt}: "
              f"scalp={r.scalp:+.2f} t={r.t} -> DSR prob={res.probability:.3f} sig={res.is_significant}")
R.to_csv(r"strategy_lab\directional\_results\midwindow_scalp_robust_2026_06_09.csv", index=False)
