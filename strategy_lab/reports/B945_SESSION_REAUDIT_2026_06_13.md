# b945 session RE-AUDIT — adversarial review of our entire chain of reasoning
**2026-06-13.** Method: 4 independent data-skeptics each tasked to REFUTE one of our conclusions against
the actual wallet data, + a critical re-read of all 3 b945 articles and the arXiv 2508.03474 PDF. Goal
(operator): find where we reasoned wrong. We found **3 real errors, 1 confirmation, and a meta-pattern**
that explains them. The headline NO-GO verdict survives — but most of the *reasons* we gave for it were
wrong, and the corrected picture is materially MORE favorable to a live dry run than we'd concluded.

---

## Scorecard

| # | Our claim | Verdict | Corrected fact |
|---|---|---|---|
| 1 | Early placement ~24h pre-window = queue-priority moat; markets cluster −23.5h | **ERROR** | Pre-window activity clusters **−176s** (≈3min), not −23.5h. Only 234 trades >22h early across ALL markets. b945 has **0 pre-window fills**, first fill +38s, fills **uniform** across the window (not front-loaded). Early placement explains **<5%** of his edge. Our sim placed EARLIER than him and still captured less → placement timing is not the moat. |
| 2 | Mid-window merge loop refuted; 100% post-resolution | **CONFIRMED** | 0/1,286 mid-window merges (verified algebraically). His merge = post-resolution redemption of paired inventory at 15-min cadence; no intra-window capital recycling. Article's "merge IS the strategy, fills are 40%" = idealized design he doesn't run. |
| 3 | His 37% taker = pair-completion (lift opp-ask to lock sum<1) | **ERROR** | `sum_asks` at **every** taker fill is **≥1.0** (mean 1.013, 0/27,039 below 1.0). The pair-completion gate **never fires**. His taker is requote-crossing (weak, only at >50bp oracle moves) + entry + book-lag artifact — **overhead at sum≥1, NOT edge**. Edge is **maker-only**. |
| 4 | Flow capture 7% (us) vs **28.5%** (him); 4× unmodellable gap = NO-GO | **ERROR (overstated 2.5×)** | True matched-denominator capture: him **11.5%**, us **6.9%** → gap **1.65×**, not 4×. The "28.5%" was computed on his self-selected active slugs (29% coverage) — a population artifact. Flow is **accessible** (~0% uncaptured; other makers take 89%), NOT a structurally occupied niche. |

---

## The corrected picture of b945's strategy (what he ACTUALLY does)

After the audit, stripping every article claim that the data contradicts:

> **A dense, competitively-priced, two-sided MAKER bid ladder run across the FULL 15-min window.**
> He rests bids on both Up and Down at many levels, repriced continuously, and captures ~**11.5%** of
> the taker-sell flow at a paired cost sum of **0.968** (<1). Profit = a **large paired base × a tiny
> per-pair edge** (~3.2¢), ~**+$3.18/slug median**. His directional residual actually **loses**
> (−$10.9/slug) — it's drag he tolerates because his paired base is so large. Collateral is recovered
> post-resolution via merge/redeem (relayer); capital locks per window.

**What is NOT his edge** (all things we or the articles over-credited): queue priority / early placement
(error #1), sub-second speed (we refuted via latency sweep), the taker layer (error #3), mid-window
capital recycling (#2), splits/naked-sells (0 on-chain). **His only edge is maker-side competitive
pricing + scale.**

## Why our offline reproduction failed OOS (the corrected reason)

NOT "flow capture is an unmodellable 4× moat." The real chain:
- The matched-denominator gap is only **1.65×** (6.9% vs 11.5%) — modest and **closeable live**.
- The binding constraint is **residual drag**: OOS residual −$4.53/slug overwhelms paired gain
  +$3.89/slug. At our smaller capture + scale, the tiny per-pair edge doesn't cover the residual.
- Residual drag is an **inventory-management problem** (GLT cap already moved net −$9.46→−$0.31 from
  Q∞→Q20). It is NOT a structural-exclusion problem.
- Flow is queue-constrained, not budget-constrained (doubling budget → +30-40%, not 2×).

So the honest OOS story: **we land at −$0.32/slug, a small distance from breakeven, gated by residual
drag in thin flow — with a 1.65× capture gap that live execution plausibly closes.** That is a far more
deployable picture than "dead, 4× unbridgeable moat."

---

## The meta-pattern: WHY we made these errors (lessons)

Every error shares a root, and it's the same failure the GROUND-TRUTH RULE exists to prevent:

1. **Adopting article claims as fact without checking the chain.** Errors #1 (24h placement) and #3
   (taker pair-completion) came from reasoning forward from the articles' logic, not backward from his
   fills. The articles are **generic teaching material** — they describe the full Polymarket-MM toolkit
   (splits, naked sells, mid-window merge, 24h placement, 100-300 WS conns, sub-second requote), but our
   on-chain data proves **b945 uses only a subset**. Treat his behavior as truth; treat the articles as
   a menu, not his spec.
2. **Population/denominator mismatches.** Error #4 (28.5%) compared his cherry-picked active slugs to our
   full universe. Always match denominators before quoting a ratio.
3. **Mis-reading our own intermediate outputs.** The "−23.5h cluster" (#1) and the "speed = moat" (later
   self-refuted) were misreads of our own data that went unchallenged for several steps.

We DID catch several of these mid-session (speed via the latency sweep; the 4 fake-negative ledgers via
audit; the strawman NO-GO when the operator pushed). The 3 errors above are the ones that survived to
this audit — all in the "we believed the article / didn't match denominators" class.

---

## What this changes for the build (spec corrections — applied)

`TV_AGENT_SPEC_RUST_LADDER_B945_2026_06_13.md` and memory are being corrected:
- **DROP "place 24h early" as a hard requirement** → optional. Place at window open; do not build a
  24h-ahead discovery path on the early-placement thesis. (Discovery still needs to find the market;
  just not 24h ahead for queue priority.)
- **REMOVE the taker-completion rule** from `tv-strat-ladder`. Run **maker-only**; let any taker fills be
  an emergent property of live requote-crossing, measured not engineered.
- **Correct the flow-capture target**: his true capture is **~11.5%**, not 28.5%. The dry-run gate
  becomes **≥~12% live capture (his level) + positive net on a thin-flow week** — a LOWER, more
  achievable bar than the 20% we wrote.
- **Reframe the moat in the spec**: it is **dense competitive maker pricing + residual control (tight
  GLT cap)**, NOT queue priority / speed / early placement / taker tricks. Build for pricing density and
  inventory discipline.
- The data-quality feed layer (racer/warmup/dedup) and the trade-feed-for-flow-capture-metric remain
  valid and important (clean data, measurement) — just not justified as a *speed* moat.

---

## Remaining genuine gaps (not yet addressed)

1. **Short-side arb never scanned.** arXiv 2508.03474 states **shorting (sum_bid > 1: split $1, sell
   both legs above $1) is MORE profitable** than the long side we spent the whole session on. Every
   engine we built tests only the long (sum_ask<1) side. This is an entire untested half. (Caveat:
   paper is zero-fee-era; fees compress it. Still worth a cheap offline L25 scan of sum_bid>1 frequency
   + depth.)
2. **Tighter GLT cap untested.** Since residual drag (not flow capture) is the true binding constraint,
   and GLT Q is the dominant lever, Q<20 (e.g. 5, 10) was never swept. A tighter cap trades volume for
   less residual — there may be a breakeven-crossing sweet spot. This is the ONE remaining offline knob
   that directly attacks the actual binding constraint. (Discipline note: test it pre-registered; don't
   p-hack to a GO.)
3. **IS "validation" has mild circularity.** We tuned params (Q,γ,budget,gate) to match his 63/37 + pvs,
   then declared the engine validated because it matched him. The queue MECHANICS (real-trade FIFO
   replay) are first-principles and the reachability check (69.6%) is independent — so it's not pure
   circularity — but the parameter fit is not an out-of-sample validation of the strategy.
4. **ce25 ($300k wallet) chain-true PnL never computed** — still LB-only; the "pays 1.041/pair yet
   profits" paradox is unresolved (parked, separate wallet).

---

## Bottom line

**The NO-GO offline verdict survives, but it is now a NARROW, near-breakeven NO-GO (−$0.32/slug) gated
by residual drag — not the wide "4× unbridgeable flow-capture moat" we claimed.** Three of our four
headline reasons (early placement, taker mechanism, 28.5% gap) were wrong; the corrected picture is a
maker-only dense-pricing strategy whose only real obstacle for us is residual drag in thin flow, with a
modest 1.65× capture gap that live execution can plausibly close. **This strengthens, not weakens, the
case for the live dry run** — and adds one cheap offline test worth doing first (tighter GLT cap), plus
one unexplored opportunity (the short side, which the academic literature says is the bigger pot).
