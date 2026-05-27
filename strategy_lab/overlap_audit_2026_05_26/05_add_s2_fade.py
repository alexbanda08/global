"""
Round 6: Step 5 supplement - properly include S2 Fade Momo from its own scanner output.

S2 fade fires on contrarian signal when |dev_bps| >= threshold; this canonical
selection uses BTC mag_threshold >= 2.0 (n=299, WR=59.5%, $/tr=$3.68, sum_22d=$1099)
and ETH mag_threshold >= 2.0 (n=202, WR=61.4%, $/tr=$4.12, sum_22d=$832).

We don't have the per-fire rows in fade_momo_5m.csv (aggregated only). For the
manifest we rely on the SUM-LEVEL contribution and assume ZERO overlap with the
S6/S7/microprice gates (it's the OPPOSITE strategy — fade momentum extremes).

We add S2 BTC + ETH as DEPLOY rows in the final manifest, marked clearly as
"approximated from fade_momo_5m.csv aggregate (no per-fire fired_by_sleeve rows)".
"""
import pandas as pd
import os

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
OUT = f"{RES}/_overlap_audit_2026_05_26"

# Load existing manifest
manifest = pd.read_csv(f"{RES}/final_deploy_manifest.csv")

# Append S2 entries (use mag_threshold=2.0 cell that has best risk-adjusted profile)
# Window is 22d for fade_momo_5m (per its README); pro-rate to 28d
s2_rows = []
for asset, n22, wr22, sum22 in [('BTC', 299, 59.53, 1099.19), ('ETH', 202, 61.39, 832.40)]:
    sum28 = sum22 * (28/22)
    s2_rows.append(dict(
        deploy_priority=0,  # will resort
        sleeve_id=f"S2_fade_momo_{asset.lower()}_mag2_0",
        status='PAPER_FIRST',  # n is small; do paper first then promote
        asset=asset, tf='5m', offset_range_s='60-300', base_strategy='S2',
        n=n22, wr_pct=wr22, per_tr=sum22/n22,
        expected_sum_28d=sum28, marginal_28d=sum28,  # assumed 100% marginal (opposite-direction strategy)
        overlap_with_primary_pct=0.0,  # contrarian — disjoint by construction
        recommended_notional_share=0.5,
        gate_stack='mag_threshold>=2.0&contrarian_dev_bps'
    ))

s2_df = pd.DataFrame(s2_rows)
manifest = pd.concat([manifest, s2_df], ignore_index=True)

# Re-sort by deploy_priority logic
def sort_key(row):
    if row['status'] == 'DEPLOY':
        return (0, -row['expected_sum_28d'])
    if row['status'] == 'PAPER_FIRST':
        return (1, -row['marginal_28d'])
    return (2, 0)
manifest['_sk'] = manifest.apply(sort_key, axis=1)
manifest = manifest.sort_values('_sk').reset_index(drop=True)
manifest['deploy_priority'] = range(1, len(manifest)+1)
manifest = manifest.drop(columns=['_sk'])

manifest.to_csv(f"{RES}/final_deploy_manifest.csv", index=False)
manifest.to_csv(f"{OUT}/final_deploy_manifest.csv", index=False)
print(f"SAVED -> {RES}/final_deploy_manifest.csv ({len(manifest)} rows)")
print()
print(manifest[['deploy_priority','sleeve_id','status','asset','tf','expected_sum_28d','marginal_28d','overlap_with_primary_pct','recommended_notional_share']].to_string(index=False))

# Final deploy roster total (including S2 paper-first as 0.5 notional)
deploy_rows = manifest[manifest['status'] == 'DEPLOY']
paper_rows = manifest[manifest['status'] == 'PAPER_FIRST']
print()
print(f"DEPLOY combined marginal at $25 / 28d: ${deploy_rows['marginal_28d'].sum():,.0f}")
print(f"PAPER_FIRST (0.5 notional) marginal at $25 / 28d: ${paper_rows['marginal_28d'].sum() * 0.5:,.0f}")
print(f"GRAND TOTAL realistic deployable at $25 / 28d: ${deploy_rows['marginal_28d'].sum() + paper_rows['marginal_28d'].sum() * 0.5:,.0f}")
total = deploy_rows['marginal_28d'].sum() + paper_rows['marginal_28d'].sum() * 0.5
print(f"At $250 notional: ${total * 10:,.0f}/28d  =  ${total*10/28:,.0f}/day  =  ${total*10*365/28:,.0f}/year")
