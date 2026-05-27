"""Inspect search results — show top near-misses by various criteria."""
import pandas as pd, numpy as np
import os, json

RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"

all_c = pd.read_csv(f"{RES}/all_candidates.csv")
nm = pd.read_csv(f"{RES}/near_misses.csv")

print(f"all_candidates shape: {all_c.shape}")
print(f"all_candidates cols: {list(all_c.columns)[:30]}")
print()

# Filter: lockbox_n >= 5, lockbox_dpt_25 > 0
mask = (all_c["lockbox_n"] >= 5) & (all_c["lockbox_dpt_25"] > 0)
print(f"\n== All candidates with lockbox_n >= 5 AND dpt_25 > 0: {mask.sum()}")
sub = all_c[mask].sort_values("lockbox_dpt_25", ascending=False).head(30)
cols = ["sleeve_id","offset_label","lockbox_n","lockbox_wr","lockbox_dpt_25","lockbox_sum_25",
        "lockbox_dd_25","lockbox_loss_streak","lockbox_sharpe","bootstrap_p_lockbox",
        "train_wr","train_dpt","val_wr","val_n","val_dpt_25"]
cols = [c for c in cols if c in sub.columns]
print(sub[cols].to_string())

print()
print("== Highest WR_lockbox (n >= 8):")
mask = (all_c["lockbox_n"] >= 8) & (all_c["lockbox_wr"] > 0.7)
print(f"count: {mask.sum()}")
print(all_c[mask].sort_values("lockbox_wr", ascending=False).head(20)[cols].to_string())

print()
print("== Sniper-profile partial pass — count by metric")
def part(metric, cond, label):
    s = cond.sum()
    print(f"  {label}: {s}")
mask_n = (all_c["lockbox_n"] >= 8) & (all_c["lockbox_n"] <= 500)
part("n", mask_n, "n_lockbox 8-500")
part("wr", mask_n & (all_c["lockbox_wr"] >= 0.75), "  & WR>=0.75")
part("dpt", mask_n & (all_c["lockbox_wr"] >= 0.75) & (all_c["lockbox_dpt_25"] >= 3.0), "  & dpt>=3")
part("dd", mask_n & (all_c["lockbox_wr"] >= 0.75) & (all_c["lockbox_dpt_25"] >= 3.0) & (all_c["lockbox_dd_25"] >= -300), "  & dd>=-300")
part("ls", mask_n & (all_c["lockbox_wr"] >= 0.75) & (all_c["lockbox_dpt_25"] >= 3.0) & (all_c["lockbox_dd_25"] >= -300) & (all_c["lockbox_loss_streak"] <= 6), "  & ls<=6")
part("sh", mask_n & (all_c["lockbox_wr"] >= 0.75) & (all_c["lockbox_dpt_25"] >= 3.0) & (all_c["lockbox_dd_25"] >= -300) & (all_c["lockbox_loss_streak"] <= 6) & (all_c["lockbox_sharpe"] >= 2.0), "  & sharpe>=2")
part("bp", mask_n & (all_c["lockbox_wr"] >= 0.75) & (all_c["lockbox_dpt_25"] >= 3.0) & (all_c["lockbox_dd_25"] >= -300) & (all_c["lockbox_loss_streak"] <= 6) & (all_c["lockbox_sharpe"] >= 2.0) & (all_c["bootstrap_p_lockbox"] <= 0.05), "  & bp<=0.05")
