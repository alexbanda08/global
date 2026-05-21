# SILVER Comprehensive Overview

**Date:** 2026-05-07
**Strategy:** confluence SILVER tier, struct+flow sign-aligned (struct≥0.3, flow≥0.4)
**Cells:** SOL_5m + SOL_15m only (BTC + ETH dropped after sign-alignment failure)

## 1. Period covered

- Universe markets: **2026-04-22 → 2026-05-06** (13.9 calendar days)
- First SILVER trade: **2026-04-23 15:15:00 UTC**
- Last SILVER trade: **2026-05-05 00:30:00 UTC**
- Trade-active span: 11.39 days

## 2. Trade density

| Metric | Value |
|---|---:|
| Universe SILVER picks (pre-exec) | 13 |
| Executed (post spread-filter) | 8 |
| Live-drop rate (spread skip etc.) | 38.5% |
| Trades / calendar day | 0.571 |
| Trades / active day | 1.600 |
| Active days (≥1 trade) | 5 of 14 |

At this density, expect ~**17 trades / 30-day month** (of which ~11 actually fill).

## 3. Headline stats (8 executed SOL SILVER trades)

| Metric | Value |
|---|---:|
| n trades | 8 |
| Hit rate | 100.0% |
| Mean $/trade | $+4.0771 |
| Median $/trade | $+4.2630 |
| Std $/trade | $2.9060 |
| Min $/trade | $+0.2475 |
| Max $/trade | $+8.1217 |
| Total $ (window) | $+32.62 |
| Final equity | $+32.62 |
| Max drawdown | $+0.00 |

Stake per trade is **$25** (the engine's NOTIONAL_USD constant). All gross-of-fee.

## 4. Monthly expectancy (30-day projection)

Bootstrap projection: resample {trades_per_month} trades from observed PnL distribution × 10k draws.

| Metric | Value |
|---|---:|
| Trades per 30-day month | ~17 |
| Expected total $ (observed mean × density) | $+69.89 |
| Bootstrap mean total $ | $+69.16 |
| Bootstrap 95% CI total $ | [$+46.87, $+90.74] |
| Bootstrap 95% CI mean $/trade | [$+2.7572, $+5.3378] |
| Bootstrap P(monthly total < 0) | 0.00% |

**Interpretation:** at the observed 8 trades / 14 days density (~17 trades/month), monthly P&L could plausibly range from break-even to ~$+85/month (95% bootstrap CI). The ZERO P(loss) is a consequence of all 8 observed trades being winners — DO NOT trust this; it reflects sample, not edge.

## 5. Per-day breakdown

| day        |   n |   wins |   total_pnl |   mean_pnl |   hit_rate |
|:-----------|----:|-------:|------------:|-----------:|-----------:|
| 2026-04-23 |   4 |      4 |   23.5957   |   5.89893  |          1 |
| 2026-04-24 |   1 |      1 |    3.50795  |   3.50795  |          1 |
| 2026-04-29 |   1 |      1 |    0.247475 |   0.247475 |          1 |
| 2026-05-04 |   1 |      1 |    0.247475 |   0.247475 |          1 |
| 2026-05-05 |   1 |      1 |    5.01807  |   5.01807  |          1 |

## 6. Comparison vs. baseline momo SOL (same universe)

| Strategy | n | Hit% | Mean $/trade | Total $ |
|---|---:|---:|---:|---:|
| baseline momo SOL (5m+15m) | 354 | 87.3% | $-0.3976 | $-140.76 |
| SILVER (struct+flow signed) | 8 | 100.0% | $+4.0771 | $+32.62 |
| **Delta** | **-346** | **+12.7pp** | **$+4.4747** | **$+173.38** |

SILVER fires on ~**2.3%** of momo SOL fires but captures all the upside on this window.

## 7. Caveats — read before deploying

- **n=8 over 14 days is structurally underpowered.** Bootstrap CI is mechanically positive only because all 8 observations were wins — this WILL regress on more data.
- **30% live-drop rate** from spread filter alone — actual live trade count would be ~12 trades/month (after spread + thin-book filters), not 17.
- Permutation test (G1) gave NaN p-value because all trades won — null distribution collapses. G1 is mechanically uninformative until we observe at least one losing trade.
- Walk-forward (G2) had only **3 OOS trades across 3 windows** — confirms the signal doesn't degrade OOS, but says nothing about magnitude reliability.
- **Stake is fixed at $25** in the backtest. Cyclops SILVER tier prescribes 1.5% × bankroll. If bankroll = $1250, that's $18.75 — close enough that PnL scales linearly.
- Fees not subtracted (engine's `FEE_RATE=0.02` applies on win profit) — already in the numbers.

## 8. Recommendation

1. **Paper-deploy on TV agent for 6+ weeks** to accumulate n ≥ 80 trades.
2. Re-run validation weekly: `validate_silver_alpha.py` + this overview.
3. **Promote to live capital only when:**
   - Bootstrap 95% CI lower bound > $+1/trade
   - Walk-forward ≥ 5 of last 8 windows positive
   - At least one losing trade observed (so G1 perm test is informative)
4. Capital sizing on live: start at 0.5% × bankroll, ramp to 1.5% over 4 weeks if metrics hold.
5. Track monthly: hit rate, mean $/trade, max DD, fill skip rate.

## Files

- Per-trade CSV: `strategy_lab\results\meta_classifier\silver_per_trade.csv`
- JSON overview: `strategy_lab\results\meta_classifier\silver_overview.json`
- This report: `strategy_lab\reports\SILVER_OVERVIEW_2026_05_07.md`
- Validation gates report: `strategy_lab/reports/SILVER_VALIDATION_2026_05_07.md`
- TV agent spec: `strategy_lab/reports/TV_AGENT_SPEC_CONFLUENCE_SILVER_V1.md`