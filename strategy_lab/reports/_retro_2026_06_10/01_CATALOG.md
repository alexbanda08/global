# Strategy Research Corpus — Complete Catalog
**Generated:** 2026-06-10  
**Scope:** `strategy_lab/reports/` — 696 .md files, ~2.5 months of Polymarket/Kalshi crypto up-down 5m/15m research  
**Groups:** 26 (25 named research lines + 1 ops/misc bucket)

---

## 01. Session Handoffs (22 files)

**Files:** HANDOFF_2026_05_16_LIVE_MIMIC_GAPS.md, HANDOFF_2026_05_22_HOD_REFRESH_SLEEVE_FIXES.md, HANDOFF_2026_05_22_MOMO_F7_MARKOV.md, HANDOFF_2026_05_23_COMPLETE.md, HANDOFF_2026_05_26_COMPLETE.md, HANDOFF_2026_05_27.md, HANDOFF_2026_06_01.md, HANDOFF_2026_06_01_AUDIT_LAGTAKER_FORENSICS.md, HANDOFF_2026_06_03.md, HANDOFF_2026_06_03_SCALP_DEPLOY.md, HANDOFF_2026_06_04_ML4T_DSR.md, HANDOFF_2026_06_06_OOS_KALSHI_AUDIT.md, HANDOFF_HURST_HLCASCADE_FIX_2026_06_01.md, HANDOFF_LIVE_VS_SHADOW_2026_06_02.md, HANDOFF_NIGHT_2026_06_03_GPU_SPRINT.md, HANDOFF_PHYSICS_TICK_COLLECTOR_2026_06_01.md, HANDOFF_SLEEVE_btc_15m_ema50_ema800_off600_down_2026_05_27.md, HANDOFF_WALLET_DECODER_2026_05_16.md, SESSION_HANDOFF_2026_05_05.md, SESSION_HANDOFF_2026_05_06.md, SESSION_HANDOFF_2026_05_09_SLUG_WS_BREAKTHROUGH.md, SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md

**(a) What was tried:** Cross-session state transfer documents. Cover every major research milestone: ws_s convention breakthrough, momo F7+Markov deploy, live-mimic gap analysis, lagtaker forensics, scalp deploy, ML4T/DSR toolkit, OOS+Kalshi audit.  
**(b) Verdict:** Reference/ops — not edge research. Key milestone: HANDOFF_2026_06_03_SCALP_DEPLOY confirmed the only deployed live edge (exit-scalp). HANDOFF_2026_06_06 confirmed OOS pass + Kalshi arb lead.  
**(c) Key numbers:** See individual research groups.

---

## 02. V1–V5 Momo/Sniper Evolution (18 files)

**Files:** MOMO_V1V2_CANONICAL_2026_05_10.md, MOMO_V1_V2_F7_PROD_2026_05_20.md, POLYMARKET_V2_SIGNALS_FINDINGS.md, V1_V2_V3_FULL_RESULTS_2026_05_01.md, V3_1_PATCH_SPEC_2026_04_30.md, V3_2_DEPLOY_SPEC_2026_04_30.md, V3_BACKTEST_FINDINGS_2026_05_04.md, V3_BACKTEST_FINDINGS_FULL_2026_05_04.md, V3_BACKTEST_FULL_2026_05_04.md, V3_BACKTEST_VALIDATION_2026_05_04.md, V3_BTC_UNION_REALFILLS.md, V3_FINAL_PATCH_SPEC_PARALLEL.md, V3_LIVE_LAUNCH_SPEC_2026_04_30.md, V3_PATCH_OPTION_B_SPEC.md, V3_PRODUCTION_REPLAY.md, V3_SHADOW_VS_BACKTEST.md, V4_PLAN_AND_RESULTS_2026_04_30.md, V5_LATE_ENTRY_SPEC_2026_05_04.md

**(a) What was tried:** Iterative evolution of the directional momo strategy from V1 (simple 2m return) through V3 (lookahead-fixed, multi-horizon) and V4/V5 (late-entry sniper variants). BTC/ETH/SOL 5m+15m. Extensive backtest vs live shadow comparison at each step.  
**(b) Verdict:** Dead. V3 full 12.5d window: BTC 52.8% WR, −$0.20/53 trades (not significant, p=0.37). ETH 41.9% WR, −$8.52/31 trades. V4/V5 sniper late-entry also fails. Live shadow fleet 215 sleeves net −$25.4k. 50% WR = coin-flip.  
**(c) Key numbers:** BTC V3: WR 52.8%, −$0.20/tr, IC p=0.37. 215-sleeve fleet net −$25.4k, live WR ≈49.6%.

---

## 03. Momo Misc Research (39 files)

**Files:** MOMO_12CELLS_F7_2026_05_20.md, MOMO_3WAY_COMPARISON_2026_05_06.md, MOMO_5M_FIX_PLAN_2026_05_06.md, MOMO_5M_VS_15M_ANALYSIS_2026_05_06.md, MOMO_ANCHOR_DIAGNOSIS_2026_05_09.md, MOMO_BREAKTHROUGH_SLUG_WS_END_TIME_2026_05_09.md, MOMO_CHAINLINK_ONLY_2026_05_09.md, MOMO_COINBASE_ADDALPHA_2026_05_09.md, MOMO_COINBASE_LEAD_2026_05_09.md, MOMO_COINBASE_OVERLAY_2026_05_09.md, MOMO_EXIT_POLICY_EXPLORE_2026_05_09.md, MOMO_F7_PER_SLEEVE_TABLE_2026_05_20.md, MOMO_FEED_LAG_INVESTIGATION_2026_05_10.md, MOMO_FILTER_OVERLAY_2026_05_20.md, MOMO_FULL_BACKTEST_WS_2026_05_06.md, MOMO_FULL_UNIVERSE_2026_05_16.md, MOMO_FULL_UNIVERSE_VALIDATION_2026_05_09.md, MOMO_HEDGE_SELL_INVESTIGATION_2026_05_06.md, MOMO_HOLD_F7_BACKTEST_VS_LIVE_2026_06_08.md, MOMO_HOLD_PROD_VS_BACKTEST_2026_05_09.md, MOMO_LIVE_FILL_PLACEHOLDER_PROOF_2026_06_08.md, MOMO_LIVE_VS_BACKTEST_2026_05_08.md, MOMO_LIVE_VS_F7_2026_05_20.md, MOMO_PARTIAL_FILL_BACKTEST_2026_05_09.md, MOMO_PHASE3_4_ANCHOR_LOOKAHEAD_FIXED_2026_05_09.md, MOMO_POST_PATCH_VS_BACKTEST_2026_05_09.md, MOMO_REALFILL_VALIDATION_2026_05_06.md, MOMO_RERUN_ALL_POLICIES_2026_05_06.md, MOMO_RERUN_L25_HOLD_2026_05_06.md, MOMO_REST_LAG_VS_MICROSTRUCTURE.md, MOMO_SHADOW_MATCH_2026_05_06.md, MOMO_SHADOW_SLEEVES_TABLE_2026_05_11.md, MOMO_SHADOW_VS_BACKTEST_2026_05_06.md, MOMO_VARIANTS_28D_SUBSEC_2026_05_21.md, MOMO_VARIANTS_2ABC_2026_05_20.md, MOMO_VARIANTS_F7_MARKOV_STACK_2026_05_22.md, MOMO_VARIANTS_FRESH_F7_VERIFIED_2026_05_21.md, MOMO_VARIANTS_PROD_MATCHED_2026_05_21.md, MOMO_VARIANTS_SUBSEC_F7_WINDOW_2026_05_21.md

**(a) What was tried:** Foundational momo investigation: ws_s anchor discovery (major breakthrough), lookahead bug fix, Coinbase lead signal overlay, F7 RSI gate per sleeve, Markov filter variants (F7+Markov stack), partial fill backtest, REST lag vs microstructure, live vs shadow discrepancies, hold-to-resolution variants across all timeframes and assets.  
**(b) Verdict:** Dead for directional prediction. ws_s breakthrough (MOMO_BREAKTHROUGH_SLUG_WS_END_TIME) was critical: anchoring on slot_start inflates hit rate 25–40pp vs correct ws_s anchor. Post-fix WR ~50%. F7+Markov per-sleeve analysis: btc_15m_v1 +$2.83→+$5.44/tr with Markov (n=26) but low n.  
**(c) Key numbers:** ws_s lookahead fix drops WR 85%→50%. Best Markov-gated cell: btc_15m_v1 WR 61.5%, +$5.44/tr (n=26).

---

## 04. Cyclops Reverse-Engineering (7 files)

**Files:** CYCLOPS_ARCHITECTURE_DEEP_DIVE_2026_05_16.md, CYCLOPS_CLONE_SPEC_2026_05_16.md, CYCLOPS_COMPARISON_AND_V4_PLAN_2026_04_30.md, CYCLOPS_SIGNALS_DECODE_2026_05_29.md, CYCLOPS_UPDATE_COMPARISON_2026_05_07.md, CYCLOPS_WALLET_GRAPH_2026_06_08.md, CYCLOPS_WALLET_HUNT_2026_06_01.md

**(a) What was tried:** Reverse-engineered the Cyclops wallet (~external profitable algo on Polymarket BTC 5m). Built a clone package (`strategy_lab/cyclops/`) with 3 independent axes (trend/levels/momentum), conflict filter, time-of-day guard, blowoff guard, confidence-scaled sizing, L25 book walk.  
**(b) Verdict:** Deployed at paper level. Validated G1+G3+G4 gates at $1 stake: 21d, n=36, WR 80.6%, +$0.244/trade, p=0.002, G4 lower CI +$0.022 excl 0. BTC 5m only — does NOT generalize to ETH/SOL or 15m.  
**(c) Key numbers:** WR 80.6%, +$0.244/tr, n=36, p=0.002. BTC 5m only.

---

## 05. Silver / Confluence Multi-Layer Strategy (7 files)

**Files:** CONFLUENCE_BUILD_PLAN_2026_05_07.md, CONFLUENCE_GRAND_BACKTEST_2026_05_07.md, CONFLUENCE_VERDICT_2026_05_07.md, SILVER_EXIT_POLICY_BACKTEST_2026_05_07.md, SILVER_OVERVIEW_2026_05_07.md, SILVER_VALIDATION_2026_05_07.md, SILVER_VALIDATION_FINAL_2026_05_07.md

**(a) What was tried:** Multi-layer confluence combining structure (trend), flow, and trigger signals. Backtested across 1605 fired momo trades BTC/ETH/SOL. Three alpha vectors discovered: (A) SOL FLOW-veto, (B) SOL+ETH SILVER sleeve (structure+flow no trigger), (C) anti-confluence baseline.  
**(b) Verdict:** Inconclusive — sample too small. Vector B (SOL+ETH SILVER): 29 trades, 96.6% WR, +$3.36 mean. Vector A shows SOL veto can cut losses. Need ≥80 trades for ship. Never progressed to deploy.  
**(c) Key numbers:** Vector B: n=29, WR 96.6%, +$3.36/tr (insufficient n). Vector A SOL-flow-veto promising but thin.

---

## 06. Mint-and-Sell / Maker-Side (11 files)

**Files:** MAKER_BOTH_SIDES_BACKTEST.md, MINT_AND_SELL_CVD_TIMING_2026_05_23.md, MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md, MINT_AND_SELL_LIVE_SPEC_2026_05_16.md, MINT_AND_SELL_PARTIAL_FILL_POLICY_2026_05_16.md, MINT_AND_SELL_REPLICATION_2026_05_16.md, MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md, MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md, MINT_AND_SELL_V3_SIMULATION_2026_05_23.md, MINT_AND_SELL_V3_TEST_DEPLOY_SPEC_2026_05_18.md, POLYMARKET_MAKER_ENTRY.md

**(a) What was tried:** Decoded the most profitable external wallets ($254k+/day) as mint-and-sell makers. Replicated at $2.5 notional with corrected fee model (rebate-as-income). Per-fire stats negative; slug-level BOTH_SIDES_PARTIALS regime flips positive. Maker entry CLOB (resting bid) also tested.  
**(b) Verdict:** Dead in practice. Maker entry: adverse selection confirmed — fill WR 0.36 won vs 0.55 lost; rebate < selection loss. Mint-and-sell per-fire: −$0.06 to −$0.15/op (−$25k/day extrapolated). Slug aggregation shows +$0.04–0.41/slug only in BOTH_SIDES_PARTIALS regime which requires infra we cannot replicate. POLYMARKET_MAKER_ENTRY confirmed dead via EDGE_GAP_ANALYSIS.  
**(c) Key numbers:** Per-fire hold: −$0.06 to −$0.15. Maker fill adverse selection: won-fill WR 36% vs lost-fill WR 55%. Best wallet: 0xb27bc932 +$918k/3.6d = +$254k/day (unreplicable).

---

## 07. Maker-Arb (10 files)

**Files:** MAKER_ARB_BACKFILL_REAL_PNL_2026_05_29.md, MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md, MAKER_ARB_CONTEXT_HANDOFF_2026_05_28.md, MAKER_ARB_CONTEXT_HANDOFF_2026_05_29.md, MAKER_ARB_DEPLOY_DECISIONS_2026_05_27.md, MAKER_ARB_DEPLOY_REPORT_2026_05_21.md, MAKER_ARB_POSITIONED_PLAN_2026_05_29.md, MAKER_EXIT_SIM_2026_06_06.md, MAKER_QUEUE_LATENCY_PROBE_2026_05_29.md, MAKER_VS_TAKER_GATED_SLEEVES_2026_05_22.md

**(a) What was tried:** Built and deployed maker-arb sleeves (acc_h_v2, mas, acc_pc_v2, acc_m_v2) placing limit bids on both sides. Reported +$4.44/slug for btc_15m until canonical refresh. Maker queue latency probed. Maker-exit-with-taker-fallback simulated (Jun 6).  
**(b) Verdict:** KILLED. Survivorship bias exposed: right-censored residual slugs (directional losers never get REDEEM) → uncensored truth is −$0.41 to −$3.63/slug across all cells, all net-negative. DO NOT DEPLOY. Maker exit (+$0.42/tr SIG on optimistic fill model) remains an OPEN partial edge (queue-aware OOS needed).  
**(c) Key numbers:** acc_h_v2 btc_15m: reported +$4.44/slug → corrected **−$0.41/slug** (CI [−2.58,+1.77]). acc_m_v2 btc_5m: **−$1.60/slug** (CI [−2.63,−0.57] SIG). Fleet all negative.

---

## 08. Wallet Decode / F2 / F7 (51 files)

**Files:** CANCEL_RULES_DECODED_2026_05_18.md, DECODE_0x0079c319_2026_05_28.md, DECODE_0x07480f20_2026_05_28.md, DECODE_0x0de4458d_2026_05_28.md, DECODE_0x10188828_2026_05_28.md, DECODE_0x927f7694_2026_05_28.md, DECODE_0x9f5ffe76_2026_05_28.md, DECODE_0xc547326c_2026_05_28.md, DECODE_0xe3867b68_2026_05_28.md, DECODE_1day_wallets_2026_05_28.md, DECODE_251c_c387_btc5m_2026_05_29.md, DECODE_3c58_d9dea_twins_2026_05_29.md, DECODE_5e2b_fcdc_multicell_2026_05_29.md, DECODE_SYNTHESIS_2026_05_28.md, DECODE_bigbtc5m_2026_05_29.md, DECODE_cheap_contrarian_class_2026_05_28.md, DECODE_highfreq_makers_2026_05_29.md, DECODE_multicell_trio_2026_05_29.md, EEBDE7A0_TAKER_TRIGGER_DECODED_2026_05_18.md, EEBDE7A0_TAKER_TRIGGER_V2_2026_05_18.md, EEBDE7A0_TAKER_TRIGGER_V3_2026_05_18.md, F2_BASIS_OOS_2026_06_04.md, F2_DATA_INVENTORY_GAP_2026_05_29.md, F2_FINAL_VERDICT_2026_05_18.md, F2_REPLICATION_VERDICT_2026_05_17.md, F2_TRIGGER_DECODE_2026_05_17.md, F7_AND_RESIDUAL_FIX_VERIFICATION_2026_05_21.md, F7_LOOKAHEAD_BUG_AND_CORRECTED_2026_05_20.md, F7_V2_REGRESSION_DIAGNOSTIC_2026_05_21.md, WALLET_331BF91C_WEATHER_2026_06_03.md, WALLET_6011655C_HIGHTEMPTATION_2026_06_03.md, WALLET_B27_DECODE_2026_05_20.md, WALLET_CATALOG_2026_05_17.md, WALLET_DATA_FETCH_2026_05_18.md, WALLET_DECODER_DEBUG_2026_05_16.md, WALLET_DECODER_FIX_SPEC_2026_05_21.md, WALLET_DECODER_PIPELINE_2026_05_16.md, WALLET_DECODE_0xd44e2993_2026_05_18.md, WALLET_DECODE_5WALLETS_2026_05_29.md, WALLET_EE65685D_NEARCERT_SCALPER_2026_06_03.md, WALLET_FIND_F69AF0B9_2026_06_03.md, WALLET_HUNT_CHAIN_BACKFILL_2026_05_16.md, WALLET_HUNT_MULTIWALLET_2026_05_16.md, WALLET_HUNT_SYNTHESIS_2026_05_29.md, WALLET_HUNT_eebde7a0_2026_05_16.md, WALLET_PNL_BREAKTHROUGH_2026_05_16.md, WALLET_REGISTRY_2026_05_28.md, WALLET_STRATEGIES_CHAIN_2026_05_16.md, WALLET_STRATEGIES_DECODED_2026_05_17.md, WALLET_STRATEGIES_FINAL_2026_05_16.md, WALLET_TX_TAXONOMY_2026_05_18.md

**(a) What was tried:** Full Alchemy chain-history decoder for 9+ Polymarket wallets. Decoded F2 (0xa0a50783, $5.9k/day directional), F7 RSI filter extraction (94.67% production match), decoded 8 high-WR directional wallets in parallel. EEBDE7A0 taker trigger decoded. Synthesis: root edge is oracle-lag (Family A: EMA/ret momentum; Family B: cl_basis divergence).  
**(b) Verdict:** Insights extracted but NOT directly deployable. F2: edge is slug selection (not trigger) — FADE-flow on broad universe loses −$14k; on F2's own 102 slugs +$2,853. F7: RSI anchor confirmed at ws_s (94.67% match). Wallet 0xe3867b68: 85% WR n=141, HIGH deploy potential. 0x0079c319: 90% WR n=393. Poison-pill tail identified: entry_px<0.50 → contrarian (WR 28–35%), must gate out.  
**(c) Key numbers:** F2 on own slugs: WR 46%, +$2,853 (slug-selection alpha). 0xe3867b68: 85% WR (n=141). 0x0079c319: 90% WR (n=393, entry_px∈[0.6,0.92]).

---

## 09. Lag-Taker / LAGV2 (6 files)

**Files:** LAGV2_ROOTCAUSE_ALWAYS_UP_2026_06_01.md, LAG_TAKER_EDGE_RESEARCH_2026_05_29.md, LAG_TAKER_FINAL_CONFIG_2026_05_29.md, LAG_TAKER_GATES_2026_05_29.md, LAG_TAKER_OOS_REVAL_2026_06_01.md, LAG_TAKER_STOPLOSS_SIZING_2026_05_29.md

**(a) What was tried:** Buy-Wait-Hedge "lock-the-lag" concept: buy Binance-leading side, wait for repricing, hedge with opposite leg. Distilled to directional lag-taker (hold-to-resolution). Dose-response vs delta_bps. LAGV2 bug fixed (always-UP). OOS re-validation Jun 1.  
**(b) Verdict:** Leg-2 LOCK/HEDGE dead (UP/DOWN asks anti-correlated −0.90, sum pinned ~1.01-1.02, lockable fraction zero). Directional lag-taker (Leg-1): REAL edge at δ≥3–5bps, hold-to-resolution, WR 63–69%. But OOS Jun 1 re-validation: +$0.36/tr t=0.41 (not significant at deployment threshold). Edge absorbed into exit-scalp.  
**(c) Key numbers:** Lag taker: WR 63.3% at δ≥3, +$2.39/tr (training). OOS Jun 1: +$0.36/tr t=0.41. δ≥12 reverses to −$4.17/tr (priced-in). LAGV2 always-UP bug fixed (was 100% UP → 50/50 live after fix).

---

## 10. Exit-Scalp Research (10 files)

**Files:** SCALP_DYNAMIC_EXIT_2026_06_04.md, SCALP_EXIT_CONFIG_BY_TF_2026_06_06.md, SCALP_FROM_SHADOW_SLEEVES_2026_06_09.md, SCALP_FWD_FIRES_STATUS_2026_06_08.md, SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03.md, SCALP_LIVE_AUDIT_2026_06_06.md, SCALP_NEW_EDGE_HUNT_2026_06_09.md, SCALP_OOS_PASS_2026_06_05.md, SCALP_SLEEVE_AUDIT_2026_06_03.md, SCALP_VALIDATION_2026_06_02.md

**(a) What was tried:** The core deployed edge: buy lag-taker token cheap (entry_vwap<0.55, δ≥3bps), exit on book at +60s instead of holding to resolution. Validated gated cell, walk-forward, direction permutation. Dynamic exit timing sweep (+45/+60/+90). New-edge hunt (mid-window, FVG, cross-asset, regime, trailing). Config by TF (15m maker@0.60). STOP@(fill−0.10) validation. OOS on disjoint Mar30–Apr21 window. New coins DOGE/BNB.  
**(b) Verdict:** DEPLOYED. The ONLY confirmed edge. OOS pass: BTC +$2.38/tr CI[+0.62,+4.09], ETH +$1.92 CI[+0.53,+3.33], SOL +$2.16 CI[+1.03,+3.25], DOGE +$1.40 CI[+0.19,+2.61]. Stop@(fill−0.10): +0.88/tr SIG, confirmed 3×. New-edge hunt (7 trials, Jun 9): ALL DEAD. Mid-window/FVG/cross-asset/regime all flat or anti-signal.  
**(c) Key numbers:** Walk-forward gated: +$2.98/tr t=6.33. OOS (5 coins): +$1.40–$2.38/tr CI>0. Stop edge: +0.88/tr SIG. Time-of-day 22–02 boost: +$4.68/tr (2.2× base, OOS confirmed).

---

## 11. ML / Autoresearch (22 files)

**Files:** AUTORESEARCH_SEARCH_RESULTS_2026_06_03.md, AUTORESEARCH_W1_FINDINGS_2026_06_03.md, DSR_PBO_1D_CLUSTER_2026_06_04.md, GPU_LSTM_BTCUSDT_15m.md, GPU_LSTM_BTCUSDT_1h.md, GPU_LSTM_BTCUSDT_4h.md, GPU_LSTM_BTC_1h_smoke.md, GPU_LSTM_ETHUSDT_15m.md, GPU_LSTM_ETHUSDT_1h.md, GPU_LSTM_ETHUSDT_4h.md, GPU_LSTM_SOLUSDT_15m.md, GPU_LSTM_SOLUSDT_1h.md, GPU_LSTM_SOLUSDT_4h.md, GPU_LSTM_SUMMARY_2026_06_03.md, GPU_MODEL_SEARCH.md, META_CLASSIFIER_FULL_REPORT.md, META_CLASSIFIER_NO_KRONOS.md, META_CLASSIFIER_V1.md, META_LABELER_V1_2026_06_03.md, META_LABELER_V2_MICROSTRUCTURE_2026_06_03.md, META_LABEL_SCALP_CPCV_2026_06_04.md, ML_AGENTIC_PHASE_PLAN_2026_06_03.md

**(a) What was tried:** Full ML toolkit: GPU LSTM (9 series, 8.8y BTC/ETH/SOL, 415 architectures × 3 TF), 4.8M indicator VBT combo sweep → DSR/PBO on 1d-trend MA cluster, CPCV + meta-label on exit-scalp (61 causal features, purged CV), Kronos external model (52.9% acc archived), meta-classifiers V1/V2 with microstructure features, ML agentic phase plan.  
**(b) Verdict:** ALL DEAD for direction prediction. GPU LSTM: acc 0.489–0.519 = coin-flip on every series/TF, Sharpe ≤ 0 held-out. DSR/PBO 4.8M sweep: 0/25 survivors per asset pass deflated Sharpe, PBO >0.5. Meta-label CPCV: cannot beat single-feature delta_bps sort. ML confirms: selection is efficient, only edge is execution.  
**(c) Key numbers:** GPU LSTM: 0/415 beat Poly price. DSR 4.8M sweep: 0/25 survive. Meta-label CPCV: ML adds ≈ $0 vs delta_bps sort. Kronos OOS 52.9% (near chance).

---

## 12. Sleeve Fleet Ops / TV Agent (102 files)

**Files (sample):** ALL_SHADOW_SLEEVES_TABLE_2026_05_11.md, DEPLOY_PORTFOLIO_BY_MARKET_2026_06_01.md, DEPLOY_SLEEVES_28D_FINAL_2026_05_22.md, MASTER_FINDINGS_TABLE_2026_05_30.md, MASTER_FINDINGS_TABLE_2026_06_02.md, MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.md, SHADOW_11_SLEEVES_BACKTEST_2026_05_22.md, SHADOW_11_SLEEVES_V2_2026_05_22.md, SHADOW_ANALYSIS_2026_05_04.md, SHADOW_AUDIT_2026_05_21.md, SHADOW_BLEEDERS_7D_2026_06_08.md, SHADOW_DEPLOY_SPEC_2026_05_27.md, SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md, SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE_2026_05_27.md, SHADOW_PNL_REAUDIT_RUNBOOK_2026_05_21.md, SHADOW_SLEEVE_AUDIT_2026_06_01.md, SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md, SLEEVE_BT_VS_LIVE_AUDIT_2026_06_08.md, SLEEVE_DEBUG_LIVE_VS_SHADOW_2026_06_01.md, SLEEVE_DEBUG_ROOTCAUSE_2026_06_01.md, SLEEVE_HUNT_15M_2026_05_26.md, SLEEVE_HUNT_15M_V2_2026_05_26.md, SLEEVE_INVENTORY_VPS3_2026_05_31.md, SLEEVE_LIVE_VS_SHADOW_CORRECTED_2026_06_01.md, SLEEVE_OPTIMIZATION_2026_05_30.md, SLEEVE_STOP_FORENSICS_2026_06_01.md, TV_AGENT_AUDIT_ASOF_LOOKAHEAD.md, TV_AGENT_BUG_AUDIT_PROMPT.md, TV_AGENT_CHANGES_2026_05_19.md, TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md, TV_AGENT_F7_RSI_FILTER_SPEC.md, TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC.md, TV_AGENT_FIX_DASHBOARD_CUMULATIVE_PNL_SPEC.md, TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md, TV_AGENT_FIX_SHADOW_AUDIT_2026_06_01.md, TV_AGENT_FIX_SILENT_MOMO_V2_5M_HOLD_2026_06_02.md, TV_AGENT_FIX_SILENT_SLEEVES_2026_06_01.md, TV_AGENT_FIX_SPEC_2026_05_21.md, TV_AGENT_FIX_SPEC_OVERLAY_POST_FIRE_HOOK_2026_05_27.md, TV_AGENT_FIX_SPEC_PHASE36_BUGS_2026_05_26.md, TV_AGENT_HANDOFF_2026_05_18.md, TV_AGENT_IMPLEMENTATION_DELTAS_2026_05_19.md, TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md, TV_AGENT_KALSHI_409_LIVE_NOT_FIRING_2026_06_02.md, TV_AGENT_LIVE_TRANSITION_SPEC.md, TV_AGENT_MAKER_BUG_FIX_GUIDE.md, TV_AGENT_MOMO_SLEEVES_IMPLEMENTATION.md, TV_AGENT_MOMO_V2_SLEEVES_IMPLEMENTATION.md, TV_AGENT_MOMO_V3_PARTIAL_SLEEVES_IMPLEMENTATION.md, TV_AGENT_PAT_ACCM_IMPLEMENTATION_SPEC.md, TV_AGENT_PHASE34_FIXES_2026_05_22.md, TV_AGENT_RESIDUAL_MARK_FIX_SPEC.md, TV_AGENT_RESTART_SPEC_1USD_2026_06_02.md, TV_AGENT_SPEC_POLY_FAST_TAKER_2026_05_29.md, TV_AGENT_SPEC_POLY_FAST_TAKER_V2_2026_05_29.md, TV_AGENT_SPEC_SCALP_ALLCOINS_2026_06_05.md, TV_AGENT_SPEC_SCALP_DELTA3_VARIANT_2026_06_02.md, TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md, TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02.md, TV_AGENT_SPEC_SCALP_MAKER_EXIT_2026_06_06.md, TV_AGENT_SPEC_SCALP_ORACLE_LAG_IRELAND_1S_STORE_2026_06_08.md, TV_AGENT_SPEC_SCALP_TOD_GATE_2026_06_05.md, TV_AGENT_SPEC_SHADOW_DISAGR_HAWKES_SOL5M_2026_06_03.md, TV_AGENT_SPEC_SHADOW_ORACLE_SETTLE_2026_06_05.md, TV_AGENT_SPEC_SLEEVE_DEBUG_FIX_2026_06_01.md, TV_AGENT_SPEC_V10_SLEEVES_2026_05_31.md, TV_AGENT_SPEC_V2_BUGS_AND_MARKOV_DEPLOY_2026_05_21.md, TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md, TV_AGENT_V3_FAMILY_REVERIFICATION_2026_05_16.md, TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md, TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23.md, TV_AGENT_WALLET_DECODER_SPEC.md

**(a) What was tried:** Full fleet operations: 215-sleeve shadow fleet deployment and ongoing audit (VPS3 + Ireland), bleeder identification, TV-agent bug specs and implementation deltas, Kalshi 409/FOK-IOC fix, scalp exit shadow spec + all-coins spec, LAGV2 always-UP fix, convergence-cancel spec, dashboard cumulative PnL fix, silent-sleeve forensics, sleeve parity corrections. Largest group by count.  
**(b) Verdict:** Ops/deployed. Fleet audit: 215 sleeves, net −$25.4k; 4 EDGE (t≥2), 13 promising, 25 bleeders killed. Scalp sleeves deployed (16 shadow): btc_5m_d3 +$4.49/tr live (VPS3_SLEEVE_VERIFICATION_2026_06_05). Edge sleeves: btc_15m ema50/ema800_off600_down WR 84.3%/+$1.33/tr (n=108).  
**(c) Key numbers:** Fleet: 215 sleeves, net −$25.4k. Bleeders: volume_INV_NIGHT ×6 net −$10k. EDGE sleeves: btc_15m_ema50_ema800_off600_down 84.3% WR +$1.33/tr. Scalp shadow: btc_5m_d3 +$4.49/tr live.

---

## 13. Hedge / Exit Policy Research (7 files)

**Files:** EXIT_POLICY_COMPARISON.md, EXIT_POLICY_MULTI_ASSET.md, EXIT_POLICY_RESEARCH_2026_05_27.md, EXIT_POLICY_TIER1.md, HEDGE_EXIT_RESEARCH_SYNTHESIS_2026_05_30.md, RESEARCH_STOPLOSS_EXITS_2026_05_30.md, STOPLOSS_BACKTEST.md

**(a) What was tried:** Comprehensive exit/hedge research: fixed SL/TP, trailing stops, HEDGE_LATE (sell bid < 0.6×entry in final 30s), oracle-confirmed reversal cut, cross-market delta hedge (perp), Kaminski-Lo stop theory, Kelly sizing. Bootstrap + walk-forward on real fires.  
**(b) Verdict:** Most exits dead. ONE robust hedge: HEDGE_LATE on marginal/breakeven sleeves (not winners, not structural losers). Example: btc_5m_parent15m_notrang +$5→+$44 (~8×) with HEDGE_LATE CI-lo +$0.13. Fixed TP/SL/trailing all lose EV. Kelly: 4× = ruin guarantee; ½-Kelly captures 75% growth at half DD.  
**(c) Key numbers:** HEDGE_LATE lift: ~8× on marginal sleeves. Fixed stops/TP/trailing: all EV-negative on fixed-expiry binary. Scalp STOP@(fill−0.10) confirmed +0.88/tr SIG separately.

---

## 14. Indicator Sweeps (19 files)

**Files:** ANCHORED_VWAP_FADE_5M_2026_05_23.md, BSM_FAIRVALUE_2026_05_31.md, EMA50_800_5M_VARIANTS_2026_05_31.md, EMA_BTC15M_DEPLOYABILITY_2026_06_01.md, EMA_DOWN_DEEPDIVE_2026_06_01.md, MA_RIBBON_OVERLAY_2026_05_23.md, MA_RIBBON_STRATEGY_5M_2026_05_23.md, SLOW_STOCH_OVERLAY_2026_05_23.md, SPIKE_ENTRY_5M_2026_05_23.md, TA_INDICATORS_MEGA_RUN_2026_05_23.md, VBT_MEGA_SWEEP.md, VBT_SWEEP_BTC_1h_smoke.md, VWAP_CONTINUATION_15M_2026_05_23.md, VWAP_CONTINUATION_5M_2026_05_23.md, VWAP_CONT_V2_GATED_2026_05_23.md, VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md, VWAP_SLOT_ANCHORED_5M_2026_05_23.md, VWAP_SLOT_V2_GATED_2026_05_23.md, Z_CONTRA_5M_2026_05_23.md

**(a) What was tried:** Full TA indicator sweep across BTC/ETH/SOL 5m+15m: VWAP continuation/slot-anchored, Z-contra, MA ribbon, slow stochastic, EMA50/800 crossovers, BSM fair value deviation, spike entry, anchored VWAP fade, VBT mega sweep (4.8M combinations). EMA50/800 extended to BTC 15m and deployability check.  
**(b) Verdict:** Mostly dead. EMA50/800 btc_15m down: PARTIAL — WR 84.3% live shadow (btc_15m_ema50_ema800_off600_down), confirmed deployable (see Group 12). BSM fair-value: partial signal but no standalone edge. VBT mega sweep: 0/25 survive DSR. Most TA indicators: no edge after 0.07 fee.  
**(c) Key numbers:** VBT 4.8M combos: 0/25 survive DSR/PBO. EMA50/800 btc_15m: 84.3% WR, +$1.33/tr, n=108 (deployed). BSM deviation: weak signal only.

---

## 15. Microstructure / HF Signals (13 files)

**Files:** AVELL_HAYASHI_2026_05_26.md, CROSS_FEATURE_RULES_2026_05_26.md, DEEP_STACKING_2026_05_26.md, DRZ_BACKTEST_2026_05_26.md, LEE_MYKLAND_2026_05_26.md, MICROPRICE_2026_05_26.md, MICROSTRUCTURE_2026_05_26.md, MLOFI_2026_05_26.md, SMS_BACKTEST_2026_05_26.md, THRESHOLD_SWEEPS_2026_05_26.md, VOL_HURST_2026_05_26.md, VPIN_HAWKES_2026_05_26.md, WEIGHTED_VOTING_2026_05_26.md

**(a) What was tried:** Full L25 microstructure signal sweep (all 2026-05-26 coordinated batch): VPIN + Hawkes intensity, Vol regime + Hurst exponent, Microprice deviation, MLOFI (multi-level OFI), DRZ (Depth-Return-Z), SMS (signed market spread), Avellaneda-Hayashi IV, Lee-Mykland trade classification, deep stacking ensemble, weighted voting, threshold sweeps, cross-feature interaction rules. 240k fires, ~40 features per fire.  
**(b) Verdict:** Dead for direction prediction. No standalone microstructure rule finds edge beyond priced-in at 0.07 fee. VPIN: toxic regime (z>2) only 0.7% BTC, 10.8% ETH bars — too rare. Vol/Hurst: no WR lift by regime. Microstructure confirms execution edge only (SOL has worst books: 2.8s stale, 8× thinner depth).  
**(c) Key numbers:** 240,882 fires analyzed. 0 standalone microstructure rules pass fee hurdle. SOL up_book_dt_us median 2.8s vs BTC 0.9s.

---

## 16. Arb / Kalshi / Cross-Timeframe (8 files)

**Files:** ARB_RESEARCH_LATENCY_HFT_2026_05_29.md, ARB_RESEARCH_MARKET_MAKING_2026_05_29.md, ARB_RESEARCH_PREDICTION_MARKET_2026_05_29.md, ARB_RESEARCH_STATARB_POSITIONED_2026_05_29.md, ARB_RESEARCH_SYNTHESIS_2026_05_29.md, CROSS_TIMEFRAME_ARB_2026_06_05.md, KALSHI_EARLY_LIQ_PROBE.md (in directional/), S4_KALSHI_VS_POLY_BACKTEST_2026_06_03.md, S4_REAUDIT_FINDINGS_2026_06_03.md

**(a) What was tried:** Literature sweep of 54 prediction-market/MM/statarb/HFT strategies. Cross-timeframe relative-value (5m vs 15m Poly, shared settle time). Poly×Kalshi deep-dip arb (set-cost<0.95/0.90). S4 pre-window 15m sleeve also tested on Kalshi variant. Oracle-lag directional ranked #1 across all domains.  
**(b) Verdict:** Oracle-lag is confirmed best. Cross-timeframe arb: DEAD — 15m token adjusts immediately to mid-window Binance price (fully efficient). Poly×Kalshi deep-dip: PARTIAL OPEN — set-cost<0.95 → +2.7¢/set CI[+1.1,+4.2]; <0.90 → +6.6¢/set; 96% settlement agreement. GATED on Kalshi ask-DEPTH unverified. Most classical arb strategies: dead at our infra (sub-ms race, no co-lo, no short).  
**(c) Key numbers:** Poly×Kalshi: +2.7¢/set (cost<0.95), +6.6¢/set (cost<0.90). Cross-TF arb: dead (15m token adjusts within seconds). S4 Kalshi variant proxy: 294 fires, 8.2% gate-pass rate.

---

## 17. Regime / Markov (4 files)

**Files:** MARKOV_FILTER_OVERLAY_2026_05_21.md, MARKOV_VS_F7_PER_SLEEVE_2026_05_21.md, REGIME_CONDITIONAL_2026_05_26.md, REGIME_CONDITIONAL_GATES_2026_05_26.md

**(a) What was tried:** Markov HMM regime filter (vol-adaptive w20 1m and 5m variants) overlaid on momo sleeves. Per-sleeve comparison vs F7 RSI gate. Regime-conditional gate sweeps.  
**(b) Verdict:** Inconclusive at scale. Per-sleeve Markov lifts some cells: btc_15m_v1 +$2.83→+$5.44/tr (w20_1m_voladaptive, n=26), btc_15m_v2 from −$0.35→+$3.83/tr (notF7+Markov, n=32). But no universal winner and n is always small. Regime gates for scalp tested in SCALP_NEW_EDGE_HUNT: dead (fails coin-split OOS).  
**(c) Key numbers:** btc_15m_v1 Markov lift: +$2.61/tr (n=26). btc_15m_v2: −$0.35→+$3.83/tr (n=32). Scalp regime gates: dead OOS.

---

## 18. Data Infrastructure (8 files)

**Files:** DATA_ASK_NEWCOIN_SCALP_OOS_2026_06_05.md, DATA_FIDELITY_VS_VPS3_2026_05_19.md, DATA_FIX_SPEC_RESOLUTIONS_HF_TIMING_2026_06_05.md, DATA_INVENTORY_2026_05_06.md, DATA_INVENTORY_2026_05_15.md, DATA_INVENTORY_2026_05_16.md, DATA_WINDOW_AUDIT_2026_05_26.md, NEW_DATA_INVENTORY_2026_06_05.md

**(a) What was tried:** Data inventory snapshots at key milestones, VPS3 fidelity checks, HF resolution timing fix spec, new-coin data request for OOS scalp (DOGE/BNB 1s backfill), canonical window audit.  
**(b) Verdict:** Ops/reference. Critical findings: HF aliplayer dataset frozen at Apr 21 2026 (not auto-updating as claimed). DOGE/BNB 1s backfill extended to Apr 21 enabled new-coin OOS. Canonical single-source invariant maintained.  
**(c) Key numbers:** See CLAUDE.md for full dataset stats.

---

## 19. Backtest Fidelity / Engine Audits (33 files)

**Files:** BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md, BACKTEST_PRODUCTION_FAITHFUL_2026_05_04.md, BACKTEST_REPLAY_BTC_2026_05_29.md, BACKTEST_REPLAY_ETH_2026_05_29.md, BACKTEST_REPLAY_SOL_2026_05_29.md, BACKTEST_SIGNAL_SOURCE_COMPARISON_2026_05_04.md, BACKTEST_VS_LIVE_MOMO_2026_05_29.md, BACKTEST_VS_SHADOW_AUDIT_2026_05_04.md, BACKTEST_VS_SHADOW_GAP_2026_05_20.md, CLEAN_BACKTEST_PHASE_B_FINAL_2026_05_21.md, CLEAN_BACKTEST_V2_BUG_CONFIRMED_2026_05_21.md, ENGINE_AUDIT_B_DIRECTIONAL_2026_05_29.md, ENGINE_AUDIT_C_MAKER_2026_05_29.md, ENGINE_AUDIT_D_VALIDATORS_2026_05_29.md, ENGINE_COMPARE_IRELAND_VS_VPS3_MOMO_F7_2026_06_03.md, ENGINE_CORRECTNESS_AUDIT_2026_05_28.md, FIDELITY_AUDIT_MOMO_SHADOW_2026_05_29.md, FIDELITY_AUDIT_V5_V9_2026_05_29.md, FIDELITY_AUDIT_V6_V7_2026_05_29.md, FIDELITY_AUDIT_V8_H_2026_05_29.md, FIDELITY_AUDIT_VL_2026_05_29.md, FIDELITY_LIVE_A1_sniperv5_framework_2026_06_01.md, FIDELITY_LIVE_A2_sniperv5_sleeves_2026_06_01.md, FIDELITY_LIVE_AUDIT_MASTER_2026_06_01.md, FIDELITY_LIVE_B_momo_f7_2026_06_01.md, FIDELITY_LIVE_C_fasttaker_oraclelag_2026_06_01.md, FIDELITY_LIVE_D_legacy_updown_2026_06_01.md, FIDELITY_LIVE_E_shadow_updown_2026_06_01.md

**(a) What was tried:** Comprehensive backtest correctness audits: production-faithful replay, cross-engine comparison (Ireland vs VPS3), fidelity audits for all sleeve families (V5/V6/V7/V8/V9/vL/H, momo shadow, fast-taker oracle-lag), engine_v2 vs legacy configs, canonical binance-klines-1m contamination fix (+$14k inflation identified), REST lag vs WS lag.  
**(b) Verdict:** Ops/validation. Critical correction: binance-klines-1m contamination inflated baseline by ~$14k (identified and fixed). engine_v2 (LiveMimicConfig + 0.07 winner-only fee) established as canonical. WS-only book reads confirmed (no REST lag post-Phase 18.6). L25 1Hz subsample bias identified and corrected.  
**(c) Key numbers:** binance-1m contamination: +$14k inflation. 0.07-curve vs 2%-on-profit: ~$0.36–0.43/win overstatement at typical vwaps. L25 1Hz vs 10Hz: dramatic fill-rate divergence (V5 live: 0 placements vs thousands in backtest).

---

## 20. Audit / Debug (5 files)

**Files:** AUDIT_FINAL_CORRECTED_2026_05_29.md, DEBUG_FINDINGS_ALL_SLEEVES_2026_05_29.md, DEBUG_SOL5M_MOMOV2_PARITY_2026_06_03.md, DEBUG_SOL_MOMO_V2_HOLD_LIVE_VS_SHADOW_2026_06_02.md, REVALIDATION_ENGINE_V2_2026_06_03.md

**(a) What was tried:** Targeted debugging: full sleeve debug at 2026-05-29, SOL momo V2 live vs shadow parity, engine_v2 revalidation.  
**(b) Verdict:** Ops fixes. SOL momo V2 HOLD live vs shadow parity confirmed after fix. Engine_v2 revalidated with 0.07 winner-only fee.  
**(c) Key numbers:** N/A (diagnostic outputs).

---

## 21. RF / LightGBM Models (4 files)

**Files:** LIGHTGBM_STACKER_2026_05_26.md, RF_GATE_UP_BIAS_AUDIT_2026_06_08.md, RF_PARAM_SWEEP_PVSRA5M_2026_05_25.md, RF_RIBBON_OVERLAP_2026_05_25.md

**(a) What was tried:** Random forest gating for sniper sleeves (PVSRA signal sweep, ribbon overlap), LightGBM stacker on microstructure panel, RF up-bias audit (Jun 8).  
**(b) Verdict:** Mostly dead or priced-in trap. RF with high WR (e.g. btc_5m_l_1hrf_imb5_rf_v8: WR 76.4%) → $/tr −$0.32, t=−4.7: classic priced-in trap (WR inflated by late-window near-certain buys). LightGBM stacker: no standalone edge.  
**(c) Key numbers:** btc_5m_l_1hrf_imb5_rf_v8: WR 76.4%, $/tr −$0.32, t=−4.7 (SIG negative — priced-in trap).

---

## 22. Cross-Asset / CEX Lead-Lag (6 files)

**Files:** BTC_LEAD_LAG_5M_2026_05_23.md, CEX_ALIGNMENT_BACKTEST_2026_05_09.md, CEX_ALIGNMENT_HARNESS_DESIGN_2026_05_08.md, CROSS_ASSET_LEADLAG.md, CROSS_ASSET_MTF_CONFLUENCE_2026_05_25.md, CROSS_EXCHANGE_LEADLAG_2026_05_26.md

**(a) What was tried:** BTC→ETH/SOL lead-lag (5m), cross-exchange lead-lag (Coinbase/Kraken/OKX vs Binance as signal), CEX alignment backtest harness, multi-timeframe confluence across assets.  
**(b) Verdict:** Dead. Cross-asset lead-lag from SCALP_NEW_EDGE_HUNT: paired diff ≈0 (alts move with BTC in first 5s, 95% correlated). Coinbase lead signal (MOMO_COINBASE_LEAD): no incremental alpha vs Binance alone. Cross-exchange lead-lag: no extractable edge at our latency.  
**(c) Key numbers:** Cross-asset lead-lag paired diff ≈ 0. Coinbase overlay: no incremental alpha.

---

## 23. Multi-Round Sweep Syntheses (12 files)

**Files:** ALL_RESULTS_TABLE_2026_05_31.md, COMPLETE_STRATEGY_METRICS_2026_05_23.md, FULLPERIOD_5STRATS_FINAL_2026_05_31.md, FULLPERIOD_PERSISTENCE_2026_05_30.md, FULL_WINDOW_ALL_SLEEVES_2026_05_26.md, FULL_WINDOW_GATE_SEARCH_2026_05_26.md, FULL_WINDOW_VALIDATION_2026_05_26.md, PHASE_PLAN_CLOB_SLUGSELECT_AUTORESEARCH_2026_06_03.md, ROUND3_SYNTHESIS_2026_05_26.md, ROUND5_SYNTHESIS_2026_05_26.md, ROUND6_SYNTHESIS_2026_05_26.md, ROUND7_SYNTHESIS_2026_05_26.md

**(a) What was tried:** Rolling synthesis of multi-round gate search results, full-period re-analysis of 5 strategy families, persistence testing, full-window sleeve catalog. Rounds 3–7 = progressively refined gate combinations on the 15m sleeve universe.  
**(b) Verdict:** Reference/synthesis. Key finding from FULLPERIOD_5STRATS: sol_rf NOT deploy-ready — live +$93/69.5% WR was a favorable 3-day window. ma_300 is the real signal for sol_rf (not the base sleeve). ETH 5m winners: deployable, low drawdown. Kelly: real but fragile and sizing-driven.  
**(c) Key numbers:** sol_rf full-period: WR 59.8%, −$1,068, MaxDD −$1,345. All_results_table May 31: comprehensive sleeve PnL catalog.

---

## 24. New Sleeve Builds / PAT (9 files)

**Files:** NEW_BATCH_CLASSIFY_2026_05_29.md, NEW_INDICATORS_COMBINATORIAL_2026_05_23.md, NEW_INDICATORS_SYNTHESIS_2026_05_26.md, NEW_SLEEVES_ENTRY_RULES_2026_05_23.md, NEW_SLEEVES_INDIVIDUAL_METRICS_2026_05_23.md, OVERNIGHT_NEW_5M_STRATEGIES_2026_05_23.md, PAT_FINDINGS_2026_05_19.md, PAT_HYPERPARAMS_FULL_SWEEP_2026_05_20.md, PAT_TIMING_SWEEP_2026_05_20.md

**(a) What was tried:** New indicator sleeve builds from overnight session (May 23): Z-contra, VWAP variants, MA ribbon, slow stoch, spike entry, combinatorial indicator stacks. PAT (Price-Action Timing) — entry offset sweep, hyperparameter full sweep. New batch classification May 29 (49 candidates → 0 deploy-grade).  
**(b) Verdict:** Mostly dead. PAT timing: no edge beyond δ≥3bps timing. New indicators: no standalone survivors. May 29 batch: 0/49 candidates deploy-grade under proper controls (HANDOFF_2026_06_03).  
**(c) Key numbers:** 0/49 new candidates passed May 29 swarm. PAT: no incremental alpha vs δ≥3bps.

---

## 25. CL Basis (3 files)

**Files:** CLBASIS_ETH15_SOL15_VALIDATION_2026_05_29.md, CLBASIS_REL_BTC5M_DATASHEET_2026_05_29.md, CLBASIS_VS_LAGV2_RECONCILE_2026_05_29.md

**(a) What was tried:** Chainlink-Binance basis (cl_basis_bps) as directional signal. Validated BTC 5m capstone, extended to ETH 15m and SOL 15m. Reconciled vs LAGV2 TV spec.  
**(b) Verdict:** SAME EDGE as LAGV2 (oracle-lag taker), arrived at independently. LAGV2 is the productionized version. cl_basis extreme tail (BTC 5m): ~2 fires/day, OOS-confirmed but low-frequency. LAGV2's broader band (3–12bps) is the deployment target.  
**(c) Key numbers:** cl_basis extreme tail: 2 fires/day BTC 5m. LAGV2 vs cl_basis: identical core signal, LAGV2 adds 22/day band with gates.

---

## 26. Ops / Misc (252 files)

**Files (sample):** ACC_PC_BACKTEST_2026_05_19.md, ANTI_EDGE_FINDINGS.md, BATCH_3WAY_SYNTHESIS_2026_05_29.md, BTC_V3_DEEP_DIVE_2026_05_04.md, CAPACITY_SWEEP_GATED_SLEEVES_2026_05_22.md, CAPSTONE_STRATEGY_ARCHITECTURE_2026_05_29.md, CLEANUP_EXECUTION_2026_05_07.md, COVERED_CALL_BACKTEST.md, DASHBOARD_DIAGNOSIS_2026_05_01.md, DIRECTIONAL_BACKTEST_GATES_2026_05_28.md, DIRECTIONAL_WR_SCAN_2026_05_28.md, EDGE_GAP_ANALYSIS_2026_06_09.md, EDGE_VALIDATION_TIER1_2026_06_01.md, EFFICIENT_MARKET_FINDING_2026_05_28.md, ETH5M_SLEEVES_FULL_PERIOD_PROPER_2026_06_09.md, ETH5M_V8_V10_RERUN_2026_06_08.md, EXTERNAL_GATES_2026_05_30.md, EXTERNAL_STRATEGY_REVIEW_2026_05_27.md, FADE_MOMO_5M_2026_05_23.md, FAVORITE_LONGSHOT_2026_06_04.md, FINAL_SCORECARD_2026_05_21.md, FLOW_G1_GATE_2026_05_07.md, FULL_RANKING_AND_LOGIC_REVIEW_2026_05_01.md, FULL_UNIVERSE_BACKTEST_2026_05_19.md, FUNDING_OI_2026_05_26.md, FV_CVD_SPIKE_BACKTEST_2026_05_23.md, GATED_CONFIGS_2026_05_30.md, GATE_SEARCH_5M_2026_05_23.md, HARVEST_CANDIDATES_TODAY_2026_05_29.md, HL_GATES_REFINEMENT_2026_05_27.md, HOD_REFRESH_2026_05_22.md, HYBRID_GATE_SEARCH_2026_05_25.md, HYBRID_STANDALONE_2026_05_25.md, HYBRID_SYSTEM_FINAL_2026_05_26.md, IDLE_SLEEVES_DIAGNOSIS_2026_05_27.md, INDICATOR_SURVEY_2026_05_22.md, INFRA_BUILD_RESEARCH_2026_05_29.md, INFRA_ROADMAP_2026_05_29.md, INTRADAY_SCALP_RESEARCH_2026_06_02.md, IRELAND_MAKER_AUDIT_2026_05_20.md, KELLY_FULLPERIOD_2026_05_31.md, KLINE_TO_POLY_BRIDGE_2026_06_03.md, LAGV2_OOS_REVAL_2026_06_01.md, LIVE_LAUNCH_TOP5_2026_05_04.md, LIVE_MIMIC_WIRED_2026_05_16.md, LIVE_SHADOW_ANALYSIS_2026_05_01.md, LIVE_VS_SHADOW_RISK_REGISTER_2026_05_28.md, LOCK_THE_LAG_HYPOTHESIS_TEST_2026_05_29.md, LP_FARM_LIVE_RANKING_2026_06_03.md, MAKER_WALLET_REEVALUATION_2026_05_29.md, MASTER_COMBINATORIAL_2026_05_26.md, MASTER_DEPLOY_SPEC_2026_05_26.md, MASTER_LIVE_VS_BACKTEST_2026_05_29.md, MAS_15M_STALE_AND_PNL_BUG_2026_05_21.md, MEANREV_GATE_TEST_2026_05_29.md, MEGA_STACK_GATE_FINDINGS_2026_05_22.md, MICRO_TIER_BACKTEST_2026_05_07.md, ML4T_DSR_JUDGE_2026_06_04.md, ML4T_READY_2026_06_04.md, MORNING_SUMMARY_2026_05_23.md, MULTIVENUE_LEADLAG_2026_05_31.md, MULTI_WALLET_ALPHA_DECODE_2026_05_18.md, NAIVE_SUM_CORRECTIONS_2026_05_26.md, NEW_EDGE_FROM_PRODUCTION_DATA_2026_05_20.md, NEW_EDGE_RESEARCH_2026_06_01.md, NEW_EDGE_RESEARCH_2026_06_08.md, NEW_GATES_RESEARCH_2026_05_27.md, NEW_INDICATOR_SLEEVES_15M_2026_05_23.md, NEW_INDICATOR_SLEEVES_PER_MARKET_2026_05_23.md, NEW_STRATEGIES_PROPOSAL_2026_05_22.md, NEW_STRATEGY_DIRECTIONS_2026_06_05.md, NEW_WALLETS_ALPHA_DECODE_2026_05_18.md, NOCHASE_MERGEARB_VERDICT_2026_05_29.md, OPTIMIZATION_TEST_INVENTORY_2026_05_26.md, ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md, OUTCOME_RESOLUTION_CLOB_DISCOVERY_2026_05_12.md, OVERNIGHT_RESULTS_2026_06_04.md, OVERNIGHT_SEARCH_ANALYSIS_2026_06_03.md, PARALLEL_INVESTIGATION_SYNTHESIS_2026_05_21.md, PARITY_CONDITION_ID_PROOF_2026_06_03.md, PAT_TIMING_ANALYSIS_2026_05_20.md, PER_STRATEGY_FAMILY_GATE_COMPARE_2026_05_21.md, PHASE2_FINAL_FINDINGS_2026_05_24.md, PHASE7_CLOB_MOMENTUM.md, PHASE7_CLOB_MOMENTUM_2026_05_04.md, PHYSICS_ETH_GENERALIZE_2026_06_01.md, PHYSICS_FILL_REALISM_2026_06_01.md, PNL_AUDIT_JUNE_2026_06_08.md, POLYMARKET_CROSS_ASSET_LEADER.md, POLYMARKET_FEATURES_UNIVARIATE.md, POLYMARKET_FORWARD_WALK_MAKER.md, POLYMARKET_FORWARD_WALK_Q10.md, POLYMARKET_FORWARD_WALK_SPREAD.md, POLYMARKET_FORWARD_WALK_V2.md, POLYMARKET_LP_FARMING_STRATEGY_TYPES_2026_06_03.md, POLYMARKET_LP_REWARDS_RESEARCH_2026_06_03.md, POLYMARKET_MICROSTRUCTURE_FILTER.md, POLYMARKET_REALFILLS_HAIRCUT.md, POLYMARKET_REVBP_FLOOR_SWEEP.md, POLYMARKET_ROBUSTNESS_CHECK.md, POLYMARKET_RUBRIC.md, POLYMARKET_SHORT_WINDOW_ANALYSIS.md, POST_AUDIT_FINAL_CATALOG_2026_05_26.md, POSTFIX_VERIFICATION_2026_06_01.md, PROD_Q90_REPLICATION_2026_05_22.md, PROD_STRATS_28D_BACKTEST_FINDINGS_2026_05_21.md, QR_BACKTEST_2026_05_26.md, QUANTMUSE_MINING_2026_05_23.md, QUANT_RESEARCH_2026_05_26.md, QUEUE_AWARE_MAKER_VS_TAKER_2026_05_22.md, R5_GATES_ON_R4_15M_2026_05_26.md, RANGE_FILTER_PANEL_2026_05_25.md, RELAY_WALLET_DECODE_0xf3cfb6a6_2026_05_18.md, REST_LAG_AFFECTS_ALL_SHADOW_STRATEGIES.md, RF_GATE_UP_BIAS_AUDIT_2026_06_08.md, ROBUSTNESS_GATED_SLEEVES_2026_05_22.md, ROUND3_SYNTHESIS_2026_05_26.md, SAME_MARKET_MERGE_SCAN_2026_06_08.md, SILENT_FORENSICS_15M_TRSTACK_2026_06_01.md, SILENT_FORENSICS_CROSSASSET_HOD_2026_06_01.md, SLOW_STOCH_OVERLAY_2026_05_23.md, SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md, SLUG_SELECTION_DECODE_2026_05_20.md, SOL_ETH_MOMO_EXTENSION_2026_05_24.md, SOLRF_FULLPERIOD_2026_05_31.md, SPREAD_LOOSEN_SIM_BTC_5M_2026_05_27.md, SPREAD_RESEARCH_2026_05_29.md, STRATEGY_BUY_WAIT_HEDGE_LOCK_2026_05_29.md, STRATEGY_CATALOG_2026_05_18.md, TAKER_TRIGGER_DECODE_0xeebde7a0_2026_05_18.md, TOP5_STOPS_OPTIMIZATION_2026_05_04.md, TV_FIX_SPREAD_FILTER_2026_05_27.md, TV_FIX_SYNTHETIC_FILLS_2026_05_27.md, UNIVERSE_EXPANSION_GATE_2026_05_23.md, VOLUME_PROFILE_2026_05_26.md, WALLET_HUNT_SYNTHESIS_2026_05_29.md (full list from directories), WS_POLY2_DEDUP_VALIDATION_2026_05_26.md, and ~100 more

**(a) What was tried:** Catch-all for supporting research, single-topic investigations, and ops docs: gate search 5m, capacity sweeps, ORACLE_SETTLEMENT_SELECTOR (100% WR, 3–12% fill rate, CI spans 0), favorite-longshot bias test, EFFICIENT_MARKET_FINDING, LP farming research, CVD spike backtests, HYBRID gate system, ANTI_EDGE_FINDINGS, parity proofs, COVERED_CALL_BACKTEST, FUNDING/OI, KELLY_FULLPERIOD, EDGE_GAP_ANALYSIS (comprehensive killed/open matrix), ORACLE_SETTLEMENT_SELECTOR, SAME_MARKET_MERGE_SCAN, ETH5M full-period, and dozens of single-session investigations.  
**(b) Verdict:** Mixed — mostly supporting docs. Notable kills: COVERED_CALL (binary has no covered-call analog), NOCHASE_MERGEARB (dead), POLYMARKET_FORWARD_WALK_Q10 (forward-walk confirms efficiency), FAVORITE_LONGSHOT (present but gated-out by entry_px filter). Notable opens: ORACLE_SETTLEMENT_SELECTOR (+EV when it fills but fill rate too low). EDGE_GAP_ANALYSIS is the definitive summary.  
**(c) Key numbers:** Oracle settlement selector: 100% WR, 3–12% fill rate, CI spans 0 (needs more data). Favorite-longshot: present in data but gated out by entry_px<0.92 deployment filter.

---

## Summary Table

| # | Research Line | #Reports | Verdict | Status |
|---|---|--:|---|---|
| 01 | Session Handoffs | 22 | Reference | ops |
| 02 | V1–V5 Momo/Sniper Evolution | 18 | Dead | killed |
| 03 | Momo Misc Research | 39 | Dead (ws_s fix drops WR to 50%) | killed |
| 04 | Cyclops Clone | 7 | Edge confirmed BTC 5m | deployed (paper) |
| 05 | Silver / Confluence | 7 | Inconclusive (n too small) | open/stalled |
| 06 | Mint-and-Sell / Maker Entry | 11 | Dead (adverse selection) | killed |
| 07 | Maker-Arb | 10 | Dead (survivorship bias; maker-exit partial open) | killed / partial open |
| 08 | Wallet Decode / F2 / F7 | 51 | Insights extracted, unreplicable slug selection | research only |
| 09 | Lag-Taker / LAGV2 | 6 | Hold-to-res thin OOS; edge absorbed into exit-scalp | superseded |
| 10 | Exit-Scalp | 10 | REAL, deployed, OOS-validated 5 coins | deployed live |
| 11 | ML / Autoresearch | 22 | Dead (0/415 GPU nets, 0/25 DSR, meta-label ≈$0) | killed |
| 12 | Sleeve Fleet Ops / TV Agent | 102 | Ops; 4 EDGE sleeves live; 25 bleeders killed | deployed/ops |
| 13 | Hedge / Exit Policy | 7 | HEDGE_LATE useful on marginal sleeves | partial open |
| 14 | Indicator Sweeps | 19 | Dead except EMA50/800 btc_15m deployed | mixed |
| 15 | Microstructure / HF | 13 | Dead for direction | killed |
| 16 | Arb / Kalshi / Cross-TF | 8 | Cross-TF dead; Poly×Kalshi partial open (unverified depth) | partial open |
| 17 | Regime / Markov | 4 | Inconclusive at scale; dead for scalp | inconclusive |
| 18 | Data Infrastructure | 8 | Ops/reference | ops |
| 19 | Backtest Fidelity / Engine | 33 | Ops; critical bugs found and fixed | ops |
| 20 | Audit / Debug | 5 | Ops fixes | ops |
| 21 | RF / LightGBM Models | 4 | Dead (priced-in trap at scale) | killed |
| 22 | Cross-Asset / CEX Lead-Lag | 6 | Dead (fully correlated in 5s window) | killed |
| 23 | Multi-Round Sweep Syntheses | 12 | Reference; sol_rf correction notable | reference |
| 24 | New Sleeve Builds / PAT | 9 | Dead (0/49 pass May 29 swarm) | killed |
| 25 | CL Basis | 3 | Same edge as LAGV2; absorbed | superseded |
| 26 | Ops / Misc | 252 | Mixed supporting; EDGE_GAP_ANALYSIS definitive | ops/reference |

**Total: 696 files, 26 groups**

---

## Notable Cross-Cutting Findings

1. **The entire corpus converges on one real edge**: the intra-window exit-scalp (buy cheap lag-taker token at window open, sell on book +60s). Every other prediction/selection approach failed under proper DSR/OOS/permutation tests.

2. **Maker-arb censoring reversal** (Group 07): what looked like +$4.44/slug (btc_15m) was a survivorship-bias artifact. Uncensored truth: −$0.41/slug. A complete strategy reversal driven by adding canonical data.

3. **Priced-in trap** (Groups 11, 21): high WR strategies (RF WR 76.4%) can be SIG negative in $/tr. Volume-weighted-WR (WR inflated by late-window near-certain buys) is a systematic confound across 215 sleeves.

4. **Poly×Kalshi deep-dip arb** (Group 16): +2.7–6.6¢/set with CI>0, gated only on unverified Kalshi ask-depth. The one open positive lead requiring new data.
