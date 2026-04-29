# Kronos fine-tuned sniff — BTCUSDT_5m_3y_polymarket_short

**Model**: `D:/kronos-ft//BTCUSDT_5m_3y_polymarket_short/basemodel/best_model`  

**Tokenizer**: `D:/kronos-ft//BTCUSDT_5m_3y_polymarket_short/tokenizer/best_model`  

**Lookback**: 512  **Pred len**: 9  **Sample count**: 8  **Windows**: 500

## Per-horizon results

| Horizon | n | Pearson | Dir Acc | Pos Bias | Majority-bet | **Edge (pp)** | MAE% | Passes |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| 5m | 500 | 0.1105 | 0.57 | 0.498 | 0.502 | **+6.80** | 0.0013 | PASS |
| 15m | 500 | 0.0919 | 0.53 | 0.484 | 0.516 | **+1.40** | 0.0023 | fail |
| 30m | 500 | -0.0138 | 0.54 | 0.518 | 0.518 | **+2.20** | 0.0034 | fail |
| 45m | 500 | 0.0217 | 0.54 | 0.512 | 0.512 | **+2.80** | 0.0043 | fail |

## Polymarket read

`Edge (pp)` = direction accuracy − always-bet-majority baseline. Positive = model beats naive. PASS gate requires edge > 2pp AND Pearson > 0.05.


Per-window forecasts at `results/kronos/ft_sniff_BTCUSDT_5m_3y_polymarket_short.csv`.