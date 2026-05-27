"""V7 rank + filter — surface top sleeves with stability across train/val/lockbox."""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
RES = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v7/_results")

df = pd.read_csv(os.path.join(RES, "v7_validated.csv"))
print(f"Loaded {len(df)} strict survivors")

# Robustness filters: stability across all 3 splits
robust = df[
    (df["dpt_train_25"] > 0) &
    (df["dpt_val_25"] > 0) &
    (df["wr_train"] >= 0.55) &
    (df["wr_val"] >= 0.55) &
    (df["n_lockbox"] >= 25) &
    (df["dd_lockbox_25"] >= -300) &
    (df["ls_lockbox"] <= 6)
].copy()
print(f"After robustness filters: {len(robust)}")

# Has V7 NEW gate (proof of concept that V7 atoms add value)
v7_new_gates = [
    "g_btc_mp_skew_with", "g_btc_trend_slope_with", "g_btc_hurst_trending",
    "g_btc_eth_trend_agree",
    "g_parent15m_trending", "g_parent15m_label_with", "g_parent15m_trend_with",
    "g_parent15m_trend_strong_with", "g_parent15m_ranging",
    "g_hurst_strong_trending_v7", "g_hurst_reverting_v7",
    "g_hurst_trend_with", "g_hurst_mp_trend_with",
    "g_pw_f7_cvd_unanimity", "g_pw_break_with",
    "g_xa_3source_trend_with",
]

def has_v7_gate(stack):
    return any(g in stack for g in v7_new_gates)

robust["has_v7_gate"] = robust["gate_stack"].apply(has_v7_gate)
print(f"  with at least 1 V7 NEW gate: {robust['has_v7_gate'].sum()}")

# Save robust pool
robust.to_csv(os.path.join(RES, "v7_robust.csv"), index=False)

# Rank by objective (dpt_lockbox * sqrt(n_lockbox))
robust_v7 = robust[robust["has_v7_gate"]].sort_values("objective", ascending=False)
print(f"\nTOP 20 V7-gate-containing sleeves by objective:")
print(robust_v7[["sleeve_id", "offset", "n_train", "wr_train", "dpt_train_25",
                "n_val", "wr_val", "dpt_val_25",
                "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25",
                "dd_lockbox_25", "ls_lockbox", "sharpe_lockbox",
                "boot_p_lockbox", "objective"]].head(20).to_string())

# Rank by sum_lockbox_25 (raw $ winners)
print(f"\nTOP 10 V7-gate sleeves by SUM_LOCKBOX_25:")
print(robust_v7.sort_values("sum_lockbox_25", ascending=False)[
    ["sleeve_id", "offset", "n_lockbox", "wr_lockbox", "dpt_lockbox_25",
     "sum_lockbox_25", "dd_lockbox_25", "ls_lockbox", "boot_p_lockbox"]
].head(10).to_string())

# Rank by sum_28d (train + val + lockbox sum)
robust_v7["sum_28d_const"] = robust_v7["sum_train_25"] + robust_v7["sum_val_25"] + robust_v7["sum_lockbox_25"]
print(f"\nTOP 10 V7-gate sleeves by SUM_28D:")
print(robust_v7.sort_values("sum_28d_const", ascending=False)[
    ["sleeve_id", "offset", "n_lockbox", "wr_lockbox", "dpt_lockbox_25",
     "sum_lockbox_25", "sum_28d_const", "dd_lockbox_25", "ls_lockbox"]
].head(10).to_string())

# Compare to V6 winner reference
# V6 c3: g_tr_above_cloud & g_ribbon_agrees & g_mp_skew_with & g_hurst_trending @off60
# n=165, WR 83.6%, dpt +$8.44, dd -$93
v6_c3_row = robust[robust["gate_stack"].str.contains("g_tr_above_cloud", na=False) &
                    robust["gate_stack"].str.contains("g_ribbon_agrees", na=False) &
                    robust["gate_stack"].str.contains("g_mp_skew_with", na=False) &
                    robust["gate_stack"].str.contains("g_hurst_trending", na=False) &
                    (robust["offset"] == 60)]
print(f"\nV6 c3 reference (cloud + ribbon + mp_skew + hurst, off60):")
if len(v6_c3_row) > 0:
    print(v6_c3_row[["depth", "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25", "dd_lockbox_25", "objective"]].to_string())
else:
    print("  NOT FOUND in robust pool")

# Save top 30 v7 candidates
top_30 = robust_v7.head(30)
top_30.to_csv(os.path.join(RES, "v7_top30_candidates.csv"), index=False)
print(f"\nSaved top 30 -> v7_top30_candidates.csv")
