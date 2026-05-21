# Momo Realfill Validation — L25 raw vs L10 bucketed exit-monitoring

**Generated:** 2026-05-06

**Scope:** Re-runs the existing momo backtest's HEDGE and SELL exit policies but replaces the 10s-bucketed L10 exit-monitoring book with the snapshot-precise L25 raw book pulled from VPS2 on 2026-05-06.

**Question answered:** *would HEDGE / SELL exits actually have liquidity in the real production orderbook at the rev_bp trigger time?*

**Reused infrastructure:**

- `book_walk.book_walk_fill` (canonical fill simulator)
- `polymarket_stats.equity_curve_stats` (Sharpe/Sortino/MaxDD)
- `extended_backtest_with_robustness.{load_klines, load_tier1_entries, sell_at_bid}`
- `loaders.raw_orderbook_l25.{load_orderbook_l25_raw, OrderbookIndex}` (NEW)

## Cell-level results

| Cell | n | hit% | total PnL | mean PnL | hedge | sell | rev_n | feasible% | snap_p50 ms | snap_p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m_HOLD | 337 | 91.1 | $+92.02 | $+0.2731 | 0 | 0 | 0 | — | 0 | 0 |
| BTC_5m_HEDGE | 337 | 68.0 | $+19.18 | $+0.0569 | 122 | 0 | 122 | 100.0 | 0 | 277 |
| BTC_5m_SELL | 337 | 68.0 | $+34.01 | $+0.1009 | 0 | 122 | 122 | 100.0 | 0 | 277 |
| BTC_15m_HOLD | 113 | 74.3 | $-157.46 | $-1.3934 | 0 | 0 | 0 | — | 0 | 0 |
| BTC_15m_HEDGE | 113 | 40.7 | $-9.64 | $-0.0853 | 69 | 0 | 69 | 100.0 | 97 | 1902 |
| BTC_15m_SELL | 113 | 40.7 | $+6.93 | $+0.0613 | 0 | 69 | 69 | 100.0 | 97 | 1902 |
| ETH_5m_HOLD | 291 | 95.5 | $+283.66 | $+0.9748 | 0 | 0 | 0 | — | 0 | 0 |
| ETH_5m_HEDGE | 291 | 67.7 | $+86.42 | $+0.2970 | 112 | 0 | 112 | 100.0 | 0 | 3604 |
| ETH_5m_SELL | 291 | 67.7 | $+96.55 | $+0.3318 | 0 | 112 | 112 | 100.0 | 0 | 3604 |
| ETH_15m_HOLD | 103 | 81.6 | $+33.08 | $+0.3212 | 0 | 0 | 0 | — | 0 | 0 |
| ETH_15m_HEDGE | 103 | 45.6 | $+28.87 | $+0.2803 | 64 | 0 | 64 | 100.0 | 351 | 11545 |
| ETH_15m_SELL | 103 | 45.6 | $+40.35 | $+0.3918 | 0 | 64 | 64 | 100.0 | 351 | 11545 |
| SOL_5m_HOLD | 260 | 90.8 | $-65.78 | $-0.2530 | 0 | 0 | 0 | — | 0 | 0 |
| SOL_5m_HEDGE | 260 | 67.3 | $-32.55 | $-0.1252 | 94 | 0 | 94 | 100.0 | 0 | 7234 |
| SOL_5m_SELL | 260 | 68.1 | $-21.12 | $-0.0812 | 0 | 94 | 94 | 100.0 | 0 | 7234 |
| SOL_15m_HOLD | 94 | 77.7 | $-74.98 | $-0.7977 | 0 | 0 | 0 | — | 0 | 0 |
| SOL_15m_HEDGE | 94 | 41.5 | $-27.43 | $-0.2918 | 60 | 0 | 60 | 100.0 | 1666 | 19435 |
| SOL_15m_SELL | 94 | 42.6 | $-13.43 | $-0.1429 | 0 | 60 | 60 | 100.0 | 1666 | 19435 |

## L25 vs L10 backtest comparison

| Cell | L25 n | L25 PnL | L25 hit% | L10 n | L10 PnL | L10 hit% | Δ PnL | Δ hit% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m_HOLD | 337 | $+92.02 | 91.1 | 337 | $+92.02 | 91.1 | $+0.00 | +0.0 |
| BTC_5m_HEDGE | 337 | $+19.18 | 68.0 | 337 | $-26.22 | 73.0 | $+45.39 | -5.0 |
| BTC_5m_SELL | 337 | $+34.01 | 68.0 | 337 | $-12.71 | 73.0 | $+46.72 | -5.0 |
| BTC_15m_HOLD | 113 | $-157.46 | 74.3 | 113 | $-157.46 | 74.3 | $+0.00 | +0.0 |
| BTC_15m_HEDGE | 113 | $-9.64 | 40.7 | 113 | $-49.82 | 45.1 | $+40.18 | -4.4 |
| BTC_15m_SELL | 113 | $+6.93 | 40.7 | 113 | $-35.02 | 46.0 | $+41.95 | -5.3 |
| ETH_5m_HOLD | 291 | $+283.66 | 95.5 | 291 | $+283.66 | 95.5 | $+0.00 | +0.0 |
| ETH_5m_HEDGE | 291 | $+86.42 | 67.7 | 291 | $+86.30 | 71.8 | $+0.12 | -4.1 |
| ETH_5m_SELL | 291 | $+96.55 | 67.7 | 291 | $+93.17 | 72.2 | $+3.38 | -4.5 |
| ETH_15m_HOLD | 103 | $+33.08 | 81.6 | 103 | $+33.08 | 81.6 | $+0.00 | +0.0 |
| ETH_15m_HEDGE | 103 | $+28.87 | 45.6 | 103 | $+16.65 | 49.5 | $+12.22 | -3.9 |
| ETH_15m_SELL | 103 | $+40.35 | 45.6 | 103 | $+25.94 | 49.5 | $+14.42 | -3.9 |
| SOL_5m_HOLD | 260 | $-65.78 | 90.8 | 260 | $-65.78 | 90.8 | $+0.00 | +0.0 |
| SOL_5m_HEDGE | 260 | $-32.55 | 67.3 | 260 | $-35.78 | 71.9 | $+3.23 | -4.6 |
| SOL_5m_SELL | 260 | $-21.12 | 68.1 | 260 | $-23.07 | 72.3 | $+1.95 | -4.2 |
| SOL_15m_HOLD | 94 | $-74.98 | 77.7 | 94 | $-74.98 | 77.7 | $+0.00 | +0.0 |
| SOL_15m_HEDGE | 94 | $-27.43 | 41.5 | 94 | $-15.44 | 48.9 | $-11.99 | -7.4 |
| SOL_15m_SELL | 94 | $-13.43 | 42.6 | 94 | $-3.97 | 48.9 | $-9.46 | -6.4 |

## Liquidity feasibility analysis

**Definition:** for HEDGE cells, `feasible_pct` = % of fires where, at the FIRST rev_bp trigger, 
the opposite-side ask book had ≥1 valid (price ∈ (0,1)) level. Same for SELL on own-side bids.

- **HEDGE feasible (avg across cells)**: 100.0%
- **SELL feasible (avg across cells)**: 100.0%

## Snap staleness

**Definition:** at each rev_bp trigger, we look up the L25 snapshot at-or-before the trigger second. `snap_staleness_ms` is `trigger_ts − snap_ts` in milliseconds. P95 of the per-trade max staleness across the cell tells us how stale the production controller's view of the book would be at decision time.

## Files

- Per-cell: `strategy_lab/results/meta_classifier/momo_realfill_validation.csv`
- Per-trade: `strategy_lab/results/meta_classifier/momo_realfill_pertrade.csv`
- This report: `strategy_lab/reports/MOMO_REALFILL_VALIDATION_2026_05_06.md`
