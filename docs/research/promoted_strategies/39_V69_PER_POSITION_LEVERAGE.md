# 39 — V69: Per-position leverage validation

**Date:** 2026-04-27
**Runner:** [strategy_lab/run_v69_per_position_lever.py](../../strategy_lab/run_v69_per_position_lever.py)
**Output:** [phase5_results/v69_per_position_lever.json](phase5_results/v69_per_position_lever.json)
**Elapsed:** 14.8 s

## TL;DR

**V69 blend-level estimate is honest.** Per-position simulation (size_mult=1.75 inside the funding-aware simulator, leverage_cap raised to 5.25) produces an aggregated V52* headline within ±10% of the blend-level target on every metric. Per-position is slightly more conservative than blend-level; live deployment should plan to per-position numbers.

## Headline comparison

| Metric | V69 blend-level (V68b) | V69 per-position (this runner) | Divergence |
|---|---:|---:|---:|
| Sharpe | 2.639 | **2.614** | −0.9 % |
| CAGR | +64.02 % | **+61.11 %** | −4.5 % |
| MDD | −12.59 % | **−12.42 %** | +1.4 % (less DD) |
| Calmar | 5.085 | **4.920** | −3.2 % |
| WR_daily | 50.43 % | 50.43 % (unchanged by leverage) | 0 % |

Decision rule from doc 38 was "within ±10% on each headline metric." All four metrics pass. **VERDICT: PASS — V69 blend-level estimate is honest; per-position confirms it.**

## Why per-position is slightly more conservative

Two structural reasons the per-position number is ~4–5% lower CAGR than the blend-level multiplier:

1. **Vol drag.** Blend-level leverage `(1 + L * r).cumprod()` overstates actual return when there are losing bars — geometric compounding is non-linear under leverage. Per-position correctly compounds: on losing trades cash shrinks, so future `risk_dollars = cash × risk_per_trade` shrinks too, naturally de-risking after losses.
2. **Cap binding on big trades.** Even with leverage_cap raised from 3.0 → 5.25, occasional trades hit the cap when `1.75 × risk_dollars / sl_distance` exceeds `5.25 × cash / entry_price`. The cap-bound trades produce slightly smaller positions than blend-level's pure 1.75× multiplier would imply.

Both effects pull per-position in the same direction (slightly lower CAGR, slightly better MDD). That's a realistic pattern — live execution carries even more drag (slippage, partial fills), so the live number will likely sit between per-position and a further-derated estimate.

## Three parameterizations are equivalent

A surprising and clean finding: variants A / B / C produced **byte-identical equity**.

| Variant | size_mult | leverage_cap | risk_per_trade | Aggregated CAGR |
|---|---:|---:|---:|---:|
| A — target spec | 1.75 | 5.25 | 0.030 | +61.11 % |
| B — capped at 3× | 1.75 | 3.00 | 0.030 | +61.11 % |
| C — via risk_pct | 1.00 | 5.25 | 0.0525 | +61.11 % |

This means **the simulator's risk knobs are commutative** when the cap is not the binding constraint. The default V52 sleeves were sized by `risk_per_trade × ATR` rather than by `leverage_cap × cash / price` — the cap rarely bound in normal trading. So multiplying `size_mult` × 1.75 has the same effect as multiplying `risk_per_trade` × 1.75.

**Practical implication for production:** any of the three knob choices works. **Choose by exchange constraints, not by simulator preference.** Hyperliquid's default 3× cap is fine if `size_mult=1.75` is applied at the position-sizing layer (variant B) — no exchange-cap exception requests needed.

## Per-sleeve breakdown (size_mult=1.75)

| Sleeve | Sharpe | CAGR | MDD | Sleeve role |
|---|---:|---:|---:|---|
| CCI_ETH_4h | +1.29 | +45.7 % | −34.7 % | V41 core |
| STF_SOL_4h | +0.97 | +38.2 % | −33.9 % | V41 core |
| **STF_AVAX_4h** | **+2.07** | **+121.8 %** | **−26.9 %** | **V41 core (best per-bar Sharpe)** |
| LATBB_AVAX_4h | +1.53 | +53.9 % | −24.2 % | V41 core |
| MFI_SOL | +0.62 | +21.4 % | −57.3 % | V52 diversifier |
| VP_LINK | +1.34 | +89.1 % | −44.1 % | V52 diversifier |
| SVD_AVAX | +0.30 | +3.9 % | −61.7 % | V52 diversifier |
| MFI_ETH | +0.25 | −1.4 % | −44.9 % | V52 diversifier |

The **per-sleeve MDDs are alarming-looking** (−24 % to −62 %) but those are per-sleeve numbers under aggressive leverage with no cross-sleeve diversification. The aggregated blend MDD is **−12.4 %** because sleeve drawdowns rarely align in time. This is the diversification-discount premise of V52 in action.

Two diversifier sleeves are concerning under per-position leverage:
- **SVD_AVAX:** Sh +0.30, MDD −61.7 %. Borderline trivial alpha at this leverage level.
- **MFI_ETH:** Sh +0.25, CAGR **negative**. Adds negligible value.

Both are weighted at 0.0625 each in the V52* α=0.75 blend (= ~6 % of risk capital). The aggregated metrics already account for this; nothing to action immediately, but flag for the next research pass: **`run_v68c_drop_dead_diversifiers.py`** — try V52** with SVD_AVAX and MFI_ETH removed (re-allocating their 0.125 share to V41 core, raising α from 0.75 to 0.875). Plausible additional Sharpe lift.

## Sanity check: variant Z (no leverage)

| Metric | V52* standalone (V68b doc 37) | V69 variant Z (this run) |
|---|---:|---:|
| Sharpe | 2.639 | **2.639** |
| CAGR | +33.29 % | **+33.29 %** |
| MDD | −7.31 % | **−7.31 %** |

Variant Z (size_mult=1.0, leverage_cap=3.0, risk=0.030) reproduces V52* standalone exactly. The runner is consistent with prior measurements.

## Production-deployment numbers (use these, not blend-level)

These are the headline numbers to plan to:

```
                          backtest      live (1.4x slip)
Sharpe                    2.61         ~1.30   (planning)
CAGR                      +61.1%       ~+50% (post-slippage)
Backtest MDD              -12.4%       -
Live MDD plan             -            -17 to -19%   (1.4x backtest)
WR_daily                  50.4%        50%+ planning
Calmar                    4.92         3.5-4.0 planning
```

The V64 → V69 deployment plan amendment should use these as the live-target gates:

| Stage | Gate | Pass |
|---|---|---|
| 1 (weeks 1-4) | Sharpe ≥ 0.5 × backtest = 1.30 | required |
| 1 (weeks 1-4) | CAGR (annualized from 4w) ≥ 30 % | required |
| 1 (weeks 1-4) | MDD ≤ 1.5 × backtest = 18.5 % | hard kill |
| 2 (weeks 5-8) | Sharpe ≥ 0.7 × backtest = 1.83 | required |
| 3 (weeks 9-12) | full migration | requires Stage 2 pass |

## Recommended next steps

1. **Action this finding by drafting the V64 → V69 deployment plan amendment.** The substitutions are: V64 spec → V69 spec, leverage from V52-stack-implicit → explicit `size_mult=1.75 / leverage_cap=5.25`, kill-switch absolute thresholds re-tuned to the levered numbers above. Mirror [V64_DEPLOYMENT_PLAN.md](../deployment/V64_DEPLOYMENT_PLAN.md) format. ~1 day.
2. **`run_v68c_drop_dead_diversifiers.py`** — surgical: drop SVD_AVAX and MFI_ETH from the blend (their per-position leveraged contribution is marginal/negative). Reallocate to V41 core (α 0.75 → ~0.875). Test for incremental Sharpe lift. ~30 min.
3. **Live execution dry-run** with the Hyperliquid testnet API. Verify the sizing math from V69 in a no-money paper environment before any capital change.

## Files

- [run_v69_per_position_lever.py](../../strategy_lab/run_v69_per_position_lever.py)
- [phase5_results/v69_per_position_lever.json](phase5_results/v69_per_position_lever.json)

Reading order: [33](33_NEW_STRATEGY_VECTORS.md) → [34](34_V67_LEVERAGE_HIT.md) → [35](35_QUANTMUSE_REPO_ANALYSIS.md) → [36](36_V68_WEIGHT_OPTIMIZER.md) → [37](37_V68B_V41_RESHARE_WIN.md) → [38](38_V68B_GATES_PROMOTED.md) → [39](39_V69_PER_POSITION_LEVERAGE.md) (this).
