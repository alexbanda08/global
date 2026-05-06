# Extended Backtest + Permutation + Walkforward

_Generated: 2026-05-05 evening_

## What's new

- **Fresh data**: pulled VPS2 `market_resolutions_v2` (15370 resolved markets, Apr 22 → May 6) and combined Binance-vision + Binance-WS + OKX-WS klines feed
- **Tier1 entries**: extended pull → 28700 (slug, outcome) entries with 25 levels of depth, microsecond-precise timestamps (median 336ms from t+120s target)
- **Active universe (asset_ret_2m valid)**: 15370 markets
- **Total fires (top-10% |asset_ret_2m| per cell)**: 1542

## Headline — full extended dataset

Engine: $25 stake, top-25 ASK book walk for entry, 2% taker fee, asset-specific spread filter, 10s-bucket book for hedge/sell exit monitoring (existing CSVs cover Apr 22-May 4).

| Cell | Policy | n | hit% | avg vwap | total | mean | std | Sharpe | Sortino | maxDD | hedged | sells |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m | HOLD | 325 | 89.2 | $0.6935 | $+4705.02 | $+14.4770 | $71.05 | +19.24 | +2243403711699425792.00 | $-71.00 | 0 | 0 |
| BTC_5m | HEDGE | 325 | 92.3 | $0.6935 | $+5127.32 | $+15.7764 | $70.43 | +21.15 | +165.09 | $-46.85 | 81 | 0 |
| BTC_5m | SELL | 325 | 92.3 | $0.6935 | $+5140.97 | $+15.8184 | $70.42 | +21.21 | +162.18 | $-46.67 | 0 | 81 |
| BTC_15m | HOLD | 108 | 82.4 | $0.6291 | $+1017.17 | $+9.4183 | $22.04 | +23.31 | +nan | $-94.62 | 0 | 0 |
| BTC_15m | HEDGE | 108 | 81.5 | $0.6291 | $+1006.07 | $+9.3155 | $16.13 | +31.50 | +55.09 | $-32.26 | 50 | 0 |
| BTC_15m | SELL | 108 | 81.5 | $0.6291 | $+1021.94 | $+9.4624 | $16.09 | +32.09 | +55.20 | $-32.26 | 0 | 50 |
| ETH_5m | HOLD | 294 | 92.2 | $0.7279 | $+3699.89 | $+12.5847 | $46.85 | +24.11 | +1491633034476531200.00 | $-61.05 | 0 | 0 |
| ETH_5m | HEDGE | 294 | 93.2 | $0.7279 | $+3850.03 | $+13.0953 | $45.95 | +25.59 | +108.50 | $-50.00 | 84 | 0 |
| ETH_5m | SELL | 294 | 93.5 | $0.7279 | $+3862.82 | $+13.1388 | $45.94 | +25.67 | +111.01 | $-50.00 | 0 | 84 |
| ETH_15m | HOLD | 101 | 74.3 | $0.6499 | $+549.06 | $+5.4363 | $23.24 | +12.32 | +nan | $-131.40 | 0 | 0 |
| ETH_15m | HEDGE | 101 | 85.1 | $0.6499 | $+796.58 | $+7.8869 | $16.61 | +25.01 | +36.81 | $-50.00 | 58 | 0 |
| ETH_15m | SELL | 101 | 87.1 | $0.6499 | $+815.97 | $+8.0789 | $16.57 | +25.68 | +36.29 | $-50.00 | 0 | 58 |
| SOL_5m | HOLD | 252 | 89.3 | $0.7319 | $+2821.28 | $+11.1955 | $45.74 | +20.37 | +345203429707978944.00 | $-86.03 | 0 | 0 |
| SOL_5m | HEDGE | 252 | 90.9 | $0.7319 | $+3235.75 | $+12.8403 | $44.87 | +23.81 | +107.28 | $-48.48 | 78 | 0 |
| SOL_5m | SELL | 252 | 91.3 | $0.7319 | $+3257.29 | $+12.9258 | $44.86 | +23.97 | +109.85 | $-48.44 | 0 | 78 |
| SOL_15m | HOLD | 71 | 84.5 | $0.6874 | $+688.21 | $+9.6931 | $27.55 | +15.58 | +191073997475522656.00 | $-51.97 | 0 | 0 |
| SOL_15m | HEDGE | 71 | 78.9 | $0.6874 | $+640.11 | $+9.0156 | $23.44 | +17.03 | +40.36 | $-36.97 | 41 | 0 |
| SOL_15m | SELL | 71 | 80.3 | $0.6874 | $+649.55 | $+9.1486 | $23.42 | +17.30 | +39.78 | $-36.97 | 0 | 41 |

## Permutation test — is the strategy edge real?

Method: hold the FIRED trades + their entry vwap fixed; randomize whether each trade wins
or loses (Bernoulli with the observed hit rate). Repeat 1000×. p-value = fraction of
random draws producing PnL ≥ observed PnL.

| Cell | n | observed PnL | null mean | null q975 | null max | p-value |
|---|---:|---:|---:|---:|---:|---:|
| BTC_5m | 325 | $+4705.02 | $+4683.38 | $+5148.54 | $+5457.12 | **0.5200** ns |
| BTC_15m | 108 | $+1017.17 | $+1016.00 | $+1351.30 | $+1434.83 | **0.5500** ns |
| ETH_5m | 294 | $+3699.89 | $+3690.19 | $+4026.09 | $+4189.19 | **0.4450** ns |
| ETH_15m | 101 | $+549.06 | $+550.87 | $+876.96 | $+1122.89 | **0.4640** ns |
| SOL_5m | 252 | $+2821.28 | $+2829.39 | $+3187.14 | $+3550.98 | **0.5060** ns |
| SOL_15m | 71 | $+688.21 | $+686.98 | $+934.53 | $+1057.69 | **0.5640** ns |

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
| BTC_5m | 201 | $+2270.96 | $+11.2983 | 89.6% | 7 |
| BTC_15m | 70 | $+417.06 | $+5.9580 | 77.1% | 7 |
| ETH_5m | 178 | $+1597.14 | $+8.9727 | 90.4% | 7 |
| ETH_15m | 72 | $+165.55 | $+2.2993 | 70.8% | 7 |
| SOL_5m | 114 | $+599.84 | $+5.2618 | 92.1% | 7 |
| SOL_15m | 35 | $+46.33 | $+1.3236 | 77.1% | 7 |

If OOS PnL ≈ in-sample, threshold refits don't degrade the edge — the strategy is robust to 
regime shifts and not overfitting to the in-sample distribution.

---

## Verdict

- **Permutation**: 0/6 cells significant at p<0.05 (observed PnL exceeds 95% of random draws)
- **Walkforward**: combined OOS PnL $+5096.88 across all 6 cells
- **Headline (all policies, all cells)**: combined PnL $+42885.04


---

## Strict Permutation Tests — DIRECTION + GATE

_(Added after the degenerate Bernoulli permutation test in the original report.)_

**A) DIRECTION_PERM**: keep the FIRED trade set fixed (the same 1542 markets at top-10% \|asset_ret_2m\|). For each, randomize whether we bet UP or DOWN. Repeat 1000×. PnL distribution under random direction is the null. p-value = P(null ≥ observed).

Tests H0: sign(asset_ret_2m) is uninformative — we'd do equally well betting random direction.

**B) GATE_PERM**: shuffle which markets get fired — pick a random 10% of the asset/tf universe per draw, use sign(asset_ret_2m) as direction. PnL distribution under random gate is the null.

Tests H0: the top-10% \|asset_ret_2m\| gate doesn't select better markets than random selection.

| Cell | n | observed PnL | DIR null_mean | DIR null_q975 | DIR p | GATE null_mean | GATE null_q975 | GATE p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m | 325 | $+4705.02 | $-298.07 | $+1242.36 | **0.0000** *** | $+1662.25 | $+2937.82 | **0.0000** *** |
| BTC_15m | 108 | $+1017.17 | $-253.04 | $+223.26 | **0.0000** *** | $+443.18 | $+960.49 | **0.0170** * |
| ETH_5m | 294 | $+3699.89 | $-1205.93 | $-245.04 | **0.0000** *** | $+1500.66 | $+2551.40 | **0.0000** *** |
| ETH_15m | 101 | $+549.06 | $-92.10 | $+458.53 | **0.0100** * | $+288.06 | $+745.03 | **0.1360** ns |
| SOL_5m | 252 | $+2821.28 | $-971.96 | $+25.79 | **0.0000** *** | $+1144.42 | $+2041.63 | **0.0000** *** |
| SOL_15m | 71 | $+688.21 | $-150.74 | $+252.32 | **0.0000** *** | $+226.67 | $+584.50 | **0.0050** ** |

**Summary**: 6/6 cells significant for DIRECTION (sign matters); 5/6 cells significant for GATE (top-10% selects better markets).
