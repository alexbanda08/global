# Strategy Stacks — q-tightening × time-of-day filter

Cross-asset hedge-hold rev_bp=5. Comparing locked baseline (q20, no filter) to combinations of tighter quintiles + UTC-hour filters.


## Best stack per cell

| Asset | TF | Best stack | n | Hit% | ROI | vs baseline |
|---|---|---|---|---|---|---|
| ALL | ALL | `europe_q10` | 90 | 90.0% | +32.96% | +12.72pp (8% volume) |
| ALL | 15m | `europe_q10` | 24 | 91.7% | +28.25% | +7.87pp (8% volume) |
| ALL | 5m | `europe_q10` | 66 | 89.4% | +34.67% | +14.49pp (8% volume) |
| btc | ALL | `europe_q10` | 34 | 97.1% | +39.41% | +16.88pp (9% volume) |
| btc | 15m | `europe_q10` | 9 | 100.0% | +33.21% | +10.96pp (9% volume) |
| btc | 5m | `europe_q10` | 25 | 96.0% | +41.64% | +19.02pp (9% volume) |
| eth | ALL | `good_hours_q5` | 43 | 88.4% | +32.23% | +12.80pp (11% volume) |
| eth | 15m | `good_hours_q5` | 10 | 100.0% | +30.72% | +9.51pp (10% volume) |
| eth | 5m | `good_hours_q5` | 33 | 84.8% | +32.68% | +13.86pp (11% volume) |
| sol | ALL | `europe_q10` | 25 | 88.0% | +27.25% | +8.47pp (6% volume) |
| sol | 15m | `europe_q10` | 7 | 85.7% | +25.84% | +8.09pp (7% volume) |
| sol | 5m | `europe_q10` | 18 | 88.9% | +27.80% | +8.67pp (6% volume) |

## ALL × ALL — all stacks ranked

| Stack | n | Hit% | PnL/trade | ROI | 95% CI |
|---|---|---|---|---|---|
| `europe_q10` | 90 | 90.0% | $+0.3296 | +32.96% | [$+25, $+34] |
| `good_hours_q10` | 293 | 86.0% | $+0.2940 | +29.40% | [$+77, $+95] |
| `good_hours_q5` | 132 | 88.6% | $+0.2909 | +29.09% | [$+32, $+44] |
| `bad_excl_q10` | 469 | 84.2% | $+0.2700 | +27.00% | [$+115, $+138] |
| `europe_q20` | 183 | 77.0% | $+0.2692 | +26.92% | [$+41, $+57] |
| `good_hours_q20` | 571 | 80.0% | $+0.2555 | +25.55% | [$+133, $+160] |
| `q5` | 292 | 83.2% | $+0.2534 | +25.34% | [$+65, $+83] |
| `q10` | 579 | 81.5% | $+0.2458 | +24.58% | [$+129, $+155] |
| `bad_excl_q20` | 931 | 77.1% | $+0.2283 | +22.83% | [$+193, $+231] |
| `baseline_q20` ★ baseline | 1152 | 73.8% | $+0.2023 | +20.23% | [$+212, $+254] |

## BTC × ALL — all stacks ranked

| Stack | n | Hit% | PnL/trade | ROI | 95% CI |
|---|---|---|---|---|---|
| `europe_q10` | 34 | 97.1% | $+0.3941 | +39.41% | [$+11, $+15] |
| `europe_q20` | 66 | 89.4% | $+0.3611 | +36.11% | [$+20, $+27] |
| `good_hours_q10` | 103 | 88.3% | $+0.3214 | +32.14% | [$+27, $+38] |
| `bad_excl_q10` | 155 | 86.5% | $+0.3094 | +30.94% | [$+41, $+54] |
| `good_hours_q20` | 193 | 84.5% | $+0.2874 | +28.74% | [$+47, $+63] |
| `good_hours_q5` | 43 | 86.0% | $+0.2855 | +28.55% | [$+8, $+16] |
| `q10` | 191 | 84.8% | $+0.2790 | +27.90% | [$+46, $+61] |
| `q5` | 96 | 83.3% | $+0.2755 | +27.55% | [$+21, $+31] |
| `bad_excl_q20` | 302 | 81.5% | $+0.2608 | +26.08% | [$+68, $+89] |
| `baseline_q20` ★ baseline | 380 | 77.1% | $+0.2253 | +22.53% | [$+73, $+98] |