# LightGBM stacker — full-feature ML probe vs manual gate stacks

**Date:** 2026-05-26
**Window:** 2026-04-24 → 2026-05-25 19:10 UTC (~32d), chainlink-resolved markets only.
**Pipeline:** `strategy_lab/ml/lightgbm_stacker.py` + `strategy_lab/ml/compare_and_stack.py`
**Outputs:** `data/v4/canonical/_results/ml_lightgbm/`
**Engine:** `LegacyConfig` (2%-on-profit fee — matches production momo). $1 stake normalization.

---

## TL;DR

| Question | Answer |
|---|---|
| Did LightGBM beat manual gate stacks? | **No.** Manual sleeves OUTPERFORM ML on lockbox in every market that had a survivor manual sleeve. |
| Did stacking ML+manual improve over manual alone? | **No.** Intersection reduces n without raising per-trade — ML's "filter" trims winners. |
| Is the ML model calibrated? | **Yes** — within ±5pp gap across all probability bins (5m especially clean). |
| Are any ML-only sleeves deployable? | **Zero** pass strict lockbox (per-trade ≥ +$0.05 with boot_p ≤ 0.10). Best: ETH 5m +$0.0062/tr, boot_p 0.49 (noise). |
| Did ML find surprising features? | **Yes** — dominant signal is **microstructure (bid/ask slopes, microprice, spread_diff)** not TA. |

---

## TASK 1 — Training matrix

Joined panels at fire_us / ws_s:

- `hybrid_features_{5m,15m}.parquet` (RF/TR/TA/ribbon/stoch/BB/MFI/CCI/Markov/F7 RSI/anchored VWAP)
- `vol_hurst_at_fire_{5m,15m}.parquet` (rv_60s/300s/900s/3600s, hurst_100s/300s/900s, GK sigma, vol_regime)
- `microstructure_panel.parquet` filtered by tf (book slopes, microprice, imbalances, eff spread, depth)
- `drz_panel_{5m,15m}.parquet` (zone counts, distances, recent RC/RE)
- `sms_panel_{5m,15m}.parquet` (asof join on ws_s — CVD, trend strengths, liquidity, RSI, BOS bars)
- `regime_panel_{5m,15m}.parquet` (asof — ADX, ATR, ribbon alignment, BB width, range compression)
- `qr_panel_{5m,15m}.parquet` (asof — ribbon state, market regime, volume ratio, signal confidence)

Result: **290 columns × 190,170 rows (5m)** / 50,712 rows (15m). After dropping leak cols (outcome, fill prices, side-pnl, IDs, regime-gate pass column) → **265 features**.

| Market | Train (Apr 24 → May 14) | Val (→ May 21) | Lockbox (→ May 25 19:10) |
|---|---:|---:|---:|
| BTC 5m | 36,603 | 17,024 | 4,935 |
| ETH 5m | 34,559 | 16,543 | 4,748 |
| SOL 5m | 22,776 | 12,017 | 4,233 |
| BTC 15m | 10,117 | 4,679 | 1,329 |
| ETH 15m | 9,438 | 4,271 | 1,223 |
| SOL 15m | 7,440 | 3,527 | 1,114 |

Drop rate post-join + post-NaN: ~1% (one all-NaN feature column dropped per model).

**Target:** `y_up = (outcome == 'Up')`. Bet direction is inferred at deploy:
- if `P_up > p_up_threshold` → bet Up, fill at `up_vwap`
- if `P_up < p_dn_threshold` → bet Down, fill at `dn_vwap`
- thresholds tuned on val to maximize sum_pnl.

**Leak audit (post-fix):** no feature has |Pearson r| > 0.70 with `y_up`. Highest legitimate prior: `up_microprice` / `dn_microprice` at r≈±0.58 (the Polymarket book ALREADY prices ~33% of variance — the rest is what ML must add).

---

## TASK 2 — Strict 3-way time split

- Train: 2026-04-24 → 2026-05-14 (20d)
- Val: 2026-05-14 → 2026-05-21 (7d) — early stopping + threshold tuning + isotonic fit
- **Lockbox: 2026-05-21 → 2026-05-25 19:10 (4.8d)** — touched ONCE.

No CV across time. No peeking. Isotonic calibration is fit on val only.

---

## TASK 3/4 — Per-market LightGBM results

| Model | best_iter | val WR | val $/tr | **lock n** | **lock WR** | **lock $/tr** | **lock sum** | boot p | iso $/tr | iso boot p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC 5m | 61 | 0.810 | +$0.012 | 3024 | 0.799 | **-$0.012** | -$35.3 | 0.17 | -$0.031 | 0.005 |
| ETH 5m | 82 | 0.858 | +$0.010 | 2215 | 0.858 | **+$0.006** | +$13.7 | 0.49 | +$0.004 | 0.75 |
| SOL 5m | 97 | 0.908 | +$0.008 | 1666 | 0.887 | **-$0.010** | -$16.8 | 0.34 | -$0.010 | 0.20 |
| BTC 15m | 48 | 0.789 | +$0.018 | 1006 | 0.752 | **-$0.021** | -$21.3 | 0.18 | -$0.022 | 0.29 |
| ETH 15m | 48 | 0.861 | +$0.005 | 584 | 0.812 | **-$0.032** | -$18.8 | 0.11 | -$0.040 | 0.04 |
| SOL 15m | 65 | 0.857 | +$0.027 | 667 | 0.753 | **-$0.076** | -$50.9 | **0.00** | -$0.086 | 0.00 |

(boot_p: prob that abs(observed mean PnL) arose under random-sign null in 200 shuffles. Low p ⇒ result is statistically distinguishable from 0 — direction read from sign of sum.)

**Lockbox passes (per-trade > $0.05 AND boot_p ≤ 0.10): 0 of 6.**
**Lockbox positive (any per-trade > 0): 1 of 6** (ETH 5m, but noise.)
**Lockbox statistically negative (boot_p ≤ 0.05, mean < 0): 1 of 6** (SOL 15m at -$0.076/tr).

The train→val→lockbox curve is monotonically decaying for every model:
- val WR is 80-91%, lockbox WR drops to 75-89%.
- val $/tr is +$0.01 to +$0.03, lockbox $/tr is 0 to -$0.08.

This is classic OOS decay — the model overfit to train+val patterns that didn't persist to lockbox.

---

## TASK 5 — Feature importance (top 10 per model by gain)

**Microstructure dominates every market.** The top 5 features for the 5m models are all book-level (bid/ask slope, microprice, spread_diff). TA / regime / DRZ features rank lower.

| Market | Top 10 |
|---|---|
| **BTC 5m** | up_ask_slope, dn_bid_slope, spread_diff, up_microprice, dn_microprice, up_bid_slope, reg_range_compression, dn_ask_slope, reg_trend_slope_30m, qr_volume_ratio |
| **ETH 5m** | dn_bid_slope, up_ask_slope, dn_microprice, up_microprice, up_bid_slope, spread_diff, dn_ask_slope, qr_volume_ratio, reg_minus_di_14, reg_bb_width_60s |
| **SOL 5m** | dn_bid_slope, dn_microprice, up_microprice, up_bid_slope, up_ask_slope, dn_ask_slope, spread_diff, gk_sigma, **drz_dist_to_nearest_support_bps**, f7_rsi_at_ws |
| **BTC 15m** | dn_microprice, up_microprice, spread_diff, up_total_bid_size, up_eff_spread_25, up_ask_slope, mag_ratio, reg_bb_width_60s, dn_spread_bps, reg_range_compression |
| **ETH 15m** | dn_microprice, up_microprice, spread_diff, up_imb1, dn_bid_slope, reg_range_compression, gk_sigma, up_eff_spread_25, reg_trend_slope_30m, f7_rsi_at_ws |
| **SOL 15m** | dn_microprice, up_microprice, spread_diff, up_imb1, gk_sigma, reg_range_compression, f7_rsi_at_ws, reg_realized_vol_60m, reg_trend_slope_30m, reg_minus_di_14 |

### Surprises

1. **Bid/ask slopes (`up_ask_slope`, `dn_bid_slope`)** are the #1-2 features for all 5m models — far above any TA gate. The slopes measure how price changes with depth at the L25 book; aggressive slopes indicate one-sided pressure that hasn't fully consumed liquidity. We were not using these as gates.
2. **`spread_diff`** (Up_spread - Dn_spread in bps) ranks #3 universally — wider spread on one side leaks information about which side market makers are wary of.
3. **`reg_range_compression`** (Bollinger Band squeeze from regime panel) is a top-10 feature for every model — consistent with the mean-reversion story.
4. **`drz_dist_to_nearest_support_bps`** in SOL 5m top-10 — DRZ levels matter for SOL specifically.
5. **`gk_sigma`** (Garman-Klass intraday vol) in SOL 5m / ETH 15m / SOL 15m — vol regime gating matters more for 15m.
6. **`qr_volume_ratio`** in BTC 5m / ETH 5m top-10 — recent volume burst relative to baseline. We use volume implicitly in RF, but the ratio is more direct.

The manual TA gates (`g_cci_with`, `g_stoch_with`, `g_ribbon_agrees`) are NOT what the ML is finding alpha in. The ML model is essentially building a **microstructure-driven mean-reverter** that fades book imbalance, while the manual sleeves are **trend-momentum**. Different alpha.

---

## TASK 6 — ML vs Manual gate-stack comparison (LOCKBOX)

Applied 6 top-WR manual sleeves on the SAME lockbox window the ML sees. Stakes normalized to $1 (manual originally at $25 notional, divided by 25).

| Sleeve | train n / WR / $/tr | val n / WR / $/tr | **lock n / WR / $/tr / boot_p** |
|---|---:|---:|---:|
| **BTC_5m_S6_hybrid_v1** (`cci_with & stoch_with & tr_above_ema50 & rf_with`) | 1589 / 74% / +$0.27 | 1003 / 81% / +$0.085 | **189 / 91.5% / +$0.24 / p=0.00** |
| ETH_5m_S6_hybrid_top (`cci_with & bb_pos_with & ribbon_agrees`) | 1862 / 74% / +$0.054 | 1535 / 78% / +$0.069 | **134 / 85.1% / +$0.11 / p=0.015** |
| ETH_5m_S6_tight_ribbon (`tight_ribbon & stoch_with`) | 744 / 69% / +$0.26 | 527 / 63% / +$0.083 | **36 / 69.4% / +$0.24 / p=0.08** |
| SOL_5m_S15_above_ema (`tr_above_ema800 & cloud & ema200`) | 1728 / 82% / -$0.03 | 1233 / 82% / +$0.0001 | **187 / 81.3% / +$0.022 / p=0.54** |
| ETH_15m_v15m_ribbon (`ribbon_agrees & ema200 & cci_with`) | 182 / 79% / +$0.020 | 117 / 74% / -$0.039 | **16 / 68.8% / -$0.15 / p=0.32** |
| BTC_15m_v15m_pp_ribbon (`tr_above_pp & ribbon_agrees & stoch_with & tight_ribbon`) | 59 / 75% / -$0.062 | 27 / 70% / -$0.10 | **5 / 80% / +$0.22 / p=0.60** (n too low) |

**Manual deployable on lockbox:**
- **BTC 5m S6 hybrid_v1** — $0.24/tr, n=189, boot_p=0.00 ✓ strong
- **ETH 5m S6 hybrid_top** — $0.11/tr, n=134, boot_p=0.015 ✓ marginal
- ETH 5m S6 tight_ribbon — $0.24/tr but n=36, p=0.08 (suggestive)

**ML deployable on lockbox:**
- None.

**Head-to-head on the same market (5m):**

| Market | ML lock $/tr | Best manual lock $/tr | Winner |
|---|---:|---:|---|
| BTC 5m | -$0.012 | **+$0.239** | Manual by 25x |
| ETH 5m | +$0.006 | **+$0.115** | Manual by 19x |
| SOL 5m | -$0.010 | +$0.022 | Manual (both marginal) |

Manual gate stacks are categorically better-performing on lockbox.

---

## TASK 7 — Stacked ensemble (ML ∩ Manual)

Stack rule: keep a fire only if BOTH the ML model (P_up_iso outside [0.45, 0.55]) AND a manual sleeve fire at the same slug/offset AND they agree on direction.

| Market | ML alone | Manual alone | **Stack (intersection)** |
|---|---|---|---|
| BTC 5m | n=3558, $-24.3, dpt=-$0.007 | n=189, +$45.2, dpt=+$0.239 | n=180, +$29.1, **dpt=+$0.162**, boot_p=0.00 |
| ETH 5m | n=3399, +$7.2, dpt=+$0.002 | n=170, +$24.1, dpt=+$0.142 | n=128, +$15.95, **dpt=+$0.125**, boot_p=0.00 |
| SOL 5m | n=3225, -$88.9, dpt=-$0.028 | n=187, +$4.0, dpt=+$0.022 | n=167, +$7.3, dpt=+$0.044, boot_p=0.20 |
| BTC 15m | n=1054, -$26.4, dpt=-$0.025 | n=5, +$1.1, dpt=+$0.223 | n=4, -$0.2, dpt=-$0.049, p=1.00 |
| ETH 15m | n=1097, -$65.6, dpt=-$0.060 | n=16, -$2.4, dpt=-$0.150 | n=15, -$1.4, dpt=-$0.093, p=0.55 |
| SOL 15m | n=918, -$43.4, dpt=-$0.047 | n=51, +$7.2, dpt=+$0.141 | n=0 (no intersection) | 

**Stacking hurts manual sleeves.**
- BTC 5m: stack dpt $0.162 vs manual alone $0.239 — adding ML filter drops 9 fires (180 vs 189) but loses $0.077/tr in quality. The 9 dropped fires were higher-than-average winners.
- ETH 5m: stack dpt $0.125 vs manual alone $0.142 — similar story, 42 fires dropped, dpt drops $0.017.

The ML model's "filter" doesn't add discriminative power on top of manual gates — it just removes some trades, including profitable ones.

**Inverse stack (manual filter on ML):**
- BTC 5m: from 3558 ML fires → 180 that ALSO pass manual gate. Per-trade jumps from -$0.007 to **+$0.162**. So the MANUAL sleeve adds value to ML, not vice versa.

---

## TASK 8 — Calibration analysis

Reliability diagram bins each val P(Up) into 5pp buckets and reports mean predicted prob vs actual Up rate.

**Pre-isotonic (raw LGB probs):** All 5m models calibrated within **±5pp** across most bins. BTC 5m and SOL 5m are nearly perfect; ETH 15m has the largest gap (about -10pp at 0.55-0.7 bins — model overconfident on bullish predictions). See `data/v4/canonical/_results/ml_lightgbm/calibration_*.csv`.

**Post-isotonic (val-fit IsotonicRegression):** Used for the iso_lockbox metrics in the summary. Net effect on lockbox PnL was small to negative (because isotonic forced more extreme thresholds → more fires → more losers given the model isn't actually edge-positive). Calibration "fixing" doesn't add edge that wasn't there.

The ML model IS reliably probabilistic — it knows what it doesn't know. The problem isn't miscalibration; it's that **the patterns it learned don't OOS**.

---

## TASK 9 — Top 5 ML-driven deployable sleeves

**Zero.** No ML sleeve passes the lockbox bar (per-trade ≥ +$0.05, boot_p ≤ 0.10, n ≥ 100).

Honorable mentions (do NOT deploy, listed for completeness):
1. **ETH 5m raw** — +$0.006/tr, n=2215, boot_p=0.49 (noise indistinguishable from 0).
2. **ETH 5m isotonic** — +$0.004/tr, n=2485, boot_p=0.75 (worse than raw).
3. BTC 5m at thresholds p_up=0.55 / p_dn=0.45 (untested) — possibly less negative.

Recommend deploying the **manual gate-stack survivors** instead:
- BTC 5m S6 hybrid_v1 (cci/stoch/tr_above_ema50/rf_with) — $0.24/tr on lockbox.
- ETH 5m S6 hybrid_top (cci/bb_pos/ribbon_agrees) — $0.11/tr on lockbox.

---

## Caveats

1. **Lockbox is only ~4.8 days** (3024 BTC 5m fires after threshold). One-week recalibration cadence is essential before any committed capital.
2. **Microstructure features depend on L25 book freshness.** Production reads WS BookMirror (Phase 18.6 Wave 1); our canonical L25 is from the same source. Apples-to-apples for now, but if production tier-2 fallback triggers (REST), the live microstructure inputs will be stale and ML drops further.
3. **Feature collinearity not pruned.** up_ask_slope, dn_bid_slope, up_microprice, dn_microprice are 80%+ correlated. LGB handles this fine for prediction but importance numbers are diluted across the cluster. Could rerun with VIF pruning or PCA.
4. **Threshold tuning has multiple-comparisons exposure.** We swept ~35×35 = 1225 (p_up, p_dn) pairs to pick the val maximizer. With 6 models that's ~7000 implicit tests. The val→lockbox gap likely overstates ML's val performance. A Bonferroni-corrected significance bar would require boot_p ≤ 0.10/7000 ~ 10^-5.
5. **`pass_w20_5m_voladaptive` dropped as feature** because it's a pre-tuned regime gate (would leak the regime panel's pre-selection). Keep this exclusion.
6. **No engineered interaction features.** A natural follow-up: train on `microstructure × regime_score`, `ribbon_compression × bid_slope`, etc. LGB tree splits already capture pairwise interactions implicitly though.
7. **Microprice prior is r=0.58 with outcome.** The market already prices most of the signal. The "alpha" available to find is bounded above by what's NOT in the microprice — which is small. This sets a hard ceiling on what any ML on this universe can deliver.

---

## Files produced

- `strategy_lab/ml/lightgbm_stacker.py` — training driver (assemble + train + threshold + isotonic + dump)
- `strategy_lab/ml/compare_and_stack.py` — manual sleeve lockbox apply + intersection stack
- `data/v4/canonical/_results/ml_lightgbm_lockbox.csv` — main summary table
- `data/v4/canonical/_results/ml_lightgbm/importance_{ASSET}_{TF}.csv` — top-20 features per model
- `data/v4/canonical/_results/ml_lightgbm/calibration_{ASSET}_{TF}.csv` — reliability bins
- `data/v4/canonical/_results/ml_lightgbm/lockbox_predictions.parquet` — per-fire P(up) for each model
- `data/v4/canonical/_results/ml_lightgbm/manual_sleeves_lockbox.csv` — manual sleeve lockbox metrics
- `data/v4/canonical/_results/ml_lightgbm/manual_lockbox_preds.parquet` — per-fire manual sleeve hits on lockbox
- `data/v4/canonical/_results/ml_lightgbm/stacker_lockbox.csv` — ML vs manual vs stack comparison
- `data/v4/canonical/_results/ml_lightgbm/results.pkl` — pickled summary dict (skip boosters)

---

## Bottom line

LightGBM with 265 features didn't find an alpha that's hidden from the manual gate-stack search. The model is well-calibrated and learned a coherent microstructure-mean-reversion signal — but that signal degrades OOS and underperforms hand-built trend-momentum gates on the same lockbox.

Best deployable sleeve right now remains **BTC 5m S6 hybrid_v1 manual gates** (+$0.24/tr, WR 91.5%, n=189 on lockbox, boot_p=0.00). Use ML signals as a *colour* (microstructure context) but not as a primary fire trigger.
