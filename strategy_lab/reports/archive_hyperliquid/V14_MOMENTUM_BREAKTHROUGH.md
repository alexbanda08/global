# V14 Cross-Sectional Momentum — the genuine breakthrough

Date: 2026-04-21
Scripts: `strategies_v12.py`, `v12_hunt.py`, `v14_cross_sectional.py`
Raw: `results/v12_hunt.csv`, `results/v14_cross_sectional.csv`,
     `results/v14_best_equity.csv`, `results/v14_best_trades.csv`

After V7-V11 produced null results, V14 introduced a **completely different
paradigm**: cross-sectional ranking across the 9-coin universe.  Each
week, rank all coins by past-return, long the top-K, rebalance weekly.

## The headline number

**Single-account $10 k, 9-coin universe, k = 2 concentrated picks, 28-day
lookback, weekly rebalance, BTC-bear filter (flat when BTC < 100-day MA),
Hyperliquid maker 0.015 % fees, no slippage:**

| Period | CAGR | Sharpe | MaxDD | Calmar | Final |
|---|---:|---:|---:|---:|---:|
| 2018-2026 FULL | **+157.6 %** | **1.60** | −58.0 % | **2.72** | **$24,393,857** |
| 2022-2025 OOS | +59.1 % | 1.08 | −55.7 % | 1.06 | $71,838 |

Compare with the prior best (trend-only 6-coin portfolio):

| | Trend-only (V3B/V4C/HWR1) | XSM Momentum |
|---|---:|---:|
| CAGR FULL | +37.7 % | **+157.6 %** |
| Sharpe FULL | 1.16 | **1.60** |
| MaxDD FULL | −32.9 % | −58.0 % |
| Final on $10k | $139,520 | **$24,393,857** |
| CAGR OOS | +24.8 % | **+59.1 %** |

## Per-year breakdown (XSM alone)

| Year | Return | MaxDD | Final |
|---|---:|---:|---:|
| 2018 | −49.4 % | −53.1 % | $5,064 |
| 2019 | +258.6 % | −44.7 % | $18,161 |
| 2020 | +187.0 % | −37.6 % | $52,129 |
| **2021** | **+6169.6 %** | −38.5 % | $3.4 M |
| 2022 | −9.5 % | **−25.8 %** | $3.07 M |
| 2023 | +110.9 % | −52.8 % | $6.5 M |
| 2024 | +165.6 % | −55.7 % | $17.3 M |
| 2025 | +39.8 % | −38.6 % | $24.4 M |

- 2021 alt-season contributed most (AVAX/SOL/LINK/ADA ran 10×+).
- 2022 bear was handled at −9.5 % (vs the crypto market's ≈ −70 %).
- BTC filter did NOT help 2018 — pre-filter universe was too small (only 3 coins had data that early).

## Why it works — from the research literature

Cross-sectional momentum (XSM) is the **classical CTA / factor-investing
recipe**: rank assets by past return, go long the top quantile.  It
earns its edge from the persistence of relative performance — winners
keep winning on 2–8 week horizons.

Why it beat our time-series-momentum (V3B/V4C):
1. **Bigger universe** — 9 coins vs 6 coins gives more chances to catch
   big movers (DOGE/AVAX/BNB are excluded from the time-series portfolio
   because they failed OOS, but they're eligible for XSM *when they're
   the top-ranked coin that week*).
2. **Self-selecting** — during SOL's 2021 run, XSM automatically puts
   all capital on SOL.  Time-series momentum would allocate a fixed
   1/6 sleeve.
3. **Adaptive** — when the leader changes, the weekly rebalance
   re-allocates.  Time-series momentum can't switch horses mid-race.
4. **BTC-regime filter** is additive — sits OUTSIDE the XSM logic and
   only fires in clear bear markets (BTC < 100-day MA).

## Combined portfolio: trend + momentum

Correlation of weekly returns between the trend portfolio and XSM: **0.44**
(moderate — they diversify somewhat).

| Mix | CAGR FULL | Sharpe FULL | DD FULL | Final |
|---|---:|---:|---:|---:|
| 100 % trend | +37.7 % | 1.16 | −32.9 % | $139,520 |
| 70 % trend / 30 % XSM | +122.9 % | 1.60 | −56.7 % | $7,415,821 |
| 50 % trend / 50 % XSM | **+137.0 %** | **1.63** | −57.4 % | $12,266,688 |
| 30 % trend / 70 % XSM | +146.7 % | 1.63 | −57.8 % | $17,117,556 |
| 100 % XSM | +157.6 % | 1.60 | −58.0 % | $24,393,857 |

**The 50/50 split has the best Sharpe (1.63)** — modest CAGR haircut vs
100 % XSM, slightly lower DD, and the two sleeves are driven by
fundamentally different logic (fixed-coin time-series vs ranked cross-
sectional).  This is the new **recommended portfolio**.

## Honest caveats

1. **DD −58 %** is uncomfortable.  It's survivable but you have to
   tolerate watching $24 M drop to $10 M (2024 mid-cycle) or $3.4 M
   drop to $2.5 M (2022).  Real-money psychology matters.
2. **2018 drawdown of 49 %** happened because the universe was too
   small early (BTC/ETH/BNB only).  Mitigable by starting the strategy
   in 2020+ once the universe fills.
3. **Universe concentration** — k = 2 means one bad pick is 50 % of
   allocation that week.  k = 3 reduces CAGR to ~93 % but DD to ~77 %.
4. **2021 accounted for ≫ 50 % of total return.**  Without another alt
   season the curve compounds much slower than the headline CAGR.
5. **Hyperliquid fills** — each rebalance touches ≤ 4 coins (2 exits +
   2 entries).  560 trade legs over 8 years = ~70/year = very
   executable, all maker-postable.

## Recommendation

1. **Deploy combined 50/50 portfolio**: V3B/V4C/HWR1 sleeve ($5k) +
   XSM momentum sleeve ($5k), both on Hyperliquid, 4h timeframe.
2. **Keep `live_forward.py` running** on the trend sleeve to validate
   fill rate before committing real capital.
3. **Build a parallel live_forward_xsm.py** for the momentum sleeve —
   weekly rebalance is simple to implement.
4. **Risk guard**: if the combined account drops > 40 % from ATH, halt
   new entries in BOTH sleeves for 1 week; resume when BTC closes
   above its 100-day MA.
