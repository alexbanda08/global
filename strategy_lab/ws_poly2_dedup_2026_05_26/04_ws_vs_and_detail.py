"""
TASK 5+6: Detailed cross-compare WS-poly2 vs binary AND.

For SAME slugs (fires both fire on):
- Per-fire-key (slug, fire_us, direction): does WS pick better direction?
- Compute WR / DPT / sum on shared fires for each

For DIFFERENT slugs:
- WS-only fires: positive PnL?
- AND-only fires: positive PnL?
"""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/ws_poly2_dedup_2026_05_26"
PP_R6 = f"{ROOT}/data/v4/canonical/_results/_overlap_audit_2026_05_26"

ws_p = pd.read_parquet(f"{OUT}/ws_poly2_fires_per_sleeve.parquet")
ws_p["slug"] = ws_p["slug"].astype(str)
ws_p["fire_us"] = ws_p["fire_us"].astype("int64")
ws_p["direction"] = ws_p["direction"].astype(str)

pp = pd.read_parquet(f"{PP_R6}/fired_by_sleeve.parquet")
pp["slug"] = pp["slug"].astype(str)
pp["fire_us"] = pp["fire_us"].astype("int64")
pp["direction"] = pp["direction"].astype(str)

# PP DEPLOY sleeves only
pp_manifest = pd.read_csv(f"{PP_R6}/final_deploy_manifest.csv")
pp_deploy_ids = pp_manifest[pp_manifest["status"]=="DEPLOY"]["sleeve_id"].tolist()
pp_d = pp[pp["sleeve_id"].isin(pp_deploy_ids)]

# WS poly2 mode A primary (all 7 since pairwise jaccard low)
ws_mode_a = ws_p  # all sleeves kept

# Unique fire-keys per set
ws_keys = set(zip(ws_mode_a["slug"], ws_mode_a["fire_us"], ws_mode_a["direction"]))
pp_keys = set(zip(pp_d["slug"], pp_d["fire_us"], pp_d["direction"]))

print(f"WS-poly2 unique fire-keys: {len(ws_keys):,}")
print(f"PP-R6 unique fire-keys: {len(pp_keys):,}")
both_keys = ws_keys & pp_keys
ws_only_keys = ws_keys - pp_keys
pp_only_keys = pp_keys - ws_keys
print(f"BOTH (exact fire-key match): {len(both_keys):,}")
print(f"WS-only: {len(ws_only_keys):,}")
print(f"PP-only: {len(pp_only_keys):,}")

# PnL on each set (dedup by fire-key first)
ws_u = ws_mode_a.drop_duplicates(subset=["slug","fire_us","direction"])
pp_u = pp_d.drop_duplicates(subset=["slug","fire_us","direction"])

def stats_on_keys(keys, df, won_col):
    mask = df.apply(lambda r: (r["slug"], r["fire_us"], r["direction"]) in keys, axis=1)
    sub = df[mask]
    if len(sub)==0:
        return dict(n=0, wr=0, sum=0, dpt=0)
    return dict(n=len(sub), wr=sub[won_col].mean(), sum=sub["pnl_legacy_usd"].sum(),
                dpt=sub["pnl_legacy_usd"].mean())

# BOTH set - same fire-key match
print("\n=== BOTH (exact fire-key match) ===")
ws_on_both = stats_on_keys(both_keys, ws_u, "won_int")
pp_on_both = stats_on_keys(both_keys, pp_u, "won")
print(f"WS on BOTH: n={ws_on_both['n']}, WR={ws_on_both['wr']*100:.1f}%, sum=${ws_on_both['sum']:.0f}, dpt=${ws_on_both['dpt']:.3f}")
print(f"PP on BOTH: n={pp_on_both['n']}, WR={pp_on_both['wr']*100:.1f}%, sum=${pp_on_both['sum']:.0f}, dpt=${pp_on_both['dpt']:.3f}")

# WS-only
print("\n=== WS-ONLY (fires WS triggers but PP-AND does NOT) ===")
ws_on_only = stats_on_keys(ws_only_keys, ws_u, "won_int")
print(f"  n={ws_on_only['n']}, WR={ws_on_only['wr']*100:.1f}%, sum=${ws_on_only['sum']:.0f}, dpt=${ws_on_only['dpt']:.3f}")
print(f"  28d (at $25): ${ws_on_only['sum']*(28/32):.0f}")

# PP-only
print("\n=== PP-ONLY (fires PP-AND triggers but WS does NOT) ===")
pp_on_only = stats_on_keys(pp_only_keys, pp_u, "won")
print(f"  n={pp_on_only['n']}, WR={pp_on_only['wr']*100:.1f}%, sum=${pp_on_only['sum']:.0f}, dpt=${pp_on_only['dpt']:.3f}")
print(f"  28d (at $25): ${pp_on_only['sum']*(28/32):.0f}")

# On same (slug, fire_us) but DIFFERENT direction:
# fire moments where both AND and WS fire on the same slug/time but opposite direction
ws_slug_fire = ws_u.groupby(["slug","fire_us"])["direction"].apply(set).to_dict()
pp_slug_fire = pp_u.groupby(["slug","fire_us"])["direction"].apply(set).to_dict()

dir_disagree = []
dir_agree_examples = []
both_sf = set(ws_slug_fire.keys()) & set(pp_slug_fire.keys())
n_same = n_diff = 0
for sf in both_sf:
    a = ws_slug_fire[sf]
    b = pp_slug_fire[sf]
    if a & b:
        n_same += 1
    elif a | b == {"UP","DOWN"}:
        n_diff += 1

print(f"\n=== On SAME (slug, fire_us) moments fired by BOTH ===")
print(f"  Total such moments: {len(both_sf):,}")
print(f"  Same direction picked: {n_same:,}")
print(f"  Disagree direction:    {n_diff:,}")

# Save outputs
df_out = pd.DataFrame([
    dict(scope="WS_on_BOTH", **ws_on_both),
    dict(scope="PP_on_BOTH", **pp_on_both),
    dict(scope="WS_only", **ws_on_only),
    dict(scope="PP_only", **pp_on_only),
])
df_out["sum_28d"] = df_out["sum"] * (28/32)
df_out["wr_pct"] = df_out["wr"] * 100
df_out.to_csv(f"{OUT}/ws_vs_and_detailed.csv", index=False)
print(f"\nSAVED -> ws_vs_and_detailed.csv")
print(df_out.to_string(index=False))

# Per-direction breakdown on WS-only - by sleeve
print("\n=== WS-only fires by sleeve (orthogonal alpha from WS) ===")
ws_only_keyset = ws_only_keys
ws_only_df = ws_mode_a[ws_mode_a.apply(lambda r: (r["slug"], r["fire_us"], r["direction"]) in ws_only_keyset, axis=1)]
sleeve_breakdown = ws_only_df.groupby("sleeve").agg(
    n=("won_int","size"),
    wr=("won_int","mean"),
    sum_pnl=("pnl_legacy_usd","sum"),
).reset_index().sort_values("sum_pnl", ascending=False)
sleeve_breakdown["sum_28d"] = sleeve_breakdown["sum_pnl"] * (28/32)
sleeve_breakdown["wr_pct"] = (sleeve_breakdown["wr"]*100).round(1)
print(sleeve_breakdown.to_string(index=False))
sleeve_breakdown.to_csv(f"{OUT}/ws_only_marginal_per_sleeve.csv", index=False)

print("\nDone.")
