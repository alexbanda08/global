# Capstone Finding — Up/Down Market Is Efficient vs All Available Signals (2026-05-28)

The decisive result that closes the directional-prediction investigation.

## Test
Predict the chainlink outcome of BTC 5m up-down slugs at a 60s decision point,
out-of-sample (train first 60% of the 33-day window, test last 40%, n_test=2038).
Compare a multivariate model using EVERY signal we can compute against the
Polymarket price itself.

Features: Binance momentum (ret_60s, ema9_slope), cl_basis (binance vs chainlink
oracle divergence), order-flow imbalance from the **39M-row trades_polymarket tape**
(flow_imb 5s/30s/60s, net signed pressure, trade intensity), px_vs_strike, and the
de-vigged price-implied P(Up).

## Result
| predictor | OOS accuracy | OOS logloss |
|---|---|---|
| **Polymarket price-implied (baseline)** | **65.7%** | **0.6153** |
| Logistic regression (all features) | 65.3% | 0.6178 |
| Gradient boosting (all features) | 64.7% | 0.6293 |

- Adding momentum + cl_basis + order-flow + intensity does **NOT** beat the price.
  GBM feature importance: price `up_prob` = 0.60 (dominant); every other signal ≈ 0.04–0.07
  and collectively add nothing OOS (logloss gets worse → overfit).
- Where the model disagrees with the price (model P(Up)>0.6 while price<0.5): n=24,
  realized Up rate 54.2% — a coin flip. The price wins.

Earlier single-signal blind backtests (full 33-day, gate battery) all agreed:
momentum, favorite, underdog, cheap-momentum, loose cl_basis, follow/fade-flow —
**every one sits at WR ≈ entry price → net-negative after fees, fails G1/G4/walk-forward/plateau.**
Order-flow imbalance does not even predict direction (48% accuracy, slightly contrarian).
The only blind rule that ever passed all gates was cl_basis EXTREME-divergence on
btc-5m (~2 profitable fires/day) — a thin tail, which the user passed on.

## Conclusion
**The Polymarket up-down price is an efficient, near-optimal estimator of the
outcome.** No signal in our data (Binance 1s, Chainlink RTDS, full L25 book, the
39M-trade order-flow tape, technical indicators) improves on it out-of-sample.

Therefore the high-WR / profitable wallets we cataloged are **NOT predicting
direction better than the market.** Their edge is **EXECUTION, not prediction**:
1. They are makers / limit-order traders filled BELOW fair value — capturing the
   bid-ask spread (and maker rebate), not paying the taker spread our $25-taker
   model pays. Our backtest charges the taker walk; theirs earns it.
2. High WR = buying favorites (≈65% base hit rate at this horizon) + better fills.
   The cash edge is the spread captured, not alpha.

This is why every wallet's apparent edge evaporated under blind, taker-priced,
gate-tested replication: we were modeling the wrong side of the trade.

## Implication — stop chasing a directional signal; pursue execution
The deployable path is a **MAKER strategy**, not a directional taker:
- Post limit orders on the favored side (or both sides) BELOW the current ask;
  get filled at a better-than-fair price; the edge = captured spread + rebate.
- This is the mint-and-sell / pair-arb / market-making family already in the repo
  (`CLAUDE.md` §"Mint-and-sell maker V2", `fast_full_backtest.py`), NOT directional
  prediction. Re-point effort there.
- Directional prediction from price/flow data is a dead end on these markets —
  proven across 6 markets × 8 strategies × full gate battery × a multivariate OOS model.

## Artifacts
- Order-flow tooling: `strategy_lab/directional_signal/flow_features.py`
  (+ `data/v4/canonical/_results/dirflow_btc_5m.parquet`)
- Backtest + gates: `directional_scan.py`, `eval_strategies.py`, `dir_eval_results.csv`
- Wallet registry: `_directional_wallet_registry.csv`, `WALLET_REGISTRY_2026_05_28.md`
- Prior reports: DIRECTIONAL_BACKTEST_GATES, DECODE_SYNTHESIS, DECODE_* (all _2026_05_28)
