"""V29 portfolio hunt — can V29 sleeves beat V28's P2 (SUI+SOL+ETH Donch)?

Approach: same yearly-rebalanced-equal-weight convention as V28. Pool =
V29 OOS-PASS strategies UNION V28 winners (re-load from V23/V27 pickles).
Scan 2..5 combos, score by worst-year CAGR 2023-2025.
"""
from __future__ import annotations
import pickle, itertools
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
OUT = RES / "v29"
OUT.mkdir(parents=True, exist_ok=True)

# V29 winners pickle
V29 = RES / "v29" / "v29_regime_results.pkl"
# V23 and V27 for V28-equivalent sleeves
SOURCES = [
    ("V23", RES / "v23" / "v23_results_with_oos.pkl"),
    ("V27", RES / "v27" / "v27_swing_results.pkl"),
    ("V29", V29),
]


def year_cagr(eq, y):
    s = pd.Timestamp(f"{y}-01-01", tz="UTC"); e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
    slc = eq[(eq.index >= s) & (eq.index < e)]
    if len(slc) < 20: return None
    ret = slc.iloc[-1] / slc.iloc[0] - 1
    yrs = (slc.index[-1] - slc.index[0]).total_seconds() / (365.25 * 86400)
    return (1 + ret) ** (1/max(yrs, 1e-6)) - 1


def eq_from_entry(d):
    idx = pd.to_datetime(d.get("eq_index"), utc=True)
    vals = np.asarray(d.get("eq_values"), dtype=float)
    return pd.Series(vals, index=idx).dropna()


# ===== Select sleeves =====
# V29 PASS list (from the OOS audit we just ran)
V29_PASS = {
    "SUI Lateral_BB_Fade 1h", "ETH Lateral_BB_Fade 4h", "SOL Lateral_BB_Fade 4h",
    "TON Trend_Grade_MTF 4h", "AVAX Lateral_BB_Fade 4h", "LINK Lateral_BB_Fade 4h",
    "INJ Lateral_BB_Fade 4h", "BTC Lateral_BB_Fade 4h", "SUI Regime_Switch 4h",
    "LINK Trend_Grade_MTF 4h", "INJ Trend_Grade_MTF 4h", "BTC Regime_Switch 4h",
    "ETH Regime_Switch 4h", "AVAX Trend_Grade_MTF 4h", "SOL Trend_Grade_MTF 4h",
    "INJ Regime_Switch 4h",
}

# V28 winners that we want in the blend pool (V23 is per-sym, V27 is per-sym_family)
V28_KEYS = {
    "V23::SUIUSDT",       # SUI BBBreak_LS 4h
    "V23::SOLUSDT",       # SOL BBBreak_LS 4h
    "V23::DOGEUSDT",      # DOGE BBBreak_LS 4h
    "V27::ETHUSDT_HTF_DONCHIAN",
    "V27::SOLUSDT_HTF_DONCHIAN",
    "V27::BTCUSDT_HTF_DONCHIAN",
    "V27::DOGEUSDT_HTF_DONCHIAN",
}


strats = {}
for tag, path in SOURCES:
    if not path.exists(): continue
    d = pickle.load(open(path, "rb"))
    for key, v in d.items():
        sym = v.get("sym",""); fam = v.get("family",""); tf = v.get("tf","")
        full_key = f"{tag}::{key}"
        label = f"{sym[:-4] if sym.endswith('USDT') else sym} {fam} {tf}"
        try: eq = eq_from_entry(v)
        except Exception: continue
        if len(eq) < 200: continue

        # Only keep V29 passes OR V28-whitelist V23/V27
        keep = False
        if tag == "V29" and label in V29_PASS: keep = True
        if full_key in V28_KEYS: keep = True
        if not keep: continue

        yrs = {y: year_cagr(eq, y) for y in (2023, 2024, 2025)}
        score = sum(v for v in yrs.values() if v is not None)
        strats[full_key] = dict(sym=sym, family=fam, tf=tf, eq=eq, yrs=yrs,
                                score=score, tag=tag, label=label)

print(f"pool = {len(strats)}")
for k, s in sorted(strats.items(), key=lambda kv: -kv[1]["score"]):
    ys = s["yrs"]
    fmt = lambda v: f"{v*100:+7.1f}%" if v is not None else "    n/a"
    print(f"  {k:42s} {s['label']:30s}  "
          f"y23={fmt(ys[2023])}  y24={fmt(ys[2024])}  y25={fmt(ys[2025])}")


def year_cagr_blend(members, y):
    vals = []
    for m in members:
        v = m["yrs"].get(y)
        vals.append(v if v is not None else 0.0)
    return sum(vals) / len(vals)


# ===== 100%/yr hunt =====
pool = list(strats.keys())
best_100 = []
best_worst = []  # ranked by max min-year CAGR even if < 100

for r in (3, 4, 5):
    for combo in itertools.combinations(pool, r):
        entries = [strats[k] for k in combo]
        syms = set(e["sym"] for e in entries)
        if len(syms) != len(entries): continue  # no same-coin stacking
        yc = {y: year_cagr_blend(entries, y) for y in (2023, 2024, 2025)}
        if any(v is None for v in yc.values()): continue
        worst = min(yc.values())

        row = {
            "size": r,
            "worst_CAGR%": round(worst * 100, 1),
            "y23": round(yc[2023]*100, 1),
            "y24": round(yc[2024]*100, 1),
            "y25": round(yc[2025]*100, 1),
            "members": " | ".join(e["label"] for e in entries),
        }
        if worst >= 1.0:
            best_100.append(row)
        best_worst.append(row)

print(f"\n100%+/yr portfolios: {len(best_100)}")
if best_100:
    df = pd.DataFrame(best_100).sort_values("worst_CAGR%", ascending=False)
    df.to_csv(OUT / "v29_portfolio_100pct.csv", index=False)
    print("\nTOP 15 (sorted by WORST-year CAGR):")
    pd.set_option('display.max_colwidth', 200)
    print(df.head(15).to_string(index=False))

# Also save top-30 by worst-year CAGR
df2 = pd.DataFrame(best_worst).sort_values("worst_CAGR%", ascending=False).head(30)
df2.to_csv(OUT / "v29_portfolio_top30.csv", index=False)
print(f"\nTop-30 by worst-year CAGR (includes near-misses):")
print(df2.to_string(index=False))
