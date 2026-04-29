# Polymarket Hedge-Fallback Policies — Realfills Backtest

Stake: $25. rev_bp=5. Realistic L10 book-walked entries + hedge attempts. `hedge_fail_p` synthetically forces hedge attempts to fail with given probability (simulates production cache+staleness bug chain). Seed=42.

## Policies

- **HEDGE_HOLD** — current locked: buy-opposite-ask. If fails → ride to resolution.
- **SELL_OWN_BID** — at reversal trigger, sell held side into ITS OWN bid. Never hedges.
- **HYBRID** — try hedge first; if fails → fall back to sell own bid.
- **STOPLOSS_20** — exit at own bid if held bid drops by $0.20 from entry, OR on reversal.


## q10 × 5m × ALL

| Policy | Fail% | n | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% | StopTrig |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | 392 | +34.50% | 72.7% | +95.7 | $-137 | 53% | 0% | 47% | 0 |
| HEDGE_HOLD | 50% | 392 | +24.46% | 68.1% | +54.6 | $-207 | 25% | 0% | 75% | 0 |
| HEDGE_HOLD | 100% | 392 | +13.62% | 61.2% | +26.1 | $-378 | 0% | 0% | 100% | 0 |
| HYBRID | 0% | 392 | +34.50% | 72.7% | +95.7 | $-137 | 53% | 0% | 47% | 0 |
| HYBRID | 50% | 392 | +35.55% | 73.7% | +99.0 | $-132 | 25% | 27% | 47% | 0 |
| HYBRID | 100% | 392 | +36.41% | 74.7% | +101.8 | $-130 | 0% | 53% | 47% | 0 |
| SELL_OWN_BID | 0% | 392 | +36.41% | 74.7% | +101.8 | $-130 | 0% | 53% | 47% | 0 |
| SELL_OWN_BID | 50% | 392 | +36.41% | 74.7% | +101.8 | $-130 | 0% | 53% | 47% | 0 |
| SELL_OWN_BID | 100% | 392 | +36.41% | 74.7% | +101.8 | $-130 | 0% | 53% | 47% | 0 |
| STOPLOSS_20 | 0% | 392 | +29.51% | 67.1% | +87.4 | $-80 | 0% | 66% | 34% | 90 |
| STOPLOSS_20 | 50% | 392 | +29.51% | 67.1% | +87.4 | $-80 | 0% | 66% | 34% | 90 |
| STOPLOSS_20 | 100% | 392 | +29.51% | 67.1% | +87.4 | $-80 | 0% | 66% | 34% | 90 |

## q20 × 15m × ALL

| Policy | Fail% | n | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% | StopTrig |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | 230 | +31.43% | 67.4% | +82.7 | $-58 | 62% | 0% | 38% | 0 |
| HEDGE_HOLD | 50% | 230 | +27.69% | 66.5% | +51.7 | $-232 | 29% | 0% | 71% | 0 |
| HEDGE_HOLD | 100% | 230 | +22.50% | 66.1% | +35.1 | $-324 | 0% | 0% | 100% | 0 |
| HYBRID | 0% | 230 | +31.43% | 67.4% | +82.7 | $-58 | 62% | 0% | 38% | 0 |
| HYBRID | 50% | 230 | +32.50% | 68.3% | +86.3 | $-49 | 29% | 33% | 38% | 0 |
| HYBRID | 100% | 230 | +33.38% | 69.1% | +89.3 | $-45 | 0% | 62% | 38% | 0 |
| SELL_OWN_BID | 0% | 230 | +33.38% | 69.1% | +89.3 | $-45 | 0% | 62% | 38% | 0 |
| SELL_OWN_BID | 50% | 230 | +33.38% | 69.1% | +89.3 | $-45 | 0% | 62% | 38% | 0 |
| SELL_OWN_BID | 100% | 230 | +33.38% | 69.1% | +89.3 | $-45 | 0% | 62% | 38% | 0 |
| STOPLOSS_20 | 0% | 230 | +30.39% | 66.5% | +82.3 | $-44 | 0% | 66% | 34% | 28 |
| STOPLOSS_20 | 50% | 230 | +30.39% | 66.5% | +82.3 | $-44 | 0% | 66% | 34% | 28 |
| STOPLOSS_20 | 100% | 230 | +30.39% | 66.5% | +82.3 | $-44 | 0% | 66% | 34% | 28 |

## q10 × 15m × ALL

| Policy | Fail% | n | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% | StopTrig |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | 117 | +35.97% | 74.4% | +77.7 | $-25 | 66% | 0% | 34% | 0 |
| HEDGE_HOLD | 50% | 117 | +32.79% | 70.1% | +46.2 | $-75 | 32% | 0% | 68% | 0 |
| HEDGE_HOLD | 100% | 117 | +33.93% | 72.6% | +40.1 | $-135 | 0% | 0% | 100% | 0 |
| HYBRID | 0% | 117 | +35.97% | 74.4% | +77.7 | $-25 | 66% | 0% | 34% | 0 |
| HYBRID | 50% | 117 | +36.90% | 75.2% | +80.4 | $-25 | 32% | 34% | 34% | 0 |
| HYBRID | 100% | 117 | +37.97% | 77.8% | +83.5 | $-25 | 0% | 66% | 34% | 0 |
| SELL_OWN_BID | 0% | 117 | +37.97% | 77.8% | +83.5 | $-25 | 0% | 66% | 34% | 0 |
| SELL_OWN_BID | 50% | 117 | +37.97% | 77.8% | +83.5 | $-25 | 0% | 66% | 34% | 0 |
| SELL_OWN_BID | 100% | 117 | +37.97% | 77.8% | +83.5 | $-25 | 0% | 66% | 34% | 0 |
| STOPLOSS_20 | 0% | 117 | +36.02% | 76.9% | +77.9 | $-24 | 0% | 68% | 32% | 7 |
| STOPLOSS_20 | 50% | 117 | +36.02% | 76.9% | +77.9 | $-24 | 0% | 68% | 32% | 7 |
| STOPLOSS_20 | 100% | 117 | +36.02% | 76.9% | +77.9 | $-24 | 0% | 68% | 32% | 7 |

## q10 × 5m × btc

| Policy | Fail% | n | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% | StopTrig |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | 131 | +41.48% | 74.8% | +67.0 | $-43 | 47% | 0% | 53% | 0 |
| HEDGE_HOLD | 50% | 131 | +34.17% | 72.5% | +45.0 | $-100 | 24% | 0% | 76% | 0 |
| HEDGE_HOLD | 100% | 131 | +29.50% | 68.7% | +33.3 | $-118 | 0% | 0% | 100% | 0 |
| HYBRID | 0% | 131 | +41.48% | 74.8% | +67.0 | $-43 | 47% | 0% | 53% | 0 |
| HYBRID | 50% | 131 | +41.94% | 75.6% | +68.0 | $-42 | 24% | 24% | 53% | 0 |
| HYBRID | 100% | 131 | +42.50% | 77.1% | +69.1 | $-42 | 0% | 47% | 53% | 0 |
| SELL_OWN_BID | 0% | 131 | +42.50% | 77.1% | +69.1 | $-42 | 0% | 47% | 53% | 0 |
| SELL_OWN_BID | 50% | 131 | +42.50% | 77.1% | +69.1 | $-42 | 0% | 47% | 53% | 0 |
| SELL_OWN_BID | 100% | 131 | +42.50% | 77.1% | +69.1 | $-42 | 0% | 47% | 53% | 0 |
| STOPLOSS_20 | 0% | 131 | +36.79% | 70.2% | +59.6 | $-39 | 0% | 56% | 44% | 25 |
| STOPLOSS_20 | 50% | 131 | +36.79% | 70.2% | +59.6 | $-39 | 0% | 56% | 44% | 25 |
| STOPLOSS_20 | 100% | 131 | +36.79% | 70.2% | +59.6 | $-39 | 0% | 56% | 44% | 25 |

## q10 × 5m × eth

| Policy | Fail% | n | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% | StopTrig |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | 130 | +36.51% | 74.6% | +57.6 | $-42 | 54% | 0% | 46% | 0 |
| HEDGE_HOLD | 50% | 130 | +29.75% | 71.5% | +38.7 | $-79 | 28% | 0% | 72% | 0 |
| HEDGE_HOLD | 100% | 130 | +15.49% | 61.5% | +17.1 | $-113 | 0% | 0% | 100% | 0 |
| HYBRID | 0% | 130 | +36.51% | 74.6% | +57.6 | $-42 | 54% | 0% | 46% | 0 |
| HYBRID | 50% | 130 | +37.15% | 74.6% | +58.7 | $-42 | 28% | 26% | 46% | 0 |
| HYBRID | 100% | 130 | +37.84% | 75.4% | +60.1 | $-42 | 0% | 54% | 46% | 0 |
| SELL_OWN_BID | 0% | 130 | +37.84% | 75.4% | +60.1 | $-42 | 0% | 54% | 46% | 0 |
| SELL_OWN_BID | 50% | 130 | +37.84% | 75.4% | +60.1 | $-42 | 0% | 54% | 46% | 0 |
| SELL_OWN_BID | 100% | 130 | +37.84% | 75.4% | +60.1 | $-42 | 0% | 54% | 46% | 0 |
| STOPLOSS_20 | 0% | 130 | +28.73% | 66.9% | +49.0 | $-39 | 0% | 69% | 31% | 34 |
| STOPLOSS_20 | 50% | 130 | +28.73% | 66.9% | +49.0 | $-39 | 0% | 69% | 31% | 34 |
| STOPLOSS_20 | 100% | 130 | +28.73% | 66.9% | +49.0 | $-39 | 0% | 69% | 31% | 34 |

## q10 × 5m × sol

| Policy | Fail% | n | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% | StopTrig |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | 131 | +25.54% | 68.7% | +42.0 | $-83 | 56% | 0% | 44% | 0 |
| HEDGE_HOLD | 50% | 131 | +11.67% | 61.1% | +15.3 | $-193 | 28% | 0% | 72% | 0 |
| HEDGE_HOLD | 100% | 131 | -4.10% | 53.4% | -4.6 | $-274 | 0% | 0% | 100% | 0 |
| HYBRID | 0% | 131 | +25.54% | 68.7% | +42.0 | $-83 | 56% | 0% | 44% | 0 |
| HYBRID | 50% | 131 | +27.09% | 70.2% | +44.6 | $-74 | 28% | 28% | 44% | 0 |
| HYBRID | 100% | 131 | +28.91% | 71.8% | +47.9 | $-69 | 0% | 56% | 44% | 0 |
| SELL_OWN_BID | 0% | 131 | +28.91% | 71.8% | +47.9 | $-69 | 0% | 56% | 44% | 0 |
| SELL_OWN_BID | 50% | 131 | +28.91% | 71.8% | +47.9 | $-69 | 0% | 56% | 44% | 0 |
| SELL_OWN_BID | 100% | 131 | +28.91% | 71.8% | +47.9 | $-69 | 0% | 56% | 44% | 0 |
| STOPLOSS_20 | 0% | 131 | +23.01% | 64.1% | +42.7 | $-43 | 0% | 73% | 27% | 31 |
| STOPLOSS_20 | 50% | 131 | +23.01% | 64.1% | +42.7 | $-43 | 0% | 73% | 27% | 31 |
| STOPLOSS_20 | 100% | 131 | +23.01% | 64.1% | +42.7 | $-43 | 0% | 73% | 27% | 31 |

## Reading the table
- **Fail%** = probability we synthetically force the hedge attempt to fail. 0% = clean book; 100% = hedge always fails (current production reality due to bugs).
- **Hedged%** = fraction of trades that ended up hedged (target outcome of HEDGE_HOLD when book is healthy).
- **BidExit%** = fraction that closed via own-bid sell (the countermeasure path).
- **Rode%** = fraction that rode to natural resolution (no hedge, no exit). Under HEDGE_HOLD at fail=100%, this catches ALL the failed hedges → loses on every wrong-direction signal.
- **StopTrig** = trades where the STOPLOSS_20 stop fired before any reversal trigger.

## Headline comparison — q10 × 5m × ALL

| Policy | ROI@0% | ROI@50% | ROI@100% | Δ@100% vs HEDGE_HOLD@100% |
|---|---:|---:|---:|---:|
| HEDGE_HOLD | +34.50% | +24.46% | +13.62% | +0.00 pp |
| SELL_OWN_BID | +36.41% | +36.41% | +36.41% | +22.79 pp |
| HYBRID | +34.50% | +35.55% | +36.41% | +22.79 pp |
| STOPLOSS_20 | +29.51% | +29.51% | +29.51% | +15.89 pp |