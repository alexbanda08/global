# GPU LSTM sequence model — 9 series (8.8y BTC/ETH/SOL) — summary 2026-06-03

Deep LSTM (SEQ=64, 5 features) on RTX 3060, next-bar direction, walk-forward train70/val15/**test15**.

| series | test acc | strat Sharpe | buy&hold |
|---|--:|--:|--:|
| BTC 1h | 0.510 | -1.53 | -0.50 |
| BTC 15m | 0.517 | -5.08 | -0.24 |
| BTC 4h | 0.502 | 0.00 | -1.04 |
| ETH 1h | 0.512 | -1.32 | -0.36 |
| ETH 15m | 0.519 | -4.57 | -0.18 |
| ETH 4h | 0.503 | -2.03 | -0.75 |
| SOL 1h | 0.504 | 0.00 | -1.27 |
| SOL 15m | 0.507 | -0.03 | -0.62 |
| SOL 4h | 0.489 | 0.00 | -2.50 |

## Verdict: deep nets find NO tradeable direction in crypto klines
- **Accuracy 0.489–0.519 = coin-flip** on every series/TF. The 0.01–0.02 above 0.50 is noise, not edge.
- **Every strategy Sharpe ≤ 0** (held-out). When the net traded actively (15m) it LOST the most (−4.6 to −5.1)
  — fees on noise. Where it abstained (4h) Sharpe=0.
- Confirms the indicator sweep + the whole session's thesis: **crypto spot direction is efficient**; neither
  TA combos nor a deep sequence model beats it. The GPU is working (CUDA confirmed) — the *market*, not the
  tooling, is the wall.
- Honest implication: do NOT pursue underlying-crypto direction prediction. The edges live in execution
  (the Polymarket exit-scalp) and relative-value, not in forecasting price.
