"""V30 portfolio hunt — pool = V30 OOS PASS ∪ V29 PASS ∪ V28 winners.
Scan 2..5 combos, score by worst-year CAGR 2023-2025, require distinct coins."""
from __future__ import annotations
import pickle, itertools
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
OUT = RES / "v30"
OUT.mkdir(parents=True, exist_ok=True)

SOURCES = [
    ("V23", RES / "v23" / "v23_results_with_oos.pkl"),
    ("V27", RES / "v27" / "v27_swing_results.pkl"),
    ("V29", RES / "v29" / "v29_regime_results.pkl"),
    ("V30", RES / "v30" / "v30_creative_results.pkl"),
]

V29_PASS = {
    "SUI Lateral_BB_Fade 1h", "ETH Lateral_BB_Fade 4h", "SOL Lateral_BB_Fade 4h",
    "TON Trend_Grade_MTF 4h", "AVAX Lateral_BB_Fade 4h", "LINK Lateral_BB_Fade 4h",
    "INJ Lateral_BB_Fade 4h", "BTC Lateral_BB_Fade 4h", "SUI Regime_Switch 4h",
    "LINK Trend_Grade_MTF 4h", "INJ Trend_Grade_MTF 4h", "BTC Regime_Switch 4h",
    "ETH Regime_Switch 4h", "AVAX Trend_Grade_MTF 4h", "SOL Trend_Grade_MTF 4h",
    "INJ Regime_Switch 4h",
}

V30_PASS = {
    "ETH CCI_Extreme_Rev 4h", "AVAX VWAP_Zfade 1h", "SUI CCI_Extreme_Rev 4h",
    "SOL SuperTrend_Flip 4h", "DOGE TTM_Squeeze_Pop 4h", "SOL CCI_Extreme_Rev 4h",
    "TON VWAP_Zfade 1h", "TON CCI_Extreme_Rev 4h", "AVAX TTM_Squeeze_Pop 4h",
    "SUI SuperTrend_Flip 4h", "SOL TTM_Squeeze_Pop 4h", "TON SuperTrend_Flip 4h",
    "DOGE VWAP_Zfade 4h", "AVAX CCI_Extreme_Rev 4h", "INJ VWAP_Zfade 4h",
    "INJ SuperTrend_Flip 4h", "ETH VWAP_Zfade 4h", "SOL Connors_RSI 4h",
    "LINK CCI_Extreme_Rev 1h", "SUI TTM_Squeeze_Pop 4h", "TON TTM_Squeeze_Pop 4h",
    "ETH SuperTrend_Flip 4h", "BTC SuperTrend_Flip 4h", "ETH TTM_Squeeze_Pop 4h",
    "INJ CCI_Extreme_Rev 4h", "LINK VWAP_Zfade 1h", "LINK SuperTrend_Flip 4h",
    "BTC CCI_Extreme_Rev 1h",
}

V28_KEYS = {
    "V23::SUIUSDT", "V23::SOLUSDT", "V23::DOGEUSDT",
    "V27::ETHUSDT_HTF_DONCHIAN", "V27::SOLUSDT_HTF_DONCHIAN",
    "V27::BTCUSDT_HTF_DONCHIAN", "V27::DOGEUSDT_HTF_DONCHIAN",
}


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

        keep = False
        if tag == "V30" and label in V30_PASS: keep = True
        if tag == "V29" and label in V29_PASS: keep = True
        if full_key in V28_KEYS: keep = True
        if not keep: continue

        yrs = {y: year_cagr(eq, y) for y in (2023, 2024, 2025)}
        score = sum(v for v in yrs.values() if v is not None)
        strats[full_key] = dict(sym=sym, family=fam, tf=tf, eq=eq, yrs=yrs,
                                score=score, tag=tag, label=label)

print(f"pool = {len(strats)} strategies")


def year_cagr_blend(members, y):
    vals = []
    for m in members:
        v = m["yrs"].get(y)
        vals.append(v if v is not None else 0.0)
    return sum(vals) / len(vals)


pool = list(strats.keys())
best_100 = []
best_worst = []

for r in (3, 4, 5):
    for combo in itertools.combinations(pool, r):
        entries = [strats[k] for k in combo]
        syms = set(e["sym"] for e in entries)
        if len(syms) != len(entries): continue   # no same-coin stacking
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
    df.to_csv(OUT / "v30_portfolio_100pct.csv", index=False)
    print("\nTOP 20 (sorted by WORST-year CAGR):")
    pd.set_option('display.max_colwidth', 220)
    pd.set_option('display.width', 260)
    print(df.head(20).to_string(index=False))

df2 = pd.DataFrame(best_worst).sort_values("worst_CAGR%", ascending=False).head(30)
df2.to_csv(OUT / "v30_portfolio_top30.csv", index=False)
print(f"\nTop-30 by worst-year CAGR:")
print(df2.to_string(index=False))
