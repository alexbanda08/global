"""Summarise queue_aware_per_sleeve.csv into clean comparison tables."""
import pandas as pd

df = pd.read_csv("strategy_lab/markov_filter/_results/queue_aware_per_sleeve.csv")

PRACTICAL = {
    "momo_v1_btc_15m_HOD":     1000,
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

# ---- (a) Per-sleeve best HYBRID placement at practical notional ----
rows = []
for s, N in PRACTICAL.items():
    sub = df[(df["sleeve"] == s) & (df["notional"] == N)]
    if sub.empty: continue
    best = sub.loc[sub["hyb_sum"].idxmax()]
    rows.append({
        "sleeve":               s,
        "notional":             N,
        "best_placement":       best["placement"],
        "queue_ahead_mean":     best["mean_queue_ahead"],
        "target_shares_mean":   best["mean_target_sh"],
        "limit_px_mean":        best["mean_limit_px"],
        "taker_vwap_mean":      best["mean_taker_vwap"],
        "maker_q_fill_frac":    best["maker_q_fill_frac"],
        "maker_q_zero_pct":     best["maker_q_zero_pct"],
        "hyb_maker_part_pct":   best["hyb_maker_part_pct"],
        "taker_sum":            best["taker_sum"],
        "maker_q_sum":          best["maker_q_sum"],
        "hyb_sum":              best["hyb_sum"],
        "maker_q_lift_$":       best["maker_q_lift_$"],
        "hyb_lift_$":           best["hyb_lift_$"],
    })
best_hyb = (pd.DataFrame(rows)
            .sort_values("hyb_sum", ascending=False)
            .reset_index(drop=True))
best_hyb.to_csv("strategy_lab/markov_filter/_results/queue_aware_best_per_sleeve.csv",
                index=False)
print("\n=== Best HYBRID placement per sleeve (at practical notional) ===")
print(best_hyb.to_string(index=False))

# ---- (b) Aggregate across all 11 sleeves at each notional ----
agg = (df.groupby(["notional","placement"])
        .agg(taker_sum   = ("taker_sum",          "sum"),
             maker_q_sum = ("maker_q_sum",        "sum"),
             hyb_sum     = ("hyb_sum",            "sum"),
             mean_fill   = ("maker_q_fill_frac",  "mean"),
             mean_zero   = ("maker_q_zero_pct",   "mean"))
        .reset_index())
agg["maker_q_lift"]   = (agg["maker_q_sum"] - agg["taker_sum"]).round(0)
agg["hyb_lift"]       = (agg["hyb_sum"] - agg["taker_sum"]).round(0)
agg["mean_fill"]      = (100*agg["mean_fill"]).round(1)
agg["mean_zero"]      = agg["mean_zero"].round(1)
for c in ["taker_sum","maker_q_sum","hyb_sum"]:
    agg[c] = agg[c].round(0)
print("\n=== Aggregate across all 11 sleeves (queue-aware) ===")
print(agg.to_string(index=False))

# ---- (c) Compare three models at practical-notional aggregate ----
practical_rows = []
for s, N in PRACTICAL.items():
    sub = df[(df["sleeve"] == s) & (df["notional"] == N)]
    if sub.empty: continue
    best_h = sub.loc[sub["hyb_sum"].idxmax()]
    best_t = sub.iloc[0]   # taker is constant across placements
    practical_rows.append({
        "sleeve":         s,
        "notional":       N,
        "taker":          best_t["taker_sum"],
        "maker_q":        sub["maker_q_sum"].max(),     # best maker_q across placements
        "hybrid":         best_h["hyb_sum"],
    })
prac = pd.DataFrame(practical_rows).sort_values("hybrid", ascending=False)
tot = prac[["taker","maker_q","hybrid"]].sum()
prac.loc[len(prac)] = {"sleeve":"TOTAL","notional":"-",
                        "taker": tot["taker"],
                        "maker_q": tot["maker_q"],
                        "hybrid": tot["hybrid"]}
print("\n=== Per-sleeve totals @ practical notional (taker | best_pure_maker_q | best_hybrid) ===")
print(prac.to_string(index=False))
