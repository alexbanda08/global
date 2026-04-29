# V13A Range Kalman (ETH 1h) — Robustness Verdict

Audit date: 2026-04-20
Script: `strategy_lab/robust_validate_v13a.py`
CSVs: `strategy_lab/results/v13a/`

Params: alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800, ATR stops (tp=5.0, sl=2.0, trail=3.5, max_hold=72).

## Results

| Test | Outcome | Pass? |
|---|---|:-:|
| 1. Cross-asset | ETH sharpe 0.93 · BTC 0.36 · SOL 0.11 (CAGR +19 %/+5 %/-4 %) | Partial |
| 2. Monte-Carlo shuffle (1000×) | real_final quantile 88 % · real_DD quantile 6 % (DD 19.4 % vs sim-median 26.9 %) | Yes |
| 3. Random 2-yr windows (200) | 100 % profitable · 79 % sharpe>0.5 · median sharpe 0.85 · worst DD 27 % | Yes |
| 4. 5-fold CV | all 5 folds profitable · sharpe 0.41→1.56 · DD 7→23 % | Yes |
| 5. Parameter-ε (81 configs) | 100 % profitable · 100 % sharpe>0.5 · range [0.58, 1.17] · worst DD 41 % | Yes |

**Score: 4.5 / 5.** Parity with the 4h winners (BTC V4C & ETH V3B each 5/5; SOL V2B 4/5).

## Interpretation

- **Edge is real and ETH-specific.** MC shuffle shows the real equity curve is in the top 12 % of random-orderings and real DD is in the bottom 6 % — the edge isn't trade-order luck.
- **Stable across time.** All 5 disjoint time-folds profitable, all 200 random 2-year windows profitable.
- **Stable across params.** 81 neighbour configs all profitable with sharpe > 0.5 — no knife-edge fit.
- **Does not generalize off-asset**, but the 4h V3B ADX-gate also fails on BTC and was still shipped as the ETH winner. Same reasoning applies.

## Decision

**Add V13A (ETH 1h) to the live portfolio alongside the 4h winners.** Recommended allocation: small (~20–25 % of ETH bucket) until forward-test data exists.

Best neighbour config if retuning: `alpha=0.07, rng_len=400, rng_mult=2.5, regime_len=800` → sharpe 1.17, CAGR 27.8 %, DD 22.4 %. Essentially identical to defaults — no retune needed.
