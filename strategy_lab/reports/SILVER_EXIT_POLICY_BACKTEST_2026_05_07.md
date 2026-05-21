# SILVER Exit-Policy Backtest — SOL

**Date:** 2026-05-07
**SILVER gate:** struct_min=0.3, flow_min=0.4, sign-aligned
**rev_bp grid:** [2, 3, 5, 8, 10]

## TL;DR

- Baseline SILVER+HOLD: n=8, hit=100.0%, mean=$+4.0771
- Best SILVER variant: HOLD rev_bp=n/a, n=8, hit=100.0%, mean=$+4.0771
- HOLD still best on SILVER (or tied)

## SILVER subset — full sweep

(Baseline SILVER+HOLD: n=8, 100% hit, +$4.08/trade — from SILVER_VALIDATION_FINAL_2026_05_07.md)

| policy   | rev_bp   |   n |   hit_pct |   mean_usd |   total_usd |   std_usd |   sharpe |   max_dd |   p_value |
|:---------|:---------|----:|----------:|-----------:|------------:|----------:|---------:|---------:|----------:|
| HOLD     | n/a      |   8 |     100   |     4.0771 |       32.62 |    2.7183 |   24.028 |     0    |       nan |
| HEDGE    | 2        |   8 |      87.5 |     3.9824 |       31.86 |    2.8596 |   22.31  |    -0.51 |       nan |
| HEDGE    | 3        |   8 |      87.5 |     3.9824 |       31.86 |    2.8596 |   22.31  |    -0.51 |       nan |
| HEDGE    | 5        |   8 |      87.5 |     3.9824 |       31.86 |    2.8596 |   22.31  |    -0.51 |       nan |
| HEDGE    | 8        |   8 |      87.5 |     3.9824 |       31.86 |    2.8596 |   22.31  |    -0.51 |       nan |
| HEDGE    | 10       |   8 |      87.5 |     3.9824 |       31.86 |    2.8596 |   22.31  |    -0.51 |       nan |
| SELL     | 2        |   8 |      87.5 |     3.983  |       31.86 |    2.8586 |   22.321 |    -0.51 |       nan |
| SELL     | 3        |   8 |      87.5 |     3.983  |       31.86 |    2.8586 |   22.321 |    -0.51 |       nan |
| SELL     | 5        |   8 |      87.5 |     3.983  |       31.86 |    2.8586 |   22.321 |    -0.51 |       nan |
| SELL     | 8        |   8 |      87.5 |     3.983  |       31.86 |    2.8586 |   22.321 |    -0.51 |       nan |
| SELL     | 10       |   8 |      87.5 |     3.983  |       31.86 |    2.8586 |   22.321 |    -0.51 |       nan |

## Full SOL momo (unfiltered top-10%) — same matrix for context

| policy   | rev_bp   |   n |   hit_pct |   mean_usd |   total_usd |   std_usd |   sharpe |   max_dd |   p_value |
|:---------|:---------|----:|----------:|-----------:|------------:|----------:|---------:|---------:|----------:|
| HOLD     | n/a      | 354 |      87.3 |    -0.3976 |     -140.76 |    9.6844 |   -4.053 |  -253.72 |     0.546 |
| HEDGE    | 2        | 354 |      56.2 |    -0.531  |     -187.98 |    5.1803 |  -10.118 |  -253.03 |     0.505 |
| HEDGE    | 3        | 354 |      60.2 |    -0.3862 |     -136.73 |    5.2548 |   -7.255 |  -201.78 |     0.542 |
| HEDGE    | 5        | 354 |      65.8 |    -0.1447 |      -51.22 |    5.592  |   -2.554 |  -157.25 |     0.529 |
| HEDGE    | 8        | 354 |      70.3 |    -0.1508 |      -53.37 |    6.2383 |   -2.385 |  -135.81 |     0.545 |
| HEDGE    | 10       | 354 |      74.9 |    -0.0276 |       -9.78 |    6.6077 |   -0.413 |  -125.51 |     0.482 |
| SELL     | 2        | 354 |      57.3 |    -0.4512 |     -159.73 |    5.0977 |   -8.737 |  -224.78 |     0.501 |
| SELL     | 3        | 354 |      61.3 |    -0.3066 |     -108.53 |    5.1701 |   -5.853 |  -173.58 |     0.477 |
| SELL     | 5        | 354 |      66.1 |    -0.0764 |      -27.04 |    5.5126 |   -1.368 |  -140.09 |     0.501 |
| SELL     | 8        | 354 |      70.3 |    -0.1022 |      -36.18 |    6.1706 |   -1.635 |  -123.78 |     0.482 |
| SELL     | 10       | 354 |      74.9 |     0.0172 |        6.08 |    6.5423 |    0.259 |  -122.5  |     0.465 |

## Best variant per subset

- **SOL_SILVER**: HOLD rev_bp=n/a n=8 hit=100.0% mean=$+4.0771 sharpe=24.028 p=nan
- **SOL_MOMO**: SELL rev_bp=10 n=354 hit=74.9% mean=$+0.0172 sharpe=0.259 p=0.465

## Caveats

- **Sample bottleneck:** SILVER n=8 over Apr22–May6. HEDGE/SELL may skip more trades (no bucket-book match), so effective n could be even smaller. All statistics with n<30 are illustrative only.
- **Upper bound:** BACKTEST engine has lookahead bug fixed (end-time-indexed asof). Production SHADOW data shows realfill leaving $7.30/trade on the table because the production hedge bug prevents exit-policy from firing. Lab numbers are the ceiling AFTER TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK lands.
- **HEDGE/SELL skip trades** when the opposite-side book is absent at the trigger bucket. On thin markets (SOL SILVER) this further reduces n.
- **Permutation test:** shuffles outcome_up within fired trades. With n<30, p-values are unreliable; treat as directional signal only.
- **CSV:** `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\results\silver_exit_policies\silver_exit_policy_sweep.csv`