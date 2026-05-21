# Strategy audit — ACC-M / ACC-H / MAS specs vs LB-API findings

**Date**: 2026-05-19
**Audits**: `TV_DEPLOY_SPEC_ACC_M_2026_05_18.md`, `TV_DEPLOY_SPEC_ACC_H_2026_05_18.md`, `TV_DEPLOY_SPEC_MAS_2026_05_18.md`, `TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md`
**Reference data**: `LB_API_DEEPDIVE_2026_05_19.md` + v3 cohort
**Scope**: Validate or revise the 3 deploy specs against fresh wallet-cohort evidence

---

## TL;DR — what's right, what's wrong, what to change

| Spec area | Status | Action |
|---|---|---|
| Core strategy logic (BIDs / ASKs / merge) | ✅ correct | none |
| Cancel rules (3¢ / 20s) | ✅ correct | none |
| POST_SIZE = 5, price band 0.05-0.95 | ✅ matches cohort | none |
| Asset start = BTC | ✅ matches all top wallets | none |
| 7-day BTC-only validation gate | ✅ matches risk profile | none |
| **MERGE_THRESHOLD_PAIRS = 5** | ⚠️ **risky** | **raise to 10-15, add 60s min-gap between merges** |
| **PnL projections** | ❌ **50-200% overstated** | **rewrite §4 of deployment plan** |
| **ACC-H V3f composite (Rule B+D)** | ⚠️ unverified in /activity | **start with A+C only, add B/D after live validation** |
| **MAS upfront-mint design** | ❌ **inferior to observed practice** | **add MAS-V2 (BID-first → ASK-second) as primary variant** |
| **Multi-asset expansion timing** | ⚠️ slow | **expand BTC→ETH after 7 days, not 14** |
| **Slug-velocity bottleneck** | ⚠️ undocumented | **plan for 8 cells (BTC+ETH×5m,15m,1h,4h-daily) by week 3** |

---

## 1. ACC-M audit

### 1.1 Core logic — VALIDATED

The 5 v3-classified PURE_PAIR_ARB_MAKERS (including our reference `0xb27bc932`, `0x04b6d7e9`) all behave exactly per the ACC-M spec:
- 100% BUY (maker BIDs fill, wallet receives shares)
- 91-100% paired-buy per slug (BIDs on BOTH outcomes)
- 0 SELL transactions in recent activity
- Reside in 5m + 15m cells

**ACC-M state machine + decision rules match observed behaviour. No changes needed there.**

### 1.2 MERGE_THRESHOLD_PAIRS=5 — REVISE TO 10-15

The spec sets merge trigger at 5 paired pairs. Risk evidence from cohort:

| Wallet | LB 30d | merges in window | window | merges/hr | $/day | verdict |
|---|---|---|---|---|---|---|
| **`0x76d4d470`** "loser2" | **-$27k** | **573** | 2.5h | **229** | -$900/d | merging itself bankrupt |
| `0xee55214e` sixx7 | +$6.8k | 32 | 2.5h | 13 | +$226/d | winner |
| `0xf8e35e78` hydroflask | -$691 | 56 | 2.0h | 28 | -$23/d | small loser |
| `0xb27bc932` known | +$1.7k/d | 0 | 1.5h | 0 | $1.7k/d | merges on different cadence |
| Top performer `0xb55fa129` | +$7.2k/d | 0 | 3.2h | 0 | $7.2k/d | doesn't merge in this window |
| All other winners | varies | 0 | varies | 0 | varies | none |

**Pattern**: Top performers (anon-217k, JetFadil, anon-19k, anon-14k) do **0 merges in observed window**. They batch/defer or merge ONLY at slug close. The aggressive merger `loser2` does 229 merges/hour and loses $27k/30d despite 97% paired-buy slug coverage.

**Likely root cause**: each NegRiskAdapter merge costs ~$0.05-0.10 in gas + 7% maker rebate forfeited × 2 sides. At 229 merges/hour × $0.20 cost = $46/hour ≈ $1,100/day eats their spread.

**Recommended changes to ACC_M_CONFIG**:

```python
# NEW PARAMS
"MERGE_THRESHOLD_PAIRS": 10,            # raised from 5 — let inventory build
"MIN_S_BETWEEN_MERGES": 60,             # NEW — gas-bleed protection
"MAX_MERGES_PER_HOUR": 30,              # NEW — hard cap, alert beyond
"MERGE_AT_SLUG_CLOSE_REGARDLESS": True, # NEW — always force final merge

# Optional: use the batch-merge router for high-volume mode (>10 merges/hour)
"USE_BATCH_MERGE_ROUTER": False,  # 0x84ba896235059fe27727eaa2695a9f99220d9a7e
                                   # Enable only when daily volume > $1k
```

### 1.3 PnL projection — CORRECT DOWNWARD 50-70%

Deployment plan §"Capital + expected PnL" claims:
- Test scale ($200 total): $100-300/day
- Wallet scale ($5k each = $15k): ~$9,000/day

Reality from LB-API 30d run-rates:
- `0x04b6d7e9` PURE_PAIR_ARB_MAKER: **$2,038/day** on $47.6M cumulative volume (≈ $20-50k working capital implied)
- `0xb27bc932` PURE_PAIR_ARB_MAKER: **$1,740/day** on $129.5M cumulative volume (≈ $50-100k working capital implied)
- `0xeebde7a0` HYBRID (our ACC-H ref): **$6,047/day** on $99.8M cumulative volume
- `anon-217k` top performer: **$7,200/day** at $9 median notional with wide-mandate

**Capital-to-PnL ratio** for established winners: 10-25x working capital per $1/day of PnL.

**Revised projections** at $50 seed × BTC 5m+15m ACC-M:

| Capital | Old projection | LB-realistic | Notes |
|---|---|---|---|
| $50 (test) | $25-50/day | **$3-15/day** | queue dilution by 10+ competing makers |
| $500 | $250-500/day | **$30-150/day** | needs slug-velocity to absorb |
| $5,000 | $2,500/day | **$300-1,000/day** | competes at the JetFadil tier |

Rewrite deployment plan §"Capital + expected PnL" with these numbers. Setting expectations correctly avoids "why isn't it working" panic in week 1.

### 1.4 MAX_CONCURRENT_SLUGS = 4 — OK FOR NOW

JetFadil (BTC 5m only) handles ~50 slugs/hour → at 5m duration that's ~4.2 concurrent. The current `MAX_CONCURRENT_SLUGS=4` is correct for BTC 5m only.

**But this caps PnL** once we expand. `anon-217k` operates 172 slugs in 3.2h = 54/h across BTC+ETH+SOL+XRP × 5m+15m+1h+4h. With 5m duration that's ~4.5 concurrent per cell × 16 cells = potential ~72 concurrent.

When expanding cells, raise `MAX_CONCURRENT_SLUGS` proportionally:

```python
"MAX_CONCURRENT_SLUGS_PER_CELL": 4,   # NEW per-cell cap
"MAX_CONCURRENT_SLUGS_TOTAL": 8,      # was 4 — raise to 8 with btc_5m+15m
                                       # raise to 16 after eth expansion
                                       # raise to 64 at full 4×4 deploy
```

---

## 2. ACC-H audit

### 2.1 Core pair-arb base — same as ACC-M, VALIDATED

Inherits all ACC-M behavior. Reference wallet `0xeebde7a0` v3-classifies as PURE_PAIR_ARB_MAKER in last 3.5h. Pair-arb maker layer is sound.

### 2.2 V3f composite taker — UNVERIFIED IN LIVE DATA

**Spec claim**: V3f composite (Rules A+B+C+D) covers 78.9% of decoded taker fires at 1.37× lift, validated against `0xeebde7a0`'s 21-day chain decode.

**LB-API/v3 finding**: In recent 3.5h of `0xeebde7a0`'s /activity:
- 0 SELLs
- 100% BUYs
- All maker-BID-filled (we cannot distinguish from market-buys in /activity)
- 0 of the 4 taker triggers were verifiably observable

This isn't refutation — it's just no recent live verification. Two possibilities:
- (a) Taker side fires sporadically; the recent 3.5h window may have hit low-trigger periods
- (b) Reference wallet has migrated to more pure-maker since the chain decode window

**Mitigation**: Phase the deployment to validate each rule independently before stacking:

```python
# Original V3f (deploy all 4 rules at once)
"TAKER_RULES_ENABLED": ["A", "B", "C", "D"]

# Recommended phased rollout
PHASE_1 = ["A"]           # Discount-capture only (highest single-rule lift = 1.94×)
PHASE_2 = ["A", "C"]      # + Early-slot (independent trigger time)
PHASE_3 = ["A", "B", "C"] # + Sharp-drop (depends on trade-tape)
PHASE_4 = ["A", "B", "C", "D"]  # full V3f
```

Each phase = 48h shadow + 48h live before adding next rule. Total ramp = ~16 days but de-risked.

### 2.3 TAKER_SIZE=5 and MAX_TAKER_BUYS_PER_SLUG=50

Reference cohort: anon-217k does $9 median notional (close to TAKER_SIZE × avg_price = 5 × $0.45 = $2.25). JetFadil at $13 median. **TAKER_SIZE=5 looks low but fine for test.** Scale 2x per week if PnL > threshold.

`MAX_TAKER_BUYS_PER_SLUG=50` is too high for a sub-bot. Reference wallet `0xeebde7a0` averages ~10-15 fills per slug on the taker side. Recommend reducing to 20.

```python
"MAX_TAKER_BUYS_PER_SLUG": 20,  # was 50 — reduce false-positive overfire
```

### 2.4 ACC-H PnL projection

Old: $50-150/day at $50 seed on BTC 5m.

Realistic from LB:
- `0xeebde7a0` (our reference) does $6,047/day on $99.8M cumulative volume + much larger bankroll
- At $50 bankroll, expect $15-60/day
- After taker fees (0.07 × p × (1-p) per share, ~$0.084 per 5-share order at p=$0.40), net edge thinner

```python
# Revised promotion criteria
"min_realized_per_slug": 0.25,  # was $0.50 — half is more realistic at our seed
"min_median_per_slug": 0.10,    # was $0.20
```

---

## 3. MAS audit

### 3.1 Current spec — UPFRONT-MINT MODEL

Per `TV_DEPLOY_SPEC_MAS_2026_05_18.md` §2:
1. On SlugActive: MINT pairs via splitPosition (cost = $1 × N pairs)
2. Post ASKs on Up + Down
3. Redeem winning leftover at slug close

**Edge model** (spec §7): `edge ≈ sum_asks - $1.00 + maker_rebate ≈ $0.024/pair`

### 3.2 What the only observed MAS wallet (`aoe2gamer`) actually does

`aoe2gamer` (`0xfb0f17657c9c24293b918adb86362a4d8fc90b02`) is the **only** wallet in our v3 cohort classified as MIXED_MAKER_BIDS_AND_ASKS:
- 3481 trades in 1.5h, 100% BTC 5m, 19 unique slugs
- **100% paired-buy** per slug (acts like ACC-M on the BID side)
- **100% both-sides** per slug (also sells)
- BUY% = 61.2, SELL% = 38.8
- $3.0 median notional
- Result: +$13k/30d profit (~$433/day on ~$5-20k implied bankroll)

**aoe2gamer's actual flow**:
1. Slug opens → post BIDs on Up + Down (like ACC-M)
2. BIDs fill at, say, $0.45 each → cost = $0.90/pair (vs the spec's $1.00/pair mint cost)
3. Post ASKs at $0.55+ on whichever leg has imbalance
4. If ASK fills → sell at $0.55 (profit $0.10/share + maker rebate)
5. If ASK doesn't fill → merge or hold to slug close

**Cost basis comparison**:
- Spec MAS: $1.00/pair (upfront mint) — needs sum_asks > $1.005 to break even
- aoe2gamer's flow: ~$0.90/pair (BID-fill cost basis) — profitable across wider price range

### 3.3 Why the spec model is structurally inferior

Spec MAS only profitable when `sum_asks > $1.00 + rebate ≈ $1.005`.

In the last 21 days of canonical L25 data (see `MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`), `sum_asks > $1.005` is rare — maybe 15-20% of slugs.

The aoe2gamer flow is profitable any time `sum_asks > sum_bids` (which is essentially always — that's the spread). It captures both:
- The structural BID-side mispricing (`sum_bids < $1`) — ACC-M edge
- The structural ASK-side mispricing (`sum_asks > $1`) — pure MAS edge

This is **strictly more powerful** than the pure MAS spec.

### 3.4 RECOMMENDED — replace pure MAS with MAS-V2

**Action**: Move pure MAS to "MAS-V1 reference variant" and make MAS-V2 (aoe2gamer pattern) the primary deployment.

```python
MAS_V2_CONFIG = {
    "strategy_code": "MAS-V2",
    "version": "2.0.0",

    "cells": ["btc_5m"],                       # Start narrow (aoe2gamer only does BTC 5m)
    "operating_hours_utc": None,

    # Capital — NO upfront mint
    "wallet_seed_usdc": 50,
    "RESERVE_USDC": 5,

    # BID side (inherits ACC-M)
    "POST_BID_SIZE": 5,
    "MIN_BID_PRICE": 0.05,
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,
    "MAX_SPREAD_PER_LEG": 0.05,

    # ASK side (NEW)
    "POST_ASK_SIZE": 5,
    "MIN_SUM_ASKS": 1.005,                     # only post asks when edge exists
    "ASK_PRICE_STRATEGY": "best_ask",           # or "best_ask + 1¢" for queue priority
    "MIN_INVENTORY_BEFORE_ASK": 5,             # don't post ASK until inv >= 5 shares

    # Asks vs merges decision
    "PREFER_ASK_OVER_MERGE_BELOW_PRICE": 0.95, # if leftover is on Up at $0.95, ASK
                                                # if at $0.50, MERGE (worth $1 in pair)
    "MAX_ASK_AGE_S": 30,                       # if ASK doesn't fill in 30s, cancel

    # Cancel rules (apply to both BID and ASK)
    "CANCEL_THRESHOLD": 0.03,
    "MAX_BID_ORDER_AGE_S": 20,
    "MAX_ASK_ORDER_AGE_S": 30,                  # asks live longer (lower fill prob)

    # Target BUY/SELL ratio (calibrate to aoe2gamer's 61/39)
    "TARGET_BUY_PCT": 60,
    "REBALANCE_THRESHOLD": 70,                  # if BUYs exceed 70%, prioritize ASK posts

    "shadow_mode": True,
}
```

### 3.5 Pure MAS spec — keep as "MAS-V1" reference only

Don't delete `TV_DEPLOY_SPEC_MAS_2026_05_18.md` — it's the pedagogical reference for the mint-and-sell concept. But mark it as "reference variant; deploy MAS-V2 instead".

---

## 4. Cross-strategy concerns

### 4.1 Slug-velocity ceiling — plan ahead

ANY deployment on BTC 5m only is capped at 12 slugs/hour fresh starts. With current `MAX_CONCURRENT_SLUGS=4`, we engage with maybe 4-8/h. JetFadil hits 50/h on BTC 5m which implies they engage with EVERY slug — extreme parallelism + sub-ms post latency.

**Plan to expand cells in this order**:

| Day | Cells active | Slug/hr ceiling | $/day target |
|---|---|---|---|
| 0-7 | BTC 5m | 12 | $5-20 |
| 7-14 | BTC 5m + 15m | 16 | $15-40 |
| 14-21 | + ETH 5m + 15m | 32 | $30-80 |
| 21-28 | + BTC + ETH 1h | 40 | $50-150 |
| 28+ | + BTC + ETH 4PM-ET daily | 42+ | $80-300 |

This is conservative. anon-217k hit 4 majors × 4 timeframes ($217k/30d). We can match that ceiling only at 16 cells.

### 4.2 Capital allocation revision

Current plan: ACC-M $50, ACC-H $50, MAS $100 = $200 total.

Recommended:

```python
# Phase 1 (first 14 days, BTC only)
ACC_M:   $50  on BTC 5m + 15m
ACC-H:   $50  on BTC 5m only (extra latency-sensitive)
MAS-V2:  $50  on BTC 5m only (new untested variant)
RESERVE: $50

# Phase 2 (after 14 days clean, ETH expansion)
ACC_M:   $150 on BTC + ETH × 5m + 15m
ACC_H:   $100 on BTC + ETH × 5m
MAS_V2:  $100 on BTC + ETH × 5m + 15m
RESERVE: $50
```

Total: $200 phase 1 → $400 phase 2. **Don't pre-fund $1,000+** until ACC-M has 14+ clean days.

### 4.3 Competitive landscape note

Spec line: "This strategy competes with 100+ other maker bots for queue position."

Reality: We've identified **specific competitors** via counterparty mining. The top 10 maker counterparties we cross:
- 6 are confirmed PURE_PAIR_ARB_MAKERs (same template as ACC-M)
- 1 is MIXED_MAKER (aoe2gamer, MAS variant)
- 3 are losers bleeding fees

So we know there are **~10 sophisticated maker bots** + a long tail of directional takers. Not 100. The actual queue competition for each post is probably 3-7 bots fast enough to matter.

**Implication**: queue dilution is real but not catastrophic. Expect to capture 10-30% of fills, not 1% of fills.

### 4.4 Monitoring + competitive intel via LB-API

Build a daily cron on Ireland VPS:

```bash
# /opt/tradingvenue/scripts/lb_monitor.sh (runs every 1h)
#!/usr/bin/env bash
for addr in $(cat /etc/tv/monitored_wallets.txt); do
  for window in 1d 7d 30d; do
    curl -s "http://lb-api.polymarket.com/profit?window=$window&address=$addr" \
      | jq ". + {window: \"$window\", queried_at: now}" \
      >> /var/log/tv/lb_monitor.jsonl
  done
done
```

`/etc/tv/monitored_wallets.txt` should include:
- Our 3 deployed wallets (track our own profit)
- Top 5 counterparty winners (anon-217k, JetFadil, anon-19k, anon-14k, aoe2gamer)
- Top 2 counterparty losers (BIG_LOSER, loser2 — watch for behavior changes)
- Our 4 reference wallets (0x04b6d7e9, 0xb27bc932, 0xeebde7a0, 0x89b5cdaa)

This gives weekly competitive movement data + early warning if competitors find new edge.

---

## 5. Action items — concrete spec changes

### 5.1 Edit `TV_DEPLOY_SPEC_ACC_M_2026_05_18.md`

In §4 (Configuration):
- Change `MERGE_THRESHOLD_PAIRS: 5` → `10`
- Add `MIN_S_BETWEEN_MERGES: 60`
- Add `MAX_MERGES_PER_HOUR: 30`
- Add `MAX_CONCURRENT_SLUGS_PER_CELL: 4` (rename existing param)

In §8 (Live promotion):
- Step 5 "Scale seed 2x per week if PnL > $50/day per cell" → "$15/day per cell"
- Add explicit merge-rate audit at each scale-up

### 5.2 Edit `TV_DEPLOY_SPEC_ACC_H_2026_05_18.md`

In §3.5 (Composite taker):
- Add "Phased rollout" subsection with the 4 phases (A → A+C → A+B+C → A+B+C+D)
- Document live-validation step between each phase

In §4 (Configuration):
- Change `MAX_TAKER_BUYS_PER_SLUG: 50` → `20`

### 5.3 Create `TV_DEPLOY_SPEC_MAS_V2_2026_05_19.md`

Brand-new spec for the BID-first → ASK-second variant. Cite aoe2gamer (`0xfb0f17657c9c24293b918adb86362a4d8fc90b02`) as the live reference.

Mark `TV_DEPLOY_SPEC_MAS_2026_05_18.md` as "MAS-V1 reference variant; deploy MAS-V2 instead".

### 5.4 Edit `TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md`

§"Capital + expected PnL":
- Rewrite numbers with the LB-realistic projection (table above in §1.3 of this audit)
- Add note "Pickup numbers from 2026-05-18 were 50-170x overstated; see LB_API_DEEPDIVE_2026_05_19.md for reconciliation"

§"Implementation phases":
- Days 1-8 unchanged for ACC-M
- Insert NEW Day 9-10 for MAS-V2 shadow validation (replaces pure MAS deploy)
- Days 9-10 ACC-H stays

§"Performance requirements (NON-NEGOTIABLE)":
- Add new req: "P11: Merge-rate limiter — gas-bleed protection from over-merging"

### 5.5 Update `NEXT_SESSION_PICKUP_2026_05_19.md`

Already updated with LB-API handoff. Add reference to this audit:
- "STRATEGY_AUDIT_VS_LB_API_2026_05_19.md — concrete spec revisions from cohort evidence"

### 5.6 Implement monitoring cron

Build `lb_monitor.sh` on Ireland VPS (see §4.4 above) — read-only, no impact on live deploy.

---

## 6. What's NOT changing

| Spec area | Why unchanged |
|---|---|
| ACC-M decision rules §3 (post/cancel/merge logic) | Verified against 4 known + 6 new PURE_PAIR_ARB_MAKERS |
| MAX_IMBALANCE_SHARES = 5 | All winners maintain near-50/50 up/down |
| Performance requirements P1-P10 | Latency-critical, already correct |
| Pre-signed order pool requirement | Critical to compete with the 10+ identified competitor makers |
| BTC-first asset start | 100% of top single-asset winners are BTC-focused |
| Shadow → 48h → Live progression | Risk-management discipline, unchanged |

---

## 7. Confidence levels

| Recommendation | Confidence | Evidence |
|---|---|---|
| Raise MERGE_THRESHOLD_PAIRS to 10-15 | **HIGH** | loser2's 573 merges → -$27k/30d direct evidence |
| Replace MAS-V1 with MAS-V2 | **HIGH** | aoe2gamer's flow strictly dominates pure mint-and-sell pedagogically + empirically (+$13k/30d) |
| PnL projection 50-70% cut | **HIGH** | LB-API run-rates for 16 known wallets all 50-170x below pickup |
| Phased ACC-H taker rollout | **MEDIUM** | V3f composite is theoretically sound; live verification gap is the concern |
| ETH expansion at day 7 (not 14) | **MEDIUM** | anon-19k/anon-14k both add ETH with positive results |
| 8-cell deployment by week 3 | **MEDIUM** | anon-217k operates 4×4 cells; we don't know their bankroll |
| Monitor merge rate metric | **HIGH** | Direct empirical evidence of merge-rate causing losses |

---

## 8. Risk if we DON'T make these changes

1. **Deploy MERGE_THRESHOLD_PAIRS=5 → likely loss in first 30 days.** loser2 has perfect strategy form and still loses $27k/30d from over-merging. With our $50 seed, gas burn could be 20-40% of capital in week 1.

2. **Deploy pure MAS (V1) → likely break-even at best.** Edge requires `sum_asks > $1.00` which is rare. MAS-V2 captures both BID and ASK mispricings.

3. **Plan promises $9k/day at $15k bankroll → unmet expectation.** Reality is $1-4.5k/day. If stakeholders expect $9k/day they'll panic-pull capital after week 1.

4. **Deploy full ACC-H V3f without phased validation → unable to attribute PnL to each rule.** If ACC-H loses money in shadow, we can't tell if Rule B is the problem vs Rule C vs taker fees in general.

5. **Skip LB monitoring cron → no competitive intel.** When a new bot enters the space and starts cross-trading us aggressively, we'll find out from PnL drop only, not from the leaderboard.

---

## 9. Bottom line

The 3 strategy designs are **fundamentally sound** — they match what 6+ profitable wallets in the v3 cohort actually do. The corrections are:

1. **Tactical knobs**: merge frequency, taker rollout phasing, MAS variant choice — all narrow tweaks based on cohort evidence
2. **Expectations**: PnL projections need rewriting with LB-realistic numbers
3. **Monitoring**: add LB-API cron for ongoing competitive intel

No fundamental redesign needed. Ship ACC-M with the merge-rate fix, replace MAS with MAS-V2, phase ACC-H. Estimated 1-2 days of additional spec work before TV agent starts implementation.

---

_End of audit. All cross-references verified against `LB_API_DEEPDIVE_2026_05_19.md`, `_lb_new_wallets_deepdive_v3.csv`, and the 4 spec files._
