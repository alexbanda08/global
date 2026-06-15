"""Pre-registered single-hypothesis OOS test (no searching).
HYPOTHESIS (mechanistic): begin-window BTC 5m lag-rebound scalp + momentum-alignment.
  entry offset 30-60s, buy binance-leading cheap token (vwap<0.55), |lag| in [3,12],
  lag sign == 30s-momentum sign; book-sell at +45s.
Split by TIME: IS = first 60%, OOS = last 40%. Report OOS $/tr + bootstrap CI.
Compare WITH vs WITHOUT momalign (is the regime filter the lift?).
"""
import sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
np.random.seed(1)
C = pd.read_parquet(r"strategy_lab\directional\_results\midwindow_scalp_cache_2026_06_09.parquet")
def sp(ev, sell, sh): return (sell-ev)*sh - 0.07*sh*ev*(1-ev) - 0.07*sh*sell*(1-sell)
def boot(v, nb=5000):
    if len(v) < 8: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))
def stats(pnl, name):
    t = pnl.mean()/pnl.std(ddof=1)*np.sqrt(len(pnl)) if (len(pnl)>1 and pnl.std()>0) else np.nan
    lo, hi = boot(pnl)
    print(f"  {name:34s} n={len(pnl):4d} wr_na  $/tr={pnl.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] {'POS' if lo>0 else '.'}")

EXIT = 45
for asset in ["BTC", "ETH"]:
    d = C[(C.asset==asset)&(C.tf=="5m")&(C.offset.isin([30,60]))].copy()
    d = d[d.entry_vwap<0.55]
    sell = pd.to_numeric(d[f"bid_{EXIT}"], errors="coerce")
    d = d[np.isfinite(sell)]; d["sell"]=sell[d.index]
    d = d.sort_values("e_us").reset_index(drop=True)
    cut = int(len(d)*0.6)
    base = (d.abs_lag.between(3,12))
    mom = base & (np.sign(d.lag_bps)==np.sign(d.mom30))
    print(f"\n===== {asset} 5m off{{30,60}} cheap exit+{EXIT}s =====  total fills={len(d)}  IS/OOS cut@{cut}")
    for label, m in [("lag[3,12]  (no regime)", base), ("lag[3,12]+momalign", mom)]:
        dm = d[m]
        pnl_all = sp(dm.entry_vwap.values, dm.sell.values, dm.shares.values)
        isd = dm[dm.index<cut]; oosd = dm[dm.index>=cut]
        stats(pnl_all, label+" ALL")
        if len(isd)>=8:  stats(sp(isd.entry_vwap.values,isd.sell.values,isd.shares.values), label+" IS")
        if len(oosd)>=8: stats(sp(oosd.entry_vwap.values,oosd.sell.values,oosd.shares.values), label+" OOS")
print("\nREAD: only worth a forward test if momalign OOS $/tr CI>0 AND beats no-regime OOS.")
