# Momo Shadow vs Backtest @ +22.8h

**Generated:** 2026-05-06 23:14 UTC  
**Deploy:** 2026-05-06 00:28 UTC  
**Source:** `data\v4\shadow_trades_2026_05_06\momo_resolutions.csv` (72 resolutions)

## Headline

- Total fires (resolutions): **72**
- Combined paper PnL: **$+229.66**
- Profitable (asset,tf) cells: **3/6**
- BTC_5m hit rate: **0.333** (n=9) vs backtest 0.892
- Worst (cell,exit) PnL: **$-21.68**

## Pass/Fail Scoring (spec §7, scaled to elapsed time)

Time-scaling factor: **0.474** (22.8h / 48h target)

| Metric | Shadow | Pass thresh (scaled) | Fail thresh (scaled) | Verdict |
|---|---:|---:|---:|---|
| Total fires | 72 | 47+ | <28 | PASS |
| Combined PnL | $+229.66 | +$379.50+ | <+$94.88 | MARGINAL |
| Profitable cells | 3/6 | 4+ | ≤2 | MARGINAL |
| BTC_5m hit | 0.333 (n=9) | ≥0.75 | <0.65 | N/A (insufficient sample) |
| Worst cellxexit | $-21.68 | >-$142.31 | <-$237.19 | PASS |

> **INTERIM at +22.8h.** Spec §7 decision is at +24h or +48h. This is a directional read.

**OVERALL: MARGINAL** — keep shadow running, recheck at next checkpoint.

## Per-Cell Detail (Shadow vs Backtest)

| Cell | n_sh | hit_sh | pnl_sh | pnl_mean_sh | n_bt | hit_bt | pnl_mean_bt | mean_ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m_HOLD | 3 | 0.333 | $-21.68 | $-7.23 | 337 | 0.911 | $+0.27 | -26.46x |
| BTC_5m_HEDGE | 3 | 0.333 | $-21.68 | $-7.23 | 337 | 0.730 | $-0.08 | +92.87x |
| BTC_5m_SELL | 3 | 0.333 | $-21.68 | $-7.23 | 337 | 0.730 | $-0.04 | +191.55x |
| BTC_15m_HOLD | 0 | 0.000 | $+0.00 | $+0.00 | 113 | 0.743 | $-1.39 | -0.00x |
| BTC_15m_HEDGE | 0 | 0.000 | $+0.00 | $+0.00 | 113 | 0.451 | $-0.44 | -0.00x |
| BTC_15m_SELL | 0 | 0.000 | $+0.00 | $+0.00 | 113 | 0.460 | $-0.31 | -0.00x |
| ETH_5m_HOLD | 4 | 0.500 | $-0.98 | $-0.24 | 291 | 0.955 | $+0.97 | -0.25x |
| ETH_5m_HEDGE | 4 | 0.500 | $-0.98 | $-0.24 | 291 | 0.718 | $+0.30 | -0.82x |
| ETH_5m_SELL | 4 | 0.500 | $-0.98 | $-0.24 | 291 | 0.722 | $+0.32 | -0.76x |
| ETH_15m_HOLD | 1 | 1.000 | $+21.87 | $+21.87 | 103 | 0.816 | $+0.32 | +68.10x |
| ETH_15m_HEDGE | 1 | 1.000 | $+21.87 | $+21.87 | 103 | 0.495 | $+0.16 | +135.28x |
| ETH_15m_SELL | 1 | 1.000 | $+21.87 | $+21.87 | 103 | 0.495 | $+0.25 | +86.85x |
| SOL_5m_HOLD | 15 | 0.600 | $+54.21 | $+3.61 | 260 | 0.908 | $-0.25 | -14.28x |
| SOL_5m_HEDGE | 15 | 0.600 | $+54.21 | $+3.61 | 260 | 0.719 | $-0.14 | -26.26x |
| SOL_5m_SELL | 15 | 0.600 | $+56.22 | $+3.75 | 260 | 0.723 | $-0.09 | -42.24x |
| SOL_15m_HOLD | 1 | 1.000 | $+22.46 | $+22.46 | 94 | 0.777 | $-0.80 | -28.16x |
| SOL_15m_HEDGE | 1 | 1.000 | $+22.46 | $+22.46 | 94 | 0.489 | $-0.16 | -136.77x |
| SOL_15m_SELL | 1 | 1.000 | $+22.46 | $+22.46 | 94 | 0.489 | $-0.04 | -531.57x |

## Per (asset, tf) cell totals (across exits)

| Cell | combined_pnl |
|---|---:|
| BTC_5m | $-65.03 |
| ETH_15m | $+65.61 |
| ETH_5m | $-2.94 |
| SOL_15m | $+67.38 |
| SOL_5m | $+164.63 |

## ContextVar bug fix verification

Per VPS3 query at run time:
- 72 FILLED rows, 69 with all 4 enrichment fields (entry_phase, ret_2m_at_signal, abs_ret_2m_threshold, bar_ctx_age_ms)
- 3 missing rows are all from 2026-05-06 02:57:05+02 (= 00:57 UTC) — first SOL trade, **pre-fix** (deploy was 00:28 UTC, fix landed shortly after).
- Post-fix: **69/69 = 100%** complete enrichment.
- bar_ctx_age_ms on FILLED: min=12, p50=51, p95=257, p99=318, max=321 ms.
- (Higher than NONE p95 of <25ms because FILLED row is stamped after order placement; entry_phase still 't_plus_120' on all 69.)
