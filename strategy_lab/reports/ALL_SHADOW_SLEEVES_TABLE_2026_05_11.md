# All Shadow Sleeves — Comprehensive Per-Sleeve Table

**Pulled:** 2026-05-11 ~07:00 UTC
**Source:** `trading.events` on VPS3 (storedata), last 14d
**Mode:** paper / shadow

## Summary

- **65 active sleeves** (3 defunct `volume_*` and `system` excluded)
- **8 families** running concurrently
- Total: **7,813 fires** → 4,565 resolved → 2,338 wins → **WR 51.22%**
- **Total PnL: -$1,278.87**  |  **pnl/trade: -$0.28**
- 575 hedge fires, 59 sell fires, 425 hedge skips

## Per-sleeve individual table

| sleeve | family | hrs | fires | fire% | resolved | wins | losses | WR% | pnl$ | pnl/tr$ | entry | qty | hedge_n | sell_n | p_sell | skip |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| btc_5m_momo_HEDGE        | momo_v1 | 101.66 | 120 | 9.93   | 99  | 47  | 52  | 47.47 | -113.78 | -1.15  | 0.4998 | 50.23 | 9  | 0  | 0 | 18 |
| btc_5m_momo_HOLD         | momo_v1 | 101.66 | 110 | 9.18   | 99  | 47  | 52  | 47.47 | -137.77 | -1.39  | 0.4998 | 50.23 | 0  | 0  | 0 | 0  |
| btc_5m_momo_SELL         | momo_v1 | 101.66 | 119 | 9.86   | 100 | 47  | 53  | 47.00 | -124.73 | -1.25  | 0.4997 | 50.24 | 0  | 7  | 0 | 18 |
| btc_15m_momo_HEDGE       | momo_v1 | 100.97 | 44  | 10.97  | 21  | 15  | 6   | **71.43** | +162.13 | +7.72  | 0.4924 | 50.90 | 5  | 0  | 0 | 3  |
| btc_15m_momo_HOLD        | momo_v1 | 100.97 | 39  | 9.85   | 21  | 15  | 6   | **71.43** | **+225.34** | **+10.73** | 0.4924 | 50.90 | 0  | 0  | 0 | 0  |
| btc_15m_momo_SELL        | momo_v1 | 100.97 | 43  | 10.75  | 21  | 14  | 7   | 66.67 | +192.49 | +9.17  | 0.4924 | 50.90 | 0  | 4  | 0 | 3  |
| eth_5m_momo_HEDGE        | momo_v1 | 101.66 | 126 | 10.45  | 66  | 30  | 36  | 45.45 | -165.31 | -2.50  | 0.5007 | 50.44 | 7  | 0  | 0 | 7  |
| eth_5m_momo_HOLD         | momo_v1 | 101.66 | 118 | 9.85   | 66  | 30  | 36  | 45.45 | -171.74 | -2.60  | 0.5007 | 50.44 | 0  | 0  | 0 | 0  |
| eth_5m_momo_SELL         | momo_v1 | 101.66 | 124 | 10.30  | 67  | 29  | 38  | 43.28 | -173.06 | -2.58  | 0.5007 | 50.45 | 0  | 6  | 0 | 6  |
| eth_15m_momo_HEDGE       | momo_v1 | 100.97 | 46  | 11.44  | 17  | 10  | 7   | 58.82 | -3.51   | -0.21  | 0.4972 | 50.52 | 5  | 0  | 0 | 4  |
| eth_15m_momo_HOLD        | momo_v1 | 100.97 | 40  | 10.10  | 17  | 10  | 7   | 58.82 | +75.62  | +4.45  | 0.4972 | 50.52 | 0  | 0  | 0 | 0  |
| eth_15m_momo_SELL        | momo_v1 | 100.97 | 46  | 11.44  | 17  | 9   | 8   | 52.94 | +36.64  | +2.16  | 0.4972 | 50.52 | 0  | 4  | 1 | 4  |
| sol_5m_momo_HEDGE        | momo_v1 | 101.66 | 210 | 17.38  | 100 | 56  | 44  | 56.00 | **+267.65** | **+2.68** | 0.5138 | 49.61 | 10 | 0  | 0 | 22 |
| sol_5m_momo_HOLD         | momo_v1 | 101.66 | 200 | 16.69  | 100 | 56  | 44  | 56.00 | +199.64 | +2.00  | 0.5138 | 49.61 | 0  | 0  | 0 | 0  |
| sol_5m_momo_SELL         | momo_v1 | 101.66 | 208 | 17.25  | 100 | 56  | 44  | 56.00 | +241.46 | +2.41  | 0.5138 | 49.61 | 0  | 1  | 7 | 21 |
| sol_15m_momo_HEDGE       | momo_v1 | 100.97 | 73  | 18.20  | 20  | 6   | 14  | **30.00** | **-265.23** | **-13.26** | 0.5229 | 48.95 | 5  | 0  | 0 | 5  |
| sol_15m_momo_HOLD        | momo_v1 | 100.97 | 68  | 17.17  | 20  | 6   | 14  | 30.00 | -223.37 | -11.17 | 0.5229 | 48.95 | 0  | 0  | 0 | 0  |
| sol_15m_momo_SELL        | momo_v1 | 100.97 | 71  | 17.79  | 20  | 6   | 14  | 30.00 | -248.07 | -12.40 | 0.5229 | 48.95 | 0  | 0  | 3 | 5  |
| btc_5m_momo_v2_HEDGE     | momo_v2 | 89.06  | 117 | 10.92  | 86  | 45  | 41  | 52.33 | -50.25  | -0.58  | 0.5018 | 49.90 | 17 | 0  | 0 | 5  |
| btc_5m_momo_v2_HOLD      | momo_v2 | 89.06  | 98  | 9.32   | 86  | 45  | 41  | 52.33 | +70.05  | +0.81  | 0.5018 | 49.90 | 0  | 0  | 0 | 0  |
| btc_5m_momo_v2_SELL      | momo_v2 | 89.06  | 117 | 10.92  | 88  | 40  | 48  | 45.45 | -7.04   | -0.08  | 0.5015 | 49.93 | 0  | 17 | 0 | 4  |
| btc_15m_momo_v2_HEDGE    | momo_v2 | 88.86  | 42  | 11.83  | 26  | 15  | 11  | 57.69 | +70.29  | +2.70  | 0.5023 | 50.11 | 5  | 0  | 0 | 5  |
| btc_15m_momo_v2_HOLD     | momo_v2 | 88.86  | 37  | 10.57  | 26  | 15  | 11  | 57.69 | +92.26  | +3.55  | 0.5023 | 50.11 | 0  | 0  | 0 | 0  |
| btc_15m_momo_v2_SELL     | momo_v2 | 88.86  | 40  | 11.33  | 26  | 15  | 11  | 57.69 | +71.88  | +2.76  | 0.5023 | 50.11 | 0  | 3  | 0 | 5  |
| eth_5m_momo_v2_HEDGE     | momo_v2 | 89.06  | 111 | 10.36  | 63  | 33  | 30  | 52.38 | -47.66  | -0.76  | 0.5055 | 50.03 | 18 | 0  | 0 | 7  |
| eth_5m_momo_v2_HOLD      | momo_v2 | 89.06  | 92  | 8.75   | 63  | 33  | 30  | 52.38 | +38.18  | +0.61  | 0.5055 | 50.03 | 0  | 0  | 0 | 0  |
| eth_5m_momo_v2_SELL      | momo_v2 | 89.06  | 108 | 10.11  | 64  | 29  | 35  | 45.31 | +68.74  | +1.07  | 0.5054 | 50.03 | 0  | 12 | 3 | 7  |
| eth_15m_momo_v2_HEDGE    | momo_v2 | 88.86  | 30  | 8.50   | 18  | 12  | 6   | 66.67 | +64.08  | +3.56  | 0.5081 | 49.46 | 3  | 0  | 0 | 6  |
| eth_15m_momo_v2_HOLD     | momo_v2 | 88.86  | 27  | 7.71   | 18  | 12  | 6   | 66.67 | +135.26 | **+7.51** | 0.5081 | 49.46 | 0  | 0  | 0 | 0  |
| eth_15m_momo_v2_SELL     | momo_v2 | 88.86  | 27  | 7.71   | 18  | 12  | 6   | 66.67 | +135.26 | +7.51  | 0.5081 | 49.46 | 0  | 0  | 0 | 6  |
| sol_5m_momo_v2_HEDGE     | momo_v2 | 89.06  | 144 | 13.50  | 63  | 34  | 29  | 53.97 | +11.97  | +0.19  | 0.5123 | 49.66 | 15 | 0  | 0 | 4  |
| sol_5m_momo_v2_HOLD      | momo_v2 | 89.06  | 129 | 12.26  | 63  | 34  | 29  | 53.97 | +71.13  | +1.13  | 0.5123 | 49.66 | 0  | 0  | 0 | 0  |
| sol_5m_momo_v2_SELL      | momo_v2 | 89.06  | 137 | 12.92  | 63  | 32  | 31  | 50.79 | +76.26  | +1.21  | 0.5123 | 49.66 | 0  | 4  | 4 | 4  |
| sol_15m_momo_v2_HEDGE    | momo_v2 | 88.86  | 41  | 11.55  | 16  | 10  | 6   | 62.50 | -0.54   | -0.03  | 0.5216 | 49.54 | 5  | 0  | 0 | 3  |
| sol_15m_momo_v2_HOLD     | momo_v2 | 88.86  | 36  | 10.29  | 16  | 10  | 6   | 62.50 | +75.55  | +4.72  | 0.5216 | 49.54 | 0  | 0  | 0 | 0  |
| sol_15m_momo_v2_SELL     | momo_v2 | 88.86  | 38  | 10.80  | 16  | 10  | 6   | 62.50 | +94.74  | +5.92  | 0.5216 | 49.54 | 0  | 1  | 1 | 3  |
| btc_5m_sniper            | sniper  | 101.83 | 156 | 12.47  | 99  | 52  | 47  | 52.53 | -83.13  | -0.84  | 0.5011 | 50.03 | 45 | 0  | 0 | 14 |
| btc_15m_sniper           | sniper  | 101.47 | 117 | 26.77  | 74  | 38  | 36  | 51.35 | -13.33  | -0.18  | 0.5016 | 50.03 | 36 | 0  | 0 | 25 |
| eth_5m_sniper            | sniper  | 101.83 | 148 | 11.89  | 96  | 42  | 54  | 43.75 | **-391.57** | **-4.08** | 0.5014 | 50.42 | 39 | 0  | 0 | 19 |
| eth_15m_sniper           | sniper  | 101.47 | 107 | 24.77  | 69  | 41  | 28  | 59.42 | +14.53  | +0.21  | 0.5096 | 49.44 | 31 | 0  | 0 | 18 |
| sol_5m_sniper            | sniper  | 101.83 | 285 | 22.27  | 197 | 88  | 109 | 44.67 | **-434.52** | **-2.21** | 0.5159 | 49.45 | 73 | 0  | 0 | 50 |
| sol_15m_sniper           | sniper  | 101.47 | 166 | 37.05  | 110 | 54  | 56  | 49.09 | -238.27 | -2.17  | 0.5234 | 48.86 | 46 | 0  | 0 | 32 |
| sol_5m_sniper_INV        | sniper_INV       | 101.74 | 208 | **100.00** | 197 | 109 | 88  | 55.33 | **+207.20** | **+1.05** | 0.5251 | 48.26 | 0  | 0  | 0 | 0  |
| eth_5m_sniper_DOWN_INV   | sniper_DOWN_INV  | 101.66 | 53  | **100.00** | 49  | 29  | 20  | 59.18 | **+136.07** | **+2.78** | 0.5311 | 47.65 | 0  | 0  | 0 | 0  |
| btc_5m_v3                | v3 | 101.83 | 128 | 10.47  | 34 | 22 | 12 | 64.71 | +123.99 | **+3.65** | 0.5152 | 48.58 | 19 | 0  | 0 | 0  |
| eth_5m_v3                | v3 | 101.83 | 50  | 4.16   | 4  | 2  | 2  | 50.00 | -3.91   | -0.98  | 0.5150 | 49.02 | 0  | 0  | 0 | 1  |
| sol_5m_v3                | v3 | 101.83 | 204 | 16.56  | 67 | 33 | 34 | 49.25 | -78.34  | -1.17  | 0.5050 | 50.87 | 29 | 0  | 0 | 22 |
| btc_5m_v3_1              | v3_1 | 101.83 | 123 | 10.10  | 27 | 17 | 10 | 62.96 | +92.77  | +3.44  | 0.5129 | 48.78 | 14 | 0  | 0 | 0  |
| eth_5m_v3_1              | v3_1 | 101.83 | 39  | 3.24   | 2  | 1  | 1  | 50.00 | -2.09   | -1.05  | 0.5164 | 49.02 | 0  | 0  | 0 | 0  |
| sol_5m_v3_1              | v3_1 | 101.83 | 168 | 13.66  | 58 | 28 | 30 | 48.28 | -41.60  | -0.72  | 0.5045 | 50.88 | 27 | 0  | 0 | 15 |
| btc_5m_v3_2              | v3_2 | 101.83 | 122 | 10.02  | 19 | 11 | 8  | 57.89 | +19.27  | +1.01  | 0.5121 | 48.82 | 13 | 0  | 0 | 0  |
| eth_5m_v3_2              | v3_2 | 101.83 | 50  | 4.16   | 1  | 1  | 0  | 100.00 | +23.54  | +23.54 *(n=1)* | 0.5100 | 49.02 | 0  | 0  | 0 | 1  |
| sol_5m_v3_2              | v3_2 | 101.83 | 318 | 25.77  | 77 | 39 | 38 | 50.65 | -61.64  | -0.80  | 0.5067 | 50.56 | 30 | 0  | 0 | 22 |
| btc_5m_v3_3              | v3_3 | 101.83 | 122 | 10.02  | 19 | 11 | 8  | 57.89 | +19.27  | +1.01  | 0.5121 | 48.82 | 13 | 0  | 0 | 0  |
| eth_5m_v3_3              | v3_3 | 101.83 | 50  | 4.16   | 1  | 1  | 0  | 100.00 | +23.54  | +23.54 *(n=1)* | 0.5100 | 49.02 | 0  | 0  | 0 | 1  |
| sol_5m_v3_3              | v3_3 | 101.83 | 198 | 16.15  | 54 | 26 | 28 | 48.15 | -84.27  | -1.56  | 0.5037 | 50.91 | 23 | 0  | 0 | 18 |
| btc_5m_v4                | v4 | 101.83 | 121 | 9.95   | 18 | 11 | 7  | 61.11 | +29.66  | +1.65  | 0.5117 | 48.86 | 12 | 0  | 0 | 0  |
| eth_5m_v4                | v4 | 101.83 | 39  | 3.24   | 0  | 0  | 0  | —     | 0.00    | 0.00   | 0.0000 | 0.00  | 0  | 0  | 0 | 0  |
| sol_5m_v4                | v4 | 101.83 | 162 | 13.24  | 47 | 22 | 25 | 46.81 | -48.83  | -1.04  | 0.5031 | 50.93 | 21 | 0  | 0 | 12 |
| btc_5m_volume_INV_NIGHT  | volume_INV_NIGHT | 100.00 | 380 | 100.00 | 368 | 188 | 180 | 51.09 | -35.02  | -0.10  | 0.5079 | 49.32 | 0  | 0  | 0 | 0  |
| btc_15m_volume_INV_NIGHT | volume_INV_NIGHT | 100.00 | 128 | 100.00 | 124 | 60  | 64  | 48.39 | **-197.00** | -1.59  | 0.5115 | 49.28 | 0  | 0  | 0 | 0  |
| eth_5m_volume_INV_NIGHT  | volume_INV_NIGHT | 100.00 | 378 | 100.00 | 366 | 187 | 179 | 51.09 | **-255.58** | -0.70  | 0.5203 | 48.73 | 0  | 0  | 0 | 0  |
| eth_15m_volume_INV_NIGHT | volume_INV_NIGHT | 100.00 | 125 | 100.00 | 121 | 62  | 59  | 51.24 | -58.71  | -0.49  | 0.5172 | 48.98 | 0  | 0  | 0 | 0  |
| sol_5m_volume_INV_NIGHT  | volume_INV_NIGHT | 100.00 | 369 | 100.00 | 357 | 177 | 180 | 49.58 | **-557.59** | -1.56  | 0.5234 | 48.53 | 0  | 0  | 0 | 0  |
| sol_15m_volume_INV_NIGHT | volume_INV_NIGHT | 100.00 | 123 | 100.00 | 120 | 61  | 59  | 50.83 | -127.87 | -1.07  | 0.5261 | 48.45 | 0  | 0  | 0 | 0  |

Columns: `hrs`=hours running, `fires`=signals where signal∈{UP,DOWN}, `fire%`=fires/total_signals, `resolved`=settled trades, `WR%`=wins/resolved, `pnl$`=total pnl USD, `pnl/tr$`=avg pnl/trade, `entry`=avg entry price, `qty`=avg shares, `hedge_n`=hedge fires, `sell_n`=bid-exit fires, `p_sell`=partial bid-exit, `skip`=hedge-skip events.

## Rollup by family

| family            | n_sleeves | fires | resolved | wins | WR%   | pnl_total  | pnl/tr$ | hedge_n | sell_n | skip_n |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| momo_v2           | 18 | 1,371 | 819   | 436 | **53.24** | **+970.16** | **+1.18** | 63 | 37 | 59 |
| sniper_INV        | 1  | 208   | 197   | 109 | 55.33 | +207.20    | +1.05  | 0 | 0 | 0 |
| sniper_DOWN_INV   | 1  | 53    | 49    | 29  | **59.18** | +136.07    | **+2.78** | 0 | 0 | 0 |
| v3_1              | 3  | 330   | 87    | 46  | 52.87 | +49.08     | +0.56  | 41 | 0 | 15 |
| v3                | 3  | 382   | 105   | 57  | 54.29 | +41.74     | +0.40  | 48 | 0 | 23 |
| v3_2              | 3  | 490   | 97    | 51  | 52.58 | -18.83     | -0.19  | 43 | 0 | 23 |
| v4                | 3  | 322   | 65    | 33  | 50.77 | -19.17     | -0.29  | 33 | 0 | 12 |
| v3_3              | 3  | 370   | 74    | 38  | 51.35 | -41.46     | -0.56  | 36 | 0 | 19 |
| momo_v1           | 18 | 1,805 | 971   | 489 | 50.36 | -225.60    | -0.23  | 41 | 22 | 116 |
| sniper            | 6  | 979   | 645   | 315 | 48.84 | **-1,146.29** | **-1.78** | 270 | 0 | 158 |
| volume_INV_NIGHT  | 6  | 1,503 | 1,456 | 735 | 50.48 | **-1,231.77** | **-0.85** | 0 | 0 | 0 |

## Key findings

1. **Profitable families** (4 of 11): momo_v2 (+$970), sniper_INV (+$207), sniper_DOWN_INV (+$136), v3 (+$42), v3_1 (+$49). Total positives ≈ **+$1,403**.

2. **Loss-leading families**: sniper (-$1,146 across 6 sleeves), volume_INV_NIGHT (-$1,232 across 6 sleeves) — together responsible for **-$2,378**. These two families net out all the positives and then some.

3. **Top 5 individual sleeves by pnl_total:**
   - sol_5m_momo_HEDGE: +$267.65 (n=100, +$2.68/trade)
   - sol_5m_momo_SELL: +$241.46 (n=100, +$2.41/trade)
   - btc_15m_momo_HOLD: +$225.34 (n=21, **+$10.73/trade**, WR 71.4%)
   - sol_5m_momo_v2_HOLD/HEDGE/SELL composite — strong cluster
   - sol_5m_sniper_INV: +$207.20 (n=197, +$1.05/trade)

4. **Worst 5 individual sleeves by pnl_total:**
   - sol_5m_volume_INV_NIGHT: -$557.59 (n=357)
   - sol_5m_sniper: -$434.52 (n=197, -$2.21/trade)
   - eth_5m_sniper: -$391.57 (n=96, -$4.08/trade) ← biggest per-trade bleeder
   - sol_15m_momo_HEDGE: -$265.23 (n=20, -$13.26/trade, WR 30%)
   - eth_5m_volume_INV_NIGHT: -$255.58 (n=366)

5. **sniper INVERSES (sniper_INV, sniper_DOWN_INV) win where sniper proper loses.** This strongly suggests the sniper base signal has a sign error — taking the opposite side of the sniper signal is profitable. **Worth investigating before disabling sniper.**

6. **volume_INV_NIGHT fires on 100% of bars** — it's the only "always-on" family. WR is coin-flip 50% with cumulative bleed. Likely no real edge.

7. **sniper bleeds despite high hedge activity** — 270 hedges fired across 6 sleeves, but still -$1.78/trade. Hedge mechanics aren't recovering the losing core signal.

8. **v3 lineage** (v3, v3_1, v3_2, v3_3, v4) is fragmented: v3 and v3_1 positive, v3_2/v3_3/v4 negative. v3_2 and v3_3 produce identical numbers on ETH and BTC — likely the same logic with different param. Worth consolidating.

## Totals (all sleeves, last 14d, paper/shadow mode)

```
65 sleeves
7,813 fires → 4,565 resolved → 2,338 wins → WR 51.22%
total pnl: -$1,278.87
pnl/trade: -$0.2801
hedge fires: 575  |  sell fires: 59  |  hedge skips: 425
```

Net: the portfolio loses money at -$0.28/trade in paper. momo_v2 + sniper_INV families are the bright spots; sniper and volume_INV_NIGHT are the heavy bleeders.

## Files

- `data/v4/shadow_trades_2026_05_09/all_sleeve_stats.csv` — raw CSV
- `strategy_lab/meta_classifier/_vps3_all_sleeves_table.sh` — SQL pull
- `strategy_lab/meta_classifier/_vps3_all_sleeves_discover.sh` — discovery
- `strategy_lab/reports/ALL_SHADOW_SLEEVES_TABLE_2026_05_11.md` — this file
