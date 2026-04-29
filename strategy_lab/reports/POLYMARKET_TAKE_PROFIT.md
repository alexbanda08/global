# Take-Profit Strategy Test

q10 universe (n=823), hedge-hold rev_bp=5 as baseline.
TP targets tested: [5, 10, 15, 20, 25, 40, 60, 80, 100, 150]%. 
TP execution: sell held side at `entry * (1 + T)` when held_bid_max reaches the target in any bucket.

## Variant grid

| Variant | n | Hit% | ROI | vs baseline | TP fire | revbp fire | natural | mean cost |
|---|---|---|---|---|---|---|---|---|
| baseline_revbp (baseline) | 823 | 81.2% | +25.26% | +0.00pp | 0.0% | 57.4% | 42.6% | $0.6960 |
| tp_5pct_only | 823 | 95.5% | -0.14% | -25.40pp | 95.1% | 0.0% | 4.9% | $0.4986 |
| tp_5pct_plus_revbp | 823 | 93.3% | +1.11% | -24.15pp | 92.8% | 6.2% | 1.0% | $0.5344 |
| tp_10pct_only | 823 | 94.3% | +1.62% | -23.64pp | 93.7% | 0.0% | 6.3% | $0.4986 |
| tp_10pct_plus_revbp | 823 | 92.6% | +3.21% | -22.05pp | 91.4% | 7.3% | 1.3% | $0.5405 |
| tp_15pct_only | 823 | 92.8% | +3.18% | -22.08pp | 92.0% | 0.0% | 8.0% | $0.4986 |
| tp_15pct_plus_revbp | 823 | 91.3% | +5.10% | -20.16pp | 89.4% | 9.0% | 1.6% | $0.5494 |
| tp_20pct_only | 823 | 91.1% | +4.41% | -20.85pp | 90.3% | 0.0% | 9.7% | $0.4986 |
| tp_20pct_plus_revbp | 823 | 89.8% | +6.80% | -18.46pp | 87.4% | 10.7% | 1.9% | $0.5591 |
| tp_25pct_only | 823 | 89.7% | +5.78% | -19.48pp | 88.5% | 0.0% | 11.5% | $0.4986 |
| tp_25pct_plus_revbp | 823 | 88.6% | +8.53% | -16.73pp | 85.2% | 12.6% | 2.2% | $0.5695 |
| tp_40pct_only | 823 | 83.6% | +8.17% | -17.09pp | 81.4% | 0.0% | 18.6% | $0.4986 |
| tp_40pct_plus_revbp | 823 | 84.7% | +12.64% | -12.62pp | 74.6% | 22.0% | 3.4% | $0.6117 |
| tp_60pct_only | 823 | 76.3% | +10.37% | -14.89pp | 71.6% | 0.0% | 28.4% | $0.4986 |
| tp_60pct_plus_revbp | 823 | 83.1% | +17.80% | -7.46pp | 60.9% | 33.8% | 5.3% | $0.6511 |
| tp_80pct_only | 823 | 69.7% | +11.30% | -13.96pp | 57.2% | 0.0% | 42.8% | $0.4986 |
| tp_80pct_plus_revbp | 823 | 82.1% | +21.51% | -3.75pp | 44.6% | 44.8% | 10.6% | $0.6785 |
| tp_100pct_only | 823 | 65.9% | +12.32% | -12.94pp | 36.2% | 0.0% | 63.8% | $0.4986 |
| tp_100pct_plus_revbp | 823 | 81.8% | +24.12% | -1.14pp | 27.1% | 51.9% | 21.0% | $0.6902 |
| tp_150pct_only | 823 | 62.7% | +12.06% | -13.21pp | 11.1% | 0.0% | 88.9% | $0.4986 |
| tp_150pct_plus_revbp ★ | 823 | 81.2% | +25.14% | -0.12pp | 7.8% | 57.4% | 34.9% | $0.6960 |

## Cross-asset × timeframe — best variant `tp_150pct_plus_revbp` vs baseline

| Asset | TF | n | Hit% | best ROI | baseline ROI | Δ |
|---|---|---|---|---|---|---|
| ALL | ALL | 823 | 81.2% | +25.14% | +25.26% | -0.12pp |
| ALL | 5m | 616 | 81.2% | +26.76% | +26.89% | -0.13pp |
| ALL | 15m | 207 | 81.2% | +20.33% | +20.43% | -0.10pp |
| btc | ALL | 275 | 84.0% | +27.32% | +27.52% | -0.20pp |
| btc | 5m | 206 | 84.0% | +28.78% | +29.01% | -0.24pp |
| btc | 15m | 69 | 84.1% | +22.96% | +23.08% | -0.11pp |
| eth | ALL | 274 | 79.9% | +25.43% | +25.52% | -0.09pp |
| eth | 5m | 205 | 79.5% | +27.26% | +27.34% | -0.08pp |
| eth | 15m | 69 | 81.2% | +20.01% | +20.11% | -0.10pp |
| sol | ALL | 274 | 79.6% | +22.66% | +22.73% | -0.07pp |
| sol | 5m | 205 | 80.0% | +24.23% | +24.29% | -0.06pp |
| sol | 15m | 69 | 78.3% | +18.00% | +18.10% | -0.10pp |

## Day-by-day — best variant `tp_150pct_plus_revbp` vs baseline

| Date | n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 63 | +21.83% | +21.83% | +0.00pp |
| 2026-04-23 | 194 | +23.24% | +23.41% | -0.17pp |
| 2026-04-24 | 122 | +26.15% | +26.33% | -0.18pp |
| 2026-04-25 | 13 | +37.80% | +38.18% | -0.38pp |
| 2026-04-26 | 81 | +27.87% | +27.94% | -0.07pp |
| 2026-04-27 | 147 | +27.12% | +27.31% | -0.19pp |
| 2026-04-28 | 91 | +21.66% | +21.72% | -0.05pp |
| 2026-04-29 | 112 | +26.00% | +26.00% | -0.01pp |

## PnL distribution — best variant `tp_150pct_plus_revbp`

Compares pnl distribution between best and baseline. Tail behavior matters.

| Stat | best | baseline |
|---|---|---|
| n | 823 | 823 |
| mean PnL | +0.2514 | +0.2526 |
| median PnL | +0.3396 | +0.3406 |
| stdev | 0.2749 | 0.2760 |
| min PnL | -0.5900 | -0.5900 |
| max PnL | +0.5978 | +0.6762 |
| % winning trades | 81.2% | 81.2% |
| Sharpe (mean/std) | 0.915 | 0.915 |

## Verdict

**Criteria:**
  1. Best variant ROI > baseline: ❌ (-0.12pp)
  2. Cross-asset agreement (≥2/3): ❌ (0/3)
  3. Day-by-day stability (≥4/5): ❌ (0/8)
  4. Sharpe improved: ❌ (0.915 vs 0.915)

**Score: 0/4**

❌ **No clear edge.** TP at this target doesn't beat the rev_bp baseline.