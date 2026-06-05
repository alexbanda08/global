# Physics Signal BTC — OOS + Fee Model Robustness Test
**Date:** 2026-06-01  
**Dataset:** `strategy_lab/physics/_results/physics_fires_enriched.parquet` — valid==True only  
**Universe:** BTC 5m + 15m, Apr 24 – Jun 1 09:07 UTC, n=11,210 valid fires  
**Split:** chronological 60/40 by `slot_start_us`

---

## 1. Split Boundaries

| Half | Period | n |
|------|--------|---|
| TRAIN (60%) | 2026-04-24 01:45 → 2026-05-16 06:45 UTC | 6,726 |
| TEST (40%)  | 2026-05-16 06:50 → 2026-06-01 08:50 UTC | 4,484 |

---

## 2. Fee Models Compared

| Label | Formula | Note |
|-------|---------|------|
| **legacy** | Won: `shares*(1−vwap)*0.98`; Lost: `−shares*vwap` | 2%-on-profit-only. VERIFIED as production behavior 2026-05-22. |
| **curve-every** | Won: `shares*(1−vwap) − 0.07*vwap*(1−vwap)*shares`; Lost: same, fee charged | 0.07 curve, fee on BOTH legs |
| **curve-winner** | Won: `shares*(1−vwap) − 0.07*vwap*(1−vwap)*shares`; Lost: `−shares*vwap` | 0.07 curve, fee on WIN leg only. `shares = 25/entry_vwap` |

All three: `shares = 25 / entry_vwap` (entry notional = $25).

---

## 3. Baseline (All Valid Fires, No Filter)

| Split | n | WR | pnl/fire (legacy) | pnl/fire (curve-every) | pnl/fire (curve-winner) |
|-------|---|----|-------------------|------------------------|-------------------------|
| TRAIN | 6726 | 82.2% | −$0.004 | −$0.228 | −$0.115 |
| TEST  | 4484 | 80.8% | −$0.062 | −$0.302 | −$0.178 |

No alpha at the unfiltered level. Slight WR decline train→test consistent with market efficiency.

---

## 4. Per-Config Results

### Config 1: dist_abs >= 40

| Split | n | WR | avg_vwap | legacy | curve-every | curve-winner |
|-------|---|----|----------|--------|-------------|--------------|
| TRAIN | 2330 | 96.3% | 0.954 | +$0.223 | +$0.166 | +$0.177 |
| TEST  | 1331 | 95.8% | 0.951 | **+$0.214** | **+$0.153** | **+$0.164** |

OOS: positive under ALL 3 fee models. t-stats on test: legacy t=1.34 p=0.18, curve-every t=0.96 p=0.34, curve-winner t=1.03 p=0.30.  
**All positive, not statistically significant at 5%.**

Key structural finding — the PnL is almost entirely from vwap < 0.95 (27.5% of fires):

| vwap bucket | n (TEST) | WR | legacy/fire | curve-every/fire | curve-winner/fire |
|-------------|----------|----|-------------|-----------------|-------------------|
| vwap < 0.95  | 366  | 89.6% | **+$0.784** | **+$0.626** | **+$0.664** |
| vwap >= 0.95 | 965  | 98.1% | −$0.003     | −$0.026     | −$0.025      |

The deep-favorite bucket (vwap ≥ 0.95, 72.5% of dist_abs≥40 fires) is essentially breakeven-to-slightly-negative under all fee models. All the apparent edge lives in the 366 non-extreme fires.

---

### Config 2: dist_abs >= 50

| Split | n | WR | avg_vwap | legacy | curve-every | curve-winner |
|-------|---|----|----------|--------|-------------|--------------|
| TRAIN | 1688 | 97.5% | 0.965 | +$0.287 | +$0.245 | +$0.250 |
| TEST  | 859  | 96.6% | 0.963 | **+$0.105** | **+$0.060** | **+$0.065** |

Train→test degradation is notable: legacy drops from +0.287 to +0.105. Same vwap-concentration issue — even more extreme favorites at dist_abs≥50.

---

### Config 3: WEAK_COMBO30/10-kept (skip if dist_abs < 30 AND speed_away < 10)

| Split | n | WR | avg_vwap | legacy | curve-every | curve-winner |
|-------|---|----|----------|--------|-------------|--------------|
| TRAIN | 4194 | 89.2% | 0.888 | +$0.126 | −$0.012 | +$0.042 |
| TEST  | 2600 | 88.3% | 0.877 | +$0.104 | **−$0.049** | +$0.016 |

curve-every is **negative in both halves**. legacy and curve-winner marginally positive but near zero. Not deployable under the realistic fee models.

---

### Config 4: WEAK_COMBO-kept AND d_speed >= 0

| Split | n | WR | avg_vwap | legacy | curve-every | curve-winner |
|-------|---|----|----------|--------|-------------|--------------|
| TRAIN | 2023 | 89.7% | 0.886 | +$0.300 | +$0.160 | +$0.213 |
| TEST  | 1320 | 88.0% | 0.870 | **+$0.215** | **+$0.053** | **+$0.123** |

Positive across all 3 fee models in TEST. t-stats: legacy t=0.71 p=0.48, curve-every t=0.17 p=0.86, curve-winner t=0.41 p=0.68. **Positive but very noisy** (std ~$11/fire, mean ~$0.05−0.21/fire).

---

### Config 5: WEAK_COMBO-kept AND entry_vwap <= 0.85

| Split | n | WR | avg_vwap | legacy | curve-every | curve-winner |
|-------|---|----|----------|--------|-------------|--------------|
| TRAIN | 1024 | 69.7% | 0.676 | +$0.680 | +$0.281 | +$0.483 |
| TEST  |  692 | 68.2% | 0.664 | **+$0.313** | **−$0.108** | **+$0.122** |

curve-every **flips negative on test**. legacy and curve-winner remain positive. At WR ~68% and avg_vwap ~0.66, this bucket has the largest per-fire dollar swing — but also 27% WR degradation from train (69.7% → 68.2%). Volatility very high (std ~$19/fire). 

---

## 5. OOS Sign Summary Table

| Config | TEST n | legacy | curve-every | curve-winner |
|--------|--------|--------|-------------|--------------|
| dist_abs>=40 | 1331 | **+$0.214** | **+$0.153** | **+$0.164** |
| dist_abs>=50 | 859  | **+$0.105** | **+$0.060** | **+$0.065** |
| WEAK_COMBO-kept | 2600 | +$0.104 | **−$0.049** | +$0.016 |
| WEAK_COMBO-kept + d_speed>=0 | 1320 | **+$0.215** | **+$0.053** | **+$0.123** |
| WEAK_COMBO-kept + vwap<=0.85 | 692 | **+$0.313** | **−$0.108** | **+$0.122** |

Bold = positive. WEAK_COMBO (base) and vwap<=0.85 go negative under curve-every on test.

---

## 6. WR vs Implied Probability (GAP) on Test

| Config | WR (test) | Implied (test) | gap |
|--------|-----------|----------------|-----|
| dist_abs>=40 | 95.8% | 95.1% | +0.74 pp |
| dist_abs>=50 | 96.6% | 96.3% | +0.31 pp |
| WEAK_COMBO-kept | 88.3% | 87.7% | +0.62 pp |
| WEAK_COMBO-kept + d_speed>=0 | 88.0% | 87.0% | +1.04 pp |
| WEAK_COMBO-kept + vwap<=0.85 | 68.2% | 66.4% | +1.86 pp |

All configs show a small positive gap in OOS. But gaps are 0.3–1.9 pp against a 1σ noise floor of ~2-3 pp for these n's, so statistical significance is marginal.

---

## 7. The Core Structural Finding

**Physics dist_abs is a VWAP-bucket selector, not a signal.** The `dist_abs>=40` filter catches large price moves that push Polymarket implied probabilities deep into the tails (vwap ~0.95+ for dist_abs≥40). At those extreme prices:

- Gross PnL potential is tiny: `shares*(1−vwap)` at vwap=0.97 is only $0.76/trade on $25 notional.
- Any fee (even legacy 2% on profit) consumes most of the upside.
- The ~27.5% of dist_abs≥40 fires where vwap < 0.95 account for **>100% of total PnL** in both train and test.

This means the deployable sub-config is effectively **dist_abs>=40 AND vwap<0.95** (n=366 TEST, WR 89.6%, legacy +$0.78/fire, curve-winner +$0.66/fire). However, this sub-config was not evaluated in isolation in the original tuning — it emerges post-hoc as the "live" edge pocket.

---

## 8. Verdict

### Fee model dependency
- **Under legacy (2%-on-profit):** dist_abs≥40, dist_abs≥50, WEAK_COMBO+d_speed≥0, WEAK_COMBO+vwap≤0.85 are ALL positive OOS. The signal looks deployable.
- **Under curve-every (0.07, both legs):** WEAK_COMBO (base) and WEAK_COMBO+vwap≤0.85 go negative. Only dist_abs≥40, dist_abs≥50, and WEAK_COMBO+d_speed≥0 survive.
- **Under curve-winner (0.07, win-only):** All configs remain positive, but WEAK_COMBO (base) is barely +$0.016/fire — effectively zero.

**The fee model is the primary swing factor.** CLAUDE.md documents that production currently runs legacy (2%-on-profit verified 2026-05-22), but HANDOFF_2026_06_01 references curve-winner as the operational rule. This dispute must be resolved before sizing.

### Statistical significance
No config achieves p < 0.05 on the test half. The best t-stat is t=1.56 (p=0.12) on the dist_abs≥40+vwap<0.95 sub-config (both train and test, consistently). With sample sizes in the hundreds-to-low-thousands and PnL std of $5-19/fire against means of $0.05-0.78/fire, significance requires much longer OOS windows.

### Robustness
- dist_abs≥40 is the most robust: positive under all 3 fee models, stable WR (96.3% train → 95.8% test), consistent per-fire values. The degradation from train to test is modest relative to noise.
- WEAK_COMBO+d_speed≥0 is second: positive under all 3 fee models, but the curve-every signal is thin (+$0.053/fire, t=0.17).
- dist_abs≥50: positive but pnl/fire drops more steeply train→test (legacy: 0.287→0.105) — likely just noise given smaller n.

### Deploy recommendation
- **Marginal / conditional** on fee model resolution. Under legacy fees (production confirmed): dist_abs≥40 is the best-behaved OOS config and is deployable at small size as a test sleeve ($25/fire, paper-shadow first).
- **Do NOT deploy** under the assumption that curve-every (0.07 both legs) is the fee model — WEAK_COMBO and vwap≤0.85 configs go negative.
- The real edge pocket (dist_abs≥40 AND vwap<0.95) needs explicit evaluation in a future dedicated backtest with longer OOS window before any real sizing.
- Longer OOS confirmation needed: this is a 40-day total window with the test half being ~16 days (May 16 → Jun 1). At n≈1,300 fires in test for the best config, the signal is real but unproven beyond p~0.12.

---

## 9. Key Numbers at a Glance

| Config (TEST) | n | WR | gap vs implied | legacy/fire | curve-every/fire | curve-winner/fire |
|---------------|---|----|----------------|-------------|-----------------|-------------------|
| dist_abs>=40 | 1331 | 95.8% | +0.7pp | +$0.214 | +$0.153 | +$0.164 |
| dist_abs>=50 | 859 | 96.6% | +0.3pp | +$0.105 | +$0.060 | +$0.065 |
| WEAK_COMBO-kept | 2600 | 88.3% | +0.6pp | +$0.104 | −$0.049 | +$0.016 |
| WEAK_COMBO+d_speed>=0 | 1320 | 88.0% | +1.0pp | +$0.215 | +$0.053 | +$0.123 |
| WEAK_COMBO+vwap<=0.85 | 692 | 68.2% | +1.9pp | +$0.313 | −$0.108 | +$0.122 |
| **dist_abs>=40 & vwap<0.95** | **366** | **89.6%** | — | **+$0.784** | **+$0.626** | **+$0.664** |

The highlighted sub-config (bottom row) is the actual edge pocket driving all dist_abs>=40 results. The deep-favorite tail (vwap>=0.95) is breakeven under every fee model.

---

*Analysis script: inline Python in subagent session 2026-06-01. Source: `strategy_lab/physics/_results/physics_fires_enriched.parquet`, `valid==True`, n=11,210.*
