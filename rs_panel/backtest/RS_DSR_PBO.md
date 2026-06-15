# DSR + PBO — pre-registered RS config

**Config (pre-registered):** `ls / score2 / contra / weekly / K=8`  ·  trials in grid N=180  ·  T=999 days

## Deflated Sharpe Ratio
- Observed Sharpe: **1.52** annualized (0.0794/day)
- Return skew 0.78, kurtosis 10.69 (normal=3)
- Trial-Sharpe dispersion across 180 configs: std(SR_day)=0.0372
- Expected-max Sharpe under N trials (SR0): **1.94** annualized
- **PSR(0)** (prob true SR>0, no selection adj): **0.995**
- **DSR** (prob true SR>0 AFTER deflating for 180 trials): **0.235**
  - Pass bar = 0.95.  Verdict: FAIL ❌ (Sharpe is explained by selection / not significant)

## PBO (CSCV)
- Combinatorial splits: S=8 blocks, 70 train/test combinations
- **PBO = 0.17** (probability the in-sample-best config is below-median out-of-sample)
  - <0.5 good, >0.5 overfit.  Verdict: OK
- Chosen config median OOS Sharpe across 70 splits: **1.52** annualized

## Bottom line
**NOT a real edge — do not deploy.** DSR 0.24 (bar 0.95), PBO 0.17 (bar <0.5), chosen-config median OOS Sharpe 1.52.

The attractive grid-top Sharpe was selection over 180 trials. After deflation and combinatorial cross-validation it does not hold. Consistent with the §RS_BACKTEST_RESULTS verdict and the project's prior DSR findings — RS-rank is a monitor, not a systematic edge on this data.