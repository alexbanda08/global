"""
Slug-selection: time-gate refinement + EXP2 (cross-token price-sum) + EXP4 (reversal-state imbalance).
Cheap, no L25 reload. master_features for pnl60/hour/buyimb; physics cache for the true book price-sum.
"""
import sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
EXIT = "pnl60"
def boot(v, nb=4000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
def line(d, name, col=EXIT):
    v = d[col].dropna().values
    if len(v) < 5: print(f"  {name:26s} n={len(v):4d} (few)"); return
    t = v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    print(f"  {name:26s} n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] tot={v.sum():+.0f}")

m = pd.read_parquet(r"strategy_lab\autoresearch\_data\master_features.parquet")
g = m[(m.asset.isin(["BTC", "ETH"])) & (m.entry_vwap < 0.55)].copy()
g["hour"] = ((g.fire_us // 1_000_000) % 86400) // 3600
g["date"] = pd.to_datetime(g.fire_us, unit="us").dt.floor("D")

# ---------- TIME-GATE: exclude dead hours, keep coverage ----------
print(f"===== TIME-GATE (base: n={len(g)} $/tr={g[EXIT].mean():+.3f} tot={g[EXIT].sum():+.0f}) =====")
hr = g.groupby("hour")[EXIT].agg(["size", "mean"]).round(2)
dead = hr[hr["mean"] < 1.0].index.tolist()
print(f"hours with $/tr<1.0 (candidates to exclude): {dead}")
for name, excl in [("exclude {12,17}", {12, 17}), ("exclude {2,12,16,17,18}", {2, 12, 16, 17, 18}),
                   ("exclude 12-18 (US midday)", set(range(12, 19))), ("keep 22-02 only", None)]:
    d = g[g.hour.isin([22, 23, 0, 1])] if excl is None else g[~g.hour.isin(excl)]
    cov = len(d) / len(g)
    print(f"  {name:26s} coverage={cov:.0%}", end=" "); line(d, "")
# walk-forward the best light gate (exclude {12,17}) across 3 folds
print("walk-forward exclude{12,17}:")
days = g.date.drop_duplicates().sort_values().values
for i, fd in enumerate(np.array_split(days, 3)):
    d = g[g.date.isin(fd) & ~g.hour.isin({12, 17})]
    line(d, f"fold{i+1}")

# ---------- EXP4: reversal-state imbalance ----------
print("\n===== EXP4 REVERSAL (book/flow imbalance buyimb; reversal = imbalance vs realized move) =====")
for c in ["pre_buyimb", "early_buyimb"]:
    g["q"] = pd.qcut(g[c].rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
    print(f"-- {c} quartile --")
    for q, d in g.groupby("q", observed=True): line(d, str(q))

# ---------- EXP2: cross-token price-sum deviation (physics cache) ----------
print("\n===== EXP2 CROSS-TOKEN PRICE-SUM (|entry_vwap + opp_ask - 1|) =====")
c = pd.read_parquet(r"strategy_lab\directional\_results\scalp_hedge_physics_cache_2026_06_03.parquet")
c = c[(c.asset.isin(["BTC", "ETH"])) & (c.filled == 1) & (c.entry_vwap < 0.55)].copy()
# book price-sum at ~fire: lead entry_vwap + opposite-token ask (oppask_30 = nearest available)
opp = pd.to_numeric(c.get("oppask_30"), errors="coerce")
c["psum"] = c.entry_vwap + opp
c["psum_dev"] = (c.psum - 1.0).abs()
def bpnl(sell, ev, sh): return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))
def hold(won, ev, sh): return np.where(won, sh * (1 - ev) * (1 - 0.07 * ev), -sh * ev)
b60 = pd.to_numeric(c.bid_60, errors="coerce").values
c["pnl60"] = np.where(np.isfinite(b60), bpnl(b60, c.entry_vwap.values, c.shares.values),
                      hold(c.won.values.astype(bool), c.entry_vwap.values, c.shares.values))
cc = c[c.psum_dev.notna()].copy()
print(f"  cache gated fires with opp_ask: {len(cc)}  psum mean={cc.psum.mean():.3f} (live cross-token ~1.30 ref)")
cc["q"] = pd.qcut(cc.psum_dev.rank(method="first"), 4, labels=["Q1_tight", "Q2", "Q3", "Q4_wide"])
for q, d in cc.groupby("q", observed=True): line(d, str(q))
print("\nREAD: EXP4/EXP2 useful only if a bin shows materially higher $/tr with CI>0 vs base; near-flat=null.")
