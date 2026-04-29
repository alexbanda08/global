# Univariate Feature Analysis — BTC Up/Down (Apr 22-27)

Sample: 2734 markets (2052× 5m + 682× 15m).

Break-even hit rate ≈ **53%** (fees + spread). Sign-test z>2 ≈ 5% significance. Top-quintile = top 20% by feature value, we'd bet UP. Bot-quintile flipped to DOWN-betting hit rate.


## 5m — features sorted by top-quintile hit rate (n=411 per quintile)

| Feature | Sign-test n | Sign hit% | Top-Q hit% | Bot-Q hit% (DOWN) | Pearson r | p |
|---|---|---|---|---|---|---|
| ret_5m | 2042 |  55.3 |  60.1 |  59.4 | +0.131 | 0.000 |
| ret_15m | 2049 |  52.7 |  56.2 |  56.0 | +0.071 | 0.001 |
| ls_count_delta_5m | 1251 |  52.2 |  54.7 |  51.3 | +0.044 | 0.046 |
| smart_minus_retail | 2052 |  50.1 |  52.8 |  50.6 | +0.009 | 0.671 |
| oiv_delta_5m | 1251 |  50.1 |  51.8 |  48.9 | -0.006 | 0.777 |
| taker_delta_5m | 1251 |  53.5 |  51.3 |  54.5 | +0.016 | 0.464 |
| oi_delta_5m | 1251 |  51.0 |  50.6 |  50.6 | +0.006 | 0.778 |
| ls_top_sum | 2052 |  50.1 |  50.6 |  49.1 | -0.018 | 0.419 |
| ret_1h | 2050 |  51.6 |  50.4 |  47.7 | -0.006 | 0.791 |
| ls_top_count | 2052 |  50.1 |  50.1 |  50.9 | +0.027 | 0.227 |
| ls_count | 2052 |  50.1 |  50.1 |  52.3 | +0.023 | 0.305 |
| taker_ratio | 2052 |  50.1 |  49.6 |  47.7 | -0.007 | 0.759 |
| oi_delta_1h | 1262 |  49.0 |  48.9 |  46.5 | -0.039 | 0.075 |
| oi_delta_15m | 1253 |  48.4 |  46.5 |  46.5 | -0.046 | 0.039 |
| book_skew | 2046 |  47.1 |  44.8 |  46.5 | -0.070 | 0.002 |

## 15m — features sorted by top-quintile hit rate (n=137 per quintile)

| Feature | Sign-test n | Sign hit% | Top-Q hit% | Bot-Q hit% (DOWN) | Pearson r | p |
|---|---|---|---|---|---|---|
| smart_minus_retail | 682 |  49.0 |  54.7 |  50.9 | +0.006 | 0.880 |
| ret_5m | 681 |  55.8 |  54.0 |  64.2 | +0.106 | 0.006 |
| ls_count_delta_5m | 418 |  56.5 |  53.3 |  55.5 | +0.073 | 0.058 |
| taker_delta_5m | 418 |  53.1 |  52.6 |  54.0 | +0.049 | 0.200 |
| ls_top_count | 682 |  49.0 |  51.8 |  54.7 | +0.067 | 0.081 |
| ret_15m | 681 |  49.3 |  51.8 |  51.1 | +0.025 | 0.520 |
| oi_delta_15m | 418 |  48.6 |  51.1 |  48.2 | -0.061 | 0.112 |
| ls_count | 682 |  49.0 |  50.4 |  54.7 | +0.060 | 0.117 |
| oi_delta_5m | 418 |  50.7 |  50.4 |  51.8 | -0.023 | 0.541 |
| oiv_delta_5m | 418 |  50.5 |  49.6 |  50.4 | -0.040 | 0.293 |
| ret_1h | 681 |  49.9 |  48.2 |  50.4 | -0.015 | 0.696 |
| taker_ratio | 682 |  49.0 |  47.4 |  50.4 | -0.007 | 0.863 |
| ls_top_sum | 682 |  49.0 |  46.0 |  53.6 | -0.026 | 0.501 |
| oi_delta_1h | 421 |  47.5 |  43.8 |  47.4 | -0.020 | 0.605 |
| book_skew | 681 |  48.8 |  40.9 |  49.6 | -0.046 | 0.233 |