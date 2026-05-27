"""Final selection — pick top 5 per roster ($25-only and $250-capable) from fast_validated.csv.

Apply target profile:
- n_lockbox in [5, 500]
- WR_lockbox >= 0.75
- $/tr_lockbox_25 >= 3 (for $25 roster) or $/tr_lockbox_250 >= 30 (for $250)
- max_dd_25 >= -300 / max_dd_250 >= -3000
- loss_streak <= 6
- sharpe_lockbox >= 2.0
- boot_p_lockbox <= 0.05
- active_days_lockbox >= 2 (sniper but not single-day flier)
"""
import pandas as pd
import numpy as np
import os
import shutil

RES = "strategy_lab/sniper_search_2026_05_27/eth_5m/_results"
res = pd.read_csv(f"{RES}/fast_validated.csv")
print(f"total: {len(res)}")
print(f"by roster: {res['roster'].value_counts().to_dict()}")

# Strict pass at $25
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
def pass_250(r):
    return (
        r["roster"] == "$250" and
        5 <= r["n_lockbox"] <= 500 and
        r["wr_lockbox"] >= 0.75 and
        r["dpt_lockbox_250"] >= 30.0 and
        r["dd_lockbox_250"] >= -3000.0 and
        r["ls_lockbox"] <= 6 and
        r["sharpe_lockbox"] >= 2.0 and
        r["boot_p_lockbox"] <= 0.05 and
        r["active_days_lockbox"] >= 2
    )

res["pass_25"] = res.apply(pass_25, axis=1)
res["pass_250"] = res.apply(pass_250, axis=1)
print(f"\nstrict pass at $25: {res['pass_25'].sum()}")
print(f"strict pass at $250: {res['pass_250'].sum()}")

roster_25 = res[res["pass_25"]].sort_values("dpt_lockbox_25", ascending=False)
roster_250 = res[res["pass_250"]].sort_values("dpt_lockbox_250", ascending=False)

print()
print("=" * 80)
print("$25 ROSTER (top 10)")
print("=" * 80)
cols = ["sleeve_id","n_train","wr_train","dpt_train_25","n_val","wr_val","dpt_val_25",
        "n_lockbox","wr_lockbox","dpt_lockbox_25","sum_lockbox_25","dd_lockbox_25",
        "ls_lockbox","sharpe_lockbox","active_days_lockbox","boot_p_lockbox"]
for _, r in roster_25.head(10).iterrows():
    print(f"\n  {r['sleeve_id']}")
    print(f"    train: n={r['n_train']}, WR={r['wr_train']:.3f}, $/tr=${r['dpt_train_25']:+.2f}")
    print(f"    val  : n={r['n_val']}, WR={r['wr_val']:.3f}, $/tr=${r['dpt_val_25']:+.2f}")
    print(f"    lock : n={r['n_lockbox']}, WR={r['wr_lockbox']:.3f}, $/tr=${r['dpt_lockbox_25']:+.2f}, sum=${r['sum_lockbox_25']:+.2f}, dd=${r['dd_lockbox_25']:.2f}, ls={r['ls_lockbox']}, sh={r['sharpe_lockbox']:.2f}, ad={r['active_days_lockbox']}, p={r['boot_p_lockbox']:.4f}")

print()
print("=" * 80)
print("$250 ROSTER (top 10)")
print("=" * 80)
for _, r in roster_250.head(10).iterrows():
    print(f"\n  {r['sleeve_id']}")
    print(f"    train: n={r['n_train']}, WR={r['wr_train']:.3f}")
    print(f"    val  : n={r['n_val']}, WR={r['wr_val']:.3f}")
    print(f"    lock : n={r['n_lockbox']}, WR={r['wr_lockbox']:.3f}, $/tr_250=${r['dpt_lockbox_250']:+.0f}, sum_250=${r['sum_lockbox_250']:+.0f}, dd_250=${r['dd_lockbox_250']:.0f}, ls={r['ls_lockbox']}, sh={r['sharpe_lockbox']:.2f}, ad={r['active_days_lockbox']}, p={r['boot_p_lockbox']:.4f}")

# Save top 5 per roster
top25 = roster_25.head(5).copy()
top250 = roster_250.head(5).copy()
top25["anchor"] = top25["offset"].apply(lambda o: f"offset_{o}s")
top250["anchor"] = top250["offset"].apply(lambda o: f"offset_{o}s")

# Combined top_5_candidates.csv per brief
combined = pd.concat([top25.assign(roster_label="$25-only"),
                      top250.assign(roster_label="$250-capable")])
out_cols = ["sleeve_id","roster_label","anchor","gate_stack",
            "n_train","n_val","n_lockbox",
            "wr_train","wr_val","wr_lockbox",
            "dpt_lockbox_25","sum_lockbox_25","dd_lockbox_25",
            "ls_lockbox","sharpe_lockbox","boot_p_lockbox",
            "dpt_lockbox_250","sum_lockbox_250","dd_lockbox_250",
            "active_days_lockbox"]
out_cols = [c for c in out_cols if c in combined.columns]
combined[out_cols].to_csv(f"{RES}/top_5_candidates.csv", index=False)
print(f"\n\nwrote {RES}/top_5_candidates.csv ({len(combined)} rows)")

# Near-misses
def near_miss(r):
    return (
        not (r["pass_25"] or r["pass_250"]) and
        r["n_lockbox"] >= 5 and
        r["wr_lockbox"] >= 0.70 and
        r["dpt_lockbox_25"] >= 1.0
    )
res["near_miss"] = res.apply(near_miss, axis=1)
nm = res[res["near_miss"]].sort_values("dpt_lockbox_25", ascending=False)
print(f"\nnear-misses (relaxed WR>=0.7, dpt>=1, not strict): {len(nm)}")
# Annotate reason
def reason(r):
    fails = []
    if r["wr_lockbox"] < 0.75: fails.append(f"WR={r['wr_lockbox']:.2f}")
    if r["dpt_lockbox_25"] < 3: fails.append(f"$/tr={r['dpt_lockbox_25']:.2f}")
    if r["dd_lockbox_25"] < -300: fails.append(f"dd=${r['dd_lockbox_25']:.0f}")
    if r["ls_lockbox"] > 6: fails.append(f"ls={r['ls_lockbox']}")
    if r["sharpe_lockbox"] < 2.0: fails.append(f"sh={r['sharpe_lockbox']:.1f}")
    if r["boot_p_lockbox"] > 0.05: fails.append(f"p={r['boot_p_lockbox']:.2f}")
    if r["active_days_lockbox"] < 2: fails.append(f"ad={r['active_days_lockbox']}")
    return ",".join(fails) if fails else "ok"
nm["fail_reasons"] = nm.apply(reason, axis=1)
nm.head(30).to_csv(f"{RES}/near_misses.csv", index=False)
print(f"wrote {RES}/near_misses.csv (top 30 near-misses)")
