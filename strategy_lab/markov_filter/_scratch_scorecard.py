"""Build clean per-sleeve scorecard from post_f7_all_sleeves_overlay output."""
import pandas as pd
df = pd.read_csv("strategy_lab/markov_filter/_results/post_f7_all_sleeves_overlay/per_sleeve_all_gates.csv")

# Normalize sleeve names
df["sleeve"] = df["sleeve"].str.replace("poly_updown_", "", regex=False)

# For each sleeve, pick the BEST gate (max sum$, n>=10) and report alongside baseline
print("=== Per-sleeve scorecard — production 23.5h window ===")
print()
rows = []
for sleeve in sorted(df["sleeve"].unique()):
    sub = df[df["sleeve"] == sleeve]
    base = sub[sub["filter"] == "BASELINE_ALL"]
    if base.empty:
        continue
    base_row = base.iloc[0]
    if base_row["n"] < 10:
        continue
    # Best gate (n>=10)
    candidates = sub[(sub["n"] >= 10) & (sub["filter"] != "BASELINE_ALL")]
    if candidates.empty:
        best = base_row
    else:
        best = candidates.loc[candidates["sum"].idxmax()]
    rows.append({
        "sleeve": sleeve,
        "n_base": int(base_row["n"]),
        "wr_base": base_row["wr"],
        "avg_base": base_row["avg"],
        "sum_base": base_row["sum"],
        "best_filter": best["filter"],
        "n_best": int(best["n"]),
        "wr_best": best["wr"],
        "avg_best": best["avg"],
        "sum_best": best["sum"],
        "lift_avg": round(best["avg"] - base_row["avg"], 3),
        "lift_sum": round(best["sum"] - base_row["sum"], 2),
    })
sc = pd.DataFrame(rows)
sc = sc.sort_values("sum_best", ascending=False)
print(sc.to_string(index=False))
sc.to_csv("strategy_lab/markov_filter/_results/post_f7_all_sleeves_overlay/scorecard_production.csv", index=False)
print()
print(f"=== Top 10 by sum_best ===")
print(sc.head(10)[["sleeve","best_filter","n_best","wr_best","avg_best","sum_best","lift_sum"]].to_string(index=False))
print()
print(f"=== Bottom 10 (worst losers) ===")
print(sc.tail(10)[["sleeve","best_filter","n_best","wr_best","avg_best","sum_best"]].to_string(index=False))
print()
print(f"=== TOTAL aggregate impact ===")
print(f'  Baseline sum: ${sc["sum_base"].sum():,.2f}')
print(f'  Best-gate sum: ${sc["sum_best"].sum():,.2f}')
print(f'  Lift: ${sc["sum_best"].sum() - sc["sum_base"].sum():,.2f}')
