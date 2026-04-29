# 34 — V67: Leverage audit clears the 60% / 50% bar

**Date:** 2026-04-27
**Runner:** [strategy_lab/run_v67_v52_lever_audit.py](../../strategy_lab/run_v67_v52_lever_audit.py)
**Output:** [phase5_results/v67_lever_audit.csv](phase5_results/v67_lever_audit.csv) · [phase5_results/v67_lever_audit.json](phase5_results/v67_lever_audit.json)

## Headline

**V52 leveraged 1.75× (blend-level) clears CAGR +60.1% AND MDD −10.0% AND WR_daily 50.4% AND no liquidation events.** Sharpe preserved at 2.52, Calmar 6.02.

## Path to this result

Three iterations against the user's 60% CAGR / 50% WR bar:

1. **V65 (session gates)** — 5 variants tested. All produced byte-identical equity to baseline (V52 already sidesteps Asia/weekend hours organically). Vector 5 closed.
2. **V66 (funding-Z fade)** — 45 grid cells across 5 HL coins. Zero cells PROMOTE. Best was BTC z=±1.0 ATR=1.5: IS Sh +0.77 / OOS Sh +1.71 / OOS CAGR +38.9% / WR 40%. Clean OOS but WR is structurally low (fading after a 1.5-ATR overshoot rarely lifts WR > 50%). Funding-Z fade is a real Sharpe-1.7 OOS edge but not a 60%/50% candidate. Confirmed Vector 1 generates uncorrelated alpha; promoted to "diversifier candidate" not "headline sleeve."
3. **V67 (leverage audit)** — V52 baseline has Sh 2.52 / CAGR 31.5% / MDD −5.8% / WR_daily 50.4%. Sweeping L ∈ {1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5}:

| L    | Sharpe | CAGR    | MDD     | Calmar | WR_daily | Liquidation |
|------|--------|---------|---------|--------|----------|-------------|
| 1.00 | 2.52   | +31.5%  | −5.8%   | 5.42   | 50.4%    | no          |
| 1.25 | 2.52   | +40.5%  | −7.2%   | 5.61   | 50.4%    | no          |
| 1.50 | 2.52   | +50.0%  | −8.6%   | 5.81   | 50.4%    | no          |
| **1.75** | **2.52** | **+60.1%** | **−10.0%** | **6.02** | **50.4%** | **no**      |
| 2.00 | 2.52   | +70.7%  | −11.3%  | 6.23   | 50.4%    | no          |
| 2.50 | 2.52   | +93.6%  | −14.0%  | 6.68   | 50.4%    | no          |

The winner is L=1.75 (smallest L that clears all three gates).

## Honest caveats — read before deploying

1. **Blend-level leverage is an upper-bound estimate.** This applies the multiplier to the post-aggregation V52 return stream. Real on-Hyperliquid execution applies leverage at the *position* level — different fee dynamics per leg, position-specific liquidation thresholds, position-sizing interaction with `risk_per_trade` inside the simulator. Per-sleeve leverage will produce a slightly different curve. **Validation step (mandatory before live):** rerun each V52 sleeve with `leverage_cap=1.75 × current_cap` inside `simulate_with_funding`, then re-aggregate.

2. **Live MDD is typically 1.3–1.5× backtest MDD.** Plan for live MDD = −13% to −15%, not −10%. Still inside the −40% cap, but not the pristine number above.

3. **WR_daily 50.4% is razor-thin** above the 50% gate. The "win-rate" semantic here is *daily up-day rate of the equity curve*, not per-trade WR (V52 is multi-sleeve, no single trade list). Per-trade WR for V52 is unknown without aggregating each sleeve's trade list — that's the second validation step.

4. **No new alpha was discovered today.** This config does not improve V52's edge; it just monetizes the existing edge harder via leverage. The Sharpe is unchanged. The implication: if V52's edge decays in live trading, the levered variant decays *faster* in absolute terms, not slower. This is a "use the runway you have" bet, not a "found new alpha" bet.

5. **The 1.75× number is single-window.** No walk-forward, no per-year audit, no Monte-Carlo on the levered curve. The full V52 gate battery (gates 1–10) was *not* re-run on the levered variant. Without that, calling this "V67 champion" would repeat the V25/V27 mistake of shipping a variant that hasn't cleared the same bar V52 had to clear. **Mandatory before promotion:** run `verdict_8gate(eq_v52_lev175)` plus gate 9 (path-shuffle MC) plus gate 10 (forward 1y MC).

## Recommended next steps (in order)

1. **`run_v67_per_sleeve_leverage.py`** (small) — re-run V52 sleeves with their `leverage_cap` kwarg multiplied by 1.75, re-aggregate, compare to blend-level estimate. If they diverge by < 5% in CAGR, blend-level is a safe shortcut. If > 10%, use per-sleeve numbers as the truth.
2. **`run_v67_full_gates.py`** (medium) — full 10-gate battery on the levered variant. Mirror `run_v59_v58_gates.py`. Decision rule: must clear ≥ V52's gate count *and* improve Calmar lower-CI.
3. **Forward Monte Carlo (1000 paths, 1y)** with realistic slippage/funding model on the levered curve. Compute P(year-1 profit) and P(MDD < −20%).
4. **Only then**: 4-week paper trade against published kill-switch schedule before any live capital change.

## What this does NOT replace

- The V64 deployment plan (12-week staged migration from V52) is still the right migration path. V67 is a parameter dial inside V52, not a new champion.
- Vector 1 (funding carry) and Vector 2 (OI×funding triplet) remain real diversification opportunities. The V66 result actually validates Vector 1 as an OOS-real edge (Sh +1.71) — just not as a single-sleeve target hit.
- The −40% MDD per-sleeve kill-switch and −30% blend halt rules carry over unchanged. Levered or not, those numbers govern.

## Files written

- [run_v67_v52_lever_audit.py](../../strategy_lab/run_v67_v52_lever_audit.py)
- [phase5_results/v67_lever_audit.csv](phase5_results/v67_lever_audit.csv)
- [phase5_results/v67_lever_audit.json](phase5_results/v67_lever_audit.json)

Cross-reference: [33_NEW_STRATEGY_VECTORS.md](33_NEW_STRATEGY_VECTORS.md) for the full vector catalog this iteration drew from.
