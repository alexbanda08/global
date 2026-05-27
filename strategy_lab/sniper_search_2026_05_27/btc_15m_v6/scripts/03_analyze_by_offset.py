"""Analyze the V6 final candidates by offset / direction to find diversity.

Key question: did V6 actually find any EARLY-offset candidates (60, 120, 240)?
If yes, those are the V6 contribution beyond V5.
"""
import pandas as pd
import numpy as np

OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v6"
df = pd.read_csv(f"{OUT_DIR}/v6_final_candidates.csv")
print(f"Total final candidates (post-bootstrap): {len(df)}")

print("\n=== BY OFFSET ===")
print(df.groupby("offset").agg(
    n_candidates=("gate_stack_str", "count"),
    median_dpt=("lock_dpt", "median"),
    median_n=("lock_n", "median"),
    median_wr=("lock_wr", "median"),
    median_obj=("obj_score", "median"),
).to_string())

print("\n=== BY DIRECTION ===")
print(df.groupby("direction").agg(
    n_candidates=("gate_stack_str", "count"),
    median_dpt=("lock_dpt", "median"),
    median_obj=("obj_score", "median"),
).to_string())

print("\n=== BY (OFFSET, DIRECTION) ===")
print(df.groupby(["offset", "direction"]).agg(
    n_cand=("gate_stack_str", "count"),
    median_dpt=("lock_dpt", "median"),
    median_obj=("obj_score", "median"),
    top_dpt=("lock_dpt", "max"),
    top_obj=("obj_score", "max"),
).to_string())

# Focus: early offset candidates
print("\n=== EARLY OFFSET candidates (60, 120, 240) ===")
early = df[df["offset"].isin(["60", "120", "240", 60, 120, 240])]
print(f"Found {len(early)} early-offset candidates")
if len(early) > 0:
    cols = ["gate_stack_str", "offset", "direction", "n_gates",
            "lock_n", "lock_wr", "lock_dpt", "lock_dd", "lock_streak", "lock_days",
            "lock_sharpe", "bootstrap_p", "obj_score", "sum_25_28d",
            "train_n", "train_wr", "val_n", "val_wr"]
    print(early.sort_values("obj_score", ascending=False)[cols].head(20).to_string())

print("\n=== TOP 5 CANDIDATES BY obj_score ===")
top5 = df.sort_values("obj_score", ascending=False).head(5)
cols = ["gate_stack_str", "offset", "direction",
        "train_n", "train_wr", "val_n", "val_wr",
        "lock_n", "lock_wr", "lock_dpt", "lock_dd", "lock_streak", "lock_days",
        "lock_sharpe", "bootstrap_p", "obj_score", "sum_25_28d"]
print(top5[cols].to_string())
print()
print("\n=== TOP 5 BY SUM_25_28d (raw $ return scaled to 28d) ===")
top5b = df.sort_values("sum_25_28d", ascending=False).head(5)
print(top5b[cols].to_string())
print()

# Look for early-offset DOWN-only candidates
print("\n=== ASYMMETRIC: EARLY-OFFSET DOWN-only candidates ===")
early_dn = df[df["offset"].isin(["60", "120", "240", 60, 120, 240]) & (df["direction"] == "DOWN")]
print(f"Found {len(early_dn)}")
if len(early_dn) > 0:
    print(early_dn.sort_values("obj_score", ascending=False)[cols].head(10).to_string())

print("\n=== EARLY OFFSET (any direction) — top by Sharpe ===")
if len(early) > 0:
    print(early.sort_values("lock_sharpe", ascending=False)[cols].head(10).to_string())
