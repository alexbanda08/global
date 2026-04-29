# Polymarket Backtest V1 — Hold-to-Resolution

Source: `strategy_lab/data/polymarket/btc_markets.csv`
Markets: 444 (333 BTC 5m + 111 BTC 15m, resolved with full entry data)
Fee assumption: 2.0% on winnings (Polymarket trading fee)
Stake per bet: $1 (scale linearly)

## Strategy

At each market's window-start timestamp, bet sign(signal) on the appropriate outcome
(buy YES if UP, buy NO if DOWN). Hold to resolution. Pay entry ask, receive $1 if correct.

## PnL by signal accuracy (Monte-Carlo, 10k sims per row)

| Accuracy | Mean PnL | 95% CI | ROI per bet | Profit rate | Mean DD | Sharpe |
|---|---|---|---|---|---|---|
| **50%** | $-4.44 | [$-24.31, $+16.03] | -1.00% | 33.7% | $14.60 | -0.43 |
| **55%** | $+17.51 | [$-2.72, $+37.79] | +3.94% | 95.5% | $7.65 | 1.69 |
| **60%** | $+39.40 | [$+19.22, $+59.03] | +8.87% | 100.0% | $5.04 | 3.87 |
| **65%** | $+61.21 | [$+41.96, $+80.52] | +13.79% | 100.0% | $3.77 | 6.17 |
| **69%** | $+79.07 | [$+59.84, $+98.07] | +17.81% | 100.0% | $3.07 | 8.23 |
| **72%** | $+92.23 | [$+73.63, $+110.35] | +20.77% | 100.0% | $2.69 | 9.89 |
| **75%** | $+105.19 | [$+87.38, $+122.31] | +23.69% | 100.0% | $2.37 | 11.69 |
| **80%** | $+127.38 | [$+111.07, $+143.71] | +28.69% | 100.0% | $1.93 | 15.35 |

Interpretation:
- Each bet stakes $1. Total PnL is dollar profit across all 444 bets.
- CI tells the range of outcomes across randomized signals. If CI includes negative, strategy is risky.
- ROI per bet = average profit per $1 bet. Comparable to per-trade edge.
- Profit rate = % of Monte-Carlo runs that ended profitable.

## Entry-price filter (skip expensive markets)

At signal accuracy 69% (measured Kronos), skip markets where the bet-side ask > threshold.

| Max entry ask | Accuracy | Mean PnL | 95% CI | # bets | ROI/bet |
|---|---|---|---|---|---|
| 0.600 | 69% | $+79.10 | [$+59.76, $+98.35] | 444 | +17.81% |
| 0.550 | 69% | $+79.04 | [$+59.96, $+97.49] | 444 | +17.80% |
| 0.530 | 69% | $+78.87 | [$+59.67, $+97.85] | 443 | +17.80% |
| 0.520 | 69% | $+75.02 | [$+55.95, $+92.80] | 428 | +17.52% |
| 0.510 | 69% | $+67.42 | [$+50.45, $+84.30] | 377 | +17.87% |

## Key insights

- **At 50% accuracy (random signal):** mean PnL $-4.44 (essentially 0 — fees and spread eat you).
- **At 69% Kronos accuracy:** mean PnL $+79.07, ROI +17.81% per bet, profitable in 100.0% of Monte-Carlo runs.
- **Verdict: Kronos-grade signal is clearly profitable on real Polymarket data.**
