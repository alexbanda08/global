"""Analyze: do PROFITABLE shadow sleeves keep their edge as a SCALP (book-exit
at +Delta) or is it priced-in (hold > scalp)? Fidelity = engine_v2 fee model.

hold (to resolution, winner-only fee): won -> sh*(1-ev)*(1-0.07*ev); lost -> -sh*ev
scalp (book-sell both-leg taker fee): (sell-ev)*sh - 0.07*sh*ev*(1-ev) - 0.07*sh*sell*(1-sell)
  (if no book at Delta -> fall back to hold)

Splits by entry_vwap band (cheap-entry <0.55 = where exit-scalp edge lives vs
favorite-buy >=0.55). Bootstrap CI per cell; paired diff (best-scalp - hold).
"""
import sys
import numpy as np, pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
np.random.seed(0)

C = pd.read_parquet(r"strategy_lab\directional\_results\sleeve_scalp_cache_2026_06_09.parquet")
C = C[C.get("filled", False) == True].copy().reset_index(drop=True)
DTS = [15, 30, 45, 60, 90, 120, 150, 180]

def scalp_pnl(ev, sell, sh):
    return (sell - ev) * sh - 0.07 * sh * ev * (1 - ev) - 0.07 * sh * sell * (1 - sell)

def hold_pnl(won, ev, sh):
    return np.where(won, sh * (1 - ev) * (1 - 0.07 * ev), -sh * ev)

def boot(v, nb=4000):
    if len(v) < 8: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))

def tstat(v):
    return v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if (len(v) > 1 and v.std() > 0) else np.nan

def eval_cell(d):
    ev = d.entry_vwap.values; sh = d.shares.values; won = d.won.values.astype(bool)
    hold = hold_pnl(won, ev, sh)
    scalps = {}
    for dt in DTS:
        sell = pd.to_numeric(d[f"bid_{dt}"], errors="coerce").values
        s = np.where(np.isfinite(sell), scalp_pnl(ev, sell, sh), hold)
        scalps[dt] = s
    return hold, scalps

print(f"cache filled rows={len(C)}  sleeves={C.sleeve_id.nunique()}\n")
rows = []
for sl, d in C.groupby("sleeve_id"):
    d = d.reset_index(drop=True)
    for band, m in [("ALL", np.ones(len(d), bool)),
                    ("cheap<0.55", d.entry_vwap.values < 0.55),
                    ("fav>=0.55", d.entry_vwap.values >= 0.55)]:
        dd = d[m]
        if len(dd) < 15: continue
        hold, scalps = eval_cell(dd)
        best_dt = max(DTS, key=lambda x: np.nanmean(scalps[x]))
        bs = scalps[best_dt]
        blo, bhi = boot(bs)
        diff = bs - hold
        dlo, dhi = boot(diff)
        rows.append(dict(
            sleeve=sl.replace("poly_sniper_v5_", ""), band=band, n=len(dd),
            wr=round(100*dd.won.mean(),1), ev=round(dd.entry_vwap.mean(),3),
            hold=round(hold.mean(),3), hold_t=round(tstat(hold),2),
            best_dt=best_dt, scalp=round(bs.mean(),3), scalp_t=round(tstat(bs),2),
            scalp_lo=round(blo,3), scalp_hi=round(bhi,3),
            scalp_pos=("Y" if blo>0 else "."),
            vs_hold=round(diff.mean(),3), vs_hold_lo=round(dlo,3),
            scalp_beats_hold=("Y" if dlo>0 else "."),
        ))

R = pd.DataFrame(rows).sort_values(["band","scalp"], ascending=[True,False])
pd.set_option("display.width", 240, "display.max_columns", 40, "display.max_rows", 200)
print(R.to_string(index=False))
R.to_csv(r"strategy_lab\directional\_results\sleeve_scalp_verdict_2026_06_09.csv", index=False)
print("\n=== SURVIVORS: scalp $/tr CI>0 (book-exit edge survives) ===")
surv = R[R.scalp_pos=="Y"]
print(surv.to_string(index=False) if len(surv) else "  NONE")
print("\n=== scalp BEATS hold (CI>0 on paired diff) ===")
sb = R[R.scalp_beats_hold=="Y"]
print(sb.to_string(index=False) if len(sb) else "  NONE")
