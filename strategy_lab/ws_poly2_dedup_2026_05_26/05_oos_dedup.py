"""
Apply dedup on OUT-OF-SAMPLE only (val + lockbox = 11d window).

The train period is IN-SAMPLE for the WS models. Including it in deploy projections
overstates true forward PnL.

Output: ws_dedup_oos_only.csv with Mode A/B/C on OOS-only.

Also compute dedup on lockbox-only (4d) for comparison, but note that 4d extrapolation
is highly unstable.
"""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/ws_poly2_dedup_2026_05_26"
PP_R6 = f"{ROOT}/data/v4/canonical/_results/_overlap_audit_2026_05_26"

ws_p = pd.read_parquet(f"{OUT}/ws_poly2_fires_per_sleeve.parquet")

# Both val + lockbox are OOS (model not trained on them)
oos = ws_p[ws_p["split"].isin(["val","lockbox"])].copy()
lock = ws_p[ws_p["split"]=="lockbox"].copy()
val_only = ws_p[ws_p["split"]=="val"].copy()

print(f"WS poly2 firing rows:")
print(f"  full (32d): {len(ws_p):,}")
print(f"  OOS (val+lockbox, 11d): {len(oos):,}")
print(f"  lockbox only (4d): {len(lock):,}")

# Build pairwise jaccard on OOS-only fires
def jaccard_matrix(df, sleeves):
    fire_sets = {}
    for sid in sleeves:
        sub = df[df["sleeve"]==sid]
        fire_sets[sid] = set(zip(sub["slug"].astype(str), sub["fire_us"].astype("int64"), sub["direction"].astype(str)))
    rows = []
    for i, a in enumerate(sleeves):
        for j, b in enumerate(sleeves):
            if i >= j: continue
            fa, fb = fire_sets[a], fire_sets[b]
            inter = len(fa & fb)
            union = len(fa | fb)
            rows.append((a, b, inter/union if union else 0, inter, union))
    return pd.DataFrame(rows, columns=["a","b","jaccard","inter","union"])

# Sort sleeves by OOS sum_pnl
oos_summary = oos.groupby("sleeve").agg(n=("won_int","size"), wr=("won_int","mean"),
                                          sum_pnl=("pnl_legacy_usd","sum")).reset_index()
oos_summary["per_day"] = oos_summary["sum_pnl"] / 11
oos_summary["sum_28d"] = oos_summary["per_day"] * 28
oos_summary["wr_pct"] = (oos_summary["wr"]*100).round(1)
oos_summary = oos_summary.sort_values("sum_pnl", ascending=False).reset_index(drop=True)
print("\n=== OOS (val+lockbox 11d) per-sleeve summary ===")
print(oos_summary.to_string(index=False))

lock_summary = lock.groupby("sleeve").agg(n=("won_int","size"), wr=("won_int","mean"),
                                            sum_pnl=("pnl_legacy_usd","sum")).reset_index()
lock_summary["per_day"] = lock_summary["sum_pnl"] / 4
lock_summary["sum_28d_extrap"] = lock_summary["per_day"] * 28
lock_summary = lock_summary.sort_values("sum_pnl", ascending=False).reset_index(drop=True)
print("\n=== LOCKBOX (4d) per-sleeve summary ===")
print(lock_summary.to_string(index=False))

# Mode A on OOS
sleeves_pos = oos_summary[oos_summary["sum_pnl"]>0].sort_values("sum_pnl", ascending=False)["sleeve"].tolist()
print(f"\nOOS positive sleeves: {sleeves_pos}")

# pairwise jaccard
pairs = jaccard_matrix(oos, sleeves_pos)
jacc_lookup = {(r["a"], r["b"]): r["jaccard"] for _, r in pairs.iterrows()}
jacc_lookup.update({(r["b"], r["a"]): r["jaccard"] for _, r in pairs.iterrows()})

THRESH = 0.40
selected = []
for sid in sleeves_pos:
    too_overlapped = False
    for s in selected:
        j = jacc_lookup.get((sid, s), 0)
        if j >= THRESH:
            too_overlapped = True
            break
    if not too_overlapped:
        selected.append(sid)
print(f"\nMode A OOS-only selected sleeves: {selected}")
print("\nPairwise overlaps:")
print(pairs.to_string(index=False))

# Mode A union of selected (winner takes all)
oos_selected_fires = oos[oos["sleeve"].isin(selected)]
oos_unique = oos_selected_fires.drop_duplicates(subset=["slug","fire_us","direction"])
print(f"\n=== Mode A (OOS) ===")
print(f"  n_unique={len(oos_unique)}, WR={oos_unique['won_int'].mean()*100:.1f}%, sum=${oos_unique['pnl_legacy_usd'].sum():.0f}")
print(f"  per_day=${oos_unique['pnl_legacy_usd'].sum()/11:.0f}, 28d=${oos_unique['pnl_legacy_usd'].sum()*(28/11):.0f}")

# Mode B (union over all positive)
oos_all_pos = oos[oos["sleeve"].isin(sleeves_pos)]
oos_b_unique = oos_all_pos.drop_duplicates(subset=["slug","fire_us","direction"])
print(f"\n=== Mode B (OOS) ===")
print(f"  n_unique={len(oos_b_unique)}, WR={oos_b_unique['won_int'].mean()*100:.1f}%, sum=${oos_b_unique['pnl_legacy_usd'].sum():.0f}")
print(f"  per_day=${oos_b_unique['pnl_legacy_usd'].sum()/11:.0f}, 28d=${oos_b_unique['pnl_legacy_usd'].sum()*(28/11):.0f}")

# Mode C (unanimity) on OOS
fm = oos_all_pos.groupby(["slug","fire_us"])
n_agree = n_disagree = n_solo = 0
rows = []
for (slug, fu), grp in fm:
    sleeves_here = grp["sleeve"].nunique()
    dirs = set(grp["direction"].unique())
    if len(dirs) > 1:
        n_disagree += 1
        continue
    if sleeves_here == 1:
        n_solo += 1
        continue
    n_agree += 1
    rows.append(dict(slug=slug, fire_us=fu, pnl=grp["pnl_legacy_usd"].iloc[0], won=grp["won_int"].iloc[0]))
c_df = pd.DataFrame(rows)
print(f"\n=== Mode C (OOS): unanimous={n_agree}, disagree={n_disagree}, solo={n_solo} ===")
if len(c_df):
    print(f"  n={len(c_df)}, WR={c_df['won'].mean()*100:.1f}%, sum=${c_df['pnl'].sum():.0f}")
    print(f"  per_day=${c_df['pnl'].sum()/11:.0f}, 28d=${c_df['pnl'].sum()*(28/11):.0f}")
else:
    print("  no unanimous fires")


# ----- Add PP-R6 binary AND on OOS-only for fair comparison -----
print("\n" + "="*60)
print("PP-R6 binary AND on OOS-only (val+lockbox, 11d)")
print("="*60)
pp = pd.read_parquet(f"{PP_R6}/fired_by_sleeve.parquet")
pp["slug"] = pp["slug"].astype(str)
pp["fire_us"] = pp["fire_us"].astype("int64")
pp["direction"] = pp["direction"].astype(str)
# Add ts
pp["ts"] = pd.to_datetime(pp["fire_us"]/1e6, unit="s")
pp_oos = pp[(pp["ts"]>=pd.Timestamp("2026-05-15"))].copy()
pp_lock = pp[(pp["ts"]>=pd.Timestamp("2026-05-22"))].copy()
print(f"  PP-R6 OOS fires: {len(pp_oos):,}")
print(f"  PP-R6 lockbox fires: {len(pp_lock):,}")

pp_manifest = pd.read_csv(f"{PP_R6}/final_deploy_manifest.csv")
pp_deploy_ids = pp_manifest[pp_manifest["status"]=="DEPLOY"]["sleeve_id"].tolist()
pp_d_oos = pp_oos[pp_oos["sleeve_id"].isin(pp_deploy_ids)]
pp_d_oos_unique = pp_d_oos.drop_duplicates(subset=["slug","fire_us","direction"])
print(f"  PP-R6 DEPLOY OOS unique fires: {len(pp_d_oos_unique):,}")
print(f"  PP-R6 DEPLOY OOS sum: ${pp_d_oos_unique['pnl_legacy_usd'].sum():.0f}")
print(f"  PP-R6 DEPLOY OOS per_day: ${pp_d_oos_unique['pnl_legacy_usd'].sum()/11:.0f}")
print(f"  PP-R6 DEPLOY OOS 28d: ${pp_d_oos_unique['pnl_legacy_usd'].sum()*(28/11):.0f}")
print(f"  PP-R6 DEPLOY OOS WR: {pp_d_oos_unique['won'].mean()*100:.1f}%")

pp_d_lock = pp_lock[pp_lock["sleeve_id"].isin(pp_deploy_ids)]
pp_d_lock_unique = pp_d_lock.drop_duplicates(subset=["slug","fire_us","direction"])
print(f"\n  PP-R6 DEPLOY LOCKBOX unique fires: {len(pp_d_lock_unique):,}")
print(f"  PP-R6 DEPLOY LOCKBOX sum: ${pp_d_lock_unique['pnl_legacy_usd'].sum():.0f}")
print(f"  PP-R6 DEPLOY LOCKBOX 28d_extrap: ${pp_d_lock_unique['pnl_legacy_usd'].sum()*(28/4):.0f}")

# Combined: WS Mode A union + PP-R6 union, dedup
ws_a_keys = set(zip(oos_unique["slug"].astype(str), oos_unique["fire_us"].astype("int64"), oos_unique["direction"].astype(str)))
pp_keys = set(zip(pp_d_oos_unique["slug"].astype(str), pp_d_oos_unique["fire_us"].astype("int64"), pp_d_oos_unique["direction"].astype(str)))
all_keys = ws_a_keys | pp_keys
overlap = ws_a_keys & pp_keys
print(f"\nWS Mode A unique keys: {len(ws_a_keys):,}")
print(f"PP-R6 keys: {len(pp_keys):,}")
print(f"Union: {len(all_keys):,}, Overlap: {len(overlap):,}")

# Build pnl for union
ws_pnl_by_key = {(r["slug"], int(r["fire_us"]), r["direction"]): r["pnl_legacy_usd"] for _, r in oos_unique.iterrows()}
pp_pnl_by_key = {(r["slug"], int(r["fire_us"]), r["direction"]): r["pnl_legacy_usd"] for _, r in pp_d_oos_unique.iterrows()}
pnls = []
for k in all_keys:
    p = ws_pnl_by_key.get(k, pp_pnl_by_key.get(k, 0))
    pnls.append(p)
union_sum = sum(pnls)
print(f"\n=== Combined WS+PP OOS deploy ===")
print(f"  union_n: {len(all_keys)}")
print(f"  union sum: ${union_sum:.0f}")
print(f"  union per_day: ${union_sum/11:.0f}")
print(f"  union 28d: ${union_sum*(28/11):.0f}")

# Final OOS modes summary
modes_oos = pd.DataFrame([
    dict(mode="WS_Mode_A_OOS", n=len(oos_unique), wr=oos_unique["won_int"].mean()*100,
         sum_pnl=oos_unique["pnl_legacy_usd"].sum(), per_day=oos_unique["pnl_legacy_usd"].sum()/11,
         sum_28d=oos_unique["pnl_legacy_usd"].sum()*(28/11)),
    dict(mode="WS_Mode_B_OOS", n=len(oos_b_unique), wr=oos_b_unique["won_int"].mean()*100,
         sum_pnl=oos_b_unique["pnl_legacy_usd"].sum(), per_day=oos_b_unique["pnl_legacy_usd"].sum()/11,
         sum_28d=oos_b_unique["pnl_legacy_usd"].sum()*(28/11)),
    dict(mode="WS_Mode_C_OOS", n=len(c_df) if len(c_df) else 0,
         wr=(c_df["won"].mean()*100) if len(c_df) else 0,
         sum_pnl=c_df["pnl"].sum() if len(c_df) else 0,
         per_day=(c_df["pnl"].sum()/11) if len(c_df) else 0,
         sum_28d=(c_df["pnl"].sum()*(28/11)) if len(c_df) else 0),
    dict(mode="PP_R6_AND_OOS", n=len(pp_d_oos_unique), wr=pp_d_oos_unique["won"].mean()*100,
         sum_pnl=pp_d_oos_unique["pnl_legacy_usd"].sum(), per_day=pp_d_oos_unique["pnl_legacy_usd"].sum()/11,
         sum_28d=pp_d_oos_unique["pnl_legacy_usd"].sum()*(28/11)),
    dict(mode="WS_PRIMARY_PLUS_PP_R6_OOS", n=len(all_keys), wr=0,
         sum_pnl=union_sum, per_day=union_sum/11, sum_28d=union_sum*(28/11)),
])
modes_oos.to_csv(f"{OUT}/ws_dedup_oos_only.csv", index=False)
print(f"\nSAVED -> ws_dedup_oos_only.csv")
print("\n=== FINAL OOS COMPARISON TABLE ===")
print(modes_oos.to_string(index=False))
