"""Final scorecard combining:
  - VPS3 production 23.5h fires (all sleeves)
  - 21-day backtest (momo only, real fees + L25 walk)

Per sleeve: baseline / F7 only / Markov only / F7+Markov, ranked by WR + PnL.
"""
import pandas as pd

# Production data
prod = pd.read_csv("strategy_lab/markov_filter/_results/post_f7_all_sleeves_overlay/per_sleeve_all_gates.csv")
prod["sleeve"] = prod["sleeve"].str.replace("poly_updown_", "", regex=False)
prod["source"] = "production_23.5h"

# Backtest data (momo only, 21 days)
bt = pd.read_csv("strategy_lab/markov_filter/_results/backtest_28d_with_gates/per_sleeve_full.csv")
bt["source"] = "backtest_21d"

# Standardize columns
prod = prod[["source","sleeve","filter","n","wr","avg","sum"]]
bt   = bt[["source","sleeve","filter","n","wr","avg","sum"]]

# Combined long-form
combined = pd.concat([prod, bt], ignore_index=True)
combined.to_csv("strategy_lab/markov_filter/_results/final_scorecard_long.csv", index=False)

# Per-sleeve scorecard: pivot the key filters
def best_filter(g):
    """Best gate for this sleeve+source by sum$, n>=10."""
    base = g[g["filter"].isin(["NO_FILTER", "BASELINE_ALL"])]
    if base.empty: return None
    base_row = base.iloc[0]
    cands = g[(g["n"] >= 10) & (~g["filter"].isin(["NO_FILTER","BASELINE_ALL"]))]
    if cands.empty: return None
    best = cands.loc[cands["sum"].idxmax()]
    return pd.Series({
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
    })

# Per-sleeve summaries grouped by source
print("\n" + "="*100)
print("FINAL SCORECARD — PRODUCTION 23.5h (all sleeves)")
print("="*100)
prod_sc = (prod.groupby("sleeve")
              .apply(best_filter, include_groups=False)
              .dropna()
              .sort_values("sum_best", ascending=False))
print(prod_sc.to_string())
prod_sc.to_csv("strategy_lab/markov_filter/_results/final_scorecard_production.csv")

print("\n" + "="*100)
print("FINAL SCORECARD — BACKTEST 21d (momo only)")
print("="*100)
bt_sc = (bt.groupby("sleeve")
            .apply(best_filter, include_groups=False)
            .dropna()
            .sort_values("sum_best", ascending=False))
print(bt_sc.to_string())
bt_sc.to_csv("strategy_lab/markov_filter/_results/final_scorecard_backtest.csv")

# Aggregate impact comparison
print("\n" + "="*100)
print("AGGREGATE IMPACT")
print("="*100)
print(f"PRODUCTION 23.5h: baseline ${prod_sc['sum_base'].sum():,.2f} → best-gate ${prod_sc['sum_best'].sum():,.2f}   "
      f"(lift ${prod_sc['sum_best'].sum()-prod_sc['sum_base'].sum():,.2f})")
print(f"BACKTEST 21d (momo only): baseline ${bt_sc['sum_base'].sum():,.2f} → best-gate ${bt_sc['sum_best'].sum():,.2f}   "
      f"(lift ${bt_sc['sum_best'].sum()-bt_sc['sum_base'].sum():,.2f})")
