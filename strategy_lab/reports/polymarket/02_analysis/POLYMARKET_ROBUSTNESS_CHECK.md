# Robustness Check — alt-strategies on small (5-day) sample

Forward-walk holdout has inadequate power on 5-day data for stacked filters. Using small-sample-appropriate tests instead.


## 1. Cross-asset hour-rank stability

Each asset's hourly ROI ranking is computed independently. If 3 unrelated assets agree on which hours are good, the signal is robust.

| Pair | Spearman ρ | n_hours | Verdict |
|---|---|---|---|
| btc↔eth | +0.353 | 24 | MEDIUM (0.25-0.5) |
| btc↔sol | +0.361 | 24 | MEDIUM (0.25-0.5) |
| eth↔sol | +0.203 | 24 | WEAK (<0.25) |

**Top-5 best hours (intersection of all 3 assets):** []
**Bot-5 worst hours (intersection):** [np.int64(4)]

Our cross-asset GOOD_HOURS choice was: [3, 5, 8, 9, 10, 11, 12, 13, 14, 17, 19, 21]
Overlap with universal top-5: **0/5** ([])

## 2. Permutation test on time-of-day filter

10,000 random 12-hour subsets sampled. Compared lift of our chosen subset to permutation distribution.

- Overall (unfiltered) ROI: **+20.23%**
- Our filter ROI: **+25.55%**
- Actual lift: **+5.32pp**
- Permutation 95th percentile lift: +2.56pp
- **p-value**: 0.0000
- **Verdict: SIGNIFICANT** at α=0.05. Random hour selections rarely beat our pick.

## 3. Bootstrap 95% CI on filtered ROI vs baseline

Baseline (no filter): n=1152, ROI **+20.23%**

| Stack | n | Mean ROI | 95% CI | Excludes baseline? |
|---|---|---|---|---|
| good_hours_only | 571 | +25.55% | [+23.01%, +27.97%] | **YES** — significant |
| bad_excluded | 931 | +22.83% | [+20.85%, +24.81%] | **YES** — significant |
| europe_only | 183 | +26.92% | [+22.44%, +31.22%] | **YES** — significant |

## 4. Day-by-day breakdown


### good_hours_only (overall +25.55%, n=571)
| Date | n | Hit% | ROI |
|---|---|---|---|
| 2026-04-22 | 50 | 92.0% | +32.71% |
| 2026-04-23 | 205 | 81.0% | +27.10% |
| 2026-04-24 | 165 | 80.6% | +24.69% |
| 2026-04-25 | 36 | 55.6% | +14.22% |
| 2026-04-26 | 115 | 80.0% | +24.47% |

### bad_excluded (overall +22.83%, n=931)
| Date | n | Hit% | ROI |
|---|---|---|---|
| 2026-04-22 | 99 | 77.8% | +21.13% |
| 2026-04-23 | 334 | 76.0% | +23.75% |
| 2026-04-24 | 238 | 80.3% | +22.52% |
| 2026-04-25 | 61 | 62.3% | +18.80% |
| 2026-04-26 | 199 | 79.4% | +23.73% |

### europe_only (overall +26.92%, n=183)
| Date | n | Hit% | ROI |
|---|---|---|---|
| 2026-04-22 | 0 | — | — |
| 2026-04-23 | 80 | 83.8% | +30.82% |
| 2026-04-24 | 67 | 82.1% | +27.75% |
| 2026-04-25 | 18 | 44.4% | +16.90% |
| 2026-04-26 | 18 | 61.1% | +16.50% |

## Verdict

Combining all 4 tests:
- Cross-asset hour rank stability: see Spearman table above
- Permutation p-value: 0.0000
- Bootstrap CIs: see Test 3
- Day-by-day stability: see Test 4 — look for consistent lift across all 5 days

**Action:** if (a) Spearman ≥ 0.4 between all asset pairs, AND (b) permutation p < 0.05, AND (c) bootstrap CI excludes baseline, AND (d) at least 4/5 days show lift, the strategy is robust enough to deploy at small stake. Otherwise, wait for more data.