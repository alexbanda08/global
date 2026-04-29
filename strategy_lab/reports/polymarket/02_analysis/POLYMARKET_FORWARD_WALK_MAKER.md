# Forward-Walk: Maker-Entry Hybrid vs Taker Baseline

q10 chronological 80/20 split. Quantile threshold (90th percentile of |ret_5m|) fit on TRAIN only.
Both taker and maker simulators run on the same train and holdout sets.
Maker variant: limit at bid+0.01, wait 30s, fallback to taker if no fill.
Hedge-hold rev_bp=5 on exit (locked baseline).


## TRAIN vs HOLDOUT — taker baseline (control)

| TF | Asset | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI |
|---|---|---|---|
| 5m | ALL | 345 / 82.3% / +25.52% | 43 / 81.4% / +28.17% / [+7.73, +15.84] |
| 5m | btc | 114 / 85.1% / +28.91% | 15 / 86.7% / +35.54% / [+3.40, +6.90] |
| 5m | eth | 116 / 80.2% / +24.81% | 15 / 73.3% / +24.81% / [+0.70, +6.22] |
| 5m | sol | 116 / 81.9% / +23.05% | 13 / 84.6% / +23.53% / [+0.54, +5.02] |
| 15m | ALL | 117 / 81.2% / +21.77% | 23 / 91.3% / +24.36% / [+3.30, +7.49] |
| 15m | btc | 38 / 81.6% / +22.06% | 8 / 87.5% / +30.95% / [+1.38, +3.33] |
| 15m | eth | 39 / 82.1% / +24.40% | 7 / 100.0% / +24.39% / [+1.01, +2.45] |
| 15m | sol | 39 / 79.5% / +19.27% | 8 / 87.5% / +17.75% / [-0.40, +2.65] |

## TRAIN vs HOLDOUT — maker hybrid

| TF | Asset | TRAIN n / hit / ROI / fill | HOLDOUT n / hit / ROI / fill / 95% CI |
|---|---|---|---|
| 5m | ALL | 309 / 85.1% / +27.55% / 27% | 38 / 78.9% / +27.88% / 32% / [+6.58, +14.26] |
| 5m | btc | 104 / 86.5% / +30.40% / 14% | 13 / 84.6% / +35.59% / 15% / [+2.65, +6.15] |
| 5m | eth | 102 / 82.4% / +27.30% / 27% | 14 / 71.4% / +24.91% / 43% / [+0.62, +5.85] |
| 5m | sol | 104 / 86.5% / +25.18% / 39% | 11 / 81.8% / +22.56% / 36% / [+0.02, +4.43] |
| 15m | ALL | 95 / 89.5% / +25.92% / 20% | 18 / 94.4% / +26.78% / 11% / [+3.49, +5.95] |
| 15m | btc | 31 / 87.1% / +26.18% / 13% | 6 / 83.3% / +26.74% / 0% / [+0.66, +2.34] |
| 15m | eth | 32 / 93.8% / +28.74% / 25% | 6 / 100.0% / +26.83% / 17% / [+0.95, +2.25] |
| 15m | sol | 31 / 87.1% / +23.41% / 23% | 6 / 100.0% / +26.79% / 17% / [+1.09, +2.03] |

## Lift table — maker minus taker

| TF | Asset | TRAIN lift | HOLDOUT lift | Verdict |
|---|---|---|---|---|
| 5m | ALL | +2.04pp | -0.29pp | ❌ holdout lift negative |
| 5m | btc | +1.50pp | +0.04pp | ✅ holdout lift positive |
| 5m | eth | +2.49pp | +0.10pp | ✅ holdout lift positive |
| 5m | sol | +2.13pp | -0.97pp | ❌ holdout lift negative |
| 15m | ALL | +4.15pp | +2.42pp | ✅ holdout lift positive |
| 15m | btc | +4.12pp | -4.22pp | ❌ holdout lift negative |
| 15m | eth | +4.34pp | +2.44pp | ✅ holdout lift positive |
| 15m | sol | +4.14pp | +9.04pp | ✅ holdout lift positive |

## Verdict

Holdout cells with positive maker lift: **5 / 8**

⚠️ **Borderline.** Maker lift mostly holds but mixed. Pilot with caution.