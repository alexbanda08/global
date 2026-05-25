"""Extract F7+Markov specific rows per sleeve from production scorecard."""
import pandas as pd

df = pd.read_csv("strategy_lab/markov_filter/_results/post_f7_all_sleeves_overlay/per_sleeve_all_gates.csv")
df["sleeve"] = df["sleeve"].str.replace("poly_updown_", "", regex=False)

# Filter to F7+MARKOV rows
rows = []
for sleeve in sorted(df["sleeve"].unique()):
    sub = df[df["sleeve"] == sleeve]
    base = sub[sub["filter"] == "BASELINE_ALL"].iloc[0] if (sub["filter"] == "BASELINE_ALL").any() else None
    if base is None or base["n"] < 10:
        continue
    f7_alone = sub[sub["filter"] == "F7_only"].iloc[0] if (sub["filter"] == "F7_only").any() else None
    for vname in ["w20_1m_voladaptive","w20_5m_voladaptive","w20_1m_fixed","w20_5m_fixed"]:
        mk = sub[sub["filter"] == f"MARKOV:{vname}"]
        fm = sub[sub["filter"] == f"F7+MARKOV:{vname}"]
        if mk.empty or fm.empty:
            continue
        rows.append({
            "sleeve": sleeve,
            "markov_variant": vname,
            "n_base": int(base["n"]),
            "wr_base": base["wr"],
            "avg_base": base["avg"],
            "n_f7": int(f7_alone["n"]) if f7_alone is not None else 0,
            "wr_f7": f7_alone["wr"] if f7_alone is not None else 0,
            "avg_f7": f7_alone["avg"] if f7_alone is not None else 0,
            "n_markov": int(mk.iloc[0]["n"]),
            "wr_markov": mk.iloc[0]["wr"],
            "avg_markov": mk.iloc[0]["avg"],
            "n_f7_markov": int(fm.iloc[0]["n"]),
            "wr_f7_markov": fm.iloc[0]["wr"],
            "avg_f7_markov": fm.iloc[0]["avg"],
            "sum_f7_markov": fm.iloc[0]["sum"],
        })
out = pd.DataFrame(rows)
out.to_csv("strategy_lab/markov_filter/_results/f7_markov_per_sleeve.csv", index=False)

# Pick best F7+Markov variant per sleeve (sum$, n>=10)
print("=== Best F7+MARKOV combo per sleeve (n>=10) ===")
best = []
for sleeve, g in out.groupby("sleeve"):
    g = g[g["n_f7_markov"] >= 10]
    if g.empty: continue
    b = g.loc[g["sum_f7_markov"].idxmax()]
    best.append({
        "sleeve": sleeve,
        "n_base": b["n_base"], "wr_base": b["wr_base"], "avg_base": b["avg_base"],
        "n_f7": b["n_f7"], "wr_f7": b["wr_f7"], "avg_f7": b["avg_f7"],
        "markov_variant": b["markov_variant"],
        "n_f7_markov": b["n_f7_markov"], "wr_f7_markov": b["wr_f7_markov"],
        "avg_f7_markov": b["avg_f7_markov"], "sum_f7_markov": b["sum_f7_markov"],
        "lift_f7_to_f7m": round(b["avg_f7_markov"] - b["avg_f7"], 3),
    })
bd = pd.DataFrame(best).sort_values("sum_f7_markov", ascending=False)
print(bd.to_string(index=False))
bd.to_csv("strategy_lab/markov_filter/_results/f7_markov_best_per_sleeve.csv", index=False)
