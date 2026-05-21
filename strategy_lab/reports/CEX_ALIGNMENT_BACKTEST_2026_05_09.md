# CEX Alignment Backtest — Phase 16 §B
_Generated: 2026-05-09_

## Question
Does multi-venue CEX kline reference (binance + coinbase + kraken + ensembles) beat
single-venue (binance-only) for predicting Polymarket UpDown resolutions?
Tested with $25 notional through L25 weighted-avg fill prices.

## Engine constants (locked, production-faithful)
- Notional: $25
- Entry walk: top-25 ASK levels at t+120s
- Hedge bucket book: top-10 levels (10s buckets)
- Hedge trigger: ≥5 bps reversion on Binance asset price (asset-truth, candidate-agnostic)
- Fee: 2% taker on winning leg's profit only
- Permutation: 1000× shuffle outcome_up within (asset, timeframe)
- Walk-forward: 7d train / 1d test rolling

## Coverage per candidate (Skip rate measures venue-data availability)

| candidate     | asset   | timeframe   |    n |   skip |   up |   down |   coverage_pct |
|:--------------|:--------|:------------|-----:|-------:|-----:|-------:|---------------:|
| bin-vision    | btc     | 15m         | 1641 |   1470 |   86 |     85 |          10.42 |
| bin-vision    | btc     | 5m          | 4925 |   4411 |  240 |    274 |          10.44 |
| bin-vision    | eth     | 15m         | 1641 |   1470 |   81 |     90 |          10.42 |
| bin-vision    | eth     | 5m          | 4924 |   4410 |  239 |    275 |          10.44 |
| bin-vision    | sol     | 15m         | 1641 |   1470 |   77 |     94 |          10.42 |
| bin-vision    | sol     | 5m          | 4924 |   4410 |  244 |    270 |          10.44 |
| bin-ws        | btc     | 15m         | 1641 |    172 |  753 |    716 |          89.52 |
| bin-ws        | btc     | 5m          | 4925 |    515 | 2200 |   2210 |          89.54 |
| bin-ws        | eth     | 15m         | 1641 |    172 |  717 |    752 |          89.52 |
| bin-ws        | eth     | 5m          | 4924 |    515 | 2188 |   2221 |          89.54 |
| bin-ws        | sol     | 15m         | 1641 |    172 |  723 |    746 |          89.52 |
| bin-ws        | sol     | 5m          | 4924 |    515 | 2129 |   2280 |          89.54 |
| coinbase      | btc     | 15m         | 1641 |     29 |  831 |    781 |          98.23 |
| coinbase      | btc     | 5m          | 4925 |     84 | 2400 |   2441 |          98.29 |
| coinbase      | eth     | 15m         | 1641 |     29 |  790 |    822 |          98.23 |
| coinbase      | eth     | 5m          | 4924 |     84 | 2385 |   2455 |          98.29 |
| coinbase      | sol     | 15m         | 1641 |     29 |  774 |    838 |          98.23 |
| coinbase      | sol     | 5m          | 4924 |     84 | 2318 |   2522 |          98.29 |
| kraken        | btc     | 15m         | 1641 |   1432 |  111 |     98 |          12.74 |
| kraken        | btc     | 5m          | 4925 |   4290 |  325 |    310 |          12.89 |
| kraken        | eth     | 15m         | 1641 |   1432 |   99 |    110 |          12.74 |
| kraken        | eth     | 5m          | 4924 |   4291 |  308 |    325 |          12.86 |
| kraken        | sol     | 15m         | 1641 |   1432 |  106 |    103 |          12.74 |
| kraken        | sol     | 5m          | 4924 |   4289 |  307 |    328 |          12.9  |
| okx           | btc     | 15m         | 1641 |    534 |  569 |    538 |          67.46 |
| okx           | btc     | 5m          | 4925 |   1598 | 1656 |   1671 |          67.55 |
| okx           | eth     | 15m         | 1641 |    534 |  548 |    559 |          67.46 |
| okx           | eth     | 5m          | 4924 |   1597 | 1637 |   1690 |          67.57 |
| okx           | sol     | 15m         | 1641 |    534 |  550 |    557 |          67.46 |
| okx           | sol     | 5m          | 4924 |   1597 | 1603 |   1724 |          67.57 |
| bin+coinbase  | btc     | 15m         | 1641 |   1470 |   86 |     85 |          10.42 |
| bin+coinbase  | btc     | 5m          | 4925 |   4411 |  241 |    273 |          10.44 |
| bin+coinbase  | eth     | 15m         | 1641 |   1470 |   82 |     89 |          10.42 |
| bin+coinbase  | eth     | 5m          | 4924 |   4410 |  240 |    274 |          10.44 |
| bin+coinbase  | sol     | 15m         | 1641 |   1470 |   78 |     93 |          10.42 |
| bin+coinbase  | sol     | 5m          | 4924 |   4410 |  249 |    265 |          10.44 |
| bin+coin+krak | btc     | 15m         | 1641 |   1641 |    0 |      0 |           0    |
| bin+coin+krak | btc     | 5m          | 4925 |   4925 |    0 |      0 |           0    |
| bin+coin+krak | eth     | 15m         | 1641 |   1641 |    0 |      0 |           0    |
| bin+coin+krak | eth     | 5m          | 4924 |   4924 |    0 |      0 |           0    |
| bin+coin+krak | sol     | 15m         | 1641 |   1641 |    0 |      0 |           0    |
| bin+coin+krak | sol     | 5m          | 4924 |   4924 |    0 |      0 |           0    |
| median3       | btc     | 15m         | 1641 |   1288 |  183 |    170 |          21.51 |
| median3       | btc     | 5m          | 4925 |   3858 |  523 |    544 |          21.66 |
| median3       | eth     | 15m         | 1641 |   1288 |  167 |    186 |          21.51 |
| median3       | eth     | 5m          | 4924 |   3859 |  504 |    561 |          21.63 |
| median3       | sol     | 15m         | 1641 |   1288 |  167 |    186 |          21.51 |
| median3       | sol     | 5m          | 4924 |   3857 |  528 |    539 |          21.67 |
| q90-bin       | btc     | 15m         | 1641 |   1613 |   10 |     18 |           1.71 |
| q90-bin       | btc     | 5m          | 4925 |   4906 |    6 |     13 |           0.39 |
| q90-bin       | eth     | 15m         | 1641 |   1615 |   10 |     16 |           1.58 |
| q90-bin       | eth     | 5m          | 4924 |   4901 |    7 |     16 |           0.47 |
| q90-bin       | sol     | 15m         | 1641 |   1617 |    9 |     15 |           1.46 |
| q90-bin       | sol     | 5m          | 4924 |   4905 |    3 |     16 |           0.39 |
| q90-ensemble  | btc     | 15m         | 1641 |   1612 |   11 |     18 |           1.77 |
| q90-ensemble  | btc     | 5m          | 4925 |   4906 |    6 |     13 |           0.39 |
| q90-ensemble  | eth     | 15m         | 1641 |   1613 |   11 |     17 |           1.71 |
| q90-ensemble  | eth     | 5m          | 4924 |   4902 |    6 |     16 |           0.45 |
| q90-ensemble  | sol     | 15m         | 1641 |   1615 |   11 |     15 |           1.58 |
| q90-ensemble  | sol     | 5m          | 4924 |   4904 |    3 |     17 |           0.41 |

## Headline ranking (by policy)

### Policy: HOLD

| candidate     |     n |   hit_rate |   sig_won_rate |   total_pnl |   mean_pnl |   roi_pct |   sharpe |       sortino |     max_dd |   avg_vwap_e |   avg_lvls_e |   underfilled_pct |   hedged_pct |
|:--------------|------:|-----------:|---------------:|------------:|-----------:|----------:|---------:|--------------:|-----------:|-------------:|-------------:|------------------:|-------------:|
| q90-bin       |   118 |   0.525424 |       0.525424 |    -576.115 |   -4.88233 | -19.5293  | -37.4227 |  -1.68893e+18 |   -649.066 |     0.606041 |      1.86441 |        0          |            0 |
| q90-ensemble  |   121 |   0.520661 |       0.520661 |    -613.477 |   -5.07006 | -20.2802  | -39.4495 |  -1.80803e+18 |   -686.428 |     0.607257 |      1.86777 |        0          |            0 |
| bin+coinbase  |  1836 |   0.54085  |       0.54085  |   -4703.07  |   -2.56158 | -10.2462  | -64.2351 |  -1.89276e+18 |  -4720.64  |     0.577568 |      2.07898 |        0.0544662  |            0 |
| kraken        |  2403 |   0.549313 |       0.549313 |   -5106.78  |   -2.12517 |  -8.50067 | -53.3906 |  -1.31593e+18 |  -5377.77  |     0.571106 |      2.28423 |        0          |            0 |
| bin-vision    |  1836 |   0.536492 |       0.536492 |   -5264.9   |   -2.86759 | -11.4702  | -72.7174 |  -2.15243e+18 |  -5282.47  |     0.57856  |      2.07625 |        0.0544662  |            0 |
| median3       |  3921 |   0.54986  |       0.54986  |   -8168.29  |   -2.08321 |  -8.3328  | -28.0136 |  -7.63078e+17 |  -8471.39  |     0.576737 |      2.17802 |        0.0255037  |            0 |
| okx           | 12371 |   0.544014 |       0.544014 |  -27291.2   |   -2.20606 |  -8.82424 | -53.5743 |  -1.34264e+18 | -27740.4   |     0.571322 |      2.27379 |        0          |            0 |
| bin-ws        | 16586 |   0.547088 |       0.547088 |  -28942.7   |   -1.74501 |  -6.98002 | -39.8189 |  -1.04418e+18 | -29378.3   |     0.567631 |      2.25069 |        0          |            0 |
| coinbase      | 18098 |   0.54564  |       0.54564  |  -33905.5   |   -1.87344 |  -7.49375 | -44.9302 |  -1.19901e+18 | -34258.6   |     0.569076 |      2.23422 |        0.00552547 |            0 |
| bin+coin+krak |     0 | nan        |     nan        |     nan     |  nan       | nan       | nan      | nan           |    nan     |   nan        |    nan       |      nan          |          nan |

## Permutation null vs observed
_Spec target: p<0.01 (operator §4)_

|   observed |   null_mean |   null_std |   null_q05 |   null_q95 |   p_value |   n_perm | candidate    | policy   |
|-----------:|------------:|-----------:|-----------:|-----------:|----------:|---------:|:-------------|:---------|
|  -5264.9   |  2920.91    |   1317.13  |    780.722 |   4988.86  |     1     |     1000 | bin-vision   | HOLD     |
| -28942.7   | 57926.1     |   4655.31  |  50487.2   |  65649.8   |     1     |     1000 | bin-ws       | HOLD     |
| -33905.5   | 59241.4     |   4850.28  |  51254.3   |  66938.6   |     1     |     1000 | coinbase     | HOLD     |
|  -5106.78  | 12081.7     |   2151.68  |   8479.45  |  15515.9   |     1     |     1000 | kraken       | HOLD     |
| -27291.2   | 44450.3     |   4137.85  |  37694     |  50916.2   |     1     |     1000 | okx          | HOLD     |
|  -4703.07  |  3157.27    |   1342.54  |    880.108 |   5246.5   |     1     |     1000 | bin+coinbase | HOLD     |
|  -8168.29  | 11823.4     |   2421.04  |   7622.62  |  15752.2   |     1     |     1000 | median3      | HOLD     |
|   -576.115 |   -20.1543  |    305.495 |   -521.6   |    483.862 |     0.966 |     1000 | q90-bin      | HOLD     |
|   -613.477 |    -8.50873 |    318.561 |   -524.05  |    495.309 |     0.977 |     1000 | q90-ensemble | HOLD     |

## Walk-forward stability (per-fold PnL)
_Edge must hold across MAJORITY of folds, not just averaged._

### bin-ws × HOLD: 0/10 positive test folds  (median test PnL $-2053.79)

### coinbase × HOLD: 0/10 positive test folds  (median test PnL $-2079.43)

### median3 × HOLD: 0/5 positive test folds  (median test PnL $+0.00)

### okx × HOLD: 0/4 positive test folds  (median test PnL $-2253.41)


## Verdict (auto-generated from headline)

**HOLD** — top candidate: `q90-bin` (n=118, hit=52.54%, PnL=$-576.12, Sharpe=-37.42)
