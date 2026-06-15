"""Full test: cloud_vwap_v7 with the AGGRESSIVE conviction filter (exclude entry vwap in
[0.40,0.60]; keep |vwap-0.5|>=0.10). Baseline vs filtered. Shadow OOS, $5 and $1-net metrics,
robustness (ex-top2), bootstrap CI, DSR, trades/day."""
import numpy as np, pandas as pd
df = pd.read_csv(r"C:\Users\alexandre bandarra\Desktop\global\migration_2026_06_08\all_eth5m.csv")
g = df[df.sid == "poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7"].dropna(subset=["vwap"]).sort_values("fire_us").copy()
TX = 0.011
rng = np.random.default_rng(9)


def boot_ci(x, n=5000):
    x = np.asarray(x, float)
    m = np.sort([x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)])
    return m[int(.025*n)], m[int(.975*n)]


def dsr(fu, p, nt=25):
    d = pd.DataFrame({"d": np.asarray(fu)//86_400_000_000, "p": p})
    by = d.groupby("d")["p"].sum().to_numpy()
    if len(by) < 4 or by.std() == 0:
        return float("nan")
    sr = by.mean()/by.std()
    try:
        from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics as f
        from scipy.stats import skew, kurtosis
        r = f(observed_sharpe=float(sr), n_samples=len(by), n_trials=nt,
              variance_trials=float((1+0.5*sr*sr)/len(by)), skewness=float(skew(by)),
              excess_kurtosis=float(kurtosis(by, fisher=True)))
        return float(getattr(r, "dsr", float("nan")))
    except Exception:
        return float("nan")


def report(b, tag):
    p5 = b["pnl"].to_numpy()                    # $5 shadow
    p1 = p5/5.0 - TX                            # $1 net of tx
    days = (b.fire_us.max()-b.fire_us.min())/86_400_000_000
    n = len(b); wr = b["won"].mean()
    psort = np.sort(p5)[::-1]
    ex2 = psort[2:].mean()                      # $5 ex-top2
    def mdd(x):
        c = np.cumsum(x); return float((c-np.maximum.accumulate(c)).min())
    lo5, hi5 = boot_ci(p5)
    print(f"\n===== {tag} =====")
    print(f"  n={n}  trades/dia={n/days:.1f}  dias={days:.1f}  WR={wr*100:.1f}%  avg_vwap={b.vwap.mean():.3f}")
    print(f"  trades_ganhos={int(b['won'].sum())}  trades_perdidos={int((~b['won'].astype(bool)).sum())}")
    print(f"  [$5 shadow]  $/tr={p5.mean():+.3f}  total=${p5.sum():+.1f}  MaxDD=${mdd(p5):.1f}  "
          f"Calmar={p5.sum()/abs(mdd(p5)):.2f}  ex-top2=${ex2:+.3f}")
    print(f"  [$5] CI95 $/tr=[{lo5:+.3f},{hi5:+.3f}]  DSR={dsr(b.fire_us.to_numpy(), p5):.2f}")
    print(f"  [$1 net]     $/tr=${p1.mean():+.4f}  total=${p1.sum():+.2f}  MaxDD=${mdd(p1):.2f}  "
          f"Calmar={p1.sum()/abs(mdd(p1)):.2f}  $/dia=${p1.sum()/days:+.2f}")


base = g
filt = g[(g.vwap <= 0.40) | (g.vwap >= 0.60)]     # exclude 0.40-0.60
excl = g[(g.vwap > 0.40) & (g.vwap < 0.60)]       # what we cut

report(base, "BASELINE (todos, sem filtro)")
report(filt, "FILTRADO (exclui vwap 0.40-0.60)")
print("\n----- o que foi CORTADO (vwap 0.40-0.60) -----")
print(f"  n={len(excl)}  WR={excl['won'].mean()*100:.1f}%  $/tr(${'5'})={excl['pnl'].mean():+.3f}  total=${excl['pnl'].sum():+.1f}")
print(f"  destes, perdedores={int((~excl['won'].astype(bool)).sum())} de {len(excl)}")
