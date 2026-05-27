# RF vs Ribbon Overlap Analysis — 2026-05-25

Joins `s15_joined_all.parquet` (S1.5 5m fires) + computes Jaccard / Pearson / conditional
probabilities between **rf_dir-agrees-with-bet** and **ribbon_color-agrees-with-bet**, then WR on disagreement subsets.

**Universe**: 28-day window 2026-05-01 → 2026-05-21, chainlink-resolved fires only, legacy 2%-on-profit fee model.

## S1.5 5m

- **n total**: 33,323
- **rf agrees with bet**: 26,379 (79.2%)
- **ribbon agrees with bet**: 24,335 (73.0%)
- **both agree**: 22,086
- **either agree**: 28,628
- **Jaccard**: **0.771**
- **Pearson (rf_dir × sign(ribbon_slope))**: 0.607
- **P(ribbon|rf)**: 0.837
- **P(rf|ribbon)**: 0.908

Disagreement / agreement subsets:

| Subset | n | WR | sum_pnl_usd | $/tr |
|---|---:|---:|---:|---:|
| BOTH agree | 22,086 | 0.812 | +14869.17 | +0.6732 |
| RF only | 4,293 | 0.801 | -3794.35 | -0.8838 |
| Ribbon only | 2,249 | 0.823 | -1141.10 | -0.5074 |
| NEITHER | 4,695 | 0.814 | -4717.76 | -1.0048 |

## S6 5m spike

- **n total**: 18,766
- **rf agrees with bet**: 17,449 (93.0%)
- **ribbon agrees with bet**: 18,387 (98.0%)
- **both agree**: 17,254
- **either agree**: 18,582
- **Jaccard**: **0.929**
- **Pearson (rf_dir × sign(ribbon_slope))**: 0.858
- **P(ribbon|rf)**: 0.989
- **P(rf|ribbon)**: 0.938

Disagreement / agreement subsets:

| Subset | n | WR | sum_pnl_usd | $/tr |
|---|---:|---:|---:|---:|
| BOTH agree | 17,254 | 0.718 | +17501.33 | +1.0143 |
| RF only | 195 | 0.667 | -332.31 | -1.7042 |
| Ribbon only | 1,133 | 0.724 | +1419.81 | +1.2531 |
| NEITHER | 184 | 0.609 | -496.73 | -2.6996 |

## v15m S7 15m

- **n total**: 12,492
- **rf agrees with bet**: 7,232 (57.9%)
- **ribbon agrees with bet**: 6,959 (55.7%)
- **both agree**: 5,819
- **either agree**: 8,372
- **Jaccard**: **0.695**
- **Pearson (rf_dir × sign(ribbon_slope))**: 0.529
- **P(ribbon|rf)**: 0.805
- **P(rf|ribbon)**: 0.836

Disagreement / agreement subsets:

| Subset | n | WR | sum_pnl_usd | $/tr |
|---|---:|---:|---:|---:|
| BOTH agree | 5,819 | 0.798 | +811.32 | +0.1394 |
| RF only | 1,413 | 0.805 | -1109.25 | -0.7850 |
| Ribbon only | 1,140 | 0.800 | -1147.12 | -1.0062 |
| NEITHER | 4,120 | 0.651 | -12101.33 | -2.9372 |

## Per-asset (S1.5 5m only)

| Asset | n | RF agrees | Ribbon agrees | Jaccard | Pearson | P(rib|rf) | P(rf|rib) |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 9,621 | 7,695 | 7,211 | 0.822 | +0.696 | 0.874 | 0.932 |
| ETH | 12,536 | 9,940 | 9,197 | 0.786 | +0.633 | 0.847 | 0.916 |
| SOL | 11,166 | 8,744 | 7,927 | 0.714 | +0.500 | 0.794 | 0.876 |

## Verdict

- **RF and ribbon are SUBSTANTIALLY overlapping** (Jaccard 0.65-0.85). Stacking both
  provides modest filter tightening but mostly trims the same fires. Look for cases
  where RF-only or ribbon-only have higher WR — that's the marginal signal.

If `RF only` WR > `Ribbon only` WR, RF has signal ribbon misses (and vice versa).
If `BOTH` WR > marginal subsets, the AND-conjunction is genuinely tightening.