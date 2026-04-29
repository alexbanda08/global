# Cross-Asset Leader Test (E6) — BTC predicts ETH/SOL

Hypothesis: BTC ret_5m at lag K predicts ETH/SOL outcomes better than (or as confirming filter to) ETH/SOL's own ret_5m. Lag K ∈ [0, 30, 60, 90, 120] seconds. Universe: ETH+SOL × q10. Exit: hedge-hold rev_bp=5 (locked baseline).


## Variant grid (sorted by ROI)

| Variant | Lag (s) | n | Trade rate | Hit% | ROI | 95% CI total | vs S0 baseline |
|---|---|---|---|---|---|---|---|
| S2_own_AND_btc_lag0_agree ★ | 0.0 | 247 | 6.4% | 84.2% | +26.61% | [+58, +73] | +3.67pp |
| S1_btc_lag0_q10 | 0.0 | 388 | 10.1% | 78.6% | +24.16% | [+82, +104] | +1.23pp |
| S0_own_q10 (baseline) | — | 388 | 10.1% | 79.9% | +22.94% | [+78, +100] | +0.00pp |
| S2_own_AND_btc_lag90_agree | 90.0 | 113 | 2.9% | 75.2% | +21.90% | [+19, +31] | -1.04pp |
| S2_own_AND_btc_lag120_agree | 120.0 | 113 | 2.9% | 75.2% | +21.90% | [+18, +31] | -1.04pp |
| S2_own_AND_btc_lag30_agree | 30.0 | 162 | 4.2% | 71.0% | +16.81% | [+19, +35] | -6.13pp |
| S2_own_AND_btc_lag60_agree | 60.0 | 162 | 4.2% | 71.0% | +16.81% | [+19, +35] | -6.13pp |
| S1_btc_lag90_q10 | 90.0 | 388 | 10.1% | 62.4% | +15.26% | [+46, +73] | -7.68pp |
| S1_btc_lag120_q10 | 120.0 | 388 | 10.1% | 62.4% | +15.26% | [+46, +73] | -7.68pp |
| S1_btc_lag60_q10 | 60.0 | 388 | 10.1% | 57.0% | +10.39% | [+27, +53] | -12.55pp |
| S1_btc_lag30_q10 | 30.0 | 388 | 10.1% | 57.0% | +10.39% | [+27, +53] | -12.55pp |
| S3_divergence_btc_lag120 | 120.0 | 4 | 0.1% | 75.0% | +4.48% | [-1, +1] | -18.46pp |
| S3_divergence_btc_lag90 | 90.0 | 4 | 0.1% | 75.0% | +4.48% | [-1, +1] | -18.46pp |
| S3_divergence_btc_lag60 | 60.0 | 5 | 0.1% | 20.0% | +2.70% | [-0, +1] | -20.23pp |
| S3_divergence_btc_lag30 | 30.0 | 5 | 0.1% | 20.0% | +2.70% | [-0, +1] | -20.23pp |
| S3_divergence_btc_lag0 | 0.0 | 0 | 0.0% | 0.0% | +nan% | [+0, +0] | +nanpp |

## Verdict

Best variant `S2_own_AND_btc_lag0_agree` lifts +3.67pp over S0 baseline.

✅ **Worth forward-walk validation.** Cross-asset leader signal candidate.