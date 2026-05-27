# Wave 2 PERP — Family B (mean-reversion) results

_Generated 2026-05-26T19:05:07.418061+00:00_

## TL;DR

Mean-reversion **does not generalize** as a perp-native strategy on crypto majors
+ alts over 2020-2026, regardless of variant (RSI extreme, BB reversal, Z-score,
SMS reclaim, VWAP deviation). 5/90 cells are profitable (5.6%); median OOS Sharpe
across families is negative (B5 worst at -3.15, B4 best at -0.24). Buy-and-hold
crushes every variant on every asset (e.g. BNB +43.5x total, DOGE +52x, SOL
+24x; best MR cell B1_LINK_4h = +$330 over 6 years on $250 notional).

Mean-reversion logic that worked on Polymarket binary momo (signal flip wins
the 2-min window) gets eaten by ATR-stops once the underlying is allowed to
trend. The thesis "indicator fires extreme → reverts to mean" is wrong:
extremes tend to *continue* on crypto futures and SL stops out before TP.

**Best per family** (n≥30, by OOS Sharpe):
- B1 (RSI): TON 4h — sharpe +1.29, OOS +3.93 but only n=42, fragile
- B2 (BB): LINK 4h — sharpe +0.55, OOS +0.79, n=882 (most credible MR cell)
- B3 (Z-score): XRP 4h — sharpe +0.42, OOS +0.94, n=698
- B4 (SMS reclaim): ETH 4h — sharpe +0.09, OOS +0.48, n=2195
- B5 (VWAP): no cells with sharpe > 0 at n≥30

**Family ranking by OOS Sharpe median**: B4 > B3 > B2 > B1 > B5.
B4 (sweep+RSI confluence) is the only family approaching breakeven — and
only because the regime gate filters out the trending periods where pure MR fails.
B5 (intraday VWAP) is unambiguously the worst; high-freq + tight SL = fee bleed.

**Promotion candidates**: B2_LINK_4h, B3_XRP_4h, B4_ETH_4h are the only cells
worth a paper-deploy probe. None are deploy-ready: all have OOS PF < 1.1 and
positive sharpe driven by a small late-window bias rather than a robust edge.

Total cells: **90**


## Summary by variant

| variant   |   cells |   n50 |   total_pnl |   med_sharpe |   med_oos_sharpe |   med_calmar |   med_pf |
|:----------|--------:|------:|------------:|-------------:|-----------------:|-------------:|---------:|
| B1        |      27 |    21 |    -9260.89 |       -2.271 |           -2.451 |       -0.761 |    0.785 |
| B2        |      22 |    22 |   -16198    |       -1.192 |           -1.818 |       -0.817 |    0.885 |
| B3        |      27 |    26 |   -17610.6  |       -1.427 |           -1.219 |       -0.779 |    0.885 |
| B4        |       3 |     3 |    -1227.08 |       -0.423 |           -0.235 |       -0.393 |    0.937 |
| B5        |      11 |    11 |    -6214.49 |       -3.198 |           -3.148 |       -0.742 |    0.818 |



## Top-10 by OOS annualized Sharpe (n>=30)

| strategy_id   |   n_trades |   win_rate |   avg_pnl_usd |   total_pnl_usd |   sharpe_ann |   oos_sharpe |   calmar |   profit_factor |   max_dd_usd |   avg_bars_held |
|:--------------|-----------:|-----------:|--------------:|----------------:|-------------:|-------------:|---------:|----------------:|-------------:|----------------:|
| B1_TON_4h     |         42 |      0.476 |         0.901 |          37.831 |        1.288 |        3.928 |    0.36  |           1.154 |     -105.008 |           4.667 |
| B1_LINK_4h    |        183 |      0.492 |         1.806 |         330.497 |        1.857 |        2.394 |    1.73  |           1.288 |     -191.029 |           6.53  |
| B1_SOL_4h     |        181 |      0.425 |        -1.957 |        -354.236 |       -2.061 |        1.529 |   -0.548 |           0.771 |     -646.957 |           6.16  |
| B3_XRP_4h     |        698 |      0.458 |         0.381 |         265.702 |        0.424 |        0.938 |    0.741 |           1.071 |     -358.481 |           9.06  |
| B3_SOL_1h     |       2847 |      0.457 |        -0.073 |        -206.913 |       -0.264 |        0.788 |   -0.204 |           0.98  |    -1015.84  |           8.223 |
| B2_LINK_4h    |        882 |      0.501 |         0.415 |         365.676 |        0.55  |        0.788 |    0.786 |           1.074 |     -465.532 |           6.407 |
| B1_ADA_4h     |        187 |      0.406 |        -1.947 |        -364     |       -2.463 |        0.761 |   -0.761 |           0.735 |     -478.302 |           5.749 |
| B2_SOL_4h     |        777 |      0.49  |        -0.176 |        -136.745 |       -0.209 |        0.687 |   -0.206 |           0.973 |     -663.293 |           6.346 |
| B5_SUI_1h     |        744 |      0.542 |        -0.061 |         -45.676 |       -0.397 |        0.488 |   -0.181 |           0.977 |     -251.88  |           4.526 |
| B4_ETH_4h     |       2195 |      0.328 |         0.07  |         152.926 |        0.089 |        0.482 |    0.193 |           1.014 |     -793.31  |           7.243 |



## Buy-and-hold benchmark (per asset)

| asset   | first      | last       |   ret_total |   ret_ann |
|:--------|:-----------|:-----------|------------:|----------:|
| BTC     | 2020-01-01 | 2026-03-31 |       8.483 |     1.357 |
| ETH     | 2020-01-01 | 2026-03-31 |      15.1   |     2.416 |
| SOL     | 2020-08-11 | 2026-03-31 |      24.224 |     4.296 |
| AVAX    | 2020-09-22 | 2026-04-30 |       0.851 |     0.152 |
| LINK    | 2020-01-01 | 2026-04-30 |       4.08  |     0.644 |
| BNB     | 2020-01-01 | 2026-04-30 |      43.538 |     6.876 |
| ADA     | 2020-01-01 | 2026-04-30 |       6.457 |     1.02  |
| DOGE    | 2020-01-01 | 2026-04-30 |      51.993 |     8.212 |
| XRP     | 2020-01-01 | 2026-04-30 |       6.052 |     0.956 |
| SUI     | 2023-05-03 | 2026-03-31 |      -0.373 |    -0.128 |
| TON     | 2024-08-08 | 2026-03-31 |      -0.804 |    -0.489 |



## Worst-10 by total PnL

| strategy_id   |   n_trades |   win_rate |   total_pnl_usd |   sharpe_ann |   max_dd_usd |
|:--------------|-----------:|-----------:|----------------:|-------------:|-------------:|
| B2_DOGE_1h    |       3448 |      0.495 |        -2063.14 |       -2.715 |     -2244.59 |
| B3_AVAX_4h    |        718 |      0.368 |        -1797.3  |       -2.432 |     -2030.44 |
| B2_ETH_1h     |       4579 |      0.487 |        -1628.23 |       -1.898 |     -2075.59 |
| B2_XRP_1h     |       3438 |      0.502 |        -1546.83 |       -2.562 |     -1690.35 |
| B3_AVAX_1h    |       2751 |      0.426 |        -1487.35 |       -2.021 |     -1785.69 |
| B3_ETH_1h     |       3806 |      0.441 |        -1461.02 |       -1.547 |     -1829.35 |
| B2_AVAX_1h    |       3075 |      0.474 |        -1396.37 |       -2.068 |     -1762.38 |
| B5_ETH_1h     |       2185 |      0.47  |        -1289.37 |       -3.367 |     -1737.67 |
| B3_BNB_1h     |       2957 |      0.432 |        -1253.22 |       -2.223 |     -1401.26 |
| B3_LINK_1h    |       3168 |      0.434 |        -1217.56 |       -1.564 |     -1562.08 |



## Best cell per variant (by OOS Sharpe, n>=30 fallback to n>=10)

- **B1**: TON 4h — n=42 wr=0.48 pnl=$+38 sharpe=+1.29 oos_sharpe=+3.93 calmar=+0.36

- **B2**: LINK 4h — n=882 wr=0.50 pnl=$+366 sharpe=+0.55 oos_sharpe=+0.79 calmar=+0.79

- **B3**: XRP 4h — n=698 wr=0.46 pnl=$+266 sharpe=+0.42 oos_sharpe=+0.94 calmar=+0.74

- **B4**: ETH 4h — n=2195 wr=0.33 pnl=$+153 sharpe=+0.09 oos_sharpe=+0.48 calmar=+0.19

- **B5**: SUI 1h — n=744 wr=0.54 pnl=$-46 sharpe=-0.40 oos_sharpe=+0.49 calmar=-0.18


## Family generalization

| variant   |   med_sharpe |   med_oos |   pct_pos |
|:----------|-------------:|----------:|----------:|
| B1        |       -2.271 |    -2.451 |     0.148 |
| B2        |       -1.192 |    -1.818 |     0.045 |
| B3        |       -1.427 |    -1.219 |     0.111 |
| B4        |       -0.423 |    -0.235 |     0.333 |
| B5        |       -3.198 |    -3.148 |     0     |

