"""V28 per-year audit: for each V23/V25/V26/V27 winner, compute CAGR in 2023,
2024, 2025 separately. Flag any strategy that clears 100% in all three."""
from __future__ import annotations
import pickle
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
    ("V26_OB_FIXED", RES / "v26" / "v26_ob_fixed_results.pkl"),
    ("V27", RES / "v27" / "v27_swing_results.pkl"),
]

def eq_from_entry(d):
    idx = pd.to_datetime(d.get("eq_index"), utc=True)
    vals = np.asarray(d.get("eq_values"), dtype=float)
    return pd.Series(vals, index=idx).dropna()

def cagr_slice(eq, start, end):
    s = eq[(eq.index >= start) & (eq.index < end)]
    if len(s) < 20: return None, 0
    ret = s.iloc[-1] / s.iloc[0] - 1
    yrs = (s.index[-1] - s.index[0]).total_seconds() / (365.25 * 86400)
    if yrs < 1e-6: return None, 0
    cagr = (1 + ret) ** (1/yrs) - 1
    return cagr, len(s)

def year_range(y):
    return pd.Timestamp(f"{y}-01-01", tz="UTC"), pd.Timestamp(f"{y+1}-01-01", tz="UTC")

rows = []
for tag, path in SOURCES:
    if not path.exists(): continue
    d = pickle.load(open(path, "rb"))
    for key, v in d.items():
        if not (v.get("eq_values") and v.get("eq_index")): continue
        try:
            eq = eq_from_entry(v)
        except Exception: continue
        if len(eq) < 100: continue

        # Only keep strategies with ≥30 trades full, Sharpe > 0 (filter junk)
        m = v.get("metrics", {})
        n = int(m.get("n", 0))
        sh = float(m.get("sharpe", 0))
        full_cagr = float(m.get("cagr_net", 0))
        if n < 20 or sh <= 0: continue

        row = {
            "round": tag, "key": key, "sym": v.get("sym",""),
            "family": v.get("family",""), "tf": v.get("tf",""),
            "full_n": n, "full_cagr": round(full_cagr*100,1), "full_sh": round(sh,2),
        }
        for y in (2022, 2023, 2024, 2025):
            s, e = year_range(y)
            c, ns = cagr_slice(eq, s, e)
            row[f"y{y}"] = None if c is None else round(c*100, 1)
        rows.append(row)

df = pd.DataFrame(rows)
df = df.sort_values(by=["y2025", "y2024", "y2023"], ascending=False, na_position="last")
df.to_csv(OUT / "peryear_audit.csv", index=False)

# Find strategies that cleared 100% in ALL three target years
def clears_100(r):
    for y in (2023, 2024, 2025):
        v = r.get(f"y{y}")
        if v is None or v < 100.0: return False
    return True

winners = df[df.apply(clears_100, axis=1)]
print("="*88)
print("V28 per-year audit — strategies that cleared 100% CAGR in 2023, 2024, AND 2025:")
print("="*88)
if len(winners):
    print(winners.to_string(index=False))
else:
    print("(none — need combinations or new hunt)")

print()
print("TOP 30 by y2025 CAGR:")
print(df.head(30).to_string(index=False))

