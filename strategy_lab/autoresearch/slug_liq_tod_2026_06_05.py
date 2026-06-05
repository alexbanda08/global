"""
Slug-selection EXP 3 (liquidity-inversion) + EXP 5 (time-of-day) on the confirmed exit-scalp.
Cheap: reuse master_features (gated scalp universe, pnl45/pnl60 precomputed). No L25 load.
EXP3: does scalp $/tr concentrate in LOW-liquidity slugs (Tetlock inversion) or need depth?
EXP5: stable UTC-hour / session pattern? (F2 prior: active 22-02 + 9-10 UTC, avoids US 12-21)
Liquidity proxies = clob pre_/early_ volume + trade-count features already in master_features.
"""
import sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
EXIT = "pnl60"
m = pd.read_parquet(r"strategy_lab\autoresearch\_data\master_features.parquet")
m = m[m.asset.isin(["BTC", "ETH"])].copy()
g = m[m.entry_vwap < 0.55].copy()                     # the confirmed gated cell
g["hour"] = ((g.fire_us // 1_000_000) % 86400) // 3600
print(f"gated scalp universe n={len(g)}  base $/tr({EXIT})={g[EXIT].mean():+.3f}")

def boot(v, nb=4000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))
np.random.seed(0)
def cell(d):
    v = d[EXIT].values
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if len(v) > 2 and v.std() > 0 else np.nan
    lo, hi = boot(v)
    return f"n={len(d):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={d.won.mean():.3f}"

# ---------- EXP 3: liquidity inversion ----------
print("\n===== EXP3 LIQUIDITY: scalp $/tr by liquidity quartile (proxy from clob volume) =====")
for liq in ["pre_vol", "early_vol", "pre_ntr", "early_ntr", "pre_maxsz"]:
    if liq not in g.columns: continue
    gg = g[g[liq].notna()].copy()
    gg["q"] = pd.qcut(gg[liq].rank(method="first"), 4, labels=["Q1_low", "Q2", "Q3", "Q4_high"])
    print(f"\n-- by {liq} --")
    for q, d in gg.groupby("q", observed=True):
        print(f"  {q:8s} {cell(d)}")

# ---------- EXP 5: time-of-day ----------
print("\n===== EXP5 TIME-OF-DAY: scalp $/tr by UTC hour =====")
hr = g.groupby("hour").apply(lambda d: pd.Series({"n": len(d), "dpt": d[EXIT].mean(),
                                                   "won": d.won.mean()}), include_groups=False)
print(hr.round(3).to_string())
print("\n-- session blocks (F2 prior) --")
for name, hrs in [("F2_active 22-02", list(range(22, 24)) + [0, 1]),
                  ("F2_active 09-10", [9, 10]),
                  ("US_hours 12-21 (F2 avoids)", list(range(12, 22))),
                  ("rest", None)]:
    if hrs is None:
        used = set(range(22, 24)) | {0, 1, 9, 10} | set(range(12, 22))
        d = g[~g.hour.isin(used)]
    else:
        d = g[g.hour.isin(hrs)]
    print(f"  {name:30s} {cell(d)}")
print("\nREAD: EXP3 edge>0 only in low-liq quartile = Tetlock inversion (trade thin slugs).")
print("      EXP5 stable + session pattern with CI>0 = a time-of-day slug filter (confirm/refute F2).")
