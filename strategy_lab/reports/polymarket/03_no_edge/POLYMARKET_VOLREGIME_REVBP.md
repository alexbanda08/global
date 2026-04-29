# Vol-Regime Adaptive rev_bp (E7) — does adaptive hedge threshold beat fixed?

Hypothesis: scale rev_bp by current vol regime to avoid over-/under-hedging.

q10 universe (n=579). Vol ratio = |ret_5m_now| / |ret_5m|_24h_mean.

Vol ratio distribution: mean=3.08 median=2.37 p10=1.65 p90=5.55

## Variant grid

| Variant | Description | n | Hit% | ROI | vs V0 baseline | Hedge rate | Mean rev_bp |
|---|---|---|---|---|---|---|---|
| V0_static5 (baseline) | rev_bp = 5 (locked baseline) | 579 | 81.5% | +24.58% | +0.00pp | 56% | 5.00 |
| V1_static3 | rev_bp = 3 (always tighter) | 579 | 82.9% | +23.16% | -1.42pp | 69% | 3.00 |
| V2_static8 ★ | rev_bp = 8 (always wider) | 579 | 77.2% | +23.46% | -1.12pp | 42% | 8.00 |
| V3_atr_linear | rev_bp = clip(5*vol_ratio, 3, 20) | 579 | 71.2% | +19.32% | -5.26pp | 27% | 13.33 |
| V4_atr_sqrt | rev_bp = clip(5*sqrt(vol_ratio), 3, 20) | 579 | 76.7% | +22.92% | -1.65pp | 42% | 8.49 |
| V5_quintile | 5 quintiles → {3,4,5,7,10} | 579 | 79.4% | +23.08% | -1.50pp | 56% | 5.80 |
| V6_inverse | rev_bp = clip(5/vol_ratio, 3, 20) — sanity null | 579 | 82.7% | +23.09% | -1.48pp | 69% | 3.02 |

## Cross-asset breakdown — best `V2_static8` vs V0 baseline

| Asset | TF | best n | best ROI | V0 ROI | Δ |
|---|---|---|---|---|---|
| ALL | ALL | 579 | +23.46% | +24.58% | -1.12pp |
| ALL | 5m | 433 | +23.31% | +25.43% | -2.12pp |
| ALL | 15m | 146 | +23.89% | +22.03% | +1.86pp |
| btc | ALL | 191 | +27.85% | +27.90% | -0.05pp |
| btc | 5m | 143 | +28.76% | +29.61% | -0.84pp |
| btc | 15m | 48 | +25.12% | +22.83% | +2.29pp |
| eth | ALL | 194 | +23.41% | +24.89% | -1.48pp |
| eth | 5m | 145 | +22.26% | +25.07% | -2.82pp |
| eth | 15m | 49 | +26.82% | +24.34% | +2.48pp |
| sol | ALL | 194 | +19.18% | +20.98% | -1.80pp |
| sol | 5m | 145 | +18.99% | +21.68% | -2.69pp |
| sol | 15m | 49 | +19.76% | +18.94% | +0.83pp |

## Day-by-day — best `V2_static8` vs V0 baseline

| Date | best n | best ROI | V0 ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 75 | +17.43% | +21.37% | -3.94pp |
| 2026-04-23 | 240 | +22.30% | +22.90% | -0.59pp |
| 2026-04-24 | 148 | +26.20% | +26.60% | -0.40pp |
| 2026-04-25 | 17 | +33.68% | +31.15% | +2.53pp |
| 2026-04-26 | 99 | +24.97% | +26.91% | -1.95pp |

## Verdict

**Criteria: 0/3**
  - In-sample lift > 0: ❌ (-1.12pp)
  - Cross-asset (≥2/3): ❌ (0/3)
  - Day stability (≥4/5): ❌ (1/5)

❌ Vol-regime adaptive rev_bp does NOT beat fixed rev_bp=5. The locked baseline already captures the optimal trade-off.