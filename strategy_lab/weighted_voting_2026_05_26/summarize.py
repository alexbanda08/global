"""Build per-sleeve summary tables for the report."""
import pandas as pd
import numpy as np
from pathlib import Path

OUT = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/weighted_voting_2026_05_26")

res = pd.read_csv(OUT/"weighted_models_results.csv")
boot = pd.read_csv(OUT/"bootstrap_results.csv")
hyb = pd.read_csv(OUT/"hybrid_v8_lockbox.csv")
w = pd.read_csv(OUT/"feature_weights.csv")
calib = pd.read_csv(OUT/"calibration_table.csv")

# 1. PER-SLEEVE lockbox comparison table
lock = res[res["split"]=="lockbox"].copy()
# pivot to wide format
piv = lock.pivot_table(index="sleeve", columns="variant", values="sum_pnl", aggfunc="first").round(0)
piv.to_csv(OUT/"lockbox_sum_pnl_pivot.csv")
print("Sum_pnl on lockbox:")
print(piv.to_string())
print()

piv_dpt = lock.pivot_table(index="sleeve", columns="variant", values="dpt", aggfunc="first").round(3)
piv_dpt.to_csv(OUT/"lockbox_dpt_pivot.csv")
print("DPT on lockbox:")
print(piv_dpt.to_string())
print()

piv_wr = lock.pivot_table(index="sleeve", columns="variant", values="wr", aggfunc="first").round(3)
piv_wr.to_csv(OUT/"lockbox_wr_pivot.csv")
print("WR on lockbox:")
print(piv_wr.to_string())
print()

piv_n = lock.pivot_table(index="sleeve", columns="variant", values="n", aggfunc="first").astype("Int64")
piv_n.to_csv(OUT/"lockbox_n_pivot.csv")
print("N on lockbox:")
print(piv_n.to_string())

# 2. Best model per sleeve (by sum_pnl)
ws_only = lock[~lock["variant"].isin(["hybrid_v1_AND"]) & ~lock["variant"].str.contains("_topN")]
best = ws_only.loc[ws_only.groupby("sleeve")["sum_pnl"].idxmax()][["sleeve","variant","n","wr","dpt","sum_pnl","threshold","boot_p"]]
best.to_csv(OUT/"best_per_sleeve.csv", index=False)
print()
print("Best WS model per sleeve:")
print(best.to_string(index=False))

# 3. Feature weight summary — top 10 across all sleeves (by mean abs weight, logistic_l2)
w_lr = w[w["model"]=="logistic_l2"].copy()
w_lr["abs"] = w_lr["weight"].abs()
top_global = w_lr.groupby("feature")["abs"].agg(["mean","max","count"]).sort_values("mean", ascending=False).head(20)
top_global.to_csv(OUT/"top_features_global.csv")
print()
print("Top 20 features (mean |weight| across sleeves, logistic_l2):")
print(top_global.to_string())

# 4. Calibration analysis - reliability deltas
print()
print("Reliability calibration analysis (logistic_l2 val):")
for sl in calib["sleeve"].unique():
    g = calib[(calib["sleeve"]==sl) & (calib["model"]=="logistic_l2")]
    deltas = (g["actual_mean"] - g["pred_mean"]).abs()
    print(f"  {sl}: mean |actual-pred| = {deltas.mean():.3f}, max = {deltas.max():.3f}")

# 5. summarize aggregate
agg_v1 = piv["hybrid_v1_AND"].sum()
print()
print("Aggregate sum_pnl on lockbox across all 7 sleeves:")
for c in piv.columns:
    print(f"  {c}: ${piv[c].sum():.0f}  ({(piv[c].sum() - agg_v1):+.0f} vs v1_AND)")

# 6. lockbox passes
print()
print("Bootstrap p<0.05 lockbox pass count per model:")
for m in boot["model"].unique():
    sub = boot[boot["model"]==m]
    passes = (sub["boot_p"]<0.05).sum()
    print(f"  {m}: {passes}/{len(sub)} pass")
