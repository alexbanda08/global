# Kronos Fine-Tune — BTC Deep Sniff Analysis

Source: `strategy_lab\results\kronos\ft_sniff_BTCUSDT_5m_3y_polymarket_short.csv`
Generated: 2026-04-23T15:09:21.283800
Bootstrap samples: 5000

## Verdict by horizon

| Horizon | n | Acc | 95% CI | Majority | Edge (pp) | Edge CI | Pearson | MAE% | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **5m** | 498 | 0.572 | [0.528, 0.615] | 0.500 | **+7.2** | [+2.8, +11.4] | +0.110 | 0.132 | **REAL** |
| **15m** | 499 | 0.531 | [0.487, 0.577] | 0.515 | **+1.6** | [-2.8, +6.2] | +0.092 | 0.234 | **MARGINAL** |
| **30m** | 500 | 0.540 | [0.494, 0.582] | 0.518 | **+2.2** | [-2.4, +6.4] | -0.014 | 0.338 | **MARGINAL** |
| **45m** | 500 | 0.540 | [0.496, 0.584] | 0.512 | **+2.8** | [-1.6, +7.2] | +0.022 | 0.431 | **MARGINAL** |

**Decision rule:** Verdict = REAL when the lower 95% CI on edge > 0 AND accuracy CI lower bound > 50%.

## Monthly breakdown — 5m

| Month | n | Acc | Majority | Edge (pp) |
|---|---|---|---|---|
| 2026-01 | 147 | 0.599 | 0.537 | +6.1 |
| 2026-02 | 179 | 0.587 | 0.508 | +7.8 |
| 2026-03 | 172 | 0.535 | 0.523 | +1.2 |

## Monthly breakdown — 15m

| Month | n | Acc | Majority | Edge (pp) |
|---|---|---|---|---|
| 2026-01 | 148 | 0.513 | 0.500 | +1.4 |
| 2026-02 | 179 | 0.508 | 0.503 | +0.6 |
| 2026-03 | 172 | 0.570 | 0.541 | +2.9 |

## Monthly breakdown — 30m

| Month | n | Acc | Majority | Edge (pp) |
|---|---|---|---|---|
| 2026-01 | 149 | 0.550 | 0.564 | -1.3 |
| 2026-02 | 179 | 0.525 | 0.542 | -1.7 |
| 2026-03 | 172 | 0.546 | 0.546 | -0.0 |

## Monthly breakdown — 45m

| Month | n | Acc | Majority | Edge (pp) |
|---|---|---|---|---|
| 2026-01 | 149 | 0.530 | 0.537 | -0.7 |
| 2026-02 | 179 | 0.525 | 0.542 | -1.7 |
| 2026-03 | 172 | 0.564 | 0.541 | +2.3 |

## Volatility regime — 5m horizon (|actual_ret| quartile)

| Quartile | n | Acc |
|---|---|---|
| Q1_low | 125 | 0.608 |
| Q2 | 124 | 0.589 |
| Q3 | 124 | 0.532 |
| Q4_high | 125 | 0.560 |

## Polymarket EV estimate (5m)

| Payout assumption | EV per $1 |
|---|---|
| 1.00 (spread 0%) | +0.1446 |
| 0.97 (spread 3%) | +0.1274 |
| 0.95 (spread 5%) | +0.1160 |
| 0.92 (spread 8%) | +0.0988 |
| 0.90 (spread 10%) | +0.0874 |

EV > 0 after the worst plausible spread = strategy is viable.
