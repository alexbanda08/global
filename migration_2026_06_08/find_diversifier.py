"""Find the best 3rd sleeve for base = {v8_grandparent + cloud_vwap_v7}: maximize NEW slugs
(low overlap with base) AND high WR + high $/tr + low DD (Calmar) + DSR. Full shadow OOS."""
import csv, math
import numpy as np, pandas as pd

df = pd.read_csv(r"C:\Users\alexandre bandarra\Desktop\global\migration_2026_06_08\all_eth5m.csv")
BASE = ["poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8",
        "poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7"]
base_slugs = set(df[df.sid.isin(BASE)]["slug"])
# common analysis window = where base operates
base_lo = df[df.sid.isin(BASE)]["fire_us"].min()
rng = np.random.default_rng(11)


def boot_ci(x, n=3000):
    x = np.asarray(x, float)
    if len(x) < 5: return (np.nan, np.nan)
    m = np.sort([x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)])
    return float(m[int(.025*n)]), float(m[int(.975*n)])


def dsr(fu, p, nt=25):
    d = pd.DataFrame({"d": (np.asarray(fu)//86_400_000_000), "p": p})
    by = d.groupby("d")["p"].sum().to_numpy()
    if len(by) < 4 or by.std() == 0: return np.nan
    sr = by.mean()/by.std()
    try:
        from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics as f
        from scipy.stats import skew, kurtosis
        r = f(observed_sharpe=float(sr), n_samples=len(by), n_trials=nt,
              variance_trials=float((1+0.5*sr*sr)/len(by)), skewness=float(skew(by)),
              excess_kurtosis=float(kurtosis(by, fisher=True)))
        return float(getattr(r, "dsr", np.nan))
    except Exception:
        return np.nan


rows = []
for sid, g in df.groupby("sid"):
    if sid in BASE: continue
    g = g[g.fire_us >= base_lo]            # restrict to base window
    if len(g) < 30: continue
    span_days = (g.fire_us.max()-g.fire_us.min())/86_400_000_000
    if span_days < 5: continue             # running >5d
    if g.fire_us.max() < df.fire_us.max()-1*86_400_000_000: continue  # still active
    slugs = set(g["slug"])
    new = len(slugs - base_slugs)
    pnl = g["pnl"].to_numpy()
    cum = np.cumsum(pnl); mdd = float((cum-np.maximum.accumulate(cum)).min())
    lo, hi = boot_ci(pnl)
    rows.append(dict(sid=sid.replace("poly_sniper_v5_eth_5m_", ""), n=len(g),
                     new=new, newpct=new/len(slugs)*100, wr=g["won"].mean()*100,
                     dpt=pnl.mean(), tot=pnl.sum(), mdd=mdd,
                     cal=(pnl.sum()/abs(mdd) if mdd < 0 else 99), lo=lo, hi=hi,
                     dsr=dsr(g["fire_us"].to_numpy(), pnl)))

r = pd.DataFrame(rows)
# candidates: positive, decent new-slug share, CI lower > 0 preferred
r = r.sort_values(["dsr", "newpct"], ascending=False)
print(f"base = v8 + cloud_vwap_v7 ({len(base_slugs)} slugs). Candidates (>5d, active, n>=30):\n")
print("%-40s %4s %5s %6s %4s %7s %7s %6s %5s %12s" %
      ("sleeve", "n", "new", "new%", "WR", "$/tr", "MaxDD", "Calmr", "DSR", "CI95"))
for _, x in r.iterrows():
    print("%-40s %4d %5d %5.0f%% %3.0f%% %+7.3f %7.1f %6.2f %5.2f [%+.2f,%+.2f]" %
          (x.sid[:40], x.n, x.new, x.newpct, x.wr, x.dpt, x.mdd, x.cal, x.dsr, x.lo, x.hi))
