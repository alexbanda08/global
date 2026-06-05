# Session Handoff — 2026-06-04 — ML scale-up + GPU sprint + ml4t/DSR verdict

**READ THIS FIRST.** Long multi-day session. Headline: we threw everything at finding a *predictive* edge
(ML, 8.8y data, GPU deep nets, 4.8M indicator combos, 387k scalp selectors, Kronos) and **formally proved
with Deflated Sharpe that the ONLY real edge is the intra-window EXIT-SCALP (execution, not prediction).**
Everything predictive is efficient/noise at scale. The ml4t toolkit is now installed and is the go-forward
rigor layer.

---

## A. THE ONE-LINE VERDICT
**Prediction/selection is efficient or multiple-testing-noise at every scale we tested; the edge is EXECUTION
— the exit-scalp, which survives formal Deflated Sharpe. Next = harden the scalp (CPCV + meta-label) and gate
it on a genuine different-window OOS. Stop hunting direction.**

## B. WHAT SURVIVED vs WHAT'S DEAD (all tested this session)
### ✅ REAL (survives rigor)
- **Intra-window EXIT-SCALP** — buy lag-token cheap (entry_vwap<0.55, δ≥5), **SELL on the book at TIME+45–60s**
  (not hold to resolution). Deployed as 16 shadow sleeves on VPS3. **Passes Deflated Sharpe** (pre-registered,
  prob 1.0, is_significant) at +45 (Sharpe 0.635) and +60. BTC≫ETH. `ML4T_DSR_JUDGE_2026_06_04.md`.
  - Refinement: **+45s ≥ +60s** (higher t, tighter CI). Per-cell exit table in `SCALP_SLEEVE_AUDIT_2026_06_03.md`.
  - ✅ EXIT LOCKED 2026-06-04 (`SCALP_DYNAMIC_EXIT_2026_06_04.md`): tested take-profit + longer-hold policies w/
    bootstrap+CPCV+DSR — **none beat fixed +45s (cell)/+60s (broad)**; TP caps the runners (paired CI [−1.63,−0.39]
    broad), longer holds decay, $/tr peaks exactly at +45/+60. Oracle pathmax (+$18.5) is a transient inter-sample
    spike, untradeable at 10Hz (possible future tick-level trailing study). Both scalp knobs now pinned at optimum
    (entry=delta_bps §D-1, exit=+45/+60); remaining gate is live fires + different-window OOS, not in-sample tuning.
  - ✅ **DIFFERENT-WINDOW OOS PASSED 2026-06-05** (`SCALP_OOS_PASS_2026_06_05.md`): on Mar 30→Apr 21 (disjoint
    from the Apr22–Jun4 search), gated cell CI>0 on ALL THREE coins — BTC +$2.38/tr (CI [0.62,4.09]), ETH +$1.92
    ([0.53,3.33]), SOL +$2.16 ([1.03,3.25]). Used aliplayer BBO (slot-aligned, full pre-slot → valid +5s fire) +
    full 1s + resolutions_hf. Caveat: BBO top-of-book fill (no L25 walk), slightly optimistic. The §D-2 gate is
    CLEARED. Validation chain now: in-sample + DSR + live-shadow + disjoint-OOS all positive.
    **+ DOGE OOS-validated 2026-06-05** (after 1s backfill to Apr21): gated +$1.40/tr CI [0.19,2.61] on Apr6–21
    → validated universe now BTC/ETH/SOL/DOGE. BNB positive but thin/underpowered (n=22). Time-of-day 22–02
    boost is BTC/ETH/SOL-specific (didn't replicate on DOGE/BNB). XRP/HYPE still blocked on data.
  - 🔴 REMAINING GATE: only **≥200 LIVE forward fires + live-wallet CI** now stands before real (small) capital.
- **DISAGR-HAWKES SOL 5m DN** (`mp_skew<0 ∧ imb5_diff>0 ∧ hawkes_imb<−0.2`) — the only cross-feature survivor of
  production fills (+$3.70/tr, clean fill-selection). Spec'd as shadow sleeve
  (`TV_AGENT_SPEC_SHADOW_DISAGR_HAWKES_SOL5M_2026_06_03.md`). Unconfirmed forward.
- ✅✅ **TIME-OF-DAY scalp gate** (NEW 2026-06-05, `SLUG_SELECTION_RESULTS_2026_06_05.md`) — the most robust
  slug/timing selector found. Scalp edge ~2× in 22–02 UTC, dead at h12/17/18–21. **`exclude {12,17}` = 94%
  coverage, $/tr +2.95→+3.14, SAME total PnL, walk-forward stable (3/3 folds).** Triple-confirmed: our
  walk-forward + F2's behavior (F2 puts 32% of slugs in 22–02 vs 17% baseline, avoids 18–21 entirely) + lit.
  → deploy gated sleeves (exclude {12,17} or {2,12,16,17,18}) alongside ungated to measure live lift. F2's
  full slug-selector PARTIALLY CRACKED = substantially time-of-day (within-hour pick still needs CLOB WS tape).
  Dead this batch: liquidity-inversion (flat), cross-token price-sum (lookahead artifact; causally tight-books
  better = confirms spread filter), reversal-imbalance (null). Microstructure does NOT sharpen the scalp (=§D-1).
- ⭐ **ORACLE-DETERMINISM SETTLEMENT SELECTOR** (NEW 2026-06-05, best slug-selection lead) —
  `ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md` + `SLUG_SELECTION_RESEARCH_2026_06_05.md` (deep research, sonnet-patched).
  Chainlink decides the outcome 30–60s before settle (18% of slugs, 99.6% acc, settle-fidelity 1.0). Poly winner
  LAGS the oracle (+1.35%/share print EV, CI excludes 0), concentrated in CHEAP-but-decided slugs (winner<0.90–0.95
  while oracle says 99%). Unlike FLB it **survives fills directionally** (filled win 92–100% at vwap~0.85,
  +$1.8–4.2/tr) — first selector that doesn't flip negative on ask-walk. 🔴 GATE: thin asks → 3–12% fill, only
  9–42 fills/43d, best-powered CI includes 0 = UNDERPOWERED. NEXT: deploy shadow sleeve (T-60s, |dist|≥15bp ∧
  winner ask<0.95, $5, hold-to-settle) to accrue ≥100–200 forward fills + CI>0. Needs live `crypto_prices_chainlink` RTDS.
- ~~FAVORITE-LONGSHOT CONVERGENCE EDGE~~ (investigated 2026-06-04, **NOT deployable**) — `FAVORITE_LONGSHOT_2026_06_04.md`.
  Real & well-powered in trade-PRINT space (buy favorites p≥0.75 @ ttl 15–120s, hold: +0.5–1.0%/share, slug-block
  CI excludes 0, millions of trades) — BUT an **execution mirage**: L25 ask-walk revalidation (engine_v2
  LiveMimicConfig $25, 85ms, 0.07 fee) → every cell's slug-CI includes 0 (best +$0.098/tr, CI [−0.48,+0.63]).
  Cross-token spread was NOT the killer (tight near settlement, 0.015–0.06); ask-walk slippage (entry→0.92) +
  hold variance kills the thin edge. **print≠fill** (new rule, alongside WR≠edge). Closed.

### 🔴 DEAD / NOISE (do NOT re-try)
- **SOL exit-scalp** (2026-06-05, `SOL_SCALP_AND_MAKER_ENTRY_2026_06_05.md`) — edge mechanism present (7 gated
  fills +$6.5/tr CI>0) but **untradeable: 0.5% fill rate at $25** (SOL up/down books too thin/spready). BTC/ETH only.
- **Maker ENTRY for the scalp** (rebate + spread capture) — **adverse selection kills it**: resting bid fills on
  losers (won 0.36 / lost 0.55), misses the winners → gated +$1.52 taker becomes −$2.59 maker. Rebate (+$1.18/fill)
  real but dwarfed by selection. Scalp stays ALL-TAKER (maker exit also dead — caps runners). New rule: maker≠taker
  for momentum-capture edges.
- **Direction prediction at fire-time** — TA (AUC 0.51), microstructure (AUC 0.78 **but loses money**, priced-in),
  GPU LSTM on 8.8y (acc ≈0.50, all Sharpe ≤0), **Kronos** (real-poly OOS 52.9%, archived — generative≠classifier).
- **Kline-model → beat poly price** — 415 GPU architectures × 8.8y, **0/415 beat the poly price** (RV-gated −$0.2/tr).
  Poly up/down is efficiently priced vs any kline-trained model. `GPU_MODEL_SEARCH.md`, `KLINE_TO_POLY_2026_06_03.md`.
- **Scalp/slug SELECTION** — 387k-searched model selectors: **0/20 survive DSR at realistic variance** (the 6 that
  "pass" need a too-lenient top-tail variance). Multiple-testing noise.
- **Indicator strategies on underlying** — 4.8M combos (45-indicator zoo), 12 series: 29 "survivors" ≈ noise;
  only a weak **daily-trend MA cluster** (BTC/ETH/SOL 1d) is mildly interesting → *daily spot/perp, NOT poly*.
  `VBT_MEGA_SWEEP.md`. (Run the 1d cluster through DSR/PBO next session — if it survives it's a separate
  underlying strategy, not poly.)
- **Volatility/physics gates on the scalp** — asset-selection confound (dist_abs in $ just picks BTC); no real lift.
- **Hedge** (stop-loss salvage, buy-opposite) — always-sell at +45/60 dominates. `SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03.md`.

## C. ⭐ ml4t TOOLKIT — INSTALLED, VALIDATED, GO-FORWARD RIGOR LAYER
Installed editable on the main **Python 3.14** env (`external/ml4t-{engineer,diagnostic,models}`):
- **engineer** — 120 features (`compute_features(polars_df,[names])`, `FeatureCatalog().list()`); López de Prado
  labeling (`atr_triple_barrier_labels`, `meta_labels`, `apply_meta_model`, `calculate_sample_weights`,
  `sequential_bootstrap`); dollar/volume/imbalance bars; leakage-safe `MLDatasetBuilder`.
- **diagnostic** ⭐ — `deflated_sharpe_ratio` / `deflated_sharpe_ratio_from_statistics(observed_sharpe,n_samples,
  n_trials,variance_trials)`; PBO (`backtest_overfitting`); `rademacher_complexity`; CPCV (`CombinatorialCV` /
  `ValidatedCrossValidation`, purging in `core`). **This is how we judge everything now** (replaces hand-rolled
  permutation null / lockbox / Bonferroni).
  - ⚠️ DSR caveat: `effective_trials>1` needs `from_statistics` + a `variance_trials` estimate; results are
    SENSITIVE to it — always report a conservative (≥4×) sensitivity. The trustworthy read is the conservative column.
- **models** — forecasters / portfolio (AR1/EWMA/DeepPortfolio/CAE...). Not central yet.
- Optional, NOT installed: `ml4t/data` (we have canonical), `ml4t/backtest` (engine_v2 is our poly fill model;
  install only to backtest the underlying 1d-trend cluster). API map: `ML4T_READY_2026_06_04.md`.

## D. NEXT STEPS (priority order — start here next session)
1. ~~**CPCV + meta-label the EXIT-SCALP**~~ ✅ **DONE 2026-06-04 — NEGATIVE.** `META_LABEL_SCALP_CPCV_2026_06_04.md`
   + `autoresearch/meta_label_scalp_2026_06_04.py`. A meta-model on 61 causal features (logit + GBM) validated
   with purged `CombinatorialCV(8,2)`=28 paths **cannot beat a 1-feature `delta_bps` sort at any selectivity**
   (delta_top dominates meta at every k=60–300). PBO low, DSR passes — but that only re-confirms the *base* edge;
   the ML filter adds ≈$0. **Conclusion: `delta_bps` is the sufficient statistic — size the scalp by delta, NO
   model in the live path.** Same lesson as 387k selectors / 415 GPU nets: selection is efficient, edge=execution.
   (physics+path features excluded as leakage — path = literal exit prices.)
2. **Different-window OOS** — `strategy_lab/autoresearch/validate_oos.py` is ready. Needs the **6-month API** data
   for a window the search never saw (must include **L25 books + CLOB trades + klines**, not just klines). This is
   the only deflation-proof gate. (Operator getting the API.)
3. **Live shadow fires** — keep the 16 scalp sleeves + DISAGR-HAWKES accruing toward **≥200 forward fires + CI>0**.
   Per-day rates are slow for 15m/eth cells (vwap<0.55 rare live); btc_5m + d3/$5 are the workhorses
   (`SCALP_SLEEVE_AUDIT_2026_06_03.md`).
4. ~~**DSR/PBO the mega-sweep 1d-trend cluster**~~ ✅ **DONE 2026-06-04 — DEAD.** `DSR_PBO_1D_CLUSTER_2026_06_04.md`
   + `autoresearch/dsr_pbo_1d_cluster_2026_06_04.py`. Reconstructed all 75 survivor positions (OOS Sharpe
   matches JSON exactly). **0/25 survive DSR per asset** at n_trials≈400k; **PBO>0.5 on all three** (BTC 0.557,
   ETH 0.886, SOL 0.700 = overfit). Multiple-testing noise — NOT a standalone daily strategy, ml4t/backtest
   not warranted.
5. **TV-agent specs pending deploy** (written this session, hand to TV agent):
   **NEW 2026-06-05:** `TV_AGENT_SPEC_SCALP_TOD_GATE_2026_06_05.md` (time-of-day gated scalp sleeves —
   `g_hour_not_in`, exclude {12,17} TOD2 / {2,12,16,17,18} TOD5; compare vs existing `_v1` control) +
   `TV_AGENT_SPEC_SHADOW_ORACLE_SETTLE_2026_06_05.md` (oracle-determinism shadow sleeve — `g_oracle_decided`,
   T-60s, |dist|≥15bp ∧ winner ask<0.95, $5 hold-to-settle, BTC/ETH/SOL; needs live `crypto_prices_chainlink`
   + per-slug strike capture). Plus the prior:
   `TV_AGENT_SPEC_POLY_ENTRY_425_RETRY_2026_06_03.md` (recover dropped live fires from CLOB 425),
   `TV_AGENT_SPEC_SHADOW_DISAGR_HAWKES_SOL5M_2026_06_03.md`, scalp exit +60→+45, the shadow `entry_vwap` band
   (B3), Kalshi exit FOK→IOC (B4), disable bleeders (INV_NIGHT confirm).
6. The live↔paper engine parity finding: engines agree ~100% on signal; divergence is execution
   (live CLOB 425 rejects vs paper qty_compute_failed). `ENGINE_COMPARE_IRELAND_VS_VPS3_MOMO_F7_2026_06_03.md`.
7. ✅ **F2 OOS + cross-exchange basis hypothesis — DONE 2026-06-04, REJECTED.** `F2_BASIS_OOS_2026_06_04.md`.
   Ran the F2 trigger OOS on the new May30→Jun4 window (where canonical now has BOTH poly books/trades AND
   `cex_futures_ticker`): 4359 fires, broad-universe **−$0.18/tr (t=−6.19)** — trigger edgeless OOS (the 86%
   WR was in-sample slug survivorship). The §5 Phase-1 basis hypothesis is **rejected**: wider cross-exchange
   basis → strictly WORSE trades (dislocation is an *avoid* signal); best of 9 basis gates DSR prob 0.000.
   F2's slug-selector is NOT basis; remaining levers = CLOB WS event tape / mempool / wallet graph (not in
   canonical). To test whether F2 *literally* conditioned on basis would need a fresh Alchemy pull of the two
   wallets in the basis window — low priority since the trigger is edgeless OOS anyway.

## E. ENVIRONMENT & ASSETS (for a fresh session)
- **Python 3.14** main env has: numpy/pandas/pyarrow/sklearn/xgboost/lightgbm/**talib**/**duckdb**/**polars**/
  **numba**/**torch 2.11+cu126 (CUDA, RTX 3060 working)**/**vectorbt 0.28.5** + ml4t (editable). torch was
  reinstalled clean this session (the original was a corrupt partial cu126 install).
- **Data (kept):** `strategy_lab/autoresearch/_data/binance_vision/{BTC,ETH,SOL}USDT_{1m,5m,15m,1h,4h,1d}_full.parquet`
  = **8.8y spot** (BTC/ETH 2017-08→, SOL 2020-08→). `_data/binance_vision_deriv/` = **6y futures klines + funding +
  OI/LSR metrics** (W3 basis). Canonical refreshed to **Jun 4 21:42**.
- **Harness:** `strategy_lab/autoresearch/` — `fetch_binance_vision_history.py`, `consolidate_vision.py`,
  `build_indicator_panel.py`, `build_clob_flow.py`, `build_master_features.py`, `search_overnight.py`,
  `vbt_mega_sweep.py`, `gpu_model_search.py`, `gpu_kline_to_poly.py`, `gpu_lstm_klines.py`, `ml4t_dsr_judge.py`,
  `fitness.py`/`candidate.py`/`run.py` (autoresearch loop), `validate_oos.py`, `_data/master_features.parquet`,
  `_data/overnight/finalists.json`. CLOB trade tape (`trades_polymarket`, 42.8M rows) is mined into `clob_flow`.
- **Gotchas this session:** exit-code 127 from background python = spurious post-completion shell hiccup (job
  actually completed — check the output/report, don't assume failure). Binance Vision 2025 files mix ms/us
  `open_time` (normalize >1e14 → /1000). Mega-sweep must store positions int8 + bounded top-K (OOM otherwise).
  GPU search must batch tensors to VRAM (don't `.to(cuda)` the whole dataset). hnswlib/torch lack 3.14 wheels for
  some (used sklearn NN; torch cu126 works).

## F. KEY REPORTS (this session)
Verdict/handoff: `HANDOFF_2026_06_04_ML4T_DSR.md` (this) · `ML4T_DSR_JUDGE_2026_06_04.md` · `ML4T_READY_2026_06_04.md` ·
`OVERNIGHT_RESULTS_2026_06_04.md` · `HANDOFF_NIGHT_2026_06_03_GPU_SPRINT.md`.
Edge/validation: `SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03.md` · `EXIT_TIMING_MODEL_2026_06_03.md` ·
`SCALP_SLEEVE_AUDIT_2026_06_03.md` · `REVALIDATION_ENGINE_V2_2026_06_03.md` · `SESSION_FINDINGS_2026_06_03_ML_SCALP_PHYSICS.md`.
ML dead-ends (proof): `META_LABELER_V2_MICROSTRUCTURE_2026_06_03.md` · `GPU_LSTM_SUMMARY_2026_06_03.md` ·
`KLINE_TO_POLY_2026_06_03.md` · `GPU_MODEL_SEARCH.md` · `VBT_MEGA_SWEEP.md` · `AUTORESEARCH_SEARCH_RESULTS_2026_06_03.md` ·
`PHASE_PLAN_CLOB_SLUGSELECT_AUTORESEARCH_2026_06_03.md` · `ML_AGENTIC_PHASE_PLAN_2026_06_03.md`.
Live/engine: `ENGINE_COMPARE_IRELAND_VS_VPS3_MOMO_F7_2026_06_03.md` + the 6 TV_AGENT specs.

## G. PRIOR HANDOFF
`HANDOFF_2026_06_03_SCALP_DEPLOY.md` (the scalp deploy + fleet audit that started this session). Still valid for
the live-shadow context; this handoff supersedes for the ML/rigor direction.
