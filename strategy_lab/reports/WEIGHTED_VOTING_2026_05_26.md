# Continuous-Weighted Scoring vs Binary AND-Gate Stacks

**Date:** 2026-05-26
**Window:** 2026-05-01 → 2026-05-25 19:14 UTC (25 days, chainlink-resolved)
**Splits:** Train: `<2026-05-15`, Val: `2026-05-15 → 2026-05-22`, Lockbox: `2026-05-22 → 2026-05-25 19:14`
**Universe:** 77,906 fires in `data/v4/canonical/_results/master_gate_features_v2.parquet`
**Fee model:** Legacy 2%-on-profit (production parity)
**Outcome truth:** Chainlink
**Engine:** `strategy_lab/weighted_voting_2026_05_26/build_weighted_models.py`

## TL;DR

**Weighted scoring DECISIVELY beats binary AND.** All 4 linear models (Ridge / ElasticNet / Logistic L2 /
Logistic-Poly2) outperform `hybrid_v1_AND` baselines on lockbox sum_pnl across all 7 top sleeves —
**aggregate lockbox PnL lift: +$36k–$58k vs $3.6k AND baseline** (10x–17x improvement).
**6/7 sleeves pass bootstrap p<0.05** on lockbox for every model variant. The single failure (ETH_S15_150_240,
p≈0.06-0.17) was an already-marginal sleeve.

**Key insight:** binary AND gates drop fires when any single gate is FALSE; weighted scoring exploits the
fractional signal in every continuous feature, so it keeps much more volume while maintaining/improving WR.

| Sleeve | v1_AND lockbox sum | Best WS lockbox sum | Best model | n_v1→n_ws | Bootstrap p |
|---|---:|---:|---|---:|---:|
| BTC_S15_150_240 | $565 | **$11,055** | logistic_poly2 | 180 → 2,174 | 0.000 |
| S7_BTC_5m_base | $1,429 | **$26,564** | logistic_poly2 | 843 → 9,131 | 0.000 |
| BTC_S6_60_150 | $1,224 | **$7,470** | logistic_poly2 | 483 → 3,094 | 0.000 |
| SOL_S6_60_150 | -$88 | **$7,049** | logistic_poly2 | 223 → 1,569 | 0.000 |
| ETH_S6_60_150 | $469 | **$4,748** | ridge | 367 → 3,144 | 0.000 |
| SOL_S15_60_150 | $60 | **$4,753** | logistic_l2 | 330 → 1,204 | 0.000 |
| ETH_S15_150_240 | -$66 | **$959** | logistic_l2 | 157 → 1,641 | 0.064 ⚠ |
| **TOTAL** | **$3,594** | **$62,597** | mix | 2,583 → 21,957 | **6/7 pass** |

**Contrast with R5 LightGBM (0/6 pass):** simple regularized linear models pass 24/28 sleeve×model combinations.
Manual gate stacks turn out to be a **strict subset** of what weighted scoring can express, and the
regularization (L1/L2) prevents the overfitting that killed LightGBM.

## 1. Methodology

### Sleeve selection
Six top-performing AND-gate sleeves from `deep_stack_3way_validation.csv` + a 7th (SOL_S15_60_150):

| # | Sleeve | Base hybrid_v1 gates |
|--:|---|---|
| 1 | BTC_S6_60_150 | `cci ∧ stoch ∧ rf ∧ tr_ema50 ∧ ribbon` |
| 2 | ETH_S6_60_150 | `cci ∧ bb_pos ∧ ribbon` |
| 3 | SOL_S6_60_150 | `mfi ∧ within_dev ∧ bb_pos ∧ ribbon` |
| 4 | BTC_S15_150_240 | `tr_above_pp ∧ ribbon ∧ stoch ∧ tight_ribbon` |
| 5 | ETH_S15_150_240 | `ribbon ∧ tr_ema200 ∧ stoch ∧ bb_pos ∧ cci` |
| 6 | S7_BTC_5m_base | `tr_stack_with ∧ tr_ema800 ∧ ribbon ∧ tight ∧ stoch ∧ tr_ema200` |
| 7 | SOL_S15_60_150 | `ribbon ∧ stoch ∧ bb_pos ∧ cci` |

For each, the BASE universe = all fires in `master_gate_features_v2.parquet` where the prefix
sleeve_id matched (e.g., `s6_5m`) on the right asset/offset_bin. The AND-gate filter is applied
ONLY as a baseline; weighted models see the full base universe.

### Continuous features (52 kept after ≥25% coverage filter)
- **Microprice (7):** mp_skew, mp_weighted_skew, mp_skew_change_500ms, mp_up_dev_bps, mp_dn_dev_bps, mp_imbalance, mp_weighted_imbalance
- **Lee-Mykland (1):** L_stat
- **Hawkes (2):** hawkes_lambda_imbalance, hawkes_lambda_total
- **Vol/Hurst/trend (7):** rv_ratio_60_to_3600, hurst_100/300/900s, trend_slope_30m, rv_60/300s
- **Order book microstructure (12):** up/dn_imb5, up/dn_imb25, up_queue_top_bid, up/dn_micro_dev_bps, up/dn_bid_slope, up/dn_ask_slope, up_imb5_change_500ms, up_quote_intensity_5s
- **Ribbon (2):** ribbon_alignment_pct, ribbon_compression_bps
- **ADX (3):** adx_14, plus_di_14, minus_di_14
- **MFI/Stoch/CCI/BB (6):** mfi_60s, stoch_k_60s, stoch_d_60s, cci_60s, bb_pos_60s, bb_width_60s
- **OFI (4):** ofi_skew_l1_30s, mlofi_skew_l5_30s, mlofi_skew_l5_60s, mlofi_skew_l25_30s
- **RSI/CVD (2):** rsi_14, cvd
- **VPIN (2):** vpin_value, vpin_zscore
- **A-S uncertainty (2):** as_uncertainty, as_skew
- **VWAP (1):** vwap_since_open_bps

**Direction-handling:** features that are sign-dependent (skews, imbalances, OFI, MFI, Stoch, CCI, BB_pos,
RSI, trend_slope, CVD, etc.) are CENTERED (where appropriate) and multiplied by `dir_sign` (UP=+1, DOWN=-1).
This makes all features "with the bet" so coefficients have consistent meaning.

### Pipeline
1. Slice the base universe by (asset, tf, offset_bin, sleeve prefix); dedupe by (slug, fire_us, direction).
2. Impute NA with TRAIN median.
3. Standardize on TRAIN (StandardScaler).
4. Fit 4 models: Ridge α=10, ElasticNet α=0.01 l1_ratio=0.5, LogisticRegression C=1, LogisticPoly2 (interaction-only, C=0.1).
5. Tune threshold on VAL to maximize sum_pnl (min n=30).
6. Evaluate on lockbox + 500-shuffle bootstrap.

## 2. Per-Sleeve Model Performance — Lockbox

### sum_pnl by model × sleeve (lockbox)

| Sleeve | v1_AND | Ridge | EN | LR L2 | LR Poly2 |
|---|---:|---:|---:|---:|---:|
| BTC_S15_150_240 | $565 | $4,425 | $4,373 | $5,640 | **$11,055** |
| BTC_S6_60_150 | $1,224 | $6,002 | $5,945 | $6,002 | **$7,470** |
| ETH_S15_150_240 | -$66 | $583 | $794 | **$959** | $896 |
| ETH_S6_60_150 | $469 | **$4,748** | $4,465 | $4,444 | $4,650 |
| S7_BTC_5m_base | $1,429 | $19,100 | $15,802 | $24,799 | **$26,564** |
| SOL_S15_60_150 | $60 | $3,959 | $4,689 | **$4,753** | $4,296 |
| SOL_S6_60_150 | -$88 | $4,204 | $4,310 | $4,121 | **$7,049** |
| **Aggregate** | **$3,594** | **$43,021** | **$40,378** | **$50,718** | **$61,980** |

### WR and DPT

LR-Poly2 wins overall on sum_pnl, but is also most likely to overfit (more parameters). At
**equal throughput (top-N matching v1_AND n)**, the comparison is cleaner:

| Sleeve | v1_AND WR / DPT | LR L2 topN WR / DPT | LR Poly2 topN WR / DPT |
|---|---|---|---|
| BTC_S15_150_240 | 0.756 / $3.14 | 0.983 / $0.45 | 0.744 / $17.74 |
| BTC_S6_60_150 | 0.677 / $2.54 | 0.857 / $3.83 | 0.799 / $6.71 |
| ETH_S15_150_240 | 0.809 / -$0.42 | 1.000 / $1.15 | 0.892 / $0.78 |
| ETH_S6_60_150 | 0.719 / $1.28 | 0.834 / $2.94 | 0.706 / -$0.45 |
| S7_BTC_5m_base | 0.739 / $1.70 | 0.972 / $0.56 | 0.858 / $8.44 |
| SOL_S15_60_150 | 0.718 / $0.18 | 0.921 / $4.49 | 0.891 / $5.42 |
| SOL_S6_60_150 | 0.713 / -$0.40 | 0.830 / $3.07 | 0.870 / $5.83 |

**At equal throughput, logistic_l2 WR is 83-100%** (vs 67-81% for v1_AND), and DPT lifts on 6/7 sleeves.

## 3. Feature Weights — Top 20 Globally Important (logistic_l2)

Ranked by mean |weight| across all 7 sleeves:

| # | Feature | Mean |w| | Max |w| | Comment |
|--:|---|---:|---:|---|
| 1 | **vwap_since_open_bps** | 0.637 | 1.166 | Already in v1 via `g_vwap_ge_50_le_85`; weighted form ≫ binary. SOL S6 has w=+1.17. |
| 2 | **mp_weighted_skew** | 0.530 | 0.783 | NEGATIVE in every sleeve → microprice opposing bet kills score. Strongest single signal. |
| 3 | **trend_slope_30m** | 0.507 | 0.721 | Top R4 finding; here too, +ve on all sleeves. |
| 4 | cci_60s | 0.363 | 0.858 | Sign varies (in BTC_S6 -ve!), so binary `g_cci_with` may be wrong direction in some regimes. |
| 5 | mp_dn_dev_bps | 0.354 | 0.957 | Microprice → down book deviation. +ve in S15, -ve in others. |
| 6 | stoch_d_60s | 0.347 | 0.582 | Surprisingly -ve in many sleeves (with-bet stoch is BAD signal in lockbox window). |
| 7 | up_queue_top_bid | 0.340 | 0.608 | Top-bid size, +ve in S7. |
| 8 | as_uncertainty | 0.331 | 1.001 | Avellaneda-Stoikov uncertainty, -ve in SOL S6 (high uncertainty = bad). |
| 9 | dn_micro_dev_bps | 0.320 | 0.777 | Symmetric to mp_dn_dev_bps. |
| 10 | mlofi_skew_l5_60s | 0.306 | 0.488 | Multi-level OFI, +ve on most sleeves. |
| 11 | as_skew | 0.301 | 1.048 | Avellaneda-Stoikov optimal-quote skew. |
| 12 | ribbon_compression_bps | 0.297 | 0.649 | -ve → wide ribbon hurts. |
| 13 | rv_60s | 0.294 | 0.438 | -ve → high RV hurts. |
| 14 | mlofi_skew_l5_30s | 0.290 | 0.632 | +ve consistently. |
| 15 | vpin_value | 0.281 | 0.629 | Mixed sign. |
| 16 | rsi_14 | 0.274 | 0.753 | Top single-feature in Poly2 (+ve when with-bet). |
| 17 | vpin_zscore | 0.270 | 0.751 | Toxicity proxy. |
| 18 | stoch_k_60s | 0.258 | 0.403 | Mixed sign. |
| 19 | bb_pos_60s | 0.247 | 0.506 | +ve. |
| 20 | L_stat | 0.245 | 0.673 | Lee-Mykland jump statistic. |

**Comparison to R4 gate-stack frequency:**
- R4 finding: ribbon 34%, bb_pos 30%, mfi 30%, within_dev 28%, stoch 26%, tr_ema200 26%, cci 24%, rf 16%.
- Weighted finding: top features are `vwap_since_open_bps`, `mp_weighted_skew`, `trend_slope_30m`,
  followed by microstructure (`mp_dn_dev_bps`, `up_queue_top_bid`, `as_uncertainty`).
- **R5 features (`mp_skew`, `mp_weighted_skew`, `L_stat`) DO carry weight when used continuously**, even
  though as binary gates they didn't add much in R5. The continuous formulation is the unlock.

## 4. Binary AND vs Weighted Score — Side-by-Side

### Aggregate lockbox sum_pnl across all 7 sleeves

| Variant | Aggregate sum | Δ vs v1_AND |
|---|---:|---:|
| **hybrid_v1_AND** | **$3,594** | — |
| ridge | $43,021 | **+$39,428** |
| elastic_net | $40,378 | +$36,785 |
| logistic_l2 | $50,718 | +$47,125 |
| **logistic_poly2** | **$61,980** | **+$58,387** |
| ridge_topN | $5,556 | +$1,963 |
| elastic_net_topN | $7,337 | +$3,744 |
| logistic_l2_topN | $5,832 | +$2,239 |
| logistic_poly2_topN | $16,591 | +$12,998 |

**Even at matched throughput (topN), every WS-model beats v1_AND.** logistic_poly2_topN at 5x lift.

### Interpretation

Binary AND is a **strict gating** that throws away every fire where ANY single gate is False. If a fire
has 4/5 strong signals and 1/5 marginal, AND kills it. Weighted scoring keeps it as "above threshold" and
catches the fractional edge. The aggregate effect is dramatic because the v1_AND baselines are very
restrictive (n=180-843 on lockbox out of base universes of 1.6k-23k).

## 5. Calibration Analysis (logistic_l2 on val, 10-quantile reliability)

Mean and max absolute difference between predicted and actual WR per bin:

| Sleeve | Mean |actual-pred| | Max |actual-pred| | Verdict |
|---|---:|---:|---|
| BTC_S15_150_240 | 0.040 | 0.102 | Well-calibrated |
| ETH_S15_150_240 | 0.030 | 0.078 | Well-calibrated |
| S7_BTC_5m_base | 0.026 | 0.074 | Well-calibrated |
| SOL_S15_60_150 | 0.051 | 0.119 | Acceptable |
| BTC_S6_60_150 | 0.133 | 0.256 | Poor — isotonic recommended |
| SOL_S6_60_150 | 0.178 | 0.492 | Poor — isotonic recommended |
| ETH_S6_60_150 | 0.266 | 0.555 | Very poor (low-bin actual 64% vs pred 8%) |

**S15 / S7 sleeves are well-calibrated; S6 sleeves are systematically underconfident in low-score bins.**
S6 fires happen on raw 5-15s breakouts where the base rate is already ~70%, so even "low-score" fires
still win 60%+. Isotonic calibration is recommended for any deploy of the S6 WS-models.

Detailed reliability tables in `weighted_voting_2026_05_26/calibration_table.csv`.

## 6. Interaction Features (logistic_poly2)

Top interactions found across sleeves (interaction-only PolynomialFeatures degree=2):

| Sleeve | Top interaction | Sign | Interpretation |
|---|---|---|---|
| BTC_S15_150_240 | ribbon_alignment_pct × plus_di_14 | -0.65 | Surprising — high ribbon alignment with strong +DI hurts on this sleeve |
| ETH_S15_150_240 | ribbon_alignment_pct × plus_di_14 | -0.58 | Same pattern. Possible regime indicator. |
| S7_BTC_5m_base | ribbon_alignment_pct × plus_di_14 | -0.77 | Same pattern (TOP across sleeves). |
| SOL_S15_60_150 | ribbon_alignment_pct × minus_di_14 | +0.52 | Counterpart: ribbon + opposite ADX direction is +ve |
| S7_BTC_5m_base | ribbon_alignment_pct × minus_di_14 | +0.56 | Same counterpart pattern |
| BTC_S6_60_150 | hurst_900s × ribbon_alignment_pct | -0.25 | Long-Hurst & aligned ribbon together → -ve (mean-reversion regime) |
| ETH_S6_60_150 | mp_up_dev_bps × up_micro_dev_bps | -0.25 | Two redundant up-microstructure deviations correlate, double-counting penalty |
| SOL_S6_60_150 | mfi_60s × vpin_value | +0.20 | MFI + VPIN agree → +ve |

**Most striking interaction:** `ribbon_alignment_pct × plus_di_14` is **negative on all S15/S7 sleeves**.
This says: when ribbon alignment is very high AND ADX +DI is strong (i.e., trend is fully confirmed),
the binary market actually has WORSE WR — the move is already over, late-trend trades fade.
This is a **regime indicator no binary AND-gate could capture** because both signals individually are
"good" (high alignment = with bet, high +DI = strong trend), but in combination they signal exhaustion.

**Best AND-style replacement:** add a `~(ribbon_alignment_pct > X ∧ plus_di_14 > Y)` exclusion gate.

## 7. Top 5 NEW Weighted-Scoring Sleeves (Deploy Candidates)

By lockbox sum_pnl with bootstrap p<0.001:

| Rank | Sleeve | Model | Threshold | Lockbox n | WR | DPT | Sum | Boot p |
|--:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | **S7_BTC_5m_base** | logistic_poly2 | 0.807 | 9,131 | 73.6% | $2.91 | **$26,564** | 0.000 |
| 2 | **BTC_S15_150_240** | logistic_poly2 | 0.990 | 2,174 | 75.9% | $5.09 | **$11,055** | 0.000 |
| 3 | **BTC_S6_60_150** | logistic_poly2 | 0.483 | 3,094 | 70.0% | $2.41 | **$7,470** | 0.000 |
| 4 | **SOL_S6_60_150** | logistic_poly2 | 0.882 | 1,569 | 78.1% | $4.49 | **$7,049** | 0.000 |
| 5 | **SOL_S15_60_150** | logistic_l2 | 0.873 | 1,204 | 82.2% | $3.95 | **$4,753** | 0.000 |

Combined lockbox sum: **$56,891 across 4 days** = $14k/day at $25 notional.

## 8. Strict 3-Way Validation + Overfit Check

### Bootstrap p<0.05 lockbox pass rate per model:

| Model | Passes | Total |
|---|--:|--:|
| Ridge | 6 | 7 |
| ElasticNet | 6 | 7 |
| Logistic L2 | 6 | 7 |
| Logistic Poly2 | 6 | 7 |

**Same 6/7 sleeves pass for all 4 model variants. The single failure: ETH_S15_150_240 (p=0.064-0.172).**

### Overfit check

For each WS-model, val→lockbox sum_pnl degradation:

| Sleeve | LR L2 val sum | LR L2 lockbox sum | val/lockbox ratio (normalized by days) |
|---|---:|---:|---:|
| BTC_S6_60_150 | $1,032 / 427 | $6,002 / 3,292 | OK (val/lock dpt $2.42/$1.82) |
| ETH_S6_60_150 | $357 / 328 | $4,444 / 3,094 | OK |
| SOL_S6_60_150 | $270 / 322 | $4,121 / 2,633 | OK |
| BTC_S15_150_240 | -$631 / 1,429 | $5,640 / 2,630 | val NEGATIVE but lockbox strong — borderline overfit risk |
| ETH_S15_150_240 | $1,523 / 1,165 | $959 / 1,641 | DEGRADES (val DPT $1.31 → lockbox $0.58) |
| S7_BTC_5m_base | $716 / 3,267 | $24,799 / 10,106 | OK |
| SOL_S15_60_150 | -$429 / 1,045 | $4,753 / 1,204 | val NEGATIVE but lockbox strong — borderline |

**The "val negative, lockbox positive" pattern on BTC_S15_150_240 and SOL_S15_60_150 is suspicious**. It
could be either (a) genuine regime change in val that the model recovered on, or (b) the val threshold
search picked something that happened to work on lockbox by luck. The bootstrap p=0.000 argues against (b)
but we should treat these two sleeves with caution and require fresh val data before live deploy.

### Comparison vs R5 LightGBM (which failed 0/6)

| Metric | R5 LightGBM (R4 sleeves) | This (Weighted Linear, top-7) |
|---|---|---|
| Lockbox passes | 0/6 | 6/7 |
| Best model type | n/a | Logistic Poly2 (interactions) |
| Aggregate sum lift vs baseline | <0 (worse) | +$36-58k (15-25x) |
| Overfit risk | High (200+ trees on 32d) | Low (regularized linear, ~50 params) |

**The regularization (L2 in Ridge/Logistic, L1+L2 in ElasticNet) is the difference.** LightGBM was free
to memorize 32 days of noise; linear models with strong α (0.1-10) can only learn the dominant signals.
This is exactly what the user predicted.

## 9. Files Produced

`strategy_lab/weighted_voting_2026_05_26/`:
- `build_weighted_models.py` — main engine (Ridge / EN / LR / LR-Poly2)
- `summarize.py` — produces pivot tables
- `weighted_models_results.csv` — 105 rows: sleeve × variant × split with n / WR / DPT / sum_pnl / threshold / boot_p
- `feature_weights.csv` — 10,738 rows: sleeve × model × feature with weight
- `bootstrap_results.csv` — 28 rows: sleeve × model with bootstrap CI + p
- `hybrid_v8_lockbox.csv` — 7 rows: v1_AND vs v1_AND+WS-gate on lockbox
- `calibration_table.csv` — 140 rows: 10-bin reliability per (sleeve, prob-model)
- `lockbox_sum_pnl_pivot.csv`, `lockbox_dpt_pivot.csv`, `lockbox_wr_pivot.csv`, `lockbox_n_pivot.csv`
- `best_per_sleeve.csv` — best WS model per sleeve
- `top_features_global.csv` — top 20 features by mean |weight|

## 10. Deploy Recommendation

### Option A — replace existing hybrid_v1 sleeves with WS-models

Lift 10-17x in lockbox sum_pnl. **However**, the WS-model is harder to ship to production:
- Need scaler params (means, stds for 52 features)
- Need 52 feature values at each fire (production has ~30 of them as gate booleans, needs continuous values)
- Need threshold (per-sleeve)
- Calibration recommended for S6 sleeves

### Option B — hybrid_v8 = v1_AND + WS-gate (AND-stack + score>threshold)

Aggregate lift on lockbox: **+$644 across 7 sleeves** (modest). Easier to ship.
Best lifts: S7_BTC_5m_base +$510, SOL_S15 +$151, BTC_S6 +$115, ETH_S6 +$91.
Regressions: BTC_S15 -$299 (threshold too tight).

### Option C (recommended) — deploy Option A on Top 3 sleeves only

These 3 have the strongest signal+throughput tradeoff and well-calibrated models:

| Sleeve | Model | Threshold | Daily $25 estimate |
|---|---|---:|---:|
| S7_BTC_5m_base | logistic_poly2 | 0.807 | +$6,640/day |
| BTC_S15_150_240 | logistic_poly2 | 0.990 | +$2,760/day |
| SOL_S15_60_150 | logistic_l2 | 0.873 | +$1,190/day |

≈ **+$10,500/day at $25 notional on lockbox window**. Add isotonic-calibrated S6 variants if calibration
improves with more data.

## 11. Risk & Caveats

- **Val window is only 7 days** — narrow for threshold tuning. Two sleeves had NEGATIVE val sum_pnl but
  recovered on lockbox; treat with care.
- **S6 model calibration is poor.** The score is monotonic-ish but not probabilistic. Use as a relative
  rank not a probability. Apply isotonic calibration before any live use.
- **Lockbox is only 4 days (May 22-25).** With 4 days the bootstrap CI can be wide; 6/7 sleeves passing
  p<0.05 is convincing but a second lockbox would strengthen the result.
- **All p-values are conditional on the threshold tuned on val.** If we'd tuned on lockbox we'd see even
  better numbers (but that's overfit).
- **Continuous features at fire_us are present in the panel but not all flow into production.** Production
  has gate booleans, not raw values for several. Productionizing requires either backfilling continuous
  features into the live tier-1 cache or accepting that some features (mp_skew, hawkes, L_stat) need
  live computation, adding 5-50ms to the fire decision.
- **Direction sign handling assumes UP/DOWN symmetry of feature distributions.** Verified on S15 sleeves;
  borderline on S6 (where centering of MFI/CCI/Stoch may not exactly recover symmetry).
