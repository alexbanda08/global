# Session Handoff — 2026-06-13 — b945 full decode, replication campaign, edge-gap, TVRUST spec

**READ THIS FIRST.** This session exhaustively decoded Polymarket maker wallet `0xb945945d`, built and
validated an offline market-making backtest engine, ran ~15 tests + 2 multi-agent workflows, found and
corrected **5 of our own prior conclusions**, wrote the TVRUST build spec, and converged on a precise
answer to "where is his edge and can we replicate it offline." One workflow is still in-flight at write
time (queue-priority-from-trades — see §H). GROUND-TRUTH RULE was the through-line: nearly every headline
got overturned at least once; trust raw fills/trades/audit, never article claims or aggregate intuition.

---

## A. THE WALLET — final decoded picture
`0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` = `@l5zn1bwom8etsk`, author of the "6 edges" + infra-guide
articles. **100% btc-updown-15m.** Gnosis Safe 1.3.0 proxy (relayer/ERC-4337 txs, never self-submits).

- **PnL = +$21,742 lifetime (AUDITED, identity closed to 0.17%):** REDEEM $1,352,604 + MAKER_REBATE $3,645
  − fill costs $1,334,507. Reconciles with operator-verified live balance 20,639 pUSD. (`B945_PNL_AUDIT`.)
  Per-slug: **+$10.65/slug mean** ($3.18 median), ~$250/day lifetime avg, **~$500/day recent** (6× throughput
  growth Mar→Jun). Deploys **~$674/slug** (≈$332/side, ~760 sh/side). Edge ≈ 0.8% of volume.
- **Strategy (confirmed at every layer):** dense two-sided **GTC MAKER** bid ladder (63% maker / 37% taker),
  clip ∝ price ($0.34@2¢ → $27@97¢, $5 median clip), across the FULL window; hold both legs to resolution;
  recover collateral POST-resolution via `mergePositions` (1,307 calls, 100% post-resolution — NOT mid-window)
  + `redeemPositions` for residual. **ZERO `splitPosition`** (never mints — the article's split-liquidity
  technique is NOT used). Soft inventory skew. **No directional signal** (open-side AUC 0.53; side-decode 0.47).
- **Profit engine:** paired sum<1 capture — median paired cost **pvs 0.968** (3.2¢/pair edge), 72.6% of slugs
  pvs<1, ~159–760 paired sh/slug. His residual (unpaired) leg LOSES (−$10.9/slug) — he tolerates it because
  the paired base × tiny edge × huge volume + rebate nets positive.

## B. WHERE HIS EDGE ACTUALLY IS (the decomposition — `B945_EDGE_GAP_DECOMPOSE_2026_06_13`)
His pvs 0.968 vs our best sim 0.991 = **2.3¢/pair gap = the whole difference between his $500/day and our
breakeven.** Decomposed (n=1,203 matched slugs, reproduced exact):
- **ALL of the gap is the WINNER/favorite leg** (he buys the eventual winner −3.28¢ cheaper, t=−12.7).
- **The LOSER leg is +2.04¢ in OUR favor** (we buy the loser cheaper — it's a DRAG on his pvs, NOT his edge).
- Mechanism: **33.4% of his fills are BELOW the contemporaneous best bid** = resting-order **time-priority**
  (a low rung placed before the bid climbed through it). This is queue priority on the winner leg.
- **~1.8¢ looks offline-addressable** (static ladder vs our requote-up chase) **BUT does NOT translate to PnL**:
  the static ladder BEATS his pvs (favorite 0.621 vs 0.695) yet nets **−$1.8 to −$2.8/slug** — cheap pairs come
  with fewer completions + bleeding residual. His edge = queue priority doing 3 things at once (fill cheap AND
  complete the pair AND stay square). ~1.2–1.5¢ + ~1¢ coverage = **purely live-queue, no L25 field encodes rank.**
- ⚠️ **OPERATOR PUSHBACK (valid, being acted on):** "unmodellable offline" was too absolute — the TRADE TAPE
  IS the queue-consumption process and lets us MEASURE realized capture. Workflow in-flight (§H).

## C. ECONOMIC BOTTOM LINE — why we can't just copy him
Our best offline replica (maker-only, tight inventory cap Q=5): deploys ~$161/slug, makes **+$0.39/slug —
which is ENTIRELY rebate**; the arb itself (paired+residual) is **−$0.12/slug** (breakeven-negative). His
per-slug is ~27× ours because: ~4× more capital + **~3.5× better edge/pair (3.2¢ vs 0.9¢, = fill quality /
queue priority)** + ~4.5× more volume. **We CAN'T copy his bigger stake:** loosening our inventory cap to
deploy more blows up the residual (Q=20 → net −$0.69), because our 0.9¢ edge can't cover the residual at
volume; his 3.2¢ edge can. The edge-per-pair (fill quality) is the root, and it's the live-queue thing.

## D. THE TEST CHAIN (chronological, all verdicts)
| # | Test | Report | Verdict |
|---|------|--------|---------|
| 1 | Snapshot sum-arb (buy both when sum_ask<1) | `SUMARB_PREREG_BT` | DEAD — 0 opportunities in 134,877 evals (sum_ask never <1 simultaneously; median 1.04) |
| 2 | ce25 legging decode | `CE25_LEGGING_DECODE` | He's untimed CLOB sweep, no dip-timing (separate wallet) |
| 3 | Inventory-managed maker engine (queue replay) | `MM_ENGINE_QUEUE_REPLAY` | VALIDATED in-sample (+$2.76/slug); OOS −$0.54 |
| 4 | Requote-latency sweep 0ms→2s | `MM_ENGINE_QUEUE_REPLAY` §latency | **SPEED IS NOT THE LEVER** — flat across all L; even 0ms OOS −$0.54 |
| 5 | Maker+taker hybrid + guide filters | `MM_HYBRID_REPLICA` | All NO-GO; taker-completion gate NEVER fires (sum_asks≥1.0 at every taker fill) |
| 6 | **Tighter GLT cap Q∈{2,3,5,8,12,16,20}** | `MM_Q_AND_SHORTSIDE` | OOS net MONOTONE in Q; **Q≤5 → +$0.39..+0.51/slug (GO)**; accounting independently verified (maxdiff 0.00000). BUT it's REBATE (arb-only −$0.12) |
| 7 | Short-side arb (sum_bid>1) | `MM_Q_AND_SHORTSIDE` | PARK — 0.005% of ticks net-of-fee; paper's "shorting bigger" is zero-fee/election-specific |
| 8 | Fresh trade-by-trade forensic | `B945_FORENSIC2` | NEW: he's **business-hours selective** (skips 67.6% of windows, near-zero overnight); edge GREW 6× |
| 9 | Tick-by-tick 10-slug timeline | `B945_TICK_TIMELINE` | Dip-buying REJECTED; (taxonomy + anti-dip later found ARTIFACTS) |
| 10 | Edge-gap decomposition (13-agent workflow) | `B945_EDGE_GAP_DECOMPOSE` | Edge = winner-leg queue priority; offline-addressable cents don't convert to PnL |
| 11 | Queue-priority-from-trades (workflow) | `B945_QUEUE_PRIORITY_FROM_TRADES` | **IN-FLIGHT (§H)** |

## E. THE 5 PRIOR CONCLUSIONS WE OVERTURNED THIS SESSION (the re-audit — `B945_SESSION_REAUDIT`)
1. **PnL ≠ +$15.7k / +$10k** → audited **+$21,742** (earlier numbers: stale balance / naive ERC20 netting broken
   by negRisk pUSD cycling). Use the REDEEM+REBATE−costs identity, NEVER raw transfer netting.
2. **"Early placement ~24h, cluster −23.5h"** → WRONG: pre-window activity clusters **−176s (3min)**; only 234
   trades >22h early across ALL markets; his fills uniform intra-window; early placement <5% of edge.
3. **"37% taker = pair-completion"** → WRONG: sum_asks ≥1.0 at every taker fill (0/27,039 below 1.0); the gate
   never fires; taker is overhead at sum≥1, NOT edge. Edge is maker-only.
4. **"Flow capture 7% vs 28.5% = 4× moat"** → overstated 2.5×: true matched = 11.5% him / 6.9% us = 1.65×; flow
   is accessible (~0% uncaptured), not an occupied niche.
5. **"Opens every window, time-of-day inert"** → WRONG: 32% engagement, strongly business-hours selective.
**Plus artifacts killed:** 4-leg taxonomy (open/add/rebal/hedge) is TAUTOLOGICAL (leading-side buy = 50.9%
coin flip); "anti-dip" was a flat-move counting bug (corrected: mild dip-buying 0.561@30s). **Root cause of
errors: believing article claims without checking the chain (articles = generic teaching menu, he uses a
subset) + denominator/population mismatches.**

## F. THE ARTICLES + ACADEMIC PAPER
- Three b945 articles (infra guide / "what this bot is" / regime filtering) analyzed (`B945_ARTICLE_INFRA_GAP_ANALYSIS`):
  GENUINE but GENERIC teaching — they describe the full MM toolkit (splits, naked sells, mid-window merge, 24h
  placement, 100-300 WS conns, sub-second speed); the chain proves he uses only a SUBSET. Don't take article
  claims as his spec.
- arXiv 2508.03474 ("Unravelling the Probabilistic Forest") (`ARB_PAPER_2508_03474_NOTES`): our sum<1 math =
  their Market-Rebalancing-Arbitrage; $39.6M extracted platform-wide (mostly uncaptured); maker-capture invisible
  to their taker-only taxonomy (his niche less-studied); "shorting more profitable" = zero-fee/election-specific
  (our short-side scan confirmed it's dead in fee-bearing crypto 15m).
- Avellaneda-Stoikov primer (`AVELLANEDA_STOIKOV_FOR_LADDER`): formal theory of his inventory skew + spread; the
  binary 15m market gives AS's hardest parameter (session T) for free; GLT inventory bound = his soft cap. AS is
  a Phase-B refinement, NOT the deployment unblocker (queue position is).

## G. TVRUST BUILD SPEC (`TV_AGENT_SPEC_RUST_LADDER_B945_2026_06_13` — TV agent implementing)
Self-contained spec for the Rust engine to PAPER-fire the ladder, observe, then stage to live. Corrected
config (post-re-audit): **MAKER-ONLY** (drop taker-completion — never fires); **place at window open, NOT 24h
early**; **GLT cap Q≈3–5 (not 20)**; **the moat is dense competitive pricing + queue priority, NOT speed**
(latency tested flat — do not build a sub-ms arms race); flow-capture target **~11.5%** (his level, not 28.5%);
**gate on net_pnl/slug AND pair_frac, NOT pvs alone** (cheaper pvs can still bleed). Build order: data-quality
feed layer (racer/dedup/warmup) + trade-feed-for-flow-metric → static ladder loop `poly_ladder.rs` → telemetry
(flow_capture + pvs headline) → zero-balance dry run → small capital. Promotion gate: **≥~12% live flow capture
+ positive net on a THIN-flow week**, multiple weeks, healthy %-positive. Insertion map: `TVRUST_LADDER_INSERTION_MAP_2026_06_12`.

## H. RESOLVED — queue-priority-from-trades (`B945_QUEUE_PRIORITY_FROM_TRADES_2026_06_13`)
Operator's pushback was CORRECT on measurement: the trade tape IS the consumption process and capture-rate
substitutes for exact resting-order rank. So I retract "unmodellable offline" — it was too strong about
MEASUREMENT (correct about EDGE-TRANSFER). Findings:
- **His MEASURED realized queue capture = 0.1375 raw / 0.122 $-wtd** (~12–14% of taker-sell flow at his levels).
  K_eff = 7.27 (≈7 b945-sized maker slots already at his levels). **Winner-leg capture 0.121 < loser-leg 0.157**
  — he captures LESS winner-side flow; his edge is cheap EARLY price via time-priority, NOT more flow-share.
  Capture declines through the window (0.150→0.094). **36% of his fills are off-tape / below the best bid** = the
  queue-priority moat unreachable by a new entrant or the lossy tape.
- **REPLACE (we get his capture): +$6.89/slug — REJECTED as an ARTIFACT.** Verify phase caught it: does NOT
  reconcile to his own realized +$2.75 gt_pnl on the same 1,333 slugs (claims 2.5× his PnL at ½ his volume,
  market-avg pvs 0.999 vs his 0.970), residual +$2.85 is a winner-heavy fill-model quirk vs his real −$19.44,
  median −$1.01, win-rate 45.5%, CI [−1.05,+14.69] straddles 0, top-5 slugs = 54% of profit, dies under any
  clip (CLIP$5 → −$0.14). Ground-truth reconciliation killed it.
- **COEXIST (honest new entrant, q=1/8 of flow): +$0.35/slug, CI [−0.10,+0.82], t=1.50 NS, win-rate 47.5%.**
  Every q from 1/8→1.0 has a NEGATIVE CI lower bound. And COEXIST is itself optimistic (inherits his cheap tape
  PRICES, only haircuts volume). Breakeven at best.
- **Per-slug correction:** "+$10.65/slug" = lifetime $21,742 ÷ 2,041 (full settled set). His mapped-ledger
  modellable economics ≈ +$4.08 gt_pnl + ~$2.3 rebate (mapped-subset number — understates like the PnL-audit
  coverage gap). Either way his modellable per-slug is single-digit $; ours is breakeven.
- **VERDICT UNCHANGED: DO NOT deploy offline.** Capture is measurable (~12–14%) but the edge doesn't transfer —
  the profitable part is the 36% below-bid early-time-priority fills, reachable only by real CLOB queue priority,
  not by the taker tape or a new entrant. The single decisive number no backtest can produce = our LIVE capture
  rate. NEXT: a live early-GTC capture probe (~30 slugs, ~$25) to confirm capture ≥12% before any TVRUST build.

## I. THE VERDICT (as of write time, pending §H)
His deployable edge = **winner-leg queue priority via below-best-bid resting fills**, fundamentally a live-CLOB
time-priority property. Offline replicas reproduce his IN-SAMPLE economics but the OOS/deployable edge needs real
queue position. Our best offline result is **breakeven-arb + rebate** (+$0.39/slug, all rebate). **The rebate
rate (assumed 0.0015/sh) is UNVALIDATED — it must be checked on a live Polymarket account; it's the single number
that decides offline viability.** Deploy verdict: **NO offline-only deploy; the live early/competitive-placement
paper probe (TVRUST) is the only remaining arbiter** — UNLESS §H shows calibrated capture flips it positive.

## J. DATA / SCRIPT ASSETS (all under strategy_lab/wallet_hunt/)
- His data: `cache/0xb945945d/{fill_tape_full.parquet (144,589 fills), ml_features.parquet (per-fill book+RTDS),
  per_slug_paired_ledger.parquet, tx_taxonomy.parquet (157k on-chain), merge_timing.parquet, orderfilled_sample*.parquet}`
  + `cache/_pm_portfolio/0xb945945d/activity_{TRADE,REDEEM,MAKER_REBATE}_2026_06_13.json` (fresh).
- Engines/sims: `_mm_inv_engine.py` (validated maker-only, GLT+AS), `_mm_queue_engine.py` (FIFO/prop queue replay),
  `_mm_hybrid_engine.py` (+taker, taker layer dead), `_mm_q_sweep.py`+`_mm_q_verify.py` (Q sweep, accounting-verified),
  `_mm_shortside_scan.py`. Forensics: `_b945_forensic2_*.py`, `_b945_tick_timeline.py`, `_b945_tx_decode.py`,
  `_b945_pnl_audit.py`, `_b945_merge_verify.py`.
- Result parquets: `cache/_mm_q{2,3,5,8,12,16,20}_full.parquet`, `_mm_q_sweep_summary.parquet`, `_mm_q_verify.parquet`,
  `_mm_hybrid_best_full.parquet`, `_mm_shortside_scan.parquet`, `_mm_engine_results.parquet`, `_mm_latency_sweep.parquet`.
- Canonical (read-only): `data/v4/canonical/trades_polymarket/btc.parquet` (44.7M taker prints = queue tape),
  `orderbook_l25/btc.parquet` (10Hz snapshots). NO order-by-order deltas in the production window.

## K. SECONDARY WALLET — ce25 (parked, separate)
`0xce25e214` (+$300k LB, taker pair-arb + resolution hold). Sign-flip resolved (legacy −$295k decode dropped
REDEEM income). Chain-true PnL never computed (Alchemy pull died on disk-full ×2). Snapshot sum-arb dead for it
too (sum_ask never <1). `WALLET_CE25E214_DECODE`, `CE25_LEGGING_DECODE`. PARKED.

## L. NEXT ACTIONS (priority)
1. **Read the §H queue-priority-from-trades report** (in-flight) — it may flip the offline verdict.
2. **Validate the maker rebate rate** on a live Polymarket account (the single number that decides offline viability).
3. **TVRUST paper dry-run** with the corrected config (§G) — measure live flow capture vs ~12% gate, judge on
   net_pnl + pair_frac across multiple thin-flow weeks. This is the only arbiter of the live-queue edge.
4. Do NOT re-open: snapshot sum-arb, short-side, taker-completion, 24h-early-placement, sub-ms speed, 4-leg
   taxonomy, dip-timing — all tested DEAD/artifact this session.

## M. KEY RULES BANKED (memory: project_b945_thread_parked.md + MEMORY.md)
- Polymarket wallet PnL = REDEEM+REBATE−costs identity; NEVER raw ERC20 netting (negRisk pUSD cycling breaks it).
- Redeems pay full $1, no fee; NEVER apply the 0.07 taker-fee curve to maker or redeem legs (caused 4 fake-negative ledgers).
- Articles are generic teaching menus, not his spec — verify every claim against the chain.
- Match denominators before quoting any ratio (the 28.5% flow-capture error).
- For maker strategies: gate on net_pnl + pair_frac, NOT pvs alone (cheaper pvs can still bleed).
- Derived-label findings (the leg taxonomy) are tautological — re-derive independently before citing.
- GROUND-TRUTH RULE: this wallet overturned 5+ of our conclusions; trust raw fills/trades/audit over intuition.
