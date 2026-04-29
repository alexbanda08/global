# Cross-Asset Leader Test (E6) — BTC predicts ETH/SOL

Hypothesis: BTC ret_5m at lag K predicts ETH/SOL outcomes better than (or as confirming filter to) ETH/SOL's own ret_5m. Lag K ∈ [0, 30, 60, 90, 120] seconds. Universe: ETH+SOL × q10. Exit: hedge-hold rev_bp=5 (locked baseline).


## Variant grid (sorted by ROI)

| Variant | Lag (s) | n | Trade rate | Hit% | ROI | 95% CI total | vs S0 baseline |
|---|---|---|---|---|---|---|---|
| S2_own_AND_btc_lag0_agree ★ | 0.0 | 336 | 6.2% | 83.3% | +27.15% | [+81, +100] | +3.02pp |
| S1_btc_lag0_q10 | 0.0 | 548 | 10.0% | 78.6% | +24.52% | [+122, +147] | +0.39pp |
| S0_own_q10 (baseline) | — | 548 | 10.0% | 79.7% | +24.13% | [+120, +144] | +0.00pp |
| S2_own_AND_btc_lag90_agree | 90.0 | 181 | 3.3% | 71.8% | +20.90% | [+30, +45] | -3.23pp |
| S2_own_AND_btc_lag120_agree | 120.0 | 181 | 3.3% | 71.8% | +20.90% | [+30, +46] | -3.23pp |
| S3_divergence_btc_lag120 | 120.0 | 3 | 0.1% | 100.0% | +20.32% | [+0, +1] | -3.81pp |
| S3_divergence_btc_lag90 | 90.0 | 3 | 0.1% | 100.0% | +20.32% | [+0, +1] | -3.81pp |
| S2_own_AND_btc_lag30_agree | 30.0 | 243 | 4.5% | 70.8% | +18.98% | [+37, +55] | -5.15pp |
| S2_own_AND_btc_lag60_agree | 60.0 | 243 | 4.5% | 70.8% | +18.98% | [+36, +55] | -5.15pp |
| S1_btc_lag90_q10 | 90.0 | 548 | 10.0% | 62.2% | +14.94% | [+66, +98] | -9.19pp |
| S1_btc_lag120_q10 | 120.0 | 548 | 10.0% | 62.2% | +14.94% | [+66, +97] | -9.19pp |
| S1_btc_lag60_q10 | 60.0 | 548 | 10.0% | 58.4% | +11.98% | [+50, +81] | -12.15pp |
| S1_btc_lag30_q10 | 30.0 | 548 | 10.0% | 58.4% | +11.98% | [+50, +81] | -12.15pp |
| S3_divergence_btc_lag60 | 60.0 | 4 | 0.1% | 0.0% | -8.13% | [-0, -0] | -32.26pp |
| S3_divergence_btc_lag30 | 30.0 | 4 | 0.1% | 0.0% | -8.13% | [-0, -0] | -32.26pp |
| S3_divergence_btc_lag0 | 0.0 | 0 | 0.0% | 0.0% | +nan% | [+0, +0] | +nanpp |

## Verdict

Best variant `S2_own_AND_btc_lag0_agree` lifts +3.02pp over S0 baseline.

✅ **Worth forward-walk validation.** Cross-asset leader signal candidate.