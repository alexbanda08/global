"""Analyze: what does post-slippage PnL look like at each notional?

For each sleeve, compute:
  - sum_pnl_25 / sum_pnl_250 / sum_pnl_2500 (raw walked PnL after fees)
  - effective_scale_250  = sum_pnl_250 / sum_pnl_25  (should be ~10 if linear)
  - effective_scale_2500 = sum_pnl_2500 / sum_pnl_25 (should be ~100 if linear)
  - degradation pct at 250 / 2500

This tells us the TRUE post-slippage scaling factor.
"""
import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
import pandas as pd
import numpy as np

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"

df = pd.read_csv(f"{RES}/sleeve_notional_fill_simulation.csv")
print(f"loaded {len(df):,} fire-level rows")

# Aggregate per sleeve
LB_DAYS = 3.96
SCALE_28D = 28.0 / LB_DAYS

g = df.groupby("sleeve_id").agg(
    asset=("asset", "first"),
    n=("won", "size"),
    wr=("won", "mean"),
    sum_25=("pnl_at_25", "sum"),
    sum_250=("pnl_at_250", "sum"),
    sum_2500=("pnl_at_2500", "sum"),
    avg_slip_250=("slippage_bps_at_250", "mean"),
    p90_slip_250=("slippage_bps_at_250", lambda s: s.quantile(0.9)),
    avg_slip_2500=("slippage_bps_at_2500", "mean"),
    p90_slip_2500=("slippage_bps_at_2500", lambda s: s.quantile(0.9)),
    avg_depth_pct_250=("depth_pct_at_250", "mean"),
    p90_depth_pct_250=("depth_pct_at_250", lambda s: s.quantile(0.9)),
    avg_depth_pct_2500=("depth_pct_at_2500", "mean"),
    under_pct_250=("under_at_250", lambda s: s.mean() * 100),
    under_pct_2500=("under_at_2500", lambda s: s.mean() * 100),
).reset_index()

g["sum_28d_25"] = g["sum_25"] * SCALE_28D
g["sum_28d_250"] = g["sum_250"] * SCALE_28D
g["sum_28d_2500"] = g["sum_2500"] * SCALE_28D
# Effective notional scaling
g["scale_250"] = g["sum_250"] / g["sum_25"].replace(0, np.nan)
g["scale_2500"] = g["sum_2500"] / g["sum_25"].replace(0, np.nan)
g["loss_vs_linear_250_pct"] = (10.0 - g["scale_250"]) / 10.0 * 100  # % below ideal 10x
g["loss_vs_linear_2500_pct"] = (100.0 - g["scale_2500"]) / 100.0 * 100

# Deployable at each notional? (positive sum + acceptable slippage)
g["deployable_25"] = g["sum_25"] > 0
g["deployable_250"] = (g["sum_250"] > 0) & (g["p90_slip_250"] < 100) & (g["under_pct_250"] < 5)
g["deployable_2500"] = (g["sum_2500"] > 0) & (g["p90_slip_2500"] < 200) & (g["under_pct_2500"] < 10)

# Sort by sum_28d_250
g = g.sort_values("sum_28d_250", ascending=False).reset_index(drop=True)

out = f"{RES}/sleeve_notional_scaling_truth.csv"
g.to_csv(out, index=False)
print(f"wrote {out}")
print()

# Display key columns
disp_cols = ["sleeve_id", "asset", "n", "wr",
              "sum_28d_25", "sum_28d_250", "sum_28d_2500",
              "scale_250", "scale_2500",
              "avg_slip_250", "p90_slip_250", "avg_depth_pct_250",
              "deployable_250", "deployable_2500"]
print(g[disp_cols].to_string(index=False))
print()
print("=== TOTAL DEPLOYABLE BY NOTIONAL ===")
print(f"Deployable @ $25:   {g.deployable_25.sum():2d} sleeves")
print(f"Deployable @ $250:  {g.deployable_250.sum():2d} sleeves")
print(f"Deployable @ $2500: {g.deployable_2500.sum():2d} sleeves")
print()
print(f"Positive sum @ $25:   ${g[g.sum_25>0].sum_28d_25.sum():>10,.0f}/28d")
print(f"Positive sum @ $250:  ${g[g.sum_250>0].sum_28d_250.sum():>10,.0f}/28d")
print(f"Positive sum @ $2500: ${g[g.sum_2500>0].sum_28d_2500.sum():>10,.0f}/28d")
