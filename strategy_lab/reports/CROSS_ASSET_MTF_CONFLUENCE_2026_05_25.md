# Cross-asset & MTF confluence — S1.5 / S6 / S7  2026-05-25

**Hypothesis**: agreement of RF/stack signals across BTC/ETH/SOL (and across 5m/15m/1h timeframes) at fire_us boosts conviction vs. bet-asset RF alone.

**Universe**: S1.5 5m fires = 33,294 (Apr 30 → May 22), S7 15m fires = 10,828.

**Fee model**: legacy 2%-on-profit (`pnl_legacy_usd`).

**Causal**: rf/tr features at fire_us use the last fully-closed bar before fire_us (1s panel keyed at ts_us+1s; 15m panel keyed at bar_start+15m; 1h panel keyed at bar_start+1h).

## 1. Cross-asset RF agreement frequencies

- All three same direction (up OR down): **67.32%** of S1.5 fires

- All three == bet direction: **57.94%**

- Majority (2/3) == bet direction: **78.71%**


Baseline WR by (asset, direction):


| asset | dir | n | wr | sum_pnl | mean_pnl |
|---|---:|---:|---:|---:|---:|
| BTC | UP | 4765 | 81.93% | 4,233.32 | 0.89 |
| BTC | DOWN | 4850 | 81.18% | 2,796.67 | 0.58 |
| ETH | UP | 6311 | 81.10% | 5,728.31 | 0.91 |
| ETH | DOWN | 6213 | 79.98% | -1,451.07 | -0.23 |
| SOL | UP | 5731 | 80.86% | -3,896.37 | -0.68 |
| SOL | DOWN | 5424 | 82.23% | -2,208.33 | -0.41 |


## 2. WR by cross-asset confluence level (S1.5)

| cell | asset | direction | n | wr | sum_pnl | mean_pnl |
|---|---|---|---:|---:|---:|---:|
| baseline | ALL | ALL | 33294 | 81.16% | 5,202.52 | 0.16 |
| baseline | BTC | ALL | 9615 | 81.55% | 7,029.98 | 0.73 |
| baseline | ETH | ALL | 12524 | 80.54% | 4,277.23 | 0.34 |
| baseline | SOL | ALL | 11155 | 81.52% | -6,104.70 | -0.55 |
| baseline | ALL | UP | 16807 | 81.25% | 6,065.26 | 0.36 |
| baseline | ALL | DOWN | 16487 | 81.07% | -862.74 | -0.05 |
| baseline | BTC | UP | 4765 | 81.93% | 4,233.32 | 0.89 |
| baseline | BTC | DOWN | 4850 | 81.18% | 2,796.67 | 0.58 |
| baseline | ETH | UP | 6311 | 81.10% | 5,728.31 | 0.91 |
| baseline | ETH | DOWN | 6213 | 79.98% | -1,451.07 | -0.23 |
| baseline | SOL | UP | 5731 | 80.86% | -3,896.37 | -0.68 |
| baseline | SOL | DOWN | 5424 | 82.23% | -2,208.33 | -0.41 |
| xa_all_with_bet | ALL | ALL | 19291 | 80.92% | 13,019.58 | 0.67 |
| xa_all_with_bet | BTC | ALL | 5534 | 82.06% | 8,748.18 | 1.58 |
| xa_all_with_bet | ETH | ALL | 7422 | 80.05% | 5,981.07 | 0.81 |
| xa_all_with_bet | SOL | ALL | 6335 | 80.95% | -1,709.67 | -0.27 |
| xa_all_with_bet | ALL | UP | 9838 | 80.78% | 7,841.54 | 0.80 |
| xa_all_with_bet | ALL | DOWN | 9453 | 81.06% | 5,178.04 | 0.55 |
| xa_all_with_bet | BTC | UP | 2808 | 81.98% | 4,284.94 | 1.53 |
| xa_all_with_bet | BTC | DOWN | 2726 | 82.13% | 4,463.24 | 1.64 |
| xa_all_with_bet | ETH | UP | 3750 | 80.43% | 4,982.28 | 1.33 |
| xa_all_with_bet | ETH | DOWN | 3672 | 79.66% | 998.79 | 0.27 |
| xa_all_with_bet | SOL | UP | 3280 | 80.15% | -1,425.67 | -0.43 |
| xa_all_with_bet | SOL | DOWN | 3055 | 81.80% | -283.99 | -0.09 |
| xa_maj_with_bet | ALL | ALL | 26205 | 81.02% | 11,361.46 | 0.43 |
| xa_maj_with_bet | BTC | ALL | 7469 | 81.62% | 8,124.56 | 1.09 |
| xa_maj_with_bet | ETH | ALL | 10022 | 80.26% | 5,947.12 | 0.59 |
| xa_maj_with_bet | SOL | ALL | 8714 | 81.36% | -2,710.22 | -0.31 |
| xa_maj_with_bet | ALL | UP | 13303 | 80.79% | 8,102.83 | 0.61 |
| xa_maj_with_bet | ALL | DOWN | 12902 | 81.24% | 3,258.64 | 0.25 |
| xa_maj_with_bet | BTC | UP | 3746 | 81.42% | 4,354.45 | 1.16 |
| xa_maj_with_bet | BTC | DOWN | 3723 | 81.82% | 3,770.11 | 1.01 |
| xa_maj_with_bet | ETH | UP | 5061 | 80.60% | 6,099.14 | 1.21 |
| xa_maj_with_bet | ETH | DOWN | 4961 | 79.92% | -152.01 | -0.03 |
| xa_maj_with_bet | SOL | UP | 4496 | 80.49% | -2,350.75 | -0.52 |
| xa_maj_with_bet | SOL | DOWN | 4218 | 82.29% | -359.46 | -0.09 |
| xa_self_with_others | ALL | ALL | 20926 | 80.93% | 11,768.29 | 0.56 |
| xa_self_with_others | BTC | ALL | 5879 | 81.80% | 8,524.85 | 1.45 |
| xa_self_with_others | ETH | ALL | 7933 | 80.13% | 5,569.02 | 0.70 |
| xa_self_with_others | SOL | ALL | 7114 | 81.09% | -2,325.58 | -0.33 |
| xa_self_with_others | ALL | UP | 10660 | 80.73% | 7,387.85 | 0.69 |
| xa_self_with_others | ALL | DOWN | 10266 | 81.13% | 4,380.44 | 0.43 |
| xa_self_with_others | BTC | UP | 2989 | 81.47% | 4,177.05 | 1.40 |
| xa_self_with_others | BTC | DOWN | 2890 | 82.15% | 4,347.81 | 1.50 |
| xa_self_with_others | ETH | UP | 4004 | 80.62% | 4,963.75 | 1.24 |
| xa_self_with_others | ETH | DOWN | 3929 | 79.64% | 605.27 | 0.15 |
| xa_self_with_others | SOL | UP | 3667 | 80.26% | -1,752.95 | -0.48 |
| xa_self_with_others | SOL | DOWN | 3447 | 81.98% | -572.64 | -0.17 |


## 3. MTF 5m/15m RF confluence (S1.5)

| cell | asset | direction | n | wr | sum_pnl | mean_pnl |
|---|---|---|---:|---:|---:|---:|
| baseline | ALL | ALL | 33294 | 81.16% | 5,202.52 | 0.16 |
| baseline | BTC | ALL | 9615 | 81.55% | 7,029.98 | 0.73 |
| baseline | ETH | ALL | 12524 | 80.54% | 4,277.23 | 0.34 |
| baseline | SOL | ALL | 11155 | 81.52% | -6,104.70 | -0.55 |
| baseline | ALL | UP | 16807 | 81.25% | 6,065.26 | 0.36 |
| baseline | ALL | DOWN | 16487 | 81.07% | -862.74 | -0.05 |
| baseline | BTC | UP | 4765 | 81.93% | 4,233.32 | 0.89 |
| baseline | BTC | DOWN | 4850 | 81.18% | 2,796.67 | 0.58 |
| baseline | ETH | UP | 6311 | 81.10% | 5,728.31 | 0.91 |
| baseline | ETH | DOWN | 6213 | 79.98% | -1,451.07 | -0.23 |
| baseline | SOL | UP | 5731 | 80.86% | -3,896.37 | -0.68 |
| baseline | SOL | DOWN | 5424 | 82.23% | -2,208.33 | -0.41 |
| mtf_5m_with_bet | ALL | ALL | 26379 | 81.03% | 11,074.82 | 0.42 |
| mtf_5m_with_bet | BTC | ALL | 7695 | 81.79% | 7,958.46 | 1.03 |
| mtf_5m_with_bet | ETH | ALL | 9940 | 80.22% | 6,041.20 | 0.61 |
| mtf_5m_with_bet | SOL | ALL | 8744 | 81.28% | -2,924.84 | -0.33 |
| mtf_5m_with_bet | ALL | UP | 13400 | 80.97% | 8,321.47 | 0.62 |
| mtf_5m_with_bet | ALL | DOWN | 12979 | 81.09% | 2,753.36 | 0.21 |
| mtf_5m_with_bet | BTC | UP | 3821 | 81.99% | 4,415.15 | 1.16 |
| mtf_5m_with_bet | BTC | DOWN | 3874 | 81.60% | 3,543.32 | 0.91 |
| mtf_5m_with_bet | ETH | UP | 5042 | 80.58% | 6,142.97 | 1.22 |
| mtf_5m_with_bet | ETH | DOWN | 4898 | 79.85% | -101.77 | -0.02 |
| mtf_5m_with_bet | SOL | UP | 4537 | 80.54% | -2,236.65 | -0.49 |
| mtf_5m_with_bet | SOL | DOWN | 4207 | 82.08% | -688.19 | -0.16 |
| mtf_15m_with_bet | ALL | ALL | 15542 | 80.97% | -5,352.65 | -0.34 |
| mtf_15m_with_bet | BTC | ALL | 4470 | 80.56% | -854.04 | -0.19 |
| mtf_15m_with_bet | ETH | ALL | 5739 | 80.69% | -820.59 | -0.14 |
| mtf_15m_with_bet | SOL | ALL | 5333 | 81.62% | -3,678.02 | -0.69 |
| mtf_15m_with_bet | ALL | UP | 7760 | 81.40% | -1,858.37 | -0.24 |
| mtf_15m_with_bet | ALL | DOWN | 7782 | 80.54% | -3,494.29 | -0.45 |
| mtf_15m_with_bet | BTC | UP | 2242 | 81.31% | -408.26 | -0.18 |
| mtf_15m_with_bet | BTC | DOWN | 2228 | 79.80% | -445.78 | -0.20 |
| mtf_15m_with_bet | ETH | UP | 2780 | 81.47% | 605.07 | 0.22 |
| mtf_15m_with_bet | ETH | DOWN | 2959 | 79.96% | -1,425.66 | -0.48 |
| mtf_15m_with_bet | SOL | UP | 2738 | 81.41% | -2,055.17 | -0.75 |
| mtf_15m_with_bet | SOL | DOWN | 2595 | 81.85% | -1,622.85 | -0.63 |
| mtf_double_with | ALL | ALL | 12276 | 80.89% | -1,407.79 | -0.11 |
| mtf_double_with | BTC | ALL | 3595 | 80.72% | 267.41 | 0.07 |
| mtf_double_with | ETH | ALL | 4547 | 80.40% | 120.95 | 0.03 |
| mtf_double_with | SOL | ALL | 4134 | 81.57% | -1,796.15 | -0.43 |
| mtf_double_with | ALL | UP | 6235 | 81.33% | -117.99 | -0.02 |
| mtf_double_with | ALL | DOWN | 6041 | 80.43% | -1,289.80 | -0.21 |
| mtf_double_with | BTC | UP | 1832 | 81.28% | -30.75 | -0.02 |
| mtf_double_with | BTC | DOWN | 1763 | 80.15% | 298.16 | 0.17 |
| mtf_double_with | ETH | UP | 2242 | 81.22% | 967.43 | 0.43 |
| mtf_double_with | ETH | DOWN | 2305 | 79.61% | -846.48 | -0.37 |
| mtf_double_with | SOL | UP | 2161 | 81.49% | -1,054.67 | -0.49 |
| mtf_double_with | SOL | DOWN | 1973 | 81.65% | -741.48 | -0.38 |


## 4. EMA stack cross-asset confluence (S1.5)

| cell | asset | direction | n | wr | sum_pnl | mean_pnl |
|---|---|---|---:|---:|---:|---:|
| baseline | ALL | ALL | 33294 | 81.16% | 5,202.52 | 0.16 |
| baseline | BTC | ALL | 9615 | 81.55% | 7,029.98 | 0.73 |
| baseline | ETH | ALL | 12524 | 80.54% | 4,277.23 | 0.34 |
| baseline | SOL | ALL | 11155 | 81.52% | -6,104.70 | -0.55 |
| baseline | ALL | UP | 16807 | 81.25% | 6,065.26 | 0.36 |
| baseline | ALL | DOWN | 16487 | 81.07% | -862.74 | -0.05 |
| baseline | BTC | UP | 4765 | 81.93% | 4,233.32 | 0.89 |
| baseline | BTC | DOWN | 4850 | 81.18% | 2,796.67 | 0.58 |
| baseline | ETH | UP | 6311 | 81.10% | 5,728.31 | 0.91 |
| baseline | ETH | DOWN | 6213 | 79.98% | -1,451.07 | -0.23 |
| baseline | SOL | UP | 5731 | 80.86% | -3,896.37 | -0.68 |
| baseline | SOL | DOWN | 5424 | 82.23% | -2,208.33 | -0.41 |
| xa_stack_all_with_bet | ALL | ALL | 20357 | 81.07% | 13,648.35 | 0.67 |
| xa_stack_all_with_bet | BTC | ALL | 5929 | 81.94% | 8,488.15 | 1.43 |
| xa_stack_all_with_bet | ETH | ALL | 7823 | 80.25% | 6,487.17 | 0.83 |
| xa_stack_all_with_bet | SOL | ALL | 6605 | 81.27% | -1,326.97 | -0.20 |
| xa_stack_all_with_bet | ALL | UP | 10325 | 81.25% | 10,119.58 | 0.98 |
| xa_stack_all_with_bet | ALL | DOWN | 10032 | 80.89% | 3,528.77 | 0.35 |
| xa_stack_all_with_bet | BTC | UP | 2993 | 82.06% | 4,630.98 | 1.55 |
| xa_stack_all_with_bet | BTC | DOWN | 2936 | 81.81% | 3,857.17 | 1.31 |
| xa_stack_all_with_bet | ETH | UP | 3941 | 80.89% | 6,123.16 | 1.55 |
| xa_stack_all_with_bet | ETH | DOWN | 3882 | 79.60% | 364.01 | 0.09 |
| xa_stack_all_with_bet | SOL | UP | 3391 | 80.95% | -634.57 | -0.19 |
| xa_stack_all_with_bet | SOL | DOWN | 3214 | 81.61% | -692.41 | -0.22 |
| xa_stack_maj_with_bet | ALL | ALL | 26589 | 81.24% | 10,933.20 | 0.41 |
| xa_stack_maj_with_bet | BTC | ALL | 7662 | 81.94% | 8,223.47 | 1.07 |
| xa_stack_maj_with_bet | ETH | ALL | 10156 | 80.53% | 5,883.63 | 0.58 |
| xa_stack_maj_with_bet | SOL | ALL | 8771 | 81.44% | -3,173.91 | -0.36 |
| xa_stack_maj_with_bet | ALL | UP | 13527 | 81.07% | 7,932.01 | 0.59 |
| xa_stack_maj_with_bet | ALL | DOWN | 13062 | 81.41% | 3,001.18 | 0.23 |
| xa_stack_maj_with_bet | BTC | UP | 3845 | 81.72% | 4,402.44 | 1.14 |
| xa_stack_maj_with_bet | BTC | DOWN | 3817 | 82.16% | 3,821.03 | 1.00 |
| xa_stack_maj_with_bet | ETH | UP | 5139 | 80.97% | 6,167.47 | 1.20 |
| xa_stack_maj_with_bet | ETH | DOWN | 5017 | 80.09% | -283.84 | -0.06 |
| xa_stack_maj_with_bet | SOL | UP | 4543 | 80.63% | -2,637.90 | -0.58 |
| xa_stack_maj_with_bet | SOL | DOWN | 4228 | 82.31% | -536.01 | -0.13 |


## 5. Combined confluence gates (S1.5)

| cell | asset | direction | n | wr | sum_pnl | mean_pnl |
|---|---|---|---:|---:|---:|---:|
| confluence_max | ALL | ALL | 8681 | 80.72% | 278.65 | 0.03 |
| confluence_max | BTC | ALL | 2550 | 81.10% | 1,151.10 | 0.45 |
| confluence_max | ETH | ALL | 3333 | 80.08% | 85.67 | 0.03 |
| confluence_max | SOL | ALL | 2798 | 81.13% | -958.12 | -0.34 |
| confluence_max | ALL | UP | 4410 | 81.38% | 489.97 | 0.11 |
| confluence_max | ALL | DOWN | 4271 | 80.03% | -211.32 | -0.05 |
| confluence_max | BTC | UP | 1321 | 81.30% | 229.05 | 0.17 |
| confluence_max | BTC | DOWN | 1229 | 80.88% | 922.05 | 0.75 |
| confluence_max | ETH | UP | 1625 | 81.42% | 696.20 | 0.43 |
| confluence_max | ETH | DOWN | 1708 | 78.81% | -610.53 | -0.36 |
| confluence_max | SOL | UP | 1464 | 81.42% | -435.27 | -0.30 |
| confluence_max | SOL | DOWN | 1334 | 80.81% | -522.85 | -0.39 |
| confluence_strong | ALL | ALL | 24113 | 81.10% | 13,104.60 | 0.54 |
| confluence_strong | BTC | ALL | 7101 | 81.83% | 8,617.79 | 1.21 |
| confluence_strong | ETH | ALL | 9370 | 80.29% | 6,040.96 | 0.64 |
| confluence_strong | SOL | ALL | 7642 | 81.41% | -1,554.15 | -0.20 |
| confluence_strong | ALL | UP | 12278 | 80.95% | 9,372.86 | 0.76 |
| confluence_strong | ALL | DOWN | 11835 | 81.25% | 3,731.74 | 0.32 |
| confluence_strong | BTC | UP | 3559 | 81.79% | 4,965.07 | 1.40 |
| confluence_strong | BTC | DOWN | 3542 | 81.87% | 3,652.72 | 1.03 |
| confluence_strong | ETH | UP | 4746 | 80.53% | 5,777.20 | 1.22 |
| confluence_strong | ETH | DOWN | 4624 | 80.04% | 263.76 | 0.06 |
| confluence_strong | SOL | UP | 3973 | 80.69% | -1,369.41 | -0.34 |
| confluence_strong | SOL | DOWN | 3669 | 82.17% | -184.74 | -0.05 |
| confluence_med | ALL | ALL | 20926 | 80.93% | 11,768.29 | 0.56 |
| confluence_med | BTC | ALL | 5879 | 81.80% | 8,524.85 | 1.45 |
| confluence_med | ETH | ALL | 7933 | 80.13% | 5,569.02 | 0.70 |
| confluence_med | SOL | ALL | 7114 | 81.09% | -2,325.58 | -0.33 |
| confluence_med | ALL | UP | 10660 | 80.73% | 7,387.85 | 0.69 |
| confluence_med | ALL | DOWN | 10266 | 81.13% | 4,380.44 | 0.43 |
| confluence_med | BTC | UP | 2989 | 81.47% | 4,177.05 | 1.40 |
| confluence_med | BTC | DOWN | 2890 | 82.15% | 4,347.81 | 1.50 |
| confluence_med | ETH | UP | 4004 | 80.62% | 4,963.75 | 1.24 |
| confluence_med | ETH | DOWN | 3929 | 79.64% | 605.27 | 0.15 |
| confluence_med | SOL | UP | 3667 | 80.26% | -1,752.95 | -0.48 |
| confluence_med | SOL | DOWN | 3447 | 81.98% | -572.64 | -0.17 |


## 6. Confluence as standalone entry strategy (S1.5)

| strategy | scope | n | wr | sum_pnl | mean_pnl |
|---|---|---:|---:|---:|---:|
| confluence_max | ALL | 8681 | 80.72% | 278.65 | 0.03 |
| confluence_max | BTC | 2550 | 81.10% | 1,151.10 | 0.45 |
| confluence_max | BTC_UP | 1321 | 81.30% | 229.05 | 0.17 |
| confluence_max | BTC_DOWN | 1229 | 80.88% | 922.05 | 0.75 |
| confluence_max | ETH | 3333 | 80.08% | 85.67 | 0.03 |
| confluence_max | ETH_UP | 1625 | 81.42% | 696.20 | 0.43 |
| confluence_max | ETH_DOWN | 1708 | 78.81% | -610.53 | -0.36 |
| confluence_max | SOL | 2798 | 81.13% | -958.12 | -0.34 |
| confluence_max | SOL_UP | 1464 | 81.42% | -435.27 | -0.30 |
| confluence_max | SOL_DOWN | 1334 | 80.81% | -522.85 | -0.39 |
| confluence_strong | ALL | 24113 | 81.10% | 13,104.60 | 0.54 |
| confluence_strong | BTC | 7101 | 81.83% | 8,617.79 | 1.21 |
| confluence_strong | BTC_UP | 3559 | 81.79% | 4,965.07 | 1.40 |
| confluence_strong | BTC_DOWN | 3542 | 81.87% | 3,652.72 | 1.03 |
| confluence_strong | ETH | 9370 | 80.29% | 6,040.96 | 0.64 |
| confluence_strong | ETH_UP | 4746 | 80.53% | 5,777.20 | 1.22 |
| confluence_strong | ETH_DOWN | 4624 | 80.04% | 263.76 | 0.06 |
| confluence_strong | SOL | 7642 | 81.41% | -1,554.15 | -0.20 |
| confluence_strong | SOL_UP | 3973 | 80.69% | -1,369.41 | -0.34 |
| confluence_strong | SOL_DOWN | 3669 | 82.17% | -184.74 | -0.05 |


## 7. Top 15 sleeves by sum_pnl (n>=30)

| rule | asset | dir | n | wr | sum_pnl | mean_pnl |
|---:|---|---:|---:|---:|---:|---:|
| xa_stack_maj_with_bet | ETH | UP | 5139 | 80.97% | 6,167.47 | 1.20 |
| xa_stack_all_with_bet | ETH | UP | 3941 | 80.89% | 6,123.16 | 1.55 |
| xa_maj_with_bet | ETH | UP | 5061 | 80.60% | 6,099.14 | 1.21 |
| confluence_strong | ETH | UP | 4746 | 80.53% | 5,777.20 | 1.22 |
| xa_all_with_bet | ETH | UP | 3750 | 80.43% | 4,982.28 | 1.33 |
| confluence_strong | BTC | UP | 3559 | 81.79% | 4,965.07 | 1.40 |
| confluence_med | ETH | UP | 4004 | 80.62% | 4,963.75 | 1.24 |
| xa_self_with_others | ETH | UP | 4004 | 80.62% | 4,963.75 | 1.24 |
| xa_stack_all_with_bet | BTC | UP | 2993 | 82.06% | 4,630.98 | 1.55 |
| xa_all_with_bet | BTC | DOWN | 2726 | 82.13% | 4,463.24 | 1.64 |
| xa_stack_maj_with_bet | BTC | UP | 3845 | 81.72% | 4,402.44 | 1.14 |
| xa_maj_with_bet | BTC | UP | 3746 | 81.42% | 4,354.45 | 1.16 |
| confluence_med | BTC | DOWN | 2890 | 82.15% | 4,347.81 | 1.50 |
| xa_self_with_others | BTC | DOWN | 2890 | 82.15% | 4,347.81 | 1.50 |
| xa_all_with_bet | BTC | UP | 2808 | 81.98% | 4,284.94 | 1.53 |


## 8. Top 15 sleeves by WR (n>=30)  — n-vs-WR Pareto

| rule | asset | dir | n | wr | sum_pnl | mean_pnl |
|---:|---|---:|---:|---:|---:|---:|
| xa_stack_maj_with_bet | SOL | DOWN | 4228 | 82.31% | -536.01 | -0.13 |
| xa_maj_with_bet | SOL | DOWN | 4218 | 82.29% | -359.46 | -0.09 |
| confluence_strong | SOL | DOWN | 3669 | 82.17% | -184.74 | -0.05 |
| xa_stack_maj_with_bet | BTC | DOWN | 3817 | 82.16% | 3,821.03 | 1.00 |
| confluence_med | BTC | DOWN | 2890 | 82.15% | 4,347.81 | 1.50 |
| xa_self_with_others | BTC | DOWN | 2890 | 82.15% | 4,347.81 | 1.50 |
| xa_all_with_bet | BTC | DOWN | 2726 | 82.13% | 4,463.24 | 1.64 |
| xa_stack_all_with_bet | BTC | UP | 2993 | 82.06% | 4,630.98 | 1.55 |
| confluence_med | SOL | DOWN | 3447 | 81.98% | -572.64 | -0.17 |
| xa_self_with_others | SOL | DOWN | 3447 | 81.98% | -572.64 | -0.17 |
| xa_all_with_bet | BTC | UP | 2808 | 81.98% | 4,284.94 | 1.53 |
| confluence_strong | BTC | DOWN | 3542 | 81.87% | 3,652.72 | 1.03 |
| mtf_15m_with_bet | SOL | DOWN | 2595 | 81.85% | -1,622.85 | -0.63 |
| xa_maj_with_bet | BTC | DOWN | 3723 | 81.82% | 3,770.11 | 1.01 |
| xa_stack_all_with_bet | BTC | DOWN | 2936 | 81.81% | 3,857.17 | 1.31 |


## 9. S7 15m fires — cross-asset + 1h confluence

| cell | scope | n | wr | sum_pnl | mean_pnl |
|---|---|---:|---:|---:|---:|
| S7_baseline | ALL | 10828 | 79.87% | -5,845.65 | -0.54 |
| S7_xa_all_with_bet | ALL | 4895 | 78.82% | 558.72 | 0.11 |
| S7_xa_all_with_bet | BTC | 1349 | 80.43% | 808.83 | 0.60 |
| S7_xa_all_with_bet | ETH | 1735 | 78.50% | -295.79 | -0.17 |
| S7_xa_all_with_bet | SOL | 1811 | 77.91% | 45.67 | 0.03 |
| S7_xa_maj_with_bet | ALL | 7199 | 79.83% | -247.60 | -0.03 |
| S7_xa_maj_with_bet | BTC | 1947 | 81.30% | 797.13 | 0.41 |
| S7_xa_maj_with_bet | ETH | 2552 | 78.96% | -955.13 | -0.37 |
| S7_xa_maj_with_bet | SOL | 2700 | 79.59% | -89.60 | -0.03 |
| S7_mtf_1h_with_bet | ALL | 5209 | 79.23% | -3,400.74 | -0.65 |
| S7_mtf_1h_with_bet | BTC | 1422 | 80.52% | -1,014.00 | -0.71 |
| S7_mtf_1h_with_bet | ETH | 1737 | 79.27% | -1,207.10 | -0.69 |
| S7_mtf_1h_with_bet | SOL | 2050 | 78.29% | -1,179.64 | -0.58 |
| s7_confluence_max | ALL | 2331 | 77.18% | -273.11 | -0.12 |
| s7_confluence_max | BTC | 612 | 78.92% | 78.48 | 0.13 |
| s7_confluence_max | ETH | 817 | 76.87% | -364.96 | -0.45 |
| s7_confluence_max | SOL | 902 | 76.27% | 13.37 | 0.01 |
| s7_confluence_strong | ALL | 3483 | 78.84% | -807.77 | -0.23 |
| s7_confluence_strong | BTC | 906 | 80.57% | -41.04 | -0.05 |
| s7_confluence_strong | ETH | 1206 | 78.36% | -480.45 | -0.40 |
| s7_confluence_strong | SOL | 1371 | 78.12% | -286.28 | -0.21 |


## 10. Trending-market check — is `xa_all_with_bet` just a trend detector?

If `xa_all_with_bet` is mostly a re-encoding of bet-asset RF trend, the

ribbon slope and |rf_dist_bps| should NOT diverge much between subset and base.


| asset | n_all | n_conf | ribbon_slope_base | ribbon_slope_conf | rf_dist_abs_base | rf_dist_abs_conf |
|---|---:|---:|---:|---:|---:|---:|
| BTC | 9615 | 5534 | 0.01 | 0.03 | 0.41 | 0.45 |
| ETH | 12524 | 7422 | -0.01 | 0.00 | 0.52 | 0.55 |
| SOL | 11155 | 6335 | 0.02 | 0.02 | 0.85 | 0.90 |


## 11. Recommendation

- **Baseline S1.5**: n=33294, WR=81.16%, sum_pnl=$5202.52, mean=$0.1563

- **xa_self_with_others**: n=20926, WR=80.93%, sum=$11768.29, mean=$0.5624, WR delta vs baseline = -0.23pp

- **mtf_double_with (5m+15m)**: n=12276, WR=80.89%, sum=$-1407.79, mean=$-0.1147, WR delta vs baseline = -0.27pp

- **confluence_strong**: n=24113, WR=81.10%, sum=$13104.60, mean=$0.5435, WR delta vs baseline = -0.06pp

- **confluence_max**: n=8681, WR=80.72%, sum=$278.65, mean=$0.0321, WR delta vs baseline = -0.45pp


## 12. Caveats

- The S1.5 fires already encode a profitable filter (baseline WR is elevated because fires were pre-selected by S1.5 gates and ws_s alignment). Confluence rules add bias on top of an already-biased universe.

- Cross-asset RF agreement is plausibly a **trending-market detector**. BTC pumps → ETH/SOL pump → all three RF=+1 simultaneously. Section 10 compares ribbon slope between the confluence subset and the full set to gauge how much of the lift is just "market is trending" already encoded in bet-asset features.

- 15m and 1h RF panels were rebuilt from 1s closes with n smaller (n=7,sn=14 for 15m; n=4,sn=7 for 1h) since each bar represents 900s / 3600s of underlying movement; tuning n was NOT optimized — these are reasonable defaults.

- All p-values would need bootstrap; this report only reports raw WR/PnL deltas.

- Window = 2026-04-30 → 2026-05-22 (~22 days); out-of-sample validation pending.
