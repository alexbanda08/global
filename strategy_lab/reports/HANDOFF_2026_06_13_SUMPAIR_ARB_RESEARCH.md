# Session Handoff — 2026-06-13 — Sum-Pair Arbitrage: deep research, pre-registered backtest, verdict, shadow plan

**READ THIS FIRST.** Scope = ONLY the sum-pair / "market rebalancing" arbitrage research (buy Up+Down when the
ask-sum < $1, hold to resolution; one leg pays $1). Sources: arXiv **2508.03474** + 0xSurferX/Luoye "binary
hedging" articles. **Outcome: DEAD as a taker on our infra** (pre-registered backtest, every cell SIG-NEG); the
only unclosed door is sub-100ms resting-maker capture, addressed by a $0 observe-only shadow spec. Cross-validated
against the parallel `HANDOFF_2026_06_13_B945_FULL_DECODE_AND_EDGE.md` — they AGREE. GROUND-TRUTH RULE held.

---

## A. What the sources teach
- **arXiv 2508.03474 "Unravelling the Probabilistic Forest"** defines two arbitrage types:
  1. **Market Rebalancing (single market):** prices of mutually-exclusive outcomes should sum to $1; when the YES/NO
     **ask** sum < 1, buy both → one resolves $1 → keep `1 − sum`. Direction-agnostic. **This is our crypto Up/Down.**
  2. **Combinatorial (cross-market):** logically-dependent market pairs (e.g. "Trump wins" vs "GOP margin"). **N/A to
     us — our crypto markets are single-condition.** (The paper's ~$40M was mostly election multi-market, mostly
     uncaptured; fees were $0 in their window — not our regime.)
- **0xSurferX / Luoye "binary hedging" (the practitioner version):** NOT a clean simultaneous buy-both — a
  **sequential legging-in**: detect overreaction (one side crashes, e.g. Up 0.50→0.35, Down lags), buy the cheap leg
  (Leg 1), then complete the hedge `leg2Price = SUM_TARGET − leg1Price`; if Leg 2 fills → hold both to settlement
  (guaranteed $1); **if it doesn't → single-leg directional risk** managed by EARLY_TAKE_PROFIT / FLOOR_PRICE /
  LAST_MIN_STOP_LOSS. Their own listed risks: "no opportunity in calm markets," "single-leg exposure if Leg 2 never
  fills," "threshold trade-off." (X article bodies are login-gated; extracted via the Luoye Medium mirror + the
  trevorlasn explainer + WebSearch.)

## B. Prior internal evidence (all consistent, all negative — reanalyzed this session)
- **ce25 wallet** (taker buy-both-hold, +$300k LB): profitable on-chain BUT **97% of income is winner-leg resolution
  recovery; CLOB-only net was −$9,117** → it's a neutral two-sided book recovering via the $1 winner, **NOT pure
  sub-$1 capture.** Overround median sum_ask **1.041**; ~35% of slugs ever dip <1.0 (a vwap/time-aggregated figure,
  not instantaneous). DEPLOY-NO, pre-registered test was OWED.
- **b945 wallet** (maker paired ladders): queue-aware sim SIG-NEG every policy (adverse selection). Taker fixes the
  fill problem but inherits the overround + fees.
- **LEG2 study** (top-of-book): legs reprice in **−0.9 lockstep** → dips barely lockable.
- **Maker-arb censoring reversal:** the old maker "edge" was survivorship bias (losers never log a REDEEM). The
  taker hold-to-resolution version escapes THAT bug **only if you settle ALL gated slugs from chainlink**, never from
  the engine REDEEM log.

## C. ⭐ THE PRE-REGISTERED BACKTEST — `sumpair_arb_t1_2026_06_13.py`
Atomic taker buy-both-hold, fully causal:
- Per slug, scan native-10Hz L25; **causal first-cross** of `sum_ask < θ` anywhere in the window (NOT the min → no
  look-ahead). FILL at the first snapshot **≥ detect + 85ms** (our measured live latency). Walk **$25 on BOTH legs'
  asks** (real depth); require both fill ≥ $12.5 else skip.
- OUTCOME = **true chainlink resolution** (winner +$1, loser $0). FEE = **winner-only 0.07·p·(1−p)** on the winning
  leg, $0 on loser. Per-pair PnL = `1 − sum_ask_fill − 0.07·p_win·(1−p_win)`.
- Also a **no-latency "opt" fill** (at the detect instant) to isolate the latency haircut.
- θ ∈ {0.99, 0.98, 0.97, 0.96, 0.95}; BTC/ETH/SOL × 5m/15m; 1,400 slugs/cell; bootstrap CI.

**RESULT — DEAD. Every cell SIG-NEGATIVE on realistic latency:**

| θ | opt $/pair (instant) | **lat $/pair (85ms)** | latency haircut |
|---|---|---|---|
| 0.99 | −0.014 | **−0.070** [−0.072,−0.068] | +0.056 |
| 0.98 | −0.004 | **−0.075** [−0.077,−0.072] | +0.070 |
| 0.97 | +0.004 | **−0.078** [−0.082,−0.075] | +0.083 |
| 0.96 | +0.017 | **−0.083** [−0.088,−0.078] | +0.100 |
| 0.95 | +0.029 | **−0.082** [−0.088,−0.076] | +0.111 |

Per coin (θ=0.97, lat): BTC −0.044/−0.055 (5m/15m), ETH −0.076/−0.069, SOL −0.112/−0.091 (SOL thinnest = worst).

**Mechanism:** the arb math is real (`opt` turns positive below 0.97) but **the dip is a single-snapshot (<100ms)
transient.** At 10Hz, "fill 85ms later" = the next snapshot, by which the book has reverted to the ~1.01 overround.
You detect sum<0.97 but fill at ~1.01 → pay the overround → lose 5–11¢/pair. **Deeper dip = faster revert** (haircut
+0.056→+0.111). This is the non-atomic execution risk the paper warns about, quantified.

**Overround reality (data-feasibility probe):** the book sits at sum_ask ≈ **1.01 essentially always** (median 1.01,
p5 = 1.00). Only 2–5% of snapshots < 1.0, 0.2–3.4% < 0.97. Per-slug MIN does dip (median ~0.96–0.97) but **mid-window
(+152s/5m, +398s/15m), not at open**, and production L25 is even tighter (only 24–36% of slugs dip <1.0).

## D. CROSS-VALIDATION vs the b945 handoff (`CROSSVAL_SUMPAIR_B945_2026_06_13.md`)
Compared to `HANDOFF_2026_06_13_B945_FULL_DECODE_AND_EDGE.md` + its `SUMARB_PREREG_BT_2026_06_12.md`.
- **AGREE on every deploy conclusion.** Magnitudes match across independent engines: their ungated −$8 to −$14/slug
  at $140 deployed ≈ **−0.06 to −0.10/pair** ↔ my **−0.070/pair**. Identical winner-only fee (their §F arithmetic =
  mine). No-censoring confirmed both sides.
- **The one apparent contradiction RESOLVED.** Their report said "sum_ask never <1, 0 opportunities in 134,877
  evals." But they only checked **3 fixed offsets (+5/+30/+60s, all first-minute)**; my full-window scan shows the
  dips occur **mid-window (+152s/+398s)** → their test fired *before* the dips happen. Plus size ($70 vs $25/leg) and
  asof-staleness explain the rest. **Correction to bank:** the handoff's §D #1 "sum never <1" should read *"never <1
  at the fire offsets; mid-window transients exist (~2–5%, per-slug min ~0.96) but are latency-uncapturable as a
  taker and partly asof-stale-quote artifacts."* This nuance KEEPS the maker-capture question open.
- **Their decode adds (complementary, no conflict):** b945 is a two-sided **maker**, +$21,742 audited, edge =
  **winner-leg queue priority** (33.4% of fills below the contemporaneous best bid = resting time-priority), NOT
  sub-$1 snapshot capture. Their best offline maker replica = **+$0.39/slug = ALL rebate; the arb itself −$0.12/slug**
  (breakeven-negative). The **maker rebate rate (assumed 0.0015/sh) is the single unvalidated number** deciding
  offline viability.

## E. VERDICT
- **Taker sum-pair arb: DEAD** — confirmed twice, two engines, consistent magnitude (−5 to −11¢/pair). The overround
  is the fee; dips are mid-window, sub-100ms, latency-uncapturable. **Do not deploy.**
- **Maker sum-pair (b945-style): NOT deployable offline** — breakeven-arb + unvalidated rebate; the real edge is
  live winner-leg queue priority. Strong negative prior, one open door.
- **Combinatorial arb: N/A** to single-condition crypto.

## F. SHADOW TEST PLAN — `sum_pair_monitor_v1` (the only sanctioned next step)
Specs: `SUMPAIR_ARB_VERDICT_AND_SHADOW_PLAN_2026_06_13.md` (plan) + `TV_AGENT_SPEC_SUMPAIR_MONITOR_2026_06_13.md`
(implementable). **Observe-only, $0, places ZERO real orders.** Purpose = resolve what 10Hz history can't (no
order-by-order deltas in the production window):
- **M1 dip recorder:** on every live WS update, log every tick `ask_up+ask_dn < 1.0` → onset, **duration_ms**,
  min_sum, depth, revert_ms (the true sub-100ms shape).
- **M2 virtual taker control:** simulate buy-both filled at detect +{50,85,150}ms → confirm the −5¢ death LIVE.
- **M3 virtual resting-maker (the open question):** rest a virtual limit bid per leg at `p_up+p_dn=0.965`; mark filled
  when the live best ask crosses ≤ your bid (FIFO lower bound); require both legs in 20s, else single-leg w/ floor/stop.
- **Settle** to chainlink resolution, winner-only fee, dedup metric.
- **Promotion to $1 live maker** only if M3: both-legs-fill ≥30%, net $/pair CI>0, ex-top2 robust, single-leg residual
  not net-negative, over ≥4wk/≥200 episodes. Else **file sum-pair FULLY DEAD** (taker proven, maker refuted live).
Engines reused: production Tier-1 `ws_mirror` (dual-token subscribe) · `engine_v2.book_walk_fill`+`LiveMimicConfig` ·
NEW best_ask≤resting_bid crossing detector · `load_resolutions` · Kalshi `status=unopened` pre-subscribe · dedup metric.

## G. ⚠️ OPEN / FLAGGED
- ~~The b945 §H workflow report does NOT exist on disk~~ **RESOLVED 2026-06-13 (cross-session): the workflow
  COMPLETED and `B945_QUEUE_PRIORITY_FROM_TRADES_2026_06_13.md` now exists. It did NOT flip the maker verdict.**
  Findings (the offline analog of M3): b945's MEASURED realized per-level queue capture = **0.1375 raw / 0.122
  $-wtd (~12–14% of taker-sell flow)**; winner-leg capture (0.121) < loser-leg (0.157) → edge is cheap EARLY
  price via time-priority, NOT more flow-share; **36% of his fills are off-tape / below the best bid = the
  unreachable moat.** Plugging measured capture into our economics: **REPLACE** (we get his capture) = +$6.89/slug
  but REJECTED as an artifact (fails ground-truth reconciliation to his own +$2.75 gt_pnl; median −$1.01; dies
  under any clip); **COEXIST** (honest new entrant, q=1/8) = **+$0.35/slug, CI [−0.10,+0.82], t=1.50 NS** — every
  flow-share assumption has a NEGATIVE CI lower bound, and COEXIST is itself optimistic (inherits his cheap tape
  prices). **Offline maker verdict UNCHANGED: breakeven-at-best; the profitable part (36% below-bid) is reachable
  only by real live time-priority. The trade tape CAN measure capture (operator was right; "unmodellable" retracted
  re measurement) but the edge does NOT transfer offline.** → §F M3 (live observe-only) is now the SOLE arbiter.
- **Rebate rate** (0.0015/sh assumed) — validate on a live Polymarket account before any maker viability claim.

## H. ARTIFACTS (this research)
- **Backtest:** `strategy_lab/directional/sumpair_arb_t1_2026_06_13.py` + `_results/sumpair_arb_t1_2026_06_13.{parquet,log}`
- **Reports:** `SUMPAIR_ARB_VERDICT_AND_SHADOW_PLAN_2026_06_13.md`, `TV_AGENT_SPEC_SUMPAIR_MONITOR_2026_06_13.md`,
  `CROSSVAL_SUMPAIR_B945_2026_06_13.md`, this handoff.
- **Source paper (local):** `Downloads/2508.03474v1.md`.
- **Cross-ref (prior/parallel):** `HANDOFF_2026_06_13_B945_FULL_DECODE_AND_EDGE.md`, `SUMARB_PREREG_BT_2026_06_12.md`,
  `WALLET_CE25E214_DECODE_2026_06_12.md`, `LEG2_REPRICING_STUDY_2026_05_29.md`,
  `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`, `ARB_PAPER_2508_03474_NOTES_2026_06_12.md`.
- **Memory:** `project_sumpair_arb_dead`.

## I. NEXT ACTIONS (priority) — UPDATED 2026-06-13 (queue-priority workflow now DONE, §G)
1. ~~Re-run the queue-priority workflow~~ **DONE — did NOT flip the maker verdict (offline breakeven-at-best; §G).
   Offline is now FULLY EXHAUSTED on both taker and maker.**
2. **Stand up `sum_pair_monitor_v1`** ($0 observe-only) per `TV_AGENT_SPEC_SUMPAIR_MONITOR_2026_06_13.md` — NOW
   the #1 action and the SOLE remaining arbiter of the maker-capture edge. M3 (virtual resting-maker, FIFO-lower-
   bound crossing detector) is the live observe-only analog of the offline COEXIST test (which came back breakeven);
   it measures the sub-100ms dip shape + below-bid capture that 10Hz history cannot. $0, no creds-with-balance, can
   run immediately. **This SUPERSEDES the b945 handoff's "small-capital probe" as the first live step** (cheaper, safer).
3. **Validate the live maker rebate rate** (0.0015/sh assumed — the single number deciding maker offline viability;
   the offline maker "positive" is ENTIRELY rebate).
4. Only if M3 passes its promotion gate (both-legs-fill ≥30%, net/pair CI>0, ex-top2 robust, single-leg residual
   not net-negative, ≥4wk/≥200 episodes) → proceed to the TVRUST `tv-strat-ladder` build (`TV_AGENT_SPEC_RUST_LADDER_B945_2026_06_13.md`,
   corrected config: maker-only, Q≈3–5, place-at-open, gate on net_pnl+pair_frac not pvs). Else file sum-pair FULLY DEAD.
5. Do NOT re-open: taker snapshot sum-arb (DEAD, latency-killed), taker sequential-legging (LEG2 −0.9 lockstep =
   dips unlockable + single-leg risk), combinatorial arb on crypto (N/A), short-side sum>1 (dead in fee-bearing crypto).

## J. RULES BANKED
- Sum-pair fee = **winner-only 0.07·p·(1−p)** on the winning leg only, $0 on loser, fee-free redeem. Settle ALL
  gated slugs from **chainlink** (never engine-redeem = the censoring trap).
- The **overround (~1.01 ask-sum) IS the fee**; dips are **mid-window, sub-100ms, latency-uncapturable as a taker**.
- A "sum<1" measured by asof-ffill can be a **stale-quote artifact**; same-instant snapshots find ~0 at fire offsets.
  Real lockable transients can't be confirmed from 10Hz (no order-by-order deltas) → live WS probe only.
- "0 opportunities" claims are sampling-dependent — check the **whole window** (dips are mid-window), not fixed offsets.
- GROUND-TRUTH RULE: ce25's profit is resolution-recovery not arb; b945's is queue priority not snapshot capture;
  trust raw fills / chainlink / the dedup metric over article claims and aggregate intuition.
```
