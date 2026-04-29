# V2 Signals — Findings & Kill Decision

**Date:** 2026-04-29
**Status:** ❌ **All 4 new signals failed forward-walk holdout. V2 stack project abandoned. Reverting to sig_ret5m sniper q10 (existing baseline winner).**

---

## 1. What was built (per `2026-04-29-v2-signals-design.md`)

Implemented a 4-signal calibrated-probability stack to test against the existing `sig_ret5m` strategy:

- **prob_a** — multi-horizon momentum agreement: empirical P(UP) per (asset, tf, votes_up∈{0,1,2,3}) bucket from train slice
- **prob_b** — vol-arb digital fair value: Black-style P(UP) from realized 1m vol + strike + time-to-resolution, isotonic-calibrated on train
- **prob_c** — Polymarket microstructure flow: 60s pre-window taker buy/sell pressure + L5 book ask-imbalance, isotonic-calibrated
- **prob_stack** — logistic regression meta-model on (prob_a, prob_b, prob_c), 3-fold isotonic-calibrated

All 4 added as columns on `data/polymarket/{asset}_features_v3.csv`. Wired into `polymarket_signal_grid_v2.py` and `polymarket_forward_walk_v2.py`. Threshold: BUY UP at p≥0.55, BUY DOWN at p≤0.45, SKIP otherwise.

Implementation tasks 1-7 all green: 19 unit tests pass, 7 commits, repo at https://github.com/alexbanda08/global.

## 2. In-sample IC (looked promising)

Per-asset univariate Information Coefficients on the FULL 7-day sample:

| Asset | prob_a | prob_b | prob_c | prob_stack |
|---|---|---|---|---|
| BTC  | +0.0848 | +0.0496 | +0.0607 | **+0.1232** |
| ETH  | +0.0783 | +0.0107 | +0.0824 | **+0.1123** |
| SOL  | +0.0750 | +0.0458 | +0.0540 | **+0.1049** |

Stack IC beats max individual IC by 36-45% on every asset. Pairwise correlations between the 3 inputs are near-zero (-0.13 to +0.04) — components are genuinely orthogonal. **The meta-model was constructive — but only in-sample.**

LogReg coefficients:
- BTC: prob_a dominates (1.876)
- ETH: prob_c dominates (1.902)
- SOL: prob_a + prob_b co-dominate (~1.9), prob_c contribution weak (0.396 — explains low SOL flow coverage at 48%)

## 3. Out-of-sample forward-walk (the gate)

Chronological 80/20 train/holdout split. Gate criteria: holdout hit ≥60%, ROI ≥+10%, train→holdout drift ≤8pp.

**E10_rev15_hedgehold exit (the recalibration winner)** — best per (signal, tf, asset):

| signal | tf | asset | TR n | TR hit | HO n | HO hit | HO PnL | drift | gate |
|---|---|---|---|---|---|---|---|---|---|
| **q20 (existing)** | 5m | ALL | 984 | 62.9% | 292 | **62.7%** | **+$36.55** | -0.2pp | ✅ PASS |
| q20 (existing) | 5m | btc | 329 | 62.9% | 97 | 61.9% | +$11 | -1.0pp | ✅ PASS |
| prob_a | 5m | ALL | 1832 | 58.1% | 443 | 55.3% | +$28 | -2.8pp | ❌ hit |
| prob_a | 5m | btc | 735 | 57.6% | 185 | 57.3% | +$15 | -0.3pp | ❌ hit |
| prob_a | 15m | ALL | 880 | 58.3% | 213 | 49.8% | +$9 | -8.5pp | ❌ drift+hit |
| prob_b | 5m | ALL | 522 | 59.8% | 580 | 51.6% | +$1 | -8.2pp | ❌ drift+hit |
| prob_c | 5m | ALL | 412 | 61.7% | 233 | **50.2%** | **−$6** | -11.5pp | ❌ all |
| prob_stack | 5m | ALL | 2064 | 60.9% | 766 | 51.8% | +$3 | -9.1pp | ❌ drift+hit |
| prob_stack | 5m | btc | 661 | 59.2% | 135 | 57.0% | +$8 | -2.2pp | ❌ hit |
| prob_stack | 15m | ALL | 816 | 60.2% | 256 | 53.9% | +$14 | -6.3pp | ❌ hit |
| prob_stack | 15m | btc | 226 | 61.1% | 65 | 56.9% | +$5 | -4.2pp | ❌ hit |

**Zero cells pass the gate among the 4 new signals.**

The existing `q20` (sig_ret5m sniper, top-20% by |ret_5m|) remains the only validated cell, and `q10` (top-10%) is even stronger but not shown above (for comparability with the new signals' fire rates).

## 4. Why it failed (honest read)

1. **In-sample IC was real but small (~0.08-0.12).** Pre-trained calibrators captured some 7-day-window-specific microstructure — that microstructure didn't persist into the holdout slice.

2. **Calibration regimes shifted between train and holdout.** prob_a's empirical bucket means assigned 0.43 to votes=0 markets, 0.57 to votes=3 markets. In the holdout, those same buckets resolved closer to 50/50 — the regime that produced the train calibration didn't carry forward to the holdout 20%.

3. **prob_c (microstructure flow) collapsed worst** — 5m ALL: 61.7% train → 50.2% holdout, **−11.5pp**. The 60s pre-window flow signal works in calm regimes but breaks during volatility — and the holdout slice is the most recent 1.4 days, which had different vol than the prior 5.6 days.

4. **prob_stack inherited the regime-fragility of its components.** A logistic-regression stack of 3 calibrators that all overfit gives you a 4th calibrator that overfits.

5. **The base case (sig_ret5m magnitude filter) is genuinely robust** — q10/q20 are nonparametric thresholds (top-N%) computed on the whole window, not learned bucket means. They survive distribution shift better.

## 5. Gate decision

Per design `§7` decision tree:

> **Nothing passes → abandon the V2 stack project; revert to sig_ret5m sniper q10.**

**Decision: kill V2 signals stack. Do not deploy any of the 4 new signals to VPS3.** The existing `sig_ret5m` sniper q10 (BTC 5m ROI +21.6%, hit 72%, n=143 in-sample; ALL 5m ROI +28.0%, hit 77.8% on the same forward-walk holdout) remains the deployable cell.

What stays:
- `sig_ret5m` sniper q10 + maker entry + rev15_hedgehold + HEDGE_HOLD policy + spread<2% filter — per `docs/FINDINGS_2026_04_29.md` and `docs/VPS3_FIX_PLAN.md`. The TV agent's existing fix plan continues unchanged.

What we learned:
- IC (univariate correlation) is necessary but not sufficient. A signal can have positive IC in-sample and zero in holdout if it was capturing transient regime structure.
- Stacking nearly-orthogonal weak signals does compose mathematically (3-component IC sum looks like single-component sqrt(3)·IC) but the gain is on the same fragile base — meta-modeling does not rescue overfit components.
- Polymarket microstructure (prob_c) has the least train→holdout stability. Probably needs >7 days of data to find a robust pattern.

What to try next (NOT this project):
- Bigger time horizon. The 7-day window is too thin for distribution-shift testing; 30+ days would let us fit on 80% (24 days) and validate on the most recent 6 days under more diverse vol regimes.
- Conditional signals — instead of stacking signals always, gate by realized vol regime. "Use prob_c only when vol is low" might survive forward-walk.
- Drop the calibration step. Raw bucket means and digital fair values may be fragile; using just the *sign* of the difference (vs market) would be a non-learned signal less prone to overfit.

## 6. Artifacts

- Code: `strategy_lab/v2_signals/` (4 builders + tests, 19 tests passing)
- Engines wired: `strategy_lab/polymarket_signal_grid_v2.py`, `strategy_lab/polymarket_forward_walk_v2.py`
- Data columns added: `prob_a, prob_b, prob_c, prob_stack` in `{asset}_features_v3.csv`
- Backtest results: `strategy_lab/results/polymarket/signal_grid_v2.csv` (616 rows, 7 signals)
- Forward-walk: `strategy_lab/reports/POLYMARKET_FORWARD_WALK_V2.md`
- Design doc: `docs/plans/2026-04-29-v2-signals-design.md`
- Implementation plan: `docs/plans/2026-04-29-v2-signals-implementation.md`
- This findings doc: `strategy_lab/reports/POLYMARKET_V2_SIGNALS_FINDINGS.md`
- Repo: https://github.com/alexbanda08/global

The code is in the repo, the columns are in the features files, the engines accept them — anyone can re-run with more data later. Just rebuild prob_* and re-validate when 30+ days are available.
