# Volume Regime Filter (E3)

Hypothesis: skip markets when Binance volume is anomalously low. q10 universe (n=579). Hedge-hold rev_bp=5.

vol_z = (vol_5m_now - vol_24h_mean) / vol_24h_std. Distribution: median 0.19, p10 -0.52, p90 2.78.


## Variant grid

| Variant | n | Hit% | ROI | vs baseline | Trade rate |
|---|---|---|---|---|---|
| baseline (baseline) | 579 | 81.5% | +24.58% | +0.00pp | 100% |
| high_vol_only | 333 | 78.1% | +22.67% | -1.90pp | 58% |
| exclude_p10 | 521 | 80.6% | +24.21% | -0.37pp | 90% |
| exclude_p25 ★ | 434 | 80.4% | +24.30% | -0.28pp | 75% |
| exclude_p50 | 289 | 77.2% | +22.50% | -2.07pp | 50% |
| only_high_vol_p75 | 145 | 75.9% | +22.10% | -2.48pp | 25% |
| only_extreme_vol_p90 | 58 | 69.0% | +17.74% | -6.84pp | 10% |

## Cross-asset breakdown — best `exclude_p25` vs baseline

| Asset | TF | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|---|
| ALL | ALL | 434 | +24.30% | +24.58% | -0.28pp |
| ALL | 5m | 330 | +24.95% | +25.43% | -0.48pp |
| ALL | 15m | 104 | +22.23% | +22.03% | +0.20pp |
| btc | ALL | 139 | +27.69% | +27.90% | -0.21pp |
| btc | 5m | 104 | +29.80% | +29.61% | +0.20pp |
| btc | 15m | 35 | +21.42% | +22.83% | -1.41pp |
| eth | ALL | 147 | +24.42% | +24.89% | -0.47pp |
| eth | 5m | 111 | +23.86% | +25.07% | -1.22pp |
| eth | 15m | 36 | +26.14% | +24.34% | +1.80pp |
| sol | ALL | 148 | +20.99% | +20.98% | +0.01pp |
| sol | 5m | 115 | +21.62% | +21.68% | -0.06pp |
| sol | 15m | 33 | +18.81% | +18.94% | -0.12pp |

## Day-by-day — best `exclude_p25` vs baseline

| Date | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 50 | +20.41% | +21.37% | -0.96pp |
| 2026-04-23 | 179 | +22.77% | +22.90% | -0.12pp |
| 2026-04-24 | 93 | +24.53% | +26.60% | -2.07pp |
| 2026-04-25 | 16 | +33.78% | +31.15% | +2.63pp |
| 2026-04-26 | 96 | +27.36% | +26.91% | +0.44pp |

## Verdict

**Criteria: 0/3**
  - In-sample lift > 0: ❌ (-0.28pp)
  - Cross-asset (≥2/3): ❌ (1/3)
  - Day stability (≥4/5): ❌ (2/5)

❌ No meaningful edge from volume filtering.