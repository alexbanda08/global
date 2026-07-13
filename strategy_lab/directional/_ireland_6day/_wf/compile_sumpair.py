import json
import pandas as pd
import numpy as np

BASE = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day"
SPLIT = pd.Timestamp("2026-07-08 12:15:00", tz="UTC")

def boot_ci(x, n=10000, seed=0):
    x = np.asarray(x, dtype=float)
    if len(x) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n, len(x)))
    means = x[idx].mean(axis=1)
    return (np.percentile(means, 2.5), np.percentile(means, 97.5))

rows = []
with open(f"{BASE}/_wf/sumpair_all.tsv", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        at, sleeve, data = parts[0], parts[1], parts[2]
        try:
            d = json.loads(data)
        except Exception:
            continue
        d["at"] = at
        d["sleeve_id"] = sleeve
        rows.append(d)

df = pd.DataFrame(rows)
df["at"] = pd.to_datetime(df["at"], utc=True)
settle = df[df["phase"] == "settle"].copy()
for c in ["net_pnl_level0", "net_pnl_walk"]:
    settle[c] = pd.to_numeric(settle[c], errors="coerce")

# dedup last row per condition_id per sleeve
settle = settle.sort_values("at").groupby(["sleeve_id","condition_id"], as_index=False).tail(1)

out = ["# Sumpair compile\n"]
for sleeve, g in settle.groupby("sleeve_id"):
    g = g.sort_values("at")
    out.append(f"\n## {sleeve} (n={len(g)})\n")
    for period_name, mask in [
        ("Jul2-Jul8 12:15", (g["at"] < SPLIT)),
        ("Jul8 12:15-now", (g["at"] >= SPLIT)),
    ]:
        gp = g[mask]
        n = len(gp)
        if n == 0:
            out.append(f"**{period_name}**: n=0\n")
            continue
        for col in ["net_pnl_level0", "net_pnl_walk"]:
            vals = gp[col].dropna().values
            mean = vals.mean() if len(vals) else float('nan')
            lo, hi = boot_ci(vals)
            out.append(f"**{period_name}** {col}: mean={mean:.4f} CI95[{lo:.4f},{hi:.4f}] n={len(vals)}\n")

with open(f"{BASE}/sumpair_compile_refresh.txt", "w", encoding="utf-8") as f:
    f.writelines(out)
print("SUMPAIR DONE")
print("".join(out))
