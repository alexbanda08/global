# Robustness Check — alt-strategies on small (5-day) sample

Forward-walk holdout has inadequate power on 5-day data for stacked filters. Using small-sample-appropriate tests instead.


## 1. Cross-asset hour-rank stability

Each asset's hourly ROI ranking is computed independently. If 3 unrelated assets agree on which hours are good, the signal is robust.

| Pair | Spearman ρ | n_hours | Verdict |
|---|---|---|---|
| btc↔eth | +0.170 | 24 | WEAK (<0.25) |
| btc↔sol | +0.203 | 24 | WEAK (<0.25) |
| eth↔sol | +0.174 | 24 | WEAK (<0.25) |

**Top-5 best hours (intersection of all 3 assets):** []
**Bot-5 worst hours (intersection):** [np.int64(16)]

Our cross-asset GOOD_HOURS choice was: [3, 5, 8, 9, 10, 11, 12, 13, 14, 17, 19, 21]
Overlap with universal top-5: **0/5** ([])

## 2. Permutation test on time-of-day filter

10,000 random 12-hour subsets sampled. Compared lift of our chosen subset to permutation distribution.

- Overall (unfiltered) ROI: **+21.51%**
- Our filter ROI: **+24.48%**
- Actual lift: **+2.97pp**
- Permutation 95th percentile lift: +1.68pp
- **p-value**: 0.0001
- **Verdict: SIGNIFICANT** at α=0.05. Random hour selections rarely beat our pick.

## 3. Bootstrap 95% CI on filtered ROI vs baseline

Baseline (no filter): n=1641, ROI **+21.51%**

| Stack | n | Mean ROI | 95% CI | Excludes baseline? |
|---|---|---|---|---|
| good_hours_only | 830 | +24.48% | [+22.48%, +26.45%] | **YES** — significant |
| bad_excluded | 1323 | +22.68% | [+21.08%, +24.25%] | no — overlap |
| europe_only | 258 | +24.70% | [+20.76%, +28.41%] | no — overlap |

## 4. Day-by-day breakdown


### good_hours_only (overall +24.48%, n=830)
| Date | n | Hit% | ROI |
|---|---|---|---|
| 2026-04-22 | 44 | 90.9% | +31.89% |
| 2026-04-23 | 164 | 81.1% | +26.91% |
| 2026-04-24 | 144 | 82.6% | +25.57% |
| 2026-04-25 | 20 | 60.0% | +21.30% |
| 2026-04-26 | 91 | 80.2% | +26.91% |
| 2026-04-27 | 135 | 81.5% | +24.71% |
| 2026-04-28 | 107 | 67.3% | +17.73% |
| 2026-04-29 | 125 | 73.6% | +21.69% |

### bad_excluded (overall +22.68%, n=1323)
| Date | n | Hit% | ROI |
|---|---|---|---|
| 2026-04-22 | 85 | 80.0% | +21.79% |
| 2026-04-23 | 263 | 77.6% | +24.68% |
| 2026-04-24 | 200 | 83.5% | +24.43% |
| 2026-04-25 | 32 | 59.4% | +20.32% |
| 2026-04-26 | 160 | 80.0% | +25.05% |
| 2026-04-27 | 225 | 76.9% | +22.57% |
| 2026-04-28 | 158 | 68.4% | +17.88% |
| 2026-04-29 | 200 | 71.0% | +21.10% |

### europe_only (overall +24.70%, n=258)
| Date | n | Hit% | ROI |
|---|---|---|---|
| 2026-04-22 | 0 | — | — |
| 2026-04-23 | 61 | 88.5% | +33.51% |
| 2026-04-24 | 55 | 85.5% | +29.79% |
| 2026-04-25 | 15 | 46.7% | +17.55% |
| 2026-04-26 | 11 | 63.6% | +23.00% |
| 2026-04-27 | 32 | 84.4% | +24.17% |
| 2026-04-28 | 31 | 58.1% | +9.71% |
| 2026-04-29 | 53 | 73.6% | +20.72% |

## Verdict

Combining all 4 tests:
- Cross-asset hour rank stability: see Spearman table above
- Permutation p-value: 0.0001
- Bootstrap CIs: see Test 3
- Day-by-day stability: see Test 4 — look for consistent lift across all 5 days

**Action:** if (a) Spearman ≥ 0.4 between all asset pairs, AND (b) permutation p < 0.05, AND (c) bootstrap CI excludes baseline, AND (d) at least 4/5 days show lift, the strategy is robust enough to deploy at small stake. Otherwise, wait for more data.