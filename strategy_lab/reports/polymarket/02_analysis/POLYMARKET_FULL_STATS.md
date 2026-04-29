# Polymarket Strategy — Full Win Rate & Performance Report

Universe: 5,742 markets across BTC/ETH/SOL (5m + 15m), Apr 22-27, 2026.

Strategy: `sig_ret5m` (sign of Binance close ratio over prior 5min) with hedge-hold exit at `rev_bp=5`. Fee 2% on winning leg payout.


## full signal × 5m × ALL assets

- **Total trades**: 4306
- **Signal hit rate (raw, before hedge)**: 2387/4306 = **55.4%** (this is the baseline directional accuracy)
- **Hedge-trigger rate**: 1151/4306 = **26.7%** (BTC reversed ≥5 bps mid-window)
- **Win rate (PnL > 0)**: 2675/4306 = **62.1%**
- **Total PnL** (per $1 stake): **$+490.82** [95% CI: $+439, $+549]
- **ROI per trade**: **+11.40%** (mean $+0.1140 / median $+0.3626)
- **Worst single trade**: $-0.7400  |  **Best**: $+0.8624
- **Std dev**: $0.4218  |  **Sharpe-like**: 0.270
- **Max drawdown** (running min): $-5.67

### Subsetted by hedge state

| Subset | n | Win% | Total PnL | Mean/trade | Median/trade |
|---|---|---|---|---|---|
| **Unhedged** (rode to resolution) | 3155 | 67.7% | $+506.54 | $+0.1606 | $+0.4606 |
| **Hedged** (synthetic close) | 1151 | 46.8% | $-15.72 | $-0.0137 | $-0.0200 |

## full signal × 15m × ALL assets

- **Total trades**: 1436
- **Signal hit rate (raw, before hedge)**: 833/1436 = **58.0%** (this is the baseline directional accuracy)
- **Hedge-trigger rate**: 681/1436 = **47.4%** (BTC reversed ≥5 bps mid-window)
- **Win rate (PnL > 0)**: 871/1436 = **60.7%**
- **Total PnL** (per $1 stake): **$+182.78** [95% CI: $+156, $+209]
- **ROI per trade**: **+12.73%** (mean $+0.1273 / median $+0.1303)
- **Worst single trade**: $-0.6300  |  **Best**: $+0.8036
- **Std dev**: $0.3544  |  **Sharpe-like**: 0.359
- **Max drawdown** (running min): $-4.70

### Subsetted by hedge state

| Subset | n | Win% | Total PnL | Mean/trade | Median/trade |
|---|---|---|---|---|---|
| **Unhedged** (rode to resolution) | 755 | 79.2% | $+209.34 | $+0.2773 | $+0.4704 |
| **Hedged** (synthetic close) | 681 | 40.1% | $-26.56 | $-0.0390 | $-0.0400 |

## q20 signal × 5m × ALL assets

- **Total trades**: 863
- **Signal hit rate (raw, before hedge)**: 494/863 = **57.2%** (this is the baseline directional accuracy)
- **Hedge-trigger rate**: 417/863 = **48.3%** (BTC reversed ≥5 bps mid-window)
- **Win rate (PnL > 0)**: 631/863 = **73.1%**
- **Total PnL** (per $1 stake): **$+174.17** [95% CI: $+155, $+193]
- **ROI per trade**: **+20.18%** (mean $+0.2018 / median $+0.3212)
- **Worst single trade**: $-0.6300  |  **Best**: $+0.6762
- **Std dev**: $0.3321  |  **Sharpe-like**: 0.608
- **Max drawdown** (running min): $-2.03

### Subsetted by hedge state

| Subset | n | Win% | Total PnL | Mean/trade | Median/trade |
|---|---|---|---|---|---|
| **Unhedged** (rode to resolution) | 446 | 81.2% | $+131.81 | $+0.2955 | $+0.4704 |
| **Hedged** (synthetic close) | 417 | 64.5% | $+42.35 | $+0.1016 | $+0.1068 |

## Headline Strategy: q20 signal × 15m × ALL assets (Sniper Mode)

- **Total trades**: 289
- **Signal hit rate (raw, before hedge)**: 183/289 = **63.3%** (this is the baseline directional accuracy)
- **Hedge-trigger rate**: 181/289 = **62.6%** (BTC reversed ≥5 bps mid-window)
- **Win rate (PnL > 0)**: 219/289 = **75.8%**
- **Total PnL** (per $1 stake): **$+58.91** [95% CI: $+50, $+67]
- **ROI per trade**: **+20.39%** (mean $+0.2039 / median $+0.2068)
- **Worst single trade**: $-0.5700  |  **Best**: $+0.5880
- **Std dev**: $0.2596  |  **Sharpe-like**: 0.785
- **Max drawdown** (running min): $-0.58

### Subsetted by hedge state

| Subset | n | Win% | Total PnL | Mean/trade | Median/trade |
|---|---|---|---|---|---|
| **Unhedged** (rode to resolution) | 108 | 92.6% | $+43.91 | $+0.4066 | $+0.4704 |
| **Hedged** (synthetic close) | 181 | 65.7% | $+15.00 | $+0.0829 | $+0.0812 |


## Per-Asset Breakdown

Using `q20` signal at 15m (sniper mode), `rev_bp=5`, hedge-hold.

| Asset | n | Hit% | Total PnL | 95% CI | Mean/trade | ROI/bet | Worst | Sharpe |
|---|---|---|---|---|---|---|---|---|
| BTC | 95 | 77.9% | $+21.13 | [$+16, $+26] | $+0.2225 | +22.25% | $-0.490 | 0.831 |
| ETH | 97 | 76.3% | $+20.57 | [$+16, $+25] | $+0.2120 | +21.20% | $-0.550 | 0.853 |
| SOL | 97 | 73.2% | $+17.21 | [$+12, $+22] | $+0.1775 | +17.75% | $-0.570 | 0.675 |
| ALL | 289 | 75.8% | $+58.91 | [$+50, $+67] | $+0.2039 | +20.39% | $-0.570 | 0.785 |

## Scaled PnL projections (assumes performance holds)

Per-trade ROI from the headline sniper cell × N trades × stake size:

| Stake size | Trades / day | Expected $/day | Trades / month | Expected $/month |
|---|---|---|---|---|
| $1 | 58 | $+11.78 | 1734 | $+353.48 |
| $5 | 58 | $+58.91 | 1734 | $+1767.40 |
| $10 | 58 | $+117.83 | 1734 | $+3534.80 |
| $25 | 58 | $+294.57 | 1734 | $+8837.01 |
| $100 | 58 | $+1178.27 | 1734 | $+35348.04 |

*These are gross projections from in-sample backtest. Subtract gas (~$0.001/trade) and any slippage haircut (estimate -10% on per-trade ROI for live execution friction).*
