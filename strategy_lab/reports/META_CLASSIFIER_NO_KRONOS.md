# Meta-Classifier v3: No-Kronos Ablation

**Date:** 2026-05-04
**Hypothesis:** removing dead-weight Kronos features (kr_pred_*) lifts AUC + hit-rate
of the full ensemble. Prior investigation (`META_CLASSIFIER_FULL_REPORT.md`) showed
Kronos features had near-zero permutation importance and made `D_Kronos+TA` AUC
WORSE than `C_TA_only` (0.506 vs 0.512 in v2).

**Inputs:**
- Labeled dataset: `strategy_lab/data/meta_classifier/labeled_v2.parquet` (same as v2)
- Pipeline: `strategy_lab/meta_classifier/train_eval_no_kronos.py`
- Output prefix: `v3_no_kronos`

**Outputs:**
- `strategy_lab/results/meta_classifier/v3_no_kronos_ablation_table.csv`
- `strategy_lab/results/meta_classifier/v3_no_kronos_feature_importance.csv`
- `strategy_lab/results/meta_classifier/v3_no_kronos_predictions_oof.parquet`
- `strategy_lab/results/meta_classifier/v3_no_kronos_calibration_curve.csv`

---

## 1. Headline AUC Comparison

| Model                              | v2 AUC | v3_no_kronos AUC | Delta   |
|------------------------------------|--------|------------------|---------|
| C_TA_only                          | 0.512  | 0.512            | 0.000   |
| D_Kronos+TA (v2) → D_TA+DerivZ (v3)| 0.506  | n/a*             | n/a     |
| E_full (v3 = no Kronos)            | 0.568  | **0.566**        | **-0.002** |
| G_V3+TA (no Kronos, no DerivZ)     | n/a    | 0.555            | n/a     |

*D in v3 was redefined to TA+DerivZ but produced 0 valid rows (DerivZ columns sparse
on the TA-only universe). Material story is in E vs E.

**Verdict (AUC):** essentially unchanged. Removing Kronos did NOT lift AUC — it
moved by -0.002 (within noise). Kronos was dead weight, not a noise injector
strong enough to dent AUC when removed. The HGB had already learned to ignore it.

---

## 2. Trading-Economics Comparison @ Threshold 0.65

| Model                                  | n_bets | hit_rate | ROI/bet | AUC   |
|----------------------------------------|--------|----------|---------|-------|
| **A_V3_baseline (champion)**           | 330    | **63.6%**| **+25.3%** | n/a   |
| v2 E_full (with Kronos)                | 1073   | 57.2%    | +12.4%  | 0.568 |
| v3 E_full_no_kronos                    | 1076   | 55.4%    | +8.8%   | 0.566 |
| v2 F_full+gate (with Kronos)           | 160    | **60.6%**| **+19.3%** | n/a   |
| v3 F_full+gate_no_kronos               | 153    | 58.2%    | +14.3%  | n/a   |
| v3 G_V3+TA_no_kronos_no_derivz         | 1231   | 55.9%    | +9.9%   | 0.555 |

### Direct answers to the comparison questions
- v2 E_full AUC 0.568 → v3 0.566. **Did NOT beat (slightly worse, within noise).**
- v2 E_full hit @ 0.65 = 57.2% → v3 = 55.4%. **Did NOT beat (worse by -1.8pp).**
- v2 F_full+gate hit @ 0.65 = 60.6% → v3 = 58.2%. **Did NOT beat (worse by -2.4pp).**
- v2 F_full+gate ROI @ 0.65 = +19.3% → v3 = +14.3%. **Did NOT beat (worse by -5.0pp).**
- V3 baseline alone @ 0.65 = 63.6% / +25.3% / 330 bets — **gap NOT closed.**
  v3 ensemble still trails baseline by ~7pp on hit rate and ~17pp on ROI/bet.

---

## 3. Feature Importance (top 15, v3 E_full)

| Rank | Feature                | Importance |
|------|------------------------|------------|
| 1    | ret_5m                 | 0.064      |
| 2    | abs_move_pct           | 0.040      |
| 3    | oiv_delta_5m           | 0.030      |
| 4    | ta_price_vs_ma200_pct  | 0.030      |
| 5    | entry_yes_ask          | 0.029      |
| 6    | book_skew              | 0.024      |
| 7    | oi_delta_5m            | 0.021      |
| 8    | ta_adx_14              | 0.018      |
| 9    | taker_ratio            | 0.018      |
| 10   | dz_z_oi_silent         | 0.018      |
| 11   | dz_z_top_lsr_sum       | 0.017      |
| 12   | prob_stack             | 0.017      |
| 13   | dz_z_taker_ratio       | 0.015      |
| 14   | dz_z_oi                | 0.015      |
| 15   | ta_rvol_24h            | 0.015      |

Note: `prob_stack` (the V3 baseline signal) ranks only #12 here. The HGB is
spreading weight across 50+ correlated micro-signals instead of leaning on the
already-validated stacked-quantile probability — this is likely WHY the ensemble
underperforms the V3 baseline alone.

---

## 4. Verdict

**Removing Kronos was NEUTRAL-TO-SLIGHTLY-NEGATIVE.**

- AUC: essentially unchanged (-0.002).
- Trading metrics at the operational threshold (0.65): meaningfully WORSE
  across both E_full (-1.8pp hit, -3.6pp ROI) and F_full+gate (-2.4pp hit,
  -5.0pp ROI).
- Pruning Kronos did not rescue the ensemble vs V3 baseline alone; the
  ~7pp hit-rate gap is intact.

### Why?
Kronos features had near-zero importance, but their inclusion gave the HGB
optional handles to use as tiebreakers in cross-validation folds. Removing
them forced more weight onto noisy DerivZ features (dz_z_oi_silent, dz_z_*
features account for 4 of top 15), which appears slightly worse-conditioned
out-of-fold than the previous mix.

### Real conclusion
The problem was NEVER Kronos. The problem is that the meta-classifier
is over-fitting on TA + DerivZ + V3-component micro-signals at the expense
of the already-calibrated `prob_stack`. The V3 baseline @ 0.65 (330 bets,
63.6% hit, +25.3% ROI) remains the production champion.

### Recommended next experiments
1. Train HGB on a small hand-picked feature set: `prob_stack` + 3-4 top TA
   features (ret_5m, abs_move_pct, ta_adx_14, ta_price_vs_ma200_pct) only.
   Hypothesis: less overfit will let ensemble at least match baseline.
2. Stacking architecture: train HGB on residuals from V3 baseline, not raw
   outcome — force the meta-model to ADD signal rather than re-discover it.
3. Constrained calibration: monotonic constraint on prob_stack so HGB cannot
   override it.

---

## 5. Files

- Pipeline script: `strategy_lab/meta_classifier/train_eval_no_kronos.py`
- Ablation CSV: `strategy_lab/results/meta_classifier/v3_no_kronos_ablation_table.csv`
- Feature importance: `strategy_lab/results/meta_classifier/v3_no_kronos_feature_importance.csv`
- Prior report: `strategy_lab/reports/META_CLASSIFIER_FULL_REPORT.md`
