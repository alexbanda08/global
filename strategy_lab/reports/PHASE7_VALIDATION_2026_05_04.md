# Phase 7 Validation — V5 LATE-ENTRY Quant Audit (2026_05_04)

Reuses `polymarket_stats.equity_curve_stats` (Sharpe / Sortino / Calmar / MaxDD) and
`polymarket_forward_walk_v2` chronological-split + bootstrap-CI pattern.

**Validation gates applied:**
1. Chronological 80/20 split (train fits Q20/Q80 thresholds; holdout is OOS)
2. Permutation test (1000× shuffled outcomes → null IC distribution → p-value)
3. Bootstrap CI on holdout PnL + hit rate (2000 resamples)
4. Per-hour-of-day PnL breakdown (holdout)
5. Equity curve stats (Sharpe / Calmar / MaxDD / longest DD run)
6. Stop-loss simulation (no_stop / 50% / 70% / 90% per-trade stops)
7. Tail-risk identification (worst 5% of trades)

Notional: $1.0 per trade. Taker fee: 2.0%. Entry at t=240s. Hold 60s.

## Headline holdout stats

| Asset | n_holdout | hit% | pnl$ | Sharpe | Sortino | Calmar | MaxDD$ | IC p-value |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 292 | 45.9% | -43.07 | -33.869 | -61.460 | -122.964 | -52.41 | 0.0000 |
| ETH | 239 | 55.6% | -10.94 | -8.246 | -17.125 | -83.874 | -19.64 | 0.0000 |
| SOL | 278 | 65.8% | -13.00 | -25.314 | -21.420 | -146.190 | -13.76 | 0.0000 |

**IC p-value < 0.05** = signal is statistically significant (true IC unlikely under null).

## Train vs Holdout degradation

| Asset | Train hit% | Holdout hit% | Train pnl | Holdout pnl | Degradation |
|---|---:|---:|---:|---:|---|
| BTC | 58.1% | 45.9% | -3.59 | -43.07 | Sharpe +6353% |
| ETH | 56.9% | 55.6% | -78.80 | -10.94 | Sharpe -52% |
| SOL | 68.7% | 65.8% | -28.42 | -13.00 | Sharpe +198% |

## Bootstrap 95% CI on holdout PnL + hit rate

| Asset | PnL CI | Hit rate CI |
|---|---|---|
| BTC | [-71.75, -10.89] | [40.1%, 51.7%] |
| ETH | [-38.85, +25.32] | [49.4%, 61.9%] |
| SOL | [-25.45, +0.23] | [60.1%, 70.9%] |

**Lower CI > 0** = strategy edge is statistically significant.

## Stop-loss simulation (holdout)

### BTC

| Variant | pnl$ | Sharpe | MaxDD$ | Longest DD | Win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -43.07 | -0.162 | -52.41 | 266 | 45.9% |
| stop_50pct | +3.73 | +0.016 | -18.44 | 140 | 45.9% |
| stop_70pct | -14.27 | -0.059 | -28.84 | 140 | 45.9% |
| stop_90pct | -32.27 | -0.126 | -42.52 | 244 | 45.9% |

### ETH

| Variant | pnl$ | Sharpe | MaxDD$ | Longest DD | Win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -10.94 | -0.043 | -19.64 | 158 | 55.6% |
| stop_50pct | +15.58 | +0.067 | -6.26 | 124 | 55.6% |
| stop_70pct | +5.38 | +0.023 | -11.32 | 156 | 55.6% |
| stop_90pct | -4.82 | -0.020 | -16.52 | 156 | 55.6% |

### SOL

| Variant | pnl$ | Sharpe | MaxDD$ | Longest DD | Win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -13.00 | -0.122 | -13.76 | 273 | 65.8% |
| stop_50pct | +0.52 | +0.007 | -3.88 | 121 | 65.8% |
| stop_70pct | -4.68 | -0.054 | -6.28 | 143 | 65.8% |
| stop_90pct | -9.88 | -0.100 | -10.76 | 273 | 65.8% |

## Tail risk (worst 5% of holdout trades)

| Asset | n_worst | total_pnl$ | %_of_total | hours | directions | avg_entry$ |
|---|---:|---:|---:|---|---|---:|
| BTC | 14/292 | -14.28 | +33.2% | 8,9,11,12,14 | Up=5/Down=9 | 0.284 |
| ETH | 11/239 | -11.22 | +102.5% | 9,10,12,13,14,15,18,21 | Up=4/Down=7 | 0.355 |
| SOL | 13/278 | -13.26 | +102.0% | 0,6,7,10,13,15,18,20,21 | Up=7/Down=6 | 0.568 |

## Per-hour holdout PnL (UTC)

### BTC

| Hour | n | total_pnl$ | avg_pnl$ | win% |
|---:|---:|---:|---:|---:|
| 0 | 12 | -1.06 | -0.0886 | 25.0% |
| 1 | 12 | -4.17 | -0.3478 | 41.7% |
| 2 | 9 | -0.76 | -0.0841 | 44.4% |
| 3 | 13 | -3.66 | -0.2815 | 23.1% |
| 4 | 10 | -1.50 | -0.1503 | 70.0% |
| 5 | 8 | -1.67 | -0.2087 | 75.0% |
| 6 | 13 | -4.94 | -0.3798 | 38.5% |
| 7 | 9 | +0.73 | +0.0811 | 66.7% |
| 8 | 12 | -3.34 | -0.2781 | 41.7% |
| 9 | 13 | -4.38 | -0.3370 | 46.2% |
| 10 | 19 | -3.47 | -0.1829 | 42.1% |
| 11 | 18 | -0.85 | -0.0471 | 55.6% |
| 12 | 15 | +3.89 | +0.2592 | 46.7% |
| 13 | 13 | +6.16 | +0.4741 | 46.2% |
| 14 | 13 | -4.33 | -0.3327 | 38.5% |
| 15 | 14 | -0.18 | -0.0129 | 71.4% |
| 16 | 12 | -8.13 | -0.6771 | 16.7% |
| 17 | 16 | +3.27 | +0.2043 | 43.8% |
| 18 | 14 | -6.40 | -0.4569 | 35.7% |
| 19 | 16 | -2.00 | -0.1247 | 68.8% |
| 20 | 9 | -1.66 | -0.1847 | 66.7% |
| 21 | 11 | -1.74 | -0.1580 | 27.3% |
| 22 | 5 | -1.97 | -0.3941 | 40.0% |
| 23 | 6 | -0.93 | -0.1543 | 33.3% |

### ETH

| Hour | n | total_pnl$ | avg_pnl$ | win% |
|---:|---:|---:|---:|---:|
| 0 | 4 | -0.03 | -0.0073 | 25.0% |
| 1 | 9 | -0.18 | -0.0197 | 44.4% |
| 2 | 8 | +0.88 | +0.1104 | 62.5% |
| 3 | 10 | -0.97 | -0.0973 | 60.0% |
| 4 | 8 | +0.59 | +0.0736 | 62.5% |
| 5 | 10 | -0.45 | -0.0451 | 70.0% |
| 6 | 9 | -2.80 | -0.3113 | 33.3% |
| 7 | 10 | -1.71 | -0.1714 | 60.0% |
| 8 | 7 | +0.20 | +0.0285 | 57.1% |
| 9 | 10 | -0.89 | -0.0886 | 60.0% |
| 10 | 16 | -3.74 | -0.2337 | 43.8% |
| 11 | 6 | -0.64 | -0.1068 | 33.3% |
| 12 | 13 | +2.89 | +0.2220 | 76.9% |
| 13 | 12 | +1.67 | +0.1388 | 66.7% |
| 14 | 13 | -2.25 | -0.1730 | 53.8% |
| 15 | 14 | -3.86 | -0.2754 | 50.0% |
| 16 | 9 | -0.75 | -0.0835 | 66.7% |
| 17 | 12 | -4.32 | -0.3600 | 33.3% |
| 18 | 16 | -0.77 | -0.0478 | 68.8% |
| 19 | 9 | -0.63 | -0.0698 | 66.7% |
| 20 | 9 | +12.59 | +1.3985 | 55.6% |
| 21 | 9 | -1.97 | -0.2190 | 55.6% |
| 22 | 6 | +0.17 | +0.0285 | 66.7% |
| 23 | 10 | -3.97 | -0.3974 | 40.0% |

### SOL

| Hour | n | total_pnl$ | avg_pnl$ | win% |
|---:|---:|---:|---:|---:|
| 0 | 12 | -4.05 | -0.3379 | 41.7% |
| 1 | 12 | -0.96 | -0.0798 | 41.7% |
| 2 | 8 | +0.03 | +0.0032 | 62.5% |
| 3 | 12 | +0.56 | +0.0466 | 66.7% |
| 4 | 5 | +0.12 | +0.0245 | 80.0% |
| 5 | 11 | +1.01 | +0.0917 | 63.6% |
| 6 | 8 | -1.93 | -0.2407 | 50.0% |
| 7 | 12 | -0.94 | -0.0784 | 58.3% |
| 8 | 9 | +0.31 | +0.0340 | 77.8% |
| 9 | 10 | -1.21 | -0.1213 | 70.0% |
| 10 | 8 | -0.80 | -0.0996 | 87.5% |
| 11 | 13 | -0.76 | -0.0581 | 61.5% |
| 12 | 19 | -0.49 | -0.0258 | 68.4% |
| 13 | 15 | -2.78 | -0.1855 | 60.0% |
| 14 | 12 | +2.44 | +0.2037 | 66.7% |
| 15 | 15 | -0.30 | -0.0201 | 86.7% |
| 16 | 14 | +1.07 | +0.0763 | 85.7% |
| 17 | 14 | +0.29 | +0.0208 | 78.6% |
| 18 | 16 | -1.30 | -0.0814 | 81.2% |
| 19 | 16 | +0.03 | +0.0018 | 81.2% |
| 20 | 6 | -2.04 | -0.3395 | 16.7% |
| 21 | 10 | -0.55 | -0.0552 | 40.0% |
| 22 | 8 | -0.95 | -0.1187 | 37.5% |
| 23 | 13 | +0.20 | +0.0156 | 69.2% |

---

**Verdict gates** (all must pass for live deployment):
- Permutation p-value < 0.05  → IC is real, not noise
- Holdout Sharpe > 0.5         → risk-adjusted returns positive
- Bootstrap PnL CI lower > 0   → edge is statistically significant
- MaxDD < 5x mean trade PnL    → manageable tail risk
- Train→Holdout Sharpe degradation < 50%  → strategy generalizes
- Stop-loss doesn't help much  → no negative skew (if stop helps a lot, signal has bad tails)