# V3 Backtest — FULL 12.5d Window (2026_05_04)

**Sample:** 7790 usable markets (04-22 → 05-04). Reuses validation gates from `phase7_validation_v3.py`.

Note: returns computed from **HL perp klines** (Binance collector dead since 04-29 due to geoblock). HL perp ≈ Binance spot for 5m/15m/1h horizons (sub-bps basis difference).

## V3_BASELINE (uniform 0.02 spread, MH on V3 base)

spread: {'BTC': 0.02, 'ETH': 0.02, 'SOL': 0.02}, MH: True

| Asset | n_holdout | fired | fire% | hit% | pnl$ | MaxDD$ | IC p |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 536 | 45 | 8.4% | 44.4% | -5.33 | -7.73 | 0.2900 |
| ETH | 534 | 22 | 4.1% | 40.9% | -5.79 | -6.73 | 0.0140 |
| SOL | 489 | 20 | 4.1% | 45.0% | -3.29 | -4.80 | 0.2800 |

### Stop-loss sim (holdout)

**BTC**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -5.33 | -12.01 | -7.73 | 41 | 44.4% |
| stop_50pct | +7.67 | +22.85 | -2.00 | 8 | 44.4% |
| stop_70pct | +2.67 | +7.09 | -3.37 | 21 | 44.4% |
| stop_90pct | -2.33 | -5.56 | -5.77 | 21 | 44.4% |

**ETH**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -5.79 | -27.61 | -6.73 | 21 | 40.9% |
| stop_50pct | +0.97 | +6.34 | -1.97 | 10 | 40.9% |
| stop_70pct | -1.63 | -9.34 | -3.37 | 14 | 40.9% |
| stop_90pct | -4.23 | -21.53 | -5.17 | 21 | 40.9% |

**SOL**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -3.29 | -15.16 | -4.80 | 18 | 45.0% |
| stop_50pct | +2.43 | +15.03 | -2.00 | 5 | 45.0% |
| stop_70pct | +0.23 | +1.26 | -2.80 | 8 | 45.0% |
| stop_90pct | -1.97 | -9.65 | -3.77 | 9 | 45.0% |

### Bootstrap 95% CI (holdout)

| Asset | PnL CI | Hit rate CI |
|---|---|---|
| BTC | [-18.26, +8.34] | [31.1%, 60.0%] |
| ETH | [-13.81, +2.94] | [22.7%, 63.6%] |
| SOL | [-11.33, +5.39] | [25.0%, 65.0%] |

### Tail risk (worst 5%)

| Asset | n_worst | sum$ | %_total | hours | dirs |
|---|---:|---:|---:|---|---|
| BTC | 2/45 | -2.04 | +38.3% | 11,20 | Up=1/Down=1 |
| ETH | 1/22 | -1.02 | +17.6% | 20 | Up=0/Down=1 |
| SOL | 1/20 | -1.02 | +31.0% | 21 | Up=0/Down=1 |

## V3_SOL_FIX (BTC/ETH=0.02, SOL=0.025, MH on)

spread: {'BTC': 0.02, 'ETH': 0.02, 'SOL': 0.025}, MH: True

| Asset | n_holdout | fired | fire% | hit% | pnl$ | MaxDD$ | IC p |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 536 | 45 | 8.4% | 44.4% | -5.33 | -7.73 | 0.2910 |
| ETH | 534 | 22 | 4.1% | 40.9% | -5.79 | -6.73 | 0.0200 |
| SOL | 489 | 22 | 4.5% | 40.9% | -5.33 | -6.84 | 0.2780 |

### Stop-loss sim (holdout)

**BTC**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -5.33 | -12.01 | -7.73 | 41 | 44.4% |
| stop_50pct | +7.67 | +22.85 | -2.00 | 8 | 44.4% |
| stop_70pct | +2.67 | +7.09 | -3.37 | 21 | 44.4% |
| stop_90pct | -2.33 | -5.56 | -5.77 | 21 | 44.4% |

**ETH**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -5.79 | -27.61 | -6.73 | 21 | 40.9% |
| stop_50pct | +0.97 | +6.34 | -1.97 | 10 | 40.9% |
| stop_70pct | -1.63 | -9.34 | -3.37 | 14 | 40.9% |
| stop_90pct | -4.23 | -21.53 | -5.17 | 21 | 40.9% |

**SOL**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -5.33 | -23.75 | -6.84 | 20 | 40.9% |
| stop_50pct | +1.43 | +8.57 | -2.50 | 5 | 40.9% |
| stop_70pct | -1.17 | -6.20 | -3.77 | 11 | 40.9% |
| stop_90pct | -3.77 | -17.86 | -5.57 | 11 | 40.9% |

### Bootstrap 95% CI (holdout)

| Asset | PnL CI | Hit rate CI |
|---|---|---|
| BTC | [-18.32, +9.06] | [31.1%, 60.0%] |
| ETH | [-13.47, +2.98] | [22.7%, 63.6%] |
| SOL | [-13.88, +3.89] | [22.7%, 63.6%] |

### Tail risk (worst 5%)

| Asset | n_worst | sum$ | %_total | hours | dirs |
|---|---:|---:|---:|---|---|
| BTC | 2/45 | -2.04 | +38.3% | 11,20 | Up=1/Down=1 |
| ETH | 1/22 | -1.02 | +17.6% | 20 | Up=0/Down=1 |
| SOL | 1/22 | -1.02 | +19.1% | 21 | Up=0/Down=1 |

## V3_SOL_FIX_NO_MH (sanity: drop MH for SOL)

spread: {'BTC': 0.02, 'ETH': 0.02, 'SOL': 0.025}, MH: False

| Asset | n_holdout | fired | fire% | hit% | pnl$ | MaxDD$ | IC p |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 536 | 45 | 8.4% | 44.4% | -5.33 | -7.73 | 0.3120 |
| ETH | 534 | 22 | 4.1% | 40.9% | -5.79 | -6.73 | 0.0230 |
| SOL | 489 | 31 | 6.3% | 41.9% | -6.99 | -10.30 | 0.2840 |

### Stop-loss sim (holdout)

**BTC**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -5.33 | -12.01 | -7.73 | 41 | 44.4% |
| stop_50pct | +7.67 | +22.85 | -2.00 | 8 | 44.4% |
| stop_70pct | +2.67 | +7.09 | -3.37 | 21 | 44.4% |
| stop_90pct | -2.33 | -5.56 | -5.77 | 21 | 44.4% |

**ETH**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -5.79 | -27.61 | -6.73 | 21 | 40.9% |
| stop_50pct | +0.97 | +6.34 | -1.97 | 10 | 40.9% |
| stop_70pct | -1.63 | -9.34 | -3.37 | 14 | 40.9% |
| stop_90pct | -4.23 | -21.53 | -5.17 | 21 | 40.9% |

**SOL**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | -6.99 | -26.18 | -10.30 | 19 | 41.9% |
| stop_50pct | +2.37 | +11.97 | -4.50 | 10 | 41.9% |
| stop_70pct | -1.23 | -5.49 | -6.30 | 10 | 41.9% |
| stop_90pct | -4.83 | -19.25 | -8.62 | 19 | 41.9% |

### Bootstrap 95% CI (holdout)

| Asset | PnL CI | Hit rate CI |
|---|---|---|
| BTC | [-18.22, +8.16] | [31.1%, 57.8%] |
| ETH | [-13.85, +2.56] | [22.7%, 59.1%] |
| SOL | [-17.64, +3.89] | [25.8%, 58.1%] |

### Tail risk (worst 5%)

| Asset | n_worst | sum$ | %_total | hours | dirs |
|---|---:|---:|---:|---|---|
| BTC | 2/45 | -2.04 | +38.3% | 11,20 | Up=1/Down=1 |
| ETH | 1/22 | -1.02 | +17.6% | 20 | Up=0/Down=1 |
| SOL | 1/31 | -1.02 | +14.6% | 21 | Up=0/Down=1 |
