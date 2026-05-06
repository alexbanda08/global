# V3 Baseline Backtest — Validation (2026_05_04)

**Reuses** `polymarket_stats.equity_curve_stats` + chronological-split + bootstrap-CI gates from `phase7_validation.py`.

**3 variants tested:**
1. `V3_BASELINE` — current production (uniform 0.02 spread filter, multi-horizon for SOL)
2. `V3_SOL_FIX` — proposed fix (per-asset spread: BTC/ETH=0.02, SOL=0.025; multi-horizon for SOL)
3. `V3_SOL_FIX_NO_MH` — sanity (drops SOL multi-horizon constraint to isolate spread filter effect)

Each variant: chronological 80/20 split, Q (per direction) fit on TRAIN, all 3 assets evaluated. Holdout = last 20% chronologically. PnL math: $1 stake, 2% taker fee, entry at `entry_yes_ask` / `entry_no_ask` from `features_v3.csv`.

## V3_BASELINE (uniform 0.02 spread)

spread_filter: {'BTC': 0.02, 'ETH': 0.02, 'SOL': 0.02}, require_mh: True

### Headline holdout stats

| Asset | n_holdout_rows | fired | fire% | hit% | pnl$ | Sharpe | MaxDD$ | IC p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 545 | 28 | 5.1% | 64.3% | +8.29 | +25.25 | -2.08 | 0.0000 |
| ETH | 543 | 10 | 1.8% | 60.0% | +2.09 | +11.43 | -3.06 | 0.0000 |
| SOL | 514 | 20 | 3.9% | 55.0% | +1.81 | +6.45 | -5.14 | 0.0000 |

### Stop-loss sim (holdout)

**BTC**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +8.29 | +25.25 | -2.08 | 7 | 64.3% |
| stop_50pct | +13.49 | +54.47 | -1.00 | 3 | 64.3% |
| stop_70pct | +11.49 | +41.25 | -1.40 | 5 | 64.3% |
| stop_90pct | +9.49 | +30.65 | -1.80 | 5 | 64.3% |

**ETH**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +2.09 | +11.43 | -3.06 | 5 | 60.0% |
| stop_50pct | +4.17 | +30.34 | -1.50 | 4 | 60.0% |
| stop_70pct | +3.37 | +21.76 | -2.10 | 4 | 60.0% |
| stop_90pct | +2.57 | +14.91 | -2.70 | 5 | 60.0% |

**SOL**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +1.81 | +6.45 | -5.14 | 14 | 55.0% |
| stop_50pct | +6.49 | +30.50 | -2.50 | 7 | 55.0% |
| stop_70pct | +4.69 | +19.63 | -3.50 | 9 | 55.0% |
| stop_90pct | +2.89 | +10.90 | -4.50 | 12 | 55.0% |

### Bootstrap 95% CI (holdout)

| Asset | PnL CI | Hit rate CI |
|---|---|---|
| BTC | [-1.67, +18.35] | [46.4%, 82.1%] |
| ETH | [-4.03, +8.24] | [30.0%, 90.0%] |
| SOL | [-7.32, +10.75] | [35.0%, 75.0%] |

### Tail risk (worst 5%)

| Asset | n_worst | sum$ | %_total | hours | dirs |
|---|---:|---:|---:|---|---|
| BTC | 1/28 | -1.02 | -12.3% | 8 | Up=1/Down=0 |
| ETH | 1/10 | -1.02 | -48.8% | 13 | Up=0/Down=1 |
| SOL | 1/20 | -1.02 | -56.3% | 8 | Up=1/Down=0 |

## V3_SOL_FIX (BTC/ETH=0.02, SOL=0.025)

spread_filter: {'BTC': 0.02, 'ETH': 0.02, 'SOL': 0.025}, require_mh: True

### Headline holdout stats

| Asset | n_holdout_rows | fired | fire% | hit% | pnl$ | Sharpe | MaxDD$ | IC p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 545 | 28 | 5.1% | 64.3% | +8.29 | +25.25 | -2.08 | 0.0000 |
| ETH | 543 | 10 | 1.8% | 60.0% | +2.09 | +11.43 | -3.06 | 0.0000 |
| SOL | 514 | 23 | 4.5% | 60.9% | +4.79 | +15.89 | -5.14 | 0.0000 |

### Stop-loss sim (holdout)

**BTC**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +8.29 | +25.25 | -2.08 | 7 | 64.3% |
| stop_50pct | +13.49 | +54.47 | -1.00 | 3 | 64.3% |
| stop_70pct | +11.49 | +41.25 | -1.40 | 5 | 64.3% |
| stop_90pct | +9.49 | +30.65 | -1.80 | 5 | 64.3% |

**ETH**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +2.09 | +11.43 | -3.06 | 5 | 60.0% |
| stop_50pct | +4.17 | +30.34 | -1.50 | 4 | 60.0% |
| stop_70pct | +3.37 | +21.76 | -2.10 | 4 | 60.0% |
| stop_90pct | +2.57 | +14.91 | -2.70 | 5 | 60.0% |

**SOL**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +4.79 | +15.89 | -5.14 | 16 | 60.9% |
| stop_50pct | +9.47 | +41.56 | -2.50 | 7 | 60.9% |
| stop_70pct | +7.67 | +29.96 | -3.50 | 9 | 60.9% |
| stop_90pct | +5.87 | +20.64 | -4.50 | 13 | 60.9% |

### Bootstrap 95% CI (holdout)

| Asset | PnL CI | Hit rate CI |
|---|---|---|
| BTC | [-2.12, +18.89] | [46.4%, 82.1%] |
| ETH | [-4.22, +8.15] | [30.0%, 90.0%] |
| SOL | [-4.56, +13.83] | [39.1%, 78.3%] |

### Tail risk (worst 5%)

| Asset | n_worst | sum$ | %_total | hours | dirs |
|---|---:|---:|---:|---|---|
| BTC | 1/28 | -1.02 | -12.3% | 8 | Up=1/Down=0 |
| ETH | 1/10 | -1.02 | -48.8% | 13 | Up=0/Down=1 |
| SOL | 1/23 | -1.02 | -21.3% | 8 | Up=1/Down=0 |

## V3_SOL_FIX_NO_MH (sanity check, no SOL multi-horizon)

spread_filter: {'BTC': 0.02, 'ETH': 0.02, 'SOL': 0.025}, require_mh: False

### Headline holdout stats

| Asset | n_holdout_rows | fired | fire% | hit% | pnl$ | Sharpe | MaxDD$ | IC p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 545 | 28 | 5.1% | 64.3% | +8.29 | +25.25 | -2.08 | 0.0000 |
| ETH | 543 | 10 | 1.8% | 60.0% | +2.09 | +11.43 | -3.06 | 0.0000 |
| SOL | 514 | 34 | 6.6% | 61.8% | +7.27 | +20.15 | -5.14 | 0.0000 |

### Stop-loss sim (holdout)

**BTC**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +8.29 | +25.25 | -2.08 | 7 | 64.3% |
| stop_50pct | +13.49 | +54.47 | -1.00 | 3 | 64.3% |
| stop_70pct | +11.49 | +41.25 | -1.40 | 5 | 64.3% |
| stop_90pct | +9.49 | +30.65 | -1.80 | 5 | 64.3% |

**ETH**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +2.09 | +11.43 | -3.06 | 5 | 60.0% |
| stop_50pct | +4.17 | +30.34 | -1.50 | 4 | 60.0% |
| stop_70pct | +3.37 | +21.76 | -2.10 | 4 | 60.0% |
| stop_90pct | +2.57 | +14.91 | -2.70 | 5 | 60.0% |

**SOL**

| Variant | pnl$ | Sharpe | MaxDD$ | LongestDD | win% |
|---|---:|---:|---:|---:|---:|
| no_stop | +7.27 | +20.15 | -5.14 | 24 | 61.8% |
| stop_50pct | +14.03 | +51.85 | -2.50 | 8 | 61.8% |
| stop_70pct | +11.43 | +37.45 | -3.50 | 11 | 61.8% |
| stop_90pct | +8.83 | +25.97 | -4.50 | 21 | 61.8% |

### Bootstrap 95% CI (holdout)

| Asset | PnL CI | Hit rate CI |
|---|---|---|
| BTC | [-2.37, +18.23] | [46.4%, 82.1%] |
| ETH | [-4.11, +8.13] | [30.0%, 90.0%] |
| SOL | [-3.55, +18.45] | [47.1%, 79.4%] |

### Tail risk (worst 5%)

| Asset | n_worst | sum$ | %_total | hours | dirs |
|---|---:|---:|---:|---|---|
| BTC | 1/28 | -1.02 | -12.3% | 8 | Up=1/Down=0 |
| ETH | 1/10 | -1.02 | -48.8% | 13 | Up=0/Down=1 |
| SOL | 1/34 | -1.02 | -14.0% | 8 | Up=1/Down=0 |

---

**Interpretation:**

Compare V3_BASELINE vs V3_SOL_FIX. The fix is worth shipping if:
- SOL fire rate increases meaningfully (0 → 5+/day in absolute terms)
- SOL holdout PnL stays non-negative
- BTC/ETH not adversely affected (spread filter unchanged for them)

Compare V3_SOL_FIX vs V3_SOL_FIX_NO_MH to validate Concern A (V3.2 multi-horizon parity)
— if the no-MH variant is significantly worse, multi-horizon is correctly a quality filter.