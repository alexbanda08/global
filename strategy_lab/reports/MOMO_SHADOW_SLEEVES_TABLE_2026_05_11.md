# Momo Shadow Sleeves — Comprehensive Per-Sleeve Table

**Pulled:** 2026-05-11 ~06:25 UTC
**Source:** `trading.events` on VPS3 (storedata), last 14d
**Mode:** paper / shadow (all sleeves running in observe-only mode)

## Summary

- **36 sleeves** total: 18 v1 (BTC/ETH/SOL × 5m/15m × HOLD/HEDGE/SELL) + 18 v2 (same matrix)
- **v1 deployed** May 7 ~01:48 UTC, **v2 deployed** May 7 ~13:54 UTC
- **Hours running** median 94.5h (v1 ~100h, v2 ~88h)
- **Total fires:** 3,171  |  **Total resolved:** 1,787  |  **Total wins:** 923  |  **WR overall:** 51.65%
- **Total PnL:** **+$736.59**  |  **Per trade:** **+$0.4122**
- **Hedge fires:** 103  |  **Sell fires:** 58  |  **Hedge skips:** 175

## Per-sleeve table (36 sleeves)

| sleeve | hrs | fires | fire% | resolved | wins | losses | WR% | pnl$ | pnl/tr$ | avg_entry | avg_qty | hedge_n | sell_n | hedge_skip |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 BTC 5m HOLD   | 101.08 | 110 | 9.24  | 99  | 47 | 52 | 47.47 | **-137.77** | -1.39  | 0.4998 | 50.23 | 0  | 0  | 0  |
| v1 BTC 5m HEDGE  | 101.08 | 120 | 9.99  | 99  | 47 | 52 | 47.47 | -113.78    | -1.15  | 0.4998 | 50.23 | 9  | 0  | 18 |
| v1 BTC 5m SELL   | 101.08 | 119 | 9.92  | 100 | 47 | 53 | 47.00 | -124.73    | -1.25  | 0.4997 | 50.24 | 0  | 7  | 18 |
| v1 BTC 15m HOLD  | 100.47 | 39  | 9.90  | 21  | 15 | 6  | **71.43** | **+225.34** | **+10.73** | 0.4924 | 50.90 | 0  | 0  | 0  |
| v1 BTC 15m HEDGE | 100.47 | 44  | 11.03 | 21  | 15 | 6  | 71.43 | +162.13    | +7.72  | 0.4924 | 50.90 | 5  | 0  | 3  |
| v1 BTC 15m SELL  | 100.47 | 43  | 10.80 | 21  | 14 | 7  | 66.67 | +192.49    | +9.17  | 0.4924 | 50.90 | 0  | 4  | 3  |
| v1 ETH 5m HOLD   | 101.08 | 118 | 9.91  | 66  | 30 | 36 | 45.45 | -171.74    | -2.60  | 0.5007 | 50.44 | 0  | 0  | 0  |
| v1 ETH 5m HEDGE  | 101.08 | 126 | 10.51 | 66  | 30 | 36 | 45.45 | -165.31    | -2.50  | 0.5007 | 50.44 | 7  | 0  | 7  |
| v1 ETH 5m SELL   | 101.08 | 124 | 10.36 | 67  | 29 | 38 | 43.28 | -173.06    | -2.58  | 0.5007 | 50.45 | 0  | 6  | 6  |
| v1 ETH 15m HOLD  | 100.47 | 40  | 10.15 | 17  | 10 | 7  | 58.82 | +75.62     | +4.45  | 0.4972 | 50.52 | 0  | 0  | 0  |
| v1 ETH 15m HEDGE | 100.47 | 46  | 11.50 | 17  | 10 | 7  | 58.82 | -3.51      | -0.21  | 0.4972 | 50.52 | 5  | 0  | 4  |
| v1 ETH 15m SELL  | 100.47 | 46  | 11.50 | 17  | 9  | 8  | 52.94 | +36.64     | +2.16  | 0.4972 | 50.52 | 0  | 4  | 4  |
| v1 SOL 5m HOLD   | 101.08 | 200 | 16.79 | 100 | 56 | 44 | 56.00 | +199.64    | +2.00  | 0.5138 | 49.61 | 0  | 0  | 0  |
| v1 SOL 5m HEDGE  | 101.08 | 210 | 17.49 | 100 | 56 | 44 | 56.00 | **+267.65** | **+2.68** | 0.5138 | 49.61 | 10 | 0  | 22 |
| v1 SOL 5m SELL   | 101.08 | 208 | 17.35 | 100 | 56 | 44 | 56.00 | +241.46    | +2.41  | 0.5138 | 49.61 | 0  | 1  | 21 |
| v1 SOL 15m HOLD  | 100.47 | 68  | 17.26 | 20  | 6  | 14 | **30.00** | **-223.37** | **-11.17** | 0.5229 | 48.95 | 0  | 0  | 0  |
| v1 SOL 15m HEDGE | 100.47 | 73  | 18.30 | 20  | 6  | 14 | 30.00 | **-265.23** | **-13.26** | 0.5229 | 48.95 | 5  | 0  | 5  |
| v1 SOL 15m SELL  | 100.47 | 71  | 17.88 | 20  | 6  | 14 | 30.00 | -248.07    | -12.40 | 0.5229 | 48.95 | 0  | 0  | 5  |
| v2 BTC 5m HOLD   | 88.48  | 98  | 9.38  | 86  | 45 | 41 | 52.33 | +70.05     | +0.81  | 0.5018 | 49.90 | 0  | 0  | 0  |
| v2 BTC 5m HEDGE  | 88.48  | 117 | 11.00 | 86  | 45 | 41 | 52.33 | -50.25     | -0.58  | 0.5018 | 49.90 | 17 | 0  | 5  |
| v2 BTC 5m SELL   | 88.48  | 117 | 11.00 | 88  | 40 | 48 | 45.45 | -7.04      | -0.08  | 0.5015 | 49.93 | 0  | 17 | 4  |
| v2 BTC 15m HOLD  | 88.36  | 37  | 10.63 | 26  | 15 | 11 | 57.69 | +92.26     | +3.55  | 0.5023 | 50.11 | 0  | 0  | 0  |
| v2 BTC 15m HEDGE | 88.36  | 42  | 11.90 | 26  | 15 | 11 | 57.69 | +70.29     | +2.70  | 0.5023 | 50.11 | 5  | 0  | 5  |
| v2 BTC 15m SELL  | 88.36  | 40  | 11.40 | 26  | 15 | 11 | 57.69 | +71.88     | +2.76  | 0.5023 | 50.11 | 0  | 3  | 5  |
| v2 ETH 5m HOLD   | 88.48  | 91  | 8.71  | 62  | 32 | 30 | 51.61 | +22.51     | +0.36  | 0.5038 | 50.17 | 0  | 0  | 0  |
| v2 ETH 5m HEDGE  | 88.48  | 109 | 10.25 | 62  | 32 | 30 | 51.61 | -43.65     | -0.70  | 0.5038 | 50.17 | 17 | 0  | 7  |
| v2 ETH 5m SELL   | 88.48  | 106 | 10.00 | 63  | 29 | 34 | 46.03 | +72.43     | +1.15  | 0.5037 | 50.17 | 0  | 11 | 7  |
| v2 ETH 15m HOLD  | 88.36  | 27  | 7.76  | 18  | 12 | 6  | 66.67 | +135.26    | +7.51  | 0.5081 | 49.46 | 0  | 0  | 0  |
| v2 ETH 15m HEDGE | 88.36  | 30  | 8.55  | 18  | 12 | 6  | 66.67 | +64.08     | +3.56  | 0.5081 | 49.46 | 3  | 0  | 6  |
| v2 ETH 15m SELL  | 88.36  | 27  | 7.76  | 18  | 12 | 6  | 66.67 | +135.26    | +7.51  | 0.5081 | 49.46 | 0  | 0  | 6  |
| v2 SOL 5m HOLD   | 88.48  | 129 | 12.34 | 63  | 34 | 29 | 53.97 | +71.13     | +1.13  | 0.5123 | 49.66 | 0  | 0  | 0  |
| v2 SOL 5m HEDGE  | 88.48  | 144 | 13.58 | 63  | 34 | 29 | 53.97 | +11.97     | +0.19  | 0.5123 | 49.66 | 15 | 0  | 4  |
| v2 SOL 5m SELL   | 88.48  | 137 | 13.01 | 63  | 32 | 31 | 50.79 | +76.26     | +1.21  | 0.5123 | 49.66 | 0  | 4  | 4  |
| v2 SOL 15m HOLD  | 88.36  | 36  | 10.34 | 16  | 10 | 6  | 62.50 | +75.55     | +4.72  | 0.5216 | 49.54 | 0  | 0  | 0  |
| v2 SOL 15m HEDGE | 88.36  | 41  | 11.61 | 16  | 10 | 6  | 62.50 | -0.54      | -0.03  | 0.5216 | 49.54 | 5  | 0  | 3  |
| v2 SOL 15m SELL  | 88.36  | 38  | 10.86 | 16  | 10 | 6  | 62.50 | +94.74     | +5.92  | 0.5216 | 49.54 | 0  | 1  | 3  |

## Rollup by version × policy

| version | policy | n_sleeves | fires | resolved | wins | WR%   | pnl_total | pnl/tr$ | hedge_n | sell_n | skip_n |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 | HOLD  | 6 | 575 | 323 | 164 | 50.77 | -32.28   | -0.10  | 0  | 0  | 0  |
| v1 | HEDGE | 6 | 619 | 323 | 164 | 50.77 | -118.05  | -0.37  | 41 | 0  | 59 |
| v1 | SELL  | 6 | 611 | 325 | 161 | 49.54 | -75.27   | -0.23  | 0  | 22 | 57 |
| v2 | HOLD  | 6 | 418 | 271 | 148 | **54.61** | **+466.76** | **+1.72** | 0  | 0  | 0  |
| v2 | HEDGE | 6 | 483 | 271 | 148 | 54.61 | +51.90   | +0.19  | 62 | 0  | 30 |
| v2 | SELL  | 6 | 465 | 274 | 138 | 50.36 | +443.53  | +1.62  | 0  | 36 | 29 |

## HOLD-only baseline (cleanest signal-quality comparison)

| version | asset | tf  | hrs    | fires | resolved | wins | WR%   | pnl$    | pnl/tr$ | entry  |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 | btc | 5m  | 101.08 | 110   | 99       | 47   | 47.47 | -137.77 | -1.39   | 0.4998 |
| v1 | btc | 15m | 100.47 | 39    | 21       | 15   | 71.43 | +225.34 | +10.73  | 0.4924 |
| v1 | eth | 5m  | 101.08 | 118   | 66       | 30   | 45.45 | -171.74 | -2.60   | 0.5007 |
| v1 | eth | 15m | 100.47 | 40    | 17       | 10   | 58.82 | +75.62  | +4.45   | 0.4972 |
| v1 | sol | 5m  | 101.08 | 200   | 100      | 56   | 56.00 | +199.64 | +2.00   | 0.5138 |
| v1 | sol | 15m | 100.47 | 68    | 20       | 6    | 30.00 | -223.37 | -11.17  | 0.5229 |
| v2 | btc | 5m  | 88.48  | 98    | 86       | 45   | 52.33 | +70.05  | +0.81   | 0.5018 |
| v2 | btc | 15m | 88.36  | 37    | 26       | 15   | 57.69 | +92.26  | +3.55   | 0.5023 |
| v2 | eth | 5m  | 88.48  | 91    | 62       | 32   | 51.61 | +22.51  | +0.36   | 0.5038 |
| v2 | eth | 15m | 88.36  | 27    | 18       | 12   | 66.67 | +135.26 | +7.51   | 0.5081 |
| v2 | sol | 5m  | 88.48  | 129   | 63       | 34   | 53.97 | +71.13  | +1.13   | 0.5123 |
| v2 | sol | 15m | 88.36  | 36    | 16       | 10   | 62.50 | +75.55  | +4.72   | 0.5216 |

## Top / bottom sleeves by pnl/trade

**TOP 8 (winners):**
| sleeve            | resolved | WR%   | pnl/tr$  | pnl$    | hedge_n | sell_n |
|---|---:|---:|---:|---:|---:|---:|
| v1 BTC 15m HOLD   | 21       | 71.43 | **+10.73** | +225.34 | 0  | 0  |
| v1 BTC 15m SELL   | 21       | 66.67 | +9.17    | +192.49 | 0  | 4  |
| v1 BTC 15m HEDGE  | 21       | 71.43 | +7.72    | +162.13 | 5  | 0  |
| v2 ETH 15m SELL   | 18       | 66.67 | +7.51    | +135.26 | 0  | 0  |
| v2 ETH 15m HOLD   | 18       | 66.67 | +7.51    | +135.26 | 0  | 0  |
| v2 SOL 15m SELL   | 16       | 62.50 | +5.92    | +94.74  | 0  | 1  |
| v2 SOL 15m HOLD   | 16       | 62.50 | +4.72    | +75.55  | 0  | 0  |
| v1 ETH 15m HOLD   | 17       | 58.82 | +4.45    | +75.62  | 0  | 0  |

**BOTTOM 8 (losers):**
| sleeve            | resolved | WR%   | pnl/tr$  | pnl$    | hedge_n | sell_n |
|---|---:|---:|---:|---:|---:|---:|
| v1 BTC 5m SELL    | 100      | 47.00 | -1.25    | -124.73 | 0  | 7  |
| v1 BTC 5m HOLD    | 99       | 47.47 | -1.39    | -137.77 | 0  | 0  |
| v1 ETH 5m HEDGE   | 66       | 45.45 | -2.50    | -165.31 | 7  | 0  |
| v1 ETH 5m SELL    | 67       | 43.28 | -2.58    | -173.06 | 0  | 6  |
| v1 ETH 5m HOLD    | 66       | 45.45 | -2.60    | -171.74 | 0  | 0  |
| v1 SOL 15m HOLD   | 20       | 30.00 | -11.17   | -223.37 | 0  | 0  |
| v1 SOL 15m SELL   | 20       | 30.00 | -12.40   | -248.07 | 0  | 0  |
| v1 SOL 15m HEDGE  | 20       | 30.00 | **-13.26** | -265.23 | 5  | 0  |

## Key findings

1. **v2 outperforms v1 across the board.** v2 HOLD: +$1.72/trade vs v1 HOLD -$0.10/trade. v2 WR 54.61% vs v1 50.77%. The +60s fire-offset shift in v2 (fires at strike+60 instead of strike+120) is materially better.

2. **15m timeframe dominates 5m on small-sample winners.** All top 8 sleeves are 15m. 15m has fewer trades (16-26 resolved per sleeve) but high pnl/trade ($4-$11/trade). 5m has more trades (60-100) and most are near coin-flip.

3. **v1 SOL 15m is a disaster** — 30% WR on n=20, all three policies bleed >$11/trade. Either small-sample bad luck or a real anti-edge during this window. Worth a deeper look.

4. **HEDGE/SELL policies underperform HOLD on average** for v2 (+0.19 / +1.62 vs +1.72 HOLD). For v1 also HEDGE worst, HOLD best. **Exit policies cost money** on net.

5. **Hedge skip count = 175 across all sleeves.** Most concentrated in v1 5m sleeves (BTC 18, ETH 7, SOL 22 per policy). Skip reasons include `stale_feed`, others to be investigated.

6. **Avg entry price = $0.50 essentially across all sleeves** (range 0.4924 - 0.5229). avg_qty = ~50 shares per $25 stake. Production fills right at top-of-book.

7. **v1 BTC 15m HOLD WR = 71.43%** is the standout — but n=21 only. Watch.

## Per-cell recommendation (preliminary, n-weighted)

| cell | best policy | edge $/tr | n_resolved | note |
|---|---|---:|---:|---|
| v2 SOL 15m | SELL | +5.92 | 16 | watch for sample |
| v2 BTC 15m | HOLD | +3.55 | 26 | clean edge |
| v2 ETH 15m | HOLD/SELL tie | +7.51 | 18 | small n, big edge |
| v2 SOL 5m  | SELL | +1.21 | 63 | weak edge, larger n |
| v2 BTC 5m  | HOLD | +0.81 | 86 | weak edge, larger n |
| v2 ETH 5m  | SELL | +1.15 | 63 | beats HOLD by 3x |
| v1 SOL 5m  | HEDGE | +2.68 | 100 | strongest 5m edge across both versions |
| v1 SOL 15m | KILL ALL | -11 to -13 | 20 | underperformer — disable? |

## Files

| path | description |
|---|---|
| `data/v4/shadow_trades_2026_05_09/momo_sleeve_stats.csv` | raw per-sleeve CSV from VPS3 |
| `strategy_lab/meta_classifier/_vps3_sleeve_table.sh` | SQL pull script (server-side) |
| `strategy_lab/meta_classifier/_render_sleeve_table.py` | local renderer |
| `strategy_lab/reports/MOMO_SHADOW_SLEEVES_TABLE_2026_05_11.md` | this file |
