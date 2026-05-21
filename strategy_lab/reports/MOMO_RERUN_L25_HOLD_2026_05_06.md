# Momo Re-run on 2026-05-06 dataset — HOLD baseline (25-level entry books)

**Generated:** 2026-05-06 22:50 UTC  
**Source:** `data/v4/refresh_2026_05_06/`  
**Strategy:** momo gate (q90 |ret_2m|, 14d trailing) → top-25 ASK walk → $25 notional → HOLD to chainlink.  
**Fee model:** 2% on profit only.

## Pipeline counts

- universe (resolved markets): **9618**
- with finite ret_2m: **9618**
- below q90 gate: **7471**
- skipped (no entry book): **178**, (spread): **234**, (thin): **5**, (no thresh): **894**
- **fires: 836**

## Per-cell HOLD

| cell | n | wins | hit% | pnl_total | pnl_mean | pnl_std | sharpe | pnl_per_$1 | avg_vwap | dt_entry_us p̄ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_15m | 105 | 105 | 100.0 | $+1808.81 | $+17.2268 | 12.52 | 1.38 | $+0.6891 | 0.6323 | 312,780 |
| BTC_5m | 241 | 190 | 78.8 | $+1318.02 | $+5.4690 | 23.93 | 0.23 | $+0.2188 | 0.6770 | 101,302 |
| ETH_15m | 81 | 80 | 98.8 | $+1387.19 | $+17.1258 | 14.81 | 1.16 | $+0.6850 | 0.6316 | 1,031,456 |
| ETH_5m | 202 | 175 | 86.6 | $+2207.86 | $+10.9300 | 28.48 | 0.38 | $+0.4372 | 0.6963 | 501,356 |
| SOL_15m | 53 | 53 | 100.0 | $+963.75 | $+18.1840 | 14.72 | 1.24 | $+0.7274 | 0.6277 | 1,581,660 |
| SOL_5m | 154 | 128 | 83.1 | $+815.37 | $+5.2946 | 22.61 | 0.23 | $+0.2118 | 0.7255 | 969,551 |

## Comparison vs prior `extended_backtest.csv` (HOLD column)

Prior run (May 6 morning): 1,151 trades total, +$13,481 across 6 cells.
This run: **836** trades total, **$+8500.99**.
Differences attributable to:
- updated resolution data (post-shadow-deploy markets included)
- 25-level entry books (was already 25-level — should be ~identical)
- threshold recompute on fresh 14d windows

## Next phases (HEDGE / SELL with 25-level exits)

HOLD-only here. HEDGE/SELL paths require book snapshots during the holding window
(buckets 13-29 for 5m, 13-89 for 15m). The raw L25 gzipped CSVs in `refresh_2026_05_06/`
contain microsecond snapshots — Phase 2 will stream-aggregate these into
per-(slug, bucket, outcome) 25-level snapshots, then HEDGE/SELL/anchor-sweep tests
can run on the precision exit data.
