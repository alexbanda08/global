# Cross-Asset Leader — Validation Report

Best in-sample variant from E6: **S2 = own_q10 AND btc_lag0_q10 agree direction**


## Per-asset × timeframe breakdown (in-sample)

| Asset | TF | S2 n | S2 hit | S2 ROI | own_q10 n | own_q10 ROI | lift |
|---|---|---|---|---|---|---|---|
| ALL | ALL | 247 | 84.2% | +26.61% | 388 | +22.94% | +3.67pp |
| ALL | 5m | 181 | 85.1% | +28.73% | 290 | +23.38% | +5.36pp |
| ALL | 15m | 66 | 81.8% | +20.77% | 98 | +21.64% | -0.86pp |
| eth | ALL | 134 | 85.8% | +29.23% | 194 | +24.89% | +4.34pp |
| eth | 5m | 97 | 86.6% | +31.42% | 145 | +25.07% | +6.34pp |
| eth | 15m | 37 | 83.8% | +23.50% | 49 | +24.34% | -0.84pp |
| sol | ALL | 113 | 82.3% | +23.49% | 194 | +20.98% | +2.51pp |
| sol | 5m | 84 | 83.3% | +25.63% | 145 | +21.68% | +3.96pp |
| sol | 15m | 29 | 79.3% | +17.29% | 49 | +18.94% | -1.64pp |

## Day-by-day (in-sample, S2 vs own_q10)

| Date | S2 n | S2 ROI | own n | own ROI | lift |
|---|---|---|---|---|---|
| 2026-04-22 | 32 | +28.02% | 53 | +19.53% | +8.49pp |
| 2026-04-23 | 109 | +25.42% | 151 | +21.87% | +3.55pp |
| 2026-04-24 | 64 | +27.31% | 100 | +23.91% | +3.40pp |
| 2026-04-25 | 3 | +17.23% | 13 | +27.78% | -10.56pp |
| 2026-04-26 | 39 | +28.33% | 71 | +25.49% | +2.84pp |

## Forward-walk holdout (80/20 chronological per asset×tf)

Quantile thresholds for both own_q10 and btc_lag0_q10 fit on TRAIN only.

| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Δhit | Verdict |
|---|---|---|---|---|---|
| 5m | eth | 77 / 85.7% / +30.73% | 8 / 87.5% / +32.66% / [+1, +4] | -1.8pp | ✅ generalizes |
| 5m | sol | 62 / 83.9% / +25.89% | 9 / 88.9% / +25.32% / [+0, +3] | -5.0pp | ⚠️ hit drift |
| 15m | eth | 29 / 82.8% / +23.81% | 5 / 100.0% / +21.76% / [+1, +2] | -17.2pp | ⚠️ hit drift |
| 15m | sol | 22 / 77.3% / +18.88% | 6 / 83.3% / +14.17% / [-1, +2] | -6.1pp | ❌ |

## Holdout: S2 vs own_q10 head-to-head

| TF | Asset | S2 holdout n / ROI | own_q10 holdout n / ROI | Lift |
|---|---|---|---|---|
| 5m | eth | 8 / ? | 15 / ? | **+7.85pp** |
| 5m | sol | 9 / ? | 13 / ? | **+1.79pp** |
| 15m | eth | 5 / ? | 7 / ? | **-2.62pp** |
| 15m | sol | 6 / ? | 8 / ? | **-3.57pp** |

## Verdict

- In-sample lift over own_q10: see top table
- Day-by-day lift: 4/5 days
- Holdout lift positive in: **2/4 cells**

⚠️ **Mixed.** Forward-walk shows partial generalization. Pilot with caution.