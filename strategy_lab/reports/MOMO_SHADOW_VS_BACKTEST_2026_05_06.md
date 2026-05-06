# Momo Shadow vs Backtest @ +11.9h

**Generated:** 2026-05-06 12:20 UTC  
**Deploy:** 2026-05-06 00:28 UTC  
**Source:** `data\v4\shadow_trades_2026_05_06\momo_resolutions.csv` (72 resolutions)

## Headline

- Total fires (resolutions): **72**
- Combined paper PnL: **$+229.66**
- Profitable (asset,tf) cells: **3/6**
- BTC_5m hit rate: **0.333** (n=9) vs backtest 0.892
- Worst (cell,exit) PnL: **$-21.68**

## Pass/Fail Scoring (spec §7, scaled to elapsed time)

Time-scaling factor: **0.248** (11.9h / 48h target)

| Metric | Shadow | Pass thresh (scaled) | Fail thresh (scaled) | Verdict |
|---|---:|---:|---:|---|
| Total fires | 72 | 24+ | <14 | PASS |
| Combined PnL | $+229.66 | +$198.03+ | <+$49.51 | PASS |
| Profitable cells | 3/6 | 4+ | ≤2 | MARGINAL |
| BTC_5m hit | 0.333 (n=9) | ≥0.75 | <0.65 | N/A (insufficient sample) |
| Worst cellxexit | $-21.68 | >-$74.26 | <-$123.77 | PASS |

> **INTERIM at +11.9h.** Spec §7 decision is at +24h or +48h. This is a directional read.

**OVERALL: MARGINAL** — keep shadow running, recheck at next checkpoint.

## Per-Cell Detail (Shadow vs Backtest)

| Cell | n_sh | hit_sh | pnl_sh | pnl_mean_sh | n_bt | hit_bt | pnl_mean_bt | mean_ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m_HOLD | 3 | 0.333 | $-21.68 | $-7.23 | 325 | 0.892 | $+14.48 | -0.50x |
| BTC_5m_HEDGE | 3 | 0.333 | $-21.68 | $-7.23 | 325 | 0.923 | $+15.78 | -0.46x |
| BTC_5m_SELL | 3 | 0.333 | $-21.68 | $-7.23 | 325 | 0.923 | $+15.82 | -0.46x |
| BTC_15m_HOLD | 0 | 0.000 | $+0.00 | $+0.00 | 108 | 0.824 | $+9.42 | +0.00x |
| BTC_15m_HEDGE | 0 | 0.000 | $+0.00 | $+0.00 | 108 | 0.815 | $+9.32 | +0.00x |
| BTC_15m_SELL | 0 | 0.000 | $+0.00 | $+0.00 | 108 | 0.815 | $+9.46 | +0.00x |
| ETH_5m_HOLD | 4 | 0.500 | $-0.98 | $-0.24 | 294 | 0.922 | $+12.58 | -0.02x |
| ETH_5m_HEDGE | 4 | 0.500 | $-0.98 | $-0.24 | 294 | 0.932 | $+13.10 | -0.02x |
| ETH_5m_SELL | 4 | 0.500 | $-0.98 | $-0.24 | 294 | 0.935 | $+13.14 | -0.02x |
| ETH_15m_HOLD | 1 | 1.000 | $+21.87 | $+21.87 | 101 | 0.743 | $+5.44 | +4.02x |
| ETH_15m_HEDGE | 1 | 1.000 | $+21.87 | $+21.87 | 101 | 0.851 | $+7.89 | +2.77x |
| ETH_15m_SELL | 1 | 1.000 | $+21.87 | $+21.87 | 101 | 0.871 | $+8.08 | +2.71x |
| SOL_5m_HOLD | 15 | 0.600 | $+54.21 | $+3.61 | 252 | 0.893 | $+11.20 | +0.32x |
| SOL_5m_HEDGE | 15 | 0.600 | $+54.21 | $+3.61 | 252 | 0.909 | $+12.84 | +0.28x |
| SOL_5m_SELL | 15 | 0.600 | $+56.22 | $+3.75 | 252 | 0.913 | $+12.93 | +0.29x |
| SOL_15m_HOLD | 1 | 1.000 | $+22.46 | $+22.46 | 71 | 0.845 | $+9.69 | +2.32x |
| SOL_15m_HEDGE | 1 | 1.000 | $+22.46 | $+22.46 | 71 | 0.789 | $+9.02 | +2.49x |
| SOL_15m_SELL | 1 | 1.000 | $+22.46 | $+22.46 | 71 | 0.803 | $+9.15 | +2.46x |

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
