# PAIR-ARB HEAD-TO-HEAD — our Ireland ladder vs Agile-Spacing, same days, same regime
**2026-07-02. OUR side: `poly_ladder_btc_15m_v2` fresh pull, 142 clean-settled windows (Jun 30 14:31 → Jul 2 07:15). HIS side: `CE25_FRESH_DECODE_2026_07_02.md` (288 slugs, Jul 1 21:17 → Jul 2 05:48, all resolved). Overlapping time = a true controlled comparison.**

## 1. The table
| metric | HIM (8 markets) | OUR ladder (btc-15m) | read |
|---|---|---|---|
| slugs·windows / day | ~810 | 84 | he's 10× wider (8 mkts + both TFs) |
| $ deployed per slug | ~$160 mean ($38 median/side) | ~$14.4 | he's ~10× bigger per slug |
| pair_fraction | **0.55** | **0.564** | IDENTICAL inventory structure |
| pvs (paired sum) | mean 1.017 · 41% <1.00 | **mean 0.853 · 80% <1.00 · 76% <0.97** | WE pair much cheaper |
| fees | −47% of gross (if taker) | $0 maker + rebate | structural edge OURS |
| residual outcome | slug WR 51%, mean +$2.19 → his remainder wins ~half | entry 0.396, **wins 14.1%** (needs 40%) → −$2.46/win | THE divergence |
| net | **+$1.8k/day** (fee-adj pace) | **−$76/day** (−$0.91/win CI[−1.50,−0.32], n=142) | |
| paired engine alone | not separable | **+$1.51/win = +$127/day** | our locked arb is healthy |
| working capital | ~$2.4–5k | ~$15–30 | capital is nobody's constraint |

## 2. The verdict: we built his machine with the fill selection INVERTED
Same pair_fraction (0.55 vs 0.56). We pair CHEAPER (0.853 vs 1.017). We pay ZERO fees vs his 47% drag. **And he prints +$1.8k/day while we bleed −$76/day.** The entire gap is one thing: **whose flow fills you.**

- **OUR fills:** resting bids AT the touch, absorbed by continuous taker sell-flow. At window scale that flow is INFORMED — the side being dumped loses 85% of the time. We are the exit liquidity for informed sellers → residual wins 14.1% vs 40% breakeven (−5.5σ). The cheap pairs are the *consolation prize* for eating toxic flow.
- **HIS fills:** ~12 clips/slug spread across the whole window at dip prices (pvs min 0.34). Whether he dip-TAKES or rests DEEP bids that only fill on spikes-through, his fills are **overshoot-selected**: he buys transient dislocations that mean-revert (exactly our V2 markout finding — the filled cheap side rises +8¢/30s). His residual is the *profit engine* (WR ~51% at cheap entries = +EV); his pairs are inventory control, not the edge — he even pays >$1 for 41% of them and doesn't care.

**So: are we mimicking him? Structurally yes, economically no — we harvest the pair and eat the residual; he harvests the residual and tolerates the pair.** The ladder's at-touch quoting is the one design choice that inverts the economics.

## 3. What this means for the implementation (v3+)
Two fixes attack it from opposite ends — we have BOTH already in the pipeline:
1. **v3 residual management (in flight):** flatten/recycle the residual → kills the −$2.46. Even at 0 residual, net ≈ paired +$1.51/win ≈ **+$127/day on btc-15m alone** (our counterfactual said +$1.2–1.6). This works WITHOUT copying his selection.
2. **Dip-selected fills (= the `sumpair_osc` sleeve, enable pending):** gate accumulation on the Binance-lag dip signal instead of resting at the touch — that IS his fill selection, and our V2 offline work already validated the mechanism (+8¢/30s markout on dip fills). **The merged design — dip-gated two-sided accumulation with pair-lock — is literally him.** The sumpair_osc shadow is the test of his half; the ladder v3 is the test of ours.
3. **Then scale** (his league): BTC-5m + ETH next (skip SOL/XRP — negative even for him this window), multi-clip re-test on clean delta data (his 12 clips/slug is live counter-evidence to our MAX_CLIPS=1 artifact verdict), capture ladder 0.8%→5%+.
4. **Fee asymmetry is our trump card:** if he's a taker, he pays 47% of gross away; the maker version of his machine keeps it. Classifying his fills (vs OUR racer book tape for his btc-15m slugs — we hold the book truth for those exact windows) settles this and is the highest-information next analysis.

## 3b. ✅ FILL CLASSIFICATION RUN (2026-07-02, `_ireland_6day/ce25_classified.csv`) — he is a HYBRID, and his maker half rests BELOW the touch
Method: 1,081 of his in-coverage fills (Jul 2 00:56→05:48, btc/eth/sol — XRP unclassifiable, no XRP books on storedata) joined to the pre-fill VPS3 book (last snapshot ≤ fill-second; book age at fill median **0.78s**, p90 2.4s — fresh). 820 classified:

| class | fills | $-weighted |
|---|---|---|
| **MAKER (at/below bid0)** | 48.5% | **42.5%** |
| INSIDE spread | 16.0% | 10.4% |
| **TAKER (at/above ask0)** | 35.5% | **47.2%** |

Robust to tightening (age≤3s: 45/11/44 by $). Splits: 5m = **63% maker$** / 32% taker$; 15m = 39% maker$ / 50% taker$; BTC most maker-ish (48%).

**The mechanical key: his maker fills rest BELOW the best bid — median −1 tick, p10 −5 ticks.** He does NOT quote at the touch. His passive fills only happen when price spikes down *through* his deep bids = overshoot-selected by construction. His taker half buys at the ask (dip-taking, consistent with the V2 lag-dip mechanism and his sub-$1 pair sums). **Both halves of his flow are dip-selected; our ladder's at-touch quotes are the exact opposite.**

**Translation to our stack — he is literally our two engines combined:**
- His taker half (47% of $) = **`sumpair_osc`** (dip-gated taker clips) — enable pending.
- His maker half (42% of $) = **the ladder with quotes moved DEEP (−1…−5 ticks below bid)** — a one-parameter change to v3 (quote-depth offset), which directly attacks our −5.5σ at-touch adverse selection.
- Fee refinement: only ~47% of his dollars pay taker fees → his true daily is HIGHER than my fee-adj estimate (~up to $2.5k/day pace). A deeper-maker-tilted copy keeps more per dollar but captures fewer dips — the paper A/B (deep-ladder vs sumpair_osc) measures that trade-off directly.

## 3c. ✅ B945 FRESH DECODE (2026-07-02) — the actual mimic target, same treatment
`0xb945945d…db68` (l5Zn1bWoM8eTsK, the "6 edges" author — the wallet our ladder replicates). data-api pull = 3,005 fills / 264 slugs / **2.95 days** (Jun 29 09:10 → Jul 2 07:59), all resolved via gamma. Files: `_ireland_6day/b945_{fills_clean,per_slug_2026_07_02,classified}.csv`.

**Economics:** lifetime **+$28,286** (was +$21,742 mid-June → **+$6.5k in 3wk ≈ $310/day avg**; this 2.95d window: net +$283 ≈ **+$96/day** fee-adj, up to ~$180/day if his maker share pays no fee). 1d leaderboard: −$179 (lumpy). Portfolio in play $1,284. **⚠️ he is NOT the 1–2k/day wallet — that's ce25/Agile-Spacing (8 markets). b945 (BTC-only) runs ~$100–310/day.**

**Universe update:** BTC only, but **15m AND 5m now** (1,919 vs 1,581 fills — he added 5m since the June decode). **And the split is the story: btc-5m +$793 (+$4.22/slug, n=188) vs btc-15m −$509 (−$6.70/slug, n=76).** His profit engine THIS window is entirely 5m; **he lost on btc-15m — the exact market our ladder trades — in the exact days our ladder lost.** Our −$76/day on 15m is partly regime, not purely design: two-sided accumulation on btc-15m was hostile for everyone these 3 days.

**Signature (vs his own June profile):** evolved the same direction as ce25 — 11.4 fills/slug (clips med $11), fills spread across the window (p50 275s, only 8% <60s), pair rate 66%, **pair_frac only 0.36**, pvs med 1.000 (50% <1), price med 0.60 with **58% of buys ≥0.55** — much less "locked-pair capture," much more selective directional accumulation with pairing as inventory control.

**Classification (n=115 classifiable — VPS3 snapshot gaps; book age 0.24s where covered):** MAKER **42.8%$** / INSIDE 5.4% / TAKER **51.8%$** — same hybrid as ce25 — and his maker bids rest **−3 ticks median (p10 −9) below the touch**. Deep-book spike-through fills, never at-touch.

**Convergent evolution = the strongest design signal we have:** two independent profitable wallets (ce25 8-market, b945 BTC-only) both moved to the SAME machine — deep resting bids (−1…−9 ticks) + dip-taking clips, laddered across the whole window, loose pairing, hold+redeem. Nobody profitable quotes at the touch. Our at-touch ladder is the outlier design, and it's the one bleeding.

## 3d. Design deltas for OUR implementation (updated)
1. **Deep quotes** (`TV_LADDER_QUOTE_DEPTH_TICKS` −2 default, sweep −1…−5): confirmed by BOTH wallets. Kills the at-touch adverse selection at the source.
2. **Add btc-5m ladder mirror** alongside 15m: both wallets print on 5m this window; 5m = more windows/day (288 vs 96) and leans MORE maker for both of them (ce25 63%$, b945 38–60%). One env/market change.
3. **Keep v3 residual management** — our data still shows residual is OUR bleed; b945 tolerates residual only because his fills are dip-selected. Belt (deep quotes) + suspenders (residual mgmt), measure which carries.
4. **Keep the pvs gate but don't worship it** — neither wallet locks cheap pairs as the edge (b945 pvs med 1.000); the paired engine is inventory control for them. Ours (+$1.51/win) is still our best working part — keep it, but the fill-selection fix is the main event.

## 4. Sequence (all $0 paper until gates)
1. TV agent: ladder v3 (residual mgmt) + enable sumpair_osc — both specs already delivered.
2. Me: maker-vs-taker classification of his btc-15m fills against our racer tape.
3. After ~1wk: compare three tapes — ladder v3 (at-touch + managed residual) vs sumpair_osc (dip-gated) vs HIS live tape → pick the winning fill-selection, merge, then widen markets.
Gate to capital stays: total_net CI>0 on ≥1wk paper + watchdog deployed.
