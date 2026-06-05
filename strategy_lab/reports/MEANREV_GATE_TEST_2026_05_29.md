# Mean-Reversion / Fade-Momentum Gate Test
**Date:** 2026-05-29  
**Hypothesis:** pandagon wallet (0x7399fe3e) wins by FADING short-term momentum and entering cheap. Decode showed: winners have negative ema9_slope / ret_5m, avg entry 0.607. Rule = buy side OPPOSITE to recent momentum, especially when cheap.

---

## Strategy Definitions

Three strategies added to `strategy_lab/directional_signal/eval_strategies.py`:

| Strategy | Rule | px gate | Plateau sweep |
|---|---|---|---|
| `fade_mom` | Up if `ema9_slope_bps < 0` else Down (invert EMA momentum) | 0.55–0.92 (standard) | (0.50/0.55/0.60) × (0.88/0.92/0.95) |
| `fade_ret60` | Up if `ret_60s_bps < 0` else Down (invert 60s return) | 0.55–0.92 (standard) | (0.50/0.55/0.60) × (0.88/0.92/0.95) |
| `fade_mom_cheap` | Fade ema9_slope, ONLY when faded side vwap < 0.55 (cheap-entry match) | 0.12–0.55 | (0.12/0.20/0.30) × (0.45/0.50/0.55) |

All strategies use the canonical gate stack (LegacyConfig 2%-on-profit fees, same-token spread ≤ 0.02/0.025, book fill required).

---

## Raw Predictive Accuracy (vs Chainlink outcome, pre-gate)

Fading the signal means predicting the outcome is OPPOSITE to the momentum direction. These are unconditional hit rates on all slugs at the primary offset (60s for 5m, 180s for 15m):

| market | fade_mom accuracy | fade_ret60 accuracy | cheap subset n | cheap WR |
|---|---|---|---|---|
| btc_15m | 0.3961 (sub-50%) | 0.4643 (sub-50%) | 2,384 | 0.3289 |
| btc_5m | 0.4670 | 0.4143 | 5,747 | 0.3551 |
| eth_15m | 0.4081 | 0.4406 | 2,355 | 0.3316 |
| eth_5m | 0.4801 | 0.4090 | 5,641 | 0.3593 |
| sol_15m | 0.3929 | 0.4399 | 2,354 | 0.3190 |
| sol_5m | 0.4776 | 0.4098 | 5,444 | 0.3543 |

**Key finding:** Fading ema9_slope predicts the outcome at ~39–48%, which is WORSE than 50% (i.e., momentum continuation is mildly predictive, making the fade wrong more often than random). Cheap fade WR is 32–36% — deeply negative EV at typical entry prices. The raw direction signal does not support the pandagon hypothesis on the broad universe.

---

## Per-Market Gate Table (primary offset only)

Gates: G1 = mean PnL > 0 | G2 = walkforward ≥ 75% windows positive | G3 = permutation p < 0.05 | G4 = bootstrap CI lower > 0

### fade_mom

| market | n | WR | mean_pnl | G1 | G2 (WF) | G2 windows | G3 p | G3 | G4 lo | G4 hi | G4 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| btc_15m | 622 | 0.6383 | -0.2895 | FAIL | FAIL | 8/14 | 0.0005 | PASS | -1.817 | 1.171 | FAIL |
| btc_5m | 3077 | 0.6558 | -0.5570 | FAIL | FAIL | 6/14 | 0.0005 | PASS | -1.185 | 0.078 | FAIL |
| eth_15m | 580 | 0.6724 | +0.6925 | **PASS** | FAIL | 10/14 | 0.0005 | PASS | -0.787 | 2.160 | FAIL |
| eth_5m | 2928 | 0.6779 | -0.0536 | FAIL | FAIL | 7/14 | 0.0005 | PASS | -0.705 | 0.571 | FAIL |
| sol_15m | 447 | 0.6421 | -0.3312 | FAIL | FAIL | 5/14 | 0.0005 | PASS | -2.060 | 1.404 | FAIL |
| sol_5m | 2183 | 0.6665 | -0.4828 | FAIL | FAIL | 4/14 | 0.0005 | PASS | -1.226 | 0.264 | FAIL |

### fade_ret60

| market | n | WR | mean_pnl | G1 | G2 (WF) | G2 windows | G3 p | G3 | G4 lo | G4 hi | G4 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| btc_15m | 918 | 0.7026 | +0.9537 | **PASS** | **PASS** (11/14) | 11/14 | 0.0005 | PASS | -0.159 | 2.063 | FAIL |
| btc_5m | 1763 | 0.6557 | -0.2633 | FAIL | FAIL | 6/14 | 0.0005 | PASS | -1.122 | 0.594 | FAIL |
| eth_15m | 833 | 0.6675 | -0.6173 | FAIL | FAIL | 6/14 | 0.0005 | PASS | -1.810 | 0.565 | FAIL |
| eth_5m | 1539 | 0.6699 | -0.3337 | FAIL | FAIL | 9/14 | 0.0130 | PASS | -1.242 | 0.540 | FAIL |
| sol_15m | 730 | 0.6712 | -0.5467 | FAIL | FAIL | 3/14 | 0.0005 | PASS | -1.847 | 0.715 | FAIL |
| sol_5m | 1246 | 0.6388 | -1.3215 | FAIL | FAIL | 4/14 | 0.4028 | FAIL | -2.335 | -0.345 | FAIL |

### fade_mom_cheap

| market | n | WR | mean_pnl | G1 | G2 (WF) | G2 windows | G3 p | G3 | G4 lo | G4 hi | G4 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| btc_15m | 2147 | 0.3354 | -2.0582 | FAIL | FAIL | 4/14 | 1.000 | FAIL | -3.523 | -0.591 | FAIL |
| btc_5m | 5029 | 0.3615 | -1.9189 | FAIL | FAIL | 2/14 | 1.000 | FAIL | -2.825 | -0.981 | FAIL |
| eth_15m | 1872 | 0.3371 | -1.5268 | FAIL | FAIL | 5/14 | 1.000 | FAIL | -3.112 | 0.119 | FAIL |
| eth_5m | 4561 | 0.3624 | -1.5675 | FAIL | FAIL | 4/14 | 1.000 | FAIL | -2.529 | -0.598 | FAIL |
| sol_15m | 1677 | 0.3053 | -4.3535 | FAIL | FAIL | 4/14 | 1.000 | FAIL | -5.936 | -2.751 | FAIL |
| sol_5m | 3523 | 0.3540 | -2.6854 | FAIL | FAIL | 3/14 | 1.000 | FAIL | -3.738 | -1.598 | FAIL |

---

## Notable Anomaly: fade_ret60 btc_15m

This is the only cell passing G1+G2+G3:
- n=918, WR=70.3%, mean_pnl=+$0.954, walkforward 11/14 windows positive
- G4 CI lower = -0.159 (just below zero) → G4 FAIL
- Plateau verdict = PASS (82.2% of cells +EV)

This looks superficially promising but fails G4 (the strictest quantitative gate). The CI straddles zero: the positive PnL signal is real in-sample but the uncertainty interval is too wide to confirm a positive expected value at the bootstrap confidence level. This is exactly the kind of fragile signal the gate system is designed to catch — it passes 3 of 4 gates but the one it fails (CI lower > 0) is the deciding criterion for deployment.

Additionally, this is a single market/timeframe among 18 (6 markets × 3 strategies). With 18 comparisons, 1 false positive at p~0.05-level is expected by chance.

---

## Gate Summary by Strategy

| strategy | markets tested | G1 pass | G1+G2 pass | G1+G2+G3 pass | G1+G2+G3+G4 (full) |
|---|---|---|---|---|---|
| fade_mom | 6 | 1 (eth_15m) | 0 | 0 | 0 |
| fade_ret60 | 6 | 1 (btc_15m) | 1 (btc_15m) | 1 (btc_15m) | **0** |
| fade_mom_cheap | 6 | 0 | 0 | 0 | 0 |

**No strategy passes all four gates in any market.**

---

## Structural Interpretation

The WR numbers for fade strategies (63–68%) in the standard px range look deceptively attractive. But these are LOWER WR than the momentum strategies on the same markets (which run ~69–72% WR). The fade direction has lower raw hit rate, and the higher-variance entry prices (fading into a move means buying at mid-book prices, not near resolution) blow out the variance, keeping G4 CI lower negative.

`fade_mom_cheap` is the closest analog to pandagon's decoded behavior. Its WR collapses to 31–36% — the "cheap" entry filter (vwap < 0.55) selects slugs where the market strongly disagrees with the faded direction, making the fade costly when wrong. The cheap-tail market discount is there to compensate for lower win probability, but not enough at the universe level.

**Why pandagon fades profitably:** pandagon's edge is likely a SLUG SELECTION signal (not fired on the whole universe), combined with timing and possibly order-type advantages (limit fills, timing entry to a specific book state). The strategy is not a naive univariate fade of ema9_slope on all available slugs — it fires selectively. Our scan cannot reproduce the slug-selection signal from canonical data alone (same gap as the F2 wallet problem).

---

## Verdict

**FAILS LIKE THE REST. Do NOT deploy.**

- `fade_mom`: fails G1+G4 in 5/6 markets. One G1 pass (eth_15m) with negative CI.
- `fade_ret60`: one partial pass (btc_15m G1+G2+G3) but G4 CI lower = -0.16 (just misses). 17/18 cells fail. 1 cell surviving 18 comparisons = likely statistical noise.
- `fade_mom_cheap`: catastrophic. 31–36% WR, deeply negative PnL, G3 p=1.0 (the universe strongly rejects the positive direction). Bootstrap CI lower is -3 to -6.

The mean-reversion / fade-momentum hypothesis, applied as a universal rule on the full dirscan universe, does NOT generate systematic edge. The pandagon wallet's profitable fading behavior requires a slug-selection signal not recoverable from our canonical feature set. This confirms the EFFICIENT_MARKET_FINDING: canonical directional signals (ema9, ret_60s, cl_basis deviation, market price) have been priced in by the Polymarket market maker at the 0.55–0.92 price range we test in.

The only surviving directional strategy remains `clbasis_rel-btc-5m` (G1+G2+G3+G4 PASS, plateau=PASS 97.8%), which exploits a structural oracle lag rather than a price-momentum or mean-reversion edge.

---

## Files

- Strategy code: `strategy_lab/directional_signal/eval_strategies.py` (fade_mom, fade_ret60, fade_mom_cheap added)
- Full results: `data/v4/canonical/_results/dir_eval_results.csv`
- Plateau detail: `data/v4/canonical/_results/dir_eval_plateau.json`
- Context: `strategy_lab/reports/EFFICIENT_MARKET_FINDING_2026_05_28.md`
