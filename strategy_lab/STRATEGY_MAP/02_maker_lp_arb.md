# Strategy Map — Maker / LP / Arb Category

**Generated:** 2026-06-03  
**Sources scanned:** ~65 reports in `strategy_lab/reports/` + `polymarket_lp_rewards/`  
**Synthesis anchor:** `ARB_RESEARCH_SYNTHESIS_2026_05_29.md` + `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`

---

## Strategy Table

| Strategy / Idea | What tried | Method / data | VERDICT | Why (1 line) | Report ref |
|---|---|---|---|---|---|
| **Symmetric maker-arb (ACC-H, ACC-M, PAT, MAS)** — paired bids both sides, hold to resolution | Multi-sleeve backtest; shadow deploy on VPS3; backfill vs live wallet PnL | engine_v2, L25 books, canonical resolutions; 1.5d live shadow | **DEAD** | Survivorship bias: "inv=0" filter excluded directional losers → apparent +$4.44/slug was actually −$0.41 to −$3.63/slug uncensored | `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`, `MAKER_ARB_CONTEXT_HANDOFF_2026_05_28/29.md`, `MAKER_ARB_DEPLOY_DECISIONS_2026_05_27.md`, `MAKER_ARB_DEPLOY_REPORT_2026_05_21.md` |
| **Positioned / sequential leg-in maker-arb** — enter one side at market, post opposing maker | Economics modeling + literature review | ARB_RESEARCH_STATARB report, Glosten-Milgrom model | **DEAD** | −$0.03/share; adverse selection on the one-sided leg per Glosten-Milgrom | `ARB_RESEARCH_STATARB_POSITIONED_2026_05_29.md`, `MAKER_ARB_POSITIONED_PLAN_2026_05_29.md`, `MAKER_ARB_BACKFILL_REAL_PNL_2026_05_29.md` |
| **Mint-and-sell V1** — mint pair, post both asks at market | Replication of live wallets; scanner on 21d canonical | `mint_and_sell_scan.py`; L25 + resolutions | **DEAD** (V1 bug) | Known bug: treated maker fee as "80% of taker fee" instead of $0 + rebate; PnL understated ~30-50%; superseded by V2 | `MINT_AND_SELL_REPLICATION_2026_05_16.md`, `MINT_AND_SELL_LIVE_SPEC_2026_05_16.md` |
| **Mint-and-sell V2** — $2.5 notional, corrected fee (rebate as income), sum_asks ≥ $1.005 | Full replication across 6 cells (BTC/ETH/SOL × 5m/15m), 21d window | `mint_and_sell_scan_v2.py`; L25 native 10Hz; slug-level aggregation | **INCONCLUSIVE → NOT-DEPLOYED** | Per-fire negative (−$0.06/−$0.15); slug-level flips positive ONLY in BOTH_SIDES_PARTIALS regime (+$0.04–$0.41/slug); implementation spec exists but needs live account validation of rebate share | `MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`, `MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md`, `MINT_AND_SELL_PARTIAL_FILL_POLICY_2026_05_16.md` |
| **Mint-and-sell V3** — asymmetric CVD-gated posting (skip one side when flow strongly directional) | Simulation on 7,490 V2 fills with CVD + sigma filters | `_v3_simulate.py`, binance 1s RTDS overlay | **DEAD** | Reduces daily bleed 47-94% but never flips net-positive; dominant lever is sigma filter (skip), not CVD asymmetry | `MINT_AND_SELL_V3_SIMULATION_2026_05_23.md`, `MINT_AND_SELL_CVD_TIMING_2026_05_23.md` |
| **Mint-and-sell V3 wallet model** — pre-mint per slug, reuse inventory, mark at fill not post | Projected PnL at $50/$100/$200 pre-mint; wallet-calibrated model | Slug-level aggregation from V2 fills; wallet chain analysis | **EDGE-VALIDATED (paper only)** | +$1.81–$5.07/slug at $50-$100 pre-mint in sol_5m mid-rank; 74-77% positive slugs — spec exists (IMPLEMENTATION_SPEC_V1, 1,479 lines) but live deploy not yet done | `MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md`, `MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md`, `TV_DEPLOY_SPEC_MAS_2026_05_18.md`, `STRATEGY_SPEC_MAS_2026_05_18.md` |
| **MAS (Maker-And-Sell / Mint-And-Sell) TV agent deploy** — V3 on VPS3 | TV agent spec written; deploy spec Rev 2026-05-19; bug fix guide | `TV_AGENT_SPEC_MAS_2026_05_18.md`, `TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md`; 15m stale bug patched | **NOT-DEPLOYED** (blocked) | MAS_15M_STALE_AND_PNL_BUG killed 15m sleeve; V3 net-negative in simulation (see above) — deploy blocked pending V2/V3 resolution | `TV_AGENT_SPEC_MAS_2026_05_18.md`, `TV_DEPLOY_SPEC_MAS_2026_05_18.md`, `TV_AGENT_FIX_MAS_V3_SPEC.md`, `MAS_15M_STALE_AND_PNL_BUG_2026_05_21.md` |
| **Sum < $1 atomic take-both arb** — buy both Up+Down when sum_asks < $1 | Literature review + brief empirical check | ARB_RESEARCH reports; book-time analysis | **DEAD** | Only 0.004–0.13% of book-time; requires sub-100ms colo we don't have | `ARB_RESEARCH_PREDICTION_MARKET_2026_05_29.md`, `ARB_RESEARCH_SYNTHESIS_2026_05_29.md` |
| **Buy→Wait→Hedge lock** — buy lag-leading side, then complete set when complement gets cheap | FIFO matched-pair analysis on wallet 0xeebde7a0; naive EV calc | `_decode_lock_pattern_2026_05_29.py`; wallet chain history | **DEAD** (naive form) | Matched-pair median sum=1.020; only 38.8% of completions sum < $1; net −$961 on completed pairs; profit is directional residual not locks | `STRATEGY_BUY_WAIT_HEDGE_LOCK_2026_05_29.md` |
| **Maker limit orders vs taker (passive fill experiment)** | 11 gated sleeves at best_bid/mid/ask−1 tick; compared PnL vs taker | `maker_vs_taker_gated_sleeves.py`; 15,844 fire × placement combos | **DEAD** | Passive limit never beats taker fill on same signal; adverse-selected by informed flow | `MAKER_VS_TAKER_GATED_SLEEVES_2026_05_22.md`, `QUEUE_AWARE_MAKER_VS_TAKER_2026_05_22.md`, `MAKER_QUEUE_LATENCY_PROBE_2026_05_29.md` |
| **Directional-tilted / one-sided maker** — post only on binance-favored side | Literature research; not yet backtested empirically | ARB_RESEARCH_MARKET_MAKING; Cartea-Wang model | **INCONCLUSIVE** | Strongest new maker concept per synthesis (Cartea-Wang: symmetric MM suboptimal when you hold signal); no empirical test yet | `ARB_RESEARCH_MARKET_MAKING_2026_05_29.md`, `ARB_RESEARCH_SYNTHESIS_2026_05_29.md` |
| **Maker rebate harvesting (Program-2)** | Rate estimation; floor income calc | Polymarket API docs; `0.07 × p × (1-p)` fee curve + 20% rebate share | **INCONCLUSIVE** | ~$0.003–0.0034/contract floor income confirmed; rebate share needs live account pin from TV dashboard; crypto up-down LP rewards pool not yet open | `MAKER_ARB_POSITIONED_PLAN_2026_05_29.md`, `ARB_RESEARCH_SYNTHESIS_2026_05_29.md` |
| **Spread-loosen simulation** — widen book spread filter 0.020→0.025 on existing sleeves | Per-sleeve impact analysis across BTC/ETH/SOL × 5m/15m | `SPREAD_LOOSEN_SIM_*.md`; L25 native 10Hz; 3,596 borderline fires | **INCONCLUSIVE** | Marginal fires from 0.025 band dilute existing top sleeves (e.g. best $/tr sleeve loses −$0.034/tr); not worth loosening for top sleeves | `SPREAD_LOOSEN_SIM_BTC_5M_2026_05_27.md`, `SPREAD_LOOSEN_SIM_ETH_2026_05_27.md`, `SPREAD_LOOSEN_SIM_SOL_5M/15M_2026_05_27.md` |
| **Deep stacking (R3+R5 gate overlays on maker panels)** | Greedy forward-add by sum_pnl and $/tr; 3-way lockbox validation | `deep_stack_panel_{s6,s15,v15m}.parquet`; 21d May panel | **DEAD** | Saturates at hybrid_v1; no R3+R5 gate improves total $ on any of 6 sleeves; 10-gate stack breaks all to n=0 | `DEEP_STACKING_2026_05_26.md` |
| **Covered-call / long perp + short binary NO** | Full backtest n=8,189 markets; leverage sweep 1-60×; two sizing modes | `covered_call_backtest.py`; Binance perp + Poly canonical | **DEAD** | No consistent edge; best cell ETH 15m q10 at +9% ROI n=69 too thin; structure is fairly-priced offset (no inherent edge) | `COVERED_CALL_BACKTEST.md` |
| **Cross-exchange CEX↔CEX latency arb / MEV / microwave** | Literature survey | ARB_RESEARCH_LATENCY_HFT | **DEAD** | Sub-ms speed race; we lose; no mempool access | `ARB_RESEARCH_LATENCY_HFT_2026_05_29.md` |
| **Pairs / cointegration / vol-arb / funding-carry / basis / index arb** | Literature survey | ARB_RESEARCH_STATARB | **DEAD / N/A** | No short, no futures leg on Poly; slugs independent; instruments not available | `ARB_RESEARCH_STATARB_POSITIONED_2026_05_29.md` |
| **LP rewards farming (Polymarket Program-1 liquidity rewards)** | Scoring math decoded; 232 healthy farm targets identified; ranked by pool/competition | `lp_rewards_rank.py`, `lp_book_analyze.py`; Polymarket CLOB sampling API; `_lp_healthy_farms.csv` | **INCONCLUSIVE → active research** | Not free money (tight orders = fillable → carry risk); crypto up-down pool "coming soon"; sports/esports $5M Apr-2026 pool active; 232 healthy targets ranked in Tier 1-3 by risk-adj yield | `POLYMARKET_LP_REWARDS_RESEARCH_2026_06_03.md`, `POLYMARKET_LP_FARMING_STRATEGY_TYPES_2026_06_03.md`, `LP_FARM_LIVE_RANKING_2026_06_03.md`, `polymarket_lp_rewards/README.md` |
| **Sponsored-pool stacking** — hunt markets with active USDC sponsorships on top of native rewards | Research; live ranking | `POLYMARKET_LP_REWARDS_RESEARCH_2026_06_03.md`; Polymarket sponsorship API | **INCONCLUSIVE** | Sponsorships stack (>$500 active sponsors found); combine with Tier-1 farm targets for higher $/day; not yet live-tested | `POLYMARKET_LP_REWARDS_RESEARCH_2026_06_03.md` |
| **Ireland maker audit** — CLOB order placement latency + book fidelity check | Live order placement tests from Ireland VPS | `IRELAND_MAKER_AUDIT_2026_05_20.md`, `IRELAND_MAKER_PATCH_VERIFICATION_2026_05_21.md` | **INCONCLUSIVE** | Infra verified (<2ms RTT to AWS eu-west-2); patch verified; findings fed into engine_v2 latency model; not a strategy verdict | `IRELAND_MAKER_AUDIT_2026_05_20.md`, `IRELAND_MAKER_PATCH_VERIFICATION_2026_05_21.md` |

---

## Net

**Total mapped:** 20 strategy/idea lines across maker, LP, arb, and liquidity-provision categories.

**Survivors (not fully killed):**
1. **Mint-and-sell V3 wallet model** — EDGE-VALIDATED on paper; full implementation spec exists; live deploy blocked (rebate share unverified, net-positive only at slug-level in BOTH_SIDES_PARTIALS regime, MAS 15m bug killed deploy attempt). Next step: live account rebate pin + shadow deploy.
2. **LP rewards farming** — active research as of 2026-06-03; 232 healthy farm targets ranked; crypto up-down pool not yet live ($5M sports pool is). Not free money but a real edge lane if managed as genuine MM with directional risk.
3. **Directional-tilted / one-sided maker** — academically motivated (Cartea-Wang); no empirical backtest yet done; flagged as "BUILD" in synthesis.
4. **Maker rebate harvesting** — confirmed floor income (~$0.003-0.0034/contract); needs live pin.
5. **Sponsored-pool stacking** — untested live; stacks on LP farming.

**5 most notable DEAD / closed lines:**
1. **Symmetric maker-arb (ACC-H/ACC-M/MAS/PAT)** — headline kill: apparent +$4.44/slug was survivorship bias; uncensored truth −$0.41 to −$3.63/slug. DO NOT revive.
2. **Mint-and-sell V3 CVD-asymmetric** — reduces bleed 47-94% but never net-positive even at ultra-aggressive gating; CVD is irrelevant, sigma filter is the lever.
3. **Covered-call (long perp + short NO binary)** — no inherent edge, fairly-priced offset; ETH 15m n=69 edge too thin.
4. **Buy→Wait→Hedge lock** — 61.2% of matched-pair completions sum ≥ $1; net −$961; directional residual is the profit, not the lock.
5. **Deep stacking (R3+R5 overlay gates)** — stacks saturate at hybrid_v1; 10-gate combos hit n=0; no improvement over base sleeves on any of 6 cells.

**Key gaps (maker/arb variants NOT tested):**
- Directional-tilted one-sided maker not empirically backtested (only literature-validated)
- Rebate income from live TV dashboard not yet pinned (needed to validate BOTH_SIDES_PARTIALS mint-sell)
- Crypto up-down LP rewards pool (Polymarket Program-1) not yet open; entire LP farming angle conditioned on this
- Cross-slug term-structure arb (1m/5m/15m consistency deviation) — mentioned in synthesis as PARTIAL but no backtest
- N(d2)/BSM fair-value-vs-Poly-price relative value — identified as new candidate, never tested
