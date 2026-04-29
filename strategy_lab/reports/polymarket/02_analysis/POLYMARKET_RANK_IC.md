# Polymarket Rank-IC Analysis

Cross-section definition: markets grouped by (window_start_date, asset, timeframe). IC = Spearman rank correlation between factor and `outcome_up`. Min 5 markets per cross-section.

**Universe:** 5742 markets across 6 dates (BTC + ETH + SOL × ['5m', '15m']).


## Summary — top factors by |IC IR| (timeframe-stratified)


### Timeframe 5m

| Factor | Asset | Mean IC | IR | Autocorr | t-stat | %positive | n_dates |
|---|---|---|---|---|---|---|---|
| ret_5m | btc | +0.1317 | +3.50 | -0.06 | +8.58 | 100% | 6 |
| ret_5m | eth | +0.1171 | +2.77 | -0.84 | +6.20 | 100% | 5 |
| book_skew | btc | -0.0870 | -2.40 | -0.44 | -5.87 | 0% | 6 |
| smart_minus_retail | btc | +0.0487 | +1.92 | -0.59 | +4.30 | 100% | 5 |
| smart_minus_retail | sol | +0.0734 | +1.81 | +0.09 | +4.05 | 100% | 5 |
| ret_5m | ALL | +0.1000 | +1.04 | +0.22 | +4.28 | 88% | 17 |
| smart_minus_retail | ALL | +0.0424 | +1.00 | -0.19 | +3.86 | 87% | 15 |
| ret_15m | btc | +0.0729 | +0.96 | -0.06 | +2.34 | 83% | 6 |
| ret_15m | eth | +0.0236 | +0.90 | -0.03 | +2.22 | 83% | 6 |
| ret_1h | eth | -0.0412 | -0.77 | -0.42 | -1.90 | 17% | 6 |
| ret_15m | ALL | +0.0417 | +0.77 | -0.25 | +3.26 | 83% | 18 |
| book_skew | ALL | -0.0449 | -0.68 | -0.12 | -2.90 | 22% | 18 |
| ret_15m | sol | +0.0285 | +0.68 | -0.26 | +1.67 | 83% | 6 |
| book_skew | sol | -0.0432 | -0.52 | -0.60 | -1.27 | 17% | 6 |
| taker_ratio | eth | -0.0279 | -0.45 | -0.56 | -1.01 | 40% | 5 |
| oi_delta_5m | eth | -0.0458 | -0.44 | -0.02 | -1.08 | 50% | 6 |
| ls_top_sum | sol | +0.0229 | +0.39 | -0.12 | +0.87 | 80% | 5 |
| ret_1h | ALL | -0.0205 | -0.36 | +0.31 | -1.55 | 39% | 18 |
| ret_5m | sol | +0.0541 | +0.36 | -0.29 | +0.88 | 67% | 6 |
| ret_1h | sol | -0.0203 | -0.32 | +0.21 | -0.78 | 50% | 6 |

### Timeframe 15m

| Factor | Asset | Mean IC | IR | Autocorr | t-stat | %positive | n_dates |
|---|---|---|---|---|---|---|---|
| ret_5m | sol | +0.1950 | +2.93 | +0.59 | +7.18 | 100% | 6 |
| book_skew | sol | -0.1660 | -2.20 | +0.59 | -5.39 | 0% | 6 |
| smart_minus_retail | sol | +0.1600 | +1.82 | -0.87 | +4.07 | 100% | 5 |
| taker_ratio | eth | -0.0950 | -1.51 | -0.42 | -3.39 | 0% | 5 |
| ret_5m | ALL | +0.1577 | +1.38 | +0.39 | +5.68 | 88% | 17 |
| ret_5m | eth | +0.1472 | +1.11 | +0.61 | +2.48 | 80% | 5 |
| ret_15m | sol | +0.0940 | +0.95 | -0.39 | +2.32 | 83% | 6 |
| smart_minus_retail | ALL | +0.1045 | +0.92 | -0.23 | +3.57 | 80% | 15 |
| ret_5m | btc | +0.1291 | +0.90 | +0.78 | +2.20 | 83% | 6 |
| ls_top_sum | eth | -0.0448 | -0.84 | -0.53 | -1.88 | 20% | 5 |
| ret_15m | eth | +0.0795 | +0.79 | +0.42 | +1.94 | 67% | 6 |
| smart_minus_retail | btc | +0.1029 | +0.69 | -0.07 | +1.54 | 60% | 5 |
| ret_1h | eth | -0.0488 | -0.61 | +0.52 | -1.51 | 33% | 6 |
| oi_delta_5m | sol | -0.0643 | -0.60 | -0.68 | -1.47 | 33% | 6 |
| smart_minus_retail | eth | +0.0507 | +0.58 | +0.89 | +1.30 | 80% | 5 |
| book_skew | eth | +0.0426 | +0.57 | -0.07 | +1.39 | 67% | 6 |
| ls_top_sum | btc | +0.0602 | +0.54 | -1.00 | +1.21 | 60% | 5 |
| ret_15m | ALL | +0.0666 | +0.49 | +0.24 | +2.09 | 61% | 18 |
| book_skew | ALL | -0.0614 | -0.48 | -0.28 | -2.05 | 33% | 18 |
| book_skew | btc | -0.0608 | -0.46 | -0.66 | -1.12 | 33% | 6 |

## Interpretation guide

- **Mean IC** — average rank correlation per cross-section. Positive = factor predicts outcome.
- **IR (Information Ratio)** = mean_IC / std_IC. Higher = more consistent. >0.5 is decent for daily.
- **Autocorr** = lag-1 corr of the IC series. >0.3 = persistent (signal durable). <0 = noisy/regime-flipping.
- **t-stat** = mean_IC / (std_IC / sqrt(n_dates)). |t| > 2 suggests IC ≠ 0 statistically.
- **%positive** — share of dates with positive IC. Should agree directionally with mean IC.


## How to use this for the live strategy

- **Drift trigger:** if rolling 14-day mean IC drops below half its all-time level for `ret_5m`, retire/refit.
- **Alt-signal screen:** any factor with |IR| > existing `ret_5m` IR is a candidate for the next experiment.
- **Refit cadence:** if autocorr > 0.5, refit weekly; if < 0.2, refit daily or move on.
