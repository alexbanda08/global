# Lookahead Bug Discovered — H_refined Correction (2026-05-16)

## TL;DR — RETRACTION

**H_refined and H_refined_v2 are NOT deployable.** A microsecond-level lookahead in the backtest framework inflated per-trade edge by 73-86%. After correcting for realistic 100ms WebSocket latency, both variants are NOT statistically significant.

```
                 latency=0 (original)    latency=100ms (corrected)
V1 baseline:     +$2.43/trade, p=0.003   +$0.33/trade, p=0.37    [-$1.56, +$2.17]
V2 compound:     +$8.67/trade, p<0.001   +$2.32/trade, p=0.13    [-$1.74, +$6.23]
```

## What was wrong

The backtest uses `asof_strict(end_us, prices, entry_us)` to look up binance prices. This returns the close of the 1MIN bar that ENDED at-or-before `entry_us`.

**The bug**: `entry_us` aligns exactly with minute boundaries (because `slot_end_us - 300s` lands on a minute). So `asof_strict` returns the bar that closes EXACTLY at `entry_us`.

**In real-time production**: that bar's close arrives via WebSocket ~10-100ms AFTER `entry_us`. You don't have it yet at decision time.

So the backtest was using future information (the bar's close from the next ~10-100ms).

## The audit that found it

Picked 20 random candidate trades, recomputed signal end-to-end:

```
Total trades audited: 20
Borderline (data ts == entry_us): 19 / 20
NEGATIVE delta (data ts > entry_us): 0
Signal changes when entry shifted -1us: 6 / 20

Delta-from-entry distributions:
  p_now_delta_us         median = 0us, min = 0us (boundary)
  book_up_delta_us       median = 949ms, min = 241ms (safe)
```

19 of 20 trades had `p_now` bar ending at EXACTLY `entry_us`. 6 of 20 signals FLIP if the entry is shifted by -1 microsecond.

## Confirming with realistic latency sweep

Re-ran the FULL candidate cell at 7 latencies:

```
latency       n     hit       pnl/trade    perm_p     bootstrap 95% CI
0.000s      118   71.19%    +$8.67/trade   <0.001     [+$4.73, +$12.68]   <- ORIGINAL
0.001ms     141   56.03%    +$2.32/trade    0.131     [-$1.74, +$6.23]
50ms        141   56.03%    +$2.32/trade    0.125     [-$1.91, +$6.44]
100ms       141   56.03%    +$2.32/trade    0.125     [-$1.58, +$6.23]
500ms       141   56.03%    +$2.32/trade    0.144     [-$1.65, +$6.31]
1s          141   56.03%    +$2.32/trade    0.128     [-$1.70, +$6.42]
60s         141   56.03%    +$2.32/trade    0.117     [-$1.83, +$6.40]
```

**Hit rate drops 71% → 56% as soon as ANY latency is applied.** Per-trade PnL drops 73%. Permutation p-value goes from <0.001 to 0.13 (not significant).

This isn't a "small bias" — it's the bulk of the apparent alpha.

## Why latencies 1us through 60s give identical results

asof_strict with `side="right" - 1` is binary: either include the bar ending AT target, or not. Any latency >= 1us excludes that bar. Until you exceed 60s of latency you don't skip another bar. So:

- latency=0: use bar [t-60s, t) → close observed at t (NOT available at t)
- latency in (0, 60s]: use bar [t-120s, t-60s) → close observed at t-60s (available at t)
- latency > 60s: would skip another bar

The "real" production setup is latency >= 1us (use the previous fully-closed bar). All my "latency >= 1us" runs are equivalent to the correct production setup.

## What this means for the broader discovery session

The microsecond-lookahead affects EVERY backtest that:
1. Uses `asof_strict` against minute-boundary timestamps
2. Has `entry_us` aligned with minute boundaries (which all of mine did, since `slot_end_us` is on 15-min/5-min boundaries)

### Impact on NULL verdicts (strategies A-G + I)
All NULL — but they were tested with the same lookahead. So their TRUE performance is even WORSE than reported. The NULL verdicts are MORE valid, not less.

### Impact on H mispricing (the supposed survivor)
Both V1 and V2 collapse with latency correction. H mispricing is NULL at production anchor (already shown). At late-15m anchor it's also NULL after correction.

### Impact on prior reports (REPORT_*.md)
- A2 CVD late-15m (88.5% hit): was already flagged as spurious due to entry-price problem (book at 0.95+). Was also affected by lookahead, but verdict unchanged.
- E book imbalance late-15m: real-fill PnL already negative (-$1,809). Lookahead doesn't change the verdict.
- I naive binance late-15m: 93% hit was tautology. Lookahead doesn't change the verdict (the signal IS the lookahead).

So the NULL verdicts hold. **The only "alpha" claim (H_refined) was the one tainted by the bug.**

## Honest final verdict on the discovery session

**Zero deployable alpha found.**

- 11 strategies tested at production anchor → all NULL.
- LATE-15m exploration revealed tautology (Strategy I baseline 93% hit) + book-already-priced effect (Strategy E -PnL despite 72% hit) + CVD over-OTM-entry artifact.
- One apparent survivor (H_refined / H_refined_v2) turned out to be a microsecond lookahead artifact. After correction, NOT significant.

## How to fix the lookahead in the framework

Option A — shift target_us by -1us inside `asof_strict`:
```python
def asof_strict(end_us, price_close, target_us):
    idx = int(np.searchsorted(end_us, int(target_us) - 1, side="right")) - 1
    if idx < 0: return float("nan")
    return float(price_close[idx])
```

Option B — change `side="right"` to `side="left"`:
```python
idx = int(np.searchsorted(end_us, int(target_us), side="left")) - 1
```

Option C — add an explicit `latency_us` parameter (default 100ms) to every caller.

**Recommended: Option C** with a default that matches the production environment's actual WS latency. Then redo every backtest in the codebase, not just the discovery session.

## What this means for future strategy hunts

1. **Every new backtest must include a realistic latency parameter.** Run at 0, 50ms, 200ms, 1s and report all three. If the strategy only works at 0, it's overfit.

2. **Bar-aligned anchors are dangerous.** When entry timestamps align with kline bar boundaries, asof_strict has the boundary issue. Better: use sub-bar timestamps (e.g., `entry_us = slot_end - 300s + 100_000` to shift off the boundary) and use causal asof.

3. **Treat any "hit rate > 60%" claim with extreme skepticism.** This session showed multiple strategies at 60-93% hit that were artifacts.

4. **The mid-only baseline at late-15m is the real ceiling.** Strategy I naive binance momo at slot_end-60 hit 93% with the lookahead included. The mid of the book at slot_end-60 likely also hits 80%+ — but THAT'S the cost basis. You can't beat the mid by buying the mid.

## Files

- `lookahead_audit.py` — the audit script that found the bug
- `lookahead_audit_report.json` — detailed audit results
- `refine_H_latency_test.py` — V2 latency sweep
- `refine_H_latency_v1.py` — V1 vs V2 latency comparison
- `refine_H_latency_results.parquet` — raw latency-test PnL data
- `LOOKAHEAD_CORRECTION.md` — this file
- `FINAL_H_REFINED.md` / `FINAL_H_REFINED_V2.md` — RETRACTED reports (preserved for reference but findings invalid)
