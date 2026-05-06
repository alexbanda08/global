# Exit Policy — Multi-Asset × Multi-Timeframe

_Generated: 2026-05-05_

## Setup

Same canonical engine as previous (book-walked entry, 2% taker, $25 stake, asset-specific spread filter). Signal is **top-10% |asset_ret_2m|** (entry @ t+120s). V3 features only exist for BTC; V3 entries fire at bucket 0 (Binance bar close).

## Why 15m might underperform 5m

**Mechanical reason**: the signal observes 2 minutes of price action. For a 5m market, that's **40%** of the lifetime — only 3 min remain to reverse. For a 15m market, that's **13%** — **13 min remain** for the move to mean-revert. Longer post-signal exposure = more chance the directional bet decays to noise.

### Naive hit-rate (top-10% momentum signal, no exits)

| Asset | TF | n | hit% | signal share of market |
|---|---|---:|---:|---:|
| BTC | 5m | 351 | 86.0% | 40% |
| BTC | 15m | 117 | 79.5% | 13% |
| ETH | 5m | 351 | 90.9% | 40% |
| ETH | 15m | 117 | 75.2% | 13% |
| SOL | 5m | 351 | 89.2% | 40% |
| SOL | 15m | 117 | 79.5% | 13% |

Hit rates drop ~7-12pp from 5m → 15m for all three assets, consistent with the longer revert window theory. The signal is observation-bound: knowing BTC moved 0.5% in the first 2 min predicts the next 3 min better than the next 13.

**For V3**: V3's `prob_stack` was calibrated on 5-minute features. V3 has no equivalent 15-minute feature stack — when applied to 15m markets, V3's prob_stack is essentially the 5m signal applied to a longer horizon, hence the hit-rate decay near coin-flip.

## All results — one row per (asset_tf, policy)

| Cell × Policy | n | hit% | total PnL | mean | std | hold | hedge | sell | Sharpe | Sortino | maxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_only_5m | HOLD | 286 | 89.2% | $+3122.65 | $+10.9184 | $73.92 | 286 | 0 | 0 | +13.71 | +nan | $-93.77 |
| BTC_only_5m | HEDGE_REVERT_5 | 286 | 89.5% | $+3515.10 | $+12.2906 | $73.42 | 208 | 78 | 0 | +15.54 | +107.22 | $-64.87 |
| BTC_only_5m | SELL_REVERT_5 | 286 | 89.9% | $+3527.93 | $+12.3354 | $73.41 | 208 | 0 | 78 | +15.60 | +107.91 | $-64.28 |
| BTC_only_5m | SELL_REVERT_8 | 286 | 91.3% | $+3417.46 | $+11.9491 | $73.58 | 258 | 0 | 28 | +15.07 | +123.49 | $-93.77 |
| BTC_only_5m | SELL_FLOOR_040 | 286 | 79.4% | $+973.72 | $+3.4046 | $12.30 | 225 | 0 | 61 | +25.69 | +44.16 | $-153.63 |
| BTC_only_5m | SELL_FLOOR_035 | 286 | 79.7% | $+1027.54 | $+3.5928 | $12.94 | 228 | 0 | 58 | +25.78 | +49.63 | $-103.78 |
| BTC_only_5m | SELL_TRAIL_10 | 286 | 68.5% | $+1318.39 | $+4.6098 | $22.83 | 149 | 0 | 137 | +18.74 | +96.22 | $-48.00 |
| BTC_only_5m | SELL_TRAIL_15 | 286 | 71.7% | $+1391.21 | $+4.8644 | $23.41 | 173 | 0 | 113 | +19.28 | +79.14 | $-64.53 |
| BTC_only_15m | HOLD | 104 | 80.8% | $+738.92 | $+7.1050 | $19.23 | 104 | 0 | 0 | +20.77 | +nan | $-78.16 |
| BTC_only_15m | HEDGE_REVERT_5 | 104 | 83.7% | $+864.61 | $+8.3135 | $11.95 | 47 | 57 | 0 | +39.11 | +80.14 | $-25.00 |
| BTC_only_15m | SELL_REVERT_5 | 104 | 85.6% | $+886.53 | $+8.5243 | $12.02 | 47 | 0 | 57 | +39.85 | +79.02 | $-25.00 |
| BTC_only_15m | SELL_REVERT_8 | 104 | 84.6% | $+1023.46 | $+9.8410 | $14.03 | 62 | 0 | 42 | +39.44 | +83.14 | $-25.00 |
| BTC_only_15m | SELL_FLOOR_040 | 104 | 71.2% | $+581.28 | $+5.5893 | $12.47 | 70 | 0 | 34 | +25.20 | +49.52 | $-42.12 |
| BTC_only_15m | SELL_FLOOR_035 | 104 | 71.2% | $+549.30 | $+5.2817 | $12.78 | 70 | 0 | 34 | +23.24 | +52.00 | $-42.74 |
| BTC_only_15m | SELL_TRAIL_10 | 104 | 70.2% | $+469.45 | $+4.5140 | $7.86 | 26 | 0 | 78 | +32.27 | +77.64 | $-18.06 |
| BTC_only_15m | SELL_TRAIL_15 | 104 | 70.2% | $+502.13 | $+4.8282 | $9.05 | 37 | 0 | 67 | +29.99 | +54.51 | $-42.12 |
| ETH_only_5m | HOLD | 267 | 92.1% | $+2249.73 | $+8.4260 | $26.95 | 267 | 0 | 0 | +28.04 | +nan | $-64.99 |
| ETH_only_5m | HEDGE_REVERT_5 | 267 | 89.9% | $+2408.79 | $+9.0217 | $26.08 | 180 | 87 | 0 | +31.02 | +79.33 | $-42.14 |
| ETH_only_5m | SELL_REVERT_5 | 267 | 89.9% | $+2418.89 | $+9.0595 | $26.08 | 180 | 0 | 87 | +31.15 | +80.36 | $-41.50 |
| ETH_only_5m | SELL_REVERT_8 | 267 | 93.3% | $+2460.44 | $+9.2151 | $26.16 | 221 | 0 | 46 | +31.59 | +78.89 | $-36.02 |
| ETH_only_5m | SELL_FLOOR_040 | 267 | 75.7% | $+332.37 | $+1.2448 | $11.98 | 196 | 0 | 71 | +9.31 | +14.00 | $-478.15 |
| ETH_only_5m | SELL_FLOOR_035 | 267 | 76.4% | $+421.27 | $+1.5778 | $13.08 | 201 | 0 | 66 | +10.82 | +19.07 | $-482.33 |
| ETH_only_5m | SELL_TRAIL_10 | 267 | 64.0% | $+389.31 | $+1.4581 | $14.56 | 138 | 0 | 129 | +8.98 | +17.58 | $-478.99 |
| ETH_only_5m | SELL_TRAIL_15 | 267 | 67.4% | $+635.01 | $+2.3783 | $17.12 | 158 | 0 | 109 | +12.46 | +27.96 | $-500.66 |
| ETH_only_15m | HOLD | 94 | 76.6% | $+249.61 | $+2.6554 | $17.29 | 94 | 0 | 0 | +8.21 | +nan | $-144.14 |
| ETH_only_15m | HEDGE_REVERT_5 | 94 | 85.1% | $+498.56 | $+5.3038 | $7.82 | 33 | 61 | 0 | +36.25 | +44.95 | $-25.00 |
| ETH_only_15m | SELL_REVERT_5 | 94 | 86.2% | $+516.50 | $+5.4946 | $7.81 | 33 | 0 | 61 | +37.60 | +43.92 | $-25.00 |
| ETH_only_15m | SELL_REVERT_8 | 94 | 80.9% | $+535.87 | $+5.7008 | $8.86 | 44 | 0 | 50 | +34.41 | +53.06 | $-25.00 |
| ETH_only_15m | SELL_FLOOR_040 | 94 | 64.9% | $+259.54 | $+2.7611 | $13.36 | 60 | 0 | 34 | +11.05 | +23.75 | $-145.03 |
| ETH_only_15m | SELL_FLOOR_035 | 94 | 66.0% | $+217.83 | $+2.3173 | $13.92 | 61 | 0 | 33 | +8.90 | +21.56 | $-162.98 |
| ETH_only_15m | SELL_TRAIL_10 | 94 | 51.1% | $+207.90 | $+2.2117 | $7.59 | 20 | 0 | 74 | +15.57 | +24.18 | $-40.63 |
| ETH_only_15m | SELL_TRAIL_15 | 94 | 59.6% | $+223.12 | $+2.3736 | $7.85 | 31 | 0 | 63 | +16.16 | +23.91 | $-32.55 |
| SOL_only_5m | HOLD | 214 | 90.2% | $+2128.19 | $+9.9448 | $31.51 | 214 | 0 | 0 | +25.41 | +429.39 | $-90.83 |
| SOL_only_5m | HEDGE_REVERT_5 | 214 | 85.0% | $+2443.04 | $+11.4161 | $30.45 | 152 | 62 | 0 | +30.19 | +98.62 | $-50.00 |
| SOL_only_5m | SELL_REVERT_5 | 214 | 85.0% | $+2463.36 | $+11.5110 | $30.47 | 152 | 0 | 62 | +30.42 | +97.16 | $-50.00 |
| SOL_only_5m | SELL_REVERT_8 | 214 | 87.9% | $+2411.18 | $+11.2672 | $30.69 | 179 | 0 | 35 | +29.57 | +80.07 | $-63.67 |
| SOL_only_5m | SELL_FLOOR_040 | 214 | 69.6% | $-208.56 | $-0.9746 | $11.28 | 145 | 0 | 69 | -6.96 | -11.38 | $-399.82 |
| SOL_only_5m | SELL_FLOOR_035 | 214 | 71.0% | $-145.81 | $-0.6814 | $11.90 | 149 | 0 | 65 | -4.61 | -8.08 | $-349.03 |
| SOL_only_5m | SELL_TRAIL_10 | 214 | 59.8% | $+327.83 | $+1.5319 | $18.51 | 112 | 0 | 102 | +6.67 | +16.98 | $-223.59 |
| SOL_only_5m | SELL_TRAIL_15 | 214 | 61.7% | $+318.63 | $+1.4889 | $19.88 | 122 | 0 | 92 | +6.03 | +16.51 | $-256.48 |
| SOL_only_15m | HOLD | 71 | 84.5% | $+527.87 | $+7.4348 | $19.50 | 71 | 0 | 0 | +17.86 | +309933604348949632.00 | $-79.22 |
| SOL_only_15m | HEDGE_REVERT_5 | 71 | 76.1% | $+554.62 | $+7.8116 | $13.30 | 27 | 44 | 0 | +27.50 | +154.35 | $-9.50 |
| SOL_only_15m | SELL_REVERT_5 | 71 | 78.9% | $+565.87 | $+7.9701 | $13.23 | 27 | 0 | 44 | +28.21 | +158.56 | $-8.49 |
| SOL_only_15m | SELL_REVERT_8 | 71 | 80.3% | $+663.81 | $+9.3494 | $15.48 | 36 | 0 | 35 | +28.28 | +67.52 | $-25.00 |
| SOL_only_15m | SELL_FLOOR_040 | 71 | 66.2% | $+131.93 | $+1.8582 | $11.43 | 47 | 0 | 24 | +7.62 | +12.41 | $-77.26 |
| SOL_only_15m | SELL_FLOOR_035 | 71 | 69.0% | $+136.15 | $+1.9176 | $12.37 | 49 | 0 | 22 | +7.26 | +12.12 | $-90.34 |
| SOL_only_15m | SELL_TRAIL_10 | 71 | 54.9% | $+168.78 | $+2.3772 | $8.63 | 20 | 0 | 51 | +12.90 | +28.81 | $-38.77 |
| SOL_only_15m | SELL_TRAIL_15 | 71 | 62.0% | $+222.65 | $+3.1359 | $9.50 | 31 | 0 | 40 | +15.46 | +43.90 | $-43.88 |
| V3_BTC_5m | HOLD | 191 | 67.0% | $+1291.33 | $+6.7609 | $23.31 | 191 | 0 | 0 | +28.81 | +nan | $-231.15 |
| V3_BTC_5m | HEDGE_REVERT_5 | 191 | 70.7% | $+1559.69 | $+8.1659 | $20.61 | 150 | 41 | 0 | +39.36 | +129.41 | $-85.43 |
| V3_BTC_5m | SELL_REVERT_5 | 191 | 70.7% | $+1573.38 | $+8.2376 | $20.58 | 150 | 0 | 41 | +39.76 | +127.08 | $-85.12 |
| V3_BTC_5m | SELL_REVERT_8 | 191 | 68.6% | $+1456.26 | $+7.6244 | $22.39 | 174 | 0 | 17 | +33.83 | +168.42 | $-153.27 |
| V3_BTC_5m | SELL_FLOOR_040 | 191 | 43.5% | $+614.64 | $+3.2180 | $14.60 | 76 | 0 | 115 | +21.90 | +73.73 | $-109.55 |
| V3_BTC_5m | SELL_FLOOR_035 | 191 | 48.2% | $+816.48 | $+4.2748 | $16.28 | 91 | 0 | 100 | +26.08 | +91.90 | $-97.16 |
| V3_BTC_5m | SELL_TRAIL_10 | 191 | 42.9% | $+294.70 | $+1.5429 | $8.93 | 14 | 0 | 177 | +17.17 | +54.23 | $-71.72 |
| V3_BTC_5m | SELL_TRAIL_15 | 191 | 42.9% | $+401.57 | $+2.1025 | $10.51 | 31 | 0 | 160 | +19.87 | +70.65 | $-62.10 |
| V3_BTC_15m | HOLD | 57 | 71.9% | $+475.60 | $+8.3439 | $21.24 | 57 | 0 | 0 | +21.61 | +nan | $-79.04 |
| V3_BTC_15m | HEDGE_REVERT_5 | 57 | 70.2% | $+452.54 | $+7.9393 | $15.67 | 33 | 24 | 0 | +27.88 | +50.19 | $-40.41 |
| V3_BTC_15m | SELL_REVERT_5 | 57 | 70.2% | $+462.60 | $+8.1158 | $15.55 | 33 | 0 | 24 | +28.73 | +51.46 | $-39.50 |
| V3_BTC_15m | SELL_REVERT_8 | 57 | 63.2% | $+373.86 | $+6.5590 | $17.46 | 37 | 0 | 20 | +20.67 | +40.46 | $-48.10 |
| V3_BTC_15m | SELL_FLOOR_040 | 57 | 43.9% | $+243.59 | $+4.2734 | $13.28 | 24 | 0 | 33 | +17.71 | +81.36 | $-32.89 |
| V3_BTC_15m | SELL_FLOOR_035 | 57 | 47.4% | $+262.79 | $+4.6104 | $14.96 | 27 | 0 | 30 | +16.96 | +73.86 | $-37.56 |
| V3_BTC_15m | SELL_TRAIL_10 | 57 | 56.1% | $+85.85 | $+1.5061 | $5.22 | 1 | 0 | 56 | +15.89 | +53.82 | $-16.56 |
| V3_BTC_15m | SELL_TRAIL_15 | 57 | 47.4% | $+106.13 | $+1.8620 | $7.05 | 6 | 0 | 51 | +14.53 | +51.28 | $-29.51 |

## Best policy per cell

| Cell | Best by total PnL | n | hit% | total | Best by Sharpe | Sharpe | total |
|---|---|---:|---:|---:|---|---:|---:|
| BTC_only_15m | SELL_REVERT_8 | 104 | 84.6% | $+1023.46 | SELL_REVERT_5 | +39.85 | $+886.53 |
| BTC_only_5m | SELL_REVERT_5 | 286 | 89.9% | $+3527.93 | SELL_FLOOR_035 | +25.78 | $+1027.54 |
| ETH_only_15m | SELL_REVERT_8 | 94 | 80.9% | $+535.87 | SELL_REVERT_5 | +37.60 | $+516.50 |
| ETH_only_5m | SELL_REVERT_8 | 267 | 93.3% | $+2460.44 | SELL_REVERT_8 | +31.59 | $+2460.44 |
| SOL_only_15m | SELL_REVERT_8 | 71 | 80.3% | $+663.81 | SELL_REVERT_8 | +28.28 | $+663.81 |
| SOL_only_5m | SELL_REVERT_5 | 214 | 85.0% | $+2463.36 | SELL_REVERT_5 | +30.42 | $+2463.36 |
| V3_BTC_15m | HOLD | 57 | 71.9% | $+475.60 | SELL_REVERT_5 | +28.73 | $+462.60 |
| V3_BTC_5m | SELL_REVERT_5 | 191 | 70.7% | $+1573.38 | SELL_REVERT_5 | +39.76 | $+1573.38 |

## 5m vs 15m head-to-head (best policy per cell)

| Asset | 5m best | 5m PnL | 5m hit | 15m best | 15m PnL | 15m hit | Δ (5m − 15m) |
|---|---|---:|---:|---|---:|---:|---:|
| BTC_only | SELL_REVERT_5 | $+3527.93 | 89.9% | SELL_REVERT_8 | $+1023.46 | 84.6% | $+2504.47 |
| ETH_only | SELL_REVERT_8 | $+2460.44 | 93.3% | SELL_REVERT_8 | $+535.87 | 80.9% | $+1924.57 |
| SOL_only | SELL_REVERT_5 | $+2463.36 | 85.0% | SELL_REVERT_8 | $+663.81 | 80.3% | $+1799.55 |
| V3_BTC | SELL_REVERT_5 | $+1573.38 | 70.7% | HOLD | $+475.60 | 71.9% | $+1097.78 |

## Deployment matrix

| Cell | Deploy? | Rationale |
|---|---|---|
| BTC_only_15m | ✅ deploy | best=SELL_REVERT_8 → $+1023.46, Sharpe +39.44 |
| BTC_only_5m | ✅ deploy | best=SELL_REVERT_5 → $+3527.93, Sharpe +15.60 |
| ETH_only_15m | ✅ deploy | best=SELL_REVERT_8 → $+535.87, Sharpe +34.41 |
| ETH_only_5m | ✅ deploy | best=SELL_REVERT_8 → $+2460.44, Sharpe +31.59 |
| SOL_only_15m | ✅ deploy | best=SELL_REVERT_8 → $+663.81, Sharpe +28.28 |
| SOL_only_5m | ✅ deploy | best=SELL_REVERT_5 → $+2463.36, Sharpe +30.42 |
| V3_BTC_15m | 🟡 small size | best=HOLD → $+475.60, Sharpe +21.61 |
| V3_BTC_5m | ✅ deploy | best=SELL_REVERT_5 → $+1573.38, Sharpe +39.76 |