# Forward-Walk Holdout — `sig_ret5m` family

Chronological 80/20 split. Train = first 80% of markets by resolve_unix, Holdout = last 20%. Quantile thresholds computed on TRAIN only.

If holdout hit% stays ≥56% and CI excludes zero, signal is **real**.


## 5m

| Signal | Threshold | Train n / hit / PnL / CI / ROI | Holdout n / hit / PnL / CI / ROI |
|---|---|---|---|
| sig_ret5m | — | 1137 / 55.2% / $+47.73 / [$+14,$+78] / +4.20% | 285 / 53.0% / $+6.87 / [$-9,$+23] / +2.41% |
| sig_ret5m_q20 | 0.091% | 228 / 60.5% / $+23.11 / [$+8,$+37] / +10.14% | 26 / 61.5% / $+2.86 / [$-2,$+7] / +10.99% |
| sig_ret5m_q10 | 0.139% | 114 / 70.2% / $+22.67 / [$+13,$+32] / +19.88% | 15 / 66.7% / $+2.33 / [$-1,$+5] / +15.50% |

## 15m

| Signal | Threshold | Train n / hit / PnL / CI / ROI | Holdout n / hit / PnL / CI / ROI |
|---|---|---|---|
| sig_ret5m | — | 379 / 58.0% / $+27.31 / [$+8,$+45] / +7.21% | 95 / 56.8% / $+6.01 / [$-3,$+16] / +6.33% |
| sig_ret5m_q20 | 0.090% | 76 / 64.5% / $+10.66 / [$+3,$+19] / +14.03% | 12 / 50.0% / $+0.32 / [$-3,$+3] / +2.66% |
| sig_ret5m_q10 | 0.136% | 38 / 68.4% / $+6.51 / [$+1,$+12] / +17.13% | 8 / 37.5% / $-0.78 / [$-3,$+2] / -9.71% |