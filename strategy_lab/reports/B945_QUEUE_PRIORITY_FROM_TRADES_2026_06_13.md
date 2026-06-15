# b945 Queue-Priority Capture, Measured From the Trade Tape (2026-06-13)

**Wallet `0xb945945d` — btc-updown-15m two-sided maker. +$21,742 LB-canonical (audited).**

**One-line verdict:** The operator was right that queue-priority capture is **modellable offline** — the
canonical trade tape *is* the queue-consumption process and lets us measure his realized per-level capture
directly (~14% raw, 12–16% range). But measuring it does **NOT** turn the winner-leg edge net-positive for *us*.
Best-case REPLACE looks +$6.89/slug only because of fill-model artifacts; it fails to reconcile to his own
realized ~+$2.5–4/slug, and a faithful COEXIST entrant is breakeven (CI straddles zero). **Offline verdict
does NOT change: DO NOT deploy.**

This session overturned the prior "queue priority is unmodellable offline" claim *and* re-overturned two of the
numbers in the calibrated-capture JSON it was handed. Both corrections are documented below per the GROUND-TRUTH RULE.

---

## 0. What reconciles vs what was overturned (adversarial pass)

Everything in this report was re-derived directly from `D:/tmp_qp/capture_buckets.parquet` (his on-chain fills
bucketed vs canonical taker-sell tape) and `strategy_lab/wallet_hunt/cache/0xb945945d/per_slug_paired_ledger.parquet`
(his realized per-slug ledger). Window: production Apr 26 – Jun 11 (trade-tape coverage), 1,333–1,433 of his 1,564
btc-15m slugs.

**Reconciles exactly to the handed JSON:**
- Pooled raw (share-wtd) capture **0.1375**; dollar-wtd **0.1221**.
- Winner vs loser raw **0.121 / 0.157**; $-weighted **0.106 / 0.173** — his per-level capture is *not* higher on
  the winner side, it is slightly **lower**.
- Favorite band 0.50–0.97 winner/loser **0.161 / 0.177**; ≥0.90 band collapses to **0.057** while holding 44% of
  all taker-sell $-flow.
- K_eff = 1/0.1375 = **7.27** equal b945-sized maker slots; off-tape (no same-cent print) share = **36%**;
  `corr(per-slug capture, pnl) ≈ 0` (0.006).
- REPLACE-FULL: net **+6.89/slug**, pvs 0.999, 867 sh/slug, CI **[−1.05, +14.69]**.
- COEXIST q=1/8: positive mean, CI straddles zero, t≈1.5, win-rate ≈47.5% (independent ballpark recon: +$0.85,
  CI [−0.16,+1.89], t=1.65 — same sign/shape).

**Overturned / does NOT reconcile (re-derived, do not trust the JSON value):**
1. **The "credible-bucket capture = 0.159"** could not be reproduced. Pooled his/tape on credible buckets
   (tape ≥ his) = **0.0712**. The honest defensible point estimate is **~0.12 (dollar-wtd) with a 0.07–0.14 range**,
   not 0.159. Also the JSON's "39% of overlap buckets his>tape" is actually **16%** (mean ratio 14.3× ✓).
2. **REPLACE +$6.89/slug does NOT reconcile to his own realized PnL** (§2, §3) — it is ~2.5× too high on the same
   slugs and is an outlier/fill-model artifact.
3. **"+$10.65/slug" is per-REDEEM, not per-slug** ($21,742 / 2,041 redeems). His per-*slug* economics are far
   lower (§2).

---

## 1. His MEASURED realized queue capture (the number we wrongly called "unmodellable")

**Method.** His on-chain fills (`fill_tape_full.parquet`, all 144,584 btc-15m fills are maker BUYS: usd == shares×price
exactly). Trade tape = `data/v4/canonical/trades_polymarket/btc.parquet` (44.7M rows, scanned all 90 row-groups,
filtered `side=='sell'` & slug in his set). A `side='sell'` print is a taker hitting a *bid* at price P; b945 is
often that bid. Capture per (slug, outcome, 1¢-bucket) = his_filled_shares / total_taker-sell_shares, pooled by
summing numerator and denominator over buckets with tape sell flow.

### Pooled
| metric | value |
|---|---|
| raw (share-weighted) capture | **0.1375** |
| dollar-weighted capture | **0.1221** |
| credible buckets only (tape ≥ his), pooled | **0.0712** *(corrected from JSON's 0.159)* |
| implied equal maker slots K_eff = 1/0.1375 | **7.27** |

He captures only ~12–14% of the taker-sell flow at his exact price levels. **The level is shared, not his alone** —
~6–7× more flow at his levels goes to other makers resting at the same price.

### By side — the headline test of his "winner-leg edge"
| side | raw capture | $-weighted | favorite band 0.50–0.97 (raw) |
|---|---|---|---|
| **winner leg** | 0.121 | 0.106 | 0.161 |
| **loser leg** | 0.157 | 0.173 | 0.177 |

**His per-level capture is NOT higher on the winner side — it is slightly lower.** His ~3.3¢-cheaper-winner edge
therefore does **not** come from grabbing a bigger *share* of flow on the winner leg. It comes from buying the
favorite **cheap and EARLY** at moderate prices (time-priority on the *price* axis), then the favorite trades up
into the ≥0.90 band where his fixed resting size is swamped.

### By price band
| band | raw capture | share of taker-sell $-flow |
|---|---|---|
| <0.10 | 0.124 | 1% |
| 0.10–0.49 | 0.169 | 18% |
| 0.50–0.89 | 0.177 | 37% |
| **≥0.90** | **0.057** | **44%** |

44% of all sell $-flow occurs in the ≥0.90 band where capture collapses to ~6% — late deep-favorite sell flow
swamps him. His edge lives in the 0.50–0.89 band.

### By window phase (offset from slot_start)
| phase | raw capture | taker-sell shares |
|---|---|---|
| 0–300s | 0.150 | 2.18M |
| 300–600s | 0.135 | — |
| 600–900s | 0.094 | 5.92M |

Capture declines **monotonically** through the window. He is most front-of-queue early (resting bids placed
pre/early-window get time-priority); late, taker-sell flow grows ~3× and swamps his fixed size.

### The off-tape moat we CANNOT reach
**36%** of his shares fill at 1¢ buckets with **zero same-cent taper-sell print** in the canonical tape. Under a
±1–3¢ tolerance most of this is bucket-edge rounding; the residual **~16%** is genuine off-tape / below-best-bid
fills — his queue-priority moat from early-GTC time-priority. The trade tape **cannot** reconstruct these (§4).

**Subset / tape-completeness check.** His 2.47M total shares = 21.5% of the 11.5M tape-sell shares in his slugs
(aggregate subset holds). But per-bucket the subset *fails*: in **16%** of overlap buckets his on-chain fills
exceed the tape's sell shares (mean 14.3×), and in **285/1,433 slugs** his slug-total exceeds the tape slug-total.
→ **The canonical trade tape is a lossy observation of Polymarket flow.** His OrderFilled events are ground truth;
the tape under-records prints. So 0.1375 is a *lower bound* where the tape is complete and a denominator-deflated
*over-estimate* where it isn't.

---

## 2. Economics: REPLACE vs COEXIST vs prior FIFO vs his realized

### His own realized per-slug (the reconciliation target — re-derived from his ledger)
| basis | all-time (1,564 slugs) | prod window (1,433) |
|---|---|---|
| `total_pnl` (0.07 fee applied to maker fills — **WRONG**, see note) | −7.51 | −8.51 |
| `total_nofee` | **+3.93** | — |
| `gt_pnl` (fill-tape, no rebate, ~88% coverage) | **+4.08** | +3.45 |
| + rebate $3,645/1,564 = +2.33/slug | → **~+6.4 true** | — |
| pvs (his cheap-pair signature) | 0.9687 | 0.9689 |

> **"+$10.65/slug" is a denominator error**: it is $21,742 / **2,041 redeems**, not per-slug. Per-*slug* all-time
> is $21,742/1,564 = $13.9 (LB-canonical, full redeem coverage + rebate), but his *modellable* fill-tape economics
> are **+$4.08/slug (gt) → ~+$6.4 with rebate**. The fee-applied −$7.51 violates the memory rule "never apply taker
> fees to maker fills" and should be ignored.

### The four scenarios
| scenario | pvs | pair_frac | paired/slug | resid/slug | rebate | **net/slug** | CI95 | verdict |
|---|---|---|---|---|---|---|---|---|
| Prior **FIFO** static ladder | — | — | — | — | — | **−1.8 .. −2.8** | (sig-neg) | DEAD |
| **REPLACE-FULL** (b945-scale, no clip) | 0.999 | 0.746 | +2.74 | +2.85 | +1.30 | **+6.89** | [−1.05, +14.69] | net-pos *(artifact)* |
| REPLACE-CLIP$5/rung | 0.944 | 0.746 | +14.3 | −15.2 | +0.67 | **−0.14** | [−3.0, +2.8] | breakeven |
| REPLACE-CLIP$2/rung | 0.922 | 0.716 | +12.0 | −12.6 | +0.42 | **−0.24** | [−2.1, +1.6] | breakeven-neg |
| **COEXIST q=1/8** (honest 8th entrant) | 0.980 | 0.847 | +0.95 | −0.75 | incl | **+0.35** | [−0.10, +0.82] | breakeven |
| COEXIST q=0.879 (equal split) | — | — | — | — | — | +2.16 | [−0.94, +5.28] | breakeven |
| COEXIST q=1.0 (upper bound) | — | — | — | — | — | +2.35 | [−1.10, +5.88] | breakeven |

The trade-tape calibration moved the static ladder from FIFO's −$1.8..−2.8 to REPLACE's +$6.89 — a +$8.7–9.7 swing.
**The entire swing is the fill model**, not a new edge: FIFO pessimistically assumed we sit behind the whole queue
and chase the bid (bad prices, bad pairing); REPLACE inherits b945's realized cheap fill *prices* via the tape and
applies his measured ~12–15% capture rate. The improvement is the **price channel**, not deployable alpha.

---

## 3. THE VERDICT — does it clear for us?

**No.** The trade tape makes queue capture *measurable* (operator correct on the methodology) but the strategy
**still does not clear** for a new operator. REPLACE-FULL's headline +$6.89/slug is not real edge:

1. **It does not reconcile to him.** On the *same 1,333 slugs*, REPLACE = +$6.89/slug while his own realized
   `gt_pnl` = **+$2.75** and `total_nofee` = **+$2.54**. REPLACE claims **~2.5× his actual PnL** while buying
   **half his volume** (867 vs 1,743 sh/slug) at **worse pricing** (pvs 0.999 market-average vs his 0.9697 edge).
   A model that under-trades, mis-prices, yet out-earns the wallet 2.5× is mis-specified, not optimistic.

2. **Its positive residual (+$2.85) is a fill-model artifact.** REPLACE fills only against *observed taker-sell
   flow*, which structurally leaves **winner-heavy** unpaired inventory (winner trades up → more late sell-flow to
   capture → more winner shares that redeem $1). Its inventory is *more* imbalanced than his (|up−dn|/total 0.298 vs
   0.128) but smaller, so the residual prints positive. **His real residual is −$19.44/slug** (balanced book, holds
   the unpaired *loser* legs to $0). Strip the artifact and REPLACE collapses toward his actual numbers.

3. **The mean is a fat tail, not a center.** REPLACE median net = **−$1.01/slug**, win-rate **45.5%**, **t=1.73**
   (NS), bootstrap CI **[−0.89, +14.57] straddles zero**. **Top-5 slugs = 54% of total profit**; 5–95% trimmed mean
   = **+$2.52**, ex-top2 = +$5.07. The +$6.89 is dragged up by a handful of slugs.

4. **Any throttle kills it.** CLIP$5 → −$0.14, CLIP$2 → −$0.24 (a "+$8.44" cheap-first allocator was rejected as a
   selection artifact — flips to −$8.19 under proportional alloc). At b945's full unthrottled scale the only number
   above zero is the artifact-laden FULL.

5. **COEXIST — the honest case — is breakeven.** A real new entrant has no early-GTC time-priority moat, so it
   reaches *only* the 64% on-tape flow (the 36% below-bid moat is unreachable) at his measured rate × q. Base
   q=1/8 = **+$0.35/slug, CI [−0.10, +0.82], t=1.50 NS, win-rate 47.5%**, ex-top2 +$0.25 (29% of mean in 2 slugs).
   **Every q from 1/8 to 1.0 has a CI95 lower bound below zero.** And COEXIST is itself optimistic — it inherits his
   realized cheap fill *prices* via the tape and only haircuts *volume* by q; a real entrant would also get worse
   prices.

`corr(per-slug capture, pnl) ≈ 0` is the clincher: capturing *more* flow does not make a slug more profitable. The
edge was never flow-share — it is the cheap winner-leg *price* from early time-priority, which is exactly the part
a new entrant cannot reproduce.

---

## 4. Honest correction: was "queue priority unmodellable offline" wrong?

**Partly wrong — and the correction is precise.**

**The trade tape CAN reconstruct:**
- The **queue-consumption process**: every taker-sell print at price P is a bid being consumed; aggregating his
  fills vs all tape-sells at (slug, outcome, 1¢) gives his **realized per-level capture rate** directly.
- His **realized fill prices** and the resulting cheap-pair signature (pvs, winner-vs-loser vwap), where the tape
  is complete.
- The **capture-rate calibration** that substitutes for an explicit queue model: instead of simulating exact
  FIFO/pro-rata rank, we *measure* the fraction of flow he actually got. This is what we previously dismissed as
  "unmodellable." It is ~14% raw, ~12% dollar-weighted, with a defensible 0.07–0.14 range.

**The trade tape CANNOT reconstruct:**
- **Exact rank among simultaneous resters at the same price/cent** — that needs the CLOB **order-delta book feed**
  (placements/cancels with timestamps) which we do not have. The capture *rate* is the aggregate substitute, but
  it cannot tell us *who* was ahead on any single fill.
- **The 36% off-tape / below-best-bid fills** — his fills at 1¢ buckets with no contemporaneous same-cent sell
  print. These are the realized output of his early-GTC time-priority moat; the tape under-records them (it is a
  **lossy** observation: 16% of overlap buckets and 285 slugs have his fills > tape sells). A new entrant cannot
  reach them, and we cannot simulate them from the tape.

So: **queue priority is modellable as a calibrated capture rate (yes), but the specific moat that makes b945
profitable — early time-priority below the contemporaneous best bid — is exactly the unmodellable, unreachable
part.** "Unmodellable offline" was too strong about the *measurement*; it was correct about the *edge transfer*.

---

## 5. Updated deploy verdict + TVRUST implication + next action

**Deploy verdict: NO (unchanged).** The offline verdict does **not** change. Calibrating queue capture from the
trade tape is a genuine methodological win and confirms the edge is real *for him*, but:
- REPLACE's net-positive is an artifact (over-states his own PnL 2.5×, positive only on fat tails + a fill-model
  residual quirk; dies under any throttle).
- COEXIST — the only honest scenario for a new entrant — is **breakeven with a CI straddling zero at every q**.
- The deployable gap is precisely the 36% below-bid early-time-priority fills, which neither the tape nor a new
  entrant can reach.

**TVRUST implication.** The B945 article-infra plan (`B945_ARTICLE_INFRA_GAP_ANALYSIS §8`) hinges on early-GTC
two-sided ladders placed ~24h pre-window to win time-priority. This analysis shows that moat is worth ~16% of
extra (off-tape) flow and the cheap winner-leg price — i.e. it is **the whole edge**, and it is **only** capturable
by *actually being early in the real CLOB queue*, not by any offline replay. **TVRUST must place real resting
GTC orders early and measure live fills**; there is no offline path to validate it. Before building, the cheaper
de-risk is to confirm the live capture rate matches the measured ~12–14% — if a paper/live probe gets materially
*less* (because we lack his standing relationships / placement latency), even COEXIST's breakeven evaporates.

**Single next action.** Run a **live $25 two-sided early-GTC probe on ~30 btc-15m slugs**: place both legs at his
typical pre/early-window prices, record (a) realized per-level capture vs the contemporaneous tape, (b) the
below-bid fill fraction we actually achieve. This is the one number neither the tape nor any backtest can produce,
and it decides whether the queue-priority moat transfers to us at all. Do not commit TVRUST engineering until that
live capture rate clears ~12%.

---

*Sources: `D:/tmp_qp/capture_buckets.parquet`, `replace_full.parquet`, `replace_results{,2}.json`, `cap/bandgrid.json`,
`sellflow.parquet`; `strategy_lab/wallet_hunt/cache/0xb945945d/{fill_tape_full,per_slug_paired_ledger}.parquet`;
trade tape `data/v4/canonical/trades_polymarket/btc.parquet`. Builders: `strategy_lab/wallet_hunt/_b945_build_tape.py`,
`_b945_coexist_econ.py`. Prior: `B945_EDGE_GAP_DECOMPOSE_2026_06_13`, `B945_PNL_AUDIT_2026_06_12`, `B945_ARTICLE_INFRA_GAP_ANALYSIS`.*
