# Session Handoff — 2026-06-12→16 — 5-lens audit, 1s-lookahead fix, capacity, sum-pair full close, OFI, TVRUST gap-check

**READ THIS FIRST.** Long multi-thread session. Headline: found+fixed a ~1s lookahead in every scalp driver
(backtest was ~41% inflated; live unaffected); mapped scalp deploy capacity per market; **fully closed the
sum-pair / b945 arbitrage campaign offline** (taker DEAD, short-side DEAD, V2 oscillation-harvest = the one
real thin edge, depth-realism done); tested + killed the OFI gate; audited TVRUST vs the new 0xSurferX article.
GROUND-TRUTH RULE held — I corrected my own auditors twice. Committed + pushed to GitHub (Lazer key scrubbed).

---

## A. DONE this session (with verdicts)

1. **Pyth Lazer probe + collector spec** (`pyth_lazer/probe_lazer.py`, `COLLECTOR_SPEC.md`). `real_time` channel
   REACHABLE on the operator's key, **~50ms cadence**; `fixed_rate@1ms` is a docs phantom (server rejects). The
   2.9s "latency" was local clock skew. **NOT yet ported to a storedata collector.** Signal feed only (Chainlink
   stays settlement truth).

2. **Synthetic-book fill ("6 edges" technique-2: buy YES = sell NO)** (`scalp_synth_book_2026_06_12.py`). No-arb
   proves itself (ev_A−ev_B = +0.0000 on 1305 fills) → zero price improvement on fillable books; only value =
   ~23 rescued fires (+$5.95/pair) ≈ **$6/day**. NOT deployed; `engine_v2` untouched. Memory: `project_synthetic_book_marginal`.

3. **5-LENS STRATEGY AUDIT** (`STRATEGY_AUDIT_5LENS_2026_06_12.md`, 5 opus agents). Findings: the **1s-lookahead
   bug** (→ §A4); **momalign "OOS" is a tail-split of the search window** (not disjoint); **cloud_vwap_hurstmp_v7
   fails Bonferroni** at N=25 and N=155 (t=2.32) = hypothesis not validated; **dead maker-exit STILL on the live
   $1 sleeve**; missed-edge ranking. (My auditors OVERSTATED the fee-inflation — corrected; the hold fee is
   winner-only and already right.) Memory: `project_5lens_audit_2026_06_12`.

4. **⭐ 1s SIGNAL LOOKAHEAD — found, FIXED, re-validated.** Every scalp driver's local `asof` searchsorted the
   bar-START (`time_period_start_us`) → the 5s-return numerator close landed ~0.9s AFTER the fire. Paired
   causal-vs-leaky one-shot (`scalp_causal_asof_oneshot_2026_06_12.py`): pooled gated **+1.71→+1.01/tr (−41%)**,
   but causal still CI>0. **FIXED (end-time asof)** in `scalp_oos_bbo_fixed_2026_06_10.py`, `scalp_gate_soften_2026_06_11.py`,
   `scalp_synth_book`; marked `scalp_oos_bbo_2026_06_05.py` ⛔SUPERSEDED. Corrected-causal OOS rerun:
   **pooled gated ALL +0.91/tr (t=2.62) / CLEAN +1.47/tr (t=5.67)**, both CI>0; ETH/SOL/XRP/BNB solid, **BTC weak,
   DOGE dead**; **STOP still SIG-NEG; TOD 22-02 boost holds.** Live was never affected (production anchors causally).

5. **SCALP CAPACITY PROSPECT per market** (`SCALP_CAPACITY_PROSPECT_2026_06_13.md`, `scalp_capacity_prospect_2026_06_13.py`).
   Production L25 depth walk. **Entry asks absorb $800+; the +60s EXIT is the binding constraint.** Ceilings: BTC5m
   $800/BTC15m $300/ETH5m $200/ETH15m $150/SOL $50. Prospect (OOS-anchored ×0.35): **~$2,875/month, ~$650 capital/fire
   (~$1.5–2k working capital), MaxDD ~$2–2.5k**, BTC-5m = ~44% of profit. Not scalable without an exit upgrade.

6. **⭐ SUM-PAIR / b945 ARBITRAGE CAMPAIGN — fully closed offline** (sources: arXiv 2508.03474 + 0xSurferX/Luoye).
   - **Taker buy-both-hold: DEAD** (`sumpair_arb_t1_2026_06_13.py`) — −5 to −11¢/pair SIG-NEG; dip is a sub-100ms
     transient that reverts before the 85ms order lands → you pay the ~1.01 overround. `SUMPAIR_ARB_VERDICT_AND_SHADOW_PLAN`.
   - **Short-side (sum_bid>1, split+sell-both): DEAD** (`sumpair_short_t3_2026_06_16.py`) — latency-confirmed all 6
     markets (pooled θ1.035 −0.098); doubly dead (rare + uncapturable + double taker fee). Extends the prior btc-15m PARK.
   - **V2 oscillation-harvest = the ONE real (thin) edge** — buy each side at its own causal lag-dip, accumulate,
     pair-hold + **scalp the residual** (`_sumpair_v2_depth_realism.py` finished this session, `SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md`).
     Real L25 depth ~9 clips/snapshot (multi-clip NOT a refill artifact). Deployable: **BTC/ETH 5m, scalp-residual,
     1-clip floor +$0.40/slug (CI>0) → +$1.77 multi-clip; SOL dropped (straddles 0).** Hold-residual has higher mean
     but median −$5 (untradeable); scalp-residual median −$0.35. TV spec ready + reconciled (`TV_AGENT_SPEC_SUMPAIR_OSC_HARVEST_2026_06_14.md`).
   - **Cross-validation with the parallel b945 decode** (`CROSSVAL_SUMPAIR_B945_2026_06_13.md`): AGREE on all deploy
     conclusions; reconciled the "0 opportunities" contradiction (they checked fixed offsets, dips are mid-window).
   - Memory: `project_sumpair_arb_dead` (all variants logged).

7. **OFI GATE on the scalp: DEAD** (`scalp_ofi_gate_2026_06_16.py`, `SCALP_OFI_GATE_RESULT_2026_06_16.md`). Tested
   gating on Binance 1s taker-order-flow-imbalance (`taker_buy_base`, never extracted before). No dose-response;
   gating LOWERS $/tr (+2.23→+1.12). **Key insight: the scalp edge is INVERSELY related to flow intensity** — thin
   low-volume moves leave the book lagging more (the lag the scalp captures). Don't gate the scalp on flow/CVD/
   aggressor signals. Memory: `project_scalp_ofi_gate_dead`.

8. **TVRUST vs new 0xSurferX article gap-check** (`TVRUST/docs/ARTICLE_2066506_GAP_CHECK_2026_06_16.md`). Article
   login-gated (same author/$21k thesis). Found 2 real TVRUST ladder mistakes (A1 `glt_cap_q=20` vs re-audit Q≈5;
   A2 taker-completion gate active vs MAKER-ONLY design → distorts the paper measurement) + 1 doc drift; structural
   gaps for live (EV-grid, real order path, **pUSD pre-funding loop — entirely missing**). Deliberately do NOT build
   the article's WS-racer moat (our re-audit: speed flat). **Fixes flagged, NOT applied.**

9. **Committed + pushed to GitHub** (`8258e90`): scrubbed a hardcoded Pyth Lazer key from 3 files (never in
   history — clean), gitignored `graphify-out/` (158MB), deleted junk (`nul`/`5s`/`fire_offset_s`).

---

## B. NOT FINISHED / OPEN (priority order)

**Quick offline/code (next session can knock out):**
1. **TVRUST ladder A1/A2/A3 fixes** — `glt_cap_q` 20→5, disable `run_taker_completion`, align the flow-capture doc
   (~12% not 20%). `crates/tv-engine/src/loops/poly_ladder.rs`. Stage-0 numbers untrustworthy until done. (Offered, not applied — TVRUST is operator-managed, no-push rule.)
2. **Finish the 1s-lookahead patch** — only the 3 main scalp drivers fixed. Grep `time_period_start_us` + local
   `asof` across `strategy_lab/directional/*` (microprice_scalp, maker_sim, trailing drivers) and fix to end-time.

**Live / operator-side (the real next moves):**
3. **Deploy the V2 `sum_pair_osc_harvest` $0 shadow** (BTC/ETH 5m, 1-clip, scalp-residual) — settles the one
   offline-unanswerable Q: inter-fire liquidity regeneration. Spec ready.
4. **Deploy `sum_pair_monitor` $0 shadow** (maker-capture question for the taker-dead arb) — spec ready.
5. **Apply the idle TV specs** (5-lens): cloud_vwap_v7 deploy + coinflip filter; maker-exit-disable on 15m sleeves.
6. **Host-side verify:** the 76 KILL sleeves are actually disabled + the Ireland 106-row resolution-dup bug — both
   unverifiable from this repo, both corrupt live PnL if unfixed.
7. **Validate the live maker rebate rate** (0.0015/sh assumed) — the single number deciding b945-ladder offline viability.

**Bigger / upside:**
8. **HL perps** — ETH-4h Donchian (OOS Sharpe 3.32) + D1 basis-carry in shadow; promotion gate ~early July.
9. **Poly×Kalshi deep-dip arb** — validated signal+depth (+2.7¢/set); blocker = build the dual-venue order executor.
10. Port the Pyth Lazer collector to storedata (§A1).

**Flagged data/process items:**
- The b945 **§H `B945_QUEUE_PRIORITY_FROM_TRADES_2026_06_13.md` report is MISSING on disk** (workflow didn't land) —
  it's the offline arbiter of the maker queue-capture edge; re-run it.
- T2 (feed-completeness as lever) is technically open but **low value** — the T1 feed-loss audit corrected to
  "feed ~92-96% faithful" (`L25_FEED_GAP_DIAGNOSIS_2026_06_16.md`), so the racer's offline justification was withdrawn.

---

## C. WHAT'S DEAD — do NOT re-open
Taker sum-pair snapshot arb · short-side sum_bid>1 · OFI/flow gate on the scalp · synthetic-book for the taker scalp ·
the leaky bar-START asof (fixed) · STOP/TP on the scalp · combinatorial arb on crypto (single-condition, N/A) ·
mid-window/FVG/cross-asset scalp variants · maker-entry · 24h-early placement · sub-ms speed arms race · mid-window merge.

## D. STILL ALIVE / VALIDATED
The **+60s lag-scalp** (causal OOS +0.9–1.5/tr, deployed live; ETH/SOL/XRP/BNB best, BTC marginal, DOGE dead) ·
the **V2 oscillation-harvest** (BTC/ETH 5m, scalp-residual, +0.40 floor — live-shadow next) · HL Donchian/basis-carry
(shadow) · Poly×Kalshi dip-arb (validated, unbuilt). Economics banked: winner-only 0.07 fee, no-split, Q≈4 inventory
control, GROUND-TRUTH RULE (trust live wallet / dedup metric, never raw backtest magnitude).

## E. KEY FILE POINTERS (this session)
Reports: `STRATEGY_AUDIT_5LENS_2026_06_12.md`, `SCALP_CAPACITY_PROSPECT_2026_06_13.md`,
`SUMPAIR_ARB_VERDICT_AND_SHADOW_PLAN_2026_06_13.md`, `SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md`,
`CROSSVAL_SUMPAIR_B945_2026_06_13.md`, `SCALP_OFI_GATE_RESULT_2026_06_16.md`,
`TV_AGENT_SPEC_SUMPAIR_{MONITOR,OSC_HARVEST}_*.md`, `TVRUST/docs/ARTICLE_2066506_GAP_CHECK_2026_06_16.md`,
`HANDOFF_2026_06_13_SUMPAIR_ARB_RESEARCH.md` (sum-pair-scoped).
Scripts (`strategy_lab/directional/`): `scalp_causal_asof_oneshot_2026_06_12.py`, `scalp_capacity_prospect_2026_06_13.py`,
`sumpair_arb_t1_2026_06_13.py`, `_sumpair_v2_depth_realism.py`, `sumpair_short_t3_2026_06_16.py`,
`scalp_ofi_gate_2026_06_16.py`, `scalp_synth_book_2026_06_12.py`. Lazer: `pyth_lazer/`.
Memory: `project_5lens_audit_2026_06_12`, `project_sumpair_arb_dead`, `project_scalp_ofi_gate_dead`,
`project_synthetic_book_marginal` (+ index in MEMORY.md).
