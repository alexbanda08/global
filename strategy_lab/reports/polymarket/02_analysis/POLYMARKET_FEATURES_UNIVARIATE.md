# Univariate Feature Analysis — BTC Up/Down (Apr 22-27)

Sample: 1896 markets (1422× 5m + 474× 15m).

Break-even hit rate ≈ **53%** (fees + spread). Sign-test z>2 ≈ 5% significance. Top-quintile = top 20% by feature value, we'd bet UP. Bot-quintile flipped to DOWN-betting hit rate.


## 5m — features sorted by top-quintile hit rate (n=285 per quintile)

| Feature | Sign-test n | Sign hit% | Top-Q hit% | Bot-Q hit% (DOWN) | Pearson r | p |
|---|---|---|---|---|---|---|
| ret_5m | 1245 |  55.5 |  60.7 |  58.9 | +0.123 | 0.000 |
| ls_count_delta_5m | 1251 |  52.2 |  56.5 |  53.0 | +0.052 | 0.049 |
| ret_15m | 1251 |  51.9 |  54.0 |  55.4 | +0.048 | 0.072 |
| ls_top_count | 1422 |  50.5 |  53.7 |  53.0 | +0.033 | 0.212 |
| ls_count | 1422 |  50.5 |  51.6 |  51.6 | +0.030 | 0.260 |
| smart_minus_retail | 1422 |  50.5 |  51.6 |  50.5 | +0.005 | 0.859 |
| taker_ratio | 1422 |  50.5 |  51.6 |  51.9 | -0.011 | 0.688 |
| ret_1h | 1260 |  51.4 |  51.2 |  46.7 | -0.022 | 0.417 |
| oi_delta_5m | 1251 |  51.0 |  49.8 |  52.6 | +0.008 | 0.764 |
| oi_delta_1h | 1262 |  49.0 |  49.1 |  48.4 | -0.046 | 0.081 |
| oiv_delta_5m | 1251 |  50.1 |  49.1 |  49.8 | -0.007 | 0.787 |
| taker_delta_5m | 1251 |  53.5 |  49.1 |  56.8 | +0.019 | 0.464 |
| ls_top_sum | 1422 |  50.5 |  48.1 |  48.1 | -0.023 | 0.388 |
| oi_delta_15m | 1253 |  48.4 |  46.7 |  44.6 | -0.054 | 0.042 |
| book_skew | 1419 |  46.6 |  46.7 |  43.9 | -0.076 | 0.004 |

## 15m — features sorted by top-quintile hit rate (n=95 per quintile)

| Feature | Sign-test n | Sign hit% | Top-Q hit% | Bot-Q hit% (DOWN) | Pearson r | p |
|---|---|---|---|---|---|---|
| smart_minus_retail | 474 |  47.7 |  60.0 |  57.9 | +0.044 | 0.339 |
| ret_5m | 417 |  57.1 |  58.9 |  61.1 | +0.116 | 0.011 |
| ls_top_count | 474 |  47.7 |  55.8 |  61.1 | +0.077 | 0.094 |
| ls_count_delta_5m | 418 |  56.5 |  54.7 |  55.8 | +0.092 | 0.045 |
| ls_count | 474 |  47.7 |  51.6 |  57.9 | +0.065 | 0.159 |
| ret_1h | 420 |  51.0 |  51.6 |  51.6 | -0.024 | 0.601 |
| oi_delta_5m | 418 |  50.7 |  51.6 |  51.6 | -0.029 | 0.531 |
| taker_delta_5m | 418 |  53.1 |  50.5 |  56.8 | +0.059 | 0.203 |
| oi_delta_15m | 418 |  48.6 |  49.5 |  45.3 | -0.076 | 0.099 |
| ret_15m | 417 |  48.9 |  47.4 |  55.8 | +0.018 | 0.700 |
| oiv_delta_5m | 418 |  50.5 |  47.4 |  50.5 | -0.049 | 0.285 |
| taker_ratio | 474 |  47.7 |  46.3 |  56.8 | +0.001 | 0.988 |
| oi_delta_1h | 421 |  47.5 |  43.2 |  50.5 | -0.028 | 0.547 |
| ls_top_sum | 474 |  47.7 |  43.2 |  54.7 | -0.026 | 0.571 |
| book_skew | 473 |  48.8 |  38.9 |  51.6 | -0.038 | 0.411 |