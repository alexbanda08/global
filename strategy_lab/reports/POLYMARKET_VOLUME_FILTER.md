# Volume Regime Filter (E3)

Hypothesis: skip markets when Binance volume is anomalously low. q10 universe (n=823). Hedge-hold rev_bp=5.

vol_z = (vol_5m_now - vol_24h_mean) / vol_24h_std. Distribution: median 0.45, p10 -0.42, p90 3.42.


## Variant grid

| Variant | n | Hit% | ROI | vs baseline | Trade rate |
|---|---|---|---|---|---|
| baseline (baseline) | 823 | 81.2% | +25.26% | +0.00pp | 100% |
| high_vol_only | 558 | 78.3% | +24.64% | -0.62pp | 68% |
| exclude_p10 ★ | 740 | 80.3% | +25.44% | +0.18pp | 90% |
| exclude_p25 | 616 | 79.2% | +25.28% | +0.01pp | 75% |
| exclude_p50 | 411 | 76.4% | +23.64% | -1.62pp | 50% |
| only_high_vol_p75 | 206 | 76.7% | +25.12% | -0.15pp | 25% |
| only_extreme_vol_p90 | 82 | 74.4% | +22.55% | -2.72pp | 10% |

## Cross-asset breakdown — best `exclude_p10` vs baseline

| Asset | TF | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|---|
| ALL | ALL | 740 | +25.44% | +25.26% | +0.18pp |
| ALL | 5m | 560 | +27.18% | +26.89% | +0.29pp |
| ALL | 15m | 180 | +20.03% | +20.43% | -0.40pp |
| btc | ALL | 241 | +27.54% | +27.52% | +0.01pp |
| btc | 5m | 182 | +29.01% | +29.01% | -0.00pp |
| btc | 15m | 59 | +23.00% | +23.08% | -0.08pp |
| eth | ALL | 249 | +26.01% | +25.52% | +0.48pp |
| eth | 5m | 189 | +28.03% | +27.34% | +0.69pp |
| eth | 15m | 60 | +19.61% | +20.11% | -0.50pp |
| sol | ALL | 250 | +22.86% | +22.73% | +0.13pp |
| sol | 5m | 189 | +24.57% | +24.29% | +0.27pp |
| sol | 15m | 61 | +17.58% | +18.10% | -0.52pp |

## Day-by-day — best `exclude_p10` vs baseline

| Date | best n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 32 | +26.72% | +21.83% | +4.89pp |
| 2026-04-23 | 181 | +23.53% | +23.41% | +0.12pp |
| 2026-04-24 | 93 | +25.70% | +26.33% | -0.63pp |
| 2026-04-25 | 13 | +38.18% | +38.18% | +0.00pp |
| 2026-04-26 | 81 | +27.94% | +27.94% | +0.00pp |
| 2026-04-27 | 141 | +27.21% | +27.31% | -0.10pp |
| 2026-04-28 | 87 | +20.87% | +21.72% | -0.85pp |
| 2026-04-29 | 112 | +26.00% | +26.00% | +0.00pp |

## Verdict

**Criteria: 2/3**
  - In-sample lift > 0: ✅ (+0.18pp)
  - Cross-asset (≥2/3): ✅ (3/3)
  - Day stability (≥4/5): ❌ (2/8)

⚠️ Worth forward-walk validation.