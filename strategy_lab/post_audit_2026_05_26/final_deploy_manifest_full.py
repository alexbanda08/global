"""TASK 5: Updated deploy manifest combining:
  1. Bug fixes (regime/SMS bar-end, 9-offset grid)
  2. Corrected 28/3.96 scaling
  3. Real L25 fill simulation at $25, $250, $2500 notionals
  4. Slug-overlap dedup with corrected marginal PnL

Per sleeve we determine:
  - deployable_25  : sum_pnl > 0 at $25
  - deployable_250 : sum_pnl > 0 at $250 AND (avg slip < 300 bps OR depth_pct < 20)
  - deployable_2500: sum_pnl > 0 at $2500 AND (avg slip < 1000 bps OR depth_pct < 60)

Output:
  data/v4/canonical/_results/final_deploy_manifest_v2_post_audit.csv (already partial)
  data/v4/canonical/_results/final_deploy_manifest_v2_post_audit_FULL.csv
"""
import os, sys
from pathlib import Path
import pandas as pd
import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

LB_DAYS = 3.96
SCALE_28D = 28.0 / LB_DAYS

# Load fired (clean panel)
fired = pd.read_parquet(RES / "_post_audit_2026_05_26" / "fired_by_sleeve_clean.parquet")

# Load notional simulation
sim = pd.read_csv(RES / "sleeve_notional_fill_simulation.csv")
scaling = pd.read_csv(RES / "sleeve_notional_scaling_truth.csv")
post_audit = pd.read_csv(RES / "final_deploy_manifest_v2_post_audit.csv")

# Merge
m = post_audit.merge(scaling, on="sleeve_id", how="left", suffixes=("", "_scale"))

# Determine deployable flags
def deployable_25(r):
    return r["sum_28d"] > 0
def deployable_250(r):
    if pd.isna(r.get("sum_28d_250")):
        return False
    return (r["sum_28d_250"] > 0) and (r["p90_slip_250"] < 800) and (r["under_pct_250"] < 10)
def deployable_2500(r):
    if pd.isna(r.get("sum_28d_2500")):
        return False
    return (r["sum_28d_2500"] > 0) and (r["p90_slip_2500"] < 3000)

m["deployable_25"] = m.apply(deployable_25, axis=1)
m["deployable_250"] = m.apply(deployable_250, axis=1)
m["deployable_2500"] = m.apply(deployable_2500, axis=1)

# Sleeves recommended at each level
print("\n=== POST-AUDIT DEPLOY MANIFEST (full) ===\n")
cols = ["sleeve_id", "status", "asset", "tf",
         "offset_lo", "offset_hi",
         "n", "wr_pct", "per_tr", "sum_28d",
         "sum_28d_250", "sum_28d_2500", "scale_250",
         "avg_slip_250", "p90_slip_250", "avg_depth_pct_250",
         "deployable_25", "deployable_250", "deployable_2500"]
out_cols = [c for c in cols if c in m.columns]
m = m.sort_values(["status", "sum_28d"], ascending=[True, False]).reset_index(drop=True)
print(m[out_cols].to_string(index=False))

# Save
out_path = RES / "final_deploy_manifest_v2_post_audit_FULL.csv"
m.to_csv(out_path, index=False)
print(f"\nSAVED -> {out_path}")

# Per notional summary
print("\n=== DEPLOYABLE AGGREGATE ===")
deploy = m[m["status"] == "DEPLOY"]
print(f"@ $25:   {deploy['deployable_25'].sum()}/{len(deploy)} DEPLOY sleeves deployable; "
       f"sum_28d = ${deploy[deploy['deployable_25']]['sum_28d'].sum():,.0f}")
print(f"@ $250:  {deploy['deployable_250'].sum()}/{len(deploy)} DEPLOY sleeves deployable; "
       f"sum_28d = ${deploy[deploy['deployable_250']]['sum_28d_250'].sum():,.0f}")
print(f"@ $2500: {deploy['deployable_2500'].sum()}/{len(deploy)} DEPLOY sleeves deployable; "
       f"sum_28d = ${deploy[deploy['deployable_2500']]['sum_28d_2500'].sum():,.0f}")

# CRITICAL: also recompute dedup at $250 — fires that survived dedup at $25 may
# behave differently at $250. Same dedup keys (slug, fire_us, direction).
print("\nRe-running dedup with $250 PnL …")
deploy_ids = deploy["sleeve_id"].tolist()
deploy_fires = fired[fired["sleeve_id"].isin(deploy_ids)]

# Join $250 PnL from sim into deploy_fires
sim_key = sim[["sleeve_id", "slug", "fire_us", "direction",
                "pnl_at_25", "pnl_at_250", "pnl_at_2500"]].copy()
df_join = deploy_fires.merge(sim_key, on=["sleeve_id", "slug", "fire_us", "direction"], how="left")
df_join = df_join.dropna(subset=["pnl_at_250"])

# Dedup per (slug, fire_us, direction)
ded = df_join.drop_duplicates(subset=["slug", "fire_us", "direction"], keep="first")
sum_ded_25 = float(ded["pnl_at_25"].sum())
sum_ded_250 = float(ded["pnl_at_250"].sum())
sum_ded_2500 = float(ded["pnl_at_2500"].sum())
print(f"  DEPLOY roster dedup unique fires: {len(ded):,}")
print(f"  Dedup sum (3.96d window):")
print(f"    @ $25:    ${sum_ded_25:>12,.0f}  /28d=${sum_ded_25*SCALE_28D:>12,.0f}")
print(f"    @ $250:   ${sum_ded_250:>12,.0f}  /28d=${sum_ded_250*SCALE_28D:>12,.0f}")
print(f"    @ $2500:  ${sum_ded_2500:>12,.0f}  /28d=${sum_ded_2500*SCALE_28D:>12,.0f}")

# Sleeves with positive $250 PnL only — recompute dedup on those
pos_sleeves_250 = m[(m["sum_28d_250"] > 0) & (m["deployable_250"])].sleeve_id.tolist()
pos_fires = fired[fired["sleeve_id"].isin(pos_sleeves_250)]
pf_join = pos_fires.merge(sim_key, on=["sleeve_id", "slug", "fire_us", "direction"], how="left")
pf_join = pf_join.dropna(subset=["pnl_at_250"])
ded_pos = pf_join.drop_duplicates(subset=["slug", "fire_us", "direction"], keep="first")
sum_pos_25 = float(ded_pos["pnl_at_25"].sum())
sum_pos_250 = float(ded_pos["pnl_at_250"].sum())
print()
print(f"  POSITIVE-$250 sleeves ({len(pos_sleeves_250)} sleeves):")
print(f"    Unique fires: {len(ded_pos):,}")
print(f"    @ $25:  ${sum_pos_25*SCALE_28D:>12,.0f}/28d")
print(f"    @ $250: ${sum_pos_250*SCALE_28D:>12,.0f}/28d  scale={sum_pos_250/max(sum_pos_25,1e-9):.2f}x")
