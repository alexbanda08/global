"""FAITHFUL v8 vs v10 re-run on the EXISTING v8 universe (exact gate columns from the real
builders) + CORRECT 0.07 fee + ml4t DSR. Window = original GA Apr24->May26 (in-sample).
This avoids feature-reproduction drift (the from-scratch klines recompute gave WR 47.8 vs 82
= unfaithful). Goal: confirm profitable + exact v10-gate (g_sms_no_liquidity_above) delta.

Run: C:/Python314/python.exe strategy_lab/directional/eth5m_v8_v10_faithful_2026_06_08.py
"""
from __future__ import annotations
import os, sys, datetime as dt
import numpy as np, pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES = os.path.join(ROOT, r"data\v4\canonical\_results")
U = os.path.join(RES, "_sniper_eth5m_v8_universe.parquet")
STAKE, FEE = 5.0, 0.07

df = pd.read_parquet(U)
print("universe rows:", len(df), "cols incl:", [c for c in df.columns if c in
      ("fire_offset_s", "direction", "won", "entry_vwap", "fire_us", "ws_s_us")])
off = "fire_offset_s" if "fire_offset_s" in df.columns else "offset_s"
print("offsets:", sorted(df[off].dropna().unique())[:10])
d = df[df[off] == 60].copy()
print("offset60 rows:", len(d))

GATES8 = ["g_tr_above_ema50", "g_hurst_trending", "g_grandparent_trend_with"]
GSMS = "g_sms_no_liquidity_above"
for g in GATES8 + [GSMS]:
    d[g] = d[g].fillna(0).astype(int)


def pnl07(won, v):
    sh = STAKE / v
    return sh * (1 - v) * (1 - FEE * v) if won else -sh * v


# entry_vwap valid + winner-only pnl
d = d[d["entry_vwap"].notna() & (d["entry_vwap"] > 0.001) & (d["entry_vwap"] < 0.999)].copy()
d["won"] = d["won"].astype(bool)
d["pnl"] = [pnl07(w, v) for w, v in zip(d["won"], d["entry_vwap"])]
fcol = "fire_us" if "fire_us" in d.columns else "ws_s_us"


def metrics(x):
    if len(x) == 0:
        return dict(n=0)
    s = x.sort_values(fcol); p = s["pnl"].to_numpy()
    cum = np.cumsum(p); mdd = float((cum - np.maximum.accumulate(cum)).min())
    day = (s[fcol].to_numpy() // 86_400_000_000); _, idx = np.unique(day, return_inverse=True)
    byday = np.bincount(idx, weights=p)
    sh = (byday.mean()/byday.std()*np.sqrt(365)) if (len(byday) > 1 and byday.std() > 0) else 0.0
    return dict(n=len(s), wr=float(s["won"].mean()), dpt=float(p.mean()), total=float(p.sum()),
                mdd=mdd, calmar=float(p.sum()/abs(mdd)) if mdd < 0 else float("inf"),
                sharpe=sh, days=len(np.unique(day)), byday=byday)


def dsr(byday, n_trials):
    try:
        from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics as f
        sr = byday.mean()/byday.std() if byday.std() > 0 else 0.0
        from scipy.stats import skew, kurtosis
        return round(float(f(observed_sr=sr, benchmark_sr=0.0, n_trials=max(1, n_trials),
                     n_observations=len(byday), skewness=float(skew(byday)),
                     kurtosis=float(kurtosis(byday, fisher=False)))), 3)
    except Exception as e:
        # fallback: simple bootstrap p(total>0)
        try:
            rng = np.random.default_rng(7); m = []
            for _ in range(2000):
                m.append(byday[rng.integers(0, len(byday), len(byday))].sum())
            return f"boot_p(>0)={np.mean(np.array(m) > 0):.3f}"
        except Exception as e2:
            return f"err:{str(e)[:30]}"


def show(name, x, nt):
    m = metrics(x)
    if m["n"] == 0:
        print(f"{name}: 0"); return m
    print(f"{name:5s} n={m['n']:5d} WR={m['wr']*100:5.1f}% $/tr={m['dpt']:+6.3f} total=${m['total']:+8.1f} "
          f"MaxDD=${m['mdd']:7.1f} Calmar={m['calmar']:6.2f} Sharpe={m['sharpe']:5.2f} days={m['days']} "
          f"DSR={dsr(m['byday'], nt)}")
    return m


v8 = d[(d[GATES8[0]] == 1) & (d[GATES8[1]] == 1) & (d[GATES8[2]] == 1)].copy()
v10 = v8[v8[GSMS] == 1].copy()
print(f"\n==== FAITHFUL v8 vs v10 (exact gate cols, 0.07 fee, $5) — Apr24->May26 in-sample ====")
m8 = show("v8", v8, 300)
m10 = show("v10", v10, 200)
if m8.get("n") and m10.get("n"):
    print(f"\nv10 vs v8: n {m8['n']}->{m10['n']} ({m10['n']/m8['n']*100:.0f}% kept) | "
          f"$/tr {m8['dpt']:+.3f}->{m10['dpt']:+.3f} | total ${m8['total']:+.1f}->${m10['total']:+.1f} | "
          f"MaxDD ${m8['mdd']:.1f}->${m10['mdd']:.1f} | Calmar {m8['calmar']:.2f}->{m10['calmar']:.2f}")
print("\n(legacy-fee study claim: v8 WR~82 MaxDD-$25 Calmar17.3 ; v10 Calmar23.7)")
