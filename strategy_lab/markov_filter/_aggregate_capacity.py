"""Quick re-aggregation from existing capacity_sweep_per_fire.csv (no L25 reload)."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

OUT_DIR = Path("strategy_lab/markov_filter/_results")
per_fire = pd.read_csv(OUT_DIR / "capacity_sweep_per_fire.csv")

agg = (per_fire.groupby(["sleeve","notional_target"], as_index=False)
    .agg(
        n_fires           = ("pnl",          "size"),
        sum_pnl_usd       = ("pnl",          "sum"),
        per_trade_pnl     = ("pnl",          "mean"),
        wr_pct            = ("won",          lambda x: 100*float(x.mean())),
        mean_fill_rate    = ("fill_rate",    "mean"),
        mean_slippage_bp  = ("slippage_bp",  "mean"),
        mean_levels       = ("levels",       "mean"),
        median_depth_usd  = ("l25_depth_usd","median"),
        share_underfilled = ("under",        lambda x: 100*float(x.mean())),
        sum_usd_filled    = ("usd_filled",   "sum"),
    )
)
agg["roi_on_filled_pct"] = (100 * agg["sum_pnl_usd"] / agg["sum_usd_filled"]).round(2)
for c in ["sum_pnl_usd","per_trade_pnl","wr_pct","mean_fill_rate",
          "mean_slippage_bp","mean_levels","median_depth_usd",
          "share_underfilled","sum_usd_filled"]:
    agg[c] = agg[c].round(2)
agg = agg.sort_values(["sleeve","notional_target"]).reset_index(drop=True)
agg.to_csv(OUT_DIR / "capacity_sweep_per_sleeve.csv", index=False)

def pick(df_sleeve):
    if df_sleeve.empty: return None
    max_sum = df_sleeve["sum_pnl_usd"].max()
    cand = df_sleeve[df_sleeve["sum_pnl_usd"] >= 0.80 * max_sum]
    if cand.empty: cand = df_sleeve
    cand = cand[cand["mean_fill_rate"] >= 0.95]
    if cand.empty: cand = df_sleeve
    return cand.sort_values("notional_target", ascending=False).iloc[0]
opt = (agg.groupby("sleeve", group_keys=False)
          .apply(pick, include_groups=False)
          .reset_index())
opt.to_csv(OUT_DIR / "capacity_sweep_optimal.csv", index=False)

# Capacity curve pivot
piv_sum   = agg.pivot(index="sleeve", columns="notional_target", values="sum_pnl_usd")
piv_pertr = agg.pivot(index="sleeve", columns="notional_target", values="per_trade_pnl")
piv_fill  = agg.pivot(index="sleeve", columns="notional_target", values="mean_fill_rate")
piv_slip  = agg.pivot(index="sleeve", columns="notional_target", values="mean_slippage_bp")

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

print("\nOPTIMAL NOTIONAL PER SLEEVE:")
print(opt.to_string(index=False))
print("\nSUM PnL ($) by notional:")
print(piv_sum.round(0).to_string())
print("\nPER-TRADE PnL ($) by notional:")
print(piv_pertr.round(2).to_string())
print("\nMEAN FILL RATE by notional:")
print(piv_fill.round(3).to_string())
print("\nMEAN SLIPPAGE (bp) by notional:")
print(piv_slip.round(0).to_string())
