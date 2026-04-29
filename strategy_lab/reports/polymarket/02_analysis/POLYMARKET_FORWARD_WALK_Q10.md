# Forward-Walk Holdout — q10 vs q20 (locked baseline)

Per (asset, timeframe, signal): chronological 80/20 split. Quantile threshold fit on TRAIN only, applied to both. Strategy = sig_ret5m + hedge-hold rev_bp=5.


**Verdict criteria:** holdout hit within ±5pp of train AND holdout CI > 0 → edge generalizes.


## q20 signal

| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Δhit | Verdict |
|---|---|---|---|---|---|
| 5m | ALL | 690 / 74.5% / +21.06% | 78 / 73.1% / +21.18% / [+10, +22] | +1.4pp | ✅ generalizes |
| 5m | btc | 228 / 76.8% / +22.09% | 26 / 76.9% / +26.91% / [+3, +10] | -0.2pp | ✅ generalizes |
| 5m | eth | 231 / 72.7% / +19.92% | 30 / 66.7% / +17.80% / [+1, +9] | +6.1pp | ⚠️ CI ok but hit drift |
| 5m | sol | 231 / 74.0% / +21.34% | 23 / 78.3% / +20.71% / [+1, +8] | -4.2pp | ✅ generalizes |
| 15m | ALL | 231 / 73.2% / +19.15% | 39 / 87.2% / +24.03% / [+7, +12] | -14.0pp | ⚠️ CI ok but hit drift |
| 15m | btc | 76 / 75.0% / +19.96% | 12 / 91.7% / +31.67% / [+3, +5] | -16.7pp | ⚠️ CI ok but hit drift |
| 15m | eth | 77 / 74.0% / +19.96% | 13 / 84.6% / +23.82% / [+2, +4] | -10.6pp | ⚠️ CI ok but hit drift |
| 15m | sol | 77 / 70.1% / +17.24% | 14 / 85.7% / +17.68% / [+0, +4] | -15.6pp | ⚠️ CI ok but hit drift |

## q10 signal

| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Δhit | Verdict |
|---|---|---|---|---|---|
| 5m | ALL | 345 / 82.3% / +25.52% | 43 / 81.4% / +28.17% / [+8, +16] | +0.9pp | ✅ generalizes |
| 5m | btc | 114 / 85.1% / +28.91% | 15 / 86.7% / +35.54% / [+3, +7] | -1.6pp | ✅ generalizes |
| 5m | eth | 116 / 80.2% / +24.81% | 15 / 73.3% / +24.81% / [+1, +6] | +6.8pp | ⚠️ CI ok but hit drift |
| 5m | sol | 116 / 81.9% / +23.05% | 13 / 84.6% / +23.53% / [+1, +5] | -2.7pp | ✅ generalizes |
| 15m | ALL | 117 / 81.2% / +21.77% | 23 / 91.3% / +24.36% / [+3, +7] | -10.1pp | ⚠️ CI ok but hit drift |
| 15m | btc | 38 / 81.6% / +22.06% | 8 / 87.5% / +30.95% / [+1, +3] | -5.9pp | ⚠️ CI ok but hit drift |
| 15m | eth | 39 / 82.1% / +24.40% | 7 / 100.0% / +24.39% / [+1, +2] | -17.9pp | ⚠️ CI ok but hit drift |
| 15m | sol | 39 / 79.5% / +19.27% | 8 / 87.5% / +17.75% / [-0, +3] | -8.0pp | ❌ does not generalize |

## q10 vs q20 head-to-head (HOLDOUT only)

| TF | Asset | q20 holdout ROI | q10 holdout ROI | Δ | q20 holdout hit | q10 holdout hit | Δ |
|---|---|---|---|---|---|---|---|
| 5m | ALL | +21.18% | +28.17% | +6.99pp ✅ | 73.1% | 81.4% | +8.3pp |
| 5m | btc | +26.91% | +35.54% | +8.63pp ✅ | 76.9% | 86.7% | +9.7pp |
| 5m | eth | +17.80% | +24.81% | +7.01pp ✅ | 66.7% | 73.3% | +6.7pp |
| 5m | sol | +20.71% | +23.53% | +2.82pp ✅ | 78.3% | 84.6% | +6.4pp |
| 15m | ALL | +24.03% | +24.36% | +0.33pp ✅ | 87.2% | 91.3% | +4.1pp |
| 15m | btc | +31.67% | +30.95% | -0.71pp ❌ | 91.7% | 87.5% | -4.2pp |
| 15m | eth | +23.82% | +24.39% | +0.56pp ✅ | 84.6% | 100.0% | +15.4pp |
| 15m | sol | +17.68% | +17.75% | +0.06pp ✅ | 85.7% | 87.5% | +1.8pp |