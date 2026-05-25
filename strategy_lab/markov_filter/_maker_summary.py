"""Summarise maker_per_sleeve.csv into clean comparison tables."""
import pandas as pd
import numpy as np

df = pd.read_csv("strategy_lab/markov_filter/_results/maker_per_sleeve.csv")

# Practical notional per sleeve (from capacity sweep)
PRACTICAL = {
    "momo_v1_btc_15m_HOD":     1000,   # capped at $1k for maker since L25 doesn't help passive fills > level 0
    "momo_v2_btc_15m_HOD":     1000,
    "momo_v2_eth_15m_HOD":     1000,
    "sniper_btc_15m_HOD":      1000,
    "momo_v2_btc_5m_HOD+MTF2": 1000,
    "sniper_btc_5m_HOD":       1000,
    "sniper_eth_15m_HOD+M5va": 1000,
    "sniper_sol_5m_HOD":        500,
    "sniper_eth_5m_HOD":        500,
    "momo_v2_sol_5m_HOD":       500,
    "momo_v2_sol_15m_HOD":      100,
}

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 240)

# ---- (a) Best maker placement per sleeve at practical notional ----
rows = []
for s, N in PRACTICAL.items():
    sub = df[(df["sleeve"] == s) & (df["notional"] == N)]
    if sub.empty: continue
    best = sub.loc[sub["sum_pnl_maker"].idxmax()]
    rows.append({
        "sleeve":           s,
        "notional":         N,
        "best_placement":   best["placement"],
        "limit_px_mean":    best["mean_limit_px"],
        "taker_vwap_mean":  best["mean_taker_vwap"],
        "savings_per_share":round(best["mean_taker_vwap"] - best["mean_limit_px"], 3),
        "fill_rate_pct":    best["fill_rate_pct"],
        "mean_fill_dt_s":   best["mean_fill_dt_s"],
        "wr_pct":           best["wr_pct"],
        "wr_when_filled":   best["wr_when_filled"],
        "adverse_sel_pp":   round(best["wr_pct"] - best["wr_when_filled"], 2),
        "sum_pnl_maker":    best["sum_pnl_maker"],
        "sum_pnl_taker":    best["sum_pnl_taker"],
        "maker_lift_$":     best["maker_lift_$"],
    })
best_maker = (pd.DataFrame(rows)
              .sort_values("sum_pnl_maker", ascending=False)
              .reset_index(drop=True))
best_maker.to_csv("strategy_lab/markov_filter/_results/maker_best_per_sleeve.csv",
                   index=False)
print("\n=== Best maker placement per sleeve (at practical notional) ===")
print(best_maker.to_string(index=False))

# ---- (b) Per-placement scoreboard at $1000 across all sleeves ----
sub = df[df["notional"] == 1000].copy()
piv_sum = sub.pivot(index="sleeve", columns="placement", values="sum_pnl_maker")
piv_fr  = sub.pivot(index="sleeve", columns="placement", values="fill_rate_pct")
piv_wf  = sub.pivot(index="sleeve", columns="placement", values="wr_when_filled")
print("\n=== Maker SUM PnL ($) by placement (notional = $1000) ===")
print(piv_sum.round(0).to_string())
print("\n=== Fill rate (%) by placement (notional = $1000) ===")
print(piv_fr.round(1).to_string())
print("\n=== WR when filled (%) by placement (notional = $1000) ===")
print(piv_wf.round(2).to_string())

# ---- (c) Aggregate maker lift across all 11 sleeves at each notional ----
agg = (df.groupby(["notional","placement"])
         .agg(sum_maker = ("sum_pnl_maker","sum"),
              sum_taker = ("sum_pnl_taker","sum"),
              fires     = ("n_fires","sum"))
         .reset_index())
agg["lift_$"] = (agg["sum_maker"] - agg["sum_taker"]).round(0)
print("\n=== Aggregate maker vs taker across all 11 sleeves ===")
print(agg.to_string(index=False))

# ---- (d) Adverse-selection summary ----
ad = (df[df["fill_rate_pct"] >= 50]
      .groupby("placement")
      .agg(mean_wr        = ("wr_pct",        "mean"),
           mean_wr_filled = ("wr_when_filled","mean"),
           mean_fill_rate = ("fill_rate_pct", "mean"))
      .reset_index())
ad["adverse_sel_pp"] = (ad["mean_wr"] - ad["mean_wr_filled"]).round(2)
print("\n=== Adverse-selection pattern (averaged across all (sleeve, notional)) ===")
print(ad.to_string(index=False))
