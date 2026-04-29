# Kronos vs Naive Baselines — BTC 5m

Same 500 test windows. Measures whether the 400 MB fine-tuned Kronos actually beats 3-line baselines.

## Overall (unfiltered)

| Predictor | n | Acc | 95% CI |
|---|---|---|---|
| Kronos | 498 | 0.572 | [0.528, 0.615] |
| Momentum | 498 | 0.486 | [0.442, 0.530] |
| Reversion | 498 | 0.510 | [0.466, 0.554] |
| HourBias (fit-Jan) | 498 | 0.552 | [0.510, 0.596] |

## In the hour+dow filter window (the actual trading universe)

Hours: [8, 10, 11, 12, 14, 17, 18, 19, 20, 22] | Exclude: Saturday

| Predictor | n | Acc | 95% CI |
|---|---|---|---|
| Kronos | 202 | 0.693 | [0.629, 0.757] |
| Momentum | 202 | 0.520 | [0.451, 0.589] |
| Reversion | 202 | 0.480 | [0.411, 0.549] |
| HourBias (fit-Jan) | 202 | 0.525 | [0.455, 0.594] |

## Interpretation

- Kronos - Momentum (filtered) = **+17.3pp**
- **Kronos adds substantial value over naive momentum.**
