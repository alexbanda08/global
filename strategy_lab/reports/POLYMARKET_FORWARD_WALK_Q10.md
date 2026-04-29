# Forward-Walk Holdout — q10 vs q20 (locked baseline)

Per (asset, timeframe, signal): chronological 80/20 split. Quantile threshold fit on TRAIN only, applied to both. Strategy = sig_ret5m + hedge-hold rev_bp=5.


**Verdict criteria:** holdout hit within ±5pp of train AND holdout CI > 0 → edge generalizes.


## q20 signal

| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Δhit | Verdict |
|---|---|---|---|---|---|
| 5m | ALL | 984 / 75.6% / +21.99% | 292 / 74.0% / +22.88% / [+56, +78] | +1.6pp | ✅ generalizes |
| 5m | btc | 329 / 77.2% / +22.78% | 97 / 72.2% / +21.90% / [+14, +28] | +5.0pp | ⚠️ CI ok but hit drift |
| 5m | eth | 328 / 73.8% / +21.47% | 105 / 80.0% / +27.19% / [+23, +34] | -6.2pp | ⚠️ CI ok but hit drift |
| 5m | sol | 328 / 75.9% / +21.68% | 90 / 68.9% / +19.35% / [+11, +23] | +7.0pp | ⚠️ CI ok but hit drift |
| 15m | ALL | 328 / 77.4% / +20.38% | 85 / 63.5% / +13.02% / [+7, +15] | +13.9pp | ⚠️ CI ok but hit drift |
| 15m | btc | 109 / 79.8% / +22.66% | 27 / 59.3% / +9.51% / [+0, +5] | +20.6pp | ⚠️ CI ok but hit drift |
| 15m | eth | 109 / 76.1% / +19.74% | 39 / 69.2% / +15.37% / [+3, +9] | +6.9pp | ⚠️ CI ok but hit drift |
| 15m | sol | 109 / 77.1% / +19.01% | 19 / 57.9% / +13.19% / [+1, +5] | +19.2pp | ⚠️ CI ok but hit drift |

## q10 signal

| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Δhit | Verdict |
|---|---|---|---|---|---|
| 5m | ALL | 492 / 82.5% / +26.61% | 135 / 77.8% / +28.02% / [+31, +44] | +4.7pp | ✅ generalizes |
| 5m | btc | 165 / 83.6% / +27.91% | 36 / 86.1% / +32.70% / [+8, +15] | -2.5pp | ✅ generalizes |
| 5m | eth | 164 / 81.7% / +27.35% | 59 / 78.0% / +28.36% / [+12, +21] | +3.7pp | ✅ generalizes |
| 5m | sol | 164 / 82.3% / +24.47% | 39 / 69.2% / +23.66% / [+5, +13] | +13.1pp | ⚠️ CI ok but hit drift |
| 15m | ALL | 165 / 84.2% / +22.69% | 34 / 67.6% / +11.69% / [+2, +6] | +16.6pp | ⚠️ CI ok but hit drift |
| 15m | btc | 55 / 85.5% / +25.34% | 10 / 80.0% / +14.01% / [+1, +2] | +5.5pp | ⚠️ CI ok but hit drift |
| 15m | eth | 55 / 85.5% / +22.75% | 15 / 66.7% / +12.81% / [+1, +3] | +18.8pp | ⚠️ CI ok but hit drift |
| 15m | sol | 55 / 81.8% / +19.97% | 9 / 55.6% / +7.24% / [-1, +2] | +26.3pp | ❌ does not generalize |

## q10 vs q20 head-to-head (HOLDOUT only)

| TF | Asset | q20 holdout ROI | q10 holdout ROI | Δ | q20 holdout hit | q10 holdout hit | Δ |
|---|---|---|---|---|---|---|---|
| 5m | ALL | +22.88% | +28.02% | +5.14pp ✅ | 74.0% | 77.8% | +3.8pp |
| 5m | btc | +21.90% | +32.70% | +10.80pp ✅ | 72.2% | 86.1% | +13.9pp |
| 5m | eth | +27.19% | +28.36% | +1.17pp ✅ | 80.0% | 78.0% | -2.0pp |
| 5m | sol | +19.35% | +23.66% | +4.32pp ✅ | 68.9% | 69.2% | +0.3pp |
| 15m | ALL | +13.02% | +11.69% | -1.33pp ❌ | 63.5% | 67.6% | +4.1pp |
| 15m | btc | +9.51% | +14.01% | +4.50pp ✅ | 59.3% | 80.0% | +20.7pp |
| 15m | eth | +15.37% | +12.81% | -2.56pp ❌ | 69.2% | 66.7% | -2.6pp |
| 15m | sol | +13.19% | +7.24% | -5.95pp ❌ | 57.9% | 55.6% | -2.3pp |