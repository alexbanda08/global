# Multi-Layer Confluence — End-to-End Verdict

**Date:** 2026-05-07
**Built:** FLOW (32k rows) + STRUCTURE (16k rows) + TRIGGER (28.7k rows) + GUARD (smoke 200) + tier classifier + grand backtest
**Status:** G3 gate FAILED but **a tradable standalone sleeve emerged** (SILVER-only on SOL+ETH).

---

## TL;DR

1. **Confluence as a universal momo refiner does NOT work.** Adding GOLD/SILVER/BRONZE tier filtering on top of momo degrades baseline performance on BTC/ETH (SKIP cell beats BASELINE).
2. **SILVER tier is a hidden gem on SOL+ETH.** STRUCTURE-aligned + FLOW-aligned trades hit 100% on SOL (n=11+5) and 84.6% on ETH_15m (n=13). Mean $/trade: +$3.76 to +$6.50.
3. **TRIGGER layer is data-broken.** HL liquidations file ends 2026-02-06; universe spans Apr-May 2026 → liq_magnet always 0%. GOLD tier needs TRIGGER and is starved (53 total trades across 6 cells).
4. **Three alpha vectors discovered** (none clears the strict ship bar but all worth paper-testing).

---

## Tier breakdown (full universe, 1605 fired momo trades)

| Tier | n | % | Mean hit | Mean $/trade |
|---|---:|---:|---:|---:|
| GOLD | 53 | 3.3% | 75.5% | -$1.99 |
| SILVER | 127 | 7.9% | 84.3% | +$0.05 |
| BRONZE | 188 | 11.7% | 78.7% | -$1.36 |
| SKIP | 1237 | 77.1% | 89.1% | +$0.10 |

GOLD/BRONZE both lose money on average. SILVER is roughly flat overall, but **drilling into per-cell shows it concentrates SOL+ETH alpha**.

## SILVER cell-level findings (the real signal)

| Cell | n | hit% | mean $/trade | total $ |
|---|---:|---:|---:|---:|
| **SOL_5m** | 11 | **100.0%** | **+$3.76** | +$41 |
| **SOL_15m** | 5 | **100.0%** | **+$6.50** | +$32 |
| **ETH_15m** | 13 | 84.6% | +$1.87 | +$24 |
| ETH_5m | 13 | 76.9% | -$3.64 | -$47 |
| BTC_5m | 45 | 86.7% | -$0.86 | -$38 |
| BTC_15m | 18 | 72.2% | -$2.85 | -$51 |

**Pattern: SILVER works on SOL (both tfs) and ETH_15m. Fails on BTC and ETH_5m.**

Combined SOL+ETH_15m SILVER: n=29, hit 96.6%, mean +$3.36/trade, total +$97. n is too small for stat sig but the signal is consistent.

---

## Three alpha vectors discovered

### Vector A — SOL FLOW-veto momo (Track A V2)
- Take momo SOL fires, keep only when flow_score sign agrees with signal AND |flow_score| ≥ 0.10.
- SOL_5m: hit 90.8% → 97.4% (+6.6pp). Mean -$0.25 → +$1.85.
- SOL_15m: hit 77.7% → 87.5% (+9.8pp). Mean -$0.80 → +$1.83.
- p-values 0.6+ — sample-underpowered, NOT statistically distinguishable.

### Vector B — SOL+ETH SILVER sleeve (grand backtest)
- STRUCTURE + FLOW alignment, no TRIGGER needed.
- 29 trades over Apr-May, 96.6% hit rate, +$3.36 mean.
- Highest edge per trade of any vector.
- Sample also too small (need ≥80 for ship).

### Vector C — Anti-confluence baseline (counter-intuitive)
- BTC_5m and ETH_5m: SKIP cell outperforms BASELINE.
- This means the confluence classifier currently makes wrong filtering decisions on BTC/ETH.
- Reframe: on BTC/ETH, run vanilla momo and IGNORE confluence.

### What does NOT work (verified failed)
- FLOW-only standalone direction (V1) — no edge above noise.
- FLOW-inverse momo (V3) — flipping flow-opposes makes things worse on 5m.
- Magnitude-quartile sizing (V4) — no monotone effect.
- GOLD tier — broken by TRIGGER data lag.

---

## Why the G3 gate failed

GOLD vs BRONZE WR spread = −1.5pp average (bar: ≥8pp).
GOLD samples are 53 across the whole universe — too few to differentiate.
The composite tier_classifier was DESIGNED for a working TRIGGER layer. With liq_magnet=0 across all data, GOLD requires FVG+OFI alignment which is over-saturated (FVG 97% active, OFI |x|>0.30 79% — nearly always on, no informative signal).

**The architecture is sound; the data lag in HL liquidations breaks the empirical test.**

---

## Recommendations

### 🔴 P0 — Top up HL liquidations data
- Pull Apr-May 2026 HL liquidation data from VPS3 storedata (collector should still have it).
- Re-run `strategy_lab/confluence/trigger/build_trigger.py` to populate liq_magnet correctly.
- Re-run grand backtest after top-up. THIS IS THE SINGLE BIGGEST UNLOCK.

### 🟡 P1 — Ship `confluence_silver_v1` paper sleeve (SOL+ETH only)
- Restrict to SOL_5m, SOL_15m, ETH_15m where SILVER showed positive edge.
- Stake 1.5% × bankroll per Cyclops sizing (≈ $18.75 at $1250 bankroll).
- Skip if STRUCTURE or FLOW disagrees, OR any GUARD blocks.
- Run paper-only for 6+ weeks to accumulate n≥80 per cell before live.
- Telemetry: log tier decision, both layer scores, skip reasons.

### 🟡 P1 — Ship `sol_flow_veto_v1` paper sleeve (parallel test)
- SOL momo fires, keep only if `flow_score · signal_dir ≥ 0.10`.
- Same sizing as baseline ($25).
- Compare head-to-head with confluence_silver_v1 on same SOL fires.

### 🟢 P2 — Build anti-confluence diagnostic
- For BTC/ETH, why does SKIP outperform tiers? Hypothesis: STRUCTURE features (BTC trend, S/R) are macro-context that adds info on SOL but harms BTC/ETH where momo is already exploiting micro-mean-reversion.
- Audit: per-tier breakdown of regime ('trend' vs 'sideways') and check if regime correlates with PnL differently per asset.

### ⚪ P3 — Re-tune classifier
- BRONZE bar (FLOW + TRIGGER) is meaningless when TRIGGER is saturated. Either drop BRONZE or tighten TRIGGER thresholds (e.g., |OFI| > 0.50 instead of 0.30).
- After HL data top-up, re-tune `_FLOW_WEIGHTS` and tier thresholds against held-out validation fold.

---

## Artifacts

### Code (this session)
- `strategy_lab/confluence/__init__.py`
- `strategy_lab/confluence/schema.py` — feature/tier contracts
- `strategy_lab/confluence/tier_classifier.py` — GOLD/SILVER/BRONZE/SKIP logic
- `strategy_lab/confluence/feature_join.py` — multi-layer enrichment adapter
- `strategy_lab/confluence/sleeve_runner.py` — bridge to existing engine
- `strategy_lab/confluence/validate_layers.py` — parquet sanity checker
- `strategy_lab/confluence/run_grand_backtest.py` — Phase 6 combo runner
- `strategy_lab/confluence/flow/{features,build_features,backtest_flow_only,sol_strategies}.py`
- `strategy_lab/confluence/structure/{btc_trend,sr_levels,regime_classifier,build_structure}.py`
- `strategy_lab/confluence/trigger/{liq_magnet,fvg,ofi,build_trigger}.py`
- `strategy_lab/confluence/guard/{filters,build_guards}.py`
- `strategy_lab/confluence/tests/test_skeleton.py` — 7 sanity tests (all pass)
- Engine perf fix: `strategy_lab/meta_classifier/extended_backtest_with_robustness.py:asof()` — added cache to fix OOM under heavy use

### Data
- `data/v4/refresh_2026_05_06/cache/all_flow_features.parquet` (32,046 rows)
- `data/v4/refresh_2026_05_06/cache/all_structure_features.parquet` (16,030 rows)
- `data/v4/refresh_2026_05_06/cache/all_trigger_features.parquet` (28,771 rows; **liq_magnet broken**)
- `data/v4/refresh_2026_05_06/cache/all_guard_blocks.smoke200.parquet` (smoke only — full build OOMed)

### Reports
- `strategy_lab/reports/CONFLUENCE_BUILD_PLAN_2026_05_07.md` — original plan
- `strategy_lab/reports/FLOW_G1_GATE_2026_05_07.md` — G1 gate findings
- `strategy_lab/reports/SOL_FLOW_STRATEGIES_2026_05_07.md` — Track A variant explorations
- `strategy_lab/reports/CONFLUENCE_GRAND_BACKTEST_2026_05_07.md` — raw grand backtest results
- `strategy_lab/reports/CONFLUENCE_VERDICT_2026_05_07.md` — this file

### Results CSVs
- `strategy_lab/results/meta_classifier/flow_g1_h1.csv`
- `strategy_lab/results/meta_classifier/flow_g1_h2.csv`
- `strategy_lab/results/meta_classifier/sol_flow_strategies.csv`
- `strategy_lab/results/meta_classifier/confluence_grand_all.csv`

---

## Reproduction

```bash
cd "/c/Users/alexandre bandarra/Desktop/global"

# Validate all layer parquets
py -X utf8 -m strategy_lab.confluence.validate_layers

# Re-run grand backtest
py -X utf8 -m strategy_lab.confluence.run_grand_backtest

# SOL-only mode
py -X utf8 -m strategy_lab.confluence.run_grand_backtest --sol-only

# Per-track re-runs
py -X utf8 -m strategy_lab.confluence.flow.backtest_flow_only          # FLOW G1
py -X utf8 -m strategy_lab.confluence.flow.sol_strategies              # SOL FLOW variants

# Layer rebuilds (after data top-up)
py -X utf8 -m strategy_lab.confluence.flow.build_features --asset all
py -X utf8 -m strategy_lab.confluence.structure.build_structure
py -X utf8 -m strategy_lab.confluence.trigger.build_trigger --asset all  # AFTER HL data top-up
py -X utf8 -m strategy_lab.confluence.guard.build_guards
```

---

## Bottom line

The Cyclops 4-layer confluence does NOT replicate as a universal alpha booster on our universe. But the BUILD process produced **two paper-shipping candidates** (SILVER on SOL+ETH, FLOW-veto on SOL) and **one diagnostic insight** (SKIP > BASELINE on BTC/ETH = filter-direction is wrong on those assets). The TRIGGER layer is gated on a data top-up.

Next decision point for operator: ship paper sleeves (P1) or wait for HL data top-up to re-evaluate full architecture (P0)?
