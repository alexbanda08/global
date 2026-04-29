# Kronos FT — BTC Deep Analysis V2 (Stability + Confidence)

Source: `strategy_lab/results/kronos/ft_sniff_BTCUSDT_5m_3y_polymarket_short.csv`  
Bootstrap samples: 5000

## 1. Weekly accuracy — 5m horizon

Is March's collapse uniform or one bad week?

| Week | n | Acc |
|---|---|---|
| 2026-01-06/2026-01-12 | 25 | 0.640 |
| 2026-01-13/2026-01-19 | 45 | 0.667 |
| 2026-01-20/2026-01-26 | 45 | 0.600 |
| 2026-01-27/2026-02-02 | 44 | 0.500 |
| 2026-02-03/2026-02-09 | 45 | 0.533 |
| 2026-02-10/2026-02-16 | 45 | 0.600 |
| 2026-02-17/2026-02-23 | 45 | 0.578 |
| 2026-02-24/2026-03-02 | 45 | 0.622 |
| 2026-03-03/2026-03-09 | 44 | 0.545 |
| 2026-03-10/2026-03-16 | 45 | 0.556 |
| 2026-03-17/2026-03-23 | 45 | 0.489 |
| 2026-03-24/2026-03-30 | 25 | 0.560 |

## 2. Confidence-decile ladder — 5m

Accuracy sorted by prediction magnitude. A rising staircase = selective trading is viable.

| Decile | n | Acc | Avg \|pred\| % |
|---|---|---|---|
| D1 | 50 | 0.500 | 0.0033 |
| D2 | 50 | 0.600 | 0.0101 |
| D3 | 50 | 0.560 | 0.0173 |
| D4 | 49 | 0.510 | 0.0259 |
| D5 | 50 | 0.520 | 0.0359 |
| D6 | 50 | 0.620 | 0.0499 |
| D7 | 49 | 0.531 | 0.0668 |
| D8 | 50 | 0.560 | 0.0907 |
| D9 | 50 | 0.700 | 0.1325 |
| D10 | 50 | 0.620 | 0.3800 |

## 3. Selective-trading thresholds — 5m

Only bet on the top X% highest-|pred_ret| forecasts.

| Top fraction | n | Acc | 95% CI | Avg \|pred\| % |
|---|---|---|---|---|
| 50% | 249 | 0.606 | [0.546, 0.667] | 0.1443 |
| 25% | 125 | 0.632 | [0.544, 0.712] | 0.2247 |
| 10% | 50 | 0.620 | [0.480, 0.760] | 0.3800 |
| 5% | 25 | 0.600 | [0.400, 0.800] | 0.5564 |

## 4. Does selective trading survive the March drop?

Top 25% by month (only the most confident predictions):

| Month | n | Acc |
|---|---|---|
| 2026-01 | 22 | 0.682 |
| 2026-02 | 54 | 0.685 |
| 2026-03 | 49 | 0.551 |

Top 10% by month (elite confidence):

| Month | n | Acc |
|---|---|---|
| 2026-01 | 8 | 0.625 |
| 2026-02 | 22 | 0.682 |
| 2026-03 | 20 | 0.550 |

## 5. Accuracy by UTC hour — 5m

| Hour (UTC) | n | Acc |
|---|---|---|
| 00 | 16 | 0.500 |
| 01 | 16 | 0.500 |
| 02 | 31 | 0.484 |
| 03 | 15 | 0.600 |
| 04 | 16 | 0.375 |
| 05 | 30 | 0.567 |
| 06 | 15 | 0.467 |
| 07 | 15 | 0.533 |
| 08 | 32 | 0.625 |
| 09 | 15 | 0.533 |
| 10 | 16 | 0.750 |
| 11 | 31 | 0.613 |
| 12 | 16 | 0.688 |
| 13 | 15 | 0.600 |
| 14 | 31 | 0.645 |
| 15 | 16 | 0.438 |
| 16 | 16 | 0.500 |
| 17 | 31 | 0.581 |
| 18 | 15 | 0.600 |
| 19 | 16 | 0.625 |
| 20 | 32 | 0.781 |
| 21 | 16 | 0.562 |
| 22 | 15 | 0.667 |
| 23 | 31 | 0.387 |

## 6. Accuracy by weekday — 5m

| Day | n | Acc |
|---|---|---|
| Monday | 70 | 0.600 |
| Tuesday | 70 | 0.557 |
| Wednesday | 71 | 0.592 |
| Thursday | 71 | 0.578 |
| Friday | 77 | 0.558 |
| Saturday | 69 | 0.478 |
| Sunday | 70 | 0.643 |
