# Physics Signal — Master Synthesis Report
**Date:** 2026-06-01  
**Author:** Analysis agent (synthesis of 4 sub-investigations)  
**Status:** INVESTIGATION COMPLETE — NOT DEPLOYABLE (see §7)

---

## Executive Summary

We implemented and fully tested a physics-of-BTC continuation signal on Polymarket up-down markets. The core finding is that the signal is **priced in**: the all-fires realized WR (81.6%) equals market-implied probability (81.5%), yielding gap ≈ 0 and negative or near-zero net PnL under all fee models. High win rates are deep-favorite pricing, not alpha. Two structural sub-pockets show persistent positive EV — `dist_abs>=40` (fee-curve convexity artifact) and the cheap-favorite band `entry_vwap<=0.85` (the only real anomaly) — but neither reaches statistical significance on OOS data (best t=1.68, p=0.094). Physics gates fail completely on ETH (wrong scale) and add nothing to the four winning sleeves tested. The sole actionable recommendation is to run 22+ additional OOS days on the `dist_abs>=40 & vwap<0.95 & spread<=0.02` sub-pocket (BTC only, ~21 fires/day) before any deployment decision. **The primary blocker before sizing anything is confirming the live fee model in production — the verdict does not flip but sizing does.**

---

## 1. What the Physics Signal Is

The signal is based on the physical dynamics of BTC price relative to the current Polymarket slug's strike price. At `fire_us = slot_end_us - 60s` (60 seconds before slug settlement), the signal reads:

- **`dist`**: signed BTC price minus strike (negative = below strike, positive = above)
- **`dist_abs`**: absolute distance in USD
- **`side`**: +1 if BTC is above strike (bet UP), -1 if below (bet DOWN)
- **`bet`**: CONTINUATION — bet the side BTC is currently on
- **`speed`**: rate of change of BTC price in the last N seconds
- **`speed_away`**: component of speed moving away from the strike
- **`d_speed`**: delta speed over last 30s (acceleration in the continuation direction)
- **`cross`**: whether BTC has crossed the strike since window open
- **`margin`**: price margin above the current implied probability threshold

The hypothesis (from the physics article) is that once BTC has moved decisively away from strike, the combination of price momentum and convexity of the payoff function makes continuation bets positive EV.

### Implementation

- **Signal code:** `strategy_lab/physics/physics_signal.py` — `physics_at(ts_us, px, strike, fire_us, slot_end_us, speed_win_s=60)` returns the full feature dict
- **Enrichment build:** Built for BTC (11,210 valid fires, Apr 24 – Jun 1) and ETH (3,369 valid fires, May 19 – Jun 1)
- **Canonical enriched parquet:** `strategy_lab/physics/_results/physics_fires_enriched.parquet`
- **ETH enriched parquet:** `strategy_lab/physics/_results/physics_fires_enriched_eth.parquet`
- **Sub-investigation reports:**
  - `PHYSICS_OOS_FEE_2026_06_01.md` — OOS train/test split + 3 fee models
  - `PHYSICS_FILL_REALISM_2026_06_01.md` — 1Hz/10Hz sensitivity, spread/depth, favorite-longshot bias
  - `PHYSICS_ETH_GENERALIZE_2026_06_01.md` — ETH scaling and generalization
  - `PHYSICS_OVERLAY_WINNERS_2026_06_01.md` — overlay on 4 winning production sleeves

---

## 2. Headline Finding: Signal Is Priced In

**The physics continuation signal has gap ≈ 0 across the full BTC universe.**

| Universe | n | Realized WR | Market-Implied WR | Gap |
|----------|---|-------------|-------------------|-----|
| BTC all valid fires (Apr 24 – Jun 1) | 11,210 | 81.6% | 81.5% | **+0.1 pp** |
| BTC TEST half (May 16 – Jun 1) | 4,484 | 80.8% | — | ~0 pp |

The high realized WR is not alpha. A bet on BTC continuing past strike with 81% WR costs ~$0.82 in implied probability — the market has already priced the continuation premium into the book. Unfiltered net PnL:

| Fee model | BTC all-fires PnL/fire |
|-----------|----------------------|
| Legacy (2%-on-profit, verified production) | -$0.023/fire |
| Curve-every (0.07 both legs, harshest) | -$0.257/fire |
| Curve-winner (0.07 win-only) | -$0.139/fire |

**Conclusion:** Betting physics continuation naively loses money under the real fee structure. The question is whether any filtered sub-pocket is genuinely +EV.

---

## 3. Structural Sub-Pockets: Real but Modest

### 3.1 dist_abs >= 40 (BTC only)

When BTC is $40+ from the strike at fire time, implied probability rises to ~95%+ and the fee curve becomes convex-favorable.

| Split | n | WR | Implied | Gap | Legacy $/fire | Curve-winner $/fire | Curve-every $/fire |
|-------|---|----|---------|-----|---------------|--------------------|--------------------|
| TRAIN | 2,330 | 96.3% | 95.4% | +0.9 pp | +$0.223 | +$0.177 | +$0.166 |
| TEST | 1,331 | 95.8% | 95.1% | +0.7 pp | **+$0.214** | **+$0.164** | **+$0.153** |

OOS is positive under all three fee models. However: **OLS slope of gap vs dist_abs = +0.000166 pp/dollar, p=0.37, R²=0.00018.** The gap does NOT grow with distance. This is NOT physics alpha — it is fee-curve convexity at high implied probability. The dist>=40 filter selects a high-vwap subset where the 2%-on-profit fee model produces structural positive EV because the payoff asymmetry dominates the fee.

**Key sub-pocket:** `dist_abs>=40 & entry_vwap<0.95`

| Split | n | WR | Implied | Gap | Legacy $/fire | Curve-winner $/fire |
|-------|---|----|---------|-----|---------------|---------------------|
| TRAIN | 1,365 | 93.1% | 89.8% | +3.3 pp | +$0.784 | +$0.664 |
| TEST | 343 | 90.1% | 87.3% | **+2.8 pp** | **+$0.853** | **+$0.818** |

This sub-pocket drives 100%+ of the dist>=40 EV. The vwap>=0.95 tier (n=965 test, 72% of dist>=40) is breakeven to slightly negative under all models (gap=+0.03 pp, PnL=-$0.002 to +$0.006/fire).

**Fill realism test (1Hz vs 10Hz):** vwap delta = +0.00061, PnL delta = -$0.013/fire. PASS — book sampling frequency is not a material risk factor for this pocket.

**Spread quality:** dist>=40, p50 spread=0.01, p90=0.01, 95.9% of fills tight. PASS.

### 3.2 Speed-Derivative Gate (d_speed >= 0)

The original physics article hypothesizes that price acceleration in the continuation direction is a predictive signal. We test `WEAK_COMBO(skip if dist<30 AND speed_away<10) & d_speed>=0`:

| Split | n | WR | Implied | Gap | Legacy $/fire | Curve-winner $/fire |
|-------|---|----|---------|-----|---------------|---------------------|
| TRAIN | 2,023 | 90.0% | 88.1% | +1.9 pp | +$0.267 | +$0.123 |
| TEST | 1,320 | 89.2% | 88.2% | **+1.0 pp** | **+$0.215** | **+$0.123** |

The d_speed>=0 gate does select for positive-momentum continuation, consistent with the article's hypothesis. However: OOS t=0.71 (legacy), p=0.48. Not significant. The gap degrades modestly train→test (+1.9 pp → +1.0 pp), suggesting the speed-derivative captures a real tendency but one that is noisy at the $25/fire scale.

### 3.3 Cheap-Favorite Gap (entry_vwap <= 0.85)

The sub-pocket with the most anomalous gap signal:

| Universe | n | WR | Implied | Gap | Curve-every $/fire | Legacy $/fire |
|----------|---|----|---------|-----|-------------------|---------------|
| BTC all-fires | 1,716 | 69.1% | 67.1% | **+2.0 pp** | +$0.125 | +$0.532 |

This is the only pocket where the WR gap materially exceeds the implied level AND the fee impact is manageable. The structural rationale is coherent: at vwap 0.65–0.85, the market is pricing a moderate continuation edge but the realized edge is consistently larger, possibly due to slower book repricing in this mid-range or partial participation from market makers.

**Fee-model dependency here IS a swing factor:** WEAK_COMBO + vwap<=0.85 goes from +$0.122/fire (curve-winner) to potentially negative under curve-every in OOS. However the dist>=40 & vwap<0.95 pocket (a cleaner version of this) stays positive under all three models.

**Spread caveat:** In the vwap<=0.85 pocket, 12.6% of fills have spread>0.02 and those earn -$1.34/fire (curve) vs +$0.34 for tight fills. **A mandatory `spread<=0.02` filter is required in live deployment of this pocket.**

### 3.4 WEAK_COMBO Threshold Recovery

The WEAK_COMBO filter (skip fires where `dist_abs<30 AND speed_away<10`) was tuned to maximize WR, not PnL. Key finding: **PnL-optimal thresholds ≠ WR-optimal thresholds.**

Recovered thresholds from tuning:
- `dist_abs` boundary: 30–40 (below which weak signals dominate)
- `speed_away` boundary: 10–15 (below which price is drifting, not accelerating away)
- **Composite gate adds marginal complexity for minimal gain over pure `dist>=40`**

Under real fees, `dist_abs>=40` alone matches or beats the two-parameter WEAK_COMBO in OOS PnL because the pure distance filter more cleanly selects the fee-convexity regime. The speed component adds noise at this sample size.

---

## 4. Overlay on Winning Production Sleeves

**Result: Physics gates do not improve net PnL on any target sleeve.**

Tested on 4 sleeves over May 27 – Jun 1 (5-day window, 327 total fires from `fires_resolved_all.parquet` with correct fire offsets — NOT `all_sleeve_fires.parquet` which uses lookahead `fire_us=slot_end_us`):

| Sleeve | Fires | Base WR | Base PnL |
|--------|-------|---------|----------|
| ETH 5m hurst-A | 107 | 73.0% | $48.22 |
| ETH 5m hurst-B | 84 | 73.2% | $40.17 |
| ETH 5m hurst-C | 78 | 73.1% | $39.83 |
| BTC 15m ema50/ema800 | 58 | 79.3% | $43.40 |
| **Combined** | **327** | **74.0%** | **$171.62** |

Best gate attempt — BTC 15m `dist_abs>=40`: WR 94.1% (n=34) but net PnL -$14 vs unfiltered $43.40. The gate cuts 41% of the fires, including high-WR profitable fires the physics screen incorrectly rejects.

**Fundamental incompatibility for ETH:** ETH price ≈ $2,000; max `dist_abs` observed in the enriched ETH parquet = $5.28. The BTC-tuned `dist_abs>=40` blocks 100% of ETH fires by construction. Physics thresholds cannot be applied cross-asset without complete re-scaling and re-tuning.

**Fundamental sparsity for BTC 15m Cyclops:** Expected physics overlap at the Cyclops sleeve's fire rate ≈ 0.14 physics-qualifying fires/day. Statistically worthless for overlay — not enough fires to form a usable gate even if the physics edge were real.

---

## 5. ETH Generalization

**Result: Indeterminate — not killed but not confirmable from 14 days of data.**

ETH enrichment (May 19 – Jun 1, n=3,369 valid fills) shows direction-consistent but attribution-ambiguous results:

| Filter | n | WR | Implied | Gap | Curve $/fire |
|--------|---|----|---------|-----|-------------|
| ALL ETH | 3,369 | 85.4% | 84.2% | **+1.2 pp** | +$0.499 |
| dist>=1.0 (BTC $40 equivalent) | 1,531 | 96.0% | 94.9% | +1.1 pp | +$0.407 |
| WC-scaled + d_speed>=0 | 1,296 | 85.0% | 84.1% | +0.9 pp | +$0.425 |
| WC + d_speed + vwap<=0.85 | 316 | gap | gap | +3.0 pp | +$1.82 |

**Attribution problem:** The ETH dist>=1.0 sub-pocket shows +1.1 pp gap — exactly matching the unfiltered ETH baseline gap (+1.2 pp) over the same 14-day window. The filter adds zero marginal alpha over just being long ETH continuation during what appears to be a favorable continuation regime across the entire May 19 – Jun 1 window. Both weeks 21 and 22 showed +1.4 pp all-baseline gap; Jun 1 partial day reversed to -6.4 pp.

The 14-day window is too short to separate filter alpha from regime alpha. **Need 30+ days of ETH enrichment (roughly May through July) to generate a clean test.** BTC required 38 days to reveal a gap≈0 baseline with real signal in sub-pockets.

BTC reference for comparison: dist>=40 curve=+$0.161 (n=3,661 over 38 days), WC+ds curve=+$0.118 (n=3,343), all-baseline=-$0.257 (n=11,210). BTC all-baseline was near-zero — which is why filter pockets were isolable. ETH all-baseline being strongly positive makes isolation impossible.

---

## 6. Fill-Realism Caveats

Three fill-realism audits conducted on the BTC enriched parquet:

**Test 1 — 1Hz vs 10Hz book sampling (n=390 dist>=40 fires, 5-day mid-dataset window):**  
vwap delta = +0.00061, PnL delta = -$0.013/fire. **PASS.** Book sampling frequency is not a material risk factor at 1Hz for this pocket. (Note: this test was bounded to a low-volatility 5-day window; extremely volatile days may show larger sensitivity.)

**Test 2 — Spread and depth quality:**

| Pocket | n | p50 spread | p90 spread | % tight fills |
|--------|---|-----------|-----------|--------------|
| dist>=40 | 3,661 | 0.01 | 0.01 | 95.9% |
| WEAK_COMBO+d_speed>=0 | 3,343 | 0.01 | 0.02 | 87.4% |
| WEAK_COMBO+vwap<=0.85 | 1,716 | 0.02 | 0.04 | **87.4% (12.6% spread>0.02)** |

**PASS for dist>=40.** The vwap<=0.85 pocket requires `spread<=0.02` filter: tight-book fills earn +$0.34/fire (curve) while wide-book fills earn -$1.34/fire.

**Test 3 — Favorite-longshot bias (does gap grow with dist?):**  
OLS slope = +0.000166 pp/dollar, p=0.37, R²=0.00018. **FLAT.** The gap does not increase with distance from strike. This falsifies the physics-alpha narrative and confirms the dist>=40 edge is a fee-curve artifact, not a predictive signal about price dynamics.

---

## 7. Adversarial Verdict on Deployability

### NOT DEPLOYABLE in any form right now.

The strongest +EV claim is `dist_abs>=40 & entry_vwap<0.95 & spread<=0.02` (BTC only, ~21 fires/day, $25/fire notional):

| Metric | Value |
|--------|-------|
| OOS fires (TEST, May 16 – Jun 1) | 343 |
| OOS WR | 90.1% vs 87.3% implied |
| OOS gap | +2.8 pp |
| OOS PnL/fire (legacy) | +$0.853 |
| OOS PnL/fire (curve-winner) | +$0.818 |
| t-statistic (legacy) | **1.68** |
| p-value | **0.094** |
| Daily Sharpe | 0.29 |
| Daily t-stat | 1.21, p=0.245 |

These fail any standard significance bar (p<0.05). The bad-week instability is material: **week 20 (May 16-17): WR=72.2% vs implied 83.2%, gap=-10.9 pp, $-121 total** (binomial p=0.079, borderline significant as a bad week). This single partial bad week wipes most of the test period's profit.

**Statistical power requirement:** Under optimistic assumptions (constant gap +2.8 pp, iid), need 22+ more OOS days for p<0.05. If week-20-type regime breaks recur at even 10% frequency, need 3+ months to establish significance against the null of zero.

### Strongest Real Finding (not yet proven)

The `dist_abs>=40 & entry_vwap<0.95 & spread<=0.02` sub-pocket (BTC only) shows:
- Directionally consistent OOS WR gap (+2.8 pp) across 343 test fires / 16 days
- Positive PnL under ALL three fee models (legacy, curve-winner, curve-every)
- Consistent week-over-week in weeks 21-22-23 (WR 92-93%, +$1.35/fire, t=2.83, p=0.005 in isolation — but this is cherry-picking after observing the bad week 20)
- Structural rationale is coherent (mid-vwap band 0.87–0.95 may partially underprice decisive continuation)
- Fill realism passes (1Hz/10Hz negligible, 94% tight-book fills)

**This is a real candidate signal — just not proven at significance yet.**

### Killed Claims

| Claim | Verdict | Reason |
|-------|---------|--------|
| dist>=40 IS physics alpha | KILLED | OLS gap-vs-dist slope p=0.37; gap is fee-convexity artifact, not predictive |
| Physics overlay on winning sleeves | KILLED | ETH: $40 blocks 100% of fires by scale; BTC 15m Cyclops: 0.14 overlap fires/day |
| ETH generalization confirmed | KILLED | ETH filter gap (+1.1 pp) matches unfiltered ETH baseline (+1.2 pp); no marginal alpha isolable |
| WC+d_speed>=0 as standalone | KILLED | OOS t=0.71, p=0.48; never significant even in-sample |
| Any config reaches p<0.05 OOS | KILLED | Best OOS t=1.68 (p=0.094). t=2.83 for weeks 21-23 is post-hoc cherry-pick |

---

## 8. Fee Model — The Outstanding Blocker

The fee model dispute does NOT reverse the directional finding for the `dist_abs>=40 & vwap<0.95` sub-pocket (positive under all three models). However, it materially affects sizing and the verdict on WEAK_COMBO+vwap<=0.85:

| Fee model | dist>=40 & vwap<0.95 OOS $/fire | WEAK_COMBO+vwap<=0.85 $/fire |
|-----------|--------------------------------|------------------------------|
| Legacy (2%-on-profit-only) | +$0.853 | +$0.532 |
| Curve-winner (0.07, win-only) | +$0.818 | +$0.122 |
| Curve-every (0.07, both legs) | +$0.626 | possibly negative |

**Fee model identification from parquet:** The enriched parquet `pnl_curve` column is confirmed as the curve-every (both-legs) model — match error 8×10⁻⁶ vs 0.076 for winner-only. The `pnl_legacy` column matches 2%-on-profit-only with error 4.9×10⁻⁵ (definitive).

**CLAUDE.md reconciliation:** The 2026-05-22 verification against 25,900 production `poly_updown_resolution` events confirms production charges 2%-on-profit-only (legacy) for the BTC/ETH/SOL up-down crypto markets. The HANDOFF_2026_06_01 reference to `0.07·p·(1-p) winner-only` is the fee model spec for the general Polymarket CLOB, which may not apply to these specific market contracts.

**Action required before any sizing decision:** Pull the Polymarket account dashboard for monthly fee/rebate line items and confirm whether `feeRate > 0` for the BTC/ETH/SOL up-down contracts. If legacy is confirmed, expected daily EV at $25/fire × 21 fires/day ≈ +$18/day with high variance.

---

## 9. Next Steps and Recommendations

### Immediate (Week 1)

1. **BLOCKER — Confirm fee model:** Check Polymarket dashboard for fee charges on BTC/ETH/SOL up-down markets. Confirm whether `feeRate=0` (legacy applies) or `feeRate=0.07` (curve applies). This is the most important single action before any deployment decision.

2. **Continue OOS accumulation on primary pocket:** The `dist_abs>=40 & entry_vwap<0.95 & spread<=0.02` filter needs ~22 more OOS days minimum (target: reach n≥600 OOS fires, t≥2.0). Track weekly WR vs implied and flag if another week-20-type breakdown occurs.

3. **Log live physics features:** If any sleeve is deployed on BTC (e.g., Cyclops BTC 15m), log the physics features at each fire so real fill data accumulates for the physics pocket. Passive OOS collection costs nothing.

### Short-term (Weeks 2-4)

4. **ETH threshold re-tuning:** Collect 30+ days of ETH enrichment, then re-run the OOS test with ETH-native thresholds (`dist_abs>=1.0`, speed thresholds scaled by ETH/BTC price ratio). Do not use BTC thresholds on ETH.

5. **Regime characterization:** Quantify what drives the week-20 breakdown (May 16-17). Look for macro/volatility markers that might serve as a regime filter to avoid deploying during adverse physics periods.

6. **Vwap<=0.85 pocket depth:** If fee model is confirmed as legacy, the vwap<=0.85 & spread<=0.02 sub-pocket (+$0.532/fire legacy, n=1,716 in-sample) is worth a dedicated OOS test with mandatory spread gate.

### Not Recommended

- **Do NOT deploy physics as a standalone strategy** until p<0.05 OOS is achieved.
- **Do NOT apply physics gates to ETH winning sleeves** — incompatible by scale, no evidence of improvement.
- **Do NOT use WEAK_COMBO as the primary filter** — pure `dist>=40` is simpler and matches or beats WEAK_COMBO OOS under all fee models. Occam's razor applies.

---

## Appendix: Key File Reference

| File | Description |
|------|-------------|
| `strategy_lab/physics/physics_signal.py` | Signal implementation — `physics_at()` fn |
| `strategy_lab/physics/_results/physics_fires_enriched.parquet` | BTC enriched, 11,210 valid fires, Apr 24 – Jun 1 |
| `strategy_lab/physics/_results/physics_fires_enriched_eth.parquet` | ETH enriched, 3,369 valid fires, May 19 – Jun 1 |
| `strategy_lab/reports/PHYSICS_OOS_FEE_2026_06_01.md` | OOS train/test + 3 fee models, BTC |
| `strategy_lab/reports/PHYSICS_FILL_REALISM_2026_06_01.md` | 1Hz/10Hz, spread/depth, OLS bias test |
| `strategy_lab/reports/PHYSICS_ETH_GENERALIZE_2026_06_01.md` | ETH scaling and 14d generalization |
| `strategy_lab/reports/PHYSICS_OVERLAY_WINNERS_2026_06_01.md` | Overlay on 4 winning production sleeves |

---

*Report generated 2026-06-01. All numbers sourced from physics_fires_enriched.parquet (valid==True) and sub-investigation reports listed above. Fee model identification confirmed by parquet pnl column reconciliation (match errors <1e-4).*
