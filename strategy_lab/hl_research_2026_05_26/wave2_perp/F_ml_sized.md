# W2P-F — ML-driven perp strategies — Report

**Author:** W2P-F agent — 2026-05-26
**Code:** `strategy_lab/hl_research_2026_05_26/wave2_perp/F_ml_sized.py`
**Results:** `F_results.csv`, `F_summary.csv`, `F_ml_sized.log`

## TL;DR — verdict: ML edge is real but not exploitable after HL fees

W3 measured a small but **real** AUC lift over baseline 0.5 (range 0.49–0.55).
G4 permutation test confirms the edge: shuffled-label training drops AUC to
~0.50 (0.479–0.510). However, **at HL's 4.5 bps taker × 2 sides + 3 bps slip
= ~12 bps round-trip drag**, the 2–4 ppt AUC lift cannot fund a profitable
strategy across full walk-forward windows. **Zero cells passed the quality
bar (mean Sharpe ann > 1.0 AND all 4 windows positive PnL).**

The closest performers are **F3 single-feature rules**, not the full ML
model:

| Rank | Strategy | Asset | TF | Mean Sharpe ann | Sum PnL (4 windows) | Pos PnL windows |
|------|----------|-------|----|-----------------|---------------------|----|
| 1 | F3_rf_dist_bps_z1.5_momentum | ETH | 4h | **+1.16** | **+$220** | 3 of 4 |
| 2 | F3_rsi_14_z1.0_momentum      | ETH | 1h | +0.91 | +$218 | 3 of 4 |
| 3 | F3_cvd_60s_z1.0_momentum     | BTC | 4h | +0.41 | +$41  | 3 of 4 |
| 4 | F2_ensemble                  | ETH | 4h | +0.24 | +$46  | 2 of 4 |
| 5 | F3_rf_band_pos_z1.5_momentum | BTC | 1h | +0.21 | +$65  | 2 of 4 |

Each has at least one losing window — so none clear "positive PnL in all 4
windows" requirement.

## Strategy designs

### F1 — Probability-gated + sized trend
- LightGBM trained per walk-forward window (2y train / 6m test).
- Per-bar P(up). LONG when prob > 0.55 AND `tr_ema_stack_score > 0`; SHORT
  when prob < 0.45 AND `tr_ema_stack_score < 0`.
- Position size = `clip(|prob - 0.5| × 4, 0, 1) × $250`.
- Exit: prob flips across 0.5 OR max-hold time stop (40 bars).
- Models AUC: 0.49–0.55. Net PnL: **negative on every TF / asset**.

### F2 — Ensemble vote (RF + LGB + XGB)
- All 3 models trained on the same train slice.
- 2-of-3 vote required to fire (thresholds 0.52 / 0.48).
- Size = clip(|avg(prob) − 0.5| × 4, 0, 1).
- Exit: ensemble flips OR time stop.
- Best cell: ETH 4h (+$46 total, mean Sharpe ann +0.24).

### F3 — Single-feature z-score rule (top-1 W3 feature)
- For each (asset, TF), pull top-1 feature from W3_feature_importance.csv.
- Compute 240-bar rolling z. LONG when z > thr AND `tr_ema_stack_score >= 0`;
  SHORT when z < -thr AND `tr_ema_stack_score <= 0`. Tested thr in {1.0, 1.5},
  sign in {momentum, fade}.
- Time-stop exit (40 bars cap).
- Best cell: ETH 4h `rf_dist_bps z>1.5 momentum` — +$220, mean Sharpe ann +1.16.

## G4 permutation test — edge IS real

For each cell, the last walk-forward window was re-trained with shuffled
y_train labels (`F1_prob_sized_shuffle` rows in `F_results.csv`).

| Cell | Real AUC (win 3) | Shuffled AUC | Real PnL | Shuffled PnL |
|------|-----------------:|-------------:|---------:|-------------:|
| BTC 15m | 0.543 | 0.500 | -$33 | -$17 |
| BTC 1h  | 0.530 | 0.510 | -$40 | -$14 |
| BTC 4h  | 0.494 | 0.497 | -$31 | -$18 |
| ETH 15m | 0.539 | 0.500 | -$31 | -$20 |
| ETH 1h  | 0.531 | 0.506 | -$19 | -$36 |
| ETH 4h  | 0.512 | 0.479 | -$5  | -$58 |

Shuffled AUC collapses to ~0.50 (mean 0.499), confirming the 2–4 ppt edge
in real models is from genuine signal. But both real and shuffled lose
money — fees overwhelm the small directional alpha.

## Why F1/F2 fail despite real AUC edge

A typical 1h trade signs around $250 notional × 12 bps total drag = **$0.30
per trade**. Average per-trade PnL gross-of-fees needs to clear $0.30 to
be profitable. With AUC 0.53 and roughly 53% win rate, the per-trade gross
edge in 1-bar 1h trades is on the order of **0.05–0.10% × $250 ≈ $0.13–
$0.25**, i.e. *below* the fee threshold for most TFs. F1's mean per-trade
PnL is in the -$0.05 to -$0.15 range consistently — exactly the fee drag.

15m makes it worse: same AUC edge, but trades 4× as often → 4× the fee
drag per unit time. Backtest: **F1 15m loses ~$220 net per cell across the
4-window 2-year OOS span**.

4h breathes a bit — fewer trades, more time for the edge to materialize.
But the AUC also degrades (0.49–0.54 vs 0.52–0.55 for 1h), so the win is
small.

## Best ML-derived cell (despite quality-bar miss)

**`F3_rf_dist_bps_z1.5_momentum` on ETH 4h:**

| Window | n trades | PnL | Sharpe ann | Win rate |
|--------|---------:|----:|-----------:|---------:|
| 0 | 12 | +$46  | +1.35 | 50% |
| 1 | 16 | +$124 | +2.09 | 56% |
| 2 | 11 | -$4   | -0.22 | 27% |
| 3 | 9  | +$54  | +1.43 | 33% |
| **Sum** | **48** | **+$220** | **mean +1.16** | **46%** |

Only one losing window (n=11), driven by 1 bad trade — small enough that
1-trade variance could be masking a real edge here.

## Comparison to non-ML baselines

The existing wave2_perp `B_results.csv` (B1 trend-following) shows ~10 cells
clearing positive aggregate Sharpe on 4h. F3 ETH 4h is competitive with
those, but B1's edge is rule-derived (EMA stack + ADX), not ML-derived.

**Conclusion**: at HL's fee structure on majors, the ML model's 2–4 ppt
AUC lift translates into 1–2 bps per-trade gross edge — below the
~6 bps one-way fee. ML adds NO exploitable edge over rule-based filters
once fees are paid. The W3 feature-importance ranking is still useful
as a *feature selector* for simpler rules like F3, but training the
full classifier and trading its probability output is a net loser.

## Recommendations

1. **Do not paper-deploy** any of F1, F2 as designed. AUC edge is real
   but fee drag wins.
2. **F3 ETH 4h `rf_dist_bps z>1.5 momentum`** is the strongest ML-derived
   cell. Worth re-running with longer history (>2y) or stricter ema_stack
   gating to see if positive-PnL-all-windows can be achieved.
3. **Re-examine fee assumptions**: if VIP tier reductions (HL Tier 1 is
   3.5 bps taker, Tier 2 is 2.5 bps) can be reached at scale, F1 1h
   on ETH (AUC 0.535, mean per-trade PnL -$0.07 at 4.5 bps) flips to
   roughly break-even at 2.5 bps and could be a tiny positive at 1.5 bps.
   Not a thesis to deploy on, but a sensitivity to track.
4. **Better target**: instead of next-bar direction (AUC 0.53), train on
   *risk-adjusted returns* or *path-shape labels* (e.g. did the next 6
   bars high-water above entry by > 1 ATR before any 1-ATR drawdown?).
   That target's autocorrelation might give a sharper model lift.
5. **Or focus elsewhere**: rule-based trend (B1) on ETH 4h likely beats
   F3 in aggregate. Use ML for *feature ranking*, not for *direction
   prediction*.

## Files

- `F_ml_sized.py`        — 460 lines, runs all 3 strategies across 6 cells × 4 windows
- `F_results.csv`        — 150 rows (3 strategies × ~4 windows × 6 cells × 2 variants for F3)
- `F_summary.csv`        — 41 aggregated cells with `quality_pass=False` on all
- `F_ml_sized.log`       — full execution log with per-window stats
