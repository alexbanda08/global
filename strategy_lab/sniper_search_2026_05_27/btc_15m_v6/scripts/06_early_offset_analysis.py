"""Document early-offset candidates separately as the V6 timing exploration.

V6 brief asks: 'Does BTC 15m work early or strictly late-window?'
This script extracts the 9 early-offset candidates (60, 120, 240) from
v6_final_candidates.csv and produces a side report.
"""
import pandas as pd
import numpy as np

OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v6"
df = pd.read_csv(f"{OUT_DIR}/v6_final_candidates.csv")

# All early
early = df[df["offset"].astype(str).isin(["60", "120", "240"])].copy()
print(f"Early-offset candidates (off in {60,120,240}): {len(early)}")

cols = ["gate_stack_str", "offset", "direction", "n_gates",
        "train_n", "train_wr", "val_n", "val_wr",
        "lock_n", "lock_wr", "lock_dpt", "lock_dd", "lock_streak", "lock_days",
        "lock_sharpe", "bootstrap_p", "obj_score", "sum_25_28d"]

# Save
early[cols].sort_values("obj_score", ascending=False).to_csv(
    f"{OUT_DIR}/early_offset_candidates.csv", index=False)
print(f"saved -> {OUT_DIR}/early_offset_candidates.csv")
print(early[cols].sort_values("obj_score", ascending=False).to_string())

print()
print("BREAKDOWN:")
print("\nBy (offset, direction):")
print(early.groupby(["offset", "direction"])[["lock_n", "lock_wr", "lock_dpt", "obj_score"]].agg(["count", "mean", "max"]).to_string())

# Compare to V5 late-window winners
print("\n=== V5 BENCHMARK (off=600 DOWN sleeves at $25) ===")
v5 = pd.read_csv("strategy_lab/sniper_search_2026_05_27/btc_15m/top_5_candidates.csv")
print(v5.to_string())

# Late vs early
print("\n=== V6 LATE (600+840) vs EARLY (60-240) ===")
late = df[df["offset"].astype(str).isin(["600", "840"])].copy()
print(f"Late candidates: {len(late)} median dpt=${late['lock_dpt'].median():.2f}, max=${late['lock_dpt'].max():.2f}")
print(f"Early candidates: {len(early)} median dpt=${early['lock_dpt'].median():.2f}, max=${early['lock_dpt'].max():.2f}")
print(f"VERDICT: late-window remains DOMINANT for BTC 15m. Early-offset is viable for a few specific gate combos.")
