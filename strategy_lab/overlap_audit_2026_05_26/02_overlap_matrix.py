"""
Round 6: Step 2 - Pairwise slug-overlap matrix.

For each pair of sleeves (A, B), compute:
  - Jaccard at FIRE level: |fires_A ∩ fires_B| / |fires_A ∪ fires_B|
       fire-key = (slug, fire_us, direction)
  - Jaccard at SLUG level: |slugs_A ∩ slugs_B| / |slugs_A ∪ slugs_B|
  - Direction agreement on overlapping slugs
  - Co-occurrence count

Output:
  - pairwise_overlap_matrix.csv  (sleeve_a, sleeve_b, jaccard_fire, jaccard_slug,
                                  inter_n, union_n, dir_agree_pct)
  - pairwise_jaccard_fire.csv    (NxN matrix)
  - pairwise_jaccard_slug.csv    (NxN matrix)
  - heatmap PNGs

"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/data/v4/canonical/_results/_overlap_audit_2026_05_26"

fired = pd.read_parquet(f"{OUT}/fired_by_sleeve.parquet")
summary = pd.read_csv(f"{OUT}/sleeve_summary.csv")

sleeves = summary['sleeve_id'].tolist()
print(f"Computing overlap for {len(sleeves)} sleeves...")

# Build sets per sleeve
fire_sets = {}
slug_sets = {}
dir_dict = {}  # (sid -> {slug: set(directions)})
for sid in sleeves:
    sub = fired[fired['sleeve_id'] == sid]
    fire_sets[sid] = set(zip(sub['slug'], sub['fire_us'].astype('int64'), sub['direction']))
    slug_sets[sid] = set(sub['slug'].unique())
    dir_dict[sid] = sub.groupby('slug')['direction'].apply(set).to_dict()

# Pairwise long-form
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

        # Direction agreement on overlapping slugs
        common_slugs = sa & sb
        agree = total = 0
        for slug in common_slugs:
            dirs_a = dir_dict[a].get(slug, set())
            dirs_b = dir_dict[b].get(slug, set())
            if dirs_a & dirs_b:
                agree += 1
            total += 1
        dir_agree_pct = (agree / total * 100) if total else 0

        rows.append(dict(
            sleeve_a=a, sleeve_b=b,
            jaccard_fire=jacc_f, jaccard_slug=jacc_s,
            inter_fires=inter_f, union_fires=union_f,
            inter_slugs=inter_s, union_slugs=union_s,
            dir_agree_pct=dir_agree_pct,
        ))

pairs = pd.DataFrame(rows)
pairs.to_csv(f"{OUT}/pairwise_overlap_matrix.csv", index=False)
print(f"SAVED -> pairwise_overlap_matrix.csv  ({len(pairs)} pairs)")

# Wide-form Jaccard matrices (slug + fire)
N = len(sleeves)
mat_fire = np.zeros((N, N))
mat_slug = np.zeros((N, N))
for _, r in pairs.iterrows():
    i = sleeves.index(r['sleeve_a'])
    j = sleeves.index(r['sleeve_b'])
    mat_fire[i, j] = mat_fire[j, i] = r['jaccard_fire']
    mat_slug[i, j] = mat_slug[j, i] = r['jaccard_slug']

mat_fire_df = pd.DataFrame(mat_fire, index=sleeves, columns=sleeves)
mat_slug_df = pd.DataFrame(mat_slug, index=sleeves, columns=sleeves)
mat_fire_df.to_csv(f"{OUT}/pairwise_jaccard_fire.csv")
mat_slug_df.to_csv(f"{OUT}/pairwise_jaccard_slug.csv")
print(f"SAVED -> pairwise_jaccard_fire.csv + pairwise_jaccard_slug.csv")

# ------------------------------------------------------------------
# Heatmaps
# ------------------------------------------------------------------
def heatmap(mat, sleeves, title, path):
    fig, ax = plt.subplots(figsize=(12, 10))
    im = ax.imshow(mat, cmap='RdYlGn_r', vmin=0, vmax=1)
    ax.set_xticks(range(len(sleeves)))
    ax.set_yticks(range(len(sleeves)))
    ax.set_xticklabels(sleeves, rotation=90, fontsize=7)
    ax.set_yticklabels(sleeves, fontsize=7)
    # annotate
    for i in range(len(sleeves)):
        for j in range(len(sleeves)):
            v = mat[i,j]
            if v > 0.05:
                ax.text(j, i, f"{v:.2f}", ha='center', va='center', fontsize=5,
                        color='white' if v > 0.5 else 'black')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label='Jaccard')
    plt.title(title, fontsize=12)
    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches='tight')
    plt.close()

heatmap(mat_fire, sleeves, 'Pairwise Jaccard - FIRE level (slug+fire_us+direction)',
        f"{OUT}/heatmap_jaccard_fire.png")
heatmap(mat_slug, sleeves, 'Pairwise Jaccard - SLUG level (any-fire-in-slug)',
        f"{OUT}/heatmap_jaccard_slug.png")
print("SAVED -> heatmap PNGs")

# ------------------------------------------------------------------
# Quick summary of overlap
# ------------------------------------------------------------------
# Highest-overlap pairs (not self)
top_pairs = pairs[pairs['sleeve_a'] != pairs['sleeve_b']].sort_values('jaccard_fire', ascending=False).head(30)
print("\n=== TOP OVERLAPPING PAIRS (fire-level Jaccard) ===")
print(top_pairs[['sleeve_a','sleeve_b','jaccard_fire','jaccard_slug','inter_fires','union_fires','dir_agree_pct']].to_string(index=False))
