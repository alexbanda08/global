"""V5+V6+V7 overlap — Step 4: redundancy clusters + deploy recommendations.

Methodology:
- A pair is REDUNDANT if jaccard_fire >= 0.50 OR cov_smaller >= 0.85
- Cluster sleeves transitively via the redundancy graph (connected components)
- Within each cluster, keep the sleeve with highest dpt_usd ($/tr) — secondary key sum_pnl
- Sleeves not in any cluster are kept individually

Outputs:
  - redundancy_clusters.csv  (cluster_id, sleeve_id, version, dpt_usd, kept_flag)
  - deploy_compatibility.csv (per V6 in-shadow sleeve: compatible / duplicate V7 sleeves)
  - final_roster.csv         (recommended final roster)
  - PnL projection summary printed
"""
import os
import pandas as pd
import numpy as np
from collections import defaultdict

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7"

pairs = pd.read_csv(f"{OUT}/pairwise_overlap_jaccard.csv")
summary = pd.read_csv(f"{OUT}/sleeve_summary.csv")

# Build summary lookup
sumlook = summary.set_index('sleeve_id').to_dict(orient='index')

REDUNDANT_J_THR = 0.50
REDUNDANT_COV_THR = 0.85
COMPATIBLE_J_THR = 0.30

# Build redundancy graph
adj = defaultdict(set)
for _, r in pairs.iterrows():
    if r['sleeve_a'] == r['sleeve_b']:
        continue
    if r['jaccard_fire'] >= REDUNDANT_J_THR or r['cov_smaller'] >= REDUNDANT_COV_THR:
        adj[r['sleeve_a']].add(r['sleeve_b'])
        adj[r['sleeve_b']].add(r['sleeve_a'])

# Connected components (union-find)
visited = set()
clusters = []
all_sleeves = summary[summary['n'] >= 5]['sleeve_id'].tolist()

def dfs(node, cluster):
    stack = [node]
    while stack:
        n = stack.pop()
        if n in visited:
            continue
        visited.add(n)
        cluster.add(n)
        for nb in adj.get(n, []):
            if nb not in visited:
                stack.append(nb)

for s in all_sleeves:
    if s not in visited:
        cluster = set()
        dfs(s, cluster)
        clusters.append(cluster)

print(f"Built {len(clusters)} clusters from {len(all_sleeves)} sleeves.")

# Within each cluster, keep the sleeve with highest dpt_usd
cluster_rows = []
keep_set = set()
for ci, cluster in enumerate(clusters):
    if not cluster:
        continue
    # Rank by dpt then sum_pnl
    rows = []
    for sid in cluster:
        meta = sumlook.get(sid, {})
        rows.append((sid, meta.get('version','?'), meta.get('asset','?'), meta.get('tf','?'),
                     meta.get('n', 0), meta.get('wr_pct', np.nan),
                     meta.get('dpt_usd', np.nan), meta.get('sum_pnl_usd', np.nan),
                     meta.get('sum_28d_proj', np.nan)))
    rows_df = pd.DataFrame(rows, columns=['sleeve_id','version','asset','tf','n','wr_pct','dpt_usd','sum_pnl_usd','sum_28d_proj'])
    # Tier-breaker: highest sum_28d_proj  (use $/tr * n)
    rows_df['score'] = rows_df['sum_28d_proj'].fillna(0) + rows_df['dpt_usd'].fillna(0) * 100  # weighted
    rows_df = rows_df.sort_values('score', ascending=False).reset_index(drop=True)
    keeper = rows_df.iloc[0]['sleeve_id']
    keep_set.add(keeper)
    for _, r in rows_df.iterrows():
        cluster_rows.append(dict(
            cluster_id=ci,
            cluster_size=len(cluster),
            sleeve_id=r['sleeve_id'],
            version=r['version'],
            asset=r['asset'],
            tf=r['tf'],
            n=r['n'],
            wr_pct=r['wr_pct'],
            dpt_usd=r['dpt_usd'],
            sum_pnl_usd=r['sum_pnl_usd'],
            sum_28d_proj=r['sum_28d_proj'],
            kept=int(r['sleeve_id'] == keeper),
            rank_in_cluster=int(_ + 1),
        ))

cdf = pd.DataFrame(cluster_rows).sort_values(['cluster_size','cluster_id','kept'], ascending=[False, True, False])
cdf.to_csv(f"{OUT}/redundancy_clusters.csv", index=False)
print(f"SAVED -> redundancy_clusters.csv ({len(cdf)} sleeve-in-cluster rows)")

# Print multi-sleeve clusters
print("\n=== CLUSTERS WITH >=2 SLEEVES (redundant) ===")
multi = cdf.groupby('cluster_id').filter(lambda x: len(x) >= 2)
for ci in sorted(multi['cluster_id'].unique()):
    rows = multi[multi['cluster_id'] == ci].sort_values('rank_in_cluster')
    versions = rows['version'].tolist()
    keeper = rows[rows['kept']==1].iloc[0]
    print(f"\nCluster {ci} (size={len(rows)}, versions={set(versions)}, KEEP={keeper['sleeve_id']} [{keeper['version']}, n={int(keeper['n'])}, dpt=${keeper['dpt_usd']:.2f}, 28d=${keeper['sum_28d_proj']:.0f}]):")
    for _, r in rows.iterrows():
        flag = "  KEEP" if r['kept']==1 else "  drop"
        print(f"  {flag}  [{r['version']}]  {r['sleeve_id']}  n={int(r['n']):4d}  WR={r['wr_pct']:5.1f}%  dpt=${r['dpt_usd']:6.2f}  sum_28d=${r['sum_28d_proj']:7.0f}")

# -------- Final roster --------
print("\n=== FINAL ROSTER (kept sleeves) ===")
final = summary[summary['sleeve_id'].isin(keep_set)].sort_values(['version','asset','tf','sleeve_id'])
final.to_csv(f"{OUT}/final_roster.csv", index=False)
print(f"SAVED -> final_roster.csv ({len(final)} sleeves)")
print(final[['version','sleeve_id','asset','tf','n','wr_pct','dpt_usd','sum_pnl_usd','sum_28d_proj']].to_string(index=False))

# Raw sum vs dedup sum
raw_sum = summary[summary['n']>=5]['sum_28d_proj'].sum()
ded_sum = final['sum_28d_proj'].sum()
print(f"\n=== PnL projection (28d const $25) ===")
print(f"Raw sum across all reproducible sleeves ({len(summary[summary['n']>=5])}): ${raw_sum:,.0f}")
print(f"Deduped sum (kept {len(final)} sleeves):                 ${ded_sum:,.0f}")
print(f"Overlap reduction:                                       ${raw_sum-ded_sum:,.0f}  ({(raw_sum-ded_sum)/raw_sum*100 if raw_sum else 0:.1f}%)")

# Per-version sums
print("\nPer-version 28d projection (deduped roster):")
print(final.groupby('version')[['sum_28d_proj']].sum().to_string())

# -------- Deploy compatibility matrix --------
# For each V6 currently-in-shadow sleeve, find:
#   - DUPLICATE V7 sleeves (jaccard_fire >= 0.50)
#   - COMPATIBLE V7 sleeves (jaccard_fire < 0.30)
#   - PARTIAL overlap V7 sleeves (0.30 <= jaccard_fire < 0.50)
v6_shadow = summary[(summary['version']=='V6') & (summary['n']>=5)]['sleeve_id'].tolist()
v7_all = summary[(summary['version']=='V7') & (summary['n']>=5)]['sleeve_id'].tolist()

compat_rows = []
for v6 in v6_shadow:
    v6_meta = sumlook.get(v6, {})
    dups = []
    partials = []
    compats = []
    for v7 in v7_all:
        v7_meta = sumlook.get(v7, {})
        # Different markets cannot overlap (different slugs entirely)
        if v6_meta.get('asset') != v7_meta.get('asset') or v6_meta.get('tf') != v7_meta.get('tf'):
            continue
        pair = pairs[((pairs['sleeve_a']==v6) & (pairs['sleeve_b']==v7)) | ((pairs['sleeve_a']==v7) & (pairs['sleeve_b']==v6))]
        if pair.empty:
            continue
        j = float(pair.iloc[0]['jaccard_fire'])
        cov = float(pair.iloc[0]['cov_smaller'])
        if j >= REDUNDANT_J_THR or cov >= REDUNDANT_COV_THR:
            dups.append(f"{v7} (J={j:.2f}, cov={cov:.2f})")
        elif j < COMPATIBLE_J_THR:
            compats.append(f"{v7} (J={j:.2f})")
        else:
            partials.append(f"{v7} (J={j:.2f}, cov={cov:.2f})")
    compat_rows.append(dict(
        v6_sleeve=v6,
        v6_asset=v6_meta.get('asset','?'),
        v6_tf=v6_meta.get('tf','?'),
        v6_n=v6_meta.get('n', 0),
        v6_dpt=v6_meta.get('dpt_usd', np.nan),
        v6_28d=v6_meta.get('sum_28d_proj', np.nan),
        duplicate_v7_count=len(dups),
        duplicate_v7_list=";".join(dups) if dups else "(none)",
        partial_v7_count=len(partials),
        partial_v7_list=";".join(partials) if partials else "(none)",
        compatible_v7_count=len(compats),
        compatible_v7_list=";".join(compats) if compats else "(none)",
    ))

cmp_df = pd.DataFrame(compat_rows)
cmp_df.to_csv(f"{OUT}/deploy_compatibility.csv", index=False)
print(f"\nSAVED -> deploy_compatibility.csv ({len(cmp_df)} V6 sleeves analyzed)")
print(cmp_df[['v6_sleeve','v6_asset','v6_tf','duplicate_v7_count','partial_v7_count','compatible_v7_count']].to_string(index=False))
