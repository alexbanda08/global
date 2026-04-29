# Polymarket Baselines × Exit Grid — BTC Up/Down (Apr 22-27)

Sample: 1896 BTC markets (1422× 5m + 474× 15m). Fee: 2% on winnings. Bootstrap n=2000 for 95% CIs.


## 5m — top 10 strategy×baseline by total PnL

| Baseline | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| market_anti | S2_stop40 | 1422 | $+2.75 | [$-11, $+17] | 18.6% |
| momentum | S2_stop40 | 1383 | $-1.06 | [$-17, $+15] | 20.2% |
| market_anti | S2_stop35 | 1422 | $-3.75 | [$-22, $+14] | 20.0% |
| momentum | S2_stop35 | 1383 | $-5.11 | [$-25, $+14] | 23.4% |
| always_down | S2_stop40 | 1422 | $-5.58 | [$-22, $+11] | 20.8% |
| market_anti | S3_t70s35 | 1422 | $-8.51 | [$-20, $+3] | 33.8% |
| momentum | S0_hold | 1383 | $-8.71 | [$-43, $+29] | 49.7% |
| momentum | S2_stop30 | 1383 | $-10.12 | [$-32, $+11] | 28.2% |
| random | S2_stop40 | 1422 | $-10.59 | [$-27, $+5] | 20.5% |
| market_with | S0_hold | 1422 | $-11.29 | [$-47, $+25] | 54.4% |

## 5m — bottom 5 (sanity check)

| Baseline | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| always_up | S1_tgt55 | 1422 | $-55.17 | [$-69, $-42] | 68.7% |
| random | S1_tgt55 | 1422 | $-56.43 | [$-72, $-41] | 68.6% |
| market_with | S1_tgt60 | 1422 | $-59.92 | [$-78, $-43] | 72.6% |
| market_with | S3_t55s40 | 1422 | $-62.11 | [$-68, $-57] | 40.5% |
| market_with | S1_tgt55 | 1422 | $-70.01 | [$-82, $-59] | 58.2% |

## 15m — top 10 strategy×baseline by total PnL

| Baseline | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| always_down | S0_hold | 474 | $+6.89 | [$-14, $+26] | 52.3% |
| always_down | S2_stop35 | 474 | $+5.35 | [$-6, $+17] | 25.9% |
| always_down | S2_stop30 | 474 | $+4.99 | [$-9, $+19] | 31.0% |
| random | S0_hold | 474 | $+2.98 | [$-18, $+24] | 51.9% |
| market_anti | S3_t70s35 | 474 | $+1.62 | [$-5, $+9] | 33.5% |
| market_anti | S2_stop30 | 474 | $+1.55 | [$-11, $+14] | 24.1% |
| random | S2_stop40 | 474 | $+1.54 | [$-8, $+12] | 19.8% |
| market_anti | S3_t60s35 | 474 | $+1.42 | [$-4, $+7] | 46.6% |
| momentum | S2_stop30 | 457 | $+1.03 | [$-12, $+14] | 26.5% |
| market_anti | S2_stop40 | 474 | $+1.03 | [$-7, $+9] | 13.7% |

## 15m — bottom 5 (sanity check)

| Baseline | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| always_up | S1_tgt60 | 474 | $-16.67 | [$-27, $-6] | 73.6% |
| always_down | S1_tgt55 | 474 | $-17.02 | [$-25, $-9] | 62.7% |
| always_up | S0_hold | 474 | $-17.86 | [$-39, $+4] | 47.7% |
| market_with | S3_t60s35 | 474 | $-17.96 | [$-24, $-13] | 56.5% |
| market_with | S1_tgt55 | 474 | $-19.11 | [$-25, $-14] | 43.5% |