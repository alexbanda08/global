"""Best 3-sleeve portfolio — PROPER: full shadow OOS, bootstrap CI on $/tr + daily DSR.
Combine per-fire PnL streams (time-ordered). Rank triples by DSR then CI-lower."""
import csv, itertools, math
import numpy as np
import pandas as pd

sh = pd.read_csv(r"C:\Users\alexandre bandarra\Desktop\global\migration_2026_06_08\shadow_full.csv")
TAGS = ["v8_grandparent", "cloud_vwap_v7", "cloud_ribbon_v6", "cloud_ribbon_V10", "v6c3_v7"]
streams = {t: sh[sh["tag"] == t][["fire_us", "pnl"]].values for t in TAGS}
rng = np.random.default_rng(7)


def boot_ci(x, n=4000):
    x = np.asarray(x, float)
    if len(x) < 5:
        return (np.nan, np.nan)
    m = np.sort([x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)])
    return float(m[int(.025 * n)]), float(m[int(.975 * n)])


def dsr(fire_us, pnl, n_trials=25):
    df = pd.DataFrame({"d": (np.asarray(fire_us) // 86_400_000_000), "p": pnl})
    byday = df.groupby("d")["p"].sum().to_numpy()
    if len(byday) < 4 or byday.std() == 0:
        return np.nan
    sr = byday.mean() / byday.std()
    try:
        from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics as f
        from scipy.stats import skew, kurtosis
        var_tr = (1.0 + 0.5 * sr * sr) / len(byday)
        r = f(observed_sharpe=float(sr), n_samples=len(byday), n_trials=n_trials,
              variance_trials=float(var_tr), skewness=float(skew(byday)), excess_kurtosis=float(kurtosis(byday, fisher=True)))
        return float(getattr(r, "dsr", getattr(r, "probability", np.nan)))
    except Exception:
        return np.nan


def port(tags):
    allf = np.vstack([streams[t] for t in tags])
    allf = allf[allf[:, 0].argsort()]
    fu, pnl = allf[:, 0], allf[:, 1]
    n = len(pnl)
    cum = np.cumsum(pnl); mdd = float((cum - np.maximum.accumulate(cum)).min())
    lo, hi = boot_ci(pnl)
    return dict(n=n, mean=pnl.mean(), tot=pnl.sum(), mdd=mdd,
                cal=(pnl.sum() / abs(mdd) if mdd < 0 else float("inf")),
                lo=lo, hi=hi, dsr=dsr(fu, pnl))


print("SINGLES (full shadow OOS):")
print("%-17s %4s %7s %7s %18s %5s" % ("sleeve", "n", "$/tr", "Calmar", "CI95", "DSR"))
for t in TAGS:
    m = port([t])
    print("%-17s %4d %+7.3f %7.2f [%+.2f,%+.2f]   %.2f" % (t, m["n"], m["mean"], m["cal"], m["lo"], m["hi"], m["dsr"]))

print("\nALL TRIPLES (ranked by DSR, then CI-lower):")
res = []
for c in itertools.combinations(TAGS, 3):
    res.append((c, port(list(c))))
res.sort(key=lambda r: (-(r[1]["dsr"] if not math.isnan(r[1]["dsr"]) else -9), -r[1]["lo"]))
print("%-46s %4s %7s %7s %18s %5s %4s" % ("portfolio", "n", "$/tr", "Calmar", "CI95", "DSR", "CI>0"))
for c, m in res:
    pos = "YES" if m["lo"] > 0 else "no"
    print("%-46s %4d %+7.3f %7.2f [%+.2f,%+.2f]   %.2f  %s"
          % ("+".join(t.replace("_grandparent", "").replace("cloud_", "") for t in c),
             m["n"], m["mean"], m["cal"], m["lo"], m["hi"], m["dsr"], pos))
