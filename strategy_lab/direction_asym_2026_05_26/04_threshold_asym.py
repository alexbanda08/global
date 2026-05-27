"""
TASK 4: Asymmetric thresholds on continuous features.

For continuous features (mp_skew, mp_imbalance, dev_bps proxies),
test whether the SIGN/MAGNITUDE of the optimal threshold differs UP vs DOWN.

Candidates inspected:
- mp_skew (signed)               positive = sellers heavy
- mp_imbalance                   positive = ask>bid heavy
- mp_weighted_skew
- up_micro_dev_bps / dn_micro_dev_bps
- L_stat (jump indicator)
- vpin_zscore
- as_skew
"""
import pandas as pd
import numpy as np
from pathlib import Path

PANEL = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"
OUTDIR = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/direction_asym_2026_05_26")

df = pd.read_parquet(PANEL)
df['fire_date_only'] = df['fire_date'].dt.date
LOCKBOX_START = pd.Timestamp("2026-05-21", tz="UTC").date()
train = df[df['fire_date_only'] < LOCKBOX_START]
lock = df[df['fire_date_only'] >= LOCKBOX_START]

# Top 7 sleeves by size
sleeves = df['sleeve_id'].value_counts().head(7).index.tolist()

FEATURES = ['mp_skew', 'mp_imbalance', 'mp_weighted_skew',
            'up_micro_dev_bps', 'dn_micro_dev_bps',
            'L_stat', 'vpin_zscore', 'as_skew',
            'mp_skew_change_500ms']

THRESHOLDS = {
    'mp_skew': np.arange(-0.4, 0.41, 0.1),
    'mp_imbalance': np.arange(-0.5, 0.51, 0.1),
    'mp_weighted_skew': np.arange(-0.4, 0.41, 0.1),
    'up_micro_dev_bps': np.arange(-20, 21, 5),
    'dn_micro_dev_bps': np.arange(-20, 21, 5),
    'L_stat': np.arange(0, 6.1, 0.5),
    'vpin_zscore': np.arange(-2, 2.1, 0.5),
    'as_skew': np.arange(-0.5, 0.51, 0.1),
    'mp_skew_change_500ms': np.arange(-0.2, 0.21, 0.05),
}

# For each (sleeve, direction, feature), find threshold that maximizes train sum_pnl
# with both ">=" and "<=" rules; keep best; report on lockbox
rows = []
for sleeve in sleeves:
    for direction in ['UP', 'DOWN']:
        sub_tr = train[(train['sleeve_id']==sleeve) & (train['direction']==direction)]
        sub_lk = lock[(lock['sleeve_id']==sleeve) & (lock['direction']==direction)]
        if len(sub_tr) < 200: continue
        for feat in FEATURES:
            if feat not in sub_tr.columns: continue
            vals = sub_tr[feat].dropna()
            if len(vals) < 100: continue
            best_score = sub_tr['pnl_legacy_usd'].sum()
            best_rule = None
            for op in ['>=', '<=']:
                for thr in THRESHOLDS[feat]:
                    if op == '>=':
                        mask = (sub_tr[feat] >= thr).fillna(False).values
                    else:
                        mask = (sub_tr[feat] <= thr).fillna(False).values
                    if mask.sum() < 100: continue
                    s = sub_tr.loc[mask, 'pnl_legacy_usd'].sum()
                    if s > best_score:
                        best_score = s
                        best_rule = (op, thr, mask.sum())
            if best_rule is None: continue
            op, thr, n_tr = best_rule
            # Eval on lockbox
            if op == '>=':
                lk_mask = (sub_lk[feat] >= thr).fillna(False).values
            else:
                lk_mask = (sub_lk[feat] <= thr).fillna(False).values
            n_lk = lk_mask.sum()
            if n_lk == 0: continue
            wr_lk = sub_lk.loc[lk_mask,'won_int'].mean()
            dpt_lk = sub_lk.loc[lk_mask,'pnl_legacy_usd'].mean()
            sum_lk = sub_lk.loc[lk_mask,'pnl_legacy_usd'].sum()
            rows.append(dict(
                sleeve=sleeve[:50], direction=direction,
                feature=feat, op=op, threshold=round(float(thr),3),
                n_train=n_tr, sum_train=round(best_score-sub_tr['pnl_legacy_usd'].sum(),1),
                n_lock=int(n_lk),
                WR_lock=round(wr_lk,4), dpt_lock=round(dpt_lk,3),
                sum_lock=round(sum_lk,1),
            ))

thr_df = pd.DataFrame(rows)
thr_df.to_csv(OUTDIR / "threshold_asym.csv", index=False)

# Pivot: for each (sleeve, feature) -> show UP threshold vs DOWN threshold side by side
print("--- Asymmetric thresholds: UP rule vs DOWN rule per sleeve/feature ---")
piv = thr_df.pivot_table(
    index=['sleeve','feature'], columns='direction',
    values=['op','threshold','sum_lock'], aggfunc='first'
)
print(piv.to_string(max_cols=20))

print(f"\nwrote {OUTDIR/'threshold_asym.csv'}")

# Summary: count features where UP threshold sign differs from DOWN
sign_diffs = []
for (sleeve, feat), grp in thr_df.groupby(['sleeve','feature']):
    if len(grp) < 2: continue
    up = grp[grp['direction']=='UP'].iloc[0] if (grp['direction']=='UP').any() else None
    dn = grp[grp['direction']=='DOWN'].iloc[0] if (grp['direction']=='DOWN').any() else None
    if up is None or dn is None: continue
    # Asymmetry: different op OR different sign of threshold
    asym = (up['op'] != dn['op']) or (np.sign(up['threshold']) != np.sign(dn['threshold']))
    sign_diffs.append(dict(sleeve=sleeve, feature=feat,
                            up_rule=f"{up['op']}{up['threshold']}",
                            dn_rule=f"{dn['op']}{dn['threshold']}",
                            up_sum_lock=up['sum_lock'], dn_sum_lock=dn['sum_lock'],
                            asym=asym))
sd = pd.DataFrame(sign_diffs)
sd.to_csv(OUTDIR / "threshold_asym_compare.csv", index=False)
n_asym = sd['asym'].sum() if len(sd) else 0
print(f"\nasymmetric (sign or op different): {n_asym} / {len(sd)} (sleeve,feature) pairs")
if len(sd):
    print(sd[sd['asym']].head(30).to_string())
