"""Dedup identical sleeves (different stacks but same hit set).

Group by (n_lockbox, wr_lockbox, sum_lockbox_25, dd_lockbox_25) -> pick shortest stack.
Then within each unique hit-set, surface the cleanest minimal sleeve.
"""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
RES = os.path.join(ROOT, "strategy_lab/sniper_search_2026_05_27/eth_5m_v7/_results")

df = pd.read_csv(os.path.join(RES, "v7_robust.csv"))
print(f"Loaded {len(df)} robust survivors")

# Group by metric fingerprint
df["fingerprint"] = df.apply(
    lambda r: f"off{r['offset']}|n{r['n_lockbox']}|wr{round(r['wr_lockbox'],4)}|s{round(r['sum_lockbox_25'],2)}|dd{round(r['dd_lockbox_25'],2)}",
    axis=1,
)
df["depth_int"] = df["gate_stack"].str.count("&") + 1
df["sum_28d"] = df["sum_train_25"] + df["sum_val_25"] + df["sum_lockbox_25"]
df_unique = df.sort_values(["depth_int", "n_lockbox", "objective"], ascending=[True, False, False]).drop_duplicates("fingerprint", keep="first")
print(f"Unique fingerprints: {len(df_unique)}")

# Filter to those containing at least one V7 NEW gate
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
df_unique["has_v7"] = df_unique["gate_stack"].apply(lambda s: any(g in s for g in v7_new_gates))

# TOP 15 unique V7 sleeves by sum_28d
top15 = df_unique[df_unique["has_v7"]].sort_values("sum_28d", ascending=False).head(15)
print(f"\nTOP 15 UNIQUE V7 sleeves by sum_28d:")
print(top15[["offset", "depth_int", "gate_stack",
             "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25", "sum_28d",
             "dd_lockbox_25", "ls_lockbox", "sharpe_lockbox", "boot_p_lockbox"]].to_string(max_colwidth=110))

# TOP 15 unique V7 sleeves by objective (dpt * sqrt(n))
print(f"\nTOP 15 UNIQUE V7 sleeves by OBJECTIVE (dpt*sqrt(n)):")
print(df_unique[df_unique["has_v7"]].sort_values("objective", ascending=False).head(15)[
    ["offset", "depth_int", "gate_stack",
     "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25",
     "dd_lockbox_25", "ls_lockbox", "objective"]
].to_string(max_colwidth=110))

# Top by dpt_lockbox (highest edge per trade)
print(f"\nTOP 15 UNIQUE V7 sleeves by DPT_LOCKBOX:")
print(df_unique[df_unique["has_v7"] & (df_unique["n_lockbox"] >= 40)].sort_values("dpt_lockbox_25", ascending=False).head(15)[
    ["offset", "depth_int", "gate_stack",
     "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25",
     "dd_lockbox_25", "ls_lockbox", "objective"]
].to_string(max_colwidth=110))

# Save top 30 unique
top30_unique = df_unique[df_unique["has_v7"]].sort_values("sum_28d", ascending=False).head(30)
top30_unique.to_csv(os.path.join(RES, "v7_top30_unique.csv"), index=False)
print(f"\nSaved -> v7_top30_unique.csv")

# Diversity: also save best NON-V7 (pure V6) for comparison
top10_nov7 = df_unique[~df_unique["has_v7"]].sort_values("sum_28d", ascending=False).head(10)
print(f"\nTOP 10 NON-V7 (V6-only atoms) for comparison:")
print(top10_nov7[["offset", "depth_int", "gate_stack",
                  "n_lockbox", "wr_lockbox", "dpt_lockbox_25", "sum_lockbox_25", "sum_28d",
                  "dd_lockbox_25"]].to_string(max_colwidth=110))

# Path-attribution: count V7 sleeves grouped by which V7 gate they used
print("\n=== Path-attribution: which V7 gate wins? ===")
counts = {g: df_unique[df_unique["gate_stack"].str.contains(g, na=False, regex=False) & df_unique["has_v7"]].shape[0]
          for g in v7_new_gates}
counts = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
print("Per-gate count of unique survivors:")
for g, n in counts.items():
    if n > 0:
        avg_sum = df_unique[df_unique["gate_stack"].str.contains(g, na=False, regex=False) & df_unique["has_v7"]]["sum_lockbox_25"].mean()
        print(f"  {g}: n_sleeves={n}  avg_sum_lockbox=${avg_sum:.2f}")
