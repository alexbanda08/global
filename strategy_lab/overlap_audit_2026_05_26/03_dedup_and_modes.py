"""
Round 6: Step 3+4 - De-dup to "primary portfolio" and compute three deploy modes:
  Mode A (PRIMARY ONLY): greedy. Highest-PnL sleeve first. Add next sleeve only if
                         fire-jaccard < 40% with all already-selected.
  Mode B (NOTIONAL-SHARE): split notional equally across sleeves firing same fire.
                           Each sleeve gets 1/k of pnl on shared fires.
  Mode C (GATED-UNANIMITY): require ALL Tier-1 sleeves that fire on this slug
                            to agree on direction. Trade only when unanimous.
                            Realistic-conservative deploy.

Output:
  primary_portfolio_greedy.csv
  mode_compare.csv
  diversifiers.csv
"""
import os
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/data/v4/canonical/_results/_overlap_audit_2026_05_26"

fired = pd.read_parquet(f"{OUT}/fired_by_sleeve.parquet")
summary = pd.read_csv(f"{OUT}/sleeve_summary.csv")
pairs   = pd.read_csv(f"{OUT}/pairwise_overlap_matrix.csv")

# Only keep PROFITABLE sleeves (negative-PnL sleeves should not deploy)
positive_summary = summary[summary['sum_pnl'] > 0].copy().sort_values('sum_pnl', ascending=False).reset_index(drop=True)
print(f"Positive-PnL sleeves: {len(positive_summary)} / {len(summary)}")
print(positive_summary[['sleeve_id','asset','tf','n','wr_pct','per_tr','sum_pnl_28d']].to_string(index=False))

# ------------------------------------------------------------------
# Mode A — Greedy PRIMARY portfolio (fire-jaccard threshold 0.40)
# ------------------------------------------------------------------
print("\n" + "="*60)
print("MODE A — GREEDY PRIMARY PORTFOLIO (jaccard_fire < 0.40)")
print("="*60)

# Build symmetric jaccard lookup
jacc_lookup = {}
for _, r in pairs.iterrows():
    a, b = r['sleeve_a'], r['sleeve_b']
    jacc_lookup[(a, b)] = r['jaccard_fire']
    jacc_lookup[(b, a)] = r['jaccard_fire']
def jacc(a, b):
    return jacc_lookup.get((a, b), 0)

THRESH = 0.40
selected = []
skipped  = []
for _, row in positive_summary.iterrows():
    sid = row['sleeve_id']
    # Check overlap vs each already-selected
    too_overlapped = False
    overlap_info = []
    for s in selected:
        j = jacc(sid, s)
        if j >= THRESH:
            too_overlapped = True
            overlap_info.append((s, j))
    if too_overlapped:
        skipped.append(dict(sleeve_id=sid, reason='overlap', max_overlap_with=overlap_info,
                             sum_pnl_28d=row['sum_pnl_28d']))
        print(f"  SKIP  {sid:50s}  overlaps with {overlap_info}")
    else:
        selected.append(sid)
        print(f"  KEEP  {sid:50s}  PnL_28d=${row['sum_pnl_28d']:.0f}")

primary_ids = selected
primary_df = positive_summary[positive_summary['sleeve_id'].isin(primary_ids)].copy()
primary_total_28d = primary_df['sum_pnl_28d'].sum()
print(f"\nPRIMARY portfolio: {len(primary_ids)} sleeves, sum_pnl_28d = ${primary_total_28d:,.0f}")

# ------------------------------------------------------------------
# Mode B — Notional-share allocation
#  For each fire-key (slug, fire_us, direction), let k = #sleeves firing on it.
#  Each sleeve's effective notional = $1/k * $25 base; pnl = pnl/k.
#  Combined pnl is sum over UNIQUE fires of one bet * (sum or average?).
#  Actually: if all sleeves bet $25 and we want total notional capped at $25, each gets $25/k.
#  Net pnl per fire = pnl (single bet, no doubling). Same as winner-takes-all but
#  attribute pnl pro-rata to each sleeve.
#  For aggregation purposes: total combined deployable = sum over unique fires
#                                                       (the SUM is just the unique fire pnl)
# ------------------------------------------------------------------
print("\n" + "="*60)
print("MODE B — NOTIONAL-SHARE ALLOCATION (split $25 across k sleeves)")
print("="*60)
# A "fire" = (slug, fire_us, direction). When multiple sleeves bet on it, they
# collectively still only bet $25 on that direction → pnl = single-bet pnl.
# But ACROSS the union of sleeves' fires, total bets multiply because each sleeve
# fires on its OWN fire universe. So union sum at notional $25 per fire is the
# de-duplicated pnl across all positive sleeves.
all_pos_fires = fired[fired['sleeve_id'].isin(positive_summary['sleeve_id'])]
unique_fires = all_pos_fires.drop_duplicates(subset=['slug','fire_us','direction'])[
    ['slug','fire_us','direction','pnl_legacy_usd','won','outcome']
]
mode_b_sum = unique_fires['pnl_legacy_usd'].sum()
mode_b_28d = mode_b_sum * (28/32)
mode_b_n   = len(unique_fires)
mode_b_wr  = unique_fires['won'].mean() * 100
print(f"Mode B: union over {len(positive_summary)} positive sleeves")
print(f"  n_unique_fires={mode_b_n:,}  WR={mode_b_wr:.1f}%  sum=${mode_b_sum:.0f}  28d=${mode_b_28d:.0f}")

# Mode B at $250 notional
mode_b_28d_250 = mode_b_28d * 10
print(f"  at $250 notional: 28d = ${mode_b_28d_250:.0f}")

# ------------------------------------------------------------------
# Mode C — Gated unanimity
# Per (slug, fire_us): count how many DIFFERENT directions are bet across positive
# sleeves. If only ONE direction is bet AND ≥2 sleeves agree → unanimous → trade.
# If sleeves disagree → SKIP. If only 1 sleeve fires → optionally include (conservative=skip).
# ------------------------------------------------------------------
print("\n" + "="*60)
print("MODE C — GATED UNANIMITY (require all Tier-1 sleeves agree)")
print("="*60)
# For each fire moment (slug, fire_us), get set of directions across positive sleeves
fm = all_pos_fires.groupby(['slug','fire_us'])
mode_c_rows = []
n_agree = n_disagree = n_solo = 0
for (slug, fu), grp in fm:
    sleeves_here = grp['sleeve_id'].nunique()
    dirs = set(grp['direction'].unique())
    if len(dirs) > 1:
        n_disagree += 1
        continue  # skip
    if sleeves_here == 1:
        n_solo += 1
        continue  # require co-fire
    # unanimous
    n_agree += 1
    pnl = grp['pnl_legacy_usd'].iloc[0]  # single direction, take pnl of one row
    won = grp['won'].iloc[0]
    mode_c_rows.append(dict(slug=slug, fire_us=fu, pnl_usd=pnl, won=won, sleeves=sleeves_here))
mode_c_df = pd.DataFrame(mode_c_rows)
mode_c_sum = mode_c_df['pnl_usd'].sum() if len(mode_c_df) else 0
mode_c_28d = mode_c_sum * (28/32)
mode_c_n   = len(mode_c_df)
mode_c_wr  = mode_c_df['won'].mean() * 100 if len(mode_c_df) else 0
print(f"Mode C: unanimous={n_agree:,}  disagree(skip)={n_disagree:,}  solo(skip)={n_solo:,}")
print(f"  n={mode_c_n:,}  WR={mode_c_wr:.1f}%  sum=${mode_c_sum:.0f}  28d=${mode_c_28d:.0f}")
print(f"  at $250 notional: 28d = ${mode_c_28d*10:.0f}")

# ------------------------------------------------------------------
# Mode A combined — PRIMARY portfolio union  (winner-takes-all)
# ------------------------------------------------------------------
primary_fires = fired[fired['sleeve_id'].isin(primary_ids)]
mode_a_unique = primary_fires.drop_duplicates(subset=['slug','fire_us','direction'])
mode_a_sum = mode_a_unique['pnl_legacy_usd'].sum()
mode_a_28d = mode_a_sum * (28/32)
mode_a_n   = len(mode_a_unique)
mode_a_wr  = mode_a_unique['won'].mean() * 100
print("\n" + "="*60)
print("MODE A — PRIMARY portfolio (union of greedy-selected sleeves' fires)")
print(f"  n={mode_a_n:,}  WR={mode_a_wr:.1f}%  sum=${mode_a_sum:.0f}  28d=${mode_a_28d:.0f}")
print(f"  at $250 notional: 28d = ${mode_a_28d*10:.0f}")

# ------------------------------------------------------------------
# Compare modes summary
# ------------------------------------------------------------------
modes = pd.DataFrame([
    dict(mode='A_PRIMARY_GREEDY', n_sleeves=len(primary_ids), n_fires=mode_a_n, wr=mode_a_wr,
         sum_pnl_32d=mode_a_sum, sum_pnl_28d=mode_a_28d, at_250=mode_a_28d*10),
    dict(mode='B_NOTIONAL_SHARE_UNION', n_sleeves=len(positive_summary), n_fires=mode_b_n,
         wr=mode_b_wr, sum_pnl_32d=mode_b_sum, sum_pnl_28d=mode_b_28d, at_250=mode_b_28d*10),
    dict(mode='C_GATED_UNANIMITY', n_sleeves=len(positive_summary), n_fires=mode_c_n,
         wr=mode_c_wr, sum_pnl_32d=mode_c_sum, sum_pnl_28d=mode_c_28d, at_250=mode_c_28d*10),
])
modes.to_csv(f"{OUT}/mode_compare.csv", index=False)
print("\n" + "="*60)
print("MODE COMPARISON")
print(modes.to_string(index=False))

# Save primary portfolio detail
primary_df['mode_a_selected'] = True
primary_df.to_csv(f"{OUT}/primary_portfolio_greedy.csv", index=False)
print(f"\nSAVED -> primary_portfolio_greedy.csv")

# ------------------------------------------------------------------
# Step 5: TRUE DIVERSIFIERS — sleeves with <30% overlap vs primary portfolio
# ------------------------------------------------------------------
print("\n" + "="*60)
print("TRUE DIVERSIFIERS (overlap_pct < 30% vs PRIMARY)")
print("="*60)
primary_fire_set = set(zip(primary_fires['slug'], primary_fires['fire_us'].astype('int64'), primary_fires['direction']))
diversifiers = []
for _, row in positive_summary.iterrows():
    sid = row['sleeve_id']
    if sid in primary_ids:
        continue
    sub = fired[fired['sleeve_id'] == sid]
    s_fires = set(zip(sub['slug'], sub['fire_us'].astype('int64'), sub['direction']))
    inter = len(s_fires & primary_fire_set)
    union = len(s_fires | primary_fire_set)
    jacc_v = inter / union if union else 0
    overlap_pct_of_self = inter / len(s_fires) * 100 if s_fires else 0
    div_rec = dict(sleeve_id=sid, overlap_pct_self=overlap_pct_of_self,
                    jaccard_vs_primary=jacc_v, n=row['n'], wr_pct=row['wr_pct'],
                    sum_pnl_28d=row['sum_pnl_28d'])
    diversifiers.append(div_rec)

div_df = pd.DataFrame(diversifiers).sort_values('overlap_pct_self').reset_index(drop=True)
div_df.to_csv(f"{OUT}/diversifiers.csv", index=False)
print(div_df.to_string(index=False))

# True diversifiers = <30% overlap with primary
true_div = div_df[div_df['overlap_pct_self'] < 30].copy()
print(f"\n{len(true_div)} TRUE diversifiers (<30% overlap):")
print(true_div[['sleeve_id','overlap_pct_self','wr_pct','sum_pnl_28d']].to_string(index=False))

# Compute INCREMENTAL combined pnl when adding diversifiers
print("\n" + "="*60)
print("INCREMENTAL DEPLOY: add diversifiers to primary one at a time")
print("="*60)
running_fires = set(primary_fire_set)
running_pnl = fired[fired['sleeve_id'].isin(primary_ids)].drop_duplicates(subset=['slug','fire_us','direction'])['pnl_legacy_usd'].sum()
rolling_records = []
rolling_records.append(dict(step=0, sleeve='PRIMARY_PORTFOLIO', total_28d=running_pnl*(28/32)))
for _, dr in true_div.sort_values('sum_pnl_28d', ascending=False).iterrows():
    sid = dr['sleeve_id']
    sub = fired[fired['sleeve_id'] == sid]
    new_fires = sub[~sub.apply(lambda r: (r['slug'], int(r['fire_us']), r['direction']) in running_fires, axis=1)]
    if len(new_fires) == 0:
        continue
    incr = new_fires['pnl_legacy_usd'].sum()
    running_pnl += incr
    for _, r in new_fires.iterrows():
        running_fires.add((r['slug'], int(r['fire_us']), r['direction']))
    rolling_records.append(dict(step=len(rolling_records), sleeve=sid, incr_32d=incr,
                                  incr_28d=incr*(28/32), total_28d=running_pnl*(28/32)))
incr_df = pd.DataFrame(rolling_records)
incr_df.to_csv(f"{OUT}/incremental_diversifier_pnl.csv", index=False)
print(incr_df.to_string(index=False))
print(f"\nFINAL TOTAL incl. diversifiers (28d, $25 notional): ${running_pnl*(28/32):.0f}")
print(f"FINAL TOTAL at $250 notional: ${running_pnl*(28/32)*10:.0f}")
