# Robustness battery — 11 gated sleeves

**Source data**: `strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv` (production strategy code, L25 walks, LiveMimic latency + 2%-on-profit fees, F7-OFF universe), 28 days, Apr 22 → May 21 2026.
**Runner**: `strategy_lab/markov_filter/robustness_gated_sleeves.py`
**Output CSV**: `strategy_lab/markov_filter/_results/robustness_gated_sleeves.csv`

## What changed vs the original `eval/metrics.py` runner

Binary up-down markets break two assumptions of the standard robustness battery:

1. **Cumprod equity collapses** when a single trade loses 100% of notional → `max_drawdown(equity)` returns −100 % on the first loss and Calmar = 0.
2. **Annualized Sharpe explodes** at trades/year ≈ 1000–3000 because `sqrt(N)` blows up modest per-trade ratios into 4-digit numbers.

The runner adapts:

* Equity = **cumulative $-PnL** (cash, no compounding). MDD reported in $.
* Sharpe / Sortino reported **per-trade** (the meaningful unit). Annualized versions kept as a separate column for those who want them.
* Calmar = annualized $-PnL ÷ |max drawdown $|.
* Null test combines:
  - **Binomial test** on real WR vs `vwap`-implied break-even WR (a coin-flip at the price paid).
  - **Monte-Carlo** (n=2000) on a hypothetical random-signal sleeve at the per-trade vwap probabilities, same shares + fees.
* Block bootstrap (n=2000, stationary, expected-block-length 10) on `sum_$`, `per_trade_$`, `sharpe_pt`.
* Walk-forward = 50/50 chronological split (train Apr 22 – May 7, test May 8 – May 21).

## Per-sleeve scorecard — ranked by sum $

| sleeve | n | WR % | vwap-WR % | edge | $/tr | sum $ | sharpe_pt | sortino_pt | wf_ret | sum CI (95 %) | sharpe CI | binom p | mc p |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|---|--:|--:|
| sniper_btc_15m_HOD       | 205 | 60.98 | 49.26 | +11.72 | 5.15  | +1055 | 0.21 |  63 | +0.45 | [+450 , +1598] | [0.09 , 0.32] | 0.0005 | 0.0000 |
| sniper_sol_5m_HOD        | 131 | 67.94 | 50.72 | +17.22 | 7.49  | +981  | 0.33 | 196 | +1.55 | [+531 , +1401] | [0.17 , 0.50] | 0.0000 | 0.0000 |
| sniper_btc_5m_HOD        | 240 | 57.92 | 48.89 |  +9.02 | 3.72  | +892  | 0.15 |  53 | +0.53 | [+143 , +1641] | [0.02 , 0.27] | 0.0031 | 0.0010 |
| sniper_eth_5m_HOD        | 182 | 57.69 | 48.56 |  +9.14 | 4.00  | +729  | 0.16 |  66 | +0.01 | [+66  , +1368] | [0.01 , 0.30] | 0.0083 | 0.0025 |
| momo_v1_btc_15m_HOD      |  54 | 75.93 | 50.59 | +25.34 | 11.86 | +640  | 0.55 | 327 | +0.82 | [+396 , +880]  | [0.31 , 0.92] | 0.0001 | 0.0000 |
| momo_v2_sol_5m_HOD       | 124 | 62.90 | 51.28 | +11.62 | 4.93  | +611  | 0.21 | 159 | +0.53 | [+210 , +1002] | [0.07 , 0.36] | 0.0060 | 0.0025 |
| momo_v2_btc_15m_HOD      |  68 | 69.12 | 50.59 | +18.53 | 8.24  | +560  | 0.36 | 341 | +0.57 | [+299 , +816]  | [0.18 , 0.57] | 0.0015 | 0.0010 |
| momo_v2_btc_5m_HOD+MTF2  | 131 | 59.54 | 49.46 | +10.08 | 4.18  | +548  | 0.17 | 194 | +2.83 | [+107 , +994]  | [0.03 , 0.32] | 0.0131 | 0.0055 |
| sniper_eth_15m_HOD+M5va  |  47 | 70.21 | 47.26 | +22.95 | 11.26 | +529  | 0.46 | 216 | +2.75 | [+257 , +783]  | [0.21 , 0.78] | 0.0012 | 0.0005 |
| momo_v2_eth_15m_HOD      |  47 | 68.09 | 50.41 | +17.67 | 8.16  | +383  | 0.35 | 404 | +1.37 | [+194 , +569]  | [0.17 , 0.57] | 0.0108 | 0.0030 |
| **momo_v2_sol_15m_HOD**  |  36 | 55.56 | 52.00 |  +3.56 | 0.95  | +34   | 0.04 |  28 | **−1.40** | [−304 , +327]  | [−0.36 , 0.41] | **0.398** | **0.268** |

Aggregate (28d, all 11 sleeves, n = 1 285):
- sum_$ = **+$6 962** (28 d) ≈ +$249/day on $25 stakes
- 10 of 11 sleeves: binomial p < 0.02, MC p < 0.01, bootstrap sum CI strictly positive
- 1 of 11 (momo_v2_sol_15m_HOD) fails every null test → **drop or convert to research**

## Recommendations

1. **Deploy the 10 surviving sleeves** as the SHADOW spec requested. Sortino and per-trade Sharpe say the directional edge is genuine (not a fee or selection artifact). Walk-forward retention is positive on 9/10, weak (≈0) on `sniper_eth_5m_HOD`.
2. **Drop `momo_v2_sol_15m_HOD`** — WR edge 3.6 %, walk-forward sum reverses sign (train −$84 → test +$118 = noise), binomial p = 0.40 vs vwap-implied null. Bootstrap CI on `sum_$` straddles zero.
3. **Monitor `sniper_eth_5m_HOD`** — sum$ = +$729 and binom p = 0.008, but `wf_retention = 0.01` (train $725 → test $4). Most of the edge concentrated in April; treat as flag-on-decay.
4. **Top conviction**: `momo_v1_btc_15m_HOD` (75.9 % WR, 25.3 pp edge over vwap, sharpe CI lo = 0.31, wf retention 0.82) and `sniper_sol_5m_HOD` (68 % WR, 17 pp edge, both CIs strictly positive, wf retention 1.55).

## Next-step proposals (optional)

* **Joint walk-forward across all 10 surviving sleeves** — pool fills, fit a per-cell threshold for `wr_edge_pct ≥ 8 pp` on train, deploy survivors on test, report aggregate test_sum and bootstrap CI. Catches sleeves that look fine individually but lose collectively due to correlated regime breaks.
* **Permutation test on signal direction (not outcome)**: shuffle the UP/DOWN signal labels within each (cell, hour) cell and re-derive pnl from the actual outcome. This tests whether the controller's *direction* call carries information beyond hour-of-day bias.
* **Regime conditioning**: re-run with the binance-Markov state appended; check if any sleeve's edge is concentrated in a single regime (Bull vs Bear vs Sideways).
* **Live shadow comparison**: as the 11-sleeve SHADOW deploy from the TV-agent spec starts producing live fills on VPS3, ingest them into the same `fills.csv` schema and re-run this battery to catch shadow-vs-backtest divergence early.
