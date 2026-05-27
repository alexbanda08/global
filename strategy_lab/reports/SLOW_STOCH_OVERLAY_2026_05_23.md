# Slow-Stoch Overlay on S1.5 / S6 (2026-05-23)

**Inputs:** `s15_with_ta.parquet` (33,323 fires) + `s6_with_ta.parquet` (11,336 fires).
Anchor: TA computed at `ts_us` (fire bar). Stoch 60s = 1-min Stochastic; Stoch 300s = 5-min Stochastic.

**Fee model:** legacy 2%-on-profit (matches current production — see CLAUDE.md fee verification 2026-05-22).

---

## Headline

Quick verdict by hypothesis (median across asset×direction cells, weighted by sample size):

- **H1 (UP overbought → exhaustion)**: median ΔPnL vs UP baseline = `+0.216` $/tr, median ΔWR = `+6.39pp` (n cells = 12).
- **H3 (UP oversold → bounce)**: median ΔPnL = `-1.370` $/tr, median ΔWR = `-15.54pp` (n cells = 6).
- **H4 (K/D crossover agrees with bet direction)**: median ΔPnL vs disagreement = `+0.568` $/tr, median ΔWR = `-5.84pp` (n cells = 24).
- **Composite (both windows agree, both neutral)** vs baseline: median ΔPnL = `-0.333` $/tr (n cells = 8).

**Winner:** `H4 K/D agreement` (median ΔPnL = `+0.568` $/tr).
**Worst:** `H3 oversold bounce (UP oversold)` (median ΔPnL = `-1.370` $/tr).

---
## 1. Tier × asset × direction WR (Stoch 60s)

| source | asset | direction | tier         |     n |   WR    |   $/tr   |  sum $   |
|--------|-------|-----------|--------------|-------|---------|----------|----------|
| s15    | BTC   | DOWN      | oversold     |  3791 | 81.51% | $  +0.565 | $+2142.369 |
| s15    | BTC   | DOWN      | low_neutral  |   632 | 80.38% | $  +1.602 | $+1012.586 |
| s15    | BTC   | DOWN      | high_neutral |   241 | 76.35% | $  -2.141 | $-516.079 |
| s15    | BTC   | DOWN      | overbought   |   186 | 83.33% | $  +0.848 | $+157.789 |
| s15    | BTC   | DOWN      | ALL          |  4852 | 81.18% | $  +0.584 | $+2831.584 |
| s15    | BTC   | UP        | oversold     |   154 | 82.47% | $  -1.361 | $-209.655 |
| s15    | BTC   | UP        | low_neutral  |   251 | 80.48% | $  -1.353 | $-339.624 |
| s15    | BTC   | UP        | high_neutral |   663 | 81.75% | $  +1.097 | $+727.636 |
| s15    | BTC   | UP        | overbought   |  3697 | 82.04% | $  +1.097 | $+4054.960 |
| s15    | BTC   | UP        | ALL          |  4769 | 81.95% | $  +0.889 | $+4240.747 |
| s15    | ETH   | DOWN      | oversold     |  4652 | 80.50% | $  -0.010 | $ -46.431 |
| s15    | ETH   | DOWN      | low_neutral  |  1001 | 77.42% | $  -0.787 | $-787.568 |
| s15    | ETH   | DOWN      | high_neutral |   354 | 78.81% | $  -1.415 | $-500.925 |
| s15    | ETH   | DOWN      | overbought   |   206 | 82.52% | $  -0.564 | $-116.151 |
| s15    | ETH   | DOWN      | ALL          |  6220 | 80.00% | $  -0.228 | $-1419.318 |
| s15    | ETH   | UP        | oversold     |   186 | 85.48% | $  -1.604 | $-298.436 |
| s15    | ETH   | UP        | low_neutral  |   331 | 82.18% | $  +0.327 | $+108.359 |
| s15    | ETH   | UP        | high_neutral |   997 | 78.64% | $  -0.339 | $-337.739 |
| s15    | ETH   | UP        | overbought   |  4797 | 81.36% | $  +1.304 | $+6256.123 |
| s15    | ETH   | UP        | ALL          |  6316 | 81.08% | $  +0.899 | $+5678.965 |
| s15    | SOL   | DOWN      | oversold     |  3612 | 82.12% | $  -0.044 | $-158.238 |
| s15    | SOL   | DOWN      | low_neutral  |  1206 | 81.84% | $  -1.012 | $-1220.773 |
| s15    | SOL   | DOWN      | high_neutral |   421 | 83.85% | $  -0.977 | $-411.310 |
| s15    | SOL   | DOWN      | overbought   |   185 | 83.24% | $  -2.260 | $-418.009 |
| s15    | SOL   | DOWN      | ALL          |  5427 | 82.24% | $  -0.406 | $-2205.925 |
| s15    | SOL   | UP        | oversold     |   135 | 85.19% | $  -1.171 | $-158.050 |
| s15    | SOL   | UP        | low_neutral  |   388 | 81.96% | $  -2.060 | $-799.391 |
| s15    | SOL   | UP        | high_neutral |  1178 | 79.71% | $  -1.433 | $-1687.912 |
| s15    | SOL   | UP        | overbought   |  4032 | 80.95% | $  -0.310 | $-1250.010 |
| s15    | SOL   | UP        | ALL          |  5739 | 80.85% | $  -0.681 | $-3910.092 |
| s6     | BTC   | DOWN      | oversold     |  1619 | 73.38% | $  +2.449 | $+3964.442 |
| s6     | BTC   | DOWN      | low_neutral  |   245 | 64.49% | $ +18.552 | $+4545.206 |
| s6     | BTC   | DOWN      | high_neutral |   157 | 36.31% | $  -2.160 | $-339.064 |
| s6     | BTC   | DOWN      | overbought   |    17 | 17.65% | $  -5.467 | $ -92.944 |
| s6     | BTC   | DOWN      | ALL          |  2038 | 68.99% | $  +3.964 | $+8077.639 |
| s6     | BTC   | UP        | oversold     |    18 | 16.67% | $ -13.080 | $-235.438 |
| s6     | BTC   | UP        | low_neutral  |   170 | 35.29% | $  -7.151 | $-1215.645 |
| s6     | BTC   | UP        | high_neutral |   221 | 63.35% | $  +7.110 | $+1571.374 |
| s6     | BTC   | UP        | overbought   |  1583 | 78.65% | $  +2.492 | $+3944.363 |
| s6     | BTC   | UP        | ALL          |  1992 | 72.69% | $  +2.040 | $+4064.653 |
| s6     | ETH   | DOWN      | oversold     |  1736 | 71.49% | $  -1.097 | $-1904.902 |
| s6     | ETH   | DOWN      | low_neutral  |   366 | 59.56% | $  +4.405 | $+1612.156 |
| s6     | ETH   | DOWN      | high_neutral |   199 | 32.66% | $  -7.518 | $-1496.120 |
| s6     | ETH   | DOWN      | overbought   |    18 | 22.22% | $ -11.551 | $-207.915 |
| s6     | ETH   | DOWN      | ALL          |  2319 | 65.89% | $  -0.861 | $-1996.782 |
| s6     | ETH   | UP        | oversold     |    27 | 25.93% | $ -10.645 | $-287.416 |
| s6     | ETH   | UP        | low_neutral  |   180 | 36.11% | $  -3.804 | $-684.791 |
| s6     | ETH   | UP        | high_neutral |   304 | 66.45% | $  +3.706 | $+1126.508 |
| s6     | ETH   | UP        | overbought   |  1613 | 79.17% | $  +1.236 | $+1993.713 |
| s6     | ETH   | UP        | ALL          |  2124 | 73.02% | $  +1.011 | $+2148.014 |
| s6     | SOL   | DOWN      | oversold     |  1095 | 78.81% | $  +0.991 | $+1084.866 |
| s6     | SOL   | DOWN      | low_neutral  |   188 | 57.45% | $  -2.352 | $-442.217 |
| s6     | SOL   | DOWN      | high_neutral |   110 | 30.00% | $  -8.272 | $-909.967 |
| s6     | SOL   | DOWN      | overbought   |    13 |  7.69% | $ -20.637 | $-268.278 |
| s6     | SOL   | DOWN      | ALL          |  1406 | 71.48% | $  -0.381 | $-535.597 |
| s6     | SOL   | UP        | oversold     |    11 | 36.36% | $  +4.102 | $ +45.124 |
| s6     | SOL   | UP        | low_neutral  |    89 | 42.70% | $  -1.839 | $-163.712 |
| s6     | SOL   | UP        | high_neutral |   221 | 68.78% | $  +4.325 | $+955.827 |
| s6     | SOL   | UP        | overbought   |  1136 | 79.23% | $  +1.109 | $+1259.926 |
| s6     | SOL   | UP        | ALL          |  1457 | 75.09% | $  +1.439 | $+2097.165 |


## 2. Tier × asset × direction WR (Stoch 300s)

| source | asset | direction | tier         |     n |   WR    |   $/tr   |  sum $   |
|--------|-------|-----------|--------------|-------|---------|----------|----------|
| s15    | BTC   | DOWN      | oversold     |  3509 | 88.63% | $  +0.537 | $+1885.761 |
| s15    | BTC   | DOWN      | low_neutral  |   988 | 65.89% | $  +0.172 | $+170.415 |
| s15    | BTC   | DOWN      | high_neutral |   341 | 49.56% | $  +2.016 | $+687.364 |
| s15    | BTC   | DOWN      | overbought   |    12 | 58.33% | $  +4.427 | $ +53.125 |
| s15    | BTC   | DOWN      | ALL          |  4852 | 81.18% | $  +0.584 | $+2831.584 |
| s15    | BTC   | UP        | oversold     |     7 | 71.43% | $  +2.572 | $ +18.003 |
| s15    | BTC   | UP        | low_neutral  |   344 | 55.23% | $  +1.805 | $+621.006 |
| s15    | BTC   | UP        | high_neutral |   949 | 67.33% | $  +1.345 | $+1276.634 |
| s15    | BTC   | UP        | overbought   |  3460 | 88.58% | $  +0.668 | $+2310.572 |
| s15    | BTC   | UP        | ALL          |  4769 | 81.95% | $  +0.889 | $+4240.747 |
| s15    | ETH   | DOWN      | oversold     |  4259 | 88.19% | $  +0.247 | $+1050.017 |
| s15    | ETH   | DOWN      | low_neutral  |  1406 | 66.71% | $  -1.135 | $-1596.234 |
| s15    | ETH   | DOWN      | high_neutral |   530 | 50.38% | $  -1.533 | $-812.608 |
| s15    | ETH   | DOWN      | overbought   |    18 | 44.44% | $  -5.125 | $ -92.250 |
| s15    | ETH   | DOWN      | ALL          |  6220 | 80.00% | $  -0.228 | $-1419.318 |
| s15    | ETH   | UP        | oversold     |    23 | 69.57% | $  +6.786 | $+156.068 |
| s15    | ETH   | UP        | low_neutral  |   545 | 52.29% | $  +0.187 | $+102.071 |
| s15    | ETH   | UP        | high_neutral |  1444 | 68.84% | $  +2.333 | $+3368.157 |
| s15    | ETH   | UP        | overbought   |  4294 | 88.91% | $  +0.488 | $+2096.039 |
| s15    | ETH   | UP        | ALL          |  6316 | 81.08% | $  +0.899 | $+5678.965 |
| s15    | SOL   | DOWN      | oversold     |  3687 | 89.83% | $  +0.224 | $+826.933 |
| s15    | SOL   | DOWN      | low_neutral  |  1273 | 71.64% | $  -1.013 | $-1290.018 |
| s15    | SOL   | DOWN      | high_neutral |   455 | 50.77% | $  -3.946 | $-1795.253 |
| s15    | SOL   | DOWN      | overbought   |     9 | 55.56% | $  +5.556 | $ +50.008 |
| s15    | SOL   | DOWN      | ALL          |  5427 | 82.24% | $  -0.406 | $-2205.925 |
| s15    | SOL   | UP        | oversold     |    19 | 63.16% | $  +2.396 | $ +45.522 |
| s15    | SOL   | UP        | low_neutral  |   466 | 48.07% | $  -4.729 | $-2203.553 |
| s15    | SOL   | UP        | high_neutral |  1179 | 67.85% | $  -0.695 | $-818.915 |
| s15    | SOL   | UP        | overbought   |  4062 | 88.45% | $  -0.228 | $-926.916 |
| s15    | SOL   | UP        | ALL          |  5739 | 80.85% | $  -0.681 | $-3910.092 |
| s6     | BTC   | DOWN      | oversold     |  1263 | 77.83% | $  +2.673 | $+3376.028 |
| s6     | BTC   | DOWN      | low_neutral  |   340 | 58.53% | $  +0.078 | $ +26.365 |
| s6     | BTC   | DOWN      | high_neutral |   327 | 54.43% | $ +13.015 | $+4255.844 |
| s6     | BTC   | DOWN      | overbought   |   108 | 42.59% | $  +3.883 | $+419.402 |
| s6     | BTC   | DOWN      | ALL          |  2038 | 68.99% | $  +3.964 | $+8077.639 |
| s6     | BTC   | UP        | oversold     |    72 | 27.78% | $  -8.353 | $-601.426 |
| s6     | BTC   | UP        | low_neutral  |   369 | 52.57% | $  +2.077 | $+766.316 |
| s6     | BTC   | UP        | high_neutral |   344 | 71.51% | $  +3.821 | $+1314.329 |
| s6     | BTC   | UP        | overbought   |  1207 | 81.86% | $  +2.142 | $+2585.434 |
| s6     | BTC   | UP        | ALL          |  1992 | 72.69% | $  +2.040 | $+4064.653 |
| s6     | ETH   | DOWN      | oversold     |  1442 | 73.02% | $  -1.615 | $-2329.274 |
| s6     | ETH   | DOWN      | low_neutral  |   387 | 64.08% | $  +2.463 | $+953.193 |
| s6     | ETH   | DOWN      | high_neutral |   388 | 47.68% | $  -1.489 | $-577.821 |
| s6     | ETH   | DOWN      | overbought   |   102 | 41.18% | $  -0.420 | $ -42.880 |
| s6     | ETH   | DOWN      | ALL          |  2319 | 65.89% | $  -0.861 | $-1996.782 |
| s6     | ETH   | UP        | oversold     |    74 | 40.54% | $  +4.695 | $+347.451 |
| s6     | ETH   | UP        | low_neutral  |   359 | 50.70% | $  -1.935 | $-694.755 |
| s6     | ETH   | UP        | high_neutral |   378 | 67.46% | $  +1.998 | $+755.222 |
| s6     | ETH   | UP        | overbought   |  1313 | 82.56% | $  +1.325 | $+1740.097 |
| s6     | ETH   | UP        | ALL          |  2124 | 73.02% | $  +1.011 | $+2148.014 |
| s6     | SOL   | DOWN      | oversold     |   823 | 82.14% | $  +0.383 | $+315.378 |
| s6     | SOL   | DOWN      | low_neutral  |   279 | 68.10% | $  +0.897 | $+250.284 |
| s6     | SOL   | DOWN      | high_neutral |   249 | 51.00% | $  -2.106 | $-524.389 |
| s6     | SOL   | DOWN      | overbought   |    55 | 21.82% | $ -10.489 | $-576.870 |
| s6     | SOL   | DOWN      | ALL          |  1406 | 71.48% | $  -0.381 | $-535.597 |
| s6     | SOL   | UP        | oversold     |    46 | 43.48% | $  +5.741 | $+264.079 |
| s6     | SOL   | UP        | low_neutral  |   187 | 54.01% | $  +2.529 | $+472.920 |
| s6     | SOL   | UP        | high_neutral |   265 | 67.92% | $  +0.269 | $ +71.380 |
| s6     | SOL   | UP        | overbought   |   959 | 82.69% | $  +1.344 | $+1288.786 |
| s6     | SOL   | UP        | ALL          |  1457 | 75.09% | $  +1.439 | $+2097.165 |


---
## 3. H1 Exhaustion FADE (UP fires with stoch_k > 80)

If WR(UP|overbought) < WR(UP|baseline), the move IS exhausted → fade signal.
Fade WR ≈ 1 − actual WR (caveats: payout asymmetry from fees not modeled — informational only).

| source | stoch | asset | n   |  WR(ob)  |  WR(base)  |  ΔWR pp  |  Δ$/tr  | Fade WR (1−p) |
|--------|-------|-------|-----|----------|------------|----------|---------|---------------|
| s15 | stoch_k_300s  | BTC   | 3460 | 88.58% | 81.95% |  +6.64pp | $  -0.221 | 11.42% |
| s15 | stoch_k_300s  | ETH   | 4294 | 88.91% | 81.08% |  +7.83pp | $  -0.411 | 11.09% |
| s15 | stoch_k_300s  | SOL   | 4062 | 88.45% | 80.85% |  +7.60pp | $  +0.453 | 11.55% |
| s15 | stoch_k_60s   | BTC   | 3697 | 82.04% | 81.95% |  +0.09pp | $  +0.208 | 17.96% |
| s15 | stoch_k_60s   | ETH   | 4797 | 81.36% | 81.08% |  +0.28pp | $  +0.405 | 18.64% |
| s15 | stoch_k_60s   | SOL   | 4032 | 80.95% | 80.85% |  +0.10pp | $  +0.371 | 19.05% |
| s6 | stoch_k_300s  | BTC   | 1207 | 81.86% | 72.69% |  +9.17pp | $  +0.102 | 18.14% |
| s6 | stoch_k_300s  | ETH   | 1313 | 82.56% | 73.02% |  +9.54pp | $  +0.314 | 17.44% |
| s6 | stoch_k_300s  | SOL   |  959 | 82.69% | 75.09% |  +7.60pp | $  -0.095 | 17.31% |
| s6 | stoch_k_60s   | BTC   | 1583 | 78.65% | 72.69% |  +5.96pp | $  +0.451 | 21.35% |
| s6 | stoch_k_60s   | ETH   | 1613 | 79.17% | 73.02% |  +6.15pp | $  +0.225 | 20.83% |
| s6 | stoch_k_60s   | SOL   | 1136 | 79.23% | 75.09% |  +4.14pp | $  -0.330 | 20.77% |

> No UP-overbought cell shows WR<50% → **H1 not supported by data**: UP fires with overbought stoch still win >50% (fee-blind).


---
## 4. H3 Oversold BOUNCE (UP fires with stoch_k < 20)

| source | stoch | asset | n   |  WR(os)  |  WR(base)  |  ΔWR pp  |  Δ$/tr  |
|--------|-------|-------|-----|----------|------------|----------|---------|
| s15 | stoch_k_60s   | BTC   |  154 | 82.47% | 81.95% |  +0.52pp | $  -2.251 |
| s15 | stoch_k_60s   | ETH   |  186 | 85.48% | 81.08% |  +4.40pp | $  -2.504 |
| s15 | stoch_k_60s   | SOL   |  135 | 85.19% | 80.85% |  +4.33pp | $  -0.489 |
| s6 | stoch_k_300s  | BTC   |   72 | 27.78% | 72.69% | -44.91pp | $ -10.394 |
| s6 | stoch_k_300s  | ETH   |   74 | 40.54% | 73.02% | -32.48pp | $  +3.684 |
| s6 | stoch_k_300s  | SOL   |   46 | 43.48% | 75.09% | -31.61pp | $  +4.301 |


---
## 5. H4 K/D Crossover confluence with bet direction

Confluence = (UP & k>d) OR (DOWN & k<d). WR(conf=yes) vs WR(conf=no).

| source | stoch | asset | dir   | n(yes) | WR(yes) | n(no)  | WR(no) | ΔWR pp | Δ$/tr |
|--------|-------|-------|-------|--------|---------|--------|--------|--------|-------|
| s6 | stoch_k_300s  | SOL   | UP    |  1000  | 72.80% |   457  | 80.09% | -7.29pp | $  +2.520 |
| s6 | stoch_k_60s   | SOL   | DOWN  |  1075  | 70.05% |   331  | 76.13% | -6.09pp | $  +2.187 |
| s15 | stoch_k_60s   | BTC   | DOWN  |  2684  | 81.89% |  2168  | 80.30% | +1.59pp | $  +1.826 |
| s15 | stoch_k_300s  | BTC   | DOWN  |  3084  | 80.54% |  1768  | 82.30% | -1.75pp | $  +1.612 |
| s6 | stoch_k_300s  | SOL   | DOWN  |  1153  | 69.90% |   253  | 78.66% | -8.75pp | $  +1.570 |
| s6 | stoch_k_60s   | SOL   | UP    |   811  | 71.39% |   646  | 79.72% | -8.33pp | $  +1.289 |
| s15 | stoch_k_300s  | BTC   | UP    |  2390  | 79.83% |  2379  | 84.07% | -4.24pp | $  +1.166 |
| s15 | stoch_k_300s  | ETH   | DOWN  |  4109  | 79.44% |  2111  | 81.10% | -1.66pp | $  +0.861 |
| s15 | stoch_k_60s   | ETH   | DOWN  |  3618  | 79.93% |  2602  | 80.09% | -0.16pp | $  +0.857 |
| s15 | stoch_k_300s  | SOL   | DOWN  |  3829  | 81.41% |  1598  | 84.23% | -2.83pp | $  +0.662 |
| s15 | stoch_k_60s   | SOL   | DOWN  |  3591  | 81.65% |  1836  | 83.39% | -1.74pp | $  +0.651 |
| s6 | stoch_k_300s  | ETH   | UP    |  1537  | 70.27% |   587  | 80.24% | -9.97pp | $  +0.592 |
| s15 | stoch_k_300s  | SOL   | UP    |  2432  | 78.00% |  3307  | 82.95% | -4.94pp | $  +0.545 |
| s15 | stoch_k_300s  | ETH   | UP    |  3107  | 78.24% |  3209  | 83.83% | -5.58pp | $  +0.355 |
| s6 | stoch_k_60s   | ETH   | DOWN  |  1611  | 62.01% |   708  | 74.72% | -12.71pp | $  +0.280 |
| s15 | stoch_k_60s   | BTC   | UP    |  1971  | 81.13% |  2798  | 82.52% | -1.40pp | $  +0.081 |
| s15 | stoch_k_60s   | ETH   | UP    |  2472  | 79.94% |  3844  | 81.82% | -1.88pp | $  -0.003 |
| s6 | stoch_k_300s  | ETH   | DOWN  |  1791  | 62.42% |   528  | 77.65% | -15.23pp | $  -0.192 |
| s6 | stoch_k_300s  | BTC   | DOWN  |  1632  | 65.99% |   406  | 81.03% | -15.04pp | $  -0.197 |
| s15 | stoch_k_60s   | SOL   | UP    |  2023  | 79.54% |  3716  | 81.57% | -2.03pp | $  -0.335 |
| s6 | stoch_k_60s   | ETH   | UP    |  1344  | 68.45% |   780  | 80.90% | -12.45pp | $  -1.017 |
| s6 | stoch_k_60s   | BTC   | DOWN  |  1488  | 64.99% |   550  | 79.82% | -14.83pp | $  -1.171 |
| s6 | stoch_k_300s  | BTC   | UP    |  1474  | 68.93% |   518  | 83.40% | -14.47pp | $  -2.318 |
| s6 | stoch_k_60s   | BTC   | UP    |  1303  | 67.00% |   689  | 83.45% | -16.46pp | $  -2.919 |


---
## 6. Composite gate: both 60s and 300s k/d agree with bet AND both neutral (20-80)

| source | asset | n(base) | WR(base) | $/tr(base) | n(agree) | WR(agree) | $/tr(agree) | n(comp) | WR(comp) | $/tr(comp) | Δ$/tr vs base |
|--------|-------|---------|----------|------------|----------|-----------|-------------|---------|----------|------------|---------------|
| s15 | ALL   |  33323  | 81.17% | $  +0.157 |  15959   | 80.73% | $  +0.385  |  1548   | 66.02% | $  -0.383 | $  -0.540 |
| s15 | BTC   |   9621  | 81.56% | $  +0.735 |   4539   | 81.67% | $  +1.244  |   342   | 69.59% | $  +4.586 | $  +3.851 |
| s15 | ETH   |  12536  | 80.54% | $  +0.340 |   5926   | 79.89% | $  +0.473  |   575   | 62.78% | $  -1.311 | $  -1.651 |
| s15 | SOL   |  11166  | 81.52% | $  -0.548 |   5494   | 80.85% | $  -0.420  |   631   | 67.04% | $  -2.231 | $  -1.683 |
| s6 | ALL   |  11336  | 70.85% | $  +1.222 |   7542   | 66.73% | $  +1.080  |  1411   | 48.05% | $  +2.514 | $  +1.291 |
| s6 | BTC   |   4030  | 70.82% | $  +3.013 |   2754   | 65.90% | $  +2.391  |   489   | 48.88% | $  +7.998 | $  +4.985 |
| s6 | ETH   |   4443  | 69.30% | $  +0.034 |   2923   | 64.97% | $  -0.111  |   608   | 48.03% | $  -0.092 | $  -0.126 |
| s6 | SOL   |   2863  | 73.31% | $  +0.545 |   1865   | 70.72% | $  +1.009  |   314   | 46.82% | $  -0.981 | $  -1.527 |


---
## 7. Top 10 stoch-gated configurations by $/tr (n≥80)

Bottom rows = configurations to avoid (lowest $/tr).

| rank | source | gate                                                                  |    n  |   WR    |   $/tr   |   sum $   |
|------|--------|-----------------------------------------------------------------------|-------|---------|----------|-----------|
|    1 | s6     | `k60_tier=low_neutral|asset=BTC|dir=DOWN                          ` |   245 | 64.49% | $ +18.552 | $+4545.206 |
|    2 | s6     | `k300_tier=high_neutral|asset=BTC|dir=DOWN                        ` |   327 | 54.43% | $ +13.015 | $+4255.844 |
|    3 | s6     | `high_neutral_rising|asset=BTC|dir=UP                             ` |   184 | 61.96% | $  +8.627 | $+1587.376 |
|    4 | s6     | `k60_tier=high_neutral|asset=BTC|dir=UP                           ` |   221 | 63.35% | $  +7.110 | $+1571.374 |
|    5 | s6     | `high_neutral_rising|asset=SOL|dir=UP                             ` |   168 | 64.29% | $  +5.513 | $+926.249 |
|    6 | s6     | `k60>d60=True|asset=BTC|dir=DOWN|agrees=False                     ` |   550 | 79.82% | $  +4.818 | $+2650.171 |
|    7 | s6     | `both_agree=False|asset=BTC|dir=DOWN                              ` |   560 | 79.11% | $  +4.582 | $+2565.745 |
|    8 | s6     | `k60_tier=low_neutral|asset=ETH|dir=DOWN                          ` |   366 | 59.56% | $  +4.405 | $+1612.156 |
|    9 | s6     | `k60_tier=high_neutral|asset=SOL|dir=UP                           ` |   221 | 68.78% | $  +4.325 | $+955.827 |
|   10 | s6     | `both_agree=False|asset=BTC|dir=UP                                ` |   716 | 83.24% | $  +4.177 | $+2990.557 |

**Bottom 5 (worst $/tr) — fade candidates:**

| source | gate                                                                  |    n  |   WR    |   $/tr   |
|--------|-----------------------------------------------------------------------|-------|---------|----------|
| s6     | `k60_tier=high_neutral|asset=SOL|dir=DOWN                         ` |   110 | 30.00% | $  -8.272 |
| s6     | `k60_tier=high_neutral|asset=ETH|dir=DOWN                         ` |   199 | 32.66% | $  -7.518 |
| s6     | `k60_tier=low_neutral|asset=BTC|dir=UP                            ` |   170 | 35.29% | $  -7.151 |
| s15    | `k300_tier=low_neutral|asset=SOL|dir=UP                           ` |   466 | 48.07% | $  -4.729 |
| s15    | `k300_tier=high_neutral|asset=SOL|dir=DOWN                        ` |   455 | 50.77% | $  -3.946 |


---
## 8. Stoch 60s vs 300s — which window predicts better?

Per-cell composite of H1/H3/H4 by stoch window (median Δ$/tr):

| window      | H1 (UP ob)  | H3 (UP os)  | H4 (kd agree) |
|-------------|-------------|-------------|---------------|
| stoch_k_60s |      +0.298 |      -2.251 |        +0.180 |
| stoch_k_300s |      +0.003 |      +3.684 |        +0.627 |


---
## 9. Actionable conclusions

- **s6/BTC**: composite gate (both windows agree + both neutral) lifts $/tr from `+3.013` (n=4030) to `+7.998` (n=489) — Δ=`+4.985`.
- **s15/BTC**: composite gate (both windows agree + both neutral) lifts $/tr from `+0.735` (n=9621) to `+4.586` (n=342) — Δ=`+3.851`.
- **s6/ALL**: composite gate (both windows agree + both neutral) lifts $/tr from `+1.222` (n=11336) to `+2.514` (n=1411) — Δ=`+1.291`.
- **s15/BTC** UP+overbought stoch_k_300s: WR=88.58% n=3460 ($/tr=`+0.668` vs baseline `+0.889`, Δ=`-0.221`) — **avoid** these UP fires (or test contrarian DOWN bet).
- **s15/ETH** UP+overbought stoch_k_300s: WR=88.91% n=4294 ($/tr=`+0.488` vs baseline `+0.899`, Δ=`-0.411`) — **avoid** these UP fires (or test contrarian DOWN bet).
- **s6/SOL** UP+overbought stoch_k_60s: WR=79.23% n=1136 ($/tr=`+1.109` vs baseline `+1.439`, Δ=`-0.330`) — **avoid** these UP fires (or test contrarian DOWN bet).
- **s6/SOL/UP** with K/D agreement (stoch_k_300s): WR=72.80% vs 80.09% (Δ=-7.29pp, Δ$/tr=+2.520, n=1000).
- **s6/SOL/DOWN** with K/D agreement (stoch_k_60s): WR=70.05% vs 76.13% (Δ=-6.09pp, Δ$/tr=+2.187, n=1075).
- **s15/BTC/DOWN** with K/D agreement (stoch_k_60s): WR=81.89% vs 80.30% (Δ=+1.59pp, Δ$/tr=+1.826, n=2684).
- **s15/BTC/DOWN** with K/D agreement (stoch_k_300s): WR=80.54% vs 82.30% (Δ=-1.75pp, Δ$/tr=+1.612, n=3084).
- **s6/SOL/DOWN** with K/D agreement (stoch_k_300s): WR=69.90% vs 78.66% (Δ=-8.75pp, Δ$/tr=+1.570, n=1153).


### Caveat: H4 winners with NEGATIVE ΔWR

Several H4 cells show Δ$/tr > 0 but ΔWR < 0. This is because the disagreement set contains larger negative-$/tr losers (e.g., UP overbought with tiny upside vs DOWN agreement on very-low priced legs). The crossover gate filters to higher-priced legs with smaller per-trade payouts — so WR drops but expected $/tr improves. Treat H4 as a **risk-adjusted filter**, not a pure WR booster.


---
## 10. Method notes

- Fee model: legacy 2%-on-profit (only winning leg pays). Matches current Polymarket production billing on BTC/ETH/SOL up-down markets.
- TA snapshots are taken at `ts_us` (the fire bar). H2 (k crossing UP through 50) is approximated as `stoch_k > 50 AND stoch_k > stoch_d`; the underlying parquet does NOT carry per-bar history so a strict 'crossed up within last 5-10 bars' lookback isn't reconstructable here — caveat noted.
- Wilson 95% intervals are NOT printed in tables for brevity; recompute from n + WR if needed.
- Output CSV: `data/v4/canonical/_results/slow_stoch_overlay.csv`.
