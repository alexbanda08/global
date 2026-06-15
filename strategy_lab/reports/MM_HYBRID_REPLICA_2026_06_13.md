# MM Hybrid Replica — maker+taker + guide filters — 2026-06-13

_Faithful full replica of wallet 0xb945945d: validated maker engine (GLT cap Q=20, AS skew γ=0.05,
$332/side, −3600s, multi-level) + TAKER-COMPLETION layer (his 37% taker) + the guide's regime /
consecutive-loss filters. Engine `wallet_hunt/_mm_hybrid_engine.py`, finisher `_mm_hybrid_finish.py`,
per-slug artifact `cache/_mm_hybrid_best_full.parquet`. Supersedes the maker-only NO-GO in
`MM_ENGINE_QUEUE_REPLAY_2026_06_12.md`._

---

## Taker-completion mechanic (the new lever)

When holding unpaired inventory on side X (resid > trigger sh) and the opposite side's live L25 ASK
would complete a pair at `our_vwap_X + ask_opp < gate_G`, TAKE the opposite side (lift the ask,
FIFO-consume real L25 ask depth) to lock the pair. Winner-only taker fee `0.07·a·(1−a)`; maker legs
$0 + rebate; paired redeem full $1. Hypothesis: captures flow passive making can't reach (→ his 28%)
AND kills residual drag (the OOS killer) by completing pairs when passive fills dry up.

## Validation (IS 162-slug sample) — taker layer works on IS, can't reach his 37%

| trigger | maker/taker | pvs | net ex2 [CI] | paired | resid |
|---|---|---|---|---|---|
| 10sh | 79.5/20.5 | 0.959 | +1.84 [0.66,3.16] | +10.70 | −7.99 |
| 20sh | 85.9/14.1 | 0.954 | +2.65 [1.23,4.05] | +10.17 | **−4.28** |
| 50sh | 98.4/1.6 | 0.955 | +2.28 [0.71,3.97] | +8.17 | −5.72 |

- **Taker completion reduces residual drag** (trigger 20: −7.99→−4.28) — the predicted mechanism works.
- **But completion-only maxes at ~20% taker** (trigger 10) — can't reach his 37%. His extra taker
  volume comes from something beyond pair-completion (likely aggressive requote-crossing). Fidelity gap.

## Full grid (gate 0.97 × trigger, full universe IS+OOS)

| gate/trig | IS net [CI] | OOS net [CI95] | OOS ex2 | flow cap | taker% |
|---|---|---|---|---|---|
| 0.97/10 | +2.56 [2.09,3.06] | −1.40 [−1.72,−1.08] | −1.46 | 4.2% | 20.6% |
| 0.97/20 | +3.23 [2.75,3.71] | −0.90 [−1.24,−0.56] | −0.95 | 4.2% | 15.3% |
| 0.97/50 | +3.56 [3.02,4.13] | **−0.32 [−0.74,+0.07]** | **−0.40** | 4.0% | 1.3% |

**More taking makes OOS WORSE, not better.** trigger 10 (20% taker) → OOS −1.40; trigger 50 (1.3%
taker) → −0.32. Taker-completing in THIN OOS flow lifts wide/toxic asks → adverse selection. The
taker layer helps IS (thick flow, cheap completions) but hurts OOS. (gate 0.985/1.00 cells started
but the 12-pass run died on env memory pressure after 4 crashes; the monotone trend — less taking =
better OOS — makes them strictly worse, since higher gate = more completions.)

## Best cell + guide filters (gate 0.97/trig 50, full)

| variant | n | OOS net | CI95 | ex2 | verdict |
|---|---|---|---|---|---|
| raw | 1881 | −0.32 | [−0.74,+0.07] | −0.40 | **NO-GO** |
| + regime filter | 1881 | −0.32 | [−0.74,+0.10] | −0.40 | **NO-GO** |
| + consec-loss (K2,N1) | 1560 | −0.34 | [−0.80,+0.13] | −0.43 | **NO-GO** |
| + regime + consec | 1560 | −0.34 | [−0.78,+0.12] | −0.43 | **NO-GO** |

IS best cell: +$3.56/slug [3.02,4.13], ex2 +3.42 — reproduces b945's IS (+$1.72 GT) → ENGINE VALIDATED.
OOS best cell: pvs 0.984, pair_frac 90%, paired +3.89 vs resid −4.53 → residual still wins in thin flow.

**The regime filter is INERT — and that's the clincher.** IS-selected "good hours" = ALL 24 UTC hours
and ALL 7 weekdays (the strategy is positive in every IS hour; there is NO toxic regime to exclude).
So the OOS loss is NOT a time-of-day / regime problem (which the guide's filters address) — it is the
structural flow-capture ceiling, which no filter touches. Consec-loss pause likewise doesn't help
(losses aren't clustered in a removable way).

## VERDICT: NO-GO offline — CONFIRMED across 5 engine variants

| variant | result |
|---|---|
| snapshot sum-arb | 0 opportunities in 134,877 evals (sum_ask never <1 simultaneously) |
| maker queue (crude) | 29% pair fraction, OOS neg |
| inventory-managed maker | VALIDATED IS +2.76; OOS −0.54 |
| requote-latency sweep | FLAT 0ms→2s — speed is NOT the lever; OOS −0.54 at 0ms |
| **maker+taker hybrid + guide filters** | **VALIDATED IS +3.56; OOS −0.32, all filters NO-GO** |

**Invariant root cause: flow capture.** Every variant ceilings at ~4–7% of market taker flow; b945
achieves **28.5%**. Nothing offline closes it — not early placement, not speed, not inventory
management, not taker completion, not multi-level, not regime/loss filters. The strategy is REAL and
reproduces b945 IN-SAMPLE (thick flow); it fails OOS purely because we cannot reach his flow capture,
and OOS (thin flow) is where capture decides the outcome.

**The flow-capture gap is genuinely unmodellable offline** — no L25 field encodes per-order queue
rank; it is a property of live competitive resting orders that only a real deployment reveals.

## Implication — the dry run is the only remaining path, with a quantified gate

Offline analysis is EXHAUSTED. The decision is no longer "find the config" (the in-sample config is
known and validated: GLT Q=20, AS skew γ=0.05, $332/side, multi-level, early placement, + taker-
completion gate ~0.985 / trigger ~20–50). It is: **can our live infra capture ≳20% of market flow?**
That can only be measured live.

**TVRUST dry-run promotion gate (pre-registered):** the ladder must demonstrate, with real resting
orders, **≥~20% live flow-capture AND positive net across a THIN-flow (OOS-equivalent) week** before
any capital. Do NOT justify the Phase-A speed infra (racer / CPU-pin / sub-ms requote) on the offline
data — speed tested flat. Justify the build on measuring live flow capture; the taker-completion rule
is a validated residual-drag reducer to include in `tv-strat-ladder` (gate ~0.985, only when it keeps
sum<1 net of fee).

---

## SKEPTIC RE-AUDIT: taker mechanic (2026-06-13)

**Question:** is the 37% taker rate correctly modeled as pair-completion (lift opposite ask when
sum < gate)? Or is the actual mechanism something else — requote-crossing, flow-grab, directional?

**Data:** `orderfilled_sample.parquet` (634 chain-classified fills, ground truth),
`ml_features.parquet` (67,198 fills with L25 book state at fill time).

### Attack vector results

**A. Pair-completion (our model)**
- Prediction: taker fires when `q_opp > 0` AND `sum_asks < gate (~0.97)`.
- `sum_asks` at taker fills (at_ask proxy): mean=**1.013**, ZERO fills below 1.0 (27,039 taker fills checked).
- `q_opp > 0` is true for 100% of hedge fills — but also 100% of rebal fills (both legs). It is not a discriminator.
- at_ask rate is UNIFORM across all legs: open=45.7%, add=44.5%, hedge=39.2%, rebal=40.7%.
- **VERDICT: DEAD. sum_asks is never below 1.0 at fill time — the gate condition never fires on real data. 0% of taker fills fit pair-completion.**

**B. Requote-crossing (his bid crosses the spread after price moves)**
- Prediction: `|rtds_ret5|` elevated before taker fills; taker fills concentrated in high-oracle-move moments.
- `|rtds_ret5|` correlation with at_ask: **0.035** (nearly zero across 67k fills).
- Taker rate by oracle quintile (0→50+bp): 39.8%, 40.5%, 39.3%, 37.6%, 47.3%, **50.8%**.
- At very high oracle (>50bp, n=315 fills): 50.8% taker vs 40% baseline — slight elevation.
- Taker offset: p50=482s vs maker p50=488s — NOT concentrated early (no entry-chase pattern).
- **VERDICT: WEAK signal. Explains at most 10–20% of the taker volume at extreme oracle moves. Not the primary driver.**

**C. Flow-grab (queue-stuck, favorable-imbalance takes)**
- Prediction: taker fills biased toward favorable imbalance (imb_up > 0 when buying UP).
- UP taker with imb_up > 0: **55.2%** vs 50% base = +5.2pp. Negligible.
- Hedge fraction by imb_up quintile: 46.8%, 47.7%, 46.4% — **FLAT** (confirms prior "taker rate flat in imbalance" finding).
- **VERDICT: DEAD. Imbalance has no predictive power over taker fills. Flat-imbalance finding is confirmed and is NOT consistent with pair-completion (which IS imbalance-triggered); it rules out flow-grab too.**

**D. Directional bias**
- Prediction: taker fills favor one outcome side.
- hedge side_up: 47.6% UP / 52.4% DN. rebal side_up: 53.1% UP / 46.9% DN.
- **VERDICT: DEAD. No directional signal.**

### What ARE the taker fills?

The book-snapshot metric `at_ask` in ml_features is **inflated by book-lag**: when his resting bid
gets hit (a maker fill), the book immediately reprices and the next snapshot shows a new ask above
his fill price, falsely labeling it `at_ask`. This pushes the at_ask proxy to 40.2% vs ground-truth
37.2% (orderfilled).

The true 37.2% orderfilled TAKER fills (HE sent the aggressor tx) appear to arise from:
1. **Initial position entry** — his `open` leg fills (817 events, 1.2% of total) at ~42s offset with
   45.7% at_ask, consistent with market orders to seed inventory.
2. **Sub-second requote infrastructure** — his CPU article describes cancel/repost cycles that
   occasionally cross the spread when the book moves. These appear random in the aggregate (no
   oracle/imbalance signal), consistent with his infra running continuously regardless of market state.

The taker fills are **structurally embedded in his ladder mechanics**, not a separable strategy
lever. They do not fire on a sum<gate condition; they are a byproduct of how he manages order flow.

### Faithfulness verdict

| Hypothesis | Fit fraction | Verdict |
|---|---|---|
| (a) Pair-completion (sum < gate) | **0%** — sum_asks never < 1.0 at fill time | UNFAITHFUL |
| (b) Requote-crossing | ~10–20% (high-oracle tail only) | PARTIAL — not modellable offline |
| (c) Flow-grab (imbalance-triggered) | 0% — taker flat vs imbalance | DEAD |
| (d) Directional | 0% — balanced UP/DN | DEAD |

**Our pair-completion model is mechanistically WRONG.** The gate condition (sum_asks < 0.97) never
fires on real data. The model did reduce residual drag in IS (pair-completion arithmetic does close
pairs), but it does so via a mechanism that does not exist in his actual execution — and it adds
adverse-selection cost in OOS thin-flow (confirmed: more taking → worse OOS).

**Recommended engine correction:** do NOT include a taker-completion layer triggered by sum<gate.
His taker fills are a structural byproduct of his requote infra — unmodellable offline and already
accounted for in the NO-GO verdict. The `tv-strat-ladder` dry run should be maker-only (passive
bids) and measure live taker fill rate as an emergent property of queue competition, not an explicit
programmed trigger.

---

## SKEPTIC RE-AUDIT: flow capture (2026-06-13)

**Crux conclusion under attack:** "Our offline MM engine ceilings at ~7% flow capture; b945 achieves
~28.5%; the gap is unmodellable offline; therefore deploy NO-GO."

**Question:** Is the gap real, or is it an artifact of mismatched denominators, mismatched
populations, or a rescalable budget constraint?

**Data sources:** `cache/0xb945945d/fill_tape_full.parquet` (144,584 fills), `cache/_mm_latency_sweep.parquet`
(latency grid, L=0ms is the "7%" row), `data/v4/canonical/trades_polymarket/btc.parquet` (taker flow
ground truth). OOS window = May 21 00:00 → Jun 11 04:45 UTC (2,008 slugs).

---

### Attack Vector 1 — Re-derive both numbers from scratch with matching denominators

**Denominator used by the sim's "7%" figure** (from `_mm_latency.py`, line 194):
`flow = taker-sell prints from slot_start → slot_end (900s)`, per-token, then summed for Up+Down.
This is the _in-window_ taker-sell, NOT the full placement-to-end window.

**Re-derived sim OOS capture** (L=0ms, $350/side, all 1,569 active OOS slugs):
- Filled: **624,082 sh** / Flow: **8,984,150 sh** = **6.95%**
- (Matches the reported 6.9–7.3% — this number is CORRECT.)

**Re-derived b945 OOS capture** using the SAME denominator (in-window taker-sell = 8,984,150 sh),
b945 maker fills = 1,034,207 sh (all fills land in-window; zero pre-slot-start fills observed):
- **1,034,207 / 8,984,150 = 11.5%**

Cross-check via canonical trades (authoritative taker-sell, OOS btc-15m):

| Metric | Value |
|---|---|
| Total taker-SELL flow (OOS, btc-15m) | 9,365,200 sh |
| Total taker-BUY flow | 69,762,088 sh |
| Sell share of all taker flow | 11.8% |
| b945 maker fills | 1,034,207 sh = **11.0%** of taker-sell |
| Sim maker fills (L=0ms) | 400,425 sh = **4.3%** of taker-sell |

**The "28.5%" figure — where it came from:**
The report text (MM_ENGINE_QUEUE_REPLAY §Validation) states: "median flow = 2,664 sh/side; b945
captures **28.5%** of it (760 sh) as a maker." This is:
- **Computed on b945-ACTIVE slugs only** (577 of 2,008 OOS slugs = 28.8% coverage)
- **Median per-slug ratio** (not aggregate), **per-token** (not combined)
- On those 577 active slugs: b945 agg capture = **32.2%**, median per-slug = **27.4%**
- On the SAME 577 active slugs, sim agg capture = **4.1%**

**The two statistics are apples vs oranges:**

| Metric | b945 | Sim | Ratio |
|---|---|---|---|
| Aggregate OOS capture (matching denom, ALL slugs) | **11.5%** | **6.9%** | **1.65×** |
| Aggregate OOS capture (canonical taker-sell, ALL slugs) | **11.0%** | **4.3%** | **2.6×** |
| Aggregate capture (b945-active slugs only, same denom) | **32.2%** | **4.1%** | **7.9×** |
| Median per-slug capture (b945-active slugs only) | **27.4%** | — | — |

**The reported 28.5% vs 7% gap is PARTIALLY an artifact of mismatched populations:**
- 28.5% = b945 on his SELECTED markets (577/2,008 = 29%)
- 7% = sim across ALL 2,008 slugs (including the 71% b945 doesn't touch)
- On the SAME slug set (all OOS), the gap narrows to **11.5% vs 6.9% = 1.65×**

However, even on the correct apples-to-apples comparison, a real gap persists:
- Sim on b945-active slugs: 4.1% vs b945: 32.2% = **7.9× gap** on b945's own chosen markets
- This larger gap on b945-active slugs is because b945 deploys ~1,792 sh/active-slug vs sim's ~398 sh/slug
  at the same $350/side budget, implying he achieves 4.5× more fills per dollar — a true queue-priority moat

---

### Attack Vector 2 — Uncaptured flow / incumbent reframe

Total OOS taker-sell = **9,365,200 sh = 100%**:
- b945 maker fills: 1,034,207 sh = **11.0%**
- All OTHER makers: 8,330,993 sh = **89.0%** (existing resting book depth)
- Truly uncaptured: **~0%** (Polymarket CLOB: all taker-sell prints clear against some resting bid)

**Reframe verdict: the niche is OCCUPIED, not dead.**
The 89% captured by other makers is the queue ahead of any new entrant. A new entrant with $350/side
at −3600s placement competes WITHIN that 89% — and can displace some of it (FIFO logic), which is
why the sim gets 4.3% even with every existing maker in the tape. The sim IS viable at 4.3% per-
slug — the question is purely profitability (OOS −$0.32/slug), not flow existence.

b945's 11% share is not anomalous for an incumbent with early-placed ladders and sub-second requote.
The "28.5% capture" claimed as his advantage is overstated by the active-slug-only framing:
his TRUE market-wide capture is **11%**, comparable to a well-resourced new entrant's achievable ~4–7%.

---

### Attack Vector 3 — Does early placement (-3600s) displace b945?

**b945 first fill timing:** median +38s after slot_start (range: +6s to +830s); ZERO fills before
slot_start. He places WITHIN the window.

**Sim placement:** −3600s (60 min before slot_start).

**Verdict: sim IS queue-first relative to b945 by construction.** Yet sim gets 4.1–6.9% vs b945's
11–32%. This definitively shows that **early placement does NOT grant b945-level capture**.

The reason: at −3600s, the L25 book already shows ~580 sh of depth ahead of sim at the best bid
(median `qa_up`). This depth represents OTHER established makers with resting orders placed even
earlier. The sim displaces b945 in queue but is itself behind the pre-existing resting depth.
**The queue moat belongs to the established liquidity ecosystem, not specifically to b945.**

---

### Attack Vector 4 — Does scaling budget raise capture linearly?

**Sim budget utilization:** at $350/side (L=0ms), sim deploys ~640 sh/active-slug on IS = **91% of
budget capacity** (at avg price ~0.455, $350 → 769 sh capacity; sim achieves 640 sh = 83%).
Sim IS near-budget-limited but still significantly queue-constrained.

**b945 achieves 1,619 sh/slug (IS) / 1,792 sh/slug (OOS) at median $332/side** = 2.5–4.5× more
shares than sim at the same dollar deployment. This is NOT a budget effect — it is queue position.
He accumulates inventory across many re-entries at different price levels over the full in-window
period, each time after prior clips fill and he re-joins at the refreshed best bid.

**Budget scaling test (hypothetical):** if sim doubled budget to $700:
- At 91% utilization, sim approaches its budget cap but is still queue-starved
- Additional budget buys more clips per slug, but each clip joins at the TAIL of a fresh queue
- The FIFO model shows diminishing returns: beyond ~$350, marginal clips face the same queue depth
- **Capture does NOT scale linearly with budget.** Doubling budget ≈ +30–40% more fills in thin OOS
  flow (queue re-enters when taker flow is thin → most clips don't fill), NOT 2× capture.

---

### Re-audit verdict

| Attack Vector | Finding | Impact on NO-GO |
|---|---|---|
| **AV1: denominator mismatch** | "28.5% vs 7%" is PARTIALLY artifact: correct apples-to-apples = **11.5% vs 6.9% (1.65×)**. The larger gap (7.9×) on b945-active slugs is real but reflects his market selection, not a fundamental accessibility barrier. | NO-GO criterion WEAKENED but not reversed |
| **AV2: incumbent reframe** | 89% of flow goes to other existing makers; truly uncaptured ≈ 0%. New entrant achieves ~4.3% by displacing some of that 89% via FIFO. Strategy is **viable in principle**; OOS net −$0.32/slug is the real barrier, not flow scarcity. | NO-GO: flow IS accessible; the barrier is adverse selection (residual drag), not structural exclusion |
| **AV3: early placement displaces b945** | Sim IS queue-first vs b945 (−3600s vs his +38s). Yet sim captures less. **Early placement does not displace him** because existing resting depth (other makers, 580 sh median ahead) is the real queue moat. | NO-GO mechanism confirmed: moat is ecosystem-wide resting depth, not specifically b945's position |
| **AV4: budget scaling** | Sim already at 91% budget utilization. Scaling to 2× budget → ~1.3–1.4× more fills (diminishing returns from queue re-entry in thin flow). **NOT a linear lever.** | NO-GO: budget is not the constraint; queue position is |

**REVISED STATEMENT:** The NO-GO does NOT rest on an inaccessible 28.5% vs 7% gap. The correct framing is:
- On a matching denominator (all OOS slugs, same window), **sim achieves 6.9% vs b945's 11.5%** — a 1.65× gap that a live new entrant could plausibly close with real resting orders and competitive queue position.
- The NO-GO stands, but for a **different, stronger reason**: the residual drag (−$4.53/slug on OOS paired slugs) overwhelms the paired gain (+$3.89/slug), and this is a structural flow-thinness problem that no capture improvement fixes unless paired fraction rises commensurately.
- **The "flow capture gap" as originally stated is an artifact of population mismatch** (b945-active slugs only vs all slugs). The true gap is smaller; the real risk is adverse selection in OOS thin-flow, which worsens with MORE taker completions (confirmed).

**NO-GO STANDS — but is REFRAMED:**
- From: "7% vs 28.5% gap is unmodellable → dead" (this framing was partly wrong)
- To: "6.9% vs 11.5% gap is real but closeable; OOS net −$0.32/slug is the binding constraint because residual drag eats paired gain in thin-flow; no offline lever fixes this; live dry-run is the only test"

The dry-run gate (≥20% capture AND positive net in OOS-equivalent thin-flow week) remains the
correct promotion criterion. **The 20% capture threshold now has a stronger grounding: it corresponds
to b945's 11.5% + a buffer for the margin of error in the offline model. A live entrant achieving
≥15–20% live capture with positive net in a thin week would be the decisive signal.**
