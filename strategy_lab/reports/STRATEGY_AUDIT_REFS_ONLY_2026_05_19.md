# Strategy audit — REFERENCE WALLETS ONLY

**Date**: 2026-05-19 (revision)
**Replaces**: `STRATEGY_AUDIT_VS_LB_API_2026_05_19.md` (which mixed new counterparties with references — methodological error)
**Scope**: Validate our 3 strategy specs (ACC-M, ACC-H, MAS) using **ONLY** the 16 reference wallets they were built from. No extrapolation from new counterparties.

---

## Why this revision exists

The previous audit drew conclusions from two new counterparty wallets (`loser2 = 0x76d4d470` and `aoe2gamer = 0xfb0f1765`) that we discovered via LB-API mining. **Neither is in our 16-wallet reference set.** Strategy specs should be audited against the wallets that informed them — not strangers we just discovered.

This audit uses **only the 16 wallets in `_addr_map.json`**.

---

## TL;DR — what the reference wallets actually tell us

| Spec area | Original audit verdict | Reference-only verdict | Why changed |
|---|---|---|---|
| ACC-M core logic | ✅ correct | ✅ **STILL correct** | 4 refs perfectly match spec |
| ACC-M MERGE_THRESHOLD=5 | ⚠️ raise to 10-15 | ✅ **leave at 5** | Profitable ref `xuanxuan008` does 1.38 merges/slug — not a problem |
| MAX_MERGES_PER_HOUR cap | Add new cap | ❌ **don't add** | Based on stranger wallet, not our refs |
| ACC-H core logic | ✅ correct | ✅ **STILL correct** | Bonereaper matches spec |
| ACC-H V3f rollout | Phase A→C→B→D | 🟡 **deploy full V3f** | Composite already shows in BUYs; phasing adds 16 days for no gain |
| MAS-V1 (upfront mint) | ❌ inferior, use MAS-V2 | 🟥 **NO REFERENCE for either variant** | Neither MAS ref currently mints |
| MAS deployment | Replace with V2 | 🟥 **POSTPONE MAS entirely** | No live reference doing MAS in current /activity |
| PnL projections | Cut 50-70% | ✅ **still cut 50-70%** | LB-API run-rates apply to refs too |

The most important change: **MAS should NOT be in week-1 deployment.** Both `0xf7f0b0b1` (wapol) and `0xd44e2993` (sherlockhomie) — the wallets we cited as MAS examples — do NOT currently practice mint-and-sell. We've been building a strategy on a misclassification.

---

## 1. ACC-M references — DOES THE SPEC MATCH?

### What the references actually do (v3 live data)

| Wallet | Role | px_med | sz_med | n_slugs | %paired_buy | %BUY | n_merge | merges/slug | TFs | slugs/h | LB 30d |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `0x04b6d7e9` | ACC-M-ref | $0.450 | $3.69 | 21 | **100%** | 100% | 0 | 0 | 5m+15m+long | 13.2 | $61k ($2.0k/d) |
| `0xb27bc932` | ACC-M-scale | $0.490 | $3.32 | 11 | **100%** | 100% | 0 | 0 | 5m only | 13.5 | $52k ($1.7k/d) |

### Spec parameter validation (ACC-M)

| Param | Spec value | Ref evidence | Verdict |
|---|---|---|---|
| `POST_SIZE: 5` | 5 shares | $3.32-3.69 med USDC ÷ ~$0.47 = ~7 shares per fill (close to 5) | ✅ correct |
| `MIN_BID_PRICE: 0.05` | 5¢ | px_p25 = $0.25-0.30 | ✅ correct |
| `MAX_BID_PRICE: 0.95` | 95¢ | px_p75 = $0.65-0.70 | ✅ correct |
| `MAX_SUM_BIDS: 1.00` | $1 | Inferred from 100% paired_buy + profitable | ✅ correct |
| `CANCEL_THRESHOLD: 0.03` | 3¢ | (from chain decode, not /activity-visible) | ✅ verified separately |
| `MAX_ORDER_AGE_S: 20` | 20s | (from chain decode) | ✅ verified separately |
| `MERGE_THRESHOLD_PAIRS: 5` | 5 pairs | **0 merges in window for both refs** | ✅ correct — see below |
| `MAX_IMBALANCE_SHARES: 5` | 5 | 100% paired_buy implies ~0 imbalance | ✅ correct |
| `MAX_CONCURRENT_SLUGS: 4` | 4 | 13.2 slugs/h × 5m = ~1.1 concurrent | ✅ correct |
| `cells = btc_5m, btc_15m` | 2 cells | `0x04b6d7e9` does 5m+15m+long, `0xb27bc932` does 5m only | ✅ correct |
| `wallet_seed_usdc: 50` | $50 | (capital not directly observable from /activity) | unknowable |

### Why MERGE_THRESHOLD=5 is fine

Original audit's argument was: `loser2 (0x76d4d470)` does 573 merges in 2.5h → loses $27k/30d → merge over-frequency causes losses → raise threshold.

**But `loser2` is not in our reference set.** Looking at our actual references:

| Wallet | merges in window | merges/slug | profitable? |
|---|---|---|---|
| `0x04b6d7e9` (ACC-M-ref) | 0 | 0.000 | yes (+$2k/d) |
| `0xb27bc932` (ACC-M-scale) | 0 | 0.000 | yes (+$1.7k/d) |
| `0xeebde7a0` (ACC-H-ref) | 0 | 0.000 | yes (+$6k/d) |
| `0xcfb103c3` xuanxuan008 (originally "LOSER") | **327** | **1.380** | yes (+$2.5k/d per LB) |
| `0xce25e214` (originally "LOSER") | 0 | 0 | yes (+$4.6k/d per LB) |
| `0x7dfc8aa2` (originally "LOSER") | 0 | 0 | yes (+$2.2k/d per LB) |

`xuanxuan008` does 1.38 merges per slug at $15 median notional and **profits $2.5k/day**. They merge ~5-10 pairs per merge transaction → fewer gas calls per unit profit.

**Conclusion**: high merge volume is not inherently bad. Merge ECONOMICS depend on size per merge:
- `xuanxuan008`: 1.38 merges/slug × $15 med = high-value merges → profitable
- `loser2` (not a ref): 5.30 merges/slug × $2.55 med = low-value merges → unprofitable

The spec's `MERGE_THRESHOLD_PAIRS=5` (i.e. merge when 5+ pairs accumulated) already enforces "batch merges" — exactly the pattern xuanxuan008 uses. **Spec is correct.**

### Revised ACC-M recommendation

✅ **Deploy ACC-M as currently spec'd. No parameter changes needed.**

The only addition worth considering: log `merge_per_slug` metric to alert if we drift toward the `loser2` anti-pattern (5+ merges/slug × <$3 size).

---

## 2. ACC-H reference — DOES THE COMPOSITE TAKER MATCH?

### Bonereaper's recent live data

| metric | value |
|---|---|
| Verdict (v3) | PURE_PAIR_ARB_MAKER |
| pct_paired_buy | **85.7%** (vs 100% for ACC-M refs) |
| pct_buy | 100% (no SELLs) |
| n_slugs | 42 |
| Assets | BTC (2,943) + ETH (516) |
| TFs | 5m (2,121) + 15m (1,277) + long (43) + 4h (18) |
| trades/h | 2,754 |
| slugs/h | 33.4 |
| px_med | $0.47 |
| sz_med | $3.96 |
| n_merge | 0 |
| LB 30d | $181k ($6.0k/d) |

### Interpretation

The pickup classified Bonereaper as HYBRID (68% paired + 81% leftover-on-winner-size-weighted = directional taker side). In recent /activity:

- 100% BUYs — consistent with HYBRID **IF** market-buys from V3f triggers show as BUY (they do — taker market-buys are still side=BUY)
- 85.7% paired_buy — slightly LOWER than ACC-M refs (100%). The 14.3% non-paired slugs could be the taker-side firing on single-outcome buys without a paired bid filling
- Wide TF mix (5m + 15m + long + 4h) — suggests deployment across more cells than our spec
- ETH presence — already trading ETH in addition to BTC

### Spec parameter validation (ACC-H)

| Param | Spec value | Ref evidence | Verdict |
|---|---|---|---|
| `TAKER_SIZE: 5` | 5 shares | $3.96 med size = ~8 shares avg (close to 5) | ✅ correct |
| `MAX_TAKER_PRICE_DISCOUNT: 0.50` | <$0.50 for Rule A | $0.47 px_med means many fires fall under this | ✅ plausible |
| `MIN_ASK_DROP_60S: 0.03` | 3¢ | (from chain decode — V3f composite) | ✅ verified separately |
| `MIN_TRADE_DROP_5S: 0.02` | 2¢ | (from chain decode) | ✅ verified separately |
| `MIN_S_BETWEEN_TAKER_BUYS: 5` | 5s throttle | (we can't observe this from /activity) | unknowable |
| `MAX_TAKER_BUYS_PER_SLUG: 50` | 50 | 42 slugs × ~50 trades/slug = 2,100 vs actual 2,754 = ~65 fills/slug | ⚠️ may be slightly low |
| `MAX_IMBALANCE_SHARES: 10` | 10 (looser than ACC-M) | 85.7% paired_buy + 14.3% non-paired = consistent with looser imbalance | ✅ correct |
| `ABSOLUTE_MAX_INVENTORY: 100` | 100 | (capital not visible from /activity) | unknowable |
| `cells = btc_5m` | 1 cell start | Bonereaper does BTC + ETH × 5m + 15m + long + 4h (6+ cells) | ⚠️ ref runs more cells |

### Phased rollout — RECONSIDER

Original audit recommended: deploy V3f composite in 4 phases (A → A+C → A+B+C → full V3f) with 48h validation each. Total ramp: 16 days.

**But the composite is INVISIBLE in /activity** — taker market-buys show as `side=BUY` just like maker-BID fills. We can't validate or invalidate individual rules from /activity alone.

The only way to verify each rule independently is **chain-trace from our own deployed wallet** — and that requires having shadow data anyway.

**Revised recommendation**: deploy full V3f from the start, with structured shadow logging:

```python
# In ACC-H taker decision logger
LogTakerDecision(
    slug=..., side=..., ts_us=...,
    rule_fired="A" | "B" | "C" | "D",
    discount_capture_value=...,
    sharp_drop_value=...,
    early_slot_value=...,
    buy_pressure_value=...,
    decision="BUY" | "SKIP",
)
```

Then within the first 48h shadow window, we have per-rule attribution. If Rule B underperforms, we disable it. This is faster than 16 days of phased rollout that we can't even validate via /activity.

### Cell expansion timing — REVISE

Bonereaper currently operates on BTC + ETH × 5m + 15m + long + 4h. The spec starts BTC 5m only. Pickup expansion plan: day 7 → btc_15m, day 14 → eth_5m+15m.

Per LB-API, Bonereaper makes $6k/day across all 6+ cells. At BTC 5m only, the per-cell PnL is probably 1/6 of that = $1k/day at full Bonereaper scale.

**Revised**: Stay BTC 5m for 14 days (instead of 7) to fully validate latency + queue dynamics on the simplest cell. **DO add btc_15m and ETH cells together at day 14** (parallel expansion vs sequential) — that matches Bonereaper's actual cell mix.

### Revised ACC-H recommendation

✅ Deploy ACC-H with **FULL V3f** from start (don't phase).
✅ Build per-rule shadow logging for attribution.
⚠️ Slow cell expansion: 14 days BTC 5m only, then add btc_15m + eth_5m + eth_15m together.
⚠️ Reduce `MAX_TAKER_BUYS_PER_SLUG` from 50 → 30 (Bonereaper averages ~65 TOTAL fills/slug, with both maker BIDs and taker buys — taker portion alone unlikely to exceed 30).

---

## 3. MAS references — STRATEGIC PROBLEM DISCOVERED

### What we thought (pickup)

`0xf7f0b0b1` (wapol) and `0xd44e2993` (sherlockhomie) were our two mint-and-sell references. Pickup said: "All 3 profitable up-down wallets we've found so far ($10k-$344k/day, identical signature)" → MAS strategy spec built on this.

### What v3 actually shows

| Wallet | Role | Verdict | %paired_buy | %BUY | %SELL | n_split | n_merge | LB 30d | LB all-time |
|---|---|---|---|---|---|---|---|---|---|
| `0xf7f0b0b1` (wapol) | MAS-ref | **DIRECTIONAL_TAKER_BALANCED** | 13.0% | 100% | 0% | **0** | 0 | NaN | NaN |
| `0xd44e2993` (sherlockhomie) | MAS-mini-ref | **PURE_PAIR_ARB_MAKER** | 100% | 100% | 0% | **0** | 0 | -$1.4k | $220k |

### Key finding: ZERO SPLIT events for both "MAS" references

The MAS spec is built around:
1. SPLIT (mint pair via splitPosition) at slug start
2. Post ASKs on both Up + Down
3. Redeem leftover at slug close

**Neither reference shows ANY SPLIT events in their last 1,500-3,500 activity records.** They are not currently practicing mint-and-sell.

What they ARE doing:
- `0xd44e2993`: pure pair-arb maker (post BIDs, accumulate pairs, no current SPLIT or MERGE). Per LB, -$1.4k in 30d (mild loss this month, +$220k all-time).
- `0xf7f0b0b1`: directional taker buying (no SELL, no SPLIT, no MERGE). Per LB, no recent data.

### Why we thought they were MAS

Likely sources of misclassification:
1. The original chain decode caught a HISTORICAL window where SPLIT events were present
2. Or SPLIT events were rare even in the chain window and the pattern was extrapolated
3. Or `0xf7f0b0b1`'s "mint-and-sell variant" classification was based on a different on-chain signature we can't see in /activity

**Action**: re-pull SPLIT events from chain for these wallets via Alchemy `getAssetTransfers` filtered to CTF `splitPosition` calls. If zero in last 30 days, MAS is not a live practice.

### MAS spec status

**Strategy specs should map 1:1 to live reference behavior.** Currently:
- ACC-M ↔ `0x04b6d7e9` + `0xb27bc932` ✓ (both validated in v3)
- ACC-H ↔ `0xeebde7a0` ✓ (validated in v3, possibly more cells than spec)
- MAS ↔ ???  ✗ **NO LIVE REFERENCE**

Options:
1. **Postpone MAS deployment** until we find a live MAS practitioner. **Recommended.**
2. **Deploy MAS as theoretical experiment** with very small capital ($25 instead of $100) and accept that we have no benchmark.
3. **Skip MAS entirely** and reallocate capital to ACC-M and ACC-H.

Recommended: option (1) postpone. Reallocate the $100 MAS capital to ACC-M ($75) and ACC-H ($25). Total still $200 across 2 strategies.

### Why the original "MAS-V2 with aoe2gamer" recommendation also fails on reference-only audit

`aoe2gamer` is **not** in our reference set. They're a counterparty we discovered post-hoc. We have no chain decode for them — only LB-API data + /activity.

Defending an "MAS-V2" strategy means betting on a 1-wallet sample we have no chain-level understanding of. **Don't do this.**

If we want a hybrid BID-and-ASK strategy, the right path:
1. Add `0xfb0f17657c9c24293b918adb86362a4d8fc90b02` (aoe2gamer) to our reference set
2. Pull their chain history via `fetch_chain.py` (~20 min)
3. Confirm their pattern over a 7-30 day chain window
4. Then write a spec from THAT decoded data

Until we do that, MAS-V2 is speculative.

---

## 4. Other reference findings worth noting

### F2 cluster (`0xa0a50783`, `0x9dae874a`, `0x7f599984`) — actually MIXED_MAKER

Originally classified as "TAKER mispricing" — but v3 says MIXED_MAKER_BIDS_AND_ASKS for all 3:

| Wallet | %paired_buy | %BUY | %both_sides | n_slugs | px_med | sz_med | LB 30d |
|---|---|---|---|---|---|---|---|
| `0x9dae874a` | 0.0% | 77.1% | 40.0% | 70 | $0.33 | $2.32 | +$49k |
| `0xa0a50783` | 0.0% | 78.7% | 38.8% | 80 | $0.364 | $2.73 | +$46k |
| `0x7f599984` | 2.4% | 72.2% | 39.8% | 83 | $0.39 | $3.10 | +$41k |

Pattern: ~40% of slugs have both BUY and SELL on the SAME outcome (pct_paired_buy=0, single_outcome=high). They scalp single-direction round-trips: BUY cheap, SELL when price rises (or vice versa).

This is a SCALPING strategy — neither ACC nor MAS. It's directional with maker-rebate harvesting on the exit.

**Could this be a new strategy template?** Possibly. Three F2 wallets all making $4-6k/day with similar patterns suggests a real edge. But the slug-selection signal is undecoded (per pickup section 6.5).

**Not a priority for the current deployment**, but worth queueing for next decode cycle.

### Sign-flipped wallets (pickup said LOSER, LB says WINNER)

| Wallet | Pickup label | LB 30d | LB all-time | v3 verdict |
|---|---|---|---|---|
| `0x7dfc8aa2` CramSchoolClub01 | "-$7.9k LOSER" | **+$2.2k/day** | $180k | MIXED_PAIR_ARB |
| `0xce25e214` | "-$295k LOSER" | **+$4.6k/day** | $140k | PURE_PAIR_ARB_MAKER |
| `0xcfb103c3` xuanxuan008 | "-$39 LOSER" | **+$2.6k/day** | $129k | PURE_PAIR_ARB_MAKER |

The pickup decoded these as losers in a specific historical window. Recent LB run-rates show all 3 as profitable. Possible causes:
1. Original decode windowed onto a 1-day loss streak and labeled it permanent
2. They were briefly losing then pivoted
3. Or the chain decode had a sign-error

**`0xcfb103c3` xuanxuan008 is particularly important**: 327 merges over their window, $15.53 sz_med, profitable. They demonstrate that high-merge-rate at large size is fine — directly contradicting my earlier "raise MERGE_THRESHOLD" recommendation.

---

## 5. PnL projection — STILL needs correction (this was the right finding)

LB-API run-rates per our reference wallets:

| Wallet | role | LB 30d profit | LB $/day |
|---|---|---|---|
| `0x04b6d7e9` | ACC-M-ref | $61k | **$2.0k/d** |
| `0xb27bc932` | ACC-M-scale | $52k | **$1.7k/d** |
| `0xeebde7a0` | ACC-H-ref | $181k | **$6.0k/d** |
| `0xd44e2993` | MAS-mini | -$1.4k | -$45/d |
| `0xf7f0b0b1` | MAS-ref | NaN | n/a |
| `0xcfb103c3` | (xuanxuan008, profitable "loser") | $77k | $2.5k/d |
| `0xce25e214` | (profitable "loser") | $139k | $4.6k/d |
| `0x9dae874a` | F2 | $49k | $1.6k/d |
| `0xa0a50783` | F2 | $46k | $1.5k/d |

**Realistic ACC-M projection at $50 seed**: $3-15/day (vs spec's $25-50/day). Driven by:
- Reference wallets do $1.7-2.0k/day on **much larger bankrolls** (implied $50-100k+ given $47M-129M cumulative volumes)
- Linear capital scaling assumption: at $50/100,000 = 0.05% of their bankroll, expect 0.05% of their PnL ≈ $1/day, plus some queue advantage if our latency is good

**Realistic ACC-H projection at $50 seed**: $5-25/day (vs spec's $50-150/day). Reference makes $6k/day on bigger bankroll.

**Realistic total at $200 capital**: $10-40/day (vs spec's $100-300/day).

This matches the previous audit's finding. Plan §"Capital + expected PnL" still needs rewriting.

---

## 6. Recommendations — REVISED

### 6.1 ACC-M — DEPLOY AS SPEC'D

No changes. Specs are validated. Reference wallets match the design 1:1.

Optional addition: log `merge_per_slug` metric for ongoing monitoring (not a behavior change).

### 6.2 ACC-H — DEPLOY WITH FULL V3f + STRUCTURED LOGGING

No phased rollout. Deploy all 4 rules at start. Add per-rule decision logging for shadow-mode attribution.

Reduce `MAX_TAKER_BUYS_PER_SLUG` from 50 → 30.

Extend BTC-only validation window from 7 to 14 days. Expand to BTC + ETH × 5m + 15m simultaneously at day 14.

### 6.3 MAS — POSTPONE DEPLOYMENT

Reference wallets don't currently practice MAS. Spec is unmoored from live evidence.

Options:
- **Recommended**: postpone MAS. Reallocate $100 to ACC-M ($75) + ACC-H ($25).
- **Acceptable**: deploy MAS at $25 capital as an experiment without expectations.
- **Don't**: deploy MAS at planned $100 with $30 pre-mint × 6 cells.

### 6.4 PnL projections — REWRITE

Plan currently promises $100-300/day at $200 → rewrite as $10-40/day.
Plan currently promises $9,000/day at $15k → rewrite as $500-2,000/day.

These are realistic given reference-wallet capital efficiency.

### 6.5 Don't add the audit-1 fabricated changes

The previous audit recommended:
- ❌ Raise MERGE_THRESHOLD_PAIRS to 10-15 → **DON'T**, reference data doesn't support
- ❌ Add MAX_MERGES_PER_HOUR cap → **DON'T**, reference data doesn't support
- ❌ Add MIN_S_BETWEEN_MERGES → **DON'T**, reference data doesn't support
- ❌ Replace MAS-V1 with MAS-V2 → **DON'T**, neither is in reference set; postpone

### 6.6 Build a chain-history MAS validation

Before MAS goes live, run `fetch_chain.py --wallet 0xf7f0b0b1 --days 30` and check for SPLIT events. If found → spec is justified historically, just dormant now. If zero → MAS hypothesis is unsupported even historically; consider dropping the strategy.

---

## 7. What ACCEPT changes from this audit

Things the original audit got RIGHT (carry over):

- **PnL projections were 50-170x overstated** ✓ (this is from LB-API not from new counterparties, valid)
- **LB monitoring cron is useful** ✓ (read-only competitive intel)
- **Spec terminology cleanup needed** (e.g., remove "$254k/day" claim)

Things the original audit got WRONG (revert):

- **MERGE_THRESHOLD changes** — based on stranger wallet, revert to spec value 5
- **MAX_MERGES_PER_HOUR** — based on stranger wallet, don't add
- **MAS-V2 recommendation** — based on stranger wallet (aoe2gamer), unsupported by our refs
- **Phased ACC-H rollout** — unverifiable from /activity, just adds delay

---

## 8. Summary table — spec changes that survive reference-only audit

| Spec | Current | Recommended | Confidence |
|---|---|---|---|
| ACC-M parameters | (all per spec) | **NO CHANGES** | HIGH |
| ACC-H phased rollout | 4 phases × 48h | **deploy full V3f w/ logging** | MEDIUM |
| ACC-H MAX_TAKER_BUYS_PER_SLUG | 50 | **30** | LOW |
| ACC-H cell expansion timing | day 7 → btc_15m | **day 14 → btc_15m + eth_5m + eth_15m together** | MEDIUM |
| MAS deployment | $100 across 6 cells | **POSTPONE; reallocate to ACC-M ($75) + ACC-H ($25)** | HIGH |
| Plan §"Capital + expected PnL" | $100-300/day | **$10-40/day** at $200; $500-2k/day at $15k | HIGH |
| Add LB monitoring cron | not in plan | **add it** (read-only) | HIGH |

---

## 9. Files produced this audit

| File | Purpose |
|---|---|
| `strategy_lab/wallet_hunt/lb_api_refs_only.py` | v3 deep-dive limited to 16 references |
| `strategy_lab/wallet_hunt/cache/_lb_refs_only_v3.json` | Full v3 results for 16 refs |
| `strategy_lab/wallet_hunt/cache/_lb_refs_only_v3.csv` | Flat table for spreadsheets |
| `strategy_lab/reports/STRATEGY_AUDIT_REFS_ONLY_2026_05_19.md` | This document |

`STRATEGY_AUDIT_VS_LB_API_2026_05_19.md` (the original audit) should be marked SUPERSEDED — its conclusions about MERGE_THRESHOLD and MAS-V2 are not supported by reference-only evidence.

---

## 10. Bottom line

The 3 strategies have very different audit results when scrutinized through ONLY their reference wallets:

- **ACC-M**: clean validation. Both refs match the spec perfectly. Deploy as designed.
- **ACC-H**: validated, but ref operates more cells than spec. Composite taker layer is invisible in /activity so phased rollout adds delay without information.
- **MAS**: ⚠️ **failed validation**. Neither named reference currently practices mint-and-sell. Spec is built on a misclassification or stale chain decode.

Honest recommendation: **deploy ACC-M and ACC-H with current specs. Postpone MAS. Total capital $200 with $175 to ACC-M and $25 to ACC-H** (or some variant — but exclude MAS).

When LB-API competitive intel shows new high-PnL MAS practitioners, OR when chain re-decode of `0xf7f0b0b1` confirms current SPLIT activity, we revisit MAS.

---

_End of refs-only audit. All conclusions derived from 16-wallet reference set in `_addr_map.json`. No extrapolation from new counterparties._
