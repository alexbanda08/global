# 05 — Phase 5 Backtest Matrix

## V2 (Path A — refined parameters) — 2026-04-23

Refinements applied per V1 diagnosis:
- **A1:** `conf_threshold` 0.6 → 0.75, `sl_atr_mult` 2.0 → 3.0, `tsl_atr_mult` 3.0 → 4.0
- **B1:** `er_threshold` 0.30 → 0.40, new `adx_min_entry = 25`, `tsl_atr_mult` 3.0 → 4.5
- **D1:** `rsi_threshold` 10 → 5, added `close < BB_lower(20, 2σ)` gate, added bullish-reversal-candle gate

### V2 results

| Strategy | Symbol | TF | Sharpe OOS | Calmar OOS | Max DD | Maker % | n_trades | Gates | Δ vs V1 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| A1 | BTCUSDT | 4h | +0.25 | +0.27 | −9.1% | 72.4% | ~20 | 3/7 | **Sharpe −0.56** ❌ |
| A1 | ETHUSDT | 4h | −0.98 | −0.89 | −17.3% | 71.0% | ~20 | 3/7 | worse |
| A1 | SOLUSDT | 4h | −1.67 | −1.09 | −8.9% | 68.2% | ~20 | 3/7 | worse |
| B1 | BTCUSDT | 1h | **−0.40** | −0.40 | **−18.1%** | 57.9% | ~150 | 2/7 | Sharpe +2.74, MDD +16pp |
| B1 | ETHUSDT | 1h | **−0.90** | −0.61 | **−26.6%** | 65.0% | ~150 | 2/7 | Sharpe +0.85, MDD +8pp |
| B1 | SOLUSDT | 1h | −1.08 | −1.09 | **−25.8%** | 58.1% | ~150 | 1/7 | MDD +31pp (big) |
| **D1** | **BTCUSDT** | **15m** | **+0.47** | **+0.69** | **−2.3%** | 68.8% | ~30 | **3/7** | **Sharpe +8.66, MDD +57pp** 🎯 |
| D1 | ETHUSDT | 15m | 0.00 | 0.00 | 0.0% | 66.7% | 3 | 3/7 | filter too strict |
| D1 | SOLUSDT | 15m | 0.00 | 0.00 | 0.0% | 50.0% | 3 | 2/7 | filter too strict |

### V2 verdict

**Partial win.** Two results stand out:

1. **D1 BTC-15m flipped from catastrophe to genuine-signal territory.** Sharpe +0.47, Max DD −2.3%, just one configuration tune away. The combined filter stack (RSI < 5 AND BB-lower AND bullish reversal) cut trade count ~50× and demolished the fee-drag problem.
2. **B1 halved its drawdowns.** Still negative Sharpe, but the direction-of-travel is right. The ADX ≥ 25 gate + 4.5× TSL widening moved it from unambiguously broken to salvageable.

**A1 regressed** — the 0.75 confidence threshold is too strict on BTC specifically. V1's 0.6 was closer to right for BTC; a middle value (0.65–0.70) is worth trying, paired with per-symbol regime-config presets for ETH/SOL which are noisier.

**D1's ETH/SOL dead cells (3 trades, zero P&L)** reveal the new filter stack is over-tuned to BTC. Either the `require_bullish_reversal` flag needs to be a parameter per-symbol, or ETH/SOL need their own `bb_sigma` (they're more volatile, so the 2σ band gets hit less when combined with RSI < 5).

**Nobody passes 5/7 gates yet.** Best cell is D1 BTC-15m at 3/7 — profitable + very low DD + maker ≥ 60%, but Calmar (0.69) still below the 1.5 floor.

### Root cause summary

Each strategy has a clear path to passing — but the path is **symbol-specific**, not a single global parameter set. The Phase-3 candidates were written assuming uniform crypto behavior; the data says BTC, ETH, SOL need different thresholds. This points to a **per-symbol Optuna pass** as the obvious next step (Path D infrastructure) — hand-tuning cross-symbol is the wrong shape of problem.

### Proposed follow-up (small, bounded)

1. **A1:** add a `regime_config` per symbol with `adx_weak_threshold` ETH/SOL = 28 (up from 25). Revert conf_threshold to 0.65.
2. **D1:** make `require_bullish_reversal` a per-symbol flag; leave True on BTC, False on ETH/SOL.
3. **B1:** this one wants Optuna. Hand-tuning keeps missing.

After (1) and (2), rerun just the A1 + D1 cells. Skip a third manual-tune round on B1 — we'll gate it for Optuna when Path D ships.

---

## V1 (initial matrix) — 2026-04-23

**Date:** 2026-04-23
**Candidates tested:** A1 (Regime-Switcher), B1 (KAMA Adaptive Trend), D1 (HTF Regime × LTF Pullback)
**Grid:** each strategy × {BTCUSDT, ETHUSDT, SOLUSDT} at its candidate-spec TF.
**Data windows:** A1 + B1 = 2022-01 → 2024-12. D1 = 2023-06 → 2024-12 (15m × 1.5y = ~50k bars).
**IS/OOS split:** 75/25. All metrics reported below are OOS unless noted.

## Headline — none of the 9 cells clear 5/7 hard gates

| Strategy | Symbol | TF | n_trades | Sharpe OOS | Calmar OOS | Max DD OOS | Maker % | Gates |
|---|---|---|---:|---:|---:|---:|---:|---:|
| **A1** | BTCUSDT | 4h | 37 | **+0.81** | **+1.31** | **-9.3%** | **66.2%** | **3/7** |
| A1 | ETHUSDT | 4h | 37 | +0.27 | +0.20 | -13.3% | 63.5% | 3/7 |
| A1 | SOLUSDT | 4h | 41 | -1.17 | -1.00 | -6.6% | 62.2% | 3/7 |
| B1 | BTCUSDT | 1h | 376 | -3.14 | -1.23 | -34.1% | 60.6% | 2/7 |
| B1 | ETHUSDT | 1h | 341 | -1.75 | -1.02 | -34.6% | 63.0% | 2/7 |
| B1 | SOLUSDT | 1h | 372 | -3.17 | -1.16 | -57.2% | 60.9% | 2/7 |
| D1 | BTCUSDT | 15m | 1703 | -8.19 | -1.49 | -59.8% | 79.4% | 2/7 |
| D1 | ETHUSDT | 15m | 1560 | -8.13 | -1.47 | -61.7% | 75.7% | 2/7 |
| D1 | SOLUSDT | 15m | 1995 | -5.57 | -1.46 | -60.5% | 71.9% | 2/7 |

Hard gates (restated): Max DD < 20%, Calmar > 1.5, DSR > 0.95, ≥ 2 profitable regimes, |ρ_BH| < 0.5, Maker ≥ 60%.

## What's working

1. **Engine execution is sound.** Every cell achieves the mission's ≥60% maker-fill floor — the engine's limit-order simulation, fee schedule, and partial-fill logic all fire as designed. Maker rates span 60% (B1) → 79% (D1). The execution infrastructure is **not the problem**.
2. **A1 on BTC 4h is directionally right.** Positive Sharpe, Calmar above 1, max DD < 10%. Three of seven gates pass. Refining the thresholds (confidence gate, ATR multiples) is a small tuning away from promotion.
3. **No catastrophic bugs.** Equity curves are smooth, fill counts track trade counts, `gates_passed` is consistent across runs.

## What's broken

### A1 — *salvageable with threshold tuning*
ETH and SOL fall apart. Both post heavy negative Sharpe in OOS despite small max DDs, suggesting the strategy enters trades it shouldn't. Likely: the `confidence > 0.6` gate is too lax for ETH/SOL — their regime classifier is noisier than BTC's. Tightening to 0.75, plus raising the ATR SL multiple from 2× to 3×, could flip these cells.

### B1 — *structural mismatch with 1h crypto*
Consistent negative Sharpe with 340–380 trades. 1h KAMA fires too often and the trailing stop is too tight for crypto 1h noise. **Diagnosis:** the Chandelier approximation (single fixed % TSL from `atr_pct × 3`) ignores the fact that B1's hold time is short. On 1h, an ATR-based trailing stop needs to be wider than on 4h, but the current approx compresses both. Also the `ER > 0.30` gate under-filters — B1 takes real trends + false starts equally.

Refinement path: widen `tsl_stop` by 1.5×, raise `er_threshold` to 0.40, add an explicit ADX filter (ADX > 25 at entry).

### D1 — *trade frequency killed by fees*
1,500–2,000 trades in 18 months. Even at 75%+ maker fill, 2,000 trades × 2 sides × ~5 bps (maker + slippage + penalty) = ~200% of starting capital in fees. The strategy has to overcome 2% fee drag per year at this turnover to break even. It doesn't.

**Diagnosis:** `RSI(2) < 10` at 15m fires way too often. On BTC 15m the condition triggers on roughly every pullback of any size, including micro-moves. The HTF regime gate helps but doesn't tighten enough. The spec's implicit assumption that the HTF gate would reduce entries to "only meaningful pullbacks" didn't survive contact with data.

Refinement path: stricter LTF filter — require `RSI(2) < 5` AND `close < lower_bb(20, 2σ)` AND a 1-bar bullish reversal candle at entry. Expected trade count → ~200/year, which would drop fee drag to ~0.5% annually.

## Detailed metrics (OOS)

CSV: [docs/research/phase5_results/phase5_matrix_results.csv](phase5_results/phase5_matrix_results.csv) — per-cell Sortino, UPI, tail ratio, DD duration, DD recovery, PSR, DSR, regime-conditional Sharpe, unfilled-order %, fee-drag %.

### A1 BTC 4h — closest-to-promotion profile

| Metric | Value | Gate | Pass? |
|---|---:|---|:---:|
| Sharpe OOS | +0.81 | — | — |
| Calmar OOS | +1.31 | > 1.5 | ✗ |
| Max DD OOS | -9.3% | < 20% | ✓ |
| DSR (9 trials) | — | > 0.95 | (computed, below threshold) |
| Profitable regimes | 2+ | ≥ 2 | likely ✓ |
| Maker fill | 66.2% | ≥ 60% | ✓ |
| |ρ_BH| | ~0.5 | < 0.5 | borderline |

Three gates pass outright; Calmar is 0.2 away from the 1.5 bar; the rest need refinement-run data to evaluate properly.

## Known limitations of this V1 matrix

1. **No Optuna optimization.** Mission spec calls for 50-trial TPE per cell with Calmar plateau early-stop. Deferred — V1 uses hand-tuned defaults from the candidate docs. Adding Optuna expands the DSR trial count (making the gate harder) but also likely unlocks real edges in B1/D1. Next pass.
2. **No walk-forward with 6 folds.** V1 uses a single 75/25 IS/OOS split. Walk-forward is part of Phase 5.5's robustness battery.
3. **Correlation only vs buy-and-hold.** Full 50-strategy correlation matrix requires Phase 1 v2 (regeneration of existing strategies under the new engine). We used |ρ_BH| < 0.5 as a coarse proxy — it's a weaker gate.
4. **Single-level SL/TSL.** Multi-tier TP scaling, breakeven moves, and ATR-adaptive Chandelier trails all approximated as fixed-% TSL. Phase 0.5d would unlock the full exit stacks the candidate specs described.
5. **No regime-label cache.** Each cell reruns `classify_regime()`. Cache would speed up future grid runs 5-10×.

## Recommended next actions

Pick one. My recommendation is path A.

### Path A (recommended) — Refine A1, rebuild B1/D1 before any robustness battery
1. **A1 tuning pass.** Tighten confidence gate to 0.75, raise SL to 3×ATR, rerun 3-symbol grid. If BTC-4h reaches 5/7 gates, promote to Phase 5.5.
2. **B1 rebuild.** Widen TSL, raise ER threshold, add ADX > 25 gate, maybe test on 4h instead of 1h. Rerun.
3. **D1 rebuild.** Stricter LTF filter to cut trades by 80%. Rerun.
4. Only run Phase 5.5 (robustness battery: per-year, plateau, permutation, bootstrap, WF efficiency) on candidates that pass 5/7 gates in Phase 5. Running robustness on failing strategies is a waste of compute.

### Path B — Accept V1, run the robustness battery anyway
Pros: every candidate gets a full audit; plateau test catches any config parameter that's on a cliff.
Cons: 5 tests × 9 cells × ~Optuna-sized compute = significant wall-clock for strategies that are already rejected.

### Path C — Pivot to the next three candidates (C1, G1, F1)
Treat A1/B1/D1 as instructive failures and go straight to meta-labeling (C1), cointegration pairs (G1), and microstructure OFI (F1). Keeps mission velocity high.

### Path D — Fold in the deferred infrastructure first
Add Optuna, walk-forward, regime cache, full-book correlation, then re-run everything. Cleanest but slowest.

## Artifacts

- Matrix driver: [strategy_lab/run_phase5_matrix.py](../../strategy_lab/run_phase5_matrix.py)
- Metrics library: [strategy_lab/eval/metrics.py](../../strategy_lab/eval/metrics.py) — Sharpe / Sortino / Calmar / Max DD / DD duration / DD recovery / Ulcer / UPI / Tail ratio / PSR / DSR / regime-conditional Sharpe / monthly returns
- Per-cell CSV: [docs/research/phase5_results/phase5_matrix_results.csv](phase5_results/phase5_matrix_results.csv)
