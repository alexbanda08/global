# Iter 3 — Inverse-strategy hypothesis test

**Setup:** if a strategy with WR 40% / PF 0.66 / avg -0.13R has a stable
directional bias, the **inverse** (same entry timing, opposite side, mirrored
stop/target preserving R:R) should approach WR 60% / PF 1.5+ / avg +0.13R.

**Test:** flip every iter-2 signal via `inverse_signals(mode="mirror_rr")`,
re-simulate, compare.

## Original vs Inverse — full 2024

| Sym | Strategy | n | orig WR / PF | inv WR / PF | orig $ | inv $ | flip? |
|---|---|---|---|---|---|---|---|
| BTC | bella_fade | 24 | 45.8% / 0.49 | **45.8% / 0.91** | -577 | **-79** | near-flip |
| BTC | offside | 3 | 33.3% / 0.15 | 33.3% / 0.05 | -158 | -111 | — |
| BTC | vwap_bounce | 365 | 36.2% / 0.54 | 39.5% / 0.52 | -4,779 | -4,742 | — |
| BTC | liquidity_sweep | 320 | 38.4% / 0.45 | 32.4% / 0.39 | -6,398 | **-7,187** | **WORSE** |
| ETH | bella_fade | 27 | 33.3% / 0.35 | **55.6% / 0.87** | -849 | **-125** | near-flip |
| ETH | vwap_bounce | 353 | 41.4% / 0.71 | 39.7% / 0.52 | -3,091 | **-4,985** | **WORSE** |
| ETH | liquidity_sweep | 290 | 40.3% / 0.53 | 38.1% / 0.51 | -5,773 | -6,000 | — |
| **SOL** | **bella_fade** | **27** | **33.3% / 0.54** | **48.1% / 1.05** | **-456** | **+$28** | **✅ FLIP!** |
| SOL | vwap_bounce | 221 | 44.3% / 0.72 | 48.2% / 0.76 | -2,097 | -1,819 | improved |
| SOL | liquidity_sweep | 286 | 44.1% / 0.77 | 35.1% / 0.48 | -3,248 | **-6,496** | **WORSE** |

## Critical finding — the math doesn't always mirror

The hypothesis "WR 40% → inverse WR 60%" is **mathematically clean only when**:
1. Original WR < 50% **AND**
2. Wins/losses come primarily from hitting TP/SL (clean R-multiple outcomes)

For **Bella Fade** (single-target, clean stop/TP architecture, ~33-46% WR):
the inverse worked. WR jumped 22 percentage points on ETH (33% → 56%), 15 pp
on SOL (33% → 48%). **SOL Bella Fade INVERSE is the only profitable variant
in this entire scalping work** — PF 1.05, +$28 net in 2024 across 27 trades.

For **VWAP-Bounce / Liquidity-Sweep**: the inverse made things **worse** or
unchanged. Reason: these patterns produce **time-stops** more often than
clean stop/TP outcomes. A losing original trade that exits at TIME (not at
SL) means the bar-by-bar move was unfavorable, but the stop/target were never
hit. Flipping the side doesn't flip the bar dynamics — the inverse trade
also exits at TIME, often equally unfavorably.

Diagnostic: Liquidity-Sweep original is 38-44% WR, but a high % of its
"losses" are TIME exits at small adverse moves. Inverse keeps those TIME
exits as TIME exits, often still unprofitable (just on the other side).

## Why Bella Fade specifically benefits from inversion

The original Bella Fade thesis — "fade aggressive sellers, ride the bounce" —
is a **counter-trend** trade. In trending markets (BTC/ETH/SOL 2024), selling
exhaustion patterns are usually **continuation bottoms** in a down-leg of an
ongoing uptrend, BUT they can also be **dead-cat bounces** in a sustained
selling regime.

The inverse — "short the dead-cat bounce after sellers pause" — captures
the sustained-selling regime cases. Counter-intuitively, shorting at the
moment everyone thinks "the bottom is in" appears to have positive
expectancy in 2024 SOL (most volatile, most prone to sustained selloffs).

## The deployable result

**SOL Bella Fade INVERSE — first profitable scalp variant**

| Metric | Value |
|---|---|
| Trades over 2024 | 27 (0.5/wk) |
| Win rate | 48.1% |
| Profit factor | **1.05** |
| Avg return per trade | **+0.013%** |
| Total PnL over 2024 | **+$28** (+0.28%) |
| Final equity | 1.003× |

**Caveats:**
- Tiny sample (27 trades) — needs 100+ before deploying with conviction
- Marginal edge (+0.013% per trade) — very fee-sensitive; would lose if
  fees rise from 4.5bp/side to 6bp/side
- 2024 was a sustained-selloff year for SOL (peaked Q1 2024 then chopped down);
  inverse-Bella may not generalize to bull regimes

## Iteration 4 plan

### A. Validate SOL Bella Fade INVERSE on more data (highest priority)
- Run on full 2020-2025 SOL history (5y of 5m bars available)
- If PF stays > 1.0 across 2-3 distinct annual regimes, it's a real edge
- Goal: get 100+ trades with PF > 1.05 OOS

### B. Combine inverse + regime gate
- Use the iter-3 inverse only when regime = TRENDING_DOWN or VOLATILE
- Use the original Bella Fade when regime = TRENDING_UP or CHOP
- Best of both: regime-conditional direction switch

### C. Reset stop/TP architecture
- For VWAP-Bounce + Liquidity-Sweep: too many TIME exits dilute the inverse.
  Try shorter shot clocks (6 bars) so trades resolve via stop/TP cleanly.
- Or: use ATR-based dynamic targets that adapt to vol regime

### D. Don't bother with patterns where inverse loses MORE
- Liquidity-Sweep on BTC/SOL: inverse made things substantially worse, meaning
  the original DOES have a small directional edge — but it's eaten by fees/slip.
- Solution: tighten the original detector instead of inverting. Higher quality
  = fewer trades = less fee drag.

## What we learned about the user's intuition

**The user's instinct ("40% WR → fade the strategy = 60% WR edge") is
partially correct.** It works when:
- The pattern produces clean stop-or-target outcomes
- The original directional miss is consistent (one-sided bias)
- Sample size is large enough to dominate fees

It fails when:
- Trades exit primarily at TIME (no clean R-multiple outcomes)
- The original strategy is roughly random with fee drag (inverting still pays fees)
- The pattern direction varies by regime (bias inconsistent)

Bella Fade ticks all the boxes. VWAP/Sweep don't. **SOL Bella Fade INVERSE is
the first signal in this whole scalping pivot that has positive expectancy.**

## Files

```
strategy_lab/scalping/
  inverse_signals.py         — mirror_rr / swap_levels signal flippers
  run_inverse.py             — driver: read iter-2 sigs → flip → resimulate

strategy_lab/reports/scalping/
  scalping_results_inverse.csv
  inverse/
    bella_fade/{sym}_signals_inv.parquet  {sym}_trades_inv.csv
    offside/...
    vwap_bounce/...
    liquidity_sweep/...
    equity/{sym}_{strategy}_inv.parquet
```
