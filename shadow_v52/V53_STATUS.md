# V53 Breadth Shadow Status

**Run:** 2026-08-24T13:05:25.262495+00:00
**Mode:** PAPER (no real orders). Notional/stream = $250 (display).
**Streams:** 2 validated families x 10 coins = 20
**Data end (max):** 2026-08-24T12:00:00+00:00

**Arms:** DEPLOY=['STF'] (eligible for capital after the shadow gate) | OBSERVE=['VP'] (logged at $0, never sized).

STF validated on an untouched window (pre-2024-03, Binance 4h, n=877, +1.054%/tr, t=+5.01, 9/10 coins positive) AND positive in every sequential window since. VP passed the same untouched window (n=1914, t=+3.93, 10/10) but has since decayed monotonically to -1.091%/tr (t=-3.38, n=161, 2/10 coins) — hence OBSERVE, not DEPLOY. See strategy_lab/hl_research_2026_05_26/retest_2026_07_27/.

## Open paper positions

| Sleeve | Dir | Entry ts | Entry px | Bars | Unreal % | Unreal $ |
|---|---|---|---:|---:|---:|---:|
| VP_BTC | SHORT | 2026-08-24T00:00:00+00:00 | 77805.0 | 3 | -0.603 | -1.51 |

## Pending fires (act at next bar open)

| Sleeve | Dir | Signal bar | Close |
|---|---|---|---:|
| VP_DOGE | SHORT | 2026-08-24T12:00:00+00:00 | 0.091817 |

## Closed paper trades in ledger: 317

| Arm | Family | n | mean ret % | WR % | paper $ |
|---|---|---:|---:|---:|---:|
| DEPLOY | STF | 120 | +0.958 | 35.8 | 287.45 |
| OBSERVE | VP | 197 | -0.435 | 25.4 | -214.35 |

**DEPLOY arm only** — n=120, mean +0.958%/tr, WR 35.8%, paper $287.45

| Arm | Sleeve | n | mean ret % | paper $ |
|---|---|---:|---:|---:|
| OBSERVE | VP_BTC | 23 | -1.98 | -113.8 |
| OBSERVE | VP_BNB | 22 | -0.86 | -47.22 |
| OBSERVE | VP_ETH | 16 | -1.18 | -47.07 |
| OBSERVE | VP_DOGE | 21 | -0.73 | -38.45 |
| DEPLOY | STF_AVAX | 16 | -0.63 | -25.21 |
| OBSERVE | VP_LINK | 23 | -0.41 | -23.74 |
| OBSERVE | VP_ADA | 18 | -0.46 | -20.66 |
| OBSERVE | VP_XRP | 19 | -0.27 | -12.94 |
| OBSERVE | VP_SUI | 17 | -0.28 | -11.8 |
| DEPLOY | STF_ADA | 8 | -0.53 | -10.5 |
| DEPLOY | STF_BNB | 12 | -0.12 | -3.58 |
| OBSERVE | VP_AVAX | 19 | 0.21 | 10.2 |
| DEPLOY | STF_DOGE | 10 | 0.96 | 24.1 |
| DEPLOY | STF_SOL | 14 | 0.99 | 34.64 |
| DEPLOY | STF_XRP | 10 | 1.72 | 42.98 |
| DEPLOY | STF_BTC | 13 | 1.52 | 49.39 |
| DEPLOY | STF_LINK | 14 | 1.42 | 49.76 |
| DEPLOY | STF_ETH | 17 | 1.46 | 62.26 |
| DEPLOY | STF_SUI | 6 | 4.24 | 63.61 |
| OBSERVE | VP_SOL | 19 | 1.92 | 91.13 |
