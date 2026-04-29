# Kronos FT — BTC Combined-Filter Strategy (V3)

Source: `strategy_lab/results/kronos/ft_sniff_BTCUSDT_5m_3y_polymarket_short.csv`
Test window: 2026-01-08 → 2026-03-31 (82 days, ~6 forecasts/day sampled)
Good hours (UTC): [8, 10, 11, 12, 14, 17, 18, 19, 20, 22]
Good days: Monday-Friday + Sunday (exclude Saturday)

## Filter cascade — accuracy vs sample count

| Strategy | n | Acc | 95% CI | EV@95% payout | EV@90% payout |
|---|---|---|---|---|---|
| baseline (no filter) | 498 | 0.572 | [0.528, 0.615] | +0.116 | +0.087 |
| conf top 25% | 125 | 0.632 | [0.544, 0.720] | +0.232 | +0.201 |
| hour only | 235 | 0.655 | [0.592, 0.715] | +0.278 | +0.245 |
| dow only | 429 | 0.587 | [0.543, 0.634] | +0.145 | +0.116 |
| hour + dow | 202 | 0.693 | [0.629, 0.757] | +0.351 | +0.317 |
| conf25 + hour | 60 | 0.700 | [0.583, 0.817] | +0.365 | +0.330 |
| conf25 + dow | 108 | 0.630 | [0.537, 0.722] | +0.228 | +0.196 |
| conf25 + hour + dow | 54 | 0.704 | [0.574, 0.815] | +0.372 | +0.337 |
| conf top 10% + hour + dow | 20 | 0.700 | [0.500, 0.900] | +0.365 | +0.330 |

EV computed as: acc × payout − (1 − acc). Positive EV = profitable.

## Monthly stability — Combined filter (conf + hour + dow)

| Month | n | Acc |
|---|---|---|
| 2026-01 | 9 | 0.778 |
| 2026-02 | 22 | 0.636 |
| 2026-03 | 23 | 0.739 |

## Monthly stability — Hour + DOW filter only (no confidence threshold)

| Month | n | Acc |
|---|---|---|
| 2026-01 | 57 | 0.719 |
| 2026-02 | 72 | 0.667 |
| 2026-03 | 73 | 0.699 |

## Live-trading projection

Test slice sampled 500 windows from 82 days = ~6 forecasts/day.
If live model runs every 5m, that's 288 forecasts/day (48× more).

| Strategy | Sampled bets | Per-day bets | Per-day bets (live 5m) |
|---|---|---|---|
| baseline (no filter) | 498 | 6.07 | 291.5 |
| conf top 25% | 125 | 1.52 | 73.2 |
| hour only | 235 | 2.87 | 137.6 |
| dow only | 429 | 5.23 | 251.1 |
| hour + dow | 202 | 2.46 | 118.2 |
| conf25 + hour | 60 | 0.73 | 35.1 |
| conf25 + dow | 108 | 1.32 | 63.2 |
| conf25 + hour + dow | 54 | 0.66 | 31.6 |
| conf top 10% + hour + dow | 20 | 0.24 | 11.7 |

## Recommended trading spec

**Entry:** 5m BTC forecast on finetuned Kronos →
   IF `hour_utc ∈ [8, 10, 11, 12, 14, 17, 18, 19, 20, 22]`
   AND `weekday ≠ Saturday`
   AND `|pred_ret|` in top 25% of recent predictions
   THEN bet `sign(pred_ret)` on the 5-min Polymarket up/down market.

**Expected accuracy:** 70.4% (95% CI [57.4%, 81.5%])
**Expected EV/bet (5% spread):** +0.372 per $1 staked
**Expected live bet rate:** ~32 bets/day
**Caveat:** based on 54 test samples. CI is wide — monitor first 100 live bets carefully before scaling.
