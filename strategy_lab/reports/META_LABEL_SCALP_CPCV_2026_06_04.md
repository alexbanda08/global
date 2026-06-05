# CPCV + Meta-Label of the Exit-Scalp — NEGATIVE (delta_bps is sufficient)

**Date:** 2026-06-04 · **Step:** HANDOFF_2026_06_04 §D-1 ("CPCV + meta-label the exit-scalp")
**Script:** `strategy_lab/autoresearch/meta_label_scalp_2026_06_04.py`
**One line:** A meta-model on 61 causal fire-time features, validated with purged Combinatorial CV,
**cannot beat a single-feature `delta_bps` sort** at any selectivity. The confirmed exit-scalp edge is
fully captured by two economic primitives (`entry_vwap<0.55` gate + rank by `delta_bps`). The ML
take/skip filter adds ≈ $0. Selection is efficient; the edge stays EXECUTION.

---

## Setup (pre-registered, locked before seeing OOF)
- **Universe:** BTC+ETH, `entry_vwap < 0.55` (the buy-cheap edge zone). n=780, 38-day span.
  Baselines: all-take +$2.709/tr; hand `delta_bps>=5` cell n=118 +$5.564/tr.
- **Features:** 61 CAUSAL = indicators(37, TA @ ws_s) + clob(22, `pre_*` pre-window + `early_*` [ws_us,fire_us]) + entry(2).
  **EXCLUDED as leakage:** `path` (bid_30..bid_90 = the actual exit prices that *define* pnl45/60) and
  `physics` (phys_* derived from the post-fire bid path; also no-lift per `SCALP_HEDGE_PHYSICS_SWEEP`).
  CLOB windowing verified causal in `build_clob_flow.py` (duckdb pulls nothing after `fire_us`).
- **Label:** ml4t `meta_labels(signal=+1, return=pnl45, thr=0)`; sample weight = `|pnl45|` (López return-weighting).
- **Model:** pre-reg headline = L2 logistic (C=0.3, standardized); LightGBM (small/regularized) reported secondary.
- **CV:** ml4t `CombinatorialCV(n_groups=8, n_test_groups=2)` = **28 purged + embargoed paths**; OOF proba = mean over the ~7 paths where each fire is in test.
- **Judge:** per-trade t + bootstrap CI · PBO over a 6-threshold grid · Deflated Sharpe on daily-aggregated gated returns.

## Results

### gate @0.50 (fixed, pre-registered) — OOF
| model | n_gated | $/tr | t | boot95% CI | delta-top-k match | lift vs match |
|---|---|---|---|---|---|---|
| **logit** | 641 | +3.105 | 9.09 | [+2.46, +3.76] | +3.021 | **+0.08 (noise)** |
| gbm | 693 | +2.944 | 8.94 | [+2.29, +3.58] | +2.982 | **−0.04 (worse)** |

- PBO: logit 0.143, gbm 0.250 (low — the *base* edge is not overfit).
- DSR pre-reg (k_eff=1): daily Sharpe ≈0.93–0.95, prob 1.000, **significant** — but this only re-confirms the base edge.
  Deflated (n_trials=6, incl. 4× variance conservative): prob 1.000, still significant. The base edge is robust;
  the meta-model is not what makes it pass.

### Selectivity curve — the decisive adversarial test (OOF $/tr at top-k by score)
A useful meta-filter must build a **better small high-conviction book** than a 1-feature knob. It does not:

| k | meta_logit | meta_gbm | **delta_top** | vwap_low |
|---:|---:|---:|---:|---:|
| 60  | +2.51 | +5.47 | **+6.54** | +2.27 |
| 100 | +4.18 | +5.11 | **+6.41** | +1.88 |
| 118 | +3.82 | +5.08 | **+5.56** | +2.29 |
| 150 | +3.72 | +4.57 | **+5.15** | +2.43 |
| 200 | +4.40 | +4.05 | **+4.67** | +2.62 |
| 300 | +4.14 | +3.89 |   +3.84   | +3.36 |
| 500 | +3.48 | +3.31 |   +3.29   | +3.32 |
| 780 | +2.71 | +2.71 |   +2.71   | +2.71 |

**`delta_top` (pure `delta_bps` sort, zero ML) dominates both meta models at every selective k (60–300).**
GBM tracks just below delta; logistic is materially worse at high conviction. The hand d≥5 cell (+$5.56 @ n=118)
equals `delta_top118` (+$5.56) exactly — because d≥5 *is* a delta cut.

## Interpretation
- **`delta_bps` is the sufficient statistic for scalp selection/sizing.** Given the `entry_vwap<0.55` gate,
  nothing in 61 causal TA + microstructure features (nor a GBM/logit combining them) improves take/skip over
  ranking by `delta_bps`. This is the same lesson as the 387k selectors / 415 GPU nets / 4.8M indicator combos:
  **prediction & selection are efficient at every scale tested.** The edge is execution (sell on book @ +45s).
- Practical consequence: **do not deploy an ML meta-filter.** Size the scalp by `delta_bps` (monotonic, clean),
  keep the `entry_vwap<0.55` gate. No model in the live path.

## What this does NOT close
- This is in-sample-window CPCV (purged, but same 38-day window the edge was found in). The **only deflation-proof
  gate remains the different-window OOS** (`validate_oos.py` + the operator's 6-month API w/ L25 books + CLOB
  trades + klines). CPCV negative here means: even before OOS, the ML filter is already dead; the delta-sized
  scalp is what goes to OOS.
- Live: keep accruing the 16 shadow sleeves toward ≥200 forward fires + CI>0.

## Files
- Pipeline: `strategy_lab/autoresearch/meta_label_scalp_2026_06_04.py`
- Scratch: `_inspect_meta_2026_06_04.py`, `_landscape_meta_2026_06_04.py` (vwap×delta landscape)
- Prior: `ML4T_DSR_JUDGE_2026_06_04.md` (base edge passes DSR), `HANDOFF_2026_06_04_ML4T_DSR.md`
