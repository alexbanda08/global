# ML / Agentic Strategy Development — Next-Phase Plan — 2026-06-03

Grounded in a 3-stream codebase audit (dataset+labels, every prediction path tried, live-engine decision
plumbing). This plan deliberately does NOT propose "predict 5m/15m direction with a bigger model" — the
research shows that is efficient-market-dead. It reframes ML around the problems that are *not* dead.

---

## 0. THE HARD PRIOR (internalize before writing a line of model code)

Across ~15 documented attempts, **direction prediction at `ws_s` from price/technical features is a
coin-flip.** Dead: RSI/KAMA/CUSUM/semivariance/Kalman/Rogers-Satchell (~50%), BSM/N(d2) at expiry
(step function), cross-CEX lead-lag standalone, physics/strike-distance, anchored-VWAP fade, complete-set arb.

The recurring killer is the **PRICED-IN TRAP**: any signal read *after* the slug opens (VPIN, CVD, book
depth, ask asymmetry) shows **67–89% WR but −$0.62 to −$1.03/tr** — the move is already in the entry vwap
(0.68–0.87), and the 0.07 fee finishes it. **WR ≠ edge.** A classifier trained to maximize accuracy/AUC on
the outcome label will walk straight into this trap (it will learn "high vwap → likely win" which is true and
worthless). **The label must be PnL-after-fees, not outcome.**

Five constraints every ML artifact must respect (each one already cost us a session):
1. **Anchor at `ws_s = slot_start − window_s`**, `asof_strict` everywhere. Leaking to `slot_start` inflates hit-rate 25–40pp.
2. **Score on `engine_v2` LiveMimic fills** + **0.07 winner-only fee** + **10Hz L25** (`subsample_1hz=False`) + **cross-token spread**. Never same-token bid-ask, never legacy 2% fee, never 1Hz.
3. **Small n.** ~33–40 day common window, ~42k resolutions total, a few hundred–thousand fires per (asset×tf) cell. This dictates model choice (below).
4. **Live latency budget <50ms p95**, model inference must fit. Rules out CPU torch/LSTM in the live path.
5. **Promotion bar = the scalp bar:** ≥200 live forward shadow fires + bootstrap CI>0 before any real capital.

---

## 1. REFRAME — four ML problem types that are NOT dead

| # | Problem | Why it's open | Label / target | Base signal it rides |
|---|---|---|---|---|
| **P1** | **Meta-labeling** (take/skip + size a base fire) | base signal already carries real-but-thin info; model only filters the trap fires | **PnL-after-fee sign** of the fire (López de Prado meta-labeling) | lag-taker, momo-F7, sniper — all confirmed real-but-thin |
| **P2** | **Exit-timing** for the scalp | the ONE live edge; +60s beats hold, but per-trade optimal exit unmodeled | regression: time-to-profitable-exit / P(reaches TP before decay) | exit-scalp (deployed) |
| **P3** | **Regime / session classifier** | anti-edge shows same sleeve flips sign by UTC session; today only brittle hand-tuned HoD tables | regime label → portable gate multiplier on any sleeve | all sleeves |
| **P4** | **Relative-value / mispricing** at *pre-window* timing | lag-taker generalization; N(d2) only died *at expiry*, untested pre-window where θ≠0 | regression: `model_P − poly_ask` > fee | new sleeve |

**P1 and P2 are the priority.** P1 because meta-labeling on an already-real signal is the highest-probability
ML win and is exactly what the abandoned `meta_classifier/` scaffold was reaching for. P2 because it directly
protects/sharpens the only edge we have in live shadow right now.

---

## 2. MODEL SELECTION — honest, grounded in n (addresses your XGBoost/LSTM/SVR/RF/genetic asks directly)

| Algorithm | Verdict for THIS problem | Where to use |
|---|---|---|
| **XGBoost / LightGBM / HistGradientBoosting** | ✅ **PRIMARY.** Tabular, small-n, handles missing (we have stale/empty feeds), fast (<2ms) CPU inference, monotonic constraints, SHAP interpretability. | P1 meta-labeler, P3 regime, P4 RV |
| **Random Forest** | ✅ baseline / ensemble member. Less prone to the few-shot overfit than boosting if depth-capped; good variance check. | baseline vs XGB everywhere |
| **SVR (support-vector regression)** | 🟡 niche. Reasonable for the small-n **continuous** targets (P2 exit-time, P4 edge bps) with RBF kernel; needs careful scaling, no native missing-value handling, no probability calibration. Use as a regression baseline, not primary. | P2/P4 baseline |
| **LSTM / 1D-CNN / TCN** | 🔴 **NOT primary.** 40 days of data will overfit a recurrent net; and CPU inference blows the live latency budget. ONLY justifiable on the **dense sequence** problem (P2 exit-timing on 1s/10Hz L25 paths) and even then expect GBT-on-engineered-features to win. If pursued: heavy dropout/weight-decay, walk-forward, export to ONNX + quantize, keep OFFLINE first. | P2 experimental arm only |
| **Genetic / "DNA" / evolutionary search** | 🟡 **search wrapper, not a predictor.** Use GA for feature-subset selection, threshold tuning, or rule mining — *wrapped around the purged-walk-forward + lockbox protocol*. Standalone GA-mined rules are the #1 overfit risk (we already have lockbox machinery; reuse it). Never let GA touch the lockbox more than once. | hyperparam/feature search |
| **Logistic / Elastic-Net** | ✅ calibration-friendly transparent baseline; if XGB can't beat it, the features are the problem, not the model. | sanity baseline |

**Mandatory regardless of model: probability calibration (isotonic or Platt).** We trade calibrated-prob
vs entry-vwap — a miscalibrated 0.7 is a losing trade. The old scaffold already did isotonic; keep it.

**Decision rule:** start with XGBoost + isotonic, RF + ElasticNet as challengers. Only escalate to
sequence/LSTM if (a) GBT plateaus AND (b) the residual signal is plausibly sequential (exit-timing). This
ordering is dictated by n, not fashion.

---

## 3. VALIDATION PROTOCOL (the non-negotiable spine — reuse, don't reinvent)

- **Purged, embargoed walk-forward CV** (López de Prado): time-ordered folds, purge labels whose window
  overlaps the test fold, embargo a buffer after each test fold. The existing `meta_classifier/train_eval.py`
  used 3-fold rolling TS-CV — upgrade it to purged+embargo (overlapping 5m/15m windows leak otherwise).
- **3-way data split: train / validation / LOCKBOX.** Lockbox touched exactly once, at the end. The
  `CROSS_FEATURE_RULES` work already established this discipline — mirror it.
- **Metric = $/tr after the 0.07 winner-only fee on engine_v2 fills**, with **bootstrap 95% CI excluding 0**
  and **direction-permutation p**. AUC/accuracy reported only as diagnostics, NEVER as the gate.
- **Deflated Sharpe / Bonferroni**: we will test many cells × models × feature sets — discount for it
  explicitly (Cyclops nearly died on this; n<100 cells are untestable).
- **Forward shadow gate**: deploy as `paper_only` sleeve → accumulate ≥200 live fires → CI>0 before capital.

---

## 4. INFRASTRUCTURE TO BUILD (train==serve parity is the whole game)

1. **Causal feature store** — one `build_features(slug, ws_s)` that emits the feature matrix from canonical
   loaders, used IDENTICALLY offline (training) and online (live `BarContext`). The live `BarContext`
   (agent-3 audit) already computes most of it: `rsi_14_for_signal`, `ret_2m/5m/15m/1h`, `markov_regime_*`,
   `cvd_30s`, `macd_hist`, `rvol_30_300`, `sigma_*`, `vwap_dev_bps`, `fair_edge_bp`, `entry_vwap_yes/no`,
   `spread_pct_*`. **Mirror these field-for-field offline** so there is zero train/serve skew. Add the
   confirmed-informative flow features (HL liq-cascade recency, Hawkes intensity, cross-CEX funding/OI once
   ≥14d data).
2. **Train/eval harness** — resurrect + audit `strategy_lab/meta_classifier/` (it was scaffolded, **never run
   to a published verdict** — first task is to verify it has no ws_s/label leakage, then run it). Outputs a
   model registry artifact (joblib + ONNX) + a scored report.
3. **Live plug-in** — agent-3 found the choke point: inject a `g_ml_score` gate after `strategy.signal()`
   (step 5/6 in `controllers/polymarket_updown.py`) OR a new `strategy_mode="ml_sniper"`. The `fair_edge_bp`
   field is already a rule-based "model vs vwap" hook — the ML model replaces that closed-form with a trained
   one. Inference must be <5ms (XGBoost/ONNX fine).
4. **Shadow sleeve** — plumbing is known: add to `configs/poly_sniper_v5_sleeves.yaml` + matching
   `sniper_v5_sleeves.py` tuple + register gate in `sniper_v5_gates.py`, `paper_only: true`. Promote by
   flipping `paper_only:false` after the forward gate.

---

## 5. PHASED ROLLOUT

**Phase A — Cheap wins / de-risk (1–2 days, no ML yet):**
- Run the **6 cross-feature Hawkes+microprice lockbox survivors** (`CROSS_FEATURE_RULES_2026_05_26.md`:
  XF-I SOL-15m 78.6% WR +$6.31/tr; DISAGR-HAWKES SOL-5m) through **engine_v2 real fills + 0.07 fee**. They
  were validated on rules but never on production fills. If they survive → they are *features* for P1, and
  candidate shadow sleeves. If they die → priced-in trap, drop. Highest information-per-hour task available.
- **Audit the `meta_classifier/` scaffold for leakage** (ws_s anchor, label timing, CV purging) before trusting any output it ever produced.

**Phase B — P1 Meta-labeler (the core ML build):**
- Feature store (item 4.1). Label = PnL-after-fee sign of each historical lag-taker + momo-F7 fire.
- XGBoost + isotonic; RF + ElasticNet challengers. Purged walk-forward + lockbox. Per (asset×tf) cell AND
  pooled-with-asset-dummy (test both — asset-specificity is a known failure mode).
- Success = the meta-labeler lifts $/tr or cuts variance vs taking every base fire, surviving lockbox + CI>0.
- Deploy survivors as shadow sleeves (`g_ml_score` gate on the existing base sleeve).

**Phase C — P2 Exit-timing model (protect the live edge):**
- Target: per-fire optimal exit (regression on time-to-best-exit, or P(reach +X% before decay)) using the
  dense 1s/10Hz path after entry. GBT on engineered path features first; LSTM/TCN as the one justified
  sequence experiment. Feeds the scalp sleeves' exit policy (currently fixed +60s).

**Phase D — P3 Regime/session classifier:**
- Learned replacement for hand-tuned HoD tables → a portable probability multiplier gate usable across all
  sleeves. Lower priority; do after B/C prove the pipeline.

**Phase E — Infra-gated (data projects, parallelizable):**
- P4 relative-value at pre-window timing.
- **Chainlink Data Streams WS direct feed** collection (today the lag-taker uses Binance 1s as a proxy for
  the oracle — the direct sub-second oracle is the highest-value untapped data source).
- **F2 slug-selector**: needs Polymarket CLOB WS event tape — a data-collection project, not a modeling one.
  Catalogue its requirement; don't block the ML phase on it.

---

## 6. THE "AGENTIC DECISION" QUESTION — where agents fit (and where they don't)

- **NOT per-trade live decisions.** LLM/agent inference is far too slow for the <50ms fire budget and would
  overfit. Per-trade decisions stay as fast trained models (XGBoost/ONNX).
- **YES at the meta-allocation layer (slow loop):** a daily/weekly **portfolio-allocator agent** that reads
  rolling shadow/live PnL per sleeve and reweights/kills/promotes sleeves (Kelly-capped) — exactly the
  215-sleeve audit + kill-list work, but automated and recurring. This is a genuine agentic decision with a
  tolerant latency budget and a clear objective (fleet net PnL).
- **YES for research orchestration:** the hypothesis-generate → backtest → adversarially-verify swarm
  (already proven this session — it killed 65 candidates and surfaced the scalp). Formalize it as a recurring
  workflow that proposes feature/sleeve candidates and runs them through the Phase-A engine_v2+lockbox gate
  automatically.

---

## 7. IMMEDIATE NEXT ACTIONS (in order)
1. Phase-A: validate the 6 Hawkes lockbox survivors through `engine_v2` (real fills + 0.07 fee). ← start here
2. Phase-A: leakage-audit `strategy_lab/meta_classifier/` (ws_s anchor + label timing + CV purge).
3. Build the causal `build_features()` store mirroring the live `BarContext` fields exactly.
4. Phase-B: XGBoost meta-labeler on lag-taker+momo-F7 fires, PnL-after-fee label, purged WF + lockbox.
5. Stand up the first `g_ml_score` shadow sleeve; begin the ≥200-fire forward accumulation.

## 8. Source audits behind this plan
- Dataset/labels/features inventory (load.py, coverage, gaps, ws_s trap) — stream 1.
- Prediction-path catalogue (26 paths, dead vs open) — stream 2.
- Live-engine decision plumbing (BarContext fields, gate order, zero current ML, plug-in choke point, shadow
  sleeve recipe) — stream 3.
- Key prior reports: `EDGE_VALIDATION_TIER1_2026_06_01.md`, `NEW_EDGE_RESEARCH_2026_06_01.md`,
  `CROSS_FEATURE_RULES_2026_05_26.md`, `SCALP_VALIDATION_2026_06_02.md`, `LAG_TAKER_OOS_REVAL_2026_06_01.md`,
  `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`, `F2_FINAL_VERDICT_2026_05_18.md`, `meta_classifier/`.
