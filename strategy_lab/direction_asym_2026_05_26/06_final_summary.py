"""
Final summary: pull together asymmetric pipeline results, rank top NEW asymmetric
sleeves by lockbox sum_pnl, count lockbox pass.
"""
import pandas as pd
import numpy as np
from pathlib import Path

OUTDIR = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/direction_asym_2026_05_26")

per_sleeve = pd.read_csv(OUTDIR / "direction_asym_per_sleeve.csv")
compare = pd.read_csv(OUTDIR / "sym_vs_asym_fair.csv")
diff = pd.read_csv(OUTDIR / "gate_diff_per_sleeve.csv")
thr_asym = pd.read_csv(OUTDIR / "threshold_asym_compare.csv")
kill = pd.read_csv(OUTDIR / "kill_gates_per_direction.csv")

# Counts
n_deploy = per_sleeve['deployable'].sum()
total = len(per_sleeve)
print(f"=== Lockbox deployable pass: {n_deploy}/{total} (sleeve,direction) combos ===")

# Compare summary
compare['asym_minus_sym'] = compare['asym_sum_lock'] - compare['sym_sum_lock']
compare['asym_minus_sym_dpt'] = compare['asym_dpt_lock'] - compare['sym_dpt_lock']
n_asym_better = (compare['asym_minus_sym'] > 0).sum()
print(f"sleeves where ASYMMETRIC > SYMMETRIC on lockbox sum: {n_asym_better}/{len(compare)}")
print(f"sleeves where ASYMMETRIC > SYMMETRIC on lockbox dpt: {(compare['asym_minus_sym_dpt']>0).sum()}/{len(compare)}")
print(f"avg lockbox dpt diff (asym-sym): ${compare['asym_minus_sym_dpt'].mean():.3f}")
print(f"avg lockbox sum diff (asym-sym): ${compare['asym_minus_sym'].mean():.0f}")

# Top 5 NEW direction-asymmetric sleeves by lockbox sum
top5 = per_sleeve.sort_values('sum_lock', ascending=False).head(10)
print("\nTOP per-direction stacks by lockbox sum_pnl:")
print(top5[['sleeve','direction','stack','n_stack_lock','WR_lock','dpt_lock','sum_lock','p_lock','deployable']].to_string())

# Save top 5 NEW asymmetric sleeves
top5.to_csv(OUTDIR / "top10_asymmetric.csv", index=False)
print(f"\nwrote {OUTDIR/'top10_asymmetric.csv'}")
