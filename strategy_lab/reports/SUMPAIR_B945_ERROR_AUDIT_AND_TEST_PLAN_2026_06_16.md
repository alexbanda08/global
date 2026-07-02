# b945 / sum-pair campaign — error audit + test plan vs the 0xSurferX infra article
**2026-06-16.** Trigger: new 0xSurferX X-Article *"I'm 21. My bot hit $21k PnL today. Here's how i built what 99% can't repeat."* (same author as wallet `0xb945945d`, +$21,742 audited). The body is login-gated; this audit works from the article's confirmed thesis (title + preview + the author's **prior** article, fully analyzed in `B945_ARTICLE_INFRA_GAP_ANALYSIS_2026_06_12.md`) cross-checked against everything we measured. **If the full body later reveals new numbers, re-open §3.**

The article's thesis (consistent across both his pieces): **"your bot is not broken; the strategy logic is the easy 1%; the moat is the infrastructure — the data-freshness race, being first to KNOW the book changed. 99% can't repeat it because they lack the infra, not the logic."**

---

## 1. The central contradiction the article forces

We hold two of our own conclusions that disagree, both citing b945:

| Doc | Claim |
|---|---|
| `B945_ARTICLE_INFRA_GAP_ANALYSIS` (06-12) | Moat = infra / data-freshness / WS-racing / queue-priority / early placement. **Build the racer.** |
| `TV_AGENT_SPEC_RUST_LADDER` §0 + `B945_SESSION_REAUDIT` (06-13) | **"SPEED IS FLAT"** (we swept requote latency 0ms→2s, flow-capture + PnL flat); early placement explains **<5%**; queue-priority is **NOT** the lever; moat = dense maker pricing + inventory discipline. **Racer = Stage-0.5/optional.** |

The new article sides **hard** with 06-12. So one of our docs is wrong. Resolving this is the whole point of this audit, because it decides whether the infra build (the user's Part B) is worth doing.

---

## 2. ERROR AUDIT — what we (probably) did wrong

### 🔴 Finding #1 — "speed is flat / queue-priority doesn't matter" is an OFFLINE ARTIFACT. We varied the wrong variable.
The 06-13 latency sweep varied **our reaction time** (0ms→2s) against a **fixed, single-connection 10 Hz L25 tape**. But the article's edge is **not reacting faster to the same ticks** — it is **seeing ticks our one collector never captured**. 100–300 deduped connections catch every book change; a 10 Hz snapshot drops the sub-100 ms churn in which **new price levels appear and are consumed**. Sweeping reaction-latency on a lossy tape is **structurally incapable** of detecting a feed-completeness edge. A flat result there is a **null from an underpowered instrument, not evidence of absence.**

Corollary on "early placement <5%": we measured that via b945's **pre-window FILLS** (he has ~zero). But early placement's value is **FIFO queue position when intra-window flow arrives**, not pre-window fills. Our own sim measured the symptom and then dismissed it: join-at-+60s → **29% pair fraction vs his 44%**. That 15 pp gap *is* the queue-position effect.

**Verdict: the infra-moat question is UNRESOLVED. It is resolvable only with the instrument we never built (the N-conn racer + per-hop latency tape + our own tick tape). The 06-13 re-audit was right about economics and wrong to close the infra question.**

### 🔴 Finding #2 — ⚠️ LARGELY WITHDRAWN 2026-06-16 (see §3b correction + `L25_FEED_GAP_DIAGNOSIS_2026_06_16.md`).
> Direct measurement (corrected join) shows the canonical L25 is **~92–96% faithful on fills** (steady-state
> loss ~4% ct / ~8% vol), and the collector is on **VPS3** (not VPS2) doing **dedup-on-change ~1 Hz**. The
> "data-resolution ceiling blinds us to the edge" claim is **not supported** — the feed is mostly faithful.
> The one real (minor) item: it's **~1 Hz dedup-on-change, not 10 Hz** (cadence label was wrong), and the
> deep-book (>level 25) tail (~few %) is truncated. Original (overstated) text kept below.

Our entire fill model = canonical L25 **10 Hz** snapshots from **one** VPS2 collector. If the edge lives in sub-100 ms book churn, our tape cannot see it. This is not a bug — it is a **data-resolution ceiling** that caps the trustworthiness of *all four* of these verdicts:
- "maker DEAD / 0% conservative fills" — our FIFO joins behind 60–560 resting shares **at existing levels**; b945's fills come from being **first at NEW levels (zero queue)**, a state our sim **cannot represent**. So "0% maker fills" is a property of our queue assumption, not a measured truth.
- sum-pair "DEAD as taker" (dip reverts <100 ms before our 85 ms order lands) — measured on the same lossy tape.
- V2 oscillation-harvest +$0.52/slug floor — a Binance-lag signal edge (ours, distinct), still fill-modelled on the slow tape.
- the ladder NO-GO (29% vs 44% pair fraction).

### 🟠 Finding #3 — we never measured our own latency.
We have used **85 ms** as a single assumed fill latency *everywhere*. The article's #1 practice is **recording your own per-hop latency**. We have **no** recv→decision→submit→ack→fill distribution from the Ireland box. Every latency-sensitive conclusion rests on one unmeasured constant.

### 🟠 Finding #4 — effort allocation inverted.
~7 offline replication variants + a **31 h offline depth-realism hang** — all refining a fill model the article says is unknowable offline. **Zero of the 5 moat layers built.** Article: logic = 1%, infra = 99%. We spent the budget on the 1%.

### 🟡 Finding #5 — "CPU pinning: speed flat → deferred" was measured in the wrong regime.
We deferred pinning citing "speed flat." But that was a paper context with no WS-racing load and no contention with the live Python TV on the same box. The article's pinning argument is about **contention under 100–300 connections beside another live process** — a regime we never measured. Re-open once the racer + latency tape exist.

### ✅ What we got RIGHT (keep — do NOT re-litigate)
- **Economics is the orthogonal truth:** inventory discipline is the profit lever — GLT cap **Q≈3–5** (OOS-monotone in Q), AS reservation skew **γ=0.05**, residual drag is the enemy. Independent of the feed race; survives.
- **Fee model:** winner-only `0.07·p·(1−p)`; $0 on maker + redeem; rebates are income. Chain-verified. (Applying taker fees to maker/redeem legs produced 4 fake-negative ledgers — never repeat.)
- **No split/mint; post-resolution merge only** — chain-verified (zero `splitPosition` txs; 1,307 `mergePositions` all post-resolution).
- **Taker-completion never fires below sum 1.0** (0/27,039) — verified; keep it MAKER-ONLY.
- **PnL +$21,742** reconciled to the leaderboard API.
- **The V2 oscillation-harvest is OUR edge** (Binance→Poly lag), **distinct** from b945's passive-maker edge — do not conflate them; they share infra but not signal.

---

## 3. TEST PLAN — pre-registered, each open question → test → gate

The pattern: **two cheap offline tests can decide whether our offline instrument is trustworthy AT ALL** (and thus whether the infra build is justified) **before** we commit engineering to it. Run those first. Everything else is live and gated on the infra (Document 2).

### Tier 0 — cheap offline tests (runnable now; decide if the infra build is justified)

| ID | Question | Method | Pre-registered gate |
|---|---|---|---|
| **T1 — feed-loss audit** ⭐ | How lossy is our 10 Hz L25 tape — i.e. how many real fills happen at levels our snapshots never show? | For a sample of btc-15m windows, join the taker **trade tape** to the L25 snapshots bracketing each print (±100 ms). Count the **fraction of prints whose execution price was NOT a visible book level** in the bracketing snapshots. | **If ≥~20% of prints execute at "invisible" levels → our fill model is structurally blind → Findings #1/#2 confirmed → infra build justified.** If <5% → the feed is fine and "speed flat" stands. |
| **T2 — feed-completeness as a lever** | Does flow-capture depend on feed rate (the variable the latency sweep never touched)? | Subsample the L25 tape 10 Hz→5 Hz→2 Hz→1 Hz; run the existing FIFO flow-capture sim (`_mm_queue_engine` / `poly_ladder` math) at each rate. Plot flow-capture vs rate. | **Monotone-decreasing flow-capture → feed-completeness IS a lever → extrapolates that >10 Hz (racer) helps → "speed flat" refuted.** Flat → feed rate truly doesn't matter. |
| **T3 — short-side overround scan** | Paper appendix H: the short side (`sum_bid > 1` → split + sell both) "has more profit." We have **never scanned it.** | Offline L25 scan: per window, compute `sum_bid` over time; measure frequency of `sum_bid > 1` and the captured magnitude. btc/eth/sol × 5m+15m. | If `sum_bid>1` is frequent + sized → **the same ladder infra harvests BOTH sides of the overround** (free second strategy). Pre-register before looking. |

T1 is the **single most decisive** test in the whole campaign — it directly measures the data-resolution ceiling that everything else rests on. ~light (no queue sim). **Hang-proof design mandatory** (hard sample cap, `MAX_ITER` guards, `PYTHONUTF8=1`) given the 31 h-hang lesson.

### Tier 1 — live tests (gated on Document 2 infra; the only honest answers left)

| ID | Question | Where | Pre-registered gate |
|---|---|---|---|
| **L1 — live flow-capture + pair-fraction** | Does the racer + early-placed paper ladder lift capture/pair-fraction toward b945's? | TVRUST Stage-0/0.5 paper (`ladder_summary`) | flow-capture **≥~11.5%** (b945) vs **~7%** offline floor; pair-fraction **29% = fail / 44% = target** |
| **L2 — our real per-hop latency** | What is recv→decision→submit→ack→fill from Ireland? (replace the assumed 85 ms) | TVRUST latency tape (Stage-0.5) | establish the distribution; if p50 ≫ 85 ms, re-baseline every latency-sensitive offline result |
| **L3 — real maker fill rate at new levels** | Is "maker 0% fills" real or a queue artifact (Finding #2)? | TVRUST Stage-1/2, real GTC, $0→$50 | measured maker fill-rate at fresh levels > our FIFO ceiling ⇒ Finding #2 confirmed |
| **L4 — V2 residual-exit live** | Does the lifted lag-leg refill within the window; hold-residual vs scalp-exit-residual? | `sum_pair_osc_harvest` $0 shadow (`TV_AGENT_SPEC_SUMPAIR_OSC_HARVEST`) | scalp-exit residual ≥ hold residual AND matched-pair locked PnL CI>0 |

### Sequencing
1. **Run T1 now.** It is the gate on everything. If T1 says "feed is fine," the whole infra thesis (and the article) is wrong for *our* setup and we stop. If T1 says "feed is blind," Findings #1/#2 are confirmed and Document 2 is justified.
2. T2/T3 alongside (T3 is independent free value regardless of T1).
3. Build Document 2 infra → run L1/L2 paper → L3/L4 with capital, all on the pre-registered gates.

---

## 3b. T1 RESULT — ⚠️ RETRACTED/CORRECTED 2026-06-16 (see `L25_FEED_GAP_DIAGNOSIS_2026_06_16.md`)
> **The "CONFIRMED FEED BLIND / 49% invisible" verdict below is WRONG — a join bug.** I matched trades on
> `trade.local_timestamp_us`, which is the **data-API poll/write time** (lags the real trade by p90 = 337 s,
> hours on backfill), against the real-time book. **Corrected** (join `trade.timestamp_us` exchange-time →
> `book.timestamp_us`, clocks aligned p50 0.03 s): steady-state feed loss = **3.6% count / 7.6% volume
> (any-side ±3 s); 7.7% / 12.8% rel-side.** The collector does **dedup-on-change** (~1 Hz, gaps = book
> unchanged, benign), and is **~92–96% faithful on fills.** **Finding #2 below is therefore largely WRONG**,
> and the "build the racer because our offline data is blind" justification is **withdrawn** — the racer's
> case reverts to the original b945 LIVE-execution thesis, which T1 does not speak to. The original (buggy)
> section is kept below for the audit trail.

### (original, buggy) T1 RESULT — RUN 2026-06-16: ✅ CONFIRMED FEED BLIND
Script `strategy_lab/directional/_t1_feedloss.py`. Sample: 50 btc-15m slugs spread Apr 27→Jun 15, **100,919 real taker prints** across 46 slugs, joined to native-10 Hz canonical L25 on the **shared collector clock** (`local_timestamp_us` — trades + L25 are both VPS2). Visibility checked 3 ways, all agree:

| metric | invisible (count) | invisible (volume) |
|---|---|---|
| **bracket ±1 snap, relevant side** (cadence-independent) | **39.1%** | **49.1%** |
| both-ladders union ±300 ms (side-label-independent) | 35.8% | 49.5% |
| relevant side ±100 ms / ±300 ms | 53.0% / 43.5% | 66.7% / 56.3% |

**Decomposition by local feed health** (the decisive cut):
- **TIGHT** (bracketing snaps ≤300 ms apart — feed sampling healthily; 30% of prints): **24.4% invisible** = genuine sub-snapshot churn a racer catches. **Clears the 20% bar on its own, with the feed at its best.**
- **LOOSE** (gap >300 ms; 61% of prints): **41% invisible** = feed holes / connection stalls (also racer-fixable via redundancy).
- **INSIDE-SPREAD: 26%** of fills executed at a price *better than our best visible level* — a level materialized inside our (stale) spread and was taken before we ever sampled it.

**Side-finding (affects EVERY L25 backtest, not just the ladder):** canonical L25 snapshot gap = **p50 257 ms, p90 8.4 s, p99 259 s** — 61% of trade activity happens when our "10 Hz" book is >300 ms stale. Series verified sorted (0 unsorted) → the gaps are real.

**Verdict:** every metric clears the pre-registered ≥20% threshold, including the cleanest (tight-bucket 24.4%). **Findings #1 + #2 are CONFIRMED — our offline fill model is structurally blind to ~25–49% of real fills.** The infra build (Document 2 / `TV_AGENT_SPEC_TVRUST_MOAT_INFRA_2026_06_16.md`) is justified. The next honest number — does the racer actually *recover* these fills — is live-only (L1).

## 4. The one-paragraph synthesis
We spent the campaign perfecting an offline fill model and concluded the infra moat "doesn't matter" — but that conclusion came from an instrument (a single-connection 10 Hz tape + a reaction-latency sweep) that is **physically incapable of seeing the edge the article describes.** The article is internally consistent with everything we *could* check, which raises confidence in the part we couldn't. The honest position: **the infra-moat is an open question, not a closed one**; T1 is the cheap offline test that tells us whether to believe our own offline numbers; and the racer + latency tape + tick tape are the instrument that finally lets us answer L1–L3 live. Economics (Q, γ, fees, no-split) we got right; the feed race we dismissed prematurely.
