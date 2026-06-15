"""Rank 15m shadow sleeves for Kalshi deploy. Filters: offset>=60 (Kalshi book exists after
+30s), running>=5d, active, n>=30, robust (top2%<=40 & ex-top2 $/tr>0). Rank by ex-top2 then WR.
Note: shadow PnL is Polymarket-fill; for Kalshi the DIRECTIONAL WR/robustness transfer, $/tr is
indicative (Kalshi fill/fee differ)."""
import numpy as np, pandas as pd

df = pd.read_csv(r"C:\Users\alexandre bandarra\Desktop\global\migration_2026_06_08\all_15m.csv")
gmax = df.fire_us.max()
rng = np.random.default_rng(5)


def ci(x, n=3000):
    x = np.asarray(x, float)
    if len(x) < 5:
        return (np.nan, np.nan)
    m = np.sort([x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)])
    return m[int(.025*n)], m[int(.975*n)]


def dsr(fu, p, nt=25):
    d = pd.DataFrame({"d": np.asarray(fu)//86_400_000_000, "p": p})
    by = d.groupby("d")["p"].sum().to_numpy()
    if len(by) < 4 or by.std() == 0:
        return np.nan
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
    asset = g.asset.iloc[0]
    minoff = g.offset.min()
    if len(g) < 30:
        continue
    span = (g.fire_us.max()-g.fire_us.min())/86_400_000_000
    if span < 5 or g.fire_us.max() < gmax-1*86_400_000_000:
        continue
    p = np.sort(g["pnl"].to_numpy())[::-1]
    n = len(p); tot = p.sum()
    top2pct = (p[:2].sum()/tot*100) if tot > 0 else 999
    ex2 = p[2:].mean()
    gg = g.sort_values("fire_us")["pnl"].to_numpy()
    cum = np.cumsum(gg); mdd = float((cum-np.maximum.accumulate(cum)).min())
    lo, hi = ci(g["pnl"].to_numpy())
    rows.append(dict(sid=sid.replace("poly_sniper_v5_", ""), a=asset, off=int(minoff), n=n,
                     wr=g["won"].mean()*100, dpt=tot/n, ex2=ex2, top2=top2pct, mdd=mdd,
                     cal=(tot/abs(mdd) if mdd < 0 else 99), lo=lo, hi=hi,
                     dsr=dsr(g["fire_us"].to_numpy(), g["pnl"].to_numpy())))
r = pd.DataFrame(rows)
# Kalshi-compatible = offset>=60
rob = r[(r.off >= 60) & (r.top2 <= 40) & (r.ex2 > 0)].sort_values(["dsr", "ex2"], ascending=False)
print("15m sleeves — KALSHI-COMPATIBLE (offset>=60), robust, profitable. Rank DSR/ex-top2:\n")
print("%-42s %3s %4s %4s %4s %7s %8s %5s %6s %5s %14s" %
      ("sleeve", "ast", "off", "n", "WR", "$/tr", "ex-top2", "top2", "Calmr", "DSR", "CI95"))
for _, x in rob.iterrows():
    print("%-42s %3s %4d %4d %3.0f%% %+7.3f %+8.3f %4.0f%% %6.2f %5.2f [%+.2f,%+.2f]" %
          (x.sid[:42], x.a, x.off, x.n, x.wr, x.dpt, x.ex2, x.top2, x.cal, x.dsr, x.lo, x.hi))

print("\n--- offset<60 (NÃO serve p/ Kalshi — book só +30s) ---")
for _, x in r[r.off < 60].sort_values("ex2", ascending=False).head(6).iterrows():
    print("  %-40s %s off=%d n=%d $/tr=%+.3f WR=%.0f%%" % (x.sid[:40], x.a, x.off, x.n, x.dpt, x.wr))
print("\n--- rejeitadas por contaminação top2>40% (15m, off>=60) ---")
for _, x in r[(r.off >= 60) & (r.top2 > 40)].sort_values("top2", ascending=False).head(6).iterrows():
    print("  %-40s %s n=%d $/tr=%+.3f ex2=%+.3f top2=%.0f%%" % (x.sid[:40], x.a, x.n, x.dpt, x.ex2, x.top2))
