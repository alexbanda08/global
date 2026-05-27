"""V5+V6+V7 overlap — Step 3: pairwise Jaccard matrix at FIRE level and SLUG level.

Outputs:
  - pairwise_overlap_jaccard.csv (long form: a, b, jaccard_fire, jaccard_slug, inter_n, union_n)
  - pairwise_jaccard_fire.csv  (NxN wide)
  - pairwise_jaccard_slug.csv  (NxN wide)
  - heatmap_jaccard_fire.png
  - heatmap_jaccard_slug.png
"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7"

fired = pd.read_parquet(f"{OUT}/fired_by_sleeve.parquet")
summary = pd.read_csv(f"{OUT}/sleeve_summary.csv")

# Only consider sleeves with n >= 5 (otherwise overlap math is unstable)
sleeves_with_fires = summary[summary['n'] >= 5]['sleeve_id'].tolist()
print(f"Computing pairwise overlap for {len(sleeves_with_fires)} sleeves with n>=5 fires...")

# Build fire-key sets and slug sets per sleeve
fire_sets = {}
slug_sets = {}
for sid in sleeves_with_fires:
    sub = fired[fired['sleeve_id'] == sid]
    if sub.empty:
        fire_sets[sid] = set()
        slug_sets[sid] = set()
        continue
    fire_sets[sid] = set(zip(sub['slug'].astype(str), sub['fire_us'].astype('int64'), sub['direction'].astype(str)))
    slug_sets[sid] = set(sub['slug'].astype(str).unique())

# Pairwise long form
rows = []
N = len(sleeves_with_fires)
for i, a in enumerate(sleeves_with_fires):
    for j, b in enumerate(sleeves_with_fires):
        if i > j:
            continue
        fa, fb = fire_sets[a], fire_sets[b]
        sa, sb = slug_sets[a], slug_sets[b]
        inter_f = len(fa & fb)
        union_f = len(fa | fb)
        inter_s = len(sa & sb)
        union_s = len(sa | sb)
        jacc_f = inter_f / union_f if union_f else 0.0
        jacc_s = inter_s / union_s if union_s else 0.0
        # Also smallest-set-coverage ratio (overlap as % of smaller sleeve)
        cov_smaller = inter_f / min(len(fa), len(fb)) if min(len(fa), len(fb)) else 0.0
        rows.append(dict(
            sleeve_a=a, sleeve_b=b,
            n_a=len(fa), n_b=len(fb),
            jaccard_fire=jacc_f, jaccard_slug=jacc_s,
            inter_fires=inter_f, union_fires=union_f,
            inter_slugs=inter_s, union_slugs=union_s,
            cov_smaller=cov_smaller,
        ))

pairs = pd.DataFrame(rows)
pairs.to_csv(f"{OUT}/pairwise_overlap_jaccard.csv", index=False)
print(f"SAVED -> pairwise_overlap_jaccard.csv ({len(pairs)} pairs)")

# Wide NxN matrices
mat_fire = np.zeros((N, N))
mat_slug = np.zeros((N, N))
for _, r in pairs.iterrows():
    i = sleeves_with_fires.index(r['sleeve_a'])
    j = sleeves_with_fires.index(r['sleeve_b'])
    mat_fire[i, j] = mat_fire[j, i] = r['jaccard_fire']
    mat_slug[i, j] = mat_slug[j, i] = r['jaccard_slug']

pd.DataFrame(mat_fire, index=sleeves_with_fires, columns=sleeves_with_fires).to_csv(f"{OUT}/pairwise_jaccard_fire.csv")
pd.DataFrame(mat_slug, index=sleeves_with_fires, columns=sleeves_with_fires).to_csv(f"{OUT}/pairwise_jaccard_slug.csv")
print(f"SAVED -> pairwise_jaccard_fire.csv + pairwise_jaccard_slug.csv")

# Heatmaps
def heatmap(mat, sleeves, title, path):
    fig, ax = plt.subplots(figsize=(max(12, len(sleeves)*0.35), max(10, len(sleeves)*0.3)))
    im = ax.imshow(mat, cmap='RdYlGn_r', vmin=0, vmax=1)
    ax.set_xticks(range(len(sleeves)))
    ax.set_yticks(range(len(sleeves)))
    ax.set_xticklabels(sleeves, rotation=90, fontsize=6)
    ax.set_yticklabels(sleeves, fontsize=6)
    for i in range(len(sleeves)):
        for j in range(len(sleeves)):
            v = mat[i, j]
            if v >= 0.30 and i != j:
                ax.text(j, i, f"{v:.2f}", ha='center', va='center', fontsize=4,
                        color='white' if v > 0.5 else 'black')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label='Jaccard')
    plt.title(title, fontsize=12)
    plt.tight_layout()
    plt.savefig(path, dpi=110, bbox_inches='tight')
    plt.close()

heatmap(mat_fire, sleeves_with_fires, 'V5+V6+V7 Pairwise Jaccard — FIRE level (slug+fire_us+direction)',
        f"{OUT}/heatmap_jaccard_fire.png")
heatmap(mat_slug, sleeves_with_fires, 'V5+V6+V7 Pairwise Jaccard — SLUG level',
        f"{OUT}/heatmap_jaccard_slug.png")
print("SAVED -> heatmap PNGs")

# Top overlapping pairs (non-self) across versions
top = pairs[pairs['sleeve_a'] != pairs['sleeve_b']].copy()
top = top.sort_values('jaccard_fire', ascending=False)

print("\n=== TOP 30 OVERLAPPING PAIRS (fire-level Jaccard) ===")
print(top.head(30)[['sleeve_a','sleeve_b','n_a','n_b','jaccard_fire','jaccard_slug','inter_fires','cov_smaller']].to_string(index=False))
