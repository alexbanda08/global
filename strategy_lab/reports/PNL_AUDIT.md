# PnL Audit — are the BTC_only HOLD numbers real?

_Generated: 2026-05-05_

## User's concern

BTC_only_5m HOLD reported total $+3,054, mean $+11.15, **max single-trade $+1,200.50**.

Theoretically, $25 stake at avg ask $0.51 → 49 shares → max win = $49 - $25 - 2%fee ≈ $23.50.

A $1,200 win implies ~1,250 shares filled, which means avg ask ~$0.02. Is the book actually quoting that, or is this a lookahead artifact?

## Per-trade audit

- Total trades: 302
- Wins / losses: 266 / 36
- Hit rate: 88.1%

### PnL distribution

| Stat | Raw | Winsorized (cap shares ≤ 50 = max $25 win) |
|---|---:|---:|
| Total | $-125.86 | $-125.86 |
| Mean  | $-0.4168 | $-0.4168 |
| Median | $+1.8441 | $+1.8441 |
| Std   | $9.45 | $9.45 |
| Min   | $-25.00 | $-25.00 |
| Max   | $+23.54 | $+23.54 |

### Outlier contribution

- Top 1 trade: **$+23.54** (-18.7% of total PnL)
- Top 10 trades: **$+132.17** (-105.0% of total PnL)
- All 36 losses: $-750.00

**If a single trade contributes >20% of total PnL, the strategy depends on extreme outliers.**

### Top 10 winners

| slug | sig | won | vwap_e | shares_e | usd_e | lvls | underfilled | pnl |
|---|---|---|---:|---:|---:|---:|---:|---:|
| btc-updown-5m-1777486200 | UP | ✓ | $0.5100 | 49.0 | $25.00 | 1 | False | $+23.54 |
| btc-updown-5m-1777476600 | UP | ✓ | $0.5900 | 42.4 | $25.00 | 1 | False | $+17.03 |
| btc-updown-5m-1776967200 | UP | ✓ | $0.6300 | 39.7 | $25.00 | 1 | False | $+14.39 |
| btc-updown-5m-1777485900 | DN | ✓ | $0.6609 | 37.8 | $25.00 | 3 | False | $+12.57 |
| btc-updown-5m-1776972300 | UP | ✓ | $0.6800 | 36.8 | $25.00 | 1 | False | $+11.53 |
| btc-updown-5m-1777487400 | DN | ✓ | $0.6884 | 36.3 | $25.00 | 2 | False | $+11.09 |
| btc-updown-5m-1776966900 | UP | ✓ | $0.6900 | 36.2 | $25.00 | 1 | False | $+11.01 |
| btc-updown-5m-1777860300 | UP | ✓ | $0.6900 | 36.2 | $25.00 | 1 | False | $+11.01 |
| btc-updown-5m-1777643400 | UP | ✓ | $0.7100 | 35.2 | $25.00 | 1 | False | $+10.01 |
| btc-updown-5m-1777907100 | UP | ✓ | $0.7100 | 35.2 | $25.00 | 1 | False | $+10.01 |

### Trades with `vwap_e < 0.20` (deeply mispriced YES/NO buy)

- count: **0 of 302** (0.0%)
- sum of these trades' PnL: **$+0.00** (-0.0% of total)
- if ALL these trades won: max possible PnL contribution = $+0.00

### Trades with `shares_e > 100` (avg fill price < $0.25)

- count: **0 of 302** (0.0%)
- sum: **$+0.00** (-0.0% of total)

## Vwap distribution (entry book quality)

| Bucket | count | %  |
|---|---:|---:|
| $0.00–$0.10 | 0 | 0.0% |
| $0.10–$0.20 | 0 | 0.0% |
| $0.20–$0.30 | 0 | 0.0% |
| $0.30–$0.40 | 0 | 0.0% |
| $0.40–$0.50 | 0 | 0.0% |
| $0.50–$0.60 | 3 | 1.0% |
| $0.60–$0.70 | 7 | 2.3% |
| $0.70–$0.80 | 25 | 8.3% |
| $0.80–$0.90 | 74 | 24.5% |
| $0.90–$1.00 | 193 | 63.9% |

## Verdict

✅ Outlier impact is bounded: top-10 trades contribute -105% of total PnL. The strategy edge is broad-based, not carried by a few extreme entries.

## What this means for shadow projections

- **Raw backtest** assumed the orderbook quotes are real, fillable, and stable.
- **Live trading** would NOT capture deep-mispricing wins because (a) those quotes are usually stale snapshots, (b) when real, they're consumed by arbitrage bots in <1s, (c) Polymarket matching engine may slip the fill.
- **Realistic projection** = winsorized total $-125.86 on 302 trades = $-0.4168/trade. Apply this haircut to all earlier headline numbers.
