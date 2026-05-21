# MICRO Tier Backtest — SOL Universe

**Date:** 2026-05-07  |  **Universe:** SOL 2026-04-22 → 2026-05-06  |  **Engine:** $25/trade HOLD

## TL;DR

MICRO adds 30 trades with positive mean $+1.0201 but p=0.415 (not significant). Likely noise at n=30.

## Tier definitions

| Tier | Rule |
|---|---|
| SILVER | struct_signed ≥ 0.3 AND flow_signed ≥ 0.4 (both layers) |
| MICRO | (struct_signed ≥ 0.2 OR flow_signed ≥ 0.3), NOT SILVER |
| MICRO_strict | exactly one of (struct_signed ≥ 0.3, flow_signed ≥ 0.4) is True (XOR), NOT SILVER |
| SKIP | everything else |

signed = raw_score × (+1 if signal==1 else -1)

## Tier counts (SOL 5m+15m combined)

```
{'SKIP': 253, 'MICRO_strict': 227, 'MICRO': 42, 'SILVER': 13}
```

## Per-cell results

Engine: $25 stake, HOLD policy. prod_mean = engine_mean ÷ 4 (0.5%×$1250=$6.25 sizing).

| Cell | Tier | n | hit% | mean$ | total$ | std$ | maxDD$ | p-value | bootstrap 95% CI | BE hit% | prod mean$ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SOL_5m | SILVER | 5 | 100.0% | $+2.6541 | $+13.2705 | $2.3329 | $0.0000 | n/a | [$+0.7490, $+4.6587] | n/a% | $+0.6635 |
| SOL_5m | MICRO | 20 | 90.0% | $-0.0079 | $-0.1576 | $8.5467 | $38.5000 | 0.3700 | [$-4.2868, $+3.0629] | 10.0% | $-0.0020 |
| SOL_5m | MICRO_strict | 114 | 90.4% | $-0.5559 | $-63.3747 | $8.1223 | $105.0808 | 0.5770 | [$-2.0450, $+0.8000] | 7.6% | $-0.1390 |
| SOL_15m | SILVER | 3 | 100.0% | $+6.4487 | $+19.3462 | $1.2786 | $0.0000 | n/a | [$+5.0181, $+8.1217] | n/a% | $+1.6122 |
| SOL_15m | MICRO | 10 | 90.0% | $+3.0760 | $+30.7599 | $9.6800 | $25.0000 | 0.3570 | [$-3.7403, $+7.3373] | 19.9% | $+0.7690 |
| SOL_15m | MICRO_strict | 35 | 74.3% | $-2.3330 | $-81.6538 | $13.4849 | $117.9722 | 0.5700 | [$-7.0489, $+1.9435] | 18.1% | $-0.5832 |

## Combined SOL (5m+15m) per tier

| Tier | n | hit% | mean$ | total$ | std$ | maxDD$ | p-value | bootstrap 95% CI | BE hit% | prod mean$ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SILVER | 8 | 100.0% | $+4.0771 | $+32.6167 | $2.7183 | $0.0000 | n/a | [$+2.1825, $+5.8809] | n/a% | $+1.0193 |
| MICRO | 30 | 90.0% | $+1.0201 | $+30.6023 | $9.0579 | $38.5000 | 0.4150 | [$-2.3718, $+3.9081] | 13.5% | $+0.2550 |
| MICRO_strict | 149 | 86.6% | $-0.9733 | $-145.0285 | $9.6828 | $202.5838 | 0.5810 | [$-2.4947, $+0.4915] | 9.9% | $-0.2433 |

## Sample concentration

| | Days with SILVER | Days MICRO only (orthogonal) | Total MICRO days |
|---|---:|---:|---:|
| MICRO | 6 | 6 | 12 |
| MICRO_strict | 6 | 9 | 15 |

SILVER fired on 6 distinct days.
MICRO orthogonal days = 6 — trades where only MICRO fires (no SILVER same day).

## Production sizing implication

Engine uses $25 notional. Production target: 0.5% × $1250 bankroll = **$6.25/trade**.
Scale factor = 6.25 / 25 = **0.25×** (÷4 on all PnL numbers).
SILVER prod mean = engine mean ÷ 4.
MICRO prod mean = engine mean ÷ 4 (same sizing assumption).

## Recommendation

Keep SILVER-only for now. MICRO shows tentative positive mean but insufficient sample to distinguish from noise.

## Files

- Backtest CSV: `strategy_lab/results/meta_classifier/micro_tier_backtest.csv`
- This report: `strategy_lab/reports/MICRO_TIER_BACKTEST_2026_05_07.md`
- Script: `strategy_lab/confluence/run_micro_tier_backtest.py`