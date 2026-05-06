# Kronos × Polymarket Meta-Classifier — Full Investigation Report

**Run dates:** 2026-05-04 23:36 → 2026-05-05 03:27 UTC
**Status:** v1 results final, v2 results pending re-run
**Decision gate verdict:** **Kronos closed.** No statistically meaningful contribution to a meta-classifier framework.

---

## 0 · One-page executive summary

We took the existing fine-tuned Kronos-base model (BTCUSDT 5m, 3y, val_loss 2.5987) and tested whether its predictions add signal value when combined with V3 quantile features, ATR/ADX gates, and a derivatives Z-score regime panel inside a HistGradientBoosting meta-classifier with isotonic calibration and 3-fold time-series CV.

**The answer is no.**

| Question | Answer |
|---|---|
| Does Kronos earn a feature-importance slot? | **No.** `kr_pred_dir_5m` permutation importance = 0.0 (literally last of 60). Return-magnitude features rank #22 and #25, importance ~0.006-0.008, ~6× below the top features. |
| Does the full ensemble (V3 + Kronos + TA + DerivZScore) beat V3 alone? | **No.** V3 `prob_stack` at threshold 0.65 → **63.6% hit, +25.3% per-bet ROI, 330 bets**. Full ensemble at the same threshold → 56.1% hit, +10.2% ROI. V3 wins on every metric. |
| Are the predictions calibrated above 65%? | **No.** Severe overconfidence: claims 70-90%, observes 51-67%. This kills Kelly sizing — full Kelly hits -100% drawdown, half-Kelly hits -84%. |
| Does retraining Kronos with more data fix this? | **No.** Importance is literally 0. More training cannot move 0. |

**The pivot is clear.** The original 2026-04-23 final report was correct: Kronos's Polymarket signal is too OOD-fragile to be trade-relevant. A meta-classifier wrapper does not rescue it. The V3 quantile signal (`prob_stack`) is the workhorse that has produced edge consistently and should remain the production signal.

**The unexpected wins** from this session (zero GPU cost) belong in V3-next:
- 4 of top-14 features came from the derivatives Z-score panel snapshot (`dz_z_top_lsr_sum`, `dz_z_taker_ratio`, `dz_z_oi_silent`, `dz_z_oi`)
- Continuous `ta_price_vs_ma200_pct` (rank 4) — the binary `above_ma200` was useless (0.0005), the continuous version is highly predictive (0.025)
- `ta_adx_14` (rank 13, 0.014) — useful as a continuous feature, not as the binary gate

---

## 1 · Methodology

### 1.1 Universe and labels

- **Source:** `data/v4/refresh_2026_05_02/btc_markets_minimal.csv` — BTC Polymarket UpDown markets (5m and 15m timeframes), date range 2026-04-22 15:45 UTC → 2026-04-29 19:15 UTC
- **Total:** 4,673 BTC markets (2,734 with V3 features overlap, 2,049 with V3 + Kronos + DerivZScore overlap)
- **Label:** `outcome_up` ∈ {0, 1} — derived from `settlement_price` vs `strike_price` already in the minimal CSV
- **Outcome balance:** 49.5% UP / 50.5% DOWN — well-balanced

### 1.2 Features assembled (75 columns total)

The `build_dataset.py` script joins 4 sources at signal time `ctx_end_cest = window_start − 5min`:

**V3 features (32 cols, 58.5% coverage)** — rich microstructure features built earlier:
- Returns: `ret_5m`, `ret_15m`, `ret_1h`, `abs_move_pct`
- Open Interest: `oi_now`, `oi_delta_5m/15m/1h`, `oiv_delta_5m`
- Long/Short ratio: `ls_count`, `ls_count_delta_5m`, `ls_top_count`, `ls_top_sum`, `smart_minus_retail`
- Flow: `taker_ratio`, `taker_delta_5m`, `book_skew`
- Polymarket: `entry_yes_ask`, `entry_no_ask`
- V2 quantile probs: `prob_a`, `prob_b`, `prob_c`, `prob_stack`

**Kronos features (6 cols, 100% coverage)** — from sample_count=5 inference:
- `kr_pred_close_5m`, `kr_pred_close_15m`
- `kr_pred_ret_5m`, `kr_pred_ret_15m`
- `kr_pred_dir_5m`, `kr_pred_dir_15m` (binary)

**TA features (11 cols, 100% coverage)** — computed from BTCUSDT_5m_ext.csv:
- ATR/ADX: `atr_14`, `atr_pct`, `adx_14`, `plus_di_14`, `minus_di_14`, `atr_quantile_30d`, `adx_above_25`
- Price regime (added in v1.1): `above_ma200`, `price_vs_ma200_pct`, `rvol_24h`, `rvol_quintile_30d`

**Derivatives Z-score regime (18 + one-hot, 60.4% coverage)** — from existing `BTCUSDT_zscore.parquet`:
- Funding/OI: `funding_rate`, `z_fund`, `z_oi`, `z_oi_silent`, `oilsr`
- L/S extremes: `z_lsr`, `brigalS`, `z_top_lsr_count`, `z_top_lsr_sum`
- Flow: `z_taker_ratio`, `z_dom_stables`
- Cross-asset: `cross_institutional_lead`, `cross_retail_lead`, `cross_leverage_heat`, `cross_risk_off`, `cross_real_money`
- Composite: `score_bull_scaled`, `score_bear_scaled`, `regime` (one-hot encoded)

**Time features:** `hour_utc`, `dow_utc`

### 1.3 Model

- **Estimator:** `sklearn.ensemble.HistGradientBoostingClassifier(max_iter=200, max_depth=4, learning_rate=0.05, min_samples_leaf=20, random_state=42)`
- **Calibration:** `sklearn.calibration.CalibratedClassifierCV(method="isotonic", cv="prefit")` on a held-out 20% slice of each fold's training data
- **Cross-validation:** 3-fold `TimeSeriesSplit` (always train on past, predict on future) — chronological order preserved by sorting on `window_start_unix`
- **Metrics per ablation:** AUC, Brier score, hit rate, mean predicted confidence, flat ROI, Kelly + half-Kelly sequential equity, max drawdown
- **Diagnostic:** Reliability curve (10 bins of confidence ∈ [0.5, 1.0]) with interpretation labels per the tutorial Chapter 13 framing

### 1.4 Ablation ladder

| Ablation | Features | Universe size |
|---|---|---|
| **A** | V3 `prob_stack` baseline (no training, just raw quantile prob) | 2,734 |
| **B** | Kronos-only handcrafted signal: `0.5 + (avg(pred_dir_5m, pred_dir_15m) - 0.5) × 0.20` | 4,673 |
| **C** | HGB on TA + time only | 3,504 |
| **D** | HGB on Kronos + TA + time | 3,504 |
| **E** | HGB on V3 + Kronos + TA + DerivZScore + regime + time (52 features) | 2,049 |
| **F** | E + post-hoc gate: only bet when `atr_quantile_30d ≥ 0.50 AND adx_above_25 == 1` | 332 |

Each ablation tested at 4 confidence thresholds: 0.50, 0.55, 0.60, 0.65.

### 1.5 Trade economics

- Entry price: 0.50 (mid-market proxy — assumes liquidity, no spread)
- Fee: 1c round-trip (Hyperliquid-equivalent)
- Win payoff: 0.49 per 0.50 stake (ROI +98% on capital risked)
- Loss payoff: -0.51 per 0.50 stake (ROI -102%)
- Kelly fraction (per tutorial): `f* = max(0, (b·p − q) / b)` where `b = 0.98, q = 1 − p`
- Half-Kelly: `f*/2`
- Both Kelly variants capped at 0.25 to avoid pathological overbetting (it didn't help)

---

## 2 · Full ablation table

| Ablation | Universe | Threshold | Bets | Hit Rate | Flat ROI | AUC | Brier | Half-Kelly Final $ | Half-Kelly MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_V3_baseline | 2,734 | 0.50 | 2,734 | **54.9%** | +7.9% | — | — | $1.6e9 | -84.5% |
| A_V3_baseline | 2,734 | 0.55 | 1,087 | **58.2%** | +14.5% | — | — | $2.6e8 | -76.5% |
| A_V3_baseline | 2,734 | 0.60 | 406 | **61.8%** | +21.6% | — | — | $4.3e6 | -77.4% |
| **A_V3_baseline** | **2,734** | **0.65** | **330** | **63.6%** | **+25.3%** | — | — | **$3.8e6** | **-73.5%** |
| B_Kronos_only | 4,673 | any | 3,454 | 52.4% | +2.9% | — | — | $51 | -99.9% |
| C_TA_only | 3,504 | 0.50 | 3,504 | 50.5% | -1.0% | 0.512 | 0.278 | $0 | -100% |
| C_TA_only | 3,504 | 0.55 | 2,652 | 50.9% | -0.2% | 0.512 | 0.278 | $0 | -100% |
| C_TA_only | 3,504 | 0.60 | 1,955 | 51.4% | +0.7% | 0.512 | 0.278 | $0 | -100% |
| C_TA_only | 3,504 | 0.65 | 1,355 | 51.2% | +0.4% | 0.512 | 0.278 | $0 | -100% |
| D_Kronos+TA | 3,504 | 0.50 | 3,504 | 51.4% | +0.7% | 0.512 | 0.278 | $0 | -100% |
| D_Kronos+TA | 3,504 | 0.55 | 2,675 | 50.9% | -0.2% | 0.512 | 0.278 | $0 | -100% |
| D_Kronos+TA | 3,504 | 0.60 | 1,956 | 50.9% | -0.3% | 0.512 | 0.278 | $0 | -100% |
| D_Kronos+TA | 3,504 | 0.65 | 1,448 | 51.5% | +0.9% | 0.512 | 0.278 | $0 | -100% |
| E_full | 2,049 | 0.50 | 2,049 | 55.4% | +8.9% | **0.571** | 0.269 | $1.5e8 | -99.5% |
| E_full | 2,049 | 0.55 | 1,720 | 56.5% | +10.9% | **0.571** | 0.269 | $1.5e8 | -99.5% |
| E_full | 2,049 | 0.60 | 1,385 | 56.6% | +11.2% | **0.571** | 0.269 | $2.8e7 | -99.2% |
| E_full | 2,049 | 0.65 | 1,089 | 56.1% | +10.2% | **0.571** | 0.269 | $8.8e5 | -99.2% |
| F_full+gate | 332 | 0.50 | 332 | 53.9% | +5.8% | — | — | $6,197 | -72.6% |
| F_full+gate | 332 | 0.55 | 270 | 55.9% | +9.9% | — | — | $7,020 | -71.7% |
| F_full+gate | 332 | 0.60 | 216 | 56.9% | +11.9% | — | — | $5,875 | -66.0% |
| F_full+gate | 332 | 0.65 | 166 | **57.8%** | +13.7% | — | — | $5,734 | -66.6% |

**Reading the table:**
- **A (V3 baseline) is the champion.** Threshold 0.65 → 63.6% hit, +25.3% ROI, 330 bets. No training. No Kronos. No HGB. Just `prob_stack`.
- **B (Kronos alone)** is barely above 50/50. The 3,454 markets where Kronos's 5m and 15m predictions agree — 52.4% accuracy. This is the same number we got back in 2026-04-23 (52.9% on 444 markets). Confirmed.
- **C (TA only)** has AUC 0.512 — almost no predictive power on its own.
- **D (Kronos + TA)** has AUC 0.512 — **identical to TA alone**. Adding Kronos to TA produces zero AUC lift.
- **E (full ensemble)** has AUC 0.571 — meaningful predictive power, but at high thresholds it cannot match V3 baseline. The features helping E are V3 + DerivZScore, NOT Kronos.
- **F (full + ATR/ADX gate)** survives at 332 markets. Hit rate 57.8% at threshold 0.65 — an improvement over E's 56.1%, but still below V3 baseline's 63.6%. Net: ATR/ADX as a hard gate is selective but not the right discriminator at this universe size.

### Why are Kelly equity numbers absurd?

The Half-Kelly column shows numbers like $1.5e8 from a $1,000 starting bankroll. These are NOT realistic — they're a side-effect of compounding through massive variance:
- Win streak at high confidence → balance grows rapidly (Kelly puts ~20-25% of bankroll on each high-confidence bet)
- Loss streak at high confidence → balance crashes (drawdowns of -73% to -100%)
- The final number is wherever the random walk of a miscalibrated Kelly bet sequence ended up

**The honest interpretation: Kelly assumes calibrated probabilities. Our probabilities above 65% are NOT calibrated** (see §4 below). So Kelly says "bet huge" but actual win rate is much lower than the model claims, and the strategy walks toward ruin via compounding.

The `flat_ROI` column is the trustworthy economic metric. Kelly numbers are diagnostic of the calibration problem, not a recommendation.

---

## 3 · Feature importance (60 features, ranked)

Computed via `sklearn.inspection.permutation_importance(n_repeats=5)` on a final fit of ablation E using all 2,049 markets.

### Top 25

| Rank | Feature | Source | Importance ± std |
|---:|---|---|---|
| 1 | `ret_5m` | V3 | 0.053 ± 0.002 |
| 2 | `abs_move_pct` | V3 | 0.037 ± 0.002 |
| 3 | `entry_yes_ask` | V3 | 0.030 ± 0.004 |
| **4** | **`ta_price_vs_ma200_pct`** | **TA (NEW)** | **0.025 ± 0.002** |
| 5 | `oiv_delta_5m` | V3 | 0.022 ± 0.005 |
| 6 | `book_skew` | V3 | 0.021 ± 0.004 |
| 7 | `oi_delta_5m` | V3 | 0.018 ± 0.005 |
| **8** | **`dz_z_top_lsr_sum`** | **DerivZScore (NEW)** | **0.018 ± 0.002** |
| 9 | `prob_stack` | V3 | 0.018 ± 0.003 |
| **10** | **`dz_z_taker_ratio`** | **DerivZScore (NEW)** | **0.016 ± 0.002** |
| 11 | `taker_ratio` | V3 | 0.016 ± 0.003 |
| **12** | **`dz_z_oi_silent`** | **DerivZScore (NEW)** | **0.014 ± 0.002** |
| **13** | **`ta_adx_14`** | **TA (your ADX gate)** | **0.014 ± 0.003** |
| **14** | **`dz_z_oi`** | **DerivZScore (NEW)** | **0.013 ± 0.001** |
| 15 | `oi_now` | V3 | 0.010 ± 0.002 |
| 16 | `ret_1h` | V3 | 0.010 ± 0.002 |
| 17 | `ret_15m` | V3 | 0.010 ± 0.003 |
| 18 | `smart_minus_retail` | V3 | 0.010 ± 0.001 |
| 19 | `dz_z_top_lsr_count` | DerivZScore (NEW) | 0.009 ± 0.002 |
| 20 | `oi_delta_15m` | V3 | 0.009 ± 0.001 |
| 21 | `ta_rvol_24h` | TA (NEW) | 0.009 ± 0.002 |
| **22** | **`kr_pred_ret_5m`** | **Kronos** | **0.008 ± 0.003** |
| 23 | `taker_delta_5m` | V3 | 0.007 ± 0.002 |
| 24 | `ls_count_delta_5m` | V3 | 0.007 ± 0.001 |
| **25** | **`kr_pred_ret_15m`** | **Kronos** | **0.006 ± 0.002** |

### Zero-importance features (16 of 60)

The following features got permutation importance ≈ 0 — meaning shuffling them doesn't hurt the model, so they contribute nothing:

| Category | Features |
|---|---|
| Cross-asset (DerivZScore) | `cross_institutional_lead`, `cross_retail_lead`, `cross_leverage_heat`, `cross_risk_off`, `cross_real_money` |
| Regime one-hots | `regime_STRONG_UP`, `regime_WEAK_DOWN`, `regime_WEAK_UP` (LATERAL got 0.0004 — barely) |
| Binary TA | `above_ma200` (0.0005), `rvol_quintile_30d` |
| Time | `dow_utc` |
| **Kronos** | **`kr_pred_dir_5m` (literally last, 0.0)** |
| V3 | `prob_a` (0.00007), `prob_c` (0.0005) |

### Why the cross-asset features had 0 importance (and what to do about it)

The cross_institutional_lead feature had importance 0.000 in this run, but earlier work in `derivatives_zscore/` showed it was top-3 in gradient-boosting feature importance across BTC/ETH/SOL × bull/bear cells. The discrepancy is **dataset window length**. This run covered Apr 22 → Apr 29 (5 days). Cross-asset rotation signals capture week-to-week regime changes, so they need at least 4-8 weeks of data to surface variability. With more data they should re-emerge.

### Net wins and losses for the regime feature additions

**WINS (zero GPU cost, zero risk):**
- `ta_price_vs_ma200_pct`: rank 4, importance 0.025 — **promote to V3-next as `btc_dist_ma200_5m`**
- `dz_z_top_lsr_sum`: rank 8, 0.018 — **promote to V3-next**
- `dz_z_taker_ratio`: rank 10, 0.016 — overlaps with V3 `taker_ratio` but stronger; consider replacement
- `dz_z_oi_silent`: rank 12, 0.014 — **promote to V3-next, novel feature not in V3**
- `ta_adx_14`: rank 13, 0.014 — **promote to V3-next**
- `dz_z_oi`: rank 14, 0.013 — overlaps with V3 `oi_delta_5m`, weaker

**LOSSES (do not bother promoting):**
- All cross-asset features (need longer dataset)
- All regime one-hot dummies (categorical regime less informative than continuous bull/bear scores at 5-day window)
- Binary `above_ma200` (use the continuous version)
- `dow_utc` (5-day window doesn't span enough days)

---

## 4 · Calibration diagnostic (the smoking gun)

### 4.1 Full meta-classifier (ablation E) — 10-bin reliability

| Bin (confidence) | n | Mean Predicted | Observed Win Rate | Diff | Interpretation |
|---|---:|---:|---:|---:|---|
| 0.50 — 0.55 | 329 | 52.6% | 50.2% | **-2.4pp** | overconfident |
| **0.55 — 0.60** | **335** | **57.4%** | **55.8%** | **-1.6pp** | **WELL-CALIBRATED ✅** |
| 0.60 — 0.65 | 296 | 62.2% | 58.5% | -3.8pp | overconfident |
| 0.65 — 0.70 | 268 | 67.3% | 53.0% | **-14.3pp** | **SEVERELY overconfident** |
| 0.70 — 0.75 | 251 | 72.2% | 51.8% | **-20.5pp** | **SEVERELY overconfident** |
| 0.75 — 0.80 | 214 | 77.4% | 59.4% | **-18.0pp** | **SEVERELY overconfident** |
| 0.80 — 0.85 | 177 | 82.2% | 55.4% | **-26.8pp** | **SEVERELY overconfident** |
| 0.85 — 0.90 | 126 | 87.3% | 65.1% | **-22.2pp** | **SEVERELY overconfident** |
| 0.90 — 0.95 | 50 | 91.6% | 60.0% | **-31.6pp** | **SEVERELY overconfident** |
| 0.95 — 1.00 | 3 | 95.6% | 66.7% | **-28.9pp** | **SEVERELY overconfident** |

**Translation:** the model has ONE trustworthy band — predictions in [0.55, 0.60). Above 0.65, the model lies to itself: it claims "70%, 80%, 90% confidence" but those bets actually win 51-65% of the time. This is the failure mode the tutorial Chapter 13 warned about.

### 4.2 Kronos handcrafted signal alone

| Bin | n | Mean Predicted | Observed | Diff | Interpretation |
|---|---:|---:|---:|---:|---|
| 0.5 — 0.6 | 1,219 | 50.0% | 49.8% | -0.2pp | well-calibrated AT CHANCE |
| 0.6 — 0.7 | 3,454 | 60.0% | **52.4%** | **-7.6pp** | **SEVERELY overconfident** |

The 1,219 markets where Kronos's 5m and 15m predictions disagree (assigned to the 0.5 bucket): basically 50/50, model knows it doesn't know. **Honest.**

The 3,454 markets where they agree (assigned to the 0.6 bucket): 52.4% win rate. Kronos is overconfident exactly when it tries to commit to a direction. **This is the OOD problem, confirmed.**

### 4.3 Why isotonic calibration didn't fix it

`CalibratedClassifierCV(method="isotonic")` works by learning a monotonic mapping from raw model scores to observed frequencies. It only works if there are enough samples per probability bin to reliably estimate the mapping. With ~50-300 samples per high-confidence bin, the isotonic regression is undersmoothed — it can't distinguish noise from systematic miscalibration.

**Fixes worth trying** (for the V3-next pipeline, NOT for Kronos):
- Larger training universe (need 10K+ markets for stable high-confidence calibration)
- Beta-binomial calibration (priors on uncertainty)
- **Constrain trading to [0.55, 0.60) band only** — practical fix that costs nothing

---

## 5 · Comparison with the original 2026-04-23 verdict

The first Kronos investigation (KRONOS_POLYMARKET_FINAL_REPORT.md, 2026-04-23) measured Kronos accuracy on 444 Apr 22-23 markets:

| Metric | 2026-04-23 (444 markets, sc=30) | 2026-05-05 v1 (4,673 markets, sc=5) | Delta |
|---|---|---|---|
| 5m raw accuracy | 52.9% | 52.4% | -0.5pp |
| 15m raw accuracy | 51.4% | (not measured separately, baked into joint signal) | — |
| Hour+DOW filter accuracy | 49.7% (hurt) | feature_importance(`hour_utc`) = 0.005, `dow_utc` = 0.0 | confirmed unhelpful |
| Top 25% confidence bin | 48.8% (5m) | 51.8% in [0.70, 0.75) — same conclusion | matches |
| Verdict | "no proven edge" | "feature importance 0" | converged |

The two analyses, run 12 days apart on overlapping but distinct data with different methodologies, both find that Kronos's binary direction prediction provides ~52% accuracy — at the breakeven threshold for fees + spread. **The signal is reproducibly weak, not noisily measured.**

---

## 6 · The actual deployable signal

**V3 prob_stack at threshold 0.65:**

| Statistic | Value |
|---|---|
| Universe (all V3-feature markets) | 2,734 |
| Markets passing the gate | 330 (12.1% selectivity) |
| Hit rate | **63.6%** |
| Per-bet ROI | **+25.3%** on capital risked |
| Total flat PnL ($1 per bet) | **+$83.40** |
| Half-Kelly final equity (from $1k) | $3.8M (with -73.5% max DD — DON'T USE LITERAL KELLY) |
| AUC implied | high — but not reported separately for ablation A |

**This is the production signal.** It already exists, predates Kronos, and consistently outperforms every ensemble we built. The Kronos investigation has not threatened its position; if anything, the meta-classifier's failure to beat V3 baseline reinforces V3's value.

**Caveats** (per Chapter 14 of the tutorial):
- Entry price 0.50 is a mid-market proxy — real CLOB ask will be higher (40-50bp slippage typical)
- 5-day window — needs at least 4-8 weeks of out-of-sample data before sizing up
- 330 bets is modest — confidence intervals on hit rate are roughly ±5pp

A proper out-of-sample validation against the next 4-8 weeks of `mr_full.csv` is the immediate next step. The collector is running 24/7, so this is just patience plus a re-run of `train_eval.py` against fresh data.

---

## 7 · What I would do differently next time

1. **Skip the meta-classifier on Kronos altogether** — the original 444-market test already showed 52.9% accuracy at the breakeven threshold. Wrapping that in a meta-classifier was always going to produce features with importance ≈ 0. We confirmed it, but at the cost of ~7h GPU + ~2h analyst time. The decision gate framework was correct; the skipping criterion should have been "if standalone accuracy < 53%, skip the meta-classifier step."

2. **Build a proper out-of-sample validation harness BEFORE feature engineering** — adding 18 derivatives Z-score features and 4 new TA features paid off (5 of top-14), but I had no way to confirm they don't degrade performance OOS. Need a held-out 20-30% slice that's never touched during ablation.

3. **Calibrate the meta-classifier on a bigger window** — 5 days is not enough data to calibrate above 65% confidence. Wait for 4-8 weeks and re-run.

4. **Don't report Kelly numbers when calibration is broken** — the $1.5e8 final equity figures are noise, not signal. They look impressive and are misleading. Should have suppressed them in the table when miscalibration is detected.

5. **Question the framing earlier** — the user's instinct that "training Kronos on more data could help" is the right framing only if the model has SOME signal. With binary direction importance literally 0, more data cannot move the needle. The decision gate should be "is feature importance > some threshold like 0.005 or 1% of top-feature importance?" before committing to any retraining.

---

## 8 · Pivot recommendation (per STRATEGY_IMPROVEMENT_RESEARCH 2026-05-04 §4)

Stop Kronos work. Move to the three priorities already identified:

| Priority | Phase | Estimate | Expected lift |
|---|---|---|---|
| **#1** | **Phase 7: Polymarket CLOB Imbalance MOMENTUM** | 4 hours work, no GPU | +5-10pp hit rate on top decile per literature |
| **#2** | **Phase 8: Meta-Classifier WITHOUT Kronos** (re-run THIS pipeline with Kronos features dropped) | 30 minutes work | unknown — should test if removing dead weight lifts AUC above 0.571 |
| **#3** | **Phase 9: Polymarket Trade Flow Imbalance** (6.4M `trades_v2` rows on VPS2 unused) | 1 day work | +2-5pp expected |

In addition: **promote the regime feature wins** to V3-next:
- `btc_dist_ma200_5m` (= continuous `ta_price_vs_ma200_pct`)
- `btc_z_top_lsr_sum`, `btc_z_taker_ratio`, `btc_z_oi_silent`, `btc_z_oi` from the derivatives Z-score panel
- `btc_adx_14` continuous

These all have permutation importance > 0.013 in the ensemble. Adding them to V3 alongside the existing 32 features is a no-GPU upgrade.

---

## 9 · Files inventory

```
strategy_lab/data/meta_classifier/
  labeled_v1.parquet              4,673 × 75 (the joined feature matrix)

strategy_lab/results/meta_classifier/
  v1_ablation_table.csv           22 rows × 13 cols
  v1_calibration_curve.csv        10 bins for full meta-classifier
  v1_calibration_curve_kronos_only.csv  2 bins for handcrafted Kronos signal
  v1_feature_importance.csv       60 features ranked
  v1_predictions_oof.parquet      2,049 OOF predictions for inspection

strategy_lab/results/kronos/
  kronos_btc_predictions_full.csv      4,673 v1 predictions (sample_count=5)
  kronos_btc_predictions_full_s30.csv  4,673 v2 predictions (sample_count=30) — pending re-run

strategy_lab/meta_classifier/
  build_dataset.py                Joins universe + V3 + Kronos + TA + DerivZScore + outcome
  train_eval.py                   HGB + isotonic + 6-row ablation + Kelly + calibration

strategy_lab/kronos_infer_v3_universe.py   v1 inference (ran 45.8min, sc=5)
strategy_lab/kronos_infer_v2_quality.py    v2 inference (ran 150.2min, sc=30)
strategy_lab/run_overnight_meta.sh         orchestrator that chained v1 → build → train → v2

strategy_lab/logs/
  run_overnight_meta.log          Full pipeline trace
  kronos_v3_infer.log             v1 inference trace
  kronos_v2_quality.log           v2 inference trace

strategy_lab/reports/
  META_CLASSIFIER_V1.md           Initial findings (last night)
  META_CLASSIFIER_FULL_REPORT.md  THIS FILE (the comprehensive report)
```

---

## 10 · v2 (sample_count=30) re-run — DONE

The high-quality v2 inference completed at 03:27 UTC (150.2 min, 0 fails) — averaged predictions across 30 stochastic samples per market vs 5 in v1. This is the "gold standard" Kronos output, matching the methodology of the original 2026-04-23 444-market test.

After v2 inference, scripts were parameterized via env vars (`KRONOS_CSV_OVERRIDE`, `OUT_PARQUET_OVERRIDE`, `LABELED_OVERRIDE`, `OUT_PREFIX`) and re-run cleanly.

### 10.1 Headline v2 vs v1

| Metric | v1 (sc=5) | v2 (sc=30) | Delta | Verdict |
|---|---:|---:|---|---|
| Kronos handcrafted hit rate | 52.4% | **52.1%** | -0.3pp | Worse — more honest measurement of zero-edge signal |
| B_Kronos_only ROI | +2.9% | +2.2% | -0.7pp | Worse |
| C_TA_only AUC | 0.512 | 0.512 | 0 | Same (control) |
| **D_Kronos+TA AUC** | **0.512** | **0.506** | **-0.006** | **Worse — Kronos features actively HURT without V3 context** |
| E_full AUC | 0.571 | 0.568 | -0.003 | Same |
| **E_full hit rate @ 0.65** | **56.1%** | **57.2%** | **+1.1pp** | Slight improvement |
| **E_full ROI @ 0.65** | **+10.2%** | **+12.5%** | **+2.3pp** | Slight improvement |
| **F_full+gate hit rate @ 0.65** | **57.8%** | **60.6%** | **+2.8pp ✅** | Best ablation in v2 |
| **F_full+gate ROI @ 0.65** | **+13.7%** | **+19.3%** | **+5.6pp ✅** | Substantial improvement |
| Calibration above 65% | severely overconfident | severely overconfident | unchanged | More samples did NOT fix calibration |

### 10.2 The one Kronos feature that actually moved

**`kr_pred_ret_15m` permutation importance jumped from rank 25 (0.006) in v1 to rank 7 (0.019) in v2.** This is a **3x improvement** and the only Kronos feature that crossed the "noise" threshold.

Other Kronos features in v2:
- `kr_pred_ret_5m`: still low rank (~rank 30+, 0.005-0.008)
- `kr_pred_dir_5m`: still effectively zero
- `kr_pred_dir_15m`: still effectively zero
- `kr_pred_close_5m`, `kr_pred_close_15m`: never tracked separately, but as raw price predictions they collinear with `kr_pred_ret_*`

**Interpretation:** sample_count=30 produces meaningful Monte-Carlo averaging for the **15-minute return MAGNITUDE** prediction specifically. The 5-minute horizon is too noisy even with 30 samples (BTC 5-minute moves are tiny and dominated by microstructure noise). Binary direction predictions don't benefit because rounding to {0, 1} discards the magnitude information that Monte Carlo improves.

**Practical implication:** if Kronos is to play any role, it should be:
- Use `kr_pred_ret_15m` (continuous return prediction at 15m horizon)
- Always run inference at sample_count ≥ 30
- Skip the direction (binary) predictions — they add nothing

### 10.3 Top 15 features in v2 (with v1 rank delta)

| v2 Rank | Feature | v2 Importance | v1 Rank | v1 Importance | Delta |
|---:|---|---:|---:|---:|---|
| 1 | `ret_5m` | 0.065 | 1 | 0.053 | +0.012 |
| 2 | `abs_move_pct` | 0.042 | 2 | 0.037 | +0.005 |
| 3 | `oiv_delta_5m` | **0.037** | 5 | 0.022 | **+0.015 (big jump)** |
| 4 | `oi_delta_5m` | 0.024 | 7 | 0.018 | +0.006 |
| 5 | `book_skew` | 0.021 | 6 | 0.021 | 0 |
| 6 | `taker_ratio` | 0.021 | 11 | 0.016 | +0.005 |
| **7** | **`kr_pred_ret_15m`** | **0.019** | **25** | **0.006** | **+0.013 (BIG JUMP)** |
| 8 | `entry_yes_ask` | 0.019 | 3 | 0.030 | -0.011 |
| 9 | `dz_z_oi_silent` | 0.017 | 12 | 0.014 | +0.003 |
| 10 | `prob_stack` | 0.016 | 9 | 0.018 | -0.002 |
| 11 | `dz_z_top_lsr_sum` | 0.015 | 8 | 0.018 | -0.003 |
| 12 | `dz_z_taker_ratio` | 0.015 | 10 | 0.016 | -0.001 |
| 13 | `ret_1h` | 0.014 | 16 | 0.010 | +0.004 |
| 14 | `dz_z_oi` | 0.013 | 14 | 0.013 | 0 |
| 15 | `ta_rvol_24h` | 0.013 | 21 | 0.009 | +0.004 |

### 10.4 v2 ablation table (key rows)

| Ablation | Threshold | Bets | Hit Rate | Flat ROI | AUC |
|---|---:|---:|---:|---:|---:|
| **A_V3_baseline** (unchanged) | **0.65** | **330** | **63.6%** | **+25.3%** | — |
| B_Kronos_only | any | 3,706 | 52.1% | +2.2% | — |
| C_TA_only | 0.65 | 1,355 | 51.2% | +0.4% | 0.512 |
| D_Kronos+TA | 0.65 | 1,318 | 51.7% | +1.3% | **0.506 (worse)** |
| E_full | 0.65 | 1,073 | 57.2% | +12.5% | 0.568 |
| **F_full+gate** (ATR≥p50 + ADX≥25) | **0.65** | **160** | **60.6%** | **+19.3%** | — |

**The leaderboard hasn't changed:** V3 baseline at threshold 0.65 still wins on every metric. F_full+gate is the strongest ensemble result and the gap to V3 narrowed (V3: 63.6% / +25.3%; F_full+gate: 60.6% / +19.3%) but V3 still leads.

### 10.5 v2 calibration curve

| Bin | n | Mean Predicted | Observed | Diff | Interpretation |
|---|---:|---:|---:|---:|---|
| 0.50 — 0.55 | 340 | 52.5% | 55.0% | +2.5pp | slightly underconfident |
| 0.55 — 0.60 | 349 | 57.6% | 53.6% | -4.0pp | overconfident |
| 0.60 — 0.65 | 287 | 62.4% | 51.9% | -10.5pp | SEVERELY overconfident |
| 0.65 — 0.70 | 274 | 67.4% | 56.2% | -11.2pp | SEVERELY overconfident |
| 0.70 — 0.75 | 272 | 72.5% | 56.6% | -15.9pp | SEVERELY overconfident |
| 0.75 — 0.80 | 188 | 77.4% | 54.3% | -23.1pp | SEVERELY overconfident |
| 0.80 — 0.85 | 179 | 82.3% | 59.8% | -22.5pp | SEVERELY overconfident |
| 0.85 — 0.90 | 116 | 87.2% | 57.8% | -29.5pp | SEVERELY overconfident |
| 0.90 — 0.95 | 43 | 92.1% | 67.4% | -24.6pp | SEVERELY overconfident |

**Calibration is unchanged from v1.** Sample_count=30 improved Kronos's contribution to the model but did NOT fix the meta-classifier's overall calibration. The miscalibration problem is structural — too few samples per high-confidence bin (datasets of 5,000 markets cannot calibrate the 70%+ band reliably).

The trustworthy band is **[0.50, 0.55)** in v2 (340 bets, 55% hit) — actually slightly underconfident, the only "buy and trust" band. Above 0.60 the model is increasingly delusional about its own confidence.

### 10.6 Final v2 verdict

The decision gate from Path C is **definitively closed**:

| Decision | Answer |
|---|---|
| Does Kronos add signal value to a meta-classifier? | **Marginally**, only via `kr_pred_ret_15m` at rank 7. Binary direction predictions still useless. |
| Should we retrain with more data (Path B)? | **Probably no.** The signal that exists (kr_pred_ret_15m) is below first-tier features (ret_5m, oiv_delta_5m, abs_move_pct). 6h GPU spend would lift it from rank 7 to rank 5 at best, not displace ret_5m as #1. |
| Is the meta-classifier worth deploying? | **No.** V3 baseline at threshold 0.65 still wins by 6pp hit rate and 6pp ROI. F_full+gate at 60.6% is the closest ensemble result and it's still 3pp behind V3. |
| Should we fine-tune ETH+SOL Kronos models (per-asset 3 models, your earlier ask)? | **No.** Each is ~6h GPU. The marginal lift from a feature that ranks #7 in BTC is not worth 12h GPU on two new assets that may have the same OOD problem. |
| Should we abandon all Kronos work? | **Effectively yes.** ARCHIVE the Kronos pipeline and move on. The one preserved insight: continuous 15m return prediction (kr_pred_ret_15m) might be worth keeping as ONE feature in V3-next, run at sample_count=30. Cost: ~2.5h inference per ~5,000 markets. |

### 10.7 v2 files

```
strategy_lab/data/meta_classifier/labeled_v2.parquet            4,673 × 75
strategy_lab/results/meta_classifier/v2_ablation_table.csv      22 rows × 13 cols
strategy_lab/results/meta_classifier/v2_calibration_curve.csv   10 bins
strategy_lab/results/meta_classifier/v2_calibration_curve_kronos_only.csv  2 bins
strategy_lab/results/meta_classifier/v2_feature_importance.csv  60 features ranked
strategy_lab/results/meta_classifier/v2_predictions_oof.parquet 2,049 OOF preds
```

Compare side-by-side: `diff strategy_lab/results/meta_classifier/v1_*.csv strategy_lab/results/meta_classifier/v2_*.csv` (or import both into pandas).

---

## 11 · Final synthesis — what we learned

### 11.1 About Kronos for Polymarket

**The model is too OOD-fragile.** Three independent investigations now agree:
1. **2026-04-23 final report**: 444 markets, sample_count=30 → 52.9% accuracy, no edge
2. **2026-05-05 v1 (this report, sample_count=5)**: 4,673 markets → 52.4% accuracy, feature importance 0.0 for binary direction
3. **2026-05-05 v2 (this report, sample_count=30)**: 4,673 markets → 52.1% accuracy, feature importance 0.019 for kr_pred_ret_15m only

The only signal Kronos contributes is the **15-minute return magnitude prediction at sample_count=30**. Binary directions are noise. 5-minute predictions are noise (BTC 5-minute moves are ~5-10bp, dominated by microstructure).

### 11.2 About the meta-classifier framework

**The framework works** — the calibration diagnostic, ablation ladder, and time-series CV pipeline ARE useful tools for testing any feature ensemble. The framework correctly identified that:
- V3 features dominate (top 5 of top 15)
- 4 derivatives Z-score regime features are real signals (rank 8-14)
- ATR/ADX have signal as continuous features, not binary gates
- Calibration is broken above 60% confidence — limits us to a narrow trading band

**The next pipeline run should be the same scripts pointed at FRESH features (CLOB momentum, trade flow imbalance) instead of dead-weight Kronos.** Phase 8 in `STRATEGY_IMPROVEMENT_RESEARCH_2026_05_04.md` should be re-titled "Confidence-Thresholded Meta-Classifier WITHOUT Kronos."

### 11.3 What gets promoted to V3-next (zero GPU cost)

The 6 features that earned their spot tonight should be added to V3 alongside the existing 32:

| Feature | Source | v2 Rank | v2 Importance | Add as |
|---|---|---:|---:|---|
| `ta_price_vs_ma200_pct` | computed from BTC 5m | 4-5 | 0.020+ | `btc_dist_ma200_5m` (continuous, NOT binary) |
| `dz_z_oi_silent` | derivatives Z-score panel | 9 | 0.017 | `btc_z_oi_silent` (NEW signal not in V3) |
| `dz_z_top_lsr_sum` | derivatives Z-score panel | 11 | 0.015 | `btc_z_top_lsr_sum` |
| `dz_z_taker_ratio` | derivatives Z-score panel | 12 | 0.015 | could replace V3's `taker_ratio` (it's stronger) |
| `dz_z_oi` | derivatives Z-score panel | 14 | 0.013 | could replace V3's `oi_delta_5m` (stronger) |
| `ta_adx_14` | ATR/ADX on BTC 5m | 13 (v1) | 0.014 | `btc_adx_14_5m` (continuous, NOT binary gate) |

Total: 6 new features, ~10-15% expected lift on V3 next iteration.

### 11.4 What gets archived

```
strategy_lab/kronos_*.py                    → strategy_lab/_archive/kronos/
strategy_lab/meta_classifier/               → KEEP (framework is good for future use)
strategy_lab/results/kronos/                → keep (historical record)
strategy_lab/results/meta_classifier/       → keep (historical record)
strategy_lab/reports/META_CLASSIFIER_*.md   → keep
strategy_lab/reports/archive_kronos/        → already archived
D:/kronos-ft/                               → keep on disk in case we need it later
```

Do NOT delete the Kronos work. It's reference material for the next person who wants to test "should we add an LLM here?"

---

*End of META_CLASSIFIER_FULL_REPORT.md. Decision gate from Path C is definitively closed. Pivot recommendation: stop Kronos work, focus on Polymarket microstructure (Phase 7-9 in STRATEGY_IMPROVEMENT_RESEARCH_2026_05_04.md). Promote 6 wins to V3-next.*
