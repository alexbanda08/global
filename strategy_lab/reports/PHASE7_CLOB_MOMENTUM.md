# Phase 7 — CLOB Imbalance MOMENTUM

_Generated: 2026-05-04_

## Hypothesis

Phase 2 static imbalance had weak/null edge (best: ETH IC=+0.082).
The 2-min DERIVATIVE of book imbalance should capture buildup pressure,
which is more predictive than steady-state level.

## Data Schema

- File: `data/v4/refresh_2026_05_02/btc_book_depth_v3_full.csv`
- Rows: 385,858 | Unique slugs: 4,655
- Cadence: 10-second buckets (`bucket_10s`), bucket=0 at `window_start_unix`
- Top-10 levels each side, both Up & Down outcome books
- No pre-window data → signal_time must be intra-window

## Signal Construction

- Use Up-token book only; top-5 cumulative depth for imbalance
- `imb_t = (sum_bid_top5 - sum_ask_top5) / (sum_bid_top5 + sum_ask_top5)`
- 5m markets: t = bucket 12 (=120s into window); slope_2m looks back to bucket 0
- 15m markets: t = bucket 30 (=300s into window); slope_5m looks back to bucket 0
- All slugs: slope_2m = (imb_t - imb_{t-12}) / 120
- accel_2m = slope_2m(t) - slope_2m(t-6) (second derivative, ~1m offset)

## Feature Coverage

- Total slugs with features: 4,631
- 5m: 3,473
- 15m: 1,158
- Joined to outcome_up: 2,716

## IC Tables


### IC table — BTC ALL (n=2716)

| Feature | n | IC (Spearman rho) | p-value |
|---|---|---|---|
| imb_t | 2716 | -0.0643 *** | 0.0007971 |
| imb_slope_2m | 2716 | -0.0741 *** | 0.0001119 |
| imb_slope_5m | 674 | -0.0769 * | 0.04602 |
| abs_imb_t | 2716 | +0.0070  | 0.7155 |
| imb_accel_2m | 2552 | -0.0266  | 0.1795 |

### IC table — BTC 5m only (n=2038)

| Feature | n | IC (Spearman rho) | p-value |
|---|---|---|---|
| imb_t | 2038 | -0.0727 ** | 0.001026 |
| imb_slope_2m | 2038 | -0.0862 *** | 9.742e-05 |
| imb_slope_5m | 0 | n/a | n/a |
| abs_imb_t | 2038 | +0.0031  | 0.8877 |
| imb_accel_2m | 1874 | -0.0409  | 0.07678 |

### IC table — BTC 15m only (n=678)

| Feature | n | IC (Spearman rho) | p-value |
|---|---|---|---|
| imb_t | 678 | -0.0353  | 0.3593 |
| imb_slope_2m | 678 | -0.0290  | 0.4511 |
| imb_slope_5m | 674 | -0.0769 * | 0.04602 |
| abs_imb_t | 678 | +0.0170  | 0.6585 |
| imb_accel_2m | 678 | +0.0147  | 0.703 |

## Threshold Sweep — imb_slope_2m, NAIVE direction (BTC ALL)


### Threshold sweep — imb_slope_2m (n=2716)

| |feat| pct | threshold | n_fired | hit_rate |
|---|---|---|---|
| 0.50 | +0.00266618 | 1358 | 0.447 |
| 0.60 | +0.00334132 | 1087 | 0.440 |
| 0.70 | +0.00420418 | 815 | 0.428 |
| 0.80 | +0.00521666 | 544 | 0.428 |
| 0.90 | +0.00673943 | 272 | 0.401 |
| 0.95 | +0.00817511 | 136 | 0.346 |

## Threshold Sweep — imb_slope_2m, CONTRARIAN (BTC ALL)

_(IC is negative → invert sign: positive book pressure on Up early in window predicts Down outcome)_


### Threshold sweep — imb_slope_2m (CONTRARIAN: predict opposite of feature sign) (n=2716)

| |feat| pct | threshold | n_fired | hit_rate |
|---|---|---|---|
| 0.50 | +0.00266618 | 1358 | 0.553 |
| 0.60 | +0.00334132 | 1087 | 0.560 |
| 0.70 | +0.00420418 | 815 | 0.572 |
| 0.80 | +0.00521666 | 544 | 0.572 |
| 0.90 | +0.00673943 | 272 | 0.599 |
| 0.95 | +0.00817511 | 136 | 0.654 |

## Threshold Sweep — imb_t static, NAIVE (BTC ALL)


### Threshold sweep — imb_t (n=2716)

| |feat| pct | threshold | n_fired | hit_rate |
|---|---|---|---|
| 0.50 | +0.240375 | 1358 | 0.457 |
| 0.60 | +0.303745 | 1087 | 0.443 |
| 0.70 | +0.38351 | 815 | 0.420 |
| 0.80 | +0.493401 | 544 | 0.415 |
| 0.90 | +0.616908 | 272 | 0.401 |
| 0.95 | +0.709474 | 136 | 0.397 |

## Threshold Sweep — imb_t static, CONTRARIAN (BTC ALL)


### Threshold sweep — imb_t (CONTRARIAN: predict opposite of feature sign) (n=2716)

| |feat| pct | threshold | n_fired | hit_rate |
|---|---|---|---|
| 0.50 | +0.240375 | 1358 | 0.543 |
| 0.60 | +0.303745 | 1087 | 0.557 |
| 0.70 | +0.38351 | 815 | 0.580 |
| 0.80 | +0.493401 | 544 | 0.585 |
| 0.90 | +0.616908 | 272 | 0.599 |
| 0.95 | +0.709474 | 136 | 0.603 |

## Comparison vs Phase 2

| Metric | Phase 2 (ETH static) | Phase 7 (BTC slope_2m) | Phase 7 (BTC static) |
|---|---|---|---|
| IC | +0.082 | -0.0741 (p=0.000112) | -0.0643 (p=0.000797) |
| n   | ~ETH univ | 2716 | 2716 |

## Verdict

**CONFIRMED (contrarian)**: imb_slope_2m IC (-0.0741, p=0.000112) is stronger and more significant than static imb_t IC (-0.0643, p=0.000797). Momentum DERIVATIVE beats LEVEL — the hypothesis from the research doc holds, just with opposite sign than intuition would suggest. Note: BOTH ICs are NEGATIVE — signal is CONTRARIAN. Bid-heavy book on Up token early in the window predicts the Up token FAILS to settle. Likely retail-dump-into-strength or fade-the-late-piler dynamic. To use, invert: predict UP when slope < 0.

## Artifacts

- Feature parquet: `strategy_lab\data\meta_classifier\btc_clob_momentum_v1.parquet`
- This report: `strategy_lab\reports\PHASE7_CLOB_MOMENTUM.md`