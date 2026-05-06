# Extended Backtest + Permutation + Walkforward

_Generated: 2026-05-05 evening_

## What's new

- **Fresh data**: pulled VPS2 `market_resolutions_v2` (16030 resolved markets, Apr 22 → May 6) and combined Binance-vision + Binance-WS + OKX-WS klines feed
- **Tier1 entries**: extended pull → 28700 (slug, outcome) entries with 25 levels of depth, microsecond-precise timestamps (median 336ms from t+120s target)
- **Active universe (asset_ret_2m valid)**: 16030 markets
- **Total fires (top-10% |asset_ret_2m| per cell)**: 1605

## Headline — full extended dataset

Engine: $25 stake, top-25 ASK book walk for entry, 2% taker fee, asset-specific spread filter, 10s-bucket book for hedge/sell exit monitoring (existing CSVs cover Apr 22-May 4).

| Cell | Policy | n | hit% | avg vwap | total | mean | std | Sharpe | Sortino | maxDD | hedged | sells |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m | HOLD | 337 | 91.1 | $0.9019 | $+92.02 | $+0.2731 | $8.16 | +3.22 | +nan | $-183.54 | 0 | 0 |
| BTC_5m | HEDGE | 337 | 73.0 | $0.9019 | $-26.22 | $-0.0778 | $5.73 | -1.31 | -1.14 | $-118.08 | 113 | 0 |
| BTC_5m | SELL | 337 | 73.0 | $0.9019 | $-12.71 | $-0.0377 | $5.68 | -0.64 | -0.55 | $-112.50 | 0 | 113 |
| BTC_15m | HOLD | 113 | 74.3 | $0.7779 | $-157.46 | $-1.3934 | $14.12 | -5.52 | +nan | $-272.16 | 0 | 0 |
| BTC_15m | HEDGE | 113 | 45.1 | $0.7779 | $-49.82 | $-0.4409 | $7.59 | -3.25 | -4.94 | $-86.03 | 64 | 0 |
| BTC_15m | SELL | 113 | 46.0 | $0.7779 | $-35.02 | $-0.3099 | $7.50 | -2.31 | -3.48 | $-73.50 | 0 | 64 |
| ETH_5m | HOLD | 291 | 95.5 | $0.9197 | $+283.66 | $+0.9748 | $5.88 | +14.82 | +nan | $-50.00 | 0 | 0 |
| ETH_5m | HEDGE | 291 | 71.8 | $0.9197 | $+86.30 | $+0.2966 | $4.42 | +6.00 | +4.50 | $-55.71 | 99 | 0 |
| ETH_5m | SELL | 291 | 72.2 | $0.9197 | $+93.17 | $+0.3202 | $4.40 | +6.51 | +4.73 | $-54.50 | 0 | 99 |
| ETH_15m | HOLD | 103 | 81.6 | $0.8050 | $+33.08 | $+0.3212 | $12.25 | +1.39 | +nan | $-153.76 | 0 | 0 |
| ETH_15m | HEDGE | 103 | 49.5 | $0.8050 | $+16.65 | $+0.1617 | $6.64 | +1.29 | +1.76 | $-75.34 | 59 | 0 |
| ETH_15m | SELL | 103 | 49.5 | $0.8050 | $+25.94 | $+0.2518 | $6.59 | +2.03 | +2.72 | $-67.12 | 0 | 59 |
| SOL_5m | HOLD | 260 | 90.8 | $0.9169 | $-65.78 | $-0.2530 | $8.05 | -2.66 | +nan | $-118.27 | 0 | 0 |
| SOL_5m | HEDGE | 260 | 71.9 | $0.9169 | $-35.78 | $-0.1376 | $4.93 | -2.36 | -2.03 | $-85.87 | 84 | 0 |
| SOL_5m | SELL | 260 | 72.3 | $0.9169 | $-23.07 | $-0.0887 | $4.85 | -1.55 | -1.33 | $-79.59 | 0 | 84 |
| SOL_15m | HOLD | 94 | 77.7 | $0.8019 | $-74.98 | $-0.7977 | $13.17 | -3.09 | +nan | $-156.06 | 0 | 0 |
| SOL_15m | HEDGE | 94 | 48.9 | $0.8019 | $-15.44 | $-0.1642 | $7.11 | -1.18 | -1.67 | $-86.42 | 54 | 0 |
| SOL_15m | SELL | 94 | 48.9 | $0.8019 | $-3.97 | $-0.0423 | $7.02 | -0.31 | -0.43 | $-79.42 | 0 | 54 |

## Permutation test — is the strategy edge real?

Method: hold the FIRED trades + their entry vwap fixed; randomize whether each trade wins
or loses (Bernoulli with the observed hit rate). Repeat 1000×. p-value = fraction of
random draws producing PnL ≥ observed PnL.

| Cell | n | observed PnL | null mean | null q975 | null max | p-value |
|---|---:|---:|---:|---:|---:|---:|
| BTC_5m | 337 | $+92.02 | $+85.33 | $+369.45 | $+535.90 | **0.4460** ns |
| BTC_15m | 113 | $-157.46 | $-156.98 | $+96.59 | $+223.62 | **0.4680** ns |
| ETH_5m | 291 | $+283.66 | $+285.07 | $+473.98 | $+528.36 | **0.5830** ns |
| ETH_15m | 103 | $+33.08 | $+33.39 | $+250.42 | $+374.61 | **0.4560** ns |
| SOL_5m | 260 | $-65.78 | $-63.65 | $+179.59 | $+288.65 | **0.5550** ns |
| SOL_15m | 94 | $-74.98 | $-73.61 | $+143.95 | $+330.16 | **0.5730** ns |

**Caveat on this permutation**: it tests the conditional H0 'given we fired on these markets,
does outcome direction match signal beyond random?' It does NOT test the GATE itself
(whether top-10% |asset_ret_2m| picks better markets than random selection). For that
we'd need to shuffle outcomes across the FULL universe and re-fire — see `permutation_test_strict`
(stub, not run here).

## Walkforward — out-of-sample stability

Method: rolling 7-day train window / 1-day test window. Each test day, refit q90 |asset_ret_2m|
on the prior 7 days, deploy that threshold on the test day, record HOLD-policy PnL. Aggregate
all out-of-sample test PnLs.

| Cell | n_test | OOS total | OOS mean | OOS hit% | n_windows |
|---|---:|---:|---:|---:|---:|
| BTC_5m | 180 | $-127.13 | $-0.7063 | 88.9% | 8 |
| BTC_15m | 64 | $-162.40 | $-2.5375 | 71.9% | 8 |
| ETH_5m | 147 | $+46.51 | $+0.3164 | 93.9% | 8 |
| ETH_15m | 56 | $+34.69 | $+0.6195 | 82.1% | 8 |
| SOL_5m | 121 | $-13.72 | $-0.1134 | 93.4% | 8 |
| SOL_15m | 43 | $-31.99 | $-0.7440 | 79.1% | 8 |

If OOS PnL ≈ in-sample, threshold refits don't degrade the edge — the strategy is robust to 
regime shifts and not overfitting to the in-sample distribution.

---

## Verdict

- **Permutation**: 0/6 cells significant at p<0.05 (observed PnL exceeds 95% of random draws)
- **Walkforward**: combined OOS PnL $-254.03 across all 6 cells
- **Headline (all policies, all cells)**: combined PnL $+130.56
