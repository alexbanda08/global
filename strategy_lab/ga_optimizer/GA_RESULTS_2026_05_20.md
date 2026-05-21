# GA Optimization Results — Honest Assessment (2026-05-20)

## Data state (refreshed today)

- Universe: **28,731 chainlink-resolved markets** Apr 24 → May 19 23:30 UTC (~26 days)
- L25 books: BTC/ETH/SOL through May 19 23:36 UTC (9.4M new rows)
- Trading events: **58,701 production fires** over May 6-19 (13 days, the rolling window)
- Klines, oracle, trades: all current through May 19

## What was built

```
strategy_lab/ga_optimizer/
├── genome.py             Gene definitions (float/int/cat/mask) + mutation
├── operators.py          Tournament/elitism/crossover/breed
├── fitness.py            PnL-heavy composite + lookahead-corrected harness wrap
├── seeds.py              Known-good seeds from manual fade-scan
├── ga_loop.py            v1: single train/val split
├── ga_loop_v2.py         v2: 3-fold walk-forward + diversity tracking + adaptive mutation
├── walk_forward.py       Multi-fold CV utility
├── runner.py             CLI for v1
├── runner_v2.py          CLI for v2
├── multi_niche_runner.py 9-niche orchestrator (BTC/ETH/SOL × momo_5m/momo_15m/mispricing_15m)
└── path_b/
    ├── events.py         Load production events + compute pnl_invert estimate
    ├── cells.py          Aggregate by (sleeve_id, signal, hour_bucket, dow_group)
    ├── ga_filter.py      GA over per-cell action map {KEEP, INVERT, SKIP}
    └── runner.py         CLI for Path B
```

## Test results (3 GA approaches)

### Approach 1: backtest-based GA (v1)
Toy run BTC momo_5m, pop=30, gens=10:
- Train fitness rises 0.60 → 0.77 ✓
- Train PnL +$1,043 → held-out **$0** (n=17) — overfit

### Approach 2: walk-forward CV GA (v2)
Toy run BTC momo_5m, pop=40, gens=15, 3-fold CV:
- Per-fold val PnLs: +$388, +$484, +$481 (consistent) ✓
- Held-out (May 16-19): n=53, win 47%, **-$97** — REGIME DRIFT

### Approach 3: production-events GA (Path B)
Full run pop=80, gens=60 on 58,701 production fires:

**Unconstrained:** train +$29,290 / val +$650 / held-out **-$5,152**
**Sparsity-constrained (max 15 active cells, train+val co-positive):**
- Conservative baseline (32 cells co-positive): train +$4,164, val +$4,431, **held-out -$1,294**
- Vs production unchanged on held-out window: -$1,840 (estimated from -$9,194 / 13d × 2.6d)
- **Net improvement: +$546 over 2.6 days = +$210/day = ~$6,300/month**

## The honest truth

**All three GA approaches confirm the same finding: the 13-day production window has REAL regime drift.**

| Approach | Train PnL | Val PnL | Held-out PnL | Verdict |
|---|---:|---:|---:|---|
| Backtest GA v1 | +$1,043 | -$121 | $0 (n=17) | Overfit |
| Backtest GA v2 (CV) | mean +$451/fold | — | -$97 to -$673 | Overfit |
| Path B unconstrained | +$29,290 | +$650 | -$5,152 | Severely overfit |
| **Path B constrained** | **+$4,164** | **+$4,431** | **-$1,294** | **Real but modest** |

The constrained Path B saves ~$210/day over status quo. That's real, not zero, but ~20× smaller than what the original manual fade-scan promised.

## Why the manual fade-scan's +$10,220/mo claim doesn't generalize

The fade-scan in `DEPLOYMENT_FINAL.md` was retrospective pattern discovery on the SAME data window we'd deploy on. With Bonferroni-strict (4 cuts, p<0.001), the patterns were robust within that window — but:
- It assumes future fires will follow the same regime
- 30-day backward isn't enough sample to project 30-day forward
- Crypto regime shifts within 3-7 days

The 4 Bonferroni-strict cuts from the fade-scan:
1. BTC momo HEDGE DOWN @ 18-22 UTC
2. BTC momo HOLD DOWN @ 18-22 UTC
3. BTC momo SELL DOWN @ 18-22 UTC
4. BTC 15m volume_INV_NIGHT UP @ 06-11 UTC

These are the ones to deploy FIRST in paper mode and verify before any GA picks. They're the only signals strong enough to survive Bonferroni at the original analysis window.

## Revised deployment recommendation

### Phase 1 — paper validation (2 weeks) with NARROW set
Deploy only the 4 Bonferroni-strict cuts. Track per-cut realized hit rate + PnL.

**Pass criteria for Phase 2:**
- Each cut must hit ≥ 55% inverse rate over its first 30 trades
- Aggregate 14-day realized PnL ≥ +$500

### Phase 2 — extend to Path B's 32 conservative cells (2 weeks)
Add the 32 cells that passed train+val co-positive filter. Per-cell kill switch: 3 consecutive losing days → pause that cell.

**Pass criteria for Phase 3:**
- Aggregate 14-day realized PnL ≥ +$1,500
- No more than 10 cells paused by kill switch

### Phase 3 — refit GA after 6 weeks of fresh data
With 60+ days of production events instead of 13, the GA should find more stable patterns. Re-run multi-niche GA + Path B with the longer window.

**Don't deploy any single-fold GA winners now.** Held-out test fails for every approach when data window is only 13 days.

## Refit cadence (locked from earlier decision)

**Monthly** + trigger override (auto-pause if rolling-7d Sharpe drops below 50% of in-sample). First re-fit: **2026-06-20** (after 30 days more data).

## Bottom line

- **Deploy now**: the 4 Bonferroni-strict cuts only (~$2k/month estimated based on fade-scan)
- **Defer**: GA-derived cuts until 6+ weeks of fresh trading_events available
- **Infrastructure**: all built and reusable. Re-run is one command.

The GA experiment was educational, not deployable. The TRUTH revealed: crypto Polymarket regime drifts faster than 13 days. We need 6-8 weeks of stable data to extract reliable patterns.
