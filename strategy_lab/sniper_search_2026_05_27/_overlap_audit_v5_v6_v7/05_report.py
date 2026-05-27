"""V5+V6+V7 overlap — Step 5: write OVERLAP_AUDIT_V5_V6_V7_REPORT.md."""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7"

registry = pd.read_csv(f"{OUT}/sleeve_registry.csv")
summary = pd.read_csv(f"{OUT}/sleeve_summary.csv")
pairs = pd.read_csv(f"{OUT}/pairwise_overlap_jaccard.csv")
clusters = pd.read_csv(f"{OUT}/redundancy_clusters.csv")
unrep = pd.read_csv(f"{OUT}/unreproducible_sleeves.csv") if os.path.exists(f"{OUT}/unreproducible_sleeves.csv") else pd.DataFrame()
final = pd.read_csv(f"{OUT}/final_roster.csv")
compat = pd.read_csv(f"{OUT}/deploy_compatibility.csv")

# Build sleeve_fire_matrix (wide form) - one column per sleeve
print("Building wide sleeve_fire_matrix...")
fired = pd.read_parquet(f"{OUT}/fired_by_sleeve.parquet")
# Pivot: unique (slug, fire_us, direction, offset) keys with 0/1 per sleeve
fired['fire_key'] = (fired['slug'].astype(str) + '|' +
                     fired['fire_us'].astype(str) + '|' +
                     fired['direction'].astype(str) + '|' +
                     fired['fire_offset_s'].astype(str))
wide = fired.assign(present=1).pivot_table(
    index='fire_key', columns='sleeve_id', values='present', fill_value=0, aggfunc='max'
).astype('int8')
wide.to_parquet(f"{OUT}/sleeve_fire_matrix.parquet", compression='snappy')
print(f"SAVED -> sleeve_fire_matrix.parquet  rows={len(wide):,}  cols={len(wide.columns)}")

# Stats
n_reproduced = len(summary[summary['n']>=5])
n_unreproducible = len(unrep)
raw_sum = summary[summary['n']>=5]['sum_28d_proj'].sum()
ded_sum = final['sum_28d_proj'].sum()
n_clusters = clusters['cluster_id'].nunique()
n_multi_clusters = clusters.groupby('cluster_id').filter(lambda x: len(x)>=2)['cluster_id'].nunique()

# V6 currently-in-shadow analysis
v6_shadow = compat['v6_sleeve'].tolist()
v6_safe = compat[compat['duplicate_v7_count']==0]['v6_sleeve'].tolist()
v6_dup = compat[compat['duplicate_v7_count']>0][['v6_sleeve','duplicate_v7_list']].values.tolist()

# Build top overlapping pairs table
top_pairs = pairs[pairs['sleeve_a'] != pairs['sleeve_b']].sort_values('jaccard_fire', ascending=False).head(20)

# Per-market analysis
by_market = clusters.groupby(['asset','tf','cluster_id']).agg(
    n_sleeves=('sleeve_id','count'),
    versions=('version', lambda x: list(set(x))),
).reset_index()
multi_per_mkt = by_market[by_market['n_sleeves']>=2]

# Compose report
lines = []
lines.append("# V5 + V6 + V7 Sleeve Overlap Audit Report")
lines.append("")
lines.append("**Generated:** 2026-05-27  ")
lines.append(f"**Data window:** Apr 24 – May 26, 2026 (33 days, full window v3 fires)  ")
lines.append(f"**Sleeves registered:** {len(registry)} ({len(registry[registry['version']=='V5'])} V5 + {len(registry[registry['version']=='V6'])} V6 + {len(registry[registry['version']=='V7'])} V7)  ")
lines.append(f"**Sleeves reproduced (n≥5 fires):** {n_reproduced}  ")
lines.append(f"**Sleeves unreproducible (missing gate columns):** {n_unreproducible}")
lines.append("")
lines.append("## Methodology")
lines.append("")
lines.append("1. **Panel selection per market.** For each (asset, tf), used the richest V7 panel as the gate source. V7 panels are supersets of V3/V6 gate columns:")
lines.append("   - BTC 5m: `strategy_lab/sniper_search_2026_05_27/btc_5m_v7/_sandbox/universe_v7.parquet`")
lines.append("   - BTC 15m: `data/v4/canonical/_results/sniper_btc15m_v7_gated.parquet`")
lines.append("   - ETH 5m: `data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet`")
lines.append("   - ETH 15m: `strategy_lab/sniper_search_2026_05_27/eth_15m_v7/eth_15m_enriched_v7.parquet`")
lines.append("   - SOL 5m: `strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet`")
lines.append("   - SOL 15m: `strategy_lab/sniper_search_2026_05_27/sol_15m_v7/sol_15m_v7_universe.parquet`")
lines.append("")
lines.append("2. **Gate stack application.** For each sleeve, all listed gate columns must equal 1. Offset filter then direction filter applied. PnL column `pnl_legacy_usd` (per panel, $25 stake, 2%-on-profit fee).")
lines.append("")
lines.append("3. **Pairwise overlap.** For each pair, computed:")
lines.append("   - `jaccard_fire` = |A∩B| / |A∪B| on (slug, fire_us, direction) tuples")
lines.append("   - `jaccard_slug` = |slugs(A)∩slugs(B)| / |slugs(A)∪slugs(B)|")
lines.append("   - `cov_smaller` = |A∩B| / min(|A|, |B|) — how much of the smaller sleeve is contained in the larger one")
lines.append("")
lines.append("4. **Redundancy classification.** A pair is REDUNDANT if `jaccard_fire >= 0.50` OR `cov_smaller >= 0.85`. Connected components form clusters. Within each cluster, the kept sleeve maximizes `sum_28d_proj + 100 * dpt_usd`.")
lines.append("")
lines.append("5. **Caveat — pnl scale.** The legacy fee on a $25 stake at vwap=0.6 winning leg pays ~$8 net; at vwap=0.05 (lottery-long) the same $25 stake returns ~$1163 if won. PnL totals here include those outlier wins. They are real backtest outcomes but should be treated cautiously for sizing decisions.")
lines.append("")
lines.append("## 0. Summary")
lines.append("")
lines.append(f"- **{n_clusters} clusters** identified across {n_reproduced} sleeves ({n_multi_clusters} clusters with ≥2 sleeves are redundant).")
lines.append(f"- **{len(final)} kept sleeves** after dedup (down from {n_reproduced}).")
lines.append(f"- **28d const-$25 PnL projection:**")
lines.append(f"    - Raw sum (no dedup): **${raw_sum:,.0f}**")
lines.append(f"    - Deduped sum: **${ded_sum:,.0f}**")
lines.append(f"    - Reduction from dedup: **${raw_sum-ded_sum:,.0f} ({(raw_sum-ded_sum)/raw_sum*100:.1f}%)**")
lines.append("")
lines.append("Per-version contribution to deduped 28d PnL:")
v_sums = final.groupby('version')['sum_28d_proj'].sum().sort_values(ascending=False)
for v, s in v_sums.items():
    lines.append(f"- **{v}**: ${s:,.0f}")
lines.append("")
lines.append("## 1. Top 20 highest-overlap pairs (FIRE-level Jaccard)")
lines.append("")
lines.append("| # | Sleeve A | Sleeve B | n_a | n_b | Jaccard_fire | cov_smaller | inter |")
lines.append("|---|----------|----------|----:|----:|-------------:|------------:|------:|")
for i, r in top_pairs.iterrows():
    rank = top_pairs.index.get_loc(i) + 1
    lines.append(f"| {rank} | {r['sleeve_a']} | {r['sleeve_b']} | {int(r['n_a'])} | {int(r['n_b'])} | {r['jaccard_fire']:.3f} | {r['cov_smaller']:.3f} | {int(r['inter_fires'])} |")
lines.append("")
lines.append("**Top 3 most overlapping pairs across versions:**")
for i in range(3):
    r = top_pairs.iloc[i]
    lines.append(f"{i+1}. `{r['sleeve_a']}` ↔ `{r['sleeve_b']}` — J_fire={r['jaccard_fire']:.3f}, cov_smaller={r['cov_smaller']:.3f}")
lines.append("")

lines.append("## 2. Redundancy clusters (size ≥ 2)")
lines.append("")
multi = clusters.groupby('cluster_id').filter(lambda x: len(x) >= 2)
for ci in sorted(multi['cluster_id'].unique()):
    cl_rows = multi[multi['cluster_id']==ci].sort_values('rank_in_cluster')
    keeper = cl_rows[cl_rows['kept']==1].iloc[0]
    market = f"{keeper['asset']} {keeper['tf']}"
    lines.append(f"### Cluster {ci} — {market} ({len(cl_rows)} sleeves)")
    lines.append(f"**KEEP**: `{keeper['sleeve_id']}` ({keeper['version']}, n={int(keeper['n'])}, WR={keeper['wr_pct']:.1f}%, $/tr=${keeper['dpt_usd']:.2f}, 28d=${keeper['sum_28d_proj']:.0f})")
    lines.append("")
    lines.append("| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |")
    lines.append("|-------|---------|-----------|--:|----:|-----:|---------:|")
    for _, r in cl_rows.iterrows():
        flag = "**KEEP**" if r['kept']==1 else "drop"
        lines.append(f"| {flag} | {r['version']} | `{r['sleeve_id']}` | {int(r['n'])} | {r['wr_pct']:.1f} | ${r['dpt_usd']:.2f} | ${r['sum_28d_proj']:.0f} |")
    lines.append("")

lines.append("## 3. Per-market overlap summary")
lines.append("")
lines.append("| Market | Total sleeves | Clusters | Multi-sleeve clusters | Singletons | After-dedup count |")
lines.append("|--------|--------------:|---------:|----------------------:|-----------:|------------------:|")
for (a, tf), grp in clusters.groupby(['asset','tf']):
    n_total = len(grp)
    cls = grp.groupby('cluster_id').size()
    n_cls = len(cls)
    n_multi = (cls >= 2).sum()
    n_single = (cls == 1).sum()
    n_kept = grp[grp['kept']==1]['sleeve_id'].nunique()
    lines.append(f"| {a} {tf} | {n_total} | {n_cls} | {n_multi} | {n_single} | {n_kept} |")
lines.append("")

lines.append("## 4. V6 in-shadow compatibility analysis")
lines.append("")
lines.append("For each V6 sleeve currently in shadow deploy, the table lists how many V7 sleeves would DUPLICATE (jaccard≥0.5 or cov≥0.85), partially overlap (0.30 ≤ J < 0.50), or be COMPATIBLE (J < 0.30) on the same market.")
lines.append("")
lines.append("| V6 sleeve | market | n | 28d proj | duplicates_v7 | partials_v7 | compatible_v7 |")
lines.append("|-----------|--------|--:|---------:|--------------:|------------:|--------------:|")
for _, r in compat.iterrows():
    lines.append(f"| `{r['v6_sleeve']}` | {r['v6_asset']} {r['v6_tf']} | {int(r['v6_n'])} | ${r['v6_28d']:.0f} | {int(r['duplicate_v7_count'])} | {int(r['partial_v7_count'])} | {int(r['compatible_v7_count'])} |")
lines.append("")

lines.append("### V6 sleeves SAFE to keep alongside V7 additions (no V7 duplicates)")
lines.append("")
safe = compat[compat['duplicate_v7_count']==0]
for _, r in safe.iterrows():
    lines.append(f"- `{r['v6_sleeve']}` ({r['v6_asset']} {r['v6_tf']}, n={int(r['v6_n'])}, 28d=${r['v6_28d']:.0f})")
lines.append("")

lines.append("### V6 sleeves with V7 DUPLICATES (must coordinate to avoid double-counting)")
lines.append("")
dup = compat[compat['duplicate_v7_count']>0]
for _, r in dup.iterrows():
    lines.append(f"- `{r['v6_sleeve']}` ({r['v6_asset']} {r['v6_tf']}, n={int(r['v6_n'])}, 28d=${r['v6_28d']:.0f})")
    for d in r['duplicate_v7_list'].split(';'):
        lines.append(f"    - DUPLICATE: {d}")
lines.append("")

lines.append("## 5. V7 sleeves that are REDUNDANT with already-shadowed V6")
lines.append("")
# For each V7 sleeve, check if it's in a cluster with any V6 in-shadow
v6_in_shadow = set(compat['v6_sleeve'].tolist())
v7_redundant = []
for ci in clusters['cluster_id'].unique():
    cl = clusters[clusters['cluster_id']==ci]
    has_v6 = (cl['sleeve_id'].isin(v6_in_shadow)).any()
    if has_v6 and len(cl) >= 2:
        v7_in_cluster = cl[cl['version']=='V7']['sleeve_id'].tolist()
        v6_in_cluster = cl[(cl['version']=='V6') & cl['sleeve_id'].isin(v6_in_shadow)]['sleeve_id'].tolist()
        for v7 in v7_in_cluster:
            v7_redundant.append((v7, v6_in_cluster))
for v7, v6list in v7_redundant:
    lines.append(f"- `{v7}` — duplicates {', '.join(['`'+v+'`' for v in v6list])}")
lines.append("")
lines.append(f"**Total V7 sleeves redundant with shadowed V6: {len(v7_redundant)}**")
lines.append("")

lines.append("## 6. Recommended final roster (after dedup)")
lines.append("")
lines.append(f"Total kept sleeves: **{len(final)}**  ")
lines.append(f"Combined 28d const-$25 PnL: **${ded_sum:,.0f}**")
lines.append("")
lines.append("Per-version count:")
v_counts = final.groupby('version').size()
for v, c in v_counts.items():
    lines.append(f"- {v}: {c} sleeves")
lines.append("")
lines.append("Full final roster (sorted by version+market+sleeve):")
lines.append("")
lines.append("| version | sleeve_id | asset | tf | n | WR% | $/tr | 28d proj |")
lines.append("|---------|-----------|-------|----|--:|----:|-----:|---------:|")
for _, r in final.iterrows():
    lines.append(f"| {r['version']} | `{r['sleeve_id']}` | {r['asset']} | {r['tf']} | {int(r['n'])} | {r['wr_pct']:.1f} | ${r['dpt_usd']:.2f} | ${r['sum_28d_proj']:.0f} |")
lines.append("")

lines.append("## 7. Unreproducible sleeves (excluded from audit)")
lines.append("")
if len(unrep) > 0:
    for _, r in unrep.iterrows():
        lines.append(f"- `{r['sleeve_id']}` — {r['reason']}")
else:
    lines.append("None.")
lines.append("")

lines.append("## 8. Output files")
lines.append("")
lines.append(f"- `sleeve_registry.csv` — all {len(registry)} sleeves defined")
lines.append(f"- `sleeve_summary.csv` — per-sleeve aggregate (n, WR, $/tr, 28d proj)")
lines.append(f"- `fired_by_sleeve.parquet` — per-fire records ({len(fired):,} fires)")
lines.append(f"- `sleeve_fire_matrix.parquet` — wide matrix (rows = unique fires, cols = sleeves)")
lines.append(f"- `pairwise_overlap_jaccard.csv` — long-form pairwise overlap ({len(pairs)} pairs)")
lines.append(f"- `pairwise_jaccard_fire.csv` — NxN wide matrix")
lines.append(f"- `pairwise_jaccard_slug.csv` — NxN wide matrix")
lines.append(f"- `heatmap_jaccard_fire.png` / `heatmap_jaccard_slug.png` — visual heatmaps")
lines.append(f"- `redundancy_clusters.csv` — cluster assignments + kept/dropped flag")
lines.append(f"- `deploy_compatibility.csv` — V6-in-shadow compatibility analysis")
lines.append(f"- `final_roster.csv` — recommended deploy roster ({len(final)} sleeves)")
lines.append(f"- `unreproducible_sleeves.csv` — sleeves excluded from audit ({len(unrep)} sleeves)")
lines.append("")
lines.append("---")
lines.append("END OF REPORT")

report = "\n".join(lines)
with open(f"{OUT}/OVERLAP_AUDIT_V5_V6_V7_REPORT.md", "w", encoding="utf-8") as f:
    f.write(report)
print(f"SAVED -> OVERLAP_AUDIT_V5_V6_V7_REPORT.md ({len(lines)} lines)")
