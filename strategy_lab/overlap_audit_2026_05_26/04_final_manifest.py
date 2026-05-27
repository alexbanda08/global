"""
Round 6: Step 6+7 - Build final deploy manifest + write report.

This builds the deploy-ready CSV that the operator will USE for going live.

Key columns:
  sleeve_id, deploy_priority, expected_sum_28d, overlap_with_primary_portfolio_pct,
  recommended_notional_share, gate_stack, base_strategy, asset, tf, offset_range_s,
  status (DEPLOY / PAPER_FIRST / SKIP_OVERLAP)
"""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
RES = f"{ROOT}/data/v4/canonical/_results"
OUT = f"{RES}/_overlap_audit_2026_05_26"

fired = pd.read_parquet(f"{OUT}/fired_by_sleeve.parquet")
summary = pd.read_csv(f"{OUT}/sleeve_summary.csv")
pairs   = pd.read_csv(f"{OUT}/pairwise_overlap_matrix.csv")
primary = pd.read_csv(f"{OUT}/primary_portfolio_greedy.csv")

# Compute INCREMENTAL contribution for each sleeve when added to the primary portfolio
# This is the only honest measure of "how much $/28d does sleeve X add?"
primary_ids = primary['sleeve_id'].tolist()
primary_fires = fired[fired['sleeve_id'].isin(primary_ids)]
primary_fire_set = set(zip(primary_fires['slug'], primary_fires['fire_us'].astype('int64'), primary_fires['direction']))

# For NON-primary sleeves, compute marginal pnl
marginal_rows = []
for sid in summary['sleeve_id']:
    sub = fired[fired['sleeve_id'] == sid]
    if sub.empty:
        marginal_rows.append(dict(sleeve_id=sid, marginal_n=0, marginal_28d=0, in_primary=sid in primary_ids))
        continue
    if sid in primary_ids:
        # marginal = its own UNIQUE contribution to the primary set
        # = fires of sid that no OTHER primary sleeve covers
        others = [s for s in primary_ids if s != sid]
        other_fires = set(zip(
            fired[fired['sleeve_id'].isin(others)]['slug'],
            fired[fired['sleeve_id'].isin(others)]['fire_us'].astype('int64'),
            fired[fired['sleeve_id'].isin(others)]['direction']
        ))
        sub_fires = list(zip(sub['slug'], sub['fire_us'].astype('int64'), sub['direction']))
        idx_unique = [i for i, k in enumerate(sub_fires) if k not in other_fires]
        marg_df = sub.iloc[idx_unique]
        # AUDIT-FIX 2026-05-26 (Bug #4): fired_by_sleeve.parquet covers ONLY 3.96d
        # (May 21 20:06 - May 25 19:13), not 32d. Previous code used (28/32) = 0.875
        # which UNDER-stated /28d by 8.07x. Correct scaling = 28/3.96.
        marg_28d = marg_df['pnl_legacy_usd'].sum() * (28/3.96)
        marg_n = len(marg_df)
        marginal_rows.append(dict(sleeve_id=sid, marginal_n=marg_n, marginal_28d=marg_28d, in_primary=True))
    else:
        # marginal = fires NOT in primary set
        sub_fires = list(zip(sub['slug'], sub['fire_us'].astype('int64'), sub['direction']))
        idx_outside = [i for i, k in enumerate(sub_fires) if k not in primary_fire_set]
        marg_df = sub.iloc[idx_outside]
        # AUDIT-FIX 2026-05-26 (Bug #4): fired_by_sleeve.parquet covers ONLY 3.96d
        # (May 21 20:06 - May 25 19:13), not 32d. Previous code used (28/32) = 0.875
        # which UNDER-stated /28d by 8.07x. Correct scaling = 28/3.96.
        marg_28d = marg_df['pnl_legacy_usd'].sum() * (28/3.96)
        marg_n = len(marg_df)
        marginal_rows.append(dict(sleeve_id=sid, marginal_n=marg_n, marginal_28d=marg_28d, in_primary=False))

marginal_df = pd.DataFrame(marginal_rows)

# Merge with summary + sleeve metadata
manifest = summary.merge(marginal_df, on='sleeve_id', how='left')

# Add gate stack from registry
sleeve_meta = fired.groupby('sleeve_id').agg(
    gate_stack=('sleeve_id', lambda x: fired.loc[x.index, 'sleeve_id'].iloc[0]),
).reset_index()
# Pull gate stack string from fired data
gate_stack_map = fired.groupby('sleeve_id')['sleeve_id'].first().to_dict()
# Actually use the recorded gate_stack_str
gate_stacks = fired.groupby('sleeve_id').apply(
    lambda g: g['sleeve_id'].iloc[0] if 'gate_stack_str' not in g.columns else 'PRESENT',
    include_groups=False
).to_dict() if False else {}

# Get gate stack from fired directly
gate_stacks = {}
for sid, grp in fired.groupby('sleeve_id'):
    if 'gate_stack_str' in fired.columns:
        gate_stacks[sid] = grp['gate_stack_str'].iloc[0] if len(grp) else ''
    else:
        gate_stacks[sid] = ''
    # base
manifest['gate_stack'] = manifest['sleeve_id'].map(gate_stacks)

# Compute overlap_pct_self vs primary (excluding primary sleeves themselves which = 100%)
overlap_rows = []
for sid in summary['sleeve_id']:
    sub = fired[fired['sleeve_id'] == sid]
    if sub.empty:
        overlap_rows.append((sid, 0))
        continue
    sub_fires = set(zip(sub['slug'], sub['fire_us'].astype('int64'), sub['direction']))
    primary_excluding_self = primary_fires[primary_fires['sleeve_id'] != sid]
    pri_set = set(zip(primary_excluding_self['slug'], primary_excluding_self['fire_us'].astype('int64'), primary_excluding_self['direction']))
    if len(sub_fires) == 0:
        op = 0
    else:
        op = len(sub_fires & pri_set) / len(sub_fires) * 100
    overlap_rows.append((sid, op))
ov_df = pd.DataFrame(overlap_rows, columns=['sleeve_id','overlap_with_primary_pct'])
manifest = manifest.merge(ov_df, on='sleeve_id', how='left')

# Build status
def status_for(row):
    sid = row['sleeve_id']
    if row['sum_pnl_28d'] <= 0:
        return 'SKIP_NEGATIVE_PNL'
    if sid in primary_ids:
        return 'DEPLOY'
    # not in primary
    if row['marginal_28d'] > 50:
        return 'PAPER_FIRST'  # adds meaningful unique fires
    return 'SKIP_OVERLAP'

manifest['status'] = manifest.apply(status_for, axis=1)

# Recommended notional share:
#   - DEPLOY: 1.0 of $25 per fire (deploy at standalone notional)
#   - PAPER_FIRST: 0.5 (half-size while paper-validating)
#   - SKIP: 0
def notional_share(s):
    return {'DEPLOY': 1.0, 'PAPER_FIRST': 0.5, 'SKIP_OVERLAP': 0.0, 'SKIP_NEGATIVE_PNL': 0.0}.get(s, 0)
manifest['recommended_notional_share'] = manifest['status'].apply(notional_share)

# Deploy priority — order DEPLOY by sum_pnl_28d desc, then PAPER_FIRST by marginal_28d desc
manifest['_sort_key'] = manifest.apply(
    lambda r: (
        0 if r['status'] == 'DEPLOY' else (1 if r['status'] == 'PAPER_FIRST' else 2),
        -r['sum_pnl_28d'] if r['status'] == 'DEPLOY' else (-r['marginal_28d'] if r['status'] == 'PAPER_FIRST' else 0)
    ), axis=1
)
manifest = manifest.sort_values('_sort_key').reset_index(drop=True)
manifest['deploy_priority'] = range(1, len(manifest)+1)

# Columns
manifest = manifest.rename(columns={
    'sum_pnl_28d': 'expected_sum_28d',
    'asset': 'asset',
    'tf': 'tf',
})
manifest['offset_range_s'] = manifest['offset_lo'].astype(str) + '-' + manifest['offset_hi'].astype(str)
manifest['base_strategy'] = manifest['sleeve_id'].str.split('_').str[0]

final_cols = [
    'deploy_priority','sleeve_id','status','asset','tf','offset_range_s','base_strategy',
    'n','wr_pct','per_tr','expected_sum_28d','marginal_28d','overlap_with_primary_pct',
    'recommended_notional_share','gate_stack',
]
final = manifest[final_cols].copy()

out_path = f"{RES}/final_deploy_manifest.csv"
final.to_csv(out_path, index=False)
print(f"SAVED -> {out_path}")
print(final.to_string(index=False))

# Also save inside audit folder for ease
final.to_csv(f"{OUT}/final_deploy_manifest.csv", index=False)

# Compute deploy roster combined - just DEPLOY rows
deploy_set = set(final[final['status'] == 'DEPLOY']['sleeve_id'])
deploy_fires = fired[fired['sleeve_id'].isin(deploy_set)].drop_duplicates(subset=['slug','fire_us','direction'])
deploy_sum = deploy_fires['pnl_legacy_usd'].sum()
# AUDIT-FIX 2026-05-26 (Bug #4): scale by 28/3.96 (actual fired panel window)
deploy_28d = deploy_sum * (28/3.96)
print(f"\n=== FINAL DEPLOY ROSTER ===")
print(f"Status: DEPLOY = {len(deploy_set)} sleeves")
print(f"Combined unique fires: {len(deploy_fires):,}")
print(f"Combined PnL 32d: ${deploy_sum:,.0f}")
print(f"Combined PnL 28d: ${deploy_28d:,.0f}")
print(f"At $250 notional: ${deploy_28d*10:,.0f}/28d  =  ${deploy_28d*10/28:,.0f}/day  =  ${deploy_28d*10*13:,.0f}/yr")

# Paper first roster
paper_set = set(final[final['status'] == 'PAPER_FIRST']['sleeve_id'])
print(f"\nPaper-first: {len(paper_set)} sleeves")
for sid in paper_set:
    row = final[final['sleeve_id'] == sid].iloc[0]
    print(f"  {sid:50s}  marginal_28d=${row['marginal_28d']:.0f}  overlap={row['overlap_with_primary_pct']:.0f}%")
