# Meta-Classifier V1 — Path C Findings

**Run date:** 2026-05-05 00:55 UTC
**Universe:** 4,673 BTC Polymarket UpDown markets (2026-04-22 → 2026-04-29)
**Model:** Kronos-base (BTC 5m, 3y, val_loss 2.5987), inference at sample_count=5
**Meta-classifier:** sklearn HistGradientBoostingClassifier + isotonic calibration + 3-fold time-series CV
**Source data:** `data/v4/refresh_2026_05_02/btc_markets_minimal.csv` + V3 features + derivatives Z-score panel + ATR/ADX

---

## TL;DR

| Question (from Path C decision gate) | Answer |
|---|---|
| Does Kronos earn its spot in the meta-classifier? | **No.** `kr_pred_dir_5m` permutation importance = **0.0**. `kr_pred_dir_15m` = 0.0003. Return-magnitude predictions (`kr_pred_ret_5m/15m`) rank #22 and #25 of 60 features (importance ≈ 0.006-0.008, ~6× below the top features). |
| Does adding Kronos to TA + time + DerivZScore beat V3 alone? | **No.** Full ablation E (52 features) at threshold 0.65: 56.1% hit, +10.2% ROI, 1089 bets. V3 baseline alone at threshold 0.65: **63.6% hit, +25.3% ROI, 330 bets.** V3 wins on accuracy AND per-bet ROI. |
| Is the meta-classifier well-calibrated? | **Only at 55-60% confidence.** Above 65%, severely overconfident (claims 70-96%, observes 51-67%). This breaks Kelly sizing — full Kelly hits -100% drawdown, half-Kelly hits -84%. |
| Should we retrain Kronos with more data (Path B)? | **No** — feature importance for the binary direction prediction is literally 0. More data won't move zero. |

**Recommendation: close the Kronos chapter.** The original 2026-04-23 verdict was correct. The signal is too OOD-fragile to be trade-relevant, and the meta-classifier wrapper does not rescue it.

---

## 1 · Pipeline as run

```
4,673 BTC markets (mr_full / btc_markets_minimal, fresh today)
  + V3 features (32 cols: ret_5m/15m/1h, OI/LSR/taker, prob_a/b/c/stack)  → 2,734 overlap = 58.5%
  + Kronos predictions (sample_count=5)                                   → 4,673 = 100%
  + ATR/ADX/MA200/rvol from BTC 5m                                        → 4,673 = 100%
  + Derivatives Z-score panel snapshots (18 features + regime one-hot)    → 2,824 = 60.4%
                                                                            ↓
                                                          labeled_v1.parquet (4,673 × 75)
                                                                            ↓
                                              HGB + isotonic calibration, 3-fold time-series CV
                                                                            ↓
                                                              6 ablations × 4 thresholds
```

---

## 2 · Ablation table (key rows)

| Ablation | n_universe | thr | n_bets | hit_rate | flat_ROI | AUC |
|---|---|---|---|---|---|---|
| **A_V3_baseline** (prob_stack as direct prob) | 2,734 | 0.50 | 2,734 | 54.9% | +7.9% | — |
| | | 0.55 | 1,087 | 58.2% | +14.5% | — |
| | | 0.60 | 406 | 61.8% | +21.6% | — |
| | | **0.65** | **330** | **63.6%** | **+25.3%** | — |
| **B_Kronos_only** (handcrafted, no training) | 4,673 | any | 3,454 | 52.4% | +2.9% | — |
| **C_TA_only** (HGB on TA + time) | 3,504 | 0.50-0.65 | 1,355-3,504 | 50.5-51.4% | -1.0 to +0.4% | 0.512 |
| **D_Kronos+TA** (HGB on Kronos + TA + time) | 3,504 | 0.50-0.65 | 1,448-3,504 | 50.9-51.5% | -0.3 to +0.9% | **0.512** (zero lift over C) |
| **E_full** (V3 + Kronos + TA + DerivZScore + time, 52 feats) | 2,049 | 0.50 | 2,049 | 55.4% | +8.9% | **0.571** |
| | | 0.55 | 1,720 | 56.5% | +10.9% | 0.571 |
| | | 0.60 | 1,385 | 56.6% | +11.2% | 0.571 |
| | | 0.65 | 1,089 | 56.1% | +10.2% | 0.571 |
| **F_full + ATR>p50 & ADX>=25 gate** | 332 | 0.65 | 166 | 57.8% | +13.7% | — |

**Key observation:** Adding Kronos to TA (D) lifts AUC from 0.512 → 0.512 — **literally zero improvement**. The full ensemble (E) does beat V3 baseline at threshold 0.50 (55.4% vs 54.9%) but **never beats V3 at threshold 0.65** (56.1% vs 63.6%).

---

## 3 · Feature importance (top 25 of 60)

| Rank | Feature | Source | Importance |
|---|---|---|---|
| 1 | `ret_5m` | V3 | 0.053 |
| 2 | `abs_move_pct` | V3 | 0.037 |
| 3 | `entry_yes_ask` | V3 | 0.030 |
| 4 | **`ta_price_vs_ma200_pct`** | **TA (NEW)** | 0.025 |
| 5 | `oiv_delta_5m` | V3 | 0.022 |
| 6 | `book_skew` | V3 | 0.021 |
| 7 | `oi_delta_5m` | V3 | 0.018 |
| 8 | **`dz_z_top_lsr_sum`** | **DerivZScore (NEW)** | 0.018 |
| 9 | `prob_stack` | V3 | 0.018 |
| 10 | **`dz_z_taker_ratio`** | **DerivZScore (NEW)** | 0.016 |
| 11 | `taker_ratio` | V3 | 0.016 |
| 12 | **`dz_z_oi_silent`** | **DerivZScore (NEW)** | 0.014 |
| 13 | **`ta_adx_14`** | **TA (your ADX gate ask)** | 0.014 |
| 14 | **`dz_z_oi`** | **DerivZScore (NEW)** | 0.013 |
| ... | ... | ... | ... |
| **22** | **`kr_pred_ret_5m`** | **Kronos** | **0.008** |
| **25** | **`kr_pred_ret_15m`** | **Kronos** | **0.006** |
| 49 | `kr_pred_dir_15m` | Kronos | 0.0003 |
| **last** | **`kr_pred_dir_5m`** | **Kronos** | **0.0** |

**The wins from the new features I added tonight:**
- `ta_price_vs_ma200_pct` (your "above MA200" idea): rank 4, importance 0.025 — **MA200-relative price IS predictive**
- `dz_z_top_lsr_sum` / `dz_z_taker_ratio` / `dz_z_oi_silent` / `dz_z_oi`: 4 of top-14 features. Derivatives Z-score panel earns its spot.
- `ta_adx_14` (your ADX gate ask): rank 13, importance 0.014 — **ADX has signal, but as a continuous feature, not a binary gate**

**The losses:**
- `dz_cross_institutional_lead`: importance **0.0** (was top-3 in derivatives_zscore standalone work)
- `dz_cross_real_money/leverage_heat/retail_lead/risk_off`: all 0.0
- All `dz_regime_*` one-hot dummies: 0.0
- `ta_above_ma200` binary: 0.0005 (binary doesn't help; the continuous version does)
- `dow_utc`: 0.0

The cross-asset features dropped to zero importance because the dataset is only 5 days (Apr 22-29). Cross-asset rotation signals need weeks/months of regime variation to surface. With more data, they should re-emerge.

---

## 4 · Calibration curve (full meta-classifier)

| Bin | n | mean_pred | observed | diff | interpretation |
|---|---|---|---|---|---|
| 0.50-0.55 | 329 | 0.526 | 0.502 | -0.024 | overconfident |
| **0.55-0.60** | **335** | **0.574** | **0.558** | **-0.016** | **well-calibrated ✅** |
| 0.60-0.65 | 296 | 0.622 | 0.585 | -0.038 | overconfident |
| 0.65-0.70 | 268 | 0.673 | 0.530 | -0.143 | **SEVERELY overconfident** |
| 0.70-0.75 | 251 | 0.722 | 0.518 | -0.205 | **SEVERELY overconfident** |
| 0.75-0.80 | 214 | 0.774 | 0.594 | -0.180 | **SEVERELY overconfident** |
| 0.80-0.85 | 177 | 0.822 | 0.554 | -0.268 | **SEVERELY overconfident** |
| 0.85-0.90 | 126 | 0.873 | 0.651 | -0.222 | **SEVERELY overconfident** |
| 0.90-0.95 | 50 | 0.916 | 0.600 | -0.316 | **SEVERELY overconfident** |
| 0.95-1.00 | 3 | 0.956 | 0.667 | -0.289 | **SEVERELY overconfident** |

**Practical implication:** The model's "high-confidence" predictions are NOT high-accuracy. The only trustworthy band is 55-60% — which corresponds to threshold 0.55. Above that, the isotonic calibration cannot fix the gap because there isn't enough data per bin.

**This is exactly the failure mode the tutorial Chapter 13 warned about.**

### Kronos handcrafted only:
| Bin | n | mean_pred | observed | diff | interpretation |
|---|---|---|---|---|---|
| 0.5-0.6 | 1219 | 0.50 | 0.498 | -0.002 | well-calibrated (at chance) |
| 0.6-0.7 | 3454 | 0.60 | **0.524** | **-0.076** | SEVERELY overconfident |

When Kronos's 5m and 15m predictions agree (3454 markets), the win rate is only 52.4% — barely above coin flip. This is consistent with the original 2026-04-23 OOD verdict.

---

## 5 · Kelly economics — pathological because of miscalibration

The pipeline computed Kelly + half-Kelly equity curves for each ablation row. The numbers are misleading:

- E_full at threshold 0.55: half-Kelly final equity = $1.5e8 (from $1000), max DD = **-99.5%**
- A_V3_baseline at threshold 0.65: half-Kelly final = $3.8e6, max DD = **-73.5%**

**Translation:** the Kelly fractions chosen are massive (because the model says "high confidence"), so a few wins compound to huge equity, but the inevitable losing streak at the high-confidence (= overconfident) bins drives 73-99% drawdowns. **Real-world Kelly with these calibration numbers = ruin.**

**Honest sizing recommendation given the v1 calibration:**
- Only bet at threshold 0.55-0.60 (the calibrated band)
- Use **flat sizing** (not Kelly, not half-Kelly) — fixed $X per bet
- Or use a hard-capped half-Kelly with max bet ≤ 1% of bankroll

---

## 6 · The actual best strategy from this run

**V3 baseline alone, threshold 0.65, FLAT sizing:**
- Universe: 2,734 markets (where V3 features exist)
- Bets: 330 (12% selectivity)
- Hit rate: 63.6%
- Per-bet ROI: +25.3%
- Total flat PnL: +$41.70 per $0.50 stake = +$83 flat / $1k stake equivalent
- **No Kronos required. No HGB required. Just `prob_stack` from V3 quantile model with a 0.65 threshold.**

This matches what we already knew about the V3 family — `prob_stack` is the workhorse signal. The meta-classifier doesn't beat it.

---

## 7 · What this means for the project

### Closed:
- ✗ **Kronos as a standalone Polymarket signal** — confirmed dead by 2026-04-23 final report
- ✗ **Kronos predictions as a feature in a meta-classifier** — confirmed dead tonight (importance ≈ 0)
- ✗ **Retraining Kronos with extended data (FIRE_RETRAIN.md)** — won't move 0 importance
- ✗ **Kronos-mini ensemble** — same expected outcome (mini will have similar OOD issues)

### Open:
- ✅ **V3 prob_stack at threshold 0.65** — 63.6% hit, +25.3% ROI, 330 bets — **deployable signal**
- ✅ **Derivatives Z-score panel features** — 4 of top-14 features in the ensemble. Worth making them first-class in V3-next.
- ✅ **`ta_price_vs_ma200_pct`** (continuous, not binary) — top-5 feature, costs nothing to add to V3-next
- ⚠️ **Calibration is broken at high confidence** — must constrain trading to the 55-60% band until we have more data per bin OR use a different calibration method (Platt scaling has been tried, isotonic too — both fail above 65%)

### Next priorities (per STRATEGY_IMPROVEMENT_RESEARCH 2026-05-04 §4):
1. **Phase 7: Polymarket CLOB Imbalance MOMENTUM** — most promising, builds on Phase 2 work, uses data we already have
2. **Phase 8: Confidence-Thresholded Meta-Classifier (V3 features only, no Kronos)** — re-run THIS pipeline with Kronos features dropped, see if removing dead weight improves AUC
3. **Phase 9: Polymarket Trade Flow Imbalance** — 6.4M `trades_v2` rows on VPS2 are unused

---

## 8 · v2 high-quality inference (running)

Started at 00:57, sample_count=30, ETA ~2.5h (finishes ~03:30 UTC). Will produce `kronos_btc_predictions_full_s30.csv` for re-running the meta-classifier with cleaner Kronos signals.

**Expected delta:** Marginal. v1 sample_count=5 produced binary direction with 52.4% accuracy. v2 sample_count=30 might lift this to 53-54% (the original 444-market run at sc=30 hit 52.9%). Not enough to move from importance 0 to importance > 0.01.

**Suggested action when v2 completes:**
- Re-run `train_eval.py` pointed at `kronos_btc_predictions_full_s30.csv`
- Compare ablation tables side-by-side
- If v2 Kronos features rise above 0.005 importance: marginal win, worth keeping
- If v2 Kronos features stay below 0.005: definitively close the chapter

---

## 9 · Files

```
strategy_lab/data/meta_classifier/labeled_v1.parquet           4,673 × 75
strategy_lab/results/meta_classifier/v1_ablation_table.csv     22 rows × 13 cols
strategy_lab/results/meta_classifier/v1_calibration_curve.csv  10 bins
strategy_lab/results/meta_classifier/v1_calibration_curve_kronos_only.csv  2 bins
strategy_lab/results/meta_classifier/v1_feature_importance.csv 60 rows
strategy_lab/results/meta_classifier/v1_predictions_oof.parquet 2,049 OOF preds for inspection

strategy_lab/results/kronos/kronos_btc_predictions_full.csv    4,673 v1 predictions (sc=5)
strategy_lab/results/kronos/kronos_btc_predictions_full_s30.csv (in progress, sc=30)

strategy_lab/meta_classifier/build_dataset.py
strategy_lab/meta_classifier/train_eval.py
strategy_lab/kronos_infer_v3_universe.py     (v1 inference)
strategy_lab/kronos_infer_v2_quality.py      (v2 inference, running)
strategy_lab/run_overnight_meta.sh           (orchestrator, completed)

strategy_lab/logs/run_overnight_meta.log     full pipeline trace
strategy_lab/logs/kronos_v3_infer.log        v1 inference trace
strategy_lab/logs/kronos_v2_quality.log      v2 inference trace (in progress)
```

---

*End of META_CLASSIFIER_V1.md. Decision gate from Path C is now hit. Pivot recommendation: stop Kronos work, focus on Polymarket microstructure (Phase 7-9 in STRATEGY_IMPROVEMENT_RESEARCH_2026_05_04.md).*
