"""Topic 3: Weighted ensemble methodology + worked example on ETH 5m.

Method tested:
  M1 — WR-lift weights: w_g = log(WR_with_gate / WR_without_gate) on training window
  M2 — Information value (IV) per gate (logistic-style)
  M3 — Logistic regression with L1 regularization

Worked example: ETH 5m, gates available in master_gate_features_v2.
Then threshold-tuning via greedy search on val.
"""
import pandas as pd
import numpy as np
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

p = r"C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/master_gate_features_v2.parquet"
df = pd.read_parquet(p)

# Filter ETH 5m
sub = df[(df['asset']=='ETH') & (df['tf']=='5m')].copy()
print(f"ETH 5m rows in master_gate_features_v2: {len(sub):,}")
# Drop rows missing won
sub = sub.dropna(subset=['won']).copy()
sub['won_int'] = sub['won'].astype(int)

# Time-based split: train 60% / val 20% / lockbox 20%
sub = sub.sort_values('fire_us').reset_index(drop=True)
n = len(sub)
i_train = int(n * 0.6)
i_val = int(n * 0.8)
train = sub.iloc[:i_train].copy()
val = sub.iloc[i_train:i_val].copy()
lockbox = sub.iloc[i_val:].copy()
print(f"  train n={len(train):,}  val n={len(val):,}  lockbox n={len(lockbox):,}")
print(f"  train WR={train['won_int'].mean():.4f}  val WR={val['won_int'].mean():.4f}  lockbox WR={lockbox['won_int'].mean():.4f}")

# Gates to ensemble — V6 universal winners + a few extras
GATES = [
    'g_tr_stack_full_with', 'g_hurst_trending', 'g_mp_skew_with', 'g_ribbon_agrees',
    'g_rf_with', 'g_tr_stack_with', 'g_trend_slope_with', 'g_imb5_strong_with',
    'g_mp_no_extreme', 'g_mp_change_with', 'g_within_dev', 'g_hawkes_imbalance_with',
    'g_vol_expanding', 'g_vol_high', 'g_tr_above_pp', 'g_tr_above_ema50', 'g_tr_above_ema200',
    'g_stoch_with', 'g_bb_pos_with', 'g_mfi_with', 'g_cci_with',
    'g_tr_above_cloud' if 'g_tr_above_cloud' in train.columns else 'g_tr_above_ema800',
]
GATES = [g for g in GATES if g in train.columns]
print(f"\nGates evaluated: {len(GATES)}")

# Method 1: WR-lift weights
print("\n=== METHOD 1: WR-lift weights ===")
print(f"{'gate':<35}{'wr_with':>10}{'wr_wo':>10}{'lift':>10}{'log_w':>10}{'n_with':>8}{'n_wo':>8}")
weights = {}
for g in GATES:
    has_g = train[train[g]==1]
    no_g = train[train[g]==0]
    if len(has_g)<50 or len(no_g)<50:
        continue
    wr_with = has_g['won_int'].mean()
    wr_wo = no_g['won_int'].mean()
    if wr_wo<1e-6: continue
    lift = wr_with / wr_wo
    log_w = float(np.log(lift)) if lift > 0 else 0.0
    weights[g] = log_w
    print(f"{g:<35}{wr_with:>10.4f}{wr_wo:>10.4f}{lift:>10.4f}{log_w:>10.4f}{len(has_g):>8}{len(no_g):>8}")

# Method 2: Information value
print("\n=== METHOD 2: Information Value (IV) ===")
weights_iv = {}
for g in GATES:
    if g not in weights: continue
    # IV = sum over bins (g=0, g=1) of (% won_dist - % loss_dist) * ln(% won / % loss)
    total_won = train['won_int'].sum()
    total_loss = (1 - train['won_int']).sum()
    iv = 0
    for v in [0, 1]:
        sub_g = train[train[g]==v]
        if len(sub_g) < 10: continue
        won_pct = sub_g['won_int'].sum() / total_won
        loss_pct = (1 - sub_g['won_int']).sum() / total_loss
        if won_pct<=0 or loss_pct<=0: continue
        iv += (won_pct - loss_pct) * np.log(won_pct / loss_pct)
    weights_iv[g] = iv
    print(f"  {g:<35}  IV={iv:+.6f}")

# Method 3: L1 logistic regression
print("\n=== METHOD 3: L1 logistic regression ===")
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    Xtr = train[list(weights.keys())].fillna(0).values
    ytr = train['won_int'].values
    clf = LogisticRegression(penalty='l1', solver='saga', C=0.1, max_iter=200)
    clf.fit(Xtr, ytr)
    weights_lr = dict(zip(list(weights.keys()), clf.coef_[0].tolist()))
    print(f"  Logistic coefs (L1, C=0.1):")
    for g, w in sorted(weights_lr.items(), key=lambda kv: -abs(kv[1])):
        print(f"    {g:<35}  coef={w:+.4f}")
except Exception as e:
    print(f"  sklearn fail: {e}")
    weights_lr = {}

# Build gate_sum on val and lockbox using each method
def gate_sum(df_, weights_dict):
    return sum(weights_dict[g] * df_[g].fillna(0).astype(float) for g in weights_dict if g in df_.columns)

train['gs_m1'] = gate_sum(train, weights)
val['gs_m1'] = gate_sum(val, weights)
lockbox['gs_m1'] = gate_sum(lockbox, weights)
if weights_iv:
    train['gs_m2'] = gate_sum(train, weights_iv)
    val['gs_m2'] = gate_sum(val, weights_iv)
    lockbox['gs_m2'] = gate_sum(lockbox, weights_iv)
if weights_lr:
    train['gs_m3'] = gate_sum(train, weights_lr)
    val['gs_m3'] = gate_sum(val, weights_lr)
    lockbox['gs_m3'] = gate_sum(lockbox, weights_lr)

# Threshold tuning: greedy search for thresh that maximizes Sharpe-like on val while keeping n>50
print("\n=== Threshold tuning on VAL for each method ===")
def tune_thresh(val_df, lockbox_df, gs_col, min_n=50):
    threshes = np.quantile(val_df[gs_col], np.arange(0.1, 1.0, 0.01))
    best = None
    for t in threshes:
        v = val_df[val_df[gs_col] >= t]
        if len(v) < min_n: continue
        wr = v['won_int'].mean()
        dpt = v['pnl_legacy_usd'].mean()
        sharpe = dpt / (v['pnl_legacy_usd'].std()+1e-9)
        # also lockbox
        lb = lockbox_df[lockbox_df[gs_col] >= t]
        if len(lb) < 10:
            wr_lb = np.nan; dpt_lb = np.nan
        else:
            wr_lb = lb['won_int'].mean()
            dpt_lb = lb['pnl_legacy_usd'].mean()
        score = sharpe  # primary objective: val Sharpe
        if best is None or score > best['score']:
            best = {'thresh': float(t), 'val_n': len(v), 'val_wr': float(wr),
                    'val_dpt': float(dpt), 'val_sharpe': float(sharpe),
                    'lockbox_n': len(lb), 'lockbox_wr': float(wr_lb),
                    'lockbox_dpt': float(dpt_lb), 'score': float(score)}
    return best

for method in ['m1', 'm2', 'm3']:
    if f'gs_{method}' not in val.columns: continue
    best = tune_thresh(val, lockbox, f'gs_{method}')
    if best is None:
        print(f"  method={method}  NO valid thresh")
    else:
        print(f"  method={method}  thresh={best['thresh']:.4f}  "
              f"val n={best['val_n']:,}  WR={best['val_wr']:.4f}  $/tr={best['val_dpt']:+.4f}  Sharpe={best['val_sharpe']:.3f}  "
              f"|| lockbox n={best['lockbox_n']:,}  WR={best['lockbox_wr']:.4f}  $/tr={best['lockbox_dpt']:+.4f}")

# Save weights for V7 search consumption
import json
out = {
    'gates': list(weights.keys()),
    'weights_M1_wr_lift': weights,
    'weights_M2_information_value': weights_iv,
    'weights_M3_l1_logistic': weights_lr,
}
import json
with open(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/sniper_search_2026_05_27/_v7_research/topic3_weights.json", 'w') as f:
    json.dump(out, f, indent=2)
print("\nWeights saved to topic3_weights.json")
