"""V7 top-5 selection — DEDUP BY ACTUAL FIRE SET (not gate-name).

Many gates collapse to identical fire sets (e.g., g_mp_skew_with == g_mp_skew_strong_with
have same fire rate 0.469). To get DIVERSE top 5, we:
  1. Drop dup gate sets by (offset, direction, lock_n, lock_dpt, lock_dd, lock_streak)
  2. Apply stability filters
  3. Pick top 5 by obj_score
  4. Keep best 1 sleeve per (offset, direction) — true diversity
"""
import os, sys, time, json
import numpy as np
import pandas as pd

OUT_DIR = "strategy_lab/sniper_search_2026_05_27/btc_15m_v7"
t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)


combo = pd.read_csv(f"{OUT_DIR}/v7_final_candidates.csv")
ensem = pd.read_csv(f"{OUT_DIR}/v7_ensemble_top.csv")
strad = pd.read_csv(f"{OUT_DIR}/v7_straddle_results.csv")
log(f"loaded: combo={len(combo)}, ensem={len(ensem)}, strad={len(strad)}")

# ============== STABILITY ==============
combo_ok = combo[(combo.train_wr >= 0.55) & (combo.val_wr.fillna(0) >= 0.50) &
                 (combo.lock_n >= 12) & (combo.bootstrap_p <= 0.05)].copy()
log(f"combo after stability: {len(combo_ok)}")

ensem_ok = ensem[(ensem.train_wr >= 0.55) & (ensem.val_wr.fillna(0) >= 0.50) &
                 (ensem.lock_n >= 12) & (ensem.bootstrap_p <= 0.05)].copy()
log(f"ensem after stability: {len(ensem_ok)}")

strad_ok = strad[(strad.train_won_either >= 0.55) & (strad.val_won_either.fillna(0) >= 0.50) &
                 (strad.lock_n >= 12) & (strad.bootstrap_p <= 0.05)].copy()
log(f"strad after stability: {len(strad_ok)}")

# ============== DEDUP BY FIRE-SET FINGERPRINT (combinatorial only) ==============
# Use (offset, direction, lock_n, lock_dpt, lock_dd, lock_streak) as a unique fire-set key
combo_ok['fingerprint'] = (combo_ok['offset'].astype(str) + '_' + combo_ok['direction'] + '_' +
                           combo_ok['lock_n'].astype(int).astype(str) + '_' +
                           combo_ok['lock_dpt'].round(2).astype(str) + '_' +
                           combo_ok['lock_dd'].round(2).astype(str) + '_' +
                           combo_ok['lock_streak'].astype(int).astype(str))
n_before = len(combo_ok)
# Sort so we keep the simplest (fewest gates) representative
combo_ok = combo_ok.sort_values(['fingerprint', 'n_gates'])
combo_ok = combo_ok.drop_duplicates(subset=['fingerprint'], keep='first')
combo_ok['obj_score_compute'] = combo_ok['lock_dpt'] * np.sqrt(combo_ok['lock_n'])
log(f"combo after fire-set dedup: {len(combo_ok)} (was {n_before})")

# ============== Build unified candidate table ==============
def to_record_combo(row):
    return dict(
        sleeve_id=f"btc15m_v7_combo_off{int(row['offset'])}_{row['direction']}_n{int(row['lock_n'])}_dpt{row['lock_dpt']:.1f}",
        anchor=f"offset_{int(row['offset'])}s",
        gate_stack=row['gate_stack_str'],
        weights="",
        conviction_method="B",
        n_train=int(row['train_n']), n_val=int(row['val_n']) if not pd.isna(row['val_n']) else 0,
        n_lockbox=int(row['lock_n']),
        wr_train=float(row['train_wr']), wr_val=float(row['val_wr']) if not pd.isna(row['val_wr']) else np.nan,
        wr_lockbox=float(row['lock_wr']),
        dpt_25_train=float(row['train_dpt']), dpt_25_val=float(row['val_dpt']) if not pd.isna(row['val_dpt']) else np.nan,
        dpt_25_lockbox=float(row['lock_dpt']),
        sum_25_28d_const=float(row['sum_25_28d']),
        max_dd_25=float(row['lock_dd']), loss_streak=int(row['lock_streak']),
        sharpe=float(row['lock_sharpe']),
        bootstrap_p_lockbox=float(row['bootstrap_p']),
        obj_score=float(row['lock_dpt']) * np.sqrt(int(row['lock_n'])),
        offset=row['offset'], direction=row['direction'],
        v7_path=row.get('v7_path', 'combo'),
    )

def to_record_ensem(row):
    return dict(
        sleeve_id=f"btc15m_v7_ensem_off{int(row['offset'])}_{row['direction']}_thr{row['threshold']:.2f}_n{int(row['lock_n'])}",
        anchor=f"offset_{int(row['offset'])}s",
        gate_stack=f"ENSEMBLE@thr={row['threshold']:.2f}",
        weights=row['gate_weights_json'],
        conviction_method="C_weighted",
        n_train=int(row['train_n']), n_val=int(row['val_n']) if not pd.isna(row['val_n']) else 0,
        n_lockbox=int(row['lock_n']),
        wr_train=float(row['train_wr']), wr_val=float(row['val_wr']) if not pd.isna(row['val_wr']) else np.nan,
        wr_lockbox=float(row['lock_wr']),
        dpt_25_train=float(row['train_dpt']), dpt_25_val=float(row['val_dpt']) if not pd.isna(row['val_dpt']) else np.nan,
        dpt_25_lockbox=float(row['lock_dpt']),
        sum_25_28d_const=float(row['sum_25_28d']),
        max_dd_25=float(row['lock_dd']), loss_streak=int(row['lock_streak']),
        sharpe=float(row['lock_sharpe']),
        bootstrap_p_lockbox=float(row['bootstrap_p']),
        obj_score=float(row['lock_dpt']) * np.sqrt(int(row['lock_n'])),
        offset=row['offset'], direction=row['direction'],
        v7_path=row.get('v7_path', 'A_weighted_ensemble'),
    )

def to_record_strad(row):
    return dict(
        sleeve_id=f"btc15m_v7_strad_{row['straddle_id'].replace('@','').replace('+','_')}_n{int(row['lock_n'])}",
        anchor=row['straddle_id'],
        gate_stack=f"[{row['stack_a']}]+[{row['stack_b']}]",
        weights="",
        conviction_method="B",
        n_train=int(row['train_n']), n_val=int(row['val_n']) if not pd.isna(row['val_n']) else 0,
        n_lockbox=int(row['lock_n']),
        wr_train=float(row['train_won_either']), wr_val=float(row['val_won_either']) if not pd.isna(row['val_won_either']) else np.nan,
        wr_lockbox=float(row['lock_won_either']),
        dpt_25_train=float(row['train_dpt']), dpt_25_val=float(row['val_dpt']) if not pd.isna(row['val_dpt']) else np.nan,
        dpt_25_lockbox=float(row['lock_dpt']),
        sum_25_28d_const=float(row['lock_dpt']) * int(row['lock_n']) * (28.0/4.0),
        max_dd_25=float(row['lock_dd']), loss_streak=int(row['lock_streak']),
        sharpe=float(row['lock_sharpe']),
        bootstrap_p_lockbox=float(row['bootstrap_p']),
        obj_score=float(row['obj_score']),
        offset=row['straddle_id'], direction='STRADDLE',
        v7_path='B_straddle',
    )

unified = []
for _, r in combo_ok.iterrows(): unified.append(to_record_combo(r))
for _, r in ensem_ok.iterrows(): unified.append(to_record_ensem(r))
for _, r in strad_ok.iterrows(): unified.append(to_record_strad(r))

df_u = pd.DataFrame(unified)
log(f"unified candidates after dedup: {len(df_u)}")

# Order by obj_score
df_u = df_u.sort_values(['obj_score','wr_lockbox'], ascending=[False, False])

# ============== Pick top 5 with bucket+path diversity ==============
# Rules:
#  1. Max 3 from off=600 DOWN (the V6 sweet spot — V7 also confirms it)
#  2. At least 1 from a non-V6-path (B straddle OR C ensemble OR off!=600)
#  3. Distinct gate fingerprint required (already deduped)
top5_list = []
counts = {}
MAX_OFF_600_DOWN = 3
saw_non_combo = False
for _, row in df_u.iterrows():
    key = (str(row['offset']), str(row['direction']))
    if key == ('600', 'DOWN') and counts.get(key, 0) >= MAX_OFF_600_DOWN:
        continue
    # Ensure path-diversity by saving 1 slot for non-combo
    if len(top5_list) == 4 and not saw_non_combo:
        if row['v7_path'] in ('A_2gate_new','A_3gate_new'):
            continue  # need to find a non-combo for last slot
    top5_list.append(row)
    counts[key] = counts.get(key, 0) + 1
    if row['v7_path'] not in ('A_2gate_new','A_3gate_new'):
        saw_non_combo = True
    if len(top5_list) >= 5:
        break

top5 = pd.DataFrame(top5_list)
log(f"top 5 picked: {len(top5)} (saw_non_combo={saw_non_combo})")

print()
print("=" * 120)
print("V7 TOP 5 CANDIDATES (deduped + diverse):")
print("=" * 120)
cols = ['sleeve_id','gate_stack','n_lockbox','wr_lockbox','dpt_25_lockbox',
        'max_dd_25','loss_streak','sharpe','bootstrap_p_lockbox','obj_score','v7_path']
print(top5[cols].to_string())

# Final write per V7 brief
out_cols = ['sleeve_id','anchor','gate_stack','weights','conviction_method',
            'n_train','n_val','n_lockbox','wr_train','wr_val','wr_lockbox',
            'dpt_25_train','dpt_25_val','dpt_25_lockbox',
            'sum_25_28d_const','max_dd_25','loss_streak','sharpe','bootstrap_p_lockbox',
            'obj_score','offset','direction','v7_path']
top5[out_cols].to_csv(f"{OUT_DIR}/top_5_candidates_v7.csv", index=False)
log(f"saved top_5_candidates_v7.csv")

# Save unified (deduped, no diversity filter) for ALL candidates view
df_u[out_cols].to_csv(f"{OUT_DIR}/v7_unified_all_dedup.csv", index=False)
log("DONE")
