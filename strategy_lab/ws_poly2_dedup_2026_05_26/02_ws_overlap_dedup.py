"""
Apply PP's slug-overlap dedup methodology to TT's WS-poly2 fires.

Pipeline:
1. Use logistic_poly2 (TT's best by sum_pnl). Sleeve = WS_poly2 fires for that sleeve.
2. Compute pairwise Jaccard (fire + slug + dir-agreement) across the 7 WS sleeves.
3. Three dedup modes (mirror PP R6):
   - Mode A (PRIMARY ONLY, greedy): start with highest-sum sleeve; add next only if jaccard_fire < 0.40.
   - Mode B (NOTIONAL-SHARE / UNION): unique fires across positive sleeves, single bet per (slug, fire_us, dir).
   - Mode C (GATED-UNANIMITY): require all sleeves firing on a slug to agree on direction.
4. Compare WS-poly2 fires vs binary AND fires:
   a. On SAME slugs, does WS pick better direction?
   b. On DIFFERENT slugs, does WS-only PnL beat AND-only PnL?
5. Cross with PP's R6 final manifest:
   - Replace binary AND sleeve with WS equivalent when WS dominates.
   - Keep both if orthogonal.
   - Output final_deploy_manifest_v2.csv

We compute ALL of this on:
  (a) lockbox only (4d, May 22-25)
  (b) full window (32d, Apr 24-May 25)
to compare apples-to-apples with PP's R6 32d numbers.

Output:
  ws_pairwise_overlap.csv
  ws_dedup_modes.csv
  ws_vs_and_same_slugs.csv
  ws_vs_and_diff_slugs.csv
  final_deploy_manifest_v2.csv
  ws_dedup_summary.txt
"""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/ws_poly2_dedup_2026_05_26"
PP_R6 = f"{ROOT}/data/v4/canonical/_results/_overlap_audit_2026_05_26"

# ----------------------------------------------------------------
# Load
# ----------------------------------------------------------------
print("Loading WS predictions and PP R6 binary AND fires...")
ws = pd.read_parquet(f"{OUT}/ws_fires_all_models_all_splits.parquet")
ws_poly2 = ws[ws["model"]=="logistic_poly2"].copy()
ws_lr2 = ws[ws["model"]=="logistic_l2"].copy()
print(f"  ws_poly2 total rows (would_fire OR not): {len(ws_poly2):,}")
print(f"  ws_poly2 firing on lockbox: {((ws_poly2['split']=='lockbox') & (ws_poly2['would_fire']==1)).sum():,}")

# Binary AND fires (full window) from R6
pp_fires = pd.read_parquet(f"{PP_R6}/fired_by_sleeve.parquet")
print(f"  PP R6 binary AND fires (full 32d window): {len(pp_fires):,}")
pp_manifest = pd.read_csv(f"{PP_R6}/final_deploy_manifest.csv")
pp_deploy = pp_manifest[pp_manifest["status"]=="DEPLOY"].copy()
print(f"  PP DEPLOY sleeves: {len(pp_deploy)}")

# ----------------------------------------------------------------
# Step 1: WS-poly2 firing fires (long format)
# ----------------------------------------------------------------
ws_fires_full = ws_poly2[ws_poly2["would_fire"]==1].copy()
ws_fires_lock = ws_fires_full[ws_fires_full["split"]=="lockbox"].copy()
print(f"\nWS-poly2 firing fires - full window: {len(ws_fires_full):,}, lockbox: {len(ws_fires_lock):,}")

# Save WS poly2 fires
ws_fires_full.to_parquet(f"{OUT}/ws_poly2_fires_per_sleeve.parquet", compression="snappy")
print(f"SAVED -> ws_poly2_fires_per_sleeve.parquet")

# Per-sleeve summary
summary = ws_fires_full.groupby("sleeve").agg(
    n_full=("won_int","size"),
    wr_full=("won_int","mean"),
    sum_pnl_full=("pnl_legacy_usd","sum"),
).reset_index()
summary["sum_pnl_28d_full"] = summary["sum_pnl_full"] * (28/32)
summary["wr_pct_full"] = (summary["wr_full"]*100).round(1)

summary_lock = ws_fires_lock.groupby("sleeve").agg(
    n_lock=("won_int","size"),
    wr_lock=("won_int","mean"),
    sum_pnl_lock=("pnl_legacy_usd","sum"),
).reset_index()
summary_lock["sum_pnl_28d_lock_extrap"] = summary_lock["sum_pnl_lock"] * (28/4)  # extrapolate 4d -> 28d
summary_lock["wr_pct_lock"] = (summary_lock["wr_lock"]*100).round(1)

ws_summary = summary.merge(summary_lock, on="sleeve").sort_values("sum_pnl_full", ascending=False)
print("\n=== WS-poly2 per-sleeve sums (full 32d + lockbox 4d extrapolated) ===")
print(ws_summary[["sleeve","n_full","wr_pct_full","sum_pnl_full","sum_pnl_28d_full",
                  "n_lock","wr_pct_lock","sum_pnl_lock","sum_pnl_28d_lock_extrap"]].to_string(index=False))
ws_summary.to_csv(f"{OUT}/ws_poly2_per_sleeve_summary.csv", index=False)


# ----------------------------------------------------------------
# Step 2: Pairwise overlap matrix (WS-poly2 on full window)
# ----------------------------------------------------------------
print("\n=== Pairwise overlap matrix (WS-poly2, full window) ===")
sleeves = ws_summary["sleeve"].tolist()

# Build sets
fire_sets = {}
slug_sets = {}
dir_dict = {}
for sid in sleeves:
    sub = ws_fires_full[ws_fires_full["sleeve"]==sid]
    fire_sets[sid] = set(zip(sub["slug"].astype(str), sub["fire_us"].astype("int64"), sub["direction"].astype(str)))
    slug_sets[sid] = set(sub["slug"].astype(str).unique())
    dir_dict[sid] = sub.groupby("slug")["direction"].apply(set).to_dict()

rows = []
for i, a in enumerate(sleeves):
    for j, b in enumerate(sleeves):
        if i > j: continue
        fa, fb = fire_sets[a], fire_sets[b]
        sa, sb = slug_sets[a], slug_sets[b]
        inter_f = len(fa & fb)
        union_f = len(fa | fb)
        inter_s = len(sa & sb)
        union_s = len(sa | sb)
        jacc_f = inter_f / union_f if union_f else 0
        jacc_s = inter_s / union_s if union_s else 0
        common_slugs = sa & sb
        agree = total = 0
        for slug in common_slugs:
            dirs_a = dir_dict[a].get(slug, set())
            dirs_b = dir_dict[b].get(slug, set())
            if dirs_a & dirs_b:
                agree += 1
            total += 1
        dir_agree_pct = (agree/total*100) if total else 0
        rows.append(dict(sleeve_a=a, sleeve_b=b,
                         jaccard_fire=jacc_f, jaccard_slug=jacc_s,
                         inter_fires=inter_f, union_fires=union_f,
                         inter_slugs=inter_s, union_slugs=union_s,
                         dir_agree_pct=dir_agree_pct))
pairs = pd.DataFrame(rows)
pairs.to_csv(f"{OUT}/ws_pairwise_overlap.csv", index=False)
print(f"SAVED -> ws_pairwise_overlap.csv")

# Show top overlaps
top_pairs = pairs[pairs["sleeve_a"]!=pairs["sleeve_b"]].sort_values("jaccard_fire", ascending=False).head(20)
print("\n=== TOP overlapping pairs (WS-poly2, fire-level Jaccard) ===")
print(top_pairs[["sleeve_a","sleeve_b","jaccard_fire","jaccard_slug","inter_fires","union_fires","dir_agree_pct"]].to_string(index=False))


# ----------------------------------------------------------------
# Step 3: Three dedup modes
# ----------------------------------------------------------------
print("\n" + "="*70)
print("DEDUP MODES (full 32d window, $25 notional)")
print("="*70)

# Symmetric jaccard lookup
jacc_lookup = {}
for _, r in pairs.iterrows():
    a, b = r["sleeve_a"], r["sleeve_b"]
    jacc_lookup[(a,b)] = r["jaccard_fire"]
    jacc_lookup[(b,a)] = r["jaccard_fire"]
def jacc(a, b): return jacc_lookup.get((a,b), 0)

# Sort sleeves by full-window sum_pnl desc (only positive)
positive = ws_summary[ws_summary["sum_pnl_full"]>0].sort_values("sum_pnl_full", ascending=False).reset_index(drop=True)

# ----- Mode A: Greedy primary with jaccard<0.40 ------
THRESH = 0.40
selected = []
skipped = []
for _, row in positive.iterrows():
    sid = row["sleeve"]
    too_overlapped = False
    overlap_info = []
    for s in selected:
        j = jacc(sid, s)
        if j >= THRESH:
            too_overlapped = True
            overlap_info.append((s, round(j,2)))
    if too_overlapped:
        skipped.append(dict(sleeve=sid, reason="overlap", overlaps=overlap_info,
                            sum_pnl_full=row["sum_pnl_full"]))
        print(f"  SKIP  {sid:25s}  overlaps with {overlap_info}")
    else:
        selected.append(sid)
        print(f"  KEEP  {sid:25s}  full_sum=${row['sum_pnl_full']:.0f}  28d=${row['sum_pnl_28d_full']:.0f}")

mode_a_primary_fires = ws_fires_full[ws_fires_full["sleeve"].isin(selected)]
mode_a_unique = mode_a_primary_fires.drop_duplicates(subset=["slug","fire_us","direction"])
mode_a_sum = mode_a_unique["pnl_legacy_usd"].sum()
mode_a_28d = mode_a_sum * (28/32)
mode_a_n = len(mode_a_unique)
mode_a_wr = mode_a_unique["won_int"].mean() * 100
print(f"\nMode A (PRIMARY GREEDY): {len(selected)} sleeves, n={mode_a_n}, WR={mode_a_wr:.1f}%, sum=${mode_a_sum:.0f}, 28d=${mode_a_28d:.0f}")

# Lockbox version
mode_a_lock_fires = ws_fires_lock[ws_fires_lock["sleeve"].isin(selected)]
mode_a_lock_unique = mode_a_lock_fires.drop_duplicates(subset=["slug","fire_us","direction"])
mode_a_lock_sum = mode_a_lock_unique["pnl_legacy_usd"].sum()
mode_a_lock_28d_extrap = mode_a_lock_sum * (28/4)
mode_a_lock_n = len(mode_a_lock_unique)
mode_a_lock_wr = mode_a_lock_unique["won_int"].mean() * 100
print(f"  LOCKBOX: n={mode_a_lock_n}, WR={mode_a_lock_wr:.1f}%, sum=${mode_a_lock_sum:.0f}, 28d_extrap=${mode_a_lock_28d_extrap:.0f}")

# ----- Mode B: Union over positive sleeves ------
all_pos_fires = ws_fires_full[ws_fires_full["sleeve"].isin(positive["sleeve"])]
mode_b_unique = all_pos_fires.drop_duplicates(subset=["slug","fire_us","direction"])
mode_b_sum = mode_b_unique["pnl_legacy_usd"].sum()
mode_b_28d = mode_b_sum * (28/32)
mode_b_n = len(mode_b_unique)
mode_b_wr = mode_b_unique["won_int"].mean() * 100
print(f"\nMode B (UNION): {len(positive)} sleeves, n={mode_b_n}, WR={mode_b_wr:.1f}%, sum=${mode_b_sum:.0f}, 28d=${mode_b_28d:.0f}")

mode_b_lock_unique = ws_fires_lock[ws_fires_lock["sleeve"].isin(positive["sleeve"])].drop_duplicates(subset=["slug","fire_us","direction"])
mode_b_lock_sum = mode_b_lock_unique["pnl_legacy_usd"].sum()
mode_b_lock_n = len(mode_b_lock_unique)
mode_b_lock_wr = mode_b_lock_unique["won_int"].mean() * 100
mode_b_lock_28d_extrap = mode_b_lock_sum * (28/4)
print(f"  LOCKBOX: n={mode_b_lock_n}, WR={mode_b_lock_wr:.1f}%, sum=${mode_b_lock_sum:.0f}, 28d_extrap=${mode_b_lock_28d_extrap:.0f}")

# ----- Mode C: Gated unanimity ------
fm = all_pos_fires.groupby(["slug","fire_us"])
mode_c_rows = []
n_agree = n_disagree = n_solo = 0
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
    pnl = grp["pnl_legacy_usd"].iloc[0]
    won = grp["won_int"].iloc[0]
    split = grp["split"].iloc[0]
    mode_c_rows.append(dict(slug=slug, fire_us=fu, pnl_usd=pnl, won=won, sleeves=sleeves_here, split=split))
mode_c_df = pd.DataFrame(mode_c_rows)
mode_c_sum = mode_c_df["pnl_usd"].sum() if len(mode_c_df) else 0
mode_c_28d = mode_c_sum * (28/32)
mode_c_n = len(mode_c_df)
mode_c_wr = mode_c_df["won"].mean()*100 if len(mode_c_df) else 0
print(f"\nMode C (UNANIMITY): unanimous={n_agree}, disagree={n_disagree}, solo={n_solo}")
print(f"  n={mode_c_n}, WR={mode_c_wr:.1f}%, sum=${mode_c_sum:.0f}, 28d=${mode_c_28d:.0f}")

# Lockbox mode C
mode_c_lock_df = mode_c_df[mode_c_df["split"]=="lockbox"] if len(mode_c_df) else mode_c_df
mode_c_lock_sum = mode_c_lock_df["pnl_usd"].sum() if len(mode_c_lock_df) else 0
mode_c_lock_n = len(mode_c_lock_df)
mode_c_lock_wr = mode_c_lock_df["won"].mean()*100 if len(mode_c_lock_df) else 0
mode_c_lock_28d_extrap = mode_c_lock_sum * (28/4)
print(f"  LOCKBOX: n={mode_c_lock_n}, WR={mode_c_lock_wr:.1f}%, sum=${mode_c_lock_sum:.0f}, 28d_extrap=${mode_c_lock_28d_extrap:.0f}")

# Save modes
modes = pd.DataFrame([
    dict(mode="A_PRIMARY_GREEDY", scope="FULL_32d", n_sleeves=len(selected),
         n_fires=mode_a_n, wr=mode_a_wr, sum_pnl=mode_a_sum, sum_28d=mode_a_28d, at_250=mode_a_28d*10),
    dict(mode="A_PRIMARY_GREEDY", scope="LOCKBOX_4d", n_sleeves=len(selected),
         n_fires=mode_a_lock_n, wr=mode_a_lock_wr, sum_pnl=mode_a_lock_sum,
         sum_28d=mode_a_lock_28d_extrap, at_250=mode_a_lock_28d_extrap*10),
    dict(mode="B_UNION", scope="FULL_32d", n_sleeves=len(positive),
         n_fires=mode_b_n, wr=mode_b_wr, sum_pnl=mode_b_sum, sum_28d=mode_b_28d, at_250=mode_b_28d*10),
    dict(mode="B_UNION", scope="LOCKBOX_4d", n_sleeves=len(positive),
         n_fires=mode_b_lock_n, wr=mode_b_lock_wr, sum_pnl=mode_b_lock_sum,
         sum_28d=mode_b_lock_28d_extrap, at_250=mode_b_lock_28d_extrap*10),
    dict(mode="C_UNANIMITY", scope="FULL_32d", n_sleeves=len(positive),
         n_fires=mode_c_n, wr=mode_c_wr, sum_pnl=mode_c_sum, sum_28d=mode_c_28d, at_250=mode_c_28d*10),
    dict(mode="C_UNANIMITY", scope="LOCKBOX_4d", n_sleeves=len(positive),
         n_fires=mode_c_lock_n, wr=mode_c_lock_wr, sum_pnl=mode_c_lock_sum,
         sum_28d=mode_c_lock_28d_extrap, at_250=mode_c_lock_28d_extrap*10),
])
modes.to_csv(f"{OUT}/ws_dedup_modes.csv", index=False)
print(f"\nSAVED -> ws_dedup_modes.csv")
print(modes.to_string(index=False))


# ----------------------------------------------------------------
# Step 5: Cross-compare WS-poly2 vs binary AND on SAME fires
# ----------------------------------------------------------------
print("\n" + "="*70)
print("WS vs AND on SAME slug universe (full 32d)")
print("="*70)
# Binary AND fires (PP R6 set)
and_keys = set(zip(pp_fires["slug"].astype(str), pp_fires["fire_us"].astype("int64"), pp_fires["direction"].astype(str)))
ws_keys = set(zip(ws_fires_full["slug"].astype(str), ws_fires_full["fire_us"].astype("int64"), ws_fires_full["direction"].astype(str)))

# Slug overlap (any direction)
and_slugs = set(pp_fires["slug"].astype(str).unique())
ws_slugs = set(ws_fires_full["slug"].astype(str).unique())
both_slugs = and_slugs & ws_slugs
and_only_slugs = and_slugs - ws_slugs
ws_only_slugs = ws_slugs - and_slugs
print(f"  AND-only slugs: {len(and_only_slugs):,}")
print(f"  WS-only slugs:  {len(ws_only_slugs):,}")
print(f"  BOTH slugs:     {len(both_slugs):,}")
print(f"  Union slugs:    {len(and_slugs | ws_slugs):,}")

# On BOTH slugs - what does each pick?
# For each slug in both, look at AND's direction vs WS's direction
def cmp_on_slugs(slugs):
    a_pnl = pp_fires[pp_fires["slug"].isin(slugs)]["pnl_legacy_usd"].sum()
    a_n = len(pp_fires[pp_fires["slug"].isin(slugs)])
    a_wr = pp_fires[pp_fires["slug"].isin(slugs)]["won"].mean()
    w_pnl = ws_fires_full[ws_fires_full["slug"].isin(slugs)]["pnl_legacy_usd"].sum()
    w_n = len(ws_fires_full[ws_fires_full["slug"].isin(slugs)])
    w_wr = ws_fires_full[ws_fires_full["slug"].isin(slugs)]["won_int"].mean()
    return dict(scope=len(slugs), and_n=a_n, and_wr=a_wr, and_sum=a_pnl,
                ws_n=w_n, ws_wr=w_wr, ws_sum=w_pnl)
both_cmp = cmp_on_slugs(both_slugs)
and_only_cmp = cmp_on_slugs(and_only_slugs)
ws_only_cmp = cmp_on_slugs(ws_only_slugs)
print("\n  BOTH slugs:")
print(f"    AND: n={both_cmp['and_n']:,}, WR={both_cmp['and_wr']*100:.1f}%, sum=${both_cmp['and_sum']:.0f}")
print(f"    WS:  n={both_cmp['ws_n']:,}, WR={both_cmp['ws_wr']*100:.1f}%, sum=${both_cmp['ws_sum']:.0f}")
print(f"  AND-only slugs: AND n={and_only_cmp['and_n']:,}, sum=${and_only_cmp['and_sum']:.0f}")
print(f"  WS-only slugs:  WS  n={ws_only_cmp['ws_n']:,}, sum=${ws_only_cmp['ws_sum']:.0f}")

# Save
diff_summary = pd.DataFrame([
    dict(scope="BOTH", n_slugs=len(both_slugs), **{k:v for k,v in both_cmp.items() if k!='scope'}),
    dict(scope="AND_ONLY", n_slugs=len(and_only_slugs), **{k:v for k,v in and_only_cmp.items() if k!='scope'}),
    dict(scope="WS_ONLY", n_slugs=len(ws_only_slugs), **{k:v for k,v in ws_only_cmp.items() if k!='scope'}),
])
diff_summary.to_csv(f"{OUT}/ws_vs_and_slug_split.csv", index=False)

# Fire-level overlap
fire_overlap = and_keys & ws_keys
and_only_fires = and_keys - ws_keys
ws_only_fires = ws_keys - and_keys
print(f"\n  Fire-level overlap: {len(fire_overlap):,}, AND-only: {len(and_only_fires):,}, WS-only: {len(ws_only_fires):,}")


# ----------------------------------------------------------------
# Step 6: Cross with PP R6 manifest - combine WS + AND
# ----------------------------------------------------------------
print("\n" + "="*70)
print("CROSS WITH PP R6 MANIFEST: combine binary AND + WS-poly2")
print("="*70)

# PP R6 primary fires (12 DEPLOY sleeves union)
pp_deploy_sleeve_ids = pp_deploy[pp_deploy["status"]=="DEPLOY"]["sleeve_id"].tolist()
print(f"PP R6 DEPLOY sleeves: {pp_deploy_sleeve_ids}")
pp_primary_fires = pp_fires[pp_fires["sleeve_id"].isin(pp_deploy_sleeve_ids)]
pp_primary_keys = set(zip(pp_primary_fires["slug"].astype(str), pp_primary_fires["fire_us"].astype("int64"), pp_primary_fires["direction"].astype(str)))
print(f"PP R6 primary (12 DEPLOY) unique fires: {len(pp_primary_fires.drop_duplicates(subset=['slug','fire_us','direction'])):,}")
print(f"PP R6 primary unique fires sum: ${pp_primary_fires.drop_duplicates(subset=['slug','fire_us','direction'])['pnl_legacy_usd'].sum():.0f}")

# WS poly2 Mode A primary fires
ws_primary_fires = mode_a_primary_fires
ws_primary_keys = set(zip(ws_primary_fires["slug"].astype(str), ws_primary_fires["fire_us"].astype("int64"), ws_primary_fires["direction"].astype(str)))

# Compute overlap between PP-R6 primary and WS primary
joint_keys = pp_primary_keys & ws_primary_keys
pp_only = pp_primary_keys - ws_primary_keys
ws_only_combined = ws_primary_keys - pp_primary_keys
print(f"\nJoint AND+WS primary fires: {len(joint_keys):,}")
print(f"PP-only fires: {len(pp_only):,}")
print(f"WS-only fires: {len(ws_only_combined):,}")

# Combined manifest (union approach): PP-R6 primary fires UNION WS Mode A primary fires
pp_p = pp_primary_fires.drop_duplicates(subset=["slug","fire_us","direction"]).reset_index(drop=True)
pp_p = pp_p[["slug","fire_us","direction","pnl_legacy_usd","won"]].copy()
ws_p_raw = ws_primary_fires.drop_duplicates(subset=["slug","fire_us","direction"]).reset_index(drop=True)
ws_p = ws_p_raw[["slug","fire_us","direction","pnl_legacy_usd","won_int"]].copy()
ws_p.columns = ["slug","fire_us","direction","pnl_legacy_usd","won"]
all_primary = pd.concat([pp_p, ws_p], ignore_index=True)
all_primary_unique = all_primary.drop_duplicates(subset=["slug","fire_us","direction"]).reset_index(drop=True)
combined_sum = all_primary_unique["pnl_legacy_usd"].sum()
combined_28d = combined_sum * (28/32)
combined_n = len(all_primary_unique)
combined_wr = all_primary_unique["won"].mean() * 100
print(f"\nCOMBINED primary deploy (AND + WS Mode A union):")
print(f"  n={combined_n:,}, WR={combined_wr:.1f}%, sum=${combined_sum:.0f}")
print(f"  28d = ${combined_28d:.0f}  (at $25 notional)")
print(f"  28d at $250 = ${combined_28d*10:.0f}")

# Now per-sleeve marginal contribution for the manifest v2
# Build sleeve list: keep PP-R6 DEPLOY, add WS primary sleeves
v2_rows = []
# Already-claimed fires (start with PP-R6 primary's union)
claimed_fires = set()

# Order PP-R6 by their assigned priority + WS by sum_pnl
pp_deploy_sorted = pp_deploy.sort_values("deploy_priority")
ws_primary_sorted = ws_summary[ws_summary["sleeve"].isin(selected)].sort_values("sum_pnl_full", ascending=False)

# Add PP-R6 DEPLOY sleeves first (preserves R6 priority)
print("\n=== Building Manifest V2 ===")
for _, row in pp_deploy_sorted.iterrows():
    sid = row["sleeve_id"]
    sub = pp_fires[pp_fires["sleeve_id"]==sid]
    sub_keys = set(zip(sub["slug"].astype(str), sub["fire_us"].astype("int64"), sub["direction"].astype(str)))
    new_fires_keys = sub_keys - claimed_fires
    if not new_fires_keys:
        marginal = 0
        n_new = 0
    else:
        new_fires = sub[sub.apply(lambda r: (str(r["slug"]), int(r["fire_us"]), str(r["direction"])) in new_fires_keys, axis=1)]
        marginal = new_fires["pnl_legacy_usd"].sum()
        n_new = len(new_fires)
    claimed_fires |= sub_keys
    v2_rows.append(dict(
        source="PP_R6_AND",
        sleeve_id=sid,
        status="DEPLOY",
        marginal_n=n_new,
        marginal_sum_full=marginal,
        marginal_sum_28d=marginal*(28/32),
    ))
    print(f"  PP_AND  {sid:50s}  marg_n={n_new}, marg_28d=${marginal*(28/32):.0f}")

# Then add WS primary sleeves (new contribution)
for _, row in ws_primary_sorted.iterrows():
    sid = row["sleeve"]
    sub = ws_fires_full[ws_fires_full["sleeve"]==sid]
    sub_keys = set(zip(sub["slug"].astype(str), sub["fire_us"].astype("int64"), sub["direction"].astype(str)))
    new_fires_keys = sub_keys - claimed_fires
    if not new_fires_keys:
        marginal = 0
        n_new = 0
    else:
        new_fires = sub[sub.apply(lambda r: (str(r["slug"]), int(r["fire_us"]), str(r["direction"])) in new_fires_keys, axis=1)]
        marginal = new_fires["pnl_legacy_usd"].sum()
        n_new = len(new_fires)
    claimed_fires |= sub_keys
    v2_rows.append(dict(
        source="WS_POLY2",
        sleeve_id=sid,
        status="DEPLOY" if marginal > 0 else "SKIP_NEGATIVE_MARGINAL",
        marginal_n=n_new,
        marginal_sum_full=marginal,
        marginal_sum_28d=marginal*(28/32),
    ))
    print(f"  WS_PLY  {sid:50s}  marg_n={n_new}, marg_28d=${marginal*(28/32):.0f}")

v2_df = pd.DataFrame(v2_rows)
v2_df["cum_28d"] = v2_df["marginal_sum_28d"].cumsum()
v2_df.to_csv(f"{OUT}/final_deploy_manifest_v2.csv", index=False)
print(f"\nSAVED -> final_deploy_manifest_v2.csv")
print(v2_df.to_string(index=False))

print(f"\n{'='*70}")
print(f"FINAL combined deploy 28d (AND-primary + WS-primary): ${v2_df['marginal_sum_28d'].sum():.0f}")
print(f"  vs PP-R6 alone: ${pp_primary_fires.drop_duplicates(subset=['slug','fire_us','direction'])['pnl_legacy_usd'].sum()*(28/32):.0f}")
print(f"  vs WS-alone (mode A): ${mode_a_28d:.0f}")
print(f"  LIFT of adding WS to R6: ${v2_df['marginal_sum_28d'].sum() - pp_primary_fires.drop_duplicates(subset=['slug','fire_us','direction'])['pnl_legacy_usd'].sum()*(28/32):.0f}")

# Save text summary
with open(f"{OUT}/ws_dedup_summary.txt", "w", encoding="utf-8") as f:
    f.write(f"WS-poly2 Dedup Summary (2026-05-26)\n")
    f.write(f"=====================================\n\n")
    f.write(f"WS-poly2 raw naive sum (no dedup) full 32d: ${ws_summary['sum_pnl_full'].sum():.0f}  28d: ${ws_summary['sum_pnl_28d_full'].sum():.0f}\n")
    f.write(f"  TT's lockbox raw: ${ws_summary['sum_pnl_lock'].sum():.0f} (4d)\n\n")
    f.write(f"Mode A (PRIMARY GREEDY) full: ${mode_a_28d:.0f} / 28d  ({len(selected)} sleeves)\n")
    f.write(f"Mode B (UNION) full: ${mode_b_28d:.0f} / 28d  ({len(positive)} sleeves)\n")
    f.write(f"Mode C (UNANIMITY) full: ${mode_c_28d:.0f} / 28d\n\n")
    f.write(f"PP-R6 AND primary 28d: ${pp_primary_fires.drop_duplicates(subset=['slug','fire_us','direction'])['pnl_legacy_usd'].sum()*(28/32):.0f}\n")
    f.write(f"Combined AND+WS deploy 28d: ${v2_df['marginal_sum_28d'].sum():.0f}\n")
    f.write(f"Lift vs PP-R6 alone: ${v2_df['marginal_sum_28d'].sum() - pp_primary_fires.drop_duplicates(subset=['slug','fire_us','direction'])['pnl_legacy_usd'].sum()*(28/32):.0f}\n")

print(f"\nSAVED -> ws_dedup_summary.txt")
print("\nDone.")
