# 07 — Phase 5.5 Robustness Battery (V1, 4-of-5 tests)

**Date:** 2026-04-24
**Tests run:** per-year consistency, null permutation, block bootstrap, walk-forward efficiency
**Parameter-plateau:** deferred (needs per-strategy param-space map)
**Driver:** [strategy_lab/run_phase55_robustness.py](../../strategy_lab/run_phase55_robustness.py)
**Library:** [strategy_lab/eval/robustness.py](../../strategy_lab/eval/robustness.py)
**Raw reports (JSON):** [docs/research/phase5_results/robustness_reports.json](phase5_results/robustness_reports.json)

## Cells audited and verdict

| Cell | Phase-5 Gates | Robustness Tests Passed | Verdict |
|---|---:|---|---|
| **c1_meta_labeled_donchian ETH 4h** | 5/7 🟢 | **2/7** 🔴 | Phase-5 edge is a 2024-only artifact |
| c1_meta_labeled_donchian BTC 4h | 2/7 | 2/7 | 2024-only, same pattern |
| gaussian_channel_v2 BTC 4h | 4/7 🟢 | **1/7** 🔴 | 2024-bull-market momentum, not real edge |
| gaussian_channel_v2 ETH 4h | 3/7 | 1/7 | Same overfitting pattern |

## The specific failures

### C1 ETH 4h (the only 5/7 Phase-5 cell)
- **Per-year Sharpe:** 2022 = 0.00, 2023 = 0.00, **2024 = +1.10**. Zero trades in 2022–2023 because the meta-label classifier's train/test split put all "live" signals into late-2023 onward.
- **Walk-forward efficiency:** 6.06 — unusually high, but driven by folds with 0.0 IS Sharpe so the ratio is mechanically inflated. **Only 3 of 6 folds positive**; worst fold Sharpe = 0.00.
- **Permutation:** p = 0.067 — fails p < 0.01 threshold. The real Sharpe is above the null median, but not far enough outside the null distribution to be significant.
- **Bootstrap CIs:** Sharpe [−0.66, +1.72], Calmar [−0.25, +3.21]. Lower bounds straddle zero — we cannot rule out zero edge with 95% confidence.

**Root cause:** the Phase-5 V1 matrix ran the classifier with `train_frac=0.6` on 3 years of 4h data. After embargo, the "live" signal window is ~1 year — effectively 2024 only, which happened to be a strong BTC/ETH uptrend. The meta-labeler was scored on the easiest market regime in the sample.

### gaussian_channel_v2 BTC 4h (the Phase-5 Calmar +6.08 outlier)
- **Per-year Sharpe:** 2022 = **−1.80**, 2023 = **−0.71**, 2024 = **+2.43**. Two losing years masked by one winning one.
- **Walk-forward efficiency: −0.50** — IS returns are positive but OOS returns are NEGATIVE. This is the classic "strategy overfits to IS and degrades OOS" signature.
- **Worst fold Sharpe: −3.55** — catastrophic single-fold drawdown, clearly violates the "no fold < −0.5 Sharpe" robustness rule.
- **Bootstrap CIs:** MDD [−0.42, −0.12] — actual risk is at least double the Phase-5 observed −6.3% MDD.

**Root cause:** Phase 5's 75/25 split put all IS training in the 2022-mid-2024 decline window; the mechanical Phase-5 Sharpe was computed on the full 3-year curve, which 2024's +$40k→+$65k BTC run skewed positive. Walk-forward exposes that every single fold's OOS drift was negative (4 of 6 positive by sign, but negative by cumulative).

## What this changes

**The mission's 7 hard gates alone are not sufficient to declare a strategy live-ready.** Our best Phase-5 cell collapses under robustness. The battery's job is exactly this — catch the one-market-regime wonders before they go live.

**Revised promotion criteria:**

| Gate | Source | Status |
|---|---|---|
| MDD OOS < 20% | Phase 5 | Necessary not sufficient |
| Calmar OOS > 1.5 | Phase 5 | Necessary not sufficient |
| Profitable in ≥ 2 regimes | Phase 5 | Necessary not sufficient |
| \|ρ_book\| < 0.5 | Phase 5 | Necessary not sufficient |
| Maker fill ≥ 60% | Phase 5 | Necessary not sufficient |
| **Per-year Sharpe > 0 in ≥ 70% of years** | Phase 5.5 | **NEW BLOCKER** |
| **Walk-forward efficiency > 0.5 AND ≥ 5/6 positive folds** | Phase 5.5 | **NEW BLOCKER** |
| **Bootstrap Sharpe lower-CI > 0.5** | Phase 5.5 | **NEW BLOCKER** |
| **Permutation p-value < 0.01** | Phase 5.5 | **NEW BLOCKER** |

A candidate must clear BOTH the Phase-5 gates AND the robustness battery to be promotion-worthy. Zero of our audited cells currently qualify.

## Implications for prior phases

1. **The Phase 5 matrix rankings are still useful** — they tell us *where* to look, just not *what to deploy*. A 4/7 or 5/7 cell is a robustness-battery candidate, not an auto-promote.
2. **C1 needs longer training data.** Redo training on 2019-01 → 2022-12 (4 years, 8,760 bars at 4h), deploy on 2023-01 → 2024-12. That gives a 2-year OOS window covering both the 2023 range AND the 2024 bull — much harder to one-year-wonder.
3. **Existing book's "winners" are suspect** until audited. `gaussian_channel_v2 BTC` was the top Calmar in the whole matrix; robustness shows it's a 2024-only signal. Before relying on ANY existing strategy for correlation analysis, we should robustness-audit it.
4. **The bootstrap MDD upper-CI is the only test 4-of-4 cells passed.** Meaning: actual drawdowns might be within 30%, but we don't have enough evidence to say the strategies MAKE MONEY consistently. The MDD gate is easy; the Sharpe/Calmar gates are hard.

## What actually works in the battery

- **Bootstrap upper-CI on Max DD** passed all 4 cells (all stayed < 30%). This IS a real invariant — the strategies' risk-containment (stops, position sizing) is working.
- **Walk-forward efficiency > 0.5** passed 2 of 4 cells (C1 ETH: 6.06, C1 BTC: 2.14). Caveat: inflated by near-zero IS Sharpe folds. The 2 legacy cells both failed — genuine signal.

## Action items

### Short-term (1–2 turns)
1. **C1 v2: retrain on longer window.** Use 2019-2022 IS, 2023-2024 OOS. Rerun the robustness battery. This is the single highest-leverage fix.
2. **Extend robustness battery to the other 4/7-gate Phase-5 cells** — `ensemble_trend_vol BTC`, `squeeze_breakout SOL`, `donchian_breakout SOL`, `macd_htf SOL`. Which existing strategies are real?

### Medium-term
3. **Build the parameter-plateau test (5th robustness test).** Requires per-strategy param sweeps. Cheap compute, high signal — detects cliff parameter sensitivities.
4. **Apply the per-year consistency gate to the existing book.** Re-rank the 42 legacy cells by "Sharpe > 0 in ≥ 70% of years" — likely cuts the "winners" list significantly.

### Long-term
5. **Add Optuna + walk-forward optimization (Path D).** Every Phase-4 candidate enters this gauntlet from day one, not after-the-fact.
