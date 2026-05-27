"""Among 48 passing $25 sleeves, prefer those with val_dpt >= 0 AND train_dpt >= 0 (cross-split robust)."""
import pandas as pd
import numpy as np

RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"
res = pd.read_csv(f"{RES}/fast_validated.csv")
# Filter to strict pass at $25
def pass_25(r):
    return (
        r["roster"] == "$25" and
        5 <= r["n_lockbox"] <= 500 and
        r["wr_lockbox"] >= 0.75 and
        r["dpt_lockbox_25"] >= 3.0 and
        r["dd_lockbox_25"] >= -300.0 and
        r["ls_lockbox"] <= 6 and
        r["sharpe_lockbox"] >= 2.0 and
        r["boot_p_lockbox"] <= 0.05 and
        r["active_days_lockbox"] >= 2
    )
res["pass_25"] = res.apply(pass_25, axis=1)
ros = res[res["pass_25"]].copy()
print(f"strict $25 pass: {len(ros)}")

ros["val_pos"] = (ros["dpt_val_25"] >= 0)
ros["train_pos"] = (ros["dpt_train_25"] >= 0)
ros["both_pos"] = ros["val_pos"] & ros["train_pos"]
ros["val_wr_solid"] = (ros["wr_val"] >= 0.70)
print(f"  with val_dpt >= 0: {ros['val_pos'].sum()}")
print(f"  with train_dpt >= 0: {ros['train_pos'].sum()}")
print(f"  with BOTH >= 0: {ros['both_pos'].sum()}")
print(f"  with val_WR >= 0.70: {ros['val_wr_solid'].sum()}")
print(f"  with both_pos AND val_WR>=0.70: {(ros['both_pos'] & ros['val_wr_solid']).sum()}")

# Robust filter
robust = ros[ros["both_pos"] & ros["val_wr_solid"]].sort_values("dpt_lockbox_25", ascending=False)
print(f"\n== ROBUST TOP 10 (both train+val dpt >= 0 AND val_WR >= 0.70) ==")
for _, r in robust.head(10).iterrows():
    print(f"\n  {r['sleeve_id']}")
    print(f"    train: n={r['n_train']}, WR={r['wr_train']:.3f}, $/tr=${r['dpt_train_25']:+.2f}")
    print(f"    val  : n={r['n_val']}, WR={r['wr_val']:.3f}, $/tr=${r['dpt_val_25']:+.2f}")
    print(f"    lock : n={r['n_lockbox']}, WR={r['wr_lockbox']:.3f}, $/tr=${r['dpt_lockbox_25']:+.2f}, sum=${r['sum_lockbox_25']:+.2f}, dd=${r['dd_lockbox_25']:.0f}, ls={r['ls_lockbox']}, sh={r['sharpe_lockbox']:.1f}, ad={r['active_days_lockbox']}, p={r['boot_p_lockbox']:.4f}")

# Save robust top 5
top5 = robust.head(5).copy()
top5["anchor"] = top5["offset"].apply(lambda o: f"offset_{o}s")
top5["roster_label"] = "$25-only"
out_cols = ["sleeve_id","roster_label","anchor","gate_stack","n_train","wr_train","dpt_train_25",
            "n_val","wr_val","dpt_val_25",
            "n_lockbox","wr_lockbox","dpt_lockbox_25","sum_lockbox_25","dd_lockbox_25",
            "ls_lockbox","sharpe_lockbox","active_days_lockbox","boot_p_lockbox"]
out_cols = [c for c in out_cols if c in top5.columns]
top5[out_cols].to_csv(f"{RES}/top_5_robust_25.csv", index=False)
print(f"\nsaved {RES}/top_5_robust_25.csv")
