# B945 EDGE-GAP DECOMPOSITION — why his pvs is 0.968 and ours is 0.991 (2026-06-13)

**Question.** b945 (btc-15m two-sided maker ladder, +$21,742 audited LB) buys each Up+Down pair for a
share-weighted sum **pvs ≈ 0.968** (3.2¢ edge/pair, ~4.5¢ on the matched cheap half). Our best maker-only sim
(`_mm_q5_full`, Q=5) buys it for **pvs ≈ 0.991** (0.9¢ edge/pair). That ~2.3¢/pair gap is the entire difference
between his ~$500/day and our rebate-dependent breakeven. **Where does it come from, and how much can we close
offline (build) vs. how much is pure live-queue priority (uncloseable without a real CLOB queue engine)?**

**Headline framings (do not confuse them).** Two different "gap" numbers appear below and both are correct:
- **2.3¢ headline** = his **full-set** pvs 0.968 (all 1,564 slugs he traded) vs our best **Q=5** sim pvs 0.991.
- **1.24¢ matched** = his pvs **0.9694** vs our **0.9818** on the **n=1,203 both-sided slugs in common** (the
  apples-to-apples overlap). Reproduced this session to the digit (winner −3.279¢ t=−12.72, loser +2.040¢ t=7.48,
  net −1.239¢, additivity exact to 2.2e-16, pvs≡vwap_up+vwap_dn max|err|=0.0).
- The **~1¢ difference** between the two (2.3 − 1.24) is a **population shift**: our sim never paired/filled the
  slugs where he was cheapest. ~0.77¢ of it is the subset-vs-full population shift, the rest is fill-coverage.

---

## 1. THE TABLE — verified contribution + replicable verdict

Sign convention: **positive cents = amount of the his-vs-our gap this angle accounts for** (i.e. how much HIS
pvs is below ours because of this mechanism). "Verdict" is the post-adversarial replicability ruling.

| # | Angle | Claimed ¢ | **Verified ¢** | Holds? | **Replicable verdict** | What it actually is |
|---|-------|-----------|----------------|--------|------------------------|---------------------|
| 1 | **Loser-side** fill price | −2 | **0 (it's +2.04¢ DRAG on HIS pvs)** | ✅ holds | `yes-config` | We already buy the loser CHEAPER. Not a gap source — it works against him. |
| 2 | **Winner-side** fill price | −1.24 | **−1.24¢ (real, this is the source)** | ✅ holds | `no-live-queue-only` | He buys the eventual WINNER ~3.3¢ cheaper, from open-queue priority on both legs. Within-window price level, not timing. |
| 3 | **Fill-depth / queue proxy** (static ladder vs chasing bid) | +1.83 | **+1.83¢ median / +1.24¢ mean (= same total)** | ✅ holds | `yes-needs-build` | Our engine REQUOTES its bid upward (chases); he holds static low rungs. The favorite/longshot per-leg split is a labeling artifact; the SUM is the real, invariant total gap. |
| 4 | **Late-window** aggressive fills (off≥700) | +1.52 | **~0 (population + top-2 outlier artifact)** | ❌ fails | `no-live-queue-only` | Mechanism direction survives; magnitude is noise after fixing the disjoint 55-common-slug overlap (Wilcoxon p=0.84 NS, sign flips pooled). |
| 5 | **Matched-pair timing** (within-30s) | 0 | **0 (confirmed tautology)** | ✅ holds | `no-live-queue-only` | Pairing is an accounting label over a fixed price multiset; can't change the share-wtd mean. Our min(sh) pairing does NOT understate edge. |
| 6 | **Verify 4-leg taxonomy / anti-dip** | 0 | **0 (taxonomy tautological, anti-dip = flat-move artifact)** | ✅ holds | `yes-config` | rebal/hedge labels are deterministic restatements; "anti-dip" is a dup_mid==0 counting artifact; sum<1 capture is real. |

---

## 2. THE 2.3¢ GAP, FULLY ACCOUNTED FOR

There are **only two real, non-overlapping ways** to slice the matched gap, and they must each sum to the same
total. **Do not add a leg-decomposition cent to a fill-mechanism cent** — they are the same dollars viewed twice.

### View A — by which leg the cost lands on (angles 1+2), n=1,203 common both-sided slugs
```
  his pvs 0.9694  −  our pvs 0.9818  =  −1.239¢   (matched gap)
      winner-leg:  −3.279¢   (he buys the WINNER cheaper)   ← the entire source
      loser-leg:   +2.040¢   (we buy the LOSER cheaper — DRAG on him)
      sum:         −1.239¢   ✓ additive to 2.2e-16
```
The loser leg is **not** a gap source. It is a ~+2¢ tax on HIS pvs that we don't pay; the winner leg is so large
(−3.28¢) that it overwhelms it. **All of the gap is the winner/favorite leg; the loser leg shrinks it.**

### View B — by execution mechanism (angle 3, the same −1.24¢ re-expressed), favorite/longshot
```
  favorite-leg:  −2.42¢   (static-ladder catches favorite cheap as it climbs)
  longshot-leg:  +1.18¢   (we pay less for the longshot)
  sum:           −1.24¢   ✓  (median per-pair gap 1.83¢)
```
⚠️ **The −2.42/+1.18 per-leg split is a LABELING ARTIFACT** (regression-to-the-mean: whichever book you call
"favorite" gets selection-inflated). Under his-own-vwap labeling it's −1.63/+0.39; under avg-vwap labeling
−2.42/+1.18. **The SUM (−1.24¢ mean / −1.83¢ median) is invariant and is the number to trust.**

### Reconciling 1.24¢ (matched) → 2.3¢ (headline)
```
  matched gap (1,203 common both-sided slugs)             −1.24¢   ← real, reproduced
  + population shift (his full 1,564-slug set is cheaper)  ~−0.77¢  ← he traded slugs our sim never paired
  + fill-coverage residual (slugs our sim never filled)    ~−0.3¢   ← unmodelled, lower-confidence
  ───────────────────────────────────────────────────────────────
  ≈ −2.3¢ headline (his 0.968 full vs our 0.991 Q=5)
```
**Honest residual:** ~1.0¢ of the 2.3¢ lives in **slugs our sim never paired or filled at all** — we cannot
attribute it to a within-slug mechanism because there's no within-slug comparison to make. It is real (he was
cheap there, we were absent) but it is **coverage, not a closeable per-fill edge**. Do not force it to a clean leg.

---

## 3. HEADLINE — OFFLINE-ADDRESSABLE vs PURELY LIVE-QUEUE

This is the decision-relevant split. Of the ~2.3¢:

| Bucket | Cents | Angles | Can we capture it by changing the sim/strategy offline? |
|--------|-------|--------|----------------------------------------------------------|
| **OFFLINE-ADDRESSABLE (build)** | **~1.8¢** (matched), the favorite-leg mechanism | #3 fill-depth | ⚠️ **YES the mechanism is buildable, but it does NOT translate to deployable PnL** — see caveat. |
| **PURELY LIVE-QUEUE (uncloseable offline)** | **~1.2–1.5¢ + the ~1¢ coverage residual** | #2 winner-side, #4 late-window, #5 matched-pairing | ❌ NO. Requires resting-order time-priority / queue rank. **No L25 field encodes it** (schema = aggregated 25-level price×size, zero order-IDs / queue position). Verified. |
| **NOT A GAP SOURCE** | 0 (it's +2¢ in our favor) | #1 loser-side, #6 taxonomy | n/a — we already win these. |

### 🚨 The critical caveat on the "offline-addressable" 1.8¢
The static-ladder fill engine (`_mm_queue_engine.py`, 47k rows already computed) **does** reproduce the
mechanism direction: same-slug it fills the FAVORITE at **0.621 — 7.5¢ cheaper than his 0.695** (pvs 0.89–0.93),
i.e. it **overshoots past him** on paired cost. **But pvs is a misleading sole objective:**
- The cheaper-pvs static ladder still **nets −$1.8 to −$2.8/slug** (pair-fraction ~60%, large negative residual leg).
- Per-slug `total_pnl` across the sim sums to **−$11.7k**; neither it nor `gt_pnl` equals his **+$21,742** audited LB.
- His $500/day vs our breakeven is dominated by **residual/pair-fraction economics**, NOT the 1.8¢/pair paired-cost stat.

**Translation:** the 1.8¢ is a real, reproducible *paired-cost* improvement, but **closing it offline does not
make us profitable** — we capture cheaper pairs at the cost of fewer completed pairs and a bleeding residual leg.
His edge is **queue priority** (fills cheap AND completes the pair AND stays square), which is the live-queue 1.2¢
+ coverage residual — the part we **cannot** build offline.

---

## 4. OFFLINE-ADDRESSABLE CENTS → concrete change + pre-registered test

The single buildable lever is in angle #3: **stop the requote-up chase.**

**Current bug-shaped behavior:** `_mm_inv_engine` requotes its single bid UPWARD on every best-bid change
(`_mm_inv_engine.py` ~lines 268–278), so it accumulates the favorite mostly at the running-up price → our
favorite vwap 0.738 vs his 0.708.

**Change (PRE-REGISTERED, single hypothesis):**
> Replace the price-following single bid with a **STATIC passive ladder**: place N fixed rungs at the open
> (e.g. 0.50/0.55/0.60/0.65 on each side) and **never requote a rung upward** within the window. Let flow hit them.
> Use the existing `_mm_queue_engine.py` FIFO/proportional queue-ahead bounds (depth≥P + tape consumption) for
> fills; below-bid fills are book-replayable (a rung at P fills when ask≤P crosses).

**Pre-registered success criteria (judge ALL three, not just pvs):**
1. **pvs** on the same common-slug set moves from 0.9818 toward ≤0.97 (necessary, not sufficient).
2. **net_pnl/slug** must turn **≥ 0** (this is the real gate — the existing static ladder FAILS it at −$1.8 to −$2.8).
3. **pair_frac** must not collapse below ~0.55 (the freeze-bid variant collapsed late paired shares −90%).

**Expected outcome (honest):** based on the already-run static-ladder results, criterion (1) passes (overshoots),
**criteria (2) and (3) likely FAIL** — the cheaper pairs come with a bleeding residual leg and fewer completions.
If (2)+(3) fail, **the offline lever is confirmed dead** and the entire deployable edge is live-queue-only.
**Run this test to formally close the offline question before any further sim work.**

---

## 5. TAUTOLOGY / ARTIFACT FLAGS (verify phase) — do not cite these as mechanisms

These came from the original tick-agent taxonomy and **must be flagged in any downstream report or the TVRUST spec:**

1. **4-leg taxonomy (open/add/hedge/rebal) is TAUTOLOGICAL.** The `leg` column is a deterministic function of
   running inventory (`_b945_ml_decode.py:81-88`): `hedge` iff q_own<q_opp, `rebal` iff q_own≥q_opp — *by
   construction*. The claim "rebal buys the leading side 99.87%" is literally `frac(q_own>q_opp)` within rebal;
   it **restates the label and measures nothing.** Independent test: of 62,519 both-held fills he buys the
   leading-inventory side **50.91%** = a coin flip → **no inventory-directional bias.**

2. **"ANTI-DIP" is a FLAT-MOVE ARTIFACT.** The definition `np.where(is_up, dup_mid<0, dup_mid>0)`
   (`_b945_tick_timeline.py:222`) routes every `dup_mid==0` (flat book) into "anti-dip". Flat fraction is
   26.9%/15.7%/6.3% at 5/10/30s. **Excluding flats:** P_dip = 0.487 @5s (near-neutral), 0.514 @10s, **0.561 @30s
   (genuine DIP-buying — the OPPOSITE direction).** The "anti-dip because rebal buys the rising side" mechanism is
   **REFUTED**: by-leg anti-dip is identical (hedge 0.3593 vs rebal 0.3599) and corr(up_rising, up_leading)=0.006.

3. **sum<1 matched-pair capture is REAL** (independent Up+nearest-Dn-30s = 62.0% sum<1, median 0.985; slug-level
   pvs median 0.9681, 71.9% pvs<1). The report's 58.7% (100-slug sample) **understates** it.

4. **Matched-pair timing reveals NO hidden edge.** Within-30s greedy share-match = 0.9875, **WORSE** than the
   slug-aggregate 0.9757 — because his cheapest fills are time-isolated and fall into the unmatched residual.
   Our slug-end `min(sh_up,sh_dn)` pairing **correctly books his true inventory cost; it does not understate.**

**Net:** angles 5 & 6 contribute **0¢** to the gap and **must not** be cited as actionable mechanisms. The real
gap is queue-priority on the favorite/winner leg (angles 2 & 3), full stop.

---

## 6. UPDATED TVRUST ENTRY-LOGIC GUIDANCE + DEPLOY VERDICT

**What this decomposition changes for the Rust ladder build:**

1. **DO place a STATIC passive ladder from the open; DO NOT requote rungs upward.** The single biggest
   mechanistic finding: his cheap favorite fills come from low rungs resting *before* the bid climbs through them
   (33.4% of his fills are BELOW the contemporaneous best bid — only reachable by a resting order with
   time-priority). A chasing single-bid engine structurally cannot replicate this. This is the #1 entry-logic rule.

2. **The edge IS the queue moat, exactly as banked.** ~1.2–1.5¢ + ~1¢ coverage of the 2.3¢ is **live-queue-only**
   and confirms the prior conclusion: btc-15m markets are tradeable ~24h pre-window, and **early-GTC-ladder
   placement = queue priority = the moat.** No L25-replayable offline strategy can capture it — it requires
   being first in the real CLOB FIFO queue. The TVRUST early-placement thesis is **reinforced**, not weakened.

3. **DROP the 4-leg taxonomy and anti-dip from any entry signal.** They are tautological/artifactual (§5). The
   sim must be a **symmetric two-sided passive maker with NO dip/rebal/leading directional input** — which is
   what `_mm_queue_engine.py` already is. There is no directional alpha to encode (side-decode AUC ~0.47).

4. **pvs is necessary but NOT sufficient — gate on net_pnl/slug and pair_frac.** The static ladder beats him on
   pvs (0.621 favorite vs 0.695) yet **loses money** (−$1.8 to −$2.8/slug). Do not let a Rust build optimize pvs
   in isolation; it will produce a cheaper-but-bleeding ladder.

**DEPLOY VERDICT — UNCHANGED: NO offline-only deploy; live-queue probe only.**
The decomposition **confirms** the standing verdict. The ~1.8¢ "offline-addressable" cents do **not** translate to
deployable PnL (the engine that captures them still nets negative). His real edge is queue-priority on the winner
leg, which is **live-queue-only** and requires the early-GTC-ladder / TVRUST infrastructure with real CLOB
time-priority. **No reason to revisit the maker-deploy verdict on offline grounds.** The next concrete step is the
§4 pre-registered static-ladder test purely to *formally close* the offline question, after which the only
remaining path is the live early-placement queue moat (TVRUST).

---

*Data: `strategy_lab/wallet_hunt/cache/0xb945945d/{ml_features,fill_tape_full,per_slug_paired_ledger}.parquet`,
`cache/_mm_q{2,3,5,8,12,16,20}_full.parquet`, `cache/_mm_queue_engine.py` outputs. pvs identity, n=1,203 matched
decomposition (winner −3.279¢ t=−12.72 / loser +2.040¢ t=7.48 / net −1.239¢, additive to 2.2e-16) reproduced from
raw files this session. GROUND-TRUTH RULE: ~1.0¢ of the 2.3¢ is unattributed coverage residual; not forced to sum.*
