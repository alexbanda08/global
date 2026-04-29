# Forward-Walk: Spread Filter (<2%) for q10 hedge-hold strategy

Per (asset, tf): chronological 80/20 split. q10 quantile fit on TRAIN only. Spread filter applied to both TRAIN and HOLDOUT identically.


## Holdout: no-filter vs spread<2%

| TF | Asset | Holdout no-filt n / ROI | Holdout w/filter n / hit / ROI / 95% CI | Holdout lift |
|---|---|---|---|---|
| 5m | ALL | 126 / +29.22% | 36 / 83.3% / +31.25% / [+8, +14] | **+2.03pp** |
| 5m | btc | 34 / +34.45% | 12 / 83.3% / +29.86% / [+1, +5] | **-4.59pp** |
| 5m | eth | 57 / +29.01% | 19 / 84.2% / +31.77% / [+4, +8] | **+2.76pp** |
| 5m | sol | 34 / +24.91% | 5 / 80.0% / +32.62% / [+1, +2] | **+7.71pp** |
| 15m | ALL | 26 / +16.86% | 7 / 100.0% / +26.08% / [+1, +3] | **+9.22pp** |
| 15m | btc | 8 / +17.31% | 4 / 100.0% / +24.20% / [+1, +2] | **+6.89pp** |
| 15m | eth | 13 / +14.35% | 2 / 100.0% / +29.36% / [+0, +1] | **+15.01pp** |
| 15m | sol | 5 / +22.66% | 1 / 100.0% / +27.06% / [+0, +0] | **+4.40pp** |

## Summary

Holdout lift positive: **7 / 8 cells**

✅ **Spread filter generalizes.** Worth deploying as additional gate on q10/q20 hedge-hold.