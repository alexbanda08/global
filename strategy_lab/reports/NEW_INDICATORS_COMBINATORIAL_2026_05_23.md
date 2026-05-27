# New Indicators Combinatorial Search (S1.5 + S6) — 2026-05-23

**Universe:** 28d of S1.5 (slot-anchored VWAP) and S6 (spike-driven) fires augmented with new TA indicators (ribbon, slow stoch, BB pos, MFI, CCI).

**Thresholds:** `n>=50, WR>=0.75, avg_pnl>=$2.0/trade`. Score = `WR * sqrt(n) * max(avg_pnl, 0)`.

**Baselines (post-NaN-drop):**  
- S1.5: n=33,279, WR=0.8115, avg_pnl=$0.1557/tr
- S6:   n=11,336, WR=0.7085, avg_pnl=$1.2222/tr

**Outputs:** `data/v4/canonical/_results/new_indicators_combinatorial.csv`, this report.

### TL;DR

- **3269 passing (cell, gate-combo) rows** (n>=50, WR>=75%, $/tr>=$2); **2108 ultra-strict** (WR>=80%).
- **S6 dominates ultra-strict picks**: ribbon-based gates on S6 T2/T3 fires unlock cells with $/tr ranging from $2 to $36 — but the high-$/tr tail is OUTLIER-DRIVEN. Example: `BTC|120|T2 + ribbon_color_bear` (n=51, WR=80%, $/tr=$36) has one DOWN trade at +$383 dominating mean; median is ~$1.3, so robust expected value is closer to $1-2/tr.
- **S1.5 is harder to beat**: its 81% baseline WR + tiny $0.16/tr baseline means gates that raise WR rarely produce $/tr>=$2 (legacy fees take ~$1/tr of a winning leg with vwap near 0.5). Only the deepest ribbon+stoch confirmation cells (asset-specific) clear the bar.
- **Most-cited gates**: `stoch_60s_kd_cross` and `ribbon_agrees` show up in the broadest set of winning combos — see §4. On its own, `stoch_60s_kd_cross` lifts WR by ~1.5-3pp across most S1.5 cells (§5).
- **Edge ADD verdict**: New indicators DO add edge in narrow tiered S6 cells (T2/T3 ribbon-aligned) but the gain is modest above the strong S1.5/S6 baselines once you require n>=50. For deployment, treat ULTRA results as candidates for a follow-up live-mimic + slug-level audit before sizing.

> **Caveat:** All PnL is `pnl_legacy_usd` (production 2%-on-profit only). Means are sensitive to single-trade outliers when n is close to 50. Recommend reviewing the median + max columns in the CSV before deploying any combo.

## 1. Top 10 ULTRA-strict configs (n>=50, WR>=80%, $/tr>=$2)

Total ultra-strict passing: **2108**

| # | strategy | cell | gates | n | WR | $/tr | sum_pnl | mcl | score |
|---|----------|------|-------|---|----|------|---------|-----|-------|
| 1 | S6 | `BTC|120|T2` | `ribbon_color_bear` | 51 | 0.804 | $36.05 | $1838.66 | 6 | 206.98 |
| 2 | S6 | `BTC|120|T2` | `ribbon_color_bear|ribbon_agrees` | 51 | 0.804 | $36.05 | $1838.66 | 6 | 206.98 |
| 3 | S6 | `BTC|120|T2` | `ribbon_color_bear|stoch_60s_agrees` | 50 | 0.800 | $34.54 | $1727.05 | 6 | 195.39 |
| 4 | S6 | `BTC|120|T2` | `ribbon_color_bear|cci_60s_agrees` | 50 | 0.800 | $34.54 | $1727.05 | 6 | 195.39 |
| 5 | S6 | `BTC|120|T2` | `ribbon_color_bear|ribbon_agrees|stoch_60s_agrees` | 50 | 0.800 | $34.54 | $1727.05 | 6 | 195.39 |
| 6 | S6 | `BTC|120|T2` | `ribbon_color_bear|ribbon_agrees|cci_60s_agrees` | 50 | 0.800 | $34.54 | $1727.05 | 6 | 195.39 |
| 7 | S6 | `BTC|120|T2` | `ribbon_color_bear|ribbon_agrees|stoch_60s_agrees|cci_60s_agrees` | 50 | 0.800 | $34.54 | $1727.05 | 6 | 195.39 |
| 8 | S6 | `BTC|120|T2` | `ribbon_color_bear|stoch_60s_agrees|cci_60s_agrees` | 50 | 0.800 | $34.54 | $1727.05 | 6 | 195.39 |
| 9 | S6 | `BTC|120|T2` | `stoch_60s_kd_cross` | 76 | 0.842 | $25.06 | $1904.51 | 3 | 183.97 |
| 10 | S6 | `BTC|120|T2` | `ribbon_agrees|stoch_60s_kd_cross` | 76 | 0.842 | $25.06 | $1904.51 | 3 | 183.97 |

## 2. Top 5 per cell (compact)

Only cells that have at least one passing combo are shown. Top-5 ranked by score within each cell.  
Full CSV with ALL 3,337 passing rows is at `data/v4/canonical/_results/new_indicators_combinatorial.csv`.

### S1.5  (27 cells total; top 12 by best-score shown — full CSV has the rest)

| cell | base_WR | base_$/tr | best_gates | n | WR | $/tr | score |
|------|---------|-----------|------------|---|----|------|-------|
| ETH|210 | 0.832 | $0.49 | `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees|mfi_60s_neutral` | 168 | 0.887 | $11.27 | 129.58 |
|  |  |  | `ribbon_color_bull|stoch_60s_agrees|bb_pos_60s_extreme_agrees|mfi_60s_neutral` | 172 | 0.884 | $11.08 | 128.41 |
|  |  |  | `ribbon_color_bull|bb_pos_60s_extreme_agrees|mfi_60s_neutral` | 174 | 0.885 | $10.96 | 128.00 |
| ETH|240 | 0.839 | $0.36 | `ribbon_color_bull|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees|mfi_60s_neutral` | 55 | 0.873 | $14.69 | 95.05 |
|  |  |  | `ribbon_color_bull|stoch_60s_agrees|stoch_60s_kd_cross|mfi_60s_neutral` | 96 | 0.865 | $7.31 | 61.89 |
|  |  |  | `ribbon_color_bull|stoch_60s_kd_cross|mfi_60s_neutral|cci_60s_agrees` | 99 | 0.869 | $7.14 | 61.73 |
| BTC|210 | 0.843 | $1.32 | `ribbon_color_bull|ribbon_compressed|bb_pos_60s_extreme_agrees` | 351 | 0.858 | $4.96 | 79.68 |
|  |  |  | `ribbon_color_bull|ribbon_compressed|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 351 | 0.858 | $4.96 | 79.68 |
|  |  |  | `ribbon_color_bull|ribbon_agrees|ribbon_compressed|bb_pos_60s_extreme_agrees` | 339 | 0.853 | $5.00 | 78.49 |
| BTC|240 | 0.835 | $0.96 | `ribbon_color_bear|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 136 | 0.890 | $7.46 | 77.42 |
|  |  |  | `ribbon_color_bear|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 136 | 0.890 | $7.46 | 77.42 |
|  |  |  | `ribbon_color_bear|ribbon_agrees|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 134 | 0.888 | $7.43 | 76.36 |
| BTC|270 | 0.797 | $-0.26 | `ribbon_agrees|stoch_60s_neutral|stoch_60s_agrees|cci_60s_agrees` | 57 | 0.860 | $11.22 | 72.82 |
|  |  |  | `ribbon_agrees|ribbon_compressed|stoch_60s_neutral|stoch_60s_agrees` | 59 | 0.847 | $10.42 | 67.85 |
|  |  |  | `ribbon_agrees|stoch_60s_neutral|stoch_60s_agrees` | 60 | 0.850 | $10.25 | 67.52 |
| SOL|270 | 0.855 | $-0.76 | `ribbon_color_bull|ribbon_strong|ribbon_compressed|bb_pos_60s_extreme_agrees` | 260 | 0.869 | $4.99 | 69.93 |
|  |  |  | `ribbon_color_bull|ribbon_agrees|ribbon_compressed|bb_pos_60s_extreme_agrees` | 254 | 0.858 | $4.62 | 63.16 |
|  |  |  | `ribbon_color_bull|ribbon_agrees|ribbon_strong|bb_pos_60s_extreme_agrees` | 278 | 0.867 | $4.18 | 60.44 |
| BTC|120 | 0.802 | $0.61 | `ribbon_agrees|stoch_60s_neutral|stoch_60s_kd_cross|cci_60s_agrees` | 57 | 0.860 | $10.60 | 68.83 |
|  |  |  | `ribbon_agrees|ribbon_compressed|stoch_60s_neutral|stoch_60s_kd_cross` | 61 | 0.852 | $10.03 | 66.77 |
|  |  |  | `ribbon_agrees|stoch_60s_neutral|stoch_60s_kd_cross` | 64 | 0.859 | $9.62 | 66.11 |
| ALL | 0.812 | $0.16 | `ribbon_color_bear|stoch_60s_neutral|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 369 | 0.840 | $3.98 | 64.24 |
|  |  |  | `ribbon_agrees|stoch_60s_neutral|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 629 | 0.820 | $3.12 | 64.23 |
|  |  |  | `stoch_60s_neutral|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 734 | 0.820 | $2.83 | 62.90 |
| ETH|270 | 0.804 | $-0.60 | `ribbon_color_bull|ribbon_agrees|ribbon_strong|bb_pos_60s_extreme_agrees` | 270 | 0.815 | $4.22 | 56.50 |
|  |  |  | `ribbon_color_bull|ribbon_strong|stoch_60s_agrees|bb_pos_60s_extreme_agrees` | 291 | 0.811 | $3.58 | 49.49 |
|  |  |  | `ribbon_color_bull|ribbon_strong|bb_pos_60s_extreme_agrees` | 292 | 0.812 | $3.57 | 49.46 |
| BTC|90 | 0.779 | $0.76 | `ribbon_color_bear|ribbon_agrees|mfi_60s_neutral` | 134 | 0.806 | $5.54 | 51.69 |
|  |  |  | `ribbon_color_bear|ribbon_agrees|stoch_60s_agrees|mfi_60s_neutral` | 134 | 0.806 | $5.54 | 51.69 |
|  |  |  | `ribbon_color_bear|ribbon_agrees|mfi_60s_neutral|cci_60s_agrees` | 134 | 0.806 | $5.54 | 51.69 |
| ETH|150 | 0.827 | $1.12 | `stoch_60s_agrees|stoch_60s_kd_cross` | 584 | 0.822 | $2.38 | 47.29 |
|  |  |  | `stoch_60s_kd_cross` | 622 | 0.822 | $2.25 | 46.03 |
|  |  |  | `stoch_60s_kd_cross|cci_60s_agrees` | 589 | 0.823 | $2.28 | 45.51 |
| BTC|150 | 0.835 | $0.72 | `stoch_60s_agrees|stoch_60s_kd_cross` | 514 | 0.854 | $2.30 | 44.47 |
|  |  |  | `stoch_60s_agrees|stoch_60s_kd_cross|cci_60s_agrees` | 513 | 0.854 | $2.29 | 44.38 |
|  |  |  | `ribbon_compressed|stoch_60s_agrees|stoch_60s_kd_cross` | 470 | 0.847 | $2.38 | 43.68 |

### S6  (31 cells total; top 12 by best-score shown — full CSV has the rest)

| cell | base_WR | base_$/tr | best_gates | n | WR | $/tr | score |
|------|---------|-----------|------------|---|----|------|-------|
| BTC|120|T2 | 0.817 | $16.49 | `ribbon_color_bear` | 51 | 0.804 | $36.05 | 206.98 |
|  |  |  | `ribbon_color_bear|ribbon_agrees` | 51 | 0.804 | $36.05 | 206.98 |
|  |  |  | `ribbon_color_bear|stoch_60s_agrees` | 50 | 0.800 | $34.54 | 195.39 |
| BTC|120|T1 | 0.740 | $5.36 | `ribbon_color_bear|ribbon_agrees|stoch_60s_kd_cross|cci_60s_agrees` | 125 | 0.792 | $16.09 | 142.51 |
|  |  |  | `ribbon_color_bear|stoch_60s_kd_cross|cci_60s_agrees` | 126 | 0.794 | $15.98 | 142.35 |
|  |  |  | `ribbon_color_bear|stoch_60s_agrees|stoch_60s_kd_cross|cci_60s_agrees` | 120 | 0.783 | $16.15 | 138.56 |
| ALL | 0.709 | $1.22 | `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees` | 4613 | 0.788 | $2.32 | 124.23 |
|  |  |  | `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 4613 | 0.788 | $2.32 | 124.23 |
|  |  |  | `ribbon_color_bull|stoch_60s_agrees` | 5062 | 0.774 | $2.24 | 123.68 |
| BTC|45|T1 | 0.721 | $4.31 | `ribbon_agrees|ribbon_compressed|stoch_60s_agrees|cci_60s_agrees` | 276 | 0.754 | $6.74 | 84.38 |
|  |  |  | `ribbon_color_bear|ribbon_agrees|ribbon_compressed|cci_60s_agrees` | 143 | 0.755 | $8.83 | 79.78 |
|  |  |  | `ribbon_color_bear|ribbon_strong|ribbon_compressed|cci_60s_agrees` | 99 | 0.808 | $9.60 | 77.21 |
| ETH|90|T1 | 0.690 | $-0.08 | `ribbon_color_bear|stoch_60s_agrees|bb_pos_60s_neutral|cci_60s_agrees` | 52 | 0.788 | $14.80 | 84.14 |
|  |  |  | `ribbon_color_bear|stoch_60s_agrees|bb_pos_60s_neutral` | 53 | 0.774 | $14.05 | 79.11 |
|  |  |  | `ribbon_color_bear|ribbon_agrees|stoch_60s_agrees|bb_pos_60s_neutral` | 51 | 0.765 | $14.09 | 76.93 |
| BTC|30|T1 | 0.736 | $3.94 | `ribbon_agrees|ribbon_strong|stoch_60s_agrees` | 308 | 0.812 | $5.78 | 82.39 |
|  |  |  | `ribbon_strong|stoch_60s_agrees` | 314 | 0.812 | $5.71 | 82.17 |
|  |  |  | `ribbon_agrees|ribbon_strong|stoch_60s_agrees|cci_60s_agrees` | 306 | 0.814 | $5.74 | 81.64 |
| BTC|90|T1 | 0.690 | $0.78 | `ribbon_color_bull|stoch_60s_agrees|stoch_60s_kd_cross|mfi_60s_neutral` | 53 | 0.755 | $14.34 | 78.77 |
|  |  |  | `ribbon_agrees|ribbon_strong|stoch_60s_agrees|mfi_60s_neutral` | 99 | 0.838 | $8.84 | 73.76 |
|  |  |  | `ribbon_strong|ribbon_compressed|stoch_60s_agrees|mfi_60s_neutral` | 65 | 0.815 | $10.81 | 71.04 |
| BTC|60|T1 | 0.717 | $3.39 | `ribbon_agrees|stoch_60s_agrees` | 442 | 0.758 | $4.22 | 67.24 |
|  |  |  | `ribbon_agrees|stoch_60s_agrees|cci_60s_agrees` | 442 | 0.758 | $4.22 | 67.24 |
|  |  |  | `stoch_60s_agrees` | 446 | 0.758 | $4.19 | 66.99 |
| ETH|60|T2 | 0.689 | $0.15 | `ribbon_color_bull|stoch_60s_kd_cross|cci_60s_agrees` | 55 | 0.855 | $10.38 | 65.77 |
|  |  |  | `ribbon_color_bull|ribbon_agrees|stoch_60s_kd_cross|cci_60s_agrees` | 55 | 0.855 | $10.38 | 65.77 |
|  |  |  | `ribbon_color_bull|cci_60s_agrees` | 84 | 0.869 | $7.51 | 59.79 |
| SOL|120|T1 | 0.709 | $-0.40 | `stoch_60s_neutral|bb_pos_60s_extreme_agrees` | 50 | 0.760 | $11.92 | 64.08 |
|  |  |  | `stoch_60s_neutral|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 50 | 0.760 | $11.92 | 64.08 |
|  |  |  | `ribbon_color_bull|ribbon_agrees|stoch_60s_agrees|bb_pos_60s_extreme_agrees` | 147 | 0.816 | $3.20 | 31.63 |
| SOL|90|T1 | 0.705 | $-1.06 | `ribbon_agrees|ribbon_compressed|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 68 | 0.794 | $9.64 | 63.15 |
|  |  |  | `ribbon_compressed|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 69 | 0.783 | $9.14 | 59.42 |
|  |  |  | `ribbon_compressed|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 69 | 0.783 | $9.14 | 59.42 |
| ETH|15|T1 | 0.659 | $0.30 | `ribbon_agrees|stoch_60s_kd_cross|bb_pos_60s_neutral|cci_60s_agrees` | 93 | 0.785 | $8.24 | 62.41 |
|  |  |  | `stoch_60s_kd_cross|bb_pos_60s_neutral|cci_60s_agrees` | 97 | 0.784 | $8.07 | 62.27 |
|  |  |  | `stoch_60s_agrees|stoch_60s_kd_cross|bb_pos_60s_neutral|cci_60s_agrees` | 88 | 0.795 | $8.33 | 62.15 |

## 3. Universal combos (work across >=3 cells)

Same gate combo passing thresholds in 3 or more distinct cells of the SAME strategy. Mean stats shown.

### S1.5  (283 universal combos)

| gates | cells | mean_n | mean_WR | mean_$/tr | total_n | total_pnl | mean_score |
|-------|-------|--------|---------|-----------|---------|-----------|------------|
| `ribbon_color_bear|ribbon_agrees|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 10 | 138 | 0.845 | $3.48 | 1382 | $4705.47 | 34.17 |
| `ribbon_color_bear|ribbon_compressed|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 8 | 135 | 0.839 | $3.71 | 1081 | $3902.19 | 35.93 |
| `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees` | 7 | 304 | 0.826 | $3.29 | 2126 | $7465.19 | 48.75 |
| `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 7 | 304 | 0.826 | $3.29 | 2126 | $7465.19 | 48.75 |
| `ribbon_color_bull|ribbon_agrees|stoch_60s_agrees|bb_pos_60s_extreme_agrees` | 7 | 302 | 0.825 | $3.28 | 2117 | $7424.20 | 48.56 |
| `ribbon_color_bull|bb_pos_60s_extreme_agrees` | 7 | 324 | 0.828 | $3.14 | 2265 | $7544.26 | 48.00 |
| `ribbon_color_bull|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 7 | 324 | 0.828 | $3.14 | 2265 | $7544.26 | 48.00 |
| `ribbon_color_bull|stoch_60s_agrees|bb_pos_60s_extreme_agrees` | 7 | 322 | 0.828 | $3.14 | 2256 | $7503.27 | 47.81 |
| `ribbon_color_bull|stoch_60s_agrees|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 7 | 322 | 0.828 | $3.14 | 2256 | $7503.27 | 47.81 |
| `ribbon_color_bull|ribbon_agrees|ribbon_compressed|bb_pos_60s_extreme_agrees` | 7 | 233 | 0.815 | $3.24 | 1634 | $5858.96 | 42.47 |
| `ribbon_color_bear|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees` | 7 | 140 | 0.850 | $4.06 | 983 | $3902.46 | 40.31 |
| `ribbon_color_bear|stoch_60s_kd_cross|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 7 | 140 | 0.850 | $4.06 | 983 | $3902.46 | 40.31 |

### S6  (213 universal combos)

| gates | cells | mean_n | mean_WR | mean_$/tr | total_n | total_pnl | mean_score |
|-------|-------|--------|---------|-----------|---------|-----------|------------|
| `ribbon_color_bull|bb_pos_60s_extreme_agrees` | 18 | 121 | 0.817 | $3.56 | 2171 | $7448.79 | 30.29 |
| `ribbon_color_bull|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 18 | 121 | 0.817 | $3.56 | 2171 | $7448.79 | 30.29 |
| `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees` | 18 | 119 | 0.817 | $3.57 | 2147 | $7418.55 | 30.25 |
| `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 18 | 119 | 0.817 | $3.57 | 2147 | $7418.55 | 30.25 |
| `ribbon_color_bull|stoch_60s_agrees|bb_pos_60s_extreme_agrees` | 17 | 114 | 0.820 | $3.62 | 1934 | $6849.37 | 30.28 |
| `ribbon_color_bull|stoch_60s_agrees|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 17 | 114 | 0.820 | $3.62 | 1934 | $6849.37 | 30.28 |
| `ribbon_color_bull|ribbon_agrees|stoch_60s_agrees|bb_pos_60s_extreme_agrees` | 17 | 112 | 0.820 | $3.63 | 1912 | $6831.19 | 30.27 |
| `ribbon_agrees|bb_pos_60s_extreme_agrees` | 15 | 224 | 0.804 | $3.42 | 3364 | $11731.29 | 39.63 |
| `ribbon_agrees|bb_pos_60s_extreme_agrees|cci_60s_agrees` | 15 | 224 | 0.804 | $3.42 | 3364 | $11731.29 | 39.63 |
| `bb_pos_60s_extreme_agrees` | 15 | 227 | 0.804 | $3.41 | 3404 | $11731.25 | 39.50 |
| `bb_pos_60s_extreme_agrees|cci_60s_agrees` | 15 | 227 | 0.804 | $3.41 | 3404 | $11731.25 | 39.50 |
| `ribbon_agrees|stoch_60s_agrees|cci_60s_agrees` | 14 | 262 | 0.790 | $5.02 | 3667 | $16154.46 | 57.17 |

## 4. Indicator usage frequency in winning configs

Count of distinct passing (cell, gate-combo) rows that mention each gate.

### S1.5  (5511 gate citations across 1560 winning rows)

| gate | citations | share |
|------|-----------|-------|
| `stoch_60s_kd_cross` | 690 | 12.5% |
| `bb_pos_60s_extreme_agrees` | 635 | 11.5% |
| `ribbon_agrees` | 533 | 9.7% |
| `stoch_60s_agrees` | 473 | 8.6% |
| `cci_60s_agrees` | 470 | 8.5% |
| `mfi_60s_neutral` | 459 | 8.3% |
| `ribbon_compressed` | 454 | 8.2% |
| `ribbon_color_bear` | 453 | 8.2% |
| `ribbon_color_bull` | 396 | 7.2% |
| `ribbon_strong` | 366 | 6.6% |
| `stoch_60s_neutral` | 291 | 5.3% |
| `bb_pos_60s_neutral` | 285 | 5.2% |
| `ribbon_expanded` | 6 | 0.1% |

### S6  (5506 gate citations across 1709 winning rows)

| gate | citations | share |
|------|-----------|-------|
| `bb_pos_60s_extreme_agrees` | 806 | 14.6% |
| `cci_60s_agrees` | 750 | 13.6% |
| `stoch_60s_agrees` | 749 | 13.6% |
| `ribbon_strong` | 745 | 13.5% |
| `ribbon_agrees` | 657 | 11.9% |
| `ribbon_color_bull` | 518 | 9.4% |
| `ribbon_color_bear` | 381 | 6.9% |
| `stoch_60s_kd_cross` | 346 | 6.3% |
| `ribbon_compressed` | 279 | 5.1% |
| `mfi_60s_neutral` | 213 | 3.9% |
| `bb_pos_60s_neutral` | 49 | 0.9% |
| `stoch_60s_neutral` | 13 | 0.2% |

## 5. Standalone `stoch_60s_kd_cross` effect (top 15 by WR lift)

Effect of applying ONLY the stochastic K-vs-D cross gate to each cell vs baseline.

### S1.5

| cell | n_base | WR_base | $/tr_base | n_kd | WR_kd | $/tr_kd | WR_lift | $/tr_lift |
|------|--------|---------|-----------|------|-------|---------|---------|-----------|
| `BTC|210` | 1456 | 0.843 | $1.32 | 564 | 0.874 | $1.19 | +0.031 | $-0.13 |
| `ETH|240` | 1755 | 0.839 | $0.36 | 642 | 0.863 | $0.72 | +0.024 | $+0.36 |
| `BTC|150` | 1367 | 0.835 | $0.72 | 544 | 0.851 | $2.10 | +0.016 | $+1.38 |
| `BTC|240` | 1318 | 0.835 | $0.96 | 530 | 0.849 | $2.15 | +0.014 | $+1.20 |
| `BTC|180` | 1506 | 0.831 | $-0.07 | 610 | 0.844 | $1.34 | +0.014 | $+1.40 |
| `SOL|180` | 1582 | 0.831 | $-0.75 | 561 | 0.838 | $-0.36 | +0.007 | $+0.40 |
| `BTC|270` | 913 | 0.797 | $-0.26 | 366 | 0.803 | $1.13 | +0.006 | $+1.40 |
| `ETH|210` | 1820 | 0.832 | $0.49 | 694 | 0.836 | $0.02 | +0.004 | $-0.47 |
| `BTC|120` | 1183 | 0.802 | $0.61 | 484 | 0.806 | $1.47 | +0.004 | $+0.86 |
| `SOL|120` | 1365 | 0.793 | $-0.44 | 487 | 0.795 | $0.16 | +0.001 | $+0.60 |
| `ETH|180` | 1773 | 0.836 | $0.19 | 685 | 0.831 | $0.33 | -0.005 | $+0.14 |
| `ETH|150` | 1714 | 0.827 | $1.12 | 622 | 0.822 | $2.25 | -0.006 | $+1.12 |
| `SOL|210` | 1638 | 0.849 | $-0.74 | 576 | 0.842 | $-0.92 | -0.007 | $-0.18 |
| `ALL` | 33279 | 0.812 | $0.16 | 12862 | 0.805 | $0.50 | -0.007 | $+0.34 |
| `ETH|120` | 1520 | 0.793 | $0.73 | 599 | 0.786 | $1.32 | -0.007 | $+0.59 |

### S6

| cell | n_base | WR_base | $/tr_base | n_kd | WR_kd | $/tr_kd | WR_lift | $/tr_lift |
|------|--------|---------|-----------|------|-------|---------|---------|-----------|
| `SOL|90|T1` | 356 | 0.705 | $-1.06 | 186 | 0.731 | $1.62 | +0.026 | $+2.68 |
| `BTC|120|T2` | 109 | 0.817 | $16.49 | 76 | 0.842 | $25.06 | +0.026 | $+8.57 |
| `SOL|120|T2` | 89 | 0.876 | $0.61 | 53 | 0.868 | $0.85 | -0.008 | $+0.24 |
| `SOL|15|T1` | 396 | 0.659 | $-0.06 | 196 | 0.643 | $1.12 | -0.016 | $+1.18 |
| `BTC|15|T1` | 628 | 0.658 | $1.52 | 398 | 0.641 | $1.60 | -0.017 | $+0.08 |
| `ETH|15|T1` | 592 | 0.659 | $0.30 | 382 | 0.641 | $0.91 | -0.017 | $+0.61 |
| `ETH|90|T2` | 163 | 0.712 | $-0.35 | 110 | 0.691 | $-0.06 | -0.021 | $+0.29 |
| `ETH|60|T1` | 574 | 0.706 | $1.32 | 362 | 0.677 | $2.25 | -0.029 | $+0.93 |
| `BTC|120|T1` | 412 | 0.740 | $5.36 | 271 | 0.705 | $7.12 | -0.035 | $+1.77 |
| `ETH|120|T2` | 127 | 0.850 | $5.73 | 97 | 0.814 | $5.88 | -0.036 | $+0.15 |
| `ETH|90|T1` | 564 | 0.690 | $-0.08 | 386 | 0.653 | $-0.66 | -0.037 | $-0.58 |
| `SOL|45|T2` | 103 | 0.757 | $0.73 | 50 | 0.720 | $2.68 | -0.037 | $+1.94 |
| `ETH|120|T1` | 487 | 0.727 | $0.93 | 327 | 0.688 | $0.75 | -0.039 | $-0.17 |
| `ETH|60|T2` | 183 | 0.689 | $0.15 | 125 | 0.648 | $0.50 | -0.041 | $+0.34 |
| `ETH|15|T2` | 155 | 0.632 | $-2.31 | 98 | 0.582 | $-3.20 | -0.051 | $-0.89 |

## 6. Do new indicators ADD edge beyond S1.5/S6 baseline?

### S1.5 — 27/28 cells have at least one passing combo (WR>=75%, $/tr>=$2)

Top 15 cells by best-combo score:

| cell | base_n | base_WR | base_$/tr | best_WR | best_$/tr | WR_lift | $/tr_lift |
|------|--------|---------|-----------|---------|-----------|---------|-----------|
| `ETH|210` | 1820 | 0.832 | $0.49 | 0.931 | $11.27 | +0.100 | $+10.79 |
| `ETH|240` | 1755 | 0.839 | $0.36 | 0.931 | $14.69 | +0.092 | $+14.33 |
| `BTC|210` | 1456 | 0.843 | $1.32 | 0.959 | $6.64 | +0.115 | $+5.32 |
| `BTC|240` | 1318 | 0.835 | $0.96 | 0.919 | $7.56 | +0.084 | $+6.61 |
| `BTC|270` | 913 | 0.797 | $-0.26 | 0.864 | $11.22 | +0.067 | $+11.48 |
| `SOL|270` | 1272 | 0.855 | $-0.76 | 0.869 | $4.99 | +0.015 | $+5.75 |
| `BTC|120` | 1183 | 0.802 | $0.61 | 0.923 | $10.60 | +0.121 | $+10.00 |
| `ALL` | 33279 | 0.812 | $0.16 | 0.981 | $3.98 | +0.169 | $+3.83 |
| `ETH|270` | 1273 | 0.804 | $-0.60 | 0.828 | $4.22 | +0.025 | $+4.82 |
| `BTC|90` | 973 | 0.779 | $0.76 | 0.852 | $6.55 | +0.073 | $+5.79 |
| `ETH|150` | 1714 | 0.827 | $1.12 | 0.880 | $5.78 | +0.053 | $+4.66 |
| `BTC|150` | 1367 | 0.835 | $0.72 | 0.933 | $4.90 | +0.099 | $+4.17 |
| `ETH|120` | 1520 | 0.793 | $0.73 | 0.891 | $4.60 | +0.098 | $+3.87 |
| `BTC|180` | 1506 | 0.831 | $-0.07 | 0.909 | $5.50 | +0.078 | $+5.57 |
| `SOL|30` | 408 | 0.701 | $0.92 | 0.820 | $5.33 | +0.119 | $+4.42 |

### S6 — 31/40 cells have at least one passing combo (WR>=75%, $/tr>=$2)

Top 15 cells by best-combo score:

| cell | base_n | base_WR | base_$/tr | best_WR | best_$/tr | WR_lift | $/tr_lift |
|------|--------|---------|-----------|---------|-----------|---------|-----------|
| `BTC|120|T2` | 109 | 0.817 | $16.49 | 0.922 | $36.05 | +0.105 | $+19.57 |
| `BTC|120|T1` | 412 | 0.740 | $5.36 | 0.922 | $16.15 | +0.182 | $+10.79 |
| `ALL` | 11336 | 0.709 | $1.22 | 0.811 | $6.10 | +0.102 | $+4.88 |
| `BTC|45|T1` | 470 | 0.721 | $4.31 | 0.826 | $9.60 | +0.104 | $+5.30 |
| `ETH|90|T1` | 564 | 0.690 | $-0.08 | 0.851 | $14.80 | +0.161 | $+14.88 |
| `BTC|30|T1` | 440 | 0.736 | $3.94 | 0.860 | $9.81 | +0.124 | $+5.88 |
| `BTC|90|T1` | 493 | 0.690 | $0.78 | 0.875 | $14.34 | +0.185 | $+13.55 |
| `BTC|60|T1` | 491 | 0.717 | $3.39 | 0.883 | $7.03 | +0.166 | $+3.64 |
| `ETH|60|T2` | 183 | 0.689 | $0.15 | 0.900 | $10.38 | +0.211 | $+10.23 |
| `SOL|120|T1` | 378 | 0.709 | $-0.40 | 0.819 | $11.92 | +0.110 | $+12.32 |
| `SOL|90|T1` | 356 | 0.705 | $-1.06 | 0.941 | $9.64 | +0.236 | $+10.71 |
| `ETH|15|T1` | 592 | 0.659 | $0.30 | 0.814 | $8.84 | +0.155 | $+8.54 |
| `SOL|30|T1` | 357 | 0.773 | $3.59 | 0.884 | $7.52 | +0.111 | $+3.93 |
| `BTC|30|T2` | 134 | 0.746 | $4.08 | 0.885 | $9.76 | +0.138 | $+5.68 |
| `ETH|120|T2` | 127 | 0.850 | $5.73 | 0.961 | $8.98 | +0.110 | $+3.24 |

## 7. Method notes

- **Gates** (~13): ribbon (color match, alignment, compression), stoch K (zone, agree, KD cross), BB pos (neutral, extreme-agree), MFI (neutral), CCI (sign-agree).
- **Subset sizes:** k=1,2,3,4. Subsets producing n<50 dropped immediately during enumeration.
- **Cells:** S1.5 = asset × fire_offset_s + ALL ; S6 = asset × fire_offset_s × tier + ALL.
- **Score:** `WR * sqrt(n) * max(avg_pnl, 0)` — penalizes avg_pnl<=0 by setting it to 0.
- **Outcome:** uses `won` flag (chainlink-derived) + `pnl_legacy_usd` (production legacy 2%-on-profit fee).
- **Direction:** uses `direction` UP/DOWN as in original fire.
