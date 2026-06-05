# 04 — Deployed/Shadow Strategy Families & Sleeves

_As of 2026-06-03. Sources: HANDOFF_2026_06_03_SCALP_DEPLOY.md, HANDOFF_2026_06_03.md,
SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md, SLEEVE_INVENTORY_VPS3_2026_05_31.md,
MOMO_SHADOW_SLEEVES_TABLE_2026_05_11.md, DEPLOY_SLEEVES_28D_FINAL_2026_05_22.md,
BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md, CAPACITY_SWEEP_GATED_SLEEVES_2026_05_22.md,
ENSEMBLE_SIMULATOR_2026_05_23.md, cyclops/_results/MASTER_TABLE_REAL_FEES.txt._

---

## Sleeve/Family Table

| Sleeve/Family | What it is | Live/Shadow status | Measured PnL/WR | Verdict | Why | Report ref |
|---|---|---|---|---|---|---|
| **momo v1 — 18 sleeves** (BTC/ETH/SOL × 5m/15m × HOLD/HEDGE/SELL) | Binance-momentum taker at ws_s+120; first shadow fleet (May 7) | Shadow (VPS3); two sleeves promoted LIVE on Ireland: `btc_5m_momo_HOLD_f7`, `sol_5m_momo_v2_HOLD_f7` | 36 sleeves 5-day: total +$736.59, WR 51.65%; v1 HOLD: −$32.28; v2 HOLD best sleeve in family +$466.76 | WATCH (v2 HOLD only) | v1 net-negative; v2 HOLD positive in early shadow window but since subsumed into sniper-v5 fleet | MOMO_SHADOW_SLEEVES_TABLE_2026_05_11.md |
| **momo v2 — 18 sleeves** (same matrix as v1, new entry anchor ws_s+60) | MomoV2Strategy, fires 60s earlier than v1; A/B vs v1 | Shadow (VPS3) + 2 LIVE | v2 HOLD: 54.6% WR, +$1.72/tr, +$466.76 vs v1 HOLD −$32; ETH 15m +$716 best sleeve | WATCH → promoted to LIVE for btc/sol HOLD_f7 | Edge held in early window; subsumed into larger sniper fleet | TV_AGENT_MOMO_V2_SLEEVES_IMPLEMENTATION.md; MOMO_SHADOW_SLEEVES_TABLE_2026_05_11.md |
| **MOMO F7 filter** | RSI-gated version of momo v1/v2; F7 = production RSI gate at ws_s | Shadow overlay on momo | F7 improves selectivity; F7+Markov best combo; S1–S5 deploy sleeves WR 57–60%, +$4.10–5.67/tr | WATCH | Gate improves hit rate but not enough n for G4 alone; live match 94.67% | DEPLOY_SLEEVES_28D_FINAL_2026_05_22.md; MOMO_F7_PER_SLEEVE_TABLE_2026_05_20.md |
| **MARKOV filter overlay** | Markov regime filter stacked on momo/sniper | Shadow overlay | MARKOV+F7 stack best combo; 5 deploy sleeves validated on 28d: S1 n=92 WR=59.8% +$4.71/tr, S5 eth_5m WR=57.4% +$4.26/tr | WATCH | Marginal improvement over base; needs OOS | MARKOV_VS_F7_PER_SLEEVE_2026_05_21.md; HANDOFF_2026_05_22_MOMO_F7_MARKOV.md |
| **S1–S5 deploy sleeves (28d final)** | Five production-matched candidates: S1=btc_15m baseline_v1/M1V, S2=late_fire, S3=F7+M1V, S4=edge_of_slot/F7+M5V, S5=eth_5m/F7+M5F | Shadow (deployed May 2026) | S1: n=92 WR=59.8% +$4.71/tr +$433; S2: n=113 +$4.10/tr; S3: n=65 +$5.67/tr; S4: n=92 +$3.55/tr; S5: n=78 +$4.26/tr | WATCH | G1+G3 pass on 28d; G4 fail (n too small); awaiting OOS accumulation | DEPLOY_SLEEVES_28D_FINAL_2026_05_22.md |
| **sniper-v5 family — 90 sleeves** (BTC/ETH/SOL, 5m/15m, V5–V9+vL families, $5 notional) | Gate-stack overlay sleeves on S6/S15/V15m base fires; deployed 2026-05-26 via MASTER_DEPLOY_SPEC | Shadow (VPS3, all paper, $5) | 215-sleeve fleet net −$25.4k; sniper-v5 dominant volume; top bleeder: `btc_5m_l_1hrf_imb5_rf_v8` 76% WR but −$611 t=−4.7 (priced-in trap) | MIXED — 4 EDGE survivors, 25+ KILLED | High-WR sleeves at vwap 0.74–0.77 are priced-in; edge exists only in off600/trstack cluster | SLEEVE_INVENTORY_VPS3_2026_05_31.md; SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md |
| **4 EDGE sleeves (t≥2, as of 2026-06-02)** | Strongest real-edge sleeves in the 215-sleeve fleet | Shadow (VPS3) | `btc_15m_ema50_ema800_off600_down`: Kalshi 108 fires 84.3% WR +$1.33/tr t=2.0; Poly 134 fires 81.3% WR +$1.24/tr t=1.99; `eth_5m_l_ema50_hurst_grandparent_v8`: 183 fires 71.0% WR +$0.66/tr t=2.2; `btc_15m_ts_trstack_off600_down` t=2.1; `btc_15m_mpskew_trstack_off600_down` t=2.4 | EDGE | Cross-venue replication (Kalshi+Poly) + WR vs breakeven gap (~8pp surplus); mechanism = established-trend continuation lag | SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md; EMA_BTC15M_DEPLOYABILITY_2026_06_01.md; REAUDIT_4SLEEVES_MASTER_2026_06_03.md |
| **INV_NIGHT × 6 sleeves** (BTC/ETH/SOL, 5m/15m) | Volume-regime overnight sleeves | Shadow (VPS3) | 2244–2819 fires per sleeve, WR ~50%, −$0.75 to −$1.81/tr; total −$10k | KILLED | Coin-flip WR, entry cost = pure loss; dominant bleeder | SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md |
| **phase1_kelly** (shadow_poly_updown_ALL_5m_phase1_kelly) | Kelly-sized S4∪S8 ensemble with fair_edge_bp tiers | Shadow (VPS3) + prior LIVE match | Backtest 28d WR 53% +$2.72/tr +$2722 bt; Live n=625 +$1728; BUT 89% of edge = sizing leverage not signal; 7d running: −$1,102 | KILLED (shadow drag) | Recent shadow negative; flat-$25 backtest collapses to +$186 — overwhelmingly sizing not alpha | BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md; SLEEVE_INVENTORY_VPS3_2026_05_31.md |
| **Fade family** (btc/eth/sol_5m/15m fade_momo_v2 + fade_sniper) | Fades production momo/sniper signals | Shadow (VPS3) | Mostly losers: btc_5m fade −$518 (44.4% WR), sol_5m fade −$371/−$427; eth_15m fade_sniper only positive +$142 | KILLED (most); WATCH eth_15m | Anti-edge on BTC/SOL; live −$487/26h vs backtest +$71/day expected → direction bug + signal inversion | BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md; FADE_MOMO_5M_2026_05_23.md |
| **S3/S4 prewindow** (ALL_5m_S3, ALL_15m_S4) | Pre-window entry 60–120s before slot open | Shadow (VPS3) | S3 live n=219 54.8% WR +$1.32/tr +$288; backtest DIVERGES (fire-set mismatch); S4 live n=14 78.6% +$12.56/tr tiny n | WATCH (live only, not backtest-confirmed) | Fire-set diverge: live fires on different subset than backtest | BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md |
| **fast_taker family** (poly_fast_taker_a25_merge, btc/eth 5m — LAGV2) | Oracle-lag HFT, $25/fire, high frequency | Shadow (VPS3) | 7d: btc_5m −$2,595; eth_5m −$7,558; LAGV2 always-UP bug fixed 2026-06-03 (now 50/50) | WATCH (post-bugfix) | Was biased always-UP; net negative pre-fix; need fresh window | SLEEVE_INVENTORY_VPS3_2026_05_31.md; HANDOFF_2026_06_03_SCALP_DEPLOY.md |
| **VWAP-cont family** (5 sleeves: btc/eth/sol, off60–240) | VWAP deviation continuation | Shadow (VPS3) | 0 fires in 3d — gates too tight; not bugs | DEPRECATED/WATCH | Gates: `|dev| ∈ [5,10] bps AND m1v agrees` → no fires in reasonable window | SLEEVE_INVENTORY_VPS3_2026_05_31.md; IDLE_SLEEVES_DIAGNOSIS_2026_05_27.md |
| **ACC-H / ACC-M / ACC-PC family** | Accumulation maker strategy | Shadow | ACC-M mean −$1.04/slug, ACC-PC −$1.12/slug on 50 slugs | DEPRECATED | Both net-negative even with rebates; survivorship bias (right-censored losers) same problem as maker-arb | ACC_PC_BACKTEST_2026_05_19.md; STRATEGY_SPEC_ACC_2026_05_18.md |
| **BDH deploy spec** | Batch-deploy hedging variant | Shadow spec | Not measured live | DEPRECATED (no live data found) | Superseded by sniper-v5 fleet | TV_DEPLOY_SPEC_BDH_2026_05_21.md |
| **PAT_ACCM hybrid** | Partial accumulation + taker hybrid | Shadow spec | Not measured live | DEPRECATED | Superseded | TV_DEPLOY_SPEC_PAT_ACCM_HYBRID_2026_05_19.md; TV_AGENT_PAT_ACCM_IMPLEMENTATION_SPEC.md |
| **V3 family** (BTC/ETH/SOL, 3 assets) | V3 baseline entry-at-window-start with spread fix | Shadow (early), then absorbed | Holdout 20% week: BTC +$8.29, ETH +$2.09, SOL_fix +$4.79 | DEPRECATED (absorbed) | Superseded by momo_v2/sniper-v5; V3/V4 on KILL LIST from fleet audit | V3_BACKTEST_FINDINGS_2026_05_04.md; V3_PRODUCTION_REPLAY.md |
| **V4 family** | V4 plan after V3 — heavier gate stack | Shadow | Not quantified separately (absorbed into sniper family) | KILLED | Fleet audit confirmed KILL | V4_PLAN_AND_RESULTS_2026_04_30.md; SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md |
| **V5 late-entry** (BTC/ETH/SOL) | Late-entry at up_imb_slope_240s tails; BTC Q0-20 69.9% UP wins | Backtest only → deployed as sniper-v5 infra | BTC Q0-20 69.9%, Q80-100 71.2%; ETH/SOL similar; n≈8,200 in-sample | WATCH (within sniper-v5 fleet) | Signal valid but 1184 V5 live evals → 0 placements (cross-token spread 31% killed all fills) | V5_LATE_ENTRY_SPEC_2026_05_04.md; ETH_5M_V3_V4_DIAGNOSIS_2026_05_11.md |
| **Cyclops S7 X1** (BTC 5m, sleeve-active composite) | Three-axis (Trend+Levels+Momentum) conflict filter; only fires when any VPS3 BTC 5m sleeve also fires | Shadow/paper-deploy spec ready | X1_S7+sleeve_active: n=36 WR=80.6% +$0.244/tr total +$8.79 G3 p=0.002 **G4 PASS** (G4lo=+$0.0042) | EDGE — deploy-ready | Only config passing G1+G3+G4 with real PMXT fees; BTC 5m only, does NOT generalize | cyclops/_results/MASTER_TABLE_REAL_FEES.txt; CYCLOPS_CLONE_SPEC_2026_05_16.md; cyclops/PAPER_DEPLOY_SPEC.md |
| **Cyclops v1_baseline** (broad, hours off) | 305 fires/21d, WR 61.3%, +$1.50/tr | Paper deploy spec (not yet live) | G1+G3 PASS; G4 FAIL (CI crosses 0); expected n=300 in ~21d of live | WATCH | G4 needs live accumulation; deploy alongside v1_hours | cyclops/PAPER_DEPLOY_SPEC.md |
| **Cyclops v1_hours** (high-confidence hours guard) | 53 fires/21d, WR 67.9%, +$4.34/tr | Paper deploy spec (not yet live) | G1+G3 PASS; G4 FAIL (sample-size only); expected n=300 in ~120d live | WATCH | G4 fail is n not signal; best mean PnL of cyclops family | cyclops/PAPER_DEPLOY_SPEC.md |
| **KELLY_FULLPERIOD** | Full-period Kelly sizing study | Research only | Kelly edge is 89% sizing (4× on fair_edge_bp tail), 11% signal; flat-$25 collapses +$1728 → +$187 | DEPRECATED (no standalone deploy) | Sizing leverage not a standalone strategy | KELLY_FULLPERIOD_2026_05_31.md; BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md |
| **BACKTEST_KELLY_PREWINDOW_FADE** | Kelly/S3-S4/Fade family backtest vs live | Research | phase1_kelly MATCH live+bt; S3/S4 DIVERGE fire-set; fade mostly anti-edge | Research finding (see fade/kelly rows above) | See individual sleeve rows | BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md |
| **CAPACITY_SWEEP — 11 gated sleeves** | L25 book capacity analysis at $25–$10k notionals | Research / sizing | Aggregate max-sum (11 sleeves, 28d) +$341k unconstrained, +$277k practical; BTC_15m_momo_v1 peaks $10k → +$118k/28d | Research / sizing guide | Not a strategy; sizing toolbox for when real capital is committed | CAPACITY_SWEEP_GATED_SLEEVES_2026_05_22.md |
| **ENSEMBLE_SIMULATOR** | All winning strategies on one timeline; de-duped by (slug, direction) | Research simulation | Combined n fires from S1.5/S2/S3/S6; top sleeve S3_refresh_momo_btc_15m: n=25 WR=76% +$12.94/tr | Research (not deployed as ensemble) | Overlap analysis; revealed slug-overlap inflation problem | ENSEMBLE_SIMULATOR_2026_05_23.md |
| **Kalshi ema50_ema800 sleeve** | Same gate as Poly ema50_ema800_off600_down but on Kalshi venue | Shadow (VPS3, Kalshi) | 108 fires 84.3% WR +$1.33/tr t=2.00 | EDGE | Cross-venue replication of the strongest Poly sleeve; Kalshi FOK→IOC bug fixed 2026-06-03 | SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md; EMA_BTC15M_DEPLOYABILITY_2026_06_01.md |
| **Scalp-exit sleeves — 16 new** (shadow_scalp_exit_{btc,eth}_{5m,15m}[_d3]_{v1,control_v1}) | Intra-window exit-scalp: buy lag-taker cheap (entry_vwap<0.55), sell on book at +60s | Shadow (VPS3, deployed 2026-06-03) | Backtest: +$2.98/tr t=6.33 walk-forward; bootstrap CI [+1.63, +3.46] excludes 0; direction permutation p=0; offline fwd_oos NEGATIVE (n=14–76 flat) | WATCH (forward-OOS gate pending) | Only strategy surviving walk-forward + permutation + worst-case fee; deployed 16 sleeves δ≥5@$25 + δ≥3@$5; needs ≥200 live forward fires with CI>0 before real capital | HANDOFF_2026_06_03_SCALP_DEPLOY.md; SCALP_VALIDATION_2026_06_02.md; MASTER_FINDINGS_TABLE_2026_06_02.md |
| **SNIPER_HOD** (btc_5m_sniper_hod) | HOD-gated sniper | Shadow (VPS3) | 7d: n=75 −$433 | KILLED | Confirmed bleeder in fleet audit | SLEEVE_INVENTORY_VPS3_2026_05_31.md; SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md |
| **Maker-arb family** | Maker side Polymarket CLOB; mint+SELL strategy variants | Research; no live deploy | ALL net-negative once right-censoring corrected: −$0.41 to −$3.63/slug (was faked +$4.44 by survivorship) | DEPRECATED — DO NOT DEPLOY | Survivorship bias: directional losers never get REDEEM event; uncensored truth all negative | MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md; MAKER_ARB_DEPLOY_DECISIONS_2026_05_27.md |

---

## LIVE sleeves (Ireland VPS, real capital, as of 2026-06-03)

| Sleeve | Notes |
|---|---|
| `poly_updown_btc_5m_momo_HOLD_f7` | Promoted from shadow; LIVE on Ireland |
| `poly_updown_sol_5m_momo_v2_HOLD_f7` | Promoted from shadow; LIVE on Ireland |
| `poly_updown_btc_15m_momo_HEDGE_f7` | DEPRECATED (redundant vs HOLD) |
| `kalshi_sniper_btc_15m_ema50_ema800_off600_down` | Kalshi venue LIVE; FOK→IOC fix deployed 2026-06-03 |
| `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` (+ `_H` hedge variant) | Poly venue LIVE; hedge FOK bug open |

All 16 scalp-exit sleeves and most sniper-v5 family = **shadow/paper** (no real orders).

---

## Net

- **Total shadow sleeves ever deployed:** ~215 active in fleet as of 2026-06-02; started from 36 (momo v1+v2, May 7) → grew to 90 (sniper-v5) + ~125 others.
- **Fleet net PnL (215 sleeves, shadow):** **−$25.4k** (as of 2026-06-02 audit).
  - 25 confirmed bleeders responsible for −$19.8k; INV_NIGHT ×6 alone = −$10k.
  - 4 EDGE survivors (t≥2, +$/tr): `btc_15m_ema50_ema800_off600_down` (Kalshi + Poly), `eth_5m_l_ema50_hurst_grandparent_v8`, `btc_15m_ts_trstack_off600_down`, `btc_15m_mpskew_trstack_off600_down`.
- **Current EDGE (t≥2):** 4 sniper-v5 sleeves above + Cyclops S7 X1 (G4 PASS, n=36) + 16 scalp-exit sleeves (WATCH, fwd-OOS gate open).
- **Current LIVE (real capital):** 2 momo HOLD_f7 sleeves (Ireland) + Kalshi ema50_ema800 sleeve.
- **Kill list (pending TV-agent action):** INV_NIGHT ×6, phase1_kelly, fade ×N, `btc_5m_l_1hrf_imb5_rf/ribbon` (trap-at-scale), v3/v4/sniper_hod. Estimated drag reduction ≈ −$13–20k shadow.
