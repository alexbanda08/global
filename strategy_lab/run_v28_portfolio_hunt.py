"""V28 portfolio hunt — compact version.

Preselect top candidates by per-year CAGR (2023+2024+2025 sum), then
try 2-4 combos. Known-leaky families excluded.
"""
from __future__ import annotations
import pickle, itertools, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
OUT = RES / "v28"
OUT.mkdir(parents=True, exist_ok=True)

SOURCES = [
    ("V23", RES / "v23" / "v23_results_with_oos.pkl"),
    ("V25", RES / "v25" / "v25_creative_results.pkl"),
    ("V26", RES / "v26" / "v26_priceaction_results.pkl"),
    ("V27", RES / "v27" / "v27_swing_results.pkl"),
]
BANNED_FAMILIES = {"Order_Block", "MTF_Conf"}  # leaky

def eq_from_entry(d):
    idx = pd.to_datetime(d.get("eq_index"), utc=True)
    vals = np.asarray(d.get("eq_values"), dtype=float)
    return pd.Series(vals, index=idx).dropna()

def year_cagr(eq, y):
    s = pd.Timestamp(f"{y}-01-01", tz="UTC"); e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
    slc = eq[(eq.index >= s) & (eq.index < e)]
    if len(slc) < 20: return None
    ret = slc.iloc[-1] / slc.iloc[0] - 1
    yrs = (slc.index[-1] - slc.index[0]).total_seconds() / (365.25 * 86400)
    return (1 + ret) ** (1/max(yrs, 1e-6)) - 1

t0 = time.time()
strats = {}
for tag, path in SOURCES:
    if not path.exists(): continue
    d = pickle.load(open(path, "rb"))
    for key, v in d.items():
        sym = v.get("sym",""); fam = v.get("family","")
        m = v.get("metrics", {}) or {}
        n = int(m.get("n", 0)); sh = float(m.get("sharpe", 0))
        if fam in BANNED_FAMILIES or n < 20 or sh <= 0: continue
        try: eq = eq_from_entry(v)
        except Exception: continue
        if len(eq) < 200: continue
        yrs = {y: year_cagr(eq, y) for y in (2023, 2024, 2025)}
        score = sum(v for v in yrs.values() if v is not None)
        strats[f"{tag}::{key}"] = {"sym": sym, "family": fam, "tf": v.get("tf",""),
                                    "n": n, "sharpe": sh, "eq": eq, "yrs": yrs,
                                    "score": score, "tag": tag}

print(f"pool={len(strats)} in {time.time()-t0:.1f}s")

# Resample each equity curve to daily — massively speeds up combine()
for s in strats.values():
    s["eq"] = s["eq"].resample("1D").last().ffill().dropna()

# Rank candidates by the simple sum-of-yearly-CAGRs objective, keep top 12
ranked = sorted(strats.items(), key=lambda kv: -kv[1]["score"])[:12]
print("\nTop 15 candidates by (y2023 + y2024 + y2025):")
def fmt(v): return f"{v*100:+7.1f}%" if v is not None else "    n/a"
for k, s in ranked:
    ys = s["yrs"]
    print(f"  {k:40s} {s['sym']:10s} {s['family']:15s} {s['tf']:3s}  "
          f"sh={s['sharpe']:+.2f}  y23={fmt(ys[2023])}  "
          f"y24={fmt(ys[2024])}  y25={fmt(ys[2025])}")

def norm(eq): return (eq / eq.iloc[0])

def combine(entries):
    curves = [norm(e["eq"]) for e in entries]
    idx = sorted(set().union(*[c.index for c in curves]))
    df = pd.DataFrame({i: c.reindex(idx).ffill() for i, c in enumerate(curves)}, index=idx)
    return df.mean(axis=1, skipna=True)

pool = [k for k,_ in ranked]
best = []
checked = 0

# Convention: yearly-rebalanced-to-equal-weight portfolio.
# Per-year portfolio CAGR = simple mean of per-strat CAGRs for strategies
# that have data in that year (live) — missing strats get a 0% contribution
# (their capital sat uninvested that year).
#
# Why: this models "same $X into each strategy, rebalanced every Jan 1".
# It's what you'd actually run as a live portfolio, not a BH-of-strats
# drifted-weight blend.
def year_cagr_blend(members, y):
    vals = []
    for m in members:
        v = m["yrs"].get(y)
        if v is not None: vals.append(v)
        else: vals.append(0.0)  # capital idle that year
    if not vals: return None
    return sum(vals) / len(vals)

for r in (2, 3, 4):
    for combo in itertools.combinations(pool, r):
        entries = [strats[k] for k in combo]
        syms = set(e["sym"] for e in entries)
        if len(syms) != len(entries): continue
        yc = {y: year_cagr_blend(entries, y) for y in (2023, 2024, 2025)}
        checked += 1
        if all(yc[y] is not None and yc[y] >= 1.0 for y in (2023,2024,2025)):
            mems = [f"{e['tag']} {e['sym']} {e['family']} {e['tf']}" for e in entries]
            best.append({
                "size": r,
                "members": " | ".join(mems),
                "y23": round(yc[2023]*100,1),
                "y24": round(yc[2024]*100,1),
                "y25": round(yc[2025]*100,1),
                "min_y": round(min(yc.values())*100,1),
            })

print(f"\ncombos checked: {checked},  winners: {len(best)}")
if best:
    df = pd.DataFrame(best).sort_values("min_y", ascending=False)
    df.to_csv(OUT / "portfolio_winners.csv", index=False)
    print("\nTOP 20 winning portfolios (sorted by WORST-year CAGR):")
    # widen display
    pd.set_option('display.max_colwidth', 200)
    print(df.head(20).to_string(index=False))
