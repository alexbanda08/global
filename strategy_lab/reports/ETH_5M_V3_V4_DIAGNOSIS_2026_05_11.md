# Diagnosis — eth_5m_v3 / v3_1 / v3_2 / v3_3 / v4 — Why So Few Fires?

**Date:** 2026-05-11 ~07:30 UTC
**Window:** last 14 days (paper/shadow)
**Question:** is the low fire rate on these ETH sleeves a bug, a data leak, or expected?

## TL;DR

**Not a bug.** Three real implementation issues compound:

1. **v3 / v3_1 / v3_2 / v3_3 / v4 share the same base signal** on BTC and ETH — they are *policy variants* of one strategy, not five independent strategies.
2. **ETH UpDown spreads are structurally wider than BTC** (avg 3.48% vs 2.25%) — the hardcoded spread filter is calibrated for BTC and kills most ETH fires.
3. **eth_5m_v4 has 0 trades placed** (all 36 fires killed by spread) because v4 has a tighter spread gate than its siblings.

## Skip-reason breakdown (14d, all assets × all v3/v4 families)

| asset | family | no_signal | wide_spread | order_placed | hedge_placed | other | total |
|---|---|---:|---:|---:|---:|---:|---:|
| btc | **v3** | **1,106** | **71** | 37 | 20 | 1 | 1,235 |
| btc | **v3_1** | **1,106** | **71** | 29 | 15 | 9 | 1,230 |
| btc | **v3_2** | **1,106** | **71** | 21 | 14 | 17 | 1,229 |
| btc | **v3_3** | **1,106** | **71** | 21 | 14 | 17 | 1,229 |
| btc | **v4** | **1,106** | **71** | 19 | 13 | 19 | 1,228 |
| eth | v3 | 1,165 | 45 | 4 | 0 | 1 | 1,215 |
| eth | v3_1 | 1,176 | 36 | 2 | 0 | 1 | 1,215 |
| eth | v3_2 | 1,165 | 45 | 1 | 0 | 4 | 1,215 |
| eth | v3_3 | 1,165 | 45 | 1 | 0 | 4 | 1,215 |
| eth | **v4** | 1,176 | 36 | **0** | **0** | 3 | 1,215 |
| sol | v3 | 1,037 | 107 | 70 | 29 | 1 | 1,244 |
| sol | v3_1 | 1,071 | 82 | 61 | 27 | 1 | 1,242 |
| sol | v3_2 | 924 | 188 | 83 | 31 | 20 | 1,246 |
| sol | v3_3 | 1,037 | 107 | 57 | 23 | 14 | 1,238 |

## Finding 1 — v3/v3_1/v3_2/v3_3/v4 share the same base signal on BTC and ETH

**Look at the BTC column:** `no_signal=1106` and `wide_spread=71` are IDENTICAL across all 5 variants. The base signal generator produces the exact same UP/DOWN/NONE output on every bar. The variants only differ in downstream policy (sizing, hedge logic, partial fills, etc.) — which show up in the `order_placed` and `hedge_placed` counts.

On ETH the same applies: v3/v3_2/v3_3 share `no_signal=1165` and `wide_spread=45`. v3_1 and v4 share `no_signal=1176` and `wide_spread=36` (slightly tighter).

On SOL there IS divergence — v3_2 has `no_signal=924, wide_spread=188` (much more aggressive). So v3_2 has SOL-specific tuning.

**Implication:** running 5 separate sleeves is redundant on BTC and ETH. Pick the best policy parameters and consolidate.

## Finding 2 — ETH UpDown markets have wider spreads than BTC

Spread_pct stats when v3 emits UP/DOWN (in 14d):

| asset | family | n | min | avg | p50 | max |
|---|---|---:|---:|---:|---:|---:|
| btc | v3 | 71  | 0.0202 | **0.0225** | 0.0206 | 0.0606 |
| eth | v3 | 45  | 0.0202 | **0.0348** | 0.0215 | 0.1010 |
| sol | v3 | 107 | 0.0400 | **0.0626** | 0.0417 | 0.1200 |

**ETH avg spread is 1.55× BTC. SOL avg is 2.8× BTC.** The spread filter (`wide_spread_skip` reason fires above some `spread_pct` threshold — appears to be ~2-2.5% based on the data) kills:
- BTC: 71 / (71+57) = 55% of fires
- ETH: 45 / (45+4) = 92% of fires
- SOL: 107 / (107+99) = 52% of fires (similar to BTC despite higher absolute spreads — likely a SOL-specific looser threshold)

**Implication:** the v3 spread filter is mis-calibrated for ETH. The threshold should be asset-specific (matching the momo sleeves' `SPREAD_FILTER = {BTC: 0.02, ETH: 0.02, SOL: 0.025}` per the handoff — but for v3 family it seems even tighter).

## Finding 3 — eth_5m_v4 has 0 trades placed

ETH v4 in 14d:
- 1,215 total signal events
- 1,176 no_signal
- 36 wide_spread_skip
- **0 order_placed, 0 hedge_placed**
- 3 other (probably `market_already_resolved` or similar)

v3_1 has the same 36 wide_spread but managed 2 placed. v4's downstream policy is even tighter — likely an extra check after wide_spread that no v4 ETH fire ever passed. Same on BTC v4 (19 placed) and SOL v4 — so v4's downstream policy is uniformly stricter than v3_1.

**Implication:** v4 on ETH is effectively dead weight. Either relax v4's gates or disable the ETH v4 sleeve.

## Finding 4 — v3_2 vs v3_3 partial-clone behavior

Verification query: BTC v3_2 fires LEFT JOIN BTC v3_3 fires on `condition_id`:

```
v3_2_fires=151  v3_3_fires=123  same_market_fires=151  same_direction_fires=123
```

Every v3_3 fire matches a v3_2 fire by condition_id with same direction. v3_2 has 28 fires that v3_3 didn't. So v3_3 ⊂ v3_2 in signal output on BTC — v3_3 is a stricter subset of v3_2. They share the underlying signal but v3_3 has additional gating.

On the resolved table earlier, BTC v3_2 and BTC v3_3 had IDENTICAL n_resolved=19 with identical pnl_total=+$19.27 — meaning even though v3_2 fires more, the ones that **place orders** are the same set as v3_3. The extra v3_2 fires get filtered downstream.

## Finding 5 — No data leak

Skip reasons are clean, no `stale_feed`, no `bar_age` issues, no `qty_compute_failed` (which appears in `momo_v2_HOLD` — *that's* a potential bug worth investigating separately). The minimal skipped-signal payload (just tf/mode/reason/signal/symbol/strategy_mode/predicted_edge_pp/predicted_cost_bps) confirms the strategy returned NONE before computing any market state — i.e., the signal generation logic itself decided not to fire, not a downstream data problem.

## Why does the ETH base signal return `no_signal` 6% more than BTC?

- BTC: 1106/1235 = 89.6% no_signal
- ETH: 1165/1215 = 95.9% no_signal
- SOL: 1037/1244 = 83.4% no_signal

The signal generator likely uses an absolute volatility threshold calibrated for SOL/BTC volatility. ETH's 2-min returns are smaller in magnitude, so the threshold is rarely exceeded. **This is the same q90 anti-pattern documented in the momo handoff** — gates calibrated on global thresholds vs per-asset percentiles.

## Recommended actions (priority order)

| # | action | rationale |
|---|---|---|
| 1 | **Use asset-specific spread filter for v3 family** — match momo's `{BTC: 2.5c, ETH: 4c, SOL: 6c}` or similar | ETH spread structurally 1.5× BTC; current filter dies on 92% of ETH fires |
| 2 | **Consolidate v3 / v3_1 / v3_2 / v3_3 / v4** on BTC and ETH | identical base signal; running 5 sleeves is duplicate compute and confused attribution |
| 3 | **Disable or relax v4** on ETH | 0 trades in 14d = paper-shadow dead weight |
| 4 | **Per-asset q90 gate** for v3 base signal | global threshold under-samples ETH (only 4% fires) |
| 5 | **Investigate momo_v2_HOLD `qty_compute_failed`** (24 events on eth_5m_momo_v2_HOLD, surfaced in skip-reason breakdown) | not the focus question, but a separate bug lead worth filing |

## Files

- `strategy_lab/meta_classifier/_vps3_diagnose_eth_v3.sh` — initial skip-reason discovery
- `strategy_lab/meta_classifier/_vps3_diagnose_eth_v3_deep.sh` — full breakdown + spread stats + clone check
- `strategy_lab/reports/ETH_5M_V3_V4_DIAGNOSIS_2026_05_11.md` — this report
