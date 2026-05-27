"""Select top 5 V6 sleeves with cross-period stability constraints.

Filtering rules on top of the V6 sniper bar:
- train_wr >= 0.60 (don't lockbox-fit)
- val_wr >= 0.55 (must hold up in val too)
- lock_n >= 12 (a bit more statistical power)
- prefer diverse offsets across the 5

Output: top_5_candidates_v6.csv (for the brief deliverable)
"""
import pandas as pd
import numpy as np

OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v6"
df = pd.read_csv(f"{OUT_DIR}/v6_final_candidates.csv")
print(f"Total final candidates: {len(df)}")

# Cross-period stability filters
stable = df.copy()
stable = stable[stable["train_wr"] >= 0.60]
stable = stable[stable["val_wr"] >= 0.55]
stable = stable[stable["lock_n"] >= 12]
print(f"After train_wr>=0.60 + val_wr>=0.55 + lock_n>=12: {len(stable)}")

# Drop exact dups (sometimes same gate variants come up)
stable["gate_key"] = stable["gate_stack_str"].apply(lambda x: tuple(sorted(x.split("+"))))
stable["dedup"] = list(zip(stable["offset"], stable["direction"], stable["gate_key"]))
stable = stable.drop_duplicates(subset="dedup", keep="first").drop(columns=["gate_key", "dedup"])
print(f"After dedup: {len(stable)}")

# Sort by obj_score
stable = stable.sort_values("obj_score", ascending=False)

# Want a diverse top 5: don't pick 5 from same (offset, direction). At most 2 per cell.
cell_counts = {}
top5 = []
for _, row in stable.iterrows():
    cell = (row["offset"], row["direction"])
    cnt = cell_counts.get(cell, 0)
    if cnt >= 2:
        continue
    cell_counts[cell] = cnt + 1
    top5.append(row)
    if len(top5) >= 5:
        break

print(f"\nSelected {len(top5)} diverse top candidates")
top5_df = pd.DataFrame(top5)

cols = ["gate_stack_str", "offset", "direction", "n_gates",
        "train_n", "train_wr", "val_n", "val_wr",
        "lock_n", "lock_wr", "lock_dpt", "lock_dd", "lock_streak", "lock_days",
        "lock_sharpe", "bootstrap_p", "obj_score", "sum_25_28d"]
print(top5_df[cols].to_string())

# Assign sleeve IDs and write top 5
def make_id(row, i):
    off = row["offset"]
    dr = row["direction"]
    return f"btc15m_v6_off{off}_{dr}_{i+1:02d}"

top5_df["sleeve_id"] = [make_id(r, i) for i, (_, r) in enumerate(top5_df.iterrows())]
top5_df["anchor"] = top5_df["offset"].apply(lambda x: f"offset_{x}s")
top5_df["gate_stack"] = top5_df["gate_stack_str"]
top5_df["conviction_method"] = "B"  # empirical bucket
top5_df["sum_25_28d_const"] = top5_df["sum_25_28d"]
top5_df["sum_25_28d_kelly"] = np.nan  # to be filled by Kelly simulation step

OUT_COLS = ["sleeve_id", "anchor", "gate_stack", "conviction_method",
            "n_gates", "train_n", "val_n", "lock_n",
            "train_wr", "val_wr", "lock_wr",
            "lock_dpt", "sum_25_28d_const", "sum_25_28d_kelly",
            "lock_dd", "lock_streak", "lock_sharpe", "bootstrap_p",
            "obj_score", "offset", "direction"]
out = top5_df[OUT_COLS].rename(columns={
    "train_n": "n_train", "val_n": "n_val", "lock_n": "n_lockbox",
    "train_wr": "wr_train", "val_wr": "wr_val", "lock_wr": "wr_lockbox",
    "lock_dpt": "dpt_25_lockbox", "lock_dd": "max_dd_25",
    "lock_streak": "loss_streak", "lock_sharpe": "sharpe",
    "bootstrap_p": "bootstrap_p_lockbox",
})
out.to_csv(f"{OUT_DIR}/top_5_candidates_v6.csv", index=False)
print(f"\nWROTE -> {OUT_DIR}/top_5_candidates_v6.csv")
