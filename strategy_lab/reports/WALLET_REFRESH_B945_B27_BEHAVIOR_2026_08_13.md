# b945 + b27 refreshed — what the reference wallets ACTUALLY do — 2026-08-13

Fresh pull via data-api `/activity` (time-cursor pagination past the 3,500-offset cap).
Scripts: `wallet_hunt/_refresh_b945_b27_2026_08_13.py`, `_analyze_updown_behavior_2026_08_13.py`.

| wallet | coverage | trades | redeems | **merges** |
|---|---|---:|---:|---:|
| `0xb945945d` | Jul 24 → Aug 13 (20d) | 123,184 | 6,253 | **0** |
| `0xb27bc932` | Aug 11 → Aug 13 (2.5d, hit 120k cap) | 121,953 | 32,026 | **20,992** |

b27 does in 2.5 days the trade count b945 does in 20. Both are pure up-down; b27 had only
$29,670 of non-updown volume.

---

## 1. The comparison table

| | **b945 @ 15m** | b945 @ 5m | **b27 @ 5m** | us (live, Aug 13) |
|---|---:|---:|---:|---:|
| windows in sample | 1,063 | 1,827 | 545 | 14 |
| two-sided windows | **99.7%** | 48.5% | **99.3%** | ~59% |
| **paired : residual** | **5.53** | 0.42 | **4.07** | 0.50 → 1.46 |
| pair vwap-sum (wtd) | **0.9762** | 1.0230 | **0.9832** | 0.915–0.97 (pvs) |
| margin per paired sh | 2.4¢ | negative | 1.7¢ | 3–8¢ |
| paired sh / window | 939 | 35 | 511 | ~10 |
| residual sold before | **0.0%** | 0.0% | **0.0%** | ~41% (recycle) |
| residual hit rate¹ | ~46.6% @ px 0.458 | ~57% @ 0.565 | ~22%¹ @ 0.510 | 10–21% |
| buy timing | spread; peak 5–10m (32.7%) | back-loaded | **FLAT all window** | 44% in first 60s |
| late-buy price vs early | 0.428 vs 0.463 | 0.533 vs 0.556 | 0.454 vs 0.502 | — |
| merges pairs for recycle | no | no | **yes — 21k in 2.5d** | built, not wired |

¹ disposition attribution is approximate: REDEEM lags the sample edge and merges consume
pairs before redemption, so b27's "expired 77.6%" is overstated — treat hit rates as bands.
b945 15m monthly ratio: Jul 2.33 → Aug 3.52 (rising; June decode said 4.40 — consistent).

New mechanism detail (n=1,063 15m windows): **in the final 40% of the window, 58.9% of
b945's buy-dollars go to the LIGHT side** (avg px 0.468) vs 41.1% to the heavy side (px
0.391). Late buying is pair *completion*, not accumulation — exactly `v5_latepair`'s rule.

---

## 2. The five things this changes

### (a) The masters take THIN pairs. We hunt cheap ones. That's the whole difference.
b945 pairs at **0.976**, b27 at **0.983** — 1.7–2.4¢ per pair, right against the measured
venue constraint (bid-sum 0.99 in 94% of ticks). They make money on **ratio × volume**
(500–950 paired sh/window), not on margin. Our whole design — `quote_depth_ticks=2`,
proposals to gate `pair_max_sum` at 0.88 — hunts 5–12¢ pairs deep in the book, and deep
quotes are precisely what fills one-sided. **Cheap pairs and naked residual are the same
purchase.** The 0.99 `pair_max_sum` default was never the bug; depth-2 quoting is.

### (b) Nobody sells residual. Ever. The control is at entry.
0.0% of residual sold, both wallets, 3,435 windows. They ride 100% to settlement — b945's
15m residual hits ~46.6% at entry 0.458 ≈ **breakeven, i.e. the residual is ~free**, because
it's small (1/5.5 of paired) and adversely-selected-but-cheap. Our sell-at-30s recycle was
still right *for our current entries* (measured: selling beat holding) — but it's
compensation for bad entry selection, not part of the reference strategy. Fix the entry
(touch quotes, light-side-only late) and the recycle becomes mostly idle.

### (c) They trade the WHOLE window — but late money only completes pairs.
b27 is flat across the 5m window (20/19/18/19/24%); b945 peaks mid-window. Nobody
front-loads like our 44%-in-60s. And late fills are *cheaper* for them (0.43–0.45 vs
0.46–0.50 early) because the late light side IS the falling side being completed into a
pair. `v5_latepair` is directionally exactly this — the frozen hypothesis (ratio ≥ 2.0,
net ≥ base) just got independent support from 1,063 b945 windows.

### (d) b27 merges — and that solves our §8.3 capital problem.
20,992 MERGE events in 2.5 days: every matched pair is burned back to $1 instantly instead
of waiting ~47s+ for redemption. At our scale ($55 pUSD, 73 `not enough balance` rejections,
second legs refused → naked legs) **merge is not "only speed", it is the capital throughput
that lets the second leg exist.** `tv-merge` is already built and proven dry-run — wire it:
auto-merge matched pairs ≥ N shares.

### (e) b945's 5m book is NOT the pair game — use b27 as the 5m reference.
b945 @5m: 48.5% two-sided, ratio 0.42, pair sums >1, back-loaded — a small different
(directional?) game. Every 5m design decision should benchmark against b27; every 15m
decision against b945. And b945's 5.53 @ 0.976 on 15m says our neglected `btc_15m_v3`
sleeve is on the structurally *easier* timeframe — 3× more time per window to complete
pairs.

---

## 3. Concrete follow-ups (for the arm roster)

1. **NEW paper arm `v5_touch`** (pre-register before enable): `quote_depth_ticks 2→0/1`,
   `pair_max_sum` stays 0.99, GLT tight, late-window light-side-only (share `v5_latepair`'s
   late rule). Frozen bar: **ratio ≥ 2.0 AND pair-sum ≤ 0.99 AND net ≥ base v3** at
   n ≥ 2,000. This is the b27 imitation arm; d1's post-epoch lead (best honest fill-rate
   79.7%, best ratio 0.61) already points the same direction.
2. **Wire auto-merge** of matched pairs (engineering; `tv-merge` exists) — unblocks capital
   before any re-arm.
3. **`v5_latepair`**: unchanged, let it run — its rule is now externally validated.
4. **15m**: after the sim reconciles (§8.4), evaluate a `btc_15m` live candidate against
   b945's 5.53 @ 0.9762 benchmark.
5. Residual recycle: keep while entries are depth-2; expect to retire it if `v5_touch` wins.

## 4. ADDENDUM (same day): b945 maker-vs-taker PROVEN, and the taker leg decoded

Three independent methods agree (`_b945_maker_taker_proof_2026_08_13.py`):

1. **Venue flag** (`/trades?takerOnly=`): 500 taker fills span 10.4h vs 500 total fills
   spanning 0.9h → **~91% of fills are MAKER by count; taker = 15.5% by USD**
   ($59,945 of $386,034 in the Aug 11–13 span).
2. **MAKER_REBATE**: **$12,953** accrued Apr 21 → Aug 13 (was $3,645 at the June audit —
   the operation 3.5×'d). Rebates only accrue to makers.
3. **On-chain** (via Ireland's Alchemy RPC): these markets trade on exchange
   `0xe111180000d2663c0091e4f400237545b87b996b`, event `OrderFilled`
   (topic0 `0xd543adfd…`). Topic2 = order OWNER, topic3 = taker counterparty. In
   venue-flagged-taker txs the wallet shows 22× in the taker-counterparty slot across 12
   txs (≈2 maker orders swept per completion) + 12× as owner of its own crossing order —
   the venue classification is confirmed at the log level.

**What the 9% taker leg IS** (3,000 taker fills, Aug 11–13):
- **100% BUY — zero taker sells** (and zero sells of any kind: 0 in 37,727 fills)
- avg price **0.705** vs maker avg ~0.415 → always the EXPENSIVE leg
- back-loaded: 53–56% of taker USD in the final 40% of the window
- both timeframes equally ($30k @5m, $29k @15m)

**Mechanism: taker pair-completion.** Rest maker both sides; when the cheap side fills and
the window ages, CROSS THE SPREAD and buy the opposite leg (~0.70) to lock the pair
(0.27 maker + 0.70 taker ≈ the measured 0.976 pair sum). This is exactly the
taker-completion (COC) we removed in the June I0 cleanup ("MAKER-ONLY spec §4") and the
`v4_coc` arm retired Jul 23 (+0.417/w, t=3.29 while it ran). The reference wallet does it
with 15% of its volume. → Revive as a pre-registered arm: late-window light-side
completion **as taker**, gated on `maker_vwap + ask ≤ ~0.98`.

Caveats: data-api has no maker/taker flag on /activity (proven via /trades + chain instead);
disposition percentages are bands not points (redemption lag + merges); b27 sample is 2.5
days (velocity hit my 120k cap — extend `MAX_RECORDS` if the month matters).
