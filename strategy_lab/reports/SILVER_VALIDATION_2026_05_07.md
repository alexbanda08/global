# SILVER Alpha Validation — 5-Gate Battery

**Date:** 2026-05-07
**Strategy:** SILVER tier (struct+flow sign-aligned, struct≥0.3, flow≥0.4)
**Cells:** ('btc', 'eth', 'sol')
**Headline:** n=85  hit=76.5%  mean=$-2.7543  total=$-234.11

## Gate verdicts

| Gate | Test | Pass? | Detail |
|---|---|---|---|
| G1 | Permutation (10k draws), p<0.05 | FAIL | p=0.4562 |
| G2 | Walk-forward, OOS mean>0 + ≥half windows positive | FAIL | OOS mean=$-4.4148, 1/5 pos windows |
| G3 | Bootstrap 95% CI excludes zero | FAIL | CI=[$-5.4971, $-0.1969] |
| G4 | Regression coefficient sig, p<0.10 | FAIL | struct_p=0.873, flow_p=0.692 |
| G5 | Realfill execution viable | INFO | thin/spread skip rates per asset |

## Overall: **UNCONFIRMED — sample underpowered**

## Headline

- n trades: 85
- hit rate: 76.5%
- mean $/trade: $-2.7543
- total $: $-234.11

## G1 — Permutation (10k draws, shuffle outcomes)

- p-value: **0.4562**
- observed total: $-234.11
- null distribution: mean=$-234.73, q975=$-30.48, max=$+144.07

## G2 — Walk-forward (rolling 5d train / 2d test)

- windows: 5
- OOS trades: 64
- OOS mean $/trade: $-4.4148
- OOS total $: $-282.55
- positive windows: 1/5

## G3 — Bootstrap (10k resamples, 95% CI on mean $/trade)

- observed mean: $-2.7543
- 95% CI: [$-5.4971, $-0.1969]
- 99% CI: [$-6.4127, $+0.5976]
- P(mean < 0): 0.983

## G4 — Regression (won ~ struct_signed + flow_signed, logistic)

- n: 85
- intercept: 0.4455
- coef struct_signed: 0.2132 (SE=1.3296, p=0.873)
- coef flow_signed: 1.1418 (SE=2.8849, p=0.692)
- 

## G5 — Realfill (engine uses L25 raw book at entry — that IS realfill)

Per-asset:

- **btc**: n=55, hit=74.5%, mean_pnl=$-3.4340, avg_vwap_entry=$0.8429, skipped_thin=0, skipped_spread=3
- **eth**: n=22, hit=72.7%, mean_pnl=$-3.5391, avg_vwap_entry=$0.8433, skipped_thin=0, skipped_spread=4
- **sol**: n=8, hit=100.0%, mean_pnl=$+4.0771, avg_vwap_entry=$0.8653, skipped_thin=0, skipped_spread=4

## Notes

- Engine: `extended_backtest_with_robustness.simulate()` walks L25 raw book via `book_walk_fill` — slippage and entry vwap reflect realistic execution.
- All 5 gates use SAME per-trade pnl set as the headline (no policy change).
- Walk-forward uses fixed thresholds (no parameter refit) — pure OOS test.
- Sample size is the dominant constraint. n<30 makes all gates structurally weak.

## Reproduction

```bash
py -X utf8 -m strategy_lab.confluence.validate_silver_alpha           # SOL only
py -X utf8 -m strategy_lab.confluence.validate_silver_alpha --include-eth-15m
py -X utf8 -m strategy_lab.confluence.validate_silver_alpha --include-all
```