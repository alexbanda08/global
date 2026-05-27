"""
TASK 9: Calibration check on WS-poly2 lockbox.

S6 sleeves had 13-27% calibration error per TT's report. Apply isotonic regression
on val and re-evaluate lockbox PnL.

For each sleeve:
1. Fit isotonic regression on (val_proba, val_won)
2. Apply to lockbox probabilities
3. Re-tune threshold on val using CALIBRATED probabilities
4. Compute lockbox sum_pnl with calibrated decision
"""
import os
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT = f"{ROOT}/strategy_lab/ws_poly2_dedup_2026_05_26"

print("Loading WS predictions...")
ws = pd.read_parquet(f"{OUT}/ws_fires_all_models_all_splits.parquet")
ws_poly2 = ws[ws["model"]=="logistic_poly2"].copy()

results = []
for sleeve in ws_poly2["sleeve"].unique():
    sub = ws_poly2[ws_poly2["sleeve"]==sleeve].copy()
    val = sub[sub["split"]=="val"].reset_index(drop=True)
    lock = sub[sub["split"]=="lockbox"].reset_index(drop=True)
    if len(val) < 50 or len(lock) < 50:
        continue

    # Baseline (uncalibrated) — already have proba + threshold
    baseline_th = sub["threshold"].iloc[0]
    base_lock_mask = lock["proba"] >= baseline_th
    base_lock_n = int(base_lock_mask.sum())
    base_lock_sum = lock.loc[base_lock_mask, "pnl_legacy_usd"].sum()
    base_lock_wr = lock.loc[base_lock_mask, "won_int"].mean() if base_lock_n else 0

    # Calibrated: isotonic on val
    iso = IsotonicRegression(out_of_bounds="clip")
    try:
        iso.fit(val["proba"].values, val["won_int"].values)
    except Exception as e:
        print(f"  {sleeve}: iso fit failed: {e}")
        continue
    val_cal = iso.transform(val["proba"].values)
    lock_cal = iso.transform(lock["proba"].values)

    # Re-tune threshold on val using calibrated proba
    qs = np.unique(np.quantile(val_cal, np.linspace(0.05, 0.95, 19)))
    best_th = None
    best_sum = -np.inf
    for t in qs:
        m = val_cal >= t
        if m.sum() < 30: continue
        sp = val.loc[m, "pnl_legacy_usd"].sum()
        if sp > best_sum:
            best_sum = sp
            best_th = t
    if best_th is None:
        best_th = 0.5

    cal_lock_mask = lock_cal >= best_th
    cal_lock_n = int(cal_lock_mask.sum())
    cal_lock_sum = lock.loc[cal_lock_mask, "pnl_legacy_usd"].sum()
    cal_lock_wr = lock.loc[cal_lock_mask, "won_int"].mean() if cal_lock_n else 0

    # Calibration error (mean abs diff in 10 bins on val)
    bins = pd.qcut(val["proba"], q=10, labels=False, duplicates="drop")
    cal_err_raw = 0
    cal_err_cal = 0
    val["cal"] = val_cal
    for b in val.groupby(bins):
        d = b[1]
        if len(d) < 5: continue
        cal_err_raw += abs(d["proba"].mean() - d["won_int"].mean())
        cal_err_cal += abs(d["cal"].mean() - d["won_int"].mean())
    n_bins = len(val.groupby(bins))
    cal_err_raw /= n_bins
    cal_err_cal /= n_bins

    results.append({
        "sleeve": sleeve,
        "baseline_n_lock": base_lock_n,
        "baseline_wr_lock": base_lock_wr,
        "baseline_sum_lock": base_lock_sum,
        "calibrated_n_lock": cal_lock_n,
        "calibrated_wr_lock": cal_lock_wr,
        "calibrated_sum_lock": cal_lock_sum,
        "calib_err_raw_val": cal_err_raw,
        "calib_err_iso_val": cal_err_cal,
        "delta_sum_lock": cal_lock_sum - base_lock_sum,
    })

df_cal = pd.DataFrame(results)
df_cal.to_csv(f"{OUT}/calibration_impact.csv", index=False)
print("\n=== Calibration impact on lockbox ===")
print(df_cal.to_string(index=False))
print(f"\nTotal baseline lockbox sum: ${df_cal['baseline_sum_lock'].sum():.0f}")
print(f"Total calibrated lockbox sum: ${df_cal['calibrated_sum_lock'].sum():.0f}")
print(f"Delta (calibration impact): ${df_cal['delta_sum_lock'].sum():.0f}")
print(f"Mean calib err (raw): {df_cal['calib_err_raw_val'].mean():.3f}")
print(f"Mean calib err (iso): {df_cal['calib_err_iso_val'].mean():.3f}")
