"""Full table: baseline / F7 only / Markov only / F7+Markov side-by-side per sleeve.
For each sleeve, picks its BEST Markov variant (by F7+Markov sum$) and shows all 4 buckets."""
import pandas as pd

df = pd.read_csv("strategy_lab/markov_filter/_results/post_f7_all_sleeves_overlay/per_sleeve_all_gates.csv")
df["sleeve"] = df["sleeve"].str.replace("poly_updown_", "", regex=False)

MARKOV = ["w20_1m_voladaptive","w20_5m_voladaptive","w20_1m_fixed","w20_5m_fixed"]

rows = []
for sleeve in sorted(df["sleeve"].unique()):
    sub = df[df["sleeve"] == sleeve]
    base = sub[sub["filter"] == "BASELINE_ALL"]
    if base.empty or base.iloc[0]["n"] < 10:
        continue
    base_row = base.iloc[0]
    f7 = sub[sub["filter"] == "F7_only"]
    f7_row = f7.iloc[0] if not f7.empty else None

    # Pick best Markov variant by F7+MARKOV sum (n>=10) — fallback to MARKOV alone if F7+M small
    best_variant = None
    best_sum = -1e9
    for v in MARKOV:
        fm = sub[sub["filter"] == f"F7+MARKOV:{v}"]
        if fm.empty: continue
        if fm.iloc[0]["n"] < 5: continue
        if fm.iloc[0]["sum"] > best_sum:
            best_sum = fm.iloc[0]["sum"]
            best_variant = v
    if best_variant is None:
        # try MARKOV alone variants
        for v in MARKOV:
            mk = sub[sub["filter"] == f"MARKOV:{v}"]
            if mk.empty or mk.iloc[0]["n"] < 5: continue
            if mk.iloc[0]["sum"] > best_sum:
                best_sum = mk.iloc[0]["sum"]
                best_variant = v
    if best_variant is None:
        continue

    mk = sub[sub["filter"] == f"MARKOV:{best_variant}"].iloc[0]
    fm_row = sub[sub["filter"] == f"F7+MARKOV:{best_variant}"]
    fm = fm_row.iloc[0] if not fm_row.empty else None

    rows.append({
        "sleeve": sleeve,
        "markov_variant": best_variant,
        # Baseline
        "n_base":  int(base_row["n"]),
        "wr_base": base_row["wr"],
        "avg_base": base_row["avg"],
        "sum_base": base_row["sum"],
        # F7 only
        "n_f7":  int(f7_row["n"]) if f7_row is not None else 0,
        "wr_f7": f7_row["wr"] if f7_row is not None else 0,
        "avg_f7": f7_row["avg"] if f7_row is not None else 0,
        "sum_f7": f7_row["sum"] if f7_row is not None else 0,
        # Markov only
        "n_mk":  int(mk["n"]),
        "wr_mk": mk["wr"],
        "avg_mk": mk["avg"],
        "sum_mk": mk["sum"],
        # F7 + Markov
        "n_fm":  int(fm["n"]) if fm is not None else 0,
        "wr_fm": fm["wr"] if fm is not None else 0,
        "avg_fm": fm["avg"] if fm is not None else 0,
        "sum_fm": fm["sum"] if fm is not None else 0,
    })

out = pd.DataFrame(rows).sort_values("sum_fm", ascending=False)
out.to_csv("strategy_lab/markov_filter/_results/per_sleeve_full_4col_table.csv", index=False)
print(out.to_string(index=False))
print()
print(f"Total sleeves: {len(out)}")
print(f"Aggregate sum: base ${out['sum_base'].sum():,.2f}  F7 ${out['sum_f7'].sum():,.2f}  M ${out['sum_mk'].sum():,.2f}  F7+M ${out['sum_fm'].sum():,.2f}")
