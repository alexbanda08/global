# Cross-Validation — my sum-pair research vs the b945 full-decode handoff (2026-06-13)

Comparing my work today (`SUMPAIR_ARB_VERDICT_AND_SHADOW_PLAN_2026_06_13.md`, `sumpair_arb_t1_2026_06_13.py`,
two data/reanalysis agents) against `HANDOFF_2026_06_13_B945_FULL_DECODE_AND_EDGE.md` + its source reports
(`SUMARB_PREREG_BT_2026_06_12.md`, `B945_EDGE_GAP_DECOMPOSE`, `MM_Q_AND_SHORTSIDE`, `B945_PNL_AUDIT`).

## TL;DR
**The two efforts AGREE on every deploy-relevant conclusion** (taker sum-pair arb is dead; the only path is a
live order-by-order probe; rebate/queue-priority is the deciding unvalidated factor). There is **one apparent
contradiction — "0 opportunities, sum never <1" (handoff §D #1) vs my "dips occur 2–5%"** — and it **resolves
cleanly into a methodology difference that makes the combined picture sharper, not weaker.** Net: both are right;
mine adds the *mechanism* (mid-window dips that die on latency), theirs adds the *maker decomposition*.

---

## 1. The apparent contradiction — RESOLVED

| | Handoff / SUMARB_PREREG_BT (06-12) | My sumpair_arb_t1 (06-13) |
|---|---|---|
| Sampling | sum_ask at **3 fixed offsets +5s/+30s/+60s**, one eval/slug/offset (134,878 evals) | **full-window 10Hz scan**, causal first-cross of sum<θ anywhere in the slug |
| Stake walked | $70/leg | $25/leg |
| sum<1.0 found | **0** (at those offsets); min ≥1.01; median 1.04–1.06 | **2–5% of snapshots**; per-slug min ≈0.96–0.97; dips at **+152s(5m)/+398s(15m)** |
| Fill realism | snapshot at the offset | first frame ≥ detect **+85ms** (latency) |
| Verdict | PARK — 0 cells qualify | DEAD as taker — every cell SIG-NEG |

**Reconciliation (three independent reasons their fixed-offset test saw 0):**
1. **Timing — the decisive one.** Their offsets (+5/+30/+60s) are all in the **first minute**; my scan shows the
   dips occur **mid-window** (median +152s for 5m, +398s for 15m). Their test structurally **could not see** the
   dips — it fired before they happen. So "sum_ask never <1" is really "never <1 in the first 60s," not "never."
2. **Size.** $70/leg walks deeper → higher vwap → their median sum 1.04–1.06 vs my 1.01 (top-of-book/$25). The
   overround itself widens with size (a capacity fact both should bank).
3. **asof-staleness (the important caveat on MY number).** My 2–5% uses an asof-ffill union grid; their snapshot
   reads both legs at the same live instant. The gap (their ~0 / Trial-Z's 0.04% vs my 2–5%) means **a large share
   of my "dips" are probably asof-stale-quote artifacts** (one leg's old ask ffilled against a freshly-moved other
   leg), NOT real lockable liquidity. We cannot tell which from 10Hz data (no order-by-order deltas — handoff §J).

**Crucially, my latency result settles the deploy question regardless of which interpretation:** whether the dips
are real sub-100ms transients OR asof artifacts, the fill at detect+85ms reverts to ~1.01 → **−5 to −11¢/pair,
SIG-NEG.** Same verdict as theirs, via a measured mechanism rather than absence.

**→ Correction to bank:** the handoff's §D #1 wording ("sum_ask never <1 simultaneously") **overstates** the
SUMARB_PREREG result (which only checked +5/+30/+60s). Accurate statement: *"sum_ask is never sub-1 at the standard
fire offsets; mid-window transient sub-1 prints exist (~2–5% of ticks, per-slug min ~0.96) but are
latency-uncapturable as a taker and partly asof-stale artifacts."* This nuance matters because it keeps the
**maker-capture question open** (real transients, if any, could be hit by a resting bid) — which is exactly what
both teams' next step targets.

## 2. Where the numbers AGREE (strong cross-validation)
- **Per-pair economics:** their ungated −$8 to −$14/slug at $140 deployed ≈ **−0.06 to −0.10/pair**; my θ=0.99
  lat = **−0.070/pair**. Independent engines, same answer.
- **Fee model identical & correct:** their §F arithmetic (row 10: up=0.42, Up wins → +$23.82 via
  `shares·(1−0.07·p_win)−costs`) is the exact winner-only 0.07 curve my test uses. Both correctly charge fee only
  on the winning leg, $0 on the loser, fee-free redeem.
- **No censoring:** both note buy-both-hold-to-resolution settles every slug from chainlink → no survivorship trap
  (unlike the maker-arb censoring reversal). Confirmed both sides.
- **Overround is the fee:** both conclude the persistent ~1.01–1.04 ask-sum overround IS the cost that kills the
  taker arb. ce25's median 1.041 (handoff) ↔ my L25 walked 1.01 ↔ their $70-walk 1.04–1.06 — all consistent once
  size/offset are accounted for.
- **Combinatorial arb N/A:** both independently flag the paper's cross-market type doesn't apply to single-condition
  crypto; the $39.6M was mostly election multi-market and mostly uncaptured.

## 3. What each effort ADDS (complementary, no conflict)
**My work adds:**
- The **latency mechanism** quantified: dips revert in <100ms; haircut +0.056→+0.111 as θ drops (deeper dip = faster
  revert). This is *why* the taker can't capture it — stronger than "0 opportunities."
- The **mid-window dip existence** (their fixed offsets missed it) → keeps the maker question alive.
- A concrete **$0 observe-only shadow spec** (`TV_AGENT_SPEC_SUMPAIR_MONITOR_2026_06_13.md`) with virtual taker
  (confirm dead live) + virtual resting-maker (the open question) + dip-duration recorder.

**The handoff adds (beyond my scope):**
- **b945 fully decoded** as a two-sided GTC **maker** (not taker arb): PnL **+$21,742 audited**, pvs 0.968,
  +$10.65/slug, ~$500/day recent. His edge = **winner-leg queue priority** (33.4% of fills below the contemporaneous
  best bid = resting time-priority), NOT sub-$1 snapshot capture.
- **Maker economics:** best offline replica **+$0.39/slug = ALL rebate; the arb itself is −$0.12/slug** (breakeven-
  negative). Consistent with my "maker has a strong negative prior; only rebate/queue-priority saves it."
- **The deciding unvalidated number:** the **maker rebate rate (assumed 0.0015/sh)** — must be checked on a live
  account; it alone decides offline viability.
- **5 prior conclusions overturned** (PnL, 24h-early-placement, taker=completion, flow-capture moat, opens-every-
  window) — good GROUND-TRUTH hygiene; none conflict with my findings.
- **TVRUST ladder build spec** (maker-only, place at open, Q≈3–5, moat=queue not speed).

## 4. Convergent next step (both teams point to the SAME door)
Both conclude the question is **not answerable from 10Hz historical data** (no order-by-order WS deltas in the
production window) and requires a **live order-by-order probe**:
- **My `sum_pair_monitor` (observe-only, $0):** measures true sub-100ms dip duration + whether a resting maker bid
  is crossed → settles the *arb-capture* question.
- **Their TVRUST ladder (paper → small capital):** replicates the full b945 MM → settles the *rebate + queue-
  priority* question.
- **Their §H `queue-priority-from-trades` workflow (NOT YET LANDED — report file absent):** the *offline* attempt to
  reconstruct queue capture from the 44.7M-print trade tape. This is the offline analog of my monitor's M3 and could
  pre-empt the live probe. **Read it first when it lands** (handoff §L #1).

These are complementary, not redundant: the monitor tests pure pair-capture; TVRUST tests the rebate-bearing MM;
§H tests whether the trade tape already proves/refutes queue capture offline. They can share the live WS + trade-feed
infra.

## 5. Net combined verdict
- **Taker sum-pair arb: DEAD** — confirmed twice, two engines, consistent magnitude (−5 to −11¢/pair). The overround
  is the fee; dips are mid-window, sub-100ms, latency-uncapturable (and partly asof artifacts). **Do not deploy.**
- **Maker sum-pair (b945 style): NOT deployable offline** — breakeven-arb + unvalidated rebate; the real edge is
  live winner-leg queue priority. Strong negative prior, one open door.
- **Only sanctioned next steps:** (1) read §H when it lands; (2) validate the live rebate rate; (3) run the $0
  `sum_pair_monitor` and/or the TVRUST paper dry-run — the live order-by-order probe is the sole remaining arbiter.
- **Trust level:** HIGH. The one discrepancy was methodology (offset timing/size/asof), reconciled; everything
  deploy-relevant agrees. The handoff's "sum never <1" should be softened to "never <1 at fire offsets; mid-window
  transients exist but uncapturable."
```
