# Forward-Walk: Spread Filter (<2%) for q10 hedge-hold strategy

Per (asset, tf): chronological 80/20 split. q10 quantile fit on TRAIN only. Spread filter applied to both TRAIN and HOLDOUT identically.


## Holdout: no-filter vs spread<2%

| TF | Asset | Holdout no-filt n / ROI | Holdout w/filter n / hit / ROI / 95% CI | Holdout lift |
|---|---|---|---|---|
| 5m | ALL | 38 / +27.13% | 16 / 81.2% / +29.69% / [+2, +7] | **+2.56pp** |
| 5m | btc | 13 / +35.36% | 8 / 87.5% / +39.69% / [+2, +4] | **+4.33pp** |
| 5m | eth | 14 / +24.06% | 6 / 66.7% / +18.24% / [-1, +3] | **-5.82pp** |
| 5m | sol | 11 / +21.30% | 2 / 100.0% / +24.00% / [+0, +1] | **+2.70pp** |
| 15m | ALL | 18 / +26.56% | 6 / 100.0% / +23.00% / [+1, +2] | **-3.57pp** |
| 15m | btc | 6 / +26.74% | 2 / 100.0% / +33.87% / [+0, +1] | **+7.13pp** |
| 15m | eth | 6 / +26.33% | 2 / 100.0% / +12.89% / [+0, +0] | **-13.44pp** |
| 15m | sol | 6 / +26.62% | 2 / 100.0% / +22.23% / [+0, +1] | **-4.39pp** |

## Summary

Holdout lift positive: **4 / 8 cells**

⚠️ **Borderline.** Some holdout cells positive, others negative. Pilot with caution.