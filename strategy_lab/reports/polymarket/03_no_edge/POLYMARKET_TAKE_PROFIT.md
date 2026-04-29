# Take-Profit Strategy Test

q10 universe (n=579), hedge-hold rev_bp=5 as baseline.
TP targets tested: [5, 10, 15, 20, 25, 40, 60, 80, 100, 150]%. 
TP execution: sell held side at `entry * (1 + T)` when held_bid_max reaches the target in any bucket.

## Variant grid

| Variant | n | Hit% | ROI | vs baseline | TP fire | revbp fire | natural | mean cost |
|---|---|---|---|---|---|---|---|---|
| baseline_revbp (baseline) | 579 | 81.5% | +24.58% | +0.00pp | 0.0% | 55.6% | 44.4% | $0.6907 |
| tp_5pct_only | 579 | 94.5% | -0.68% | -25.25pp | 94.0% | 0.0% | 6.0% | $0.5076 |
| tp_5pct_plus_revbp | 579 | 92.1% | +0.61% | -23.97pp | 91.4% | 6.6% | 2.1% | $0.5454 |
| tp_10pct_only | 579 | 93.6% | +1.17% | -23.41pp | 92.9% | 0.0% | 7.1% | $0.5076 |
| tp_10pct_plus_revbp | 579 | 91.5% | +2.77% | -21.81pp | 90.2% | 7.6% | 2.2% | $0.5502 |
| tp_15pct_only | 579 | 92.1% | +2.57% | -22.01pp | 91.2% | 0.0% | 8.8% | $0.5076 |
| tp_15pct_plus_revbp | 579 | 90.2% | +4.56% | -20.01pp | 87.6% | 9.8% | 2.6% | $0.5604 |
| tp_20pct_only | 579 | 90.7% | +3.95% | -20.62pp | 89.8% | 0.0% | 10.2% | $0.5076 |
| tp_20pct_plus_revbp | 579 | 89.3% | +6.35% | -18.23pp | 86.2% | 10.9% | 2.9% | $0.5665 |
| tp_25pct_only | 579 | 89.8% | +5.68% | -18.89pp | 88.8% | 0.0% | 11.2% | $0.5076 |
| tp_25pct_plus_revbp | 579 | 88.4% | +8.25% | -16.33pp | 84.3% | 12.6% | 3.1% | $0.5749 |
| tp_40pct_only | 579 | 84.5% | +8.44% | -16.14pp | 82.7% | 0.0% | 17.3% | $0.5076 |
| tp_40pct_plus_revbp | 579 | 85.7% | +12.78% | -11.80pp | 74.8% | 21.1% | 4.1% | $0.6116 |
| tp_60pct_only | 579 | 77.0% | +10.55% | -14.03pp | 72.5% | 0.0% | 27.5% | $0.5076 |
| tp_60pct_plus_revbp | 579 | 84.1% | +17.76% | -6.81pp | 60.4% | 33.2% | 6.4% | $0.6471 |
| tp_80pct_only | 579 | 69.9% | +11.03% | -13.54pp | 57.0% | 0.0% | 43.0% | $0.5076 |
| tp_80pct_plus_revbp | 579 | 82.9% | +21.34% | -3.24pp | 43.5% | 45.1% | 11.4% | $0.6768 |
| tp_100pct_only | 579 | 66.8% | +12.66% | -11.92pp | 35.6% | 0.0% | 64.4% | $0.5076 |
| tp_100pct_plus_revbp | 579 | 82.4% | +23.82% | -0.76pp | 26.4% | 50.3% | 23.3% | $0.6857 |
| tp_150pct_only | 579 | 62.7% | +11.17% | -13.41pp | 9.7% | 0.0% | 90.3% | $0.5076 |
| tp_150pct_plus_revbp ★ | 579 | 81.5% | +24.45% | -0.13pp | 7.6% | 55.6% | 36.8% | $0.6907 |

## Cross-asset × timeframe — best variant `tp_150pct_plus_revbp` vs baseline

| Asset | TF | n | Hit% | best ROI | baseline ROI | Δ |
|---|---|---|---|---|---|---|
| ALL | ALL | 579 | 81.5% | +24.45% | +24.58% | -0.13pp |
| ALL | 5m | 433 | 81.3% | +25.31% | +25.43% | -0.12pp |
| ALL | 15m | 146 | 82.2% | +21.90% | +22.03% | -0.13pp |
| btc | ALL | 191 | 84.8% | +27.67% | +27.90% | -0.23pp |
| btc | 5m | 143 | 85.3% | +29.34% | +29.61% | -0.27pp |
| btc | 15m | 48 | 83.3% | +22.73% | +22.83% | -0.10pp |
| eth | ALL | 194 | 80.4% | +24.80% | +24.89% | -0.09pp |
| eth | 5m | 145 | 79.3% | +25.01% | +25.07% | -0.06pp |
| eth | 15m | 49 | 83.7% | +24.16% | +24.34% | -0.18pp |
| sol | ALL | 194 | 79.4% | +20.92% | +20.98% | -0.06pp |
| sol | 5m | 145 | 79.3% | +21.64% | +21.68% | -0.04pp |
| sol | 15m | 49 | 79.6% | +18.82% | +18.94% | -0.12pp |

## Day-by-day — best variant `tp_150pct_plus_revbp` vs baseline

| Date | n | best ROI | baseline ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 75 | +21.36% | +21.37% | -0.01pp |
| 2026-04-23 | 240 | +22.75% | +22.90% | -0.15pp |
| 2026-04-24 | 148 | +26.44% | +26.60% | -0.17pp |
| 2026-04-25 | 17 | +30.80% | +31.15% | -0.35pp |
| 2026-04-26 | 99 | +26.85% | +26.91% | -0.07pp |

## PnL distribution — best variant `tp_150pct_plus_revbp`

Compares pnl distribution between best and baseline. Tail behavior matters.

| Stat | best | baseline |
|---|---|---|
| n | 579 | 579 |
| mean PnL | +0.2445 | +0.2458 |
| median PnL | +0.3318 | +0.3318 |
| stdev | 0.2806 | 0.2818 |
| min PnL | -0.6300 | -0.6300 |
| max PnL | +0.5880 | +0.6762 |
| % winning trades | 81.5% | 81.5% |
| Sharpe (mean/std) | 0.871 | 0.872 |

## Verdict

**Criteria:**
  1. Best variant ROI > baseline: ❌ (-0.13pp)
  2. Cross-asset agreement (≥2/3): ❌ (0/3)
  3. Day-by-day stability (≥4/5): ❌ (0/5)
  4. Sharpe improved: ❌ (0.871 vs 0.872)

**Score: 0/4**

❌ **No clear edge.** TP at this target doesn't beat the rev_bp baseline.