# Strategy revision — replace the 3-strategy handoff

**Date**: 2026-05-19
**Supersedes**: `README_TV_AGENT_HANDOFF.md` § "Definition of DONE" claims of $100-300/day on $200
**Source**: 213-slug validation backtest + 5-wallet chain decode (see `OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md`)
**Budget constraint**: **MAX $100 USDC.e per strategy** for initial deployment. Validate profitability before scaling.

---

## TL;DR — what to change

| Strategy | Current handoff | Status | New decision |
|---|---|---|---|
| **ACC-M** | $50 seed, POST_SIZE=5 | ✅ KEEP — strategy is right, size is wrong | Resize to POST_SIZE=20, seed $100 |
| **ACC-H** | $50 seed, V3f composite taker, "$50-150/day" | 🔴 DROP from live deploy | Shadow-only for 2 weeks before any decision |
| **MAS** | $30 pre-mint × 6 cells = $180, "$30-100/day" | 🟡 KEEP small, don't scale | Resize to $30 × 2 cells = $60 active in $100 wallet |
| **NEW: ACC-PC** | n/a | 🟡 Add as shadow-only variant | $100 wallet, fires on imbalance |
| **NEW: PAT** | n/a | 🟡 Research-stage (needs new simulator) | Defer until PAT-specific backtest built |
| **NEW: Directional MAS** | n/a | 🔵 Defer — needs signal we don't have | Research only, no deployment |

**Total live capital under new plan**: $100 ACC-M + $100 MAS + $100 ACC-PC = **$300 across 3 strategies**.
**Total shadow capital**: ACC-H (no money, logs only).

The original handoff committed $200 to 3 strategies expecting $100-300/day. Reality from backtest:
- Old expectation: $100-300/day on $200 capital
- New realistic expectation: **$15-50/day on $300 capital** (10x downward revision)

If any strategy hits $30/day consistently for 7 days, scale that one to $300. Don't scale all at once.

---

## 1. Why the original handoff is wrong

The 3-strategy spec was built from:
- 5 reference wallets we decoded from chain history
- Pickup numbers projecting $10k-$254k/day per wallet
- POST_SIZE=5 (CLOB minimum) for all 3

What 213-slug validation revealed:

### 1.1 The PnL projections were 50-170x overstated

Per LB-API official run-rates:
- `0x04b6d7e9` (ACC-M ref): $2,038/day actual (pickup said $212k/day — **104x overstated**)
- `0xeebde7a0` (ACC-H ref): $6,047/day actual (pickup said $344k/day — **57x overstated**)
- `0xb27bc932`: $1,740/day actual (pickup said $254k/day — **146x overstated**)

### 1.2 The reference wallet was misclassified

`0x04b6d7e9` (the wallet ACC-M was modeled on) actually does **98% SELL maker** in chain history. That's the MAS pattern (mint-and-sell), NOT ACC-M (post BIDs).

The v3 /activity snapshot caught a rare 1-hour window of 100% BUY activity and we labeled them PURE_PAIR_ARB_MAKER. The full 30-hour chain shows 98% mint-and-sell.

ACC-M still works in backtest because it captures the same structural mispricing (sum_bids < $1) from the BID side of the book.

### 1.3 ACC-H V3f composite taker LOSES money

Backtest result on 213 slugs across 4 wallets: **-$6.84/slug average**. The 4-rule composite (Discount-capture + Sharp-drop + Early-slot + Buy-pressure) decoded from `0xeebde7a0` doesn't survive realistic fee accounting. Taker fees (7%) overwhelm the modest 1.37× signal lift.

The handoff claims ACC-H will produce $50-150/day. Backtest says it loses money. **Strong recommendation to drop from live.**

### 1.4 POST_SIZE=5 is too small

Reference wallets post orders that fill 100-254 shares total via laddered partial fills (median fill size 8-10 shares per partial, ~10 partials per order). Our 5-share single-shot orders sit at the back of a 24+ share queue and rarely fill.

213-slug validation:
- POST_SIZE=5: +$0.37-0.73/slug
- POST_SIZE=20: +$1.25/slug (**3x better, low variance**)
- POST_SIZE=50: +$2.35/slug
- POST_SIZE=100: +$3.54/slug (best Sharpe)
- POST_SIZE=200: +$3.78/slug (higher variance)

---

## 2. Revised strategy specs

### 2.1 ACC-M REV — POST_SIZE=20, $100 budget

**Same logic as current spec, just resized.**

Changes from `TV_DEPLOY_SPEC_ACC_M_2026_05_18.md`:

```python
ACC_M_REV = {
    # CHANGED
    "POST_SIZE": 20,                   # was 5 — supports queue position with bounded capital
    "ABSOLUTE_MAX_INVENTORY": 80,      # was 50 — 4 orders worth
    "MAX_IMBALANCE_SHARES": 10,        # was 5 — slightly looser for sz=20
    "wallet_seed_usdc": 100,           # was 50 — fits POST_SIZE=20 budget
    "MAX_CONCURRENT_SLUGS": 2,         # was 4 — start narrow

    # UNCHANGED (validated correct from 213-slug test)
    "MIN_BID_PRICE": 0.05,
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,
    "CANCEL_THRESHOLD": 0.03,
    "MAX_ORDER_AGE_S": 20,
    "MERGE_THRESHOLD_PAIRS": 5,
    "stop_posting_offset_s": 270,
    "cells": ["btc_5m"],               # was ["btc_5m", "btc_15m"] — start with one cell
}
```

**Capital math at POST_SIZE=20**:
- Per posted order: 20 shares × $0.50 avg = $10 cost
- Per slug with both sides: $20 reserved
- 2 concurrent slugs: $40 working capital
- Reserve: $60 for gas + safety + merge timing
- Total: $100 ✓

**Expected PnL** (per 213-slug validation):
- $1.25/slug × ~12 BTC 5m slugs/h × 14h (assume some downtime) = **$210/day theoretical**
- Realistic after live queue dilution: **$30-80/day** on $100 capital
- Worst case 24h drawdown: ~$15

**Live promotion criteria** (per current spec, validated):
- Mean realized $/slug > $0 over 48h shadow → live promotion
- ACC-M REV target after 7d live: $20-50/day

### 2.2 ACC-H REV — SHADOW-ONLY (don't deploy live)

Backtest shows **-$6.84/slug avg** with V3f. Possible reasons:
1. Decoded taker thresholds were tuned for historical book state that doesn't hold now
2. Taker fees overwhelm signal lift in fee-accurate simulation
3. The decoded patterns require a slug-selection layer we don't have

**Action**: Run ACC-H in shadow mode with FULL V3f for 14 days. Log per-rule decisions + would-be PnL. Compare to backtest. If live shadow also shows -$5 to -$10/slug, **drop the strategy permanently**.

Per-rule shadow logging (so we can attribute):
```python
LogTakerDecision(
    ts_us, slug, side,
    rule_fired,        # "A" | "B" | "C" | "D"
    book_state_snapshot,
    decision,          # "BUY" | "SKIP_INV_CAP" | ...
    expected_pnl_if_taken,
)
```

**NO live capital allocated to ACC-H** until shadow validates.

### 2.3 MAS REV — $30 pre-mint × 2 cells, $100 wallet

Backtest result (213 slugs):
- MAS-pre30: +$0.09/slug average (essentially flat)
- MAS-pre50: +$0.04 to +$0.14/slug (still flat)
- MAS-pre500: -$3.02/slug (HARMFUL — too much capital sits on losing leftover)

**Action**: Keep MAS at SMALL pre-mint to gather live data, don't scale.

```python
MAS_REV = {
    # CHANGED
    "PRE_MINT_USDC": 30,               # unchanged
    "wallet_seed_usdc": 100,           # was originally $100 in spec but plan said $180 active
    "cells": ["btc_5m", "btc_15m"],    # was 6 cells — start with 2
    "MAX_CONCURRENT_SLUGS": 2,         # was 6 — match cell count

    # UNCHANGED (per spec)
    "POST_SIZE": 5,                    # CLOB min for asks; MAS at small pre-mint doesn't need bigger
    "MIN_SUM_ASKS": 1.005,
    "MAX_SPREAD_PER_LEG": 0.05,
    "CANCEL_THRESHOLD": 0.03,
    "MAX_ORDER_AGE_S": 30,             # asks live longer
}
```

**Capital math**:
- Pre-mint per slug: $30
- 2 concurrent slugs: $60 reserved for active mints
- Reserve: $40 for gas + new mints

**Expected PnL**: +$0.10/slug × 8 slugs/h × 14h = **~$11/day theoretical**. Realistic: $0-5/day. **Treat as data-gathering deployment, not a profit engine.**

**Live promotion criteria**:
- After 48h shadow, even just break-even is OK to promote (we're learning)
- If live PnL is < -$5/day for 7 days, halt and re-evaluate
- DO NOT scale to $200+ pre-mint without separate validation

### 2.4 NEW: ACC-PC (Pair-Completion Taker) — $100 budget

This was the variant we backtested. Inherits ACC-M, adds a TAKER trigger only when the slug is **already imbalanced** (one BID filled, other side waiting).

213-slug validation: +$0.27-0.49/slug (slightly worse than ACC-M-sz20 at +$1.25, but maybe useful for variance reduction).

```python
ACC_PC = {
    **ACC_M_REV,                       # inherit ACC-M REV config
    "strategy_code": "ACC-PC",
    "POST_SIZE": 20,
    "wallet_seed_usdc": 100,

    # ACC-PC additions
    "enable_pc_taker": True,
    "pc_max_pair_cost": 0.97,          # only take if leading_cost + lagging_ask + fee < $0.97
    "pc_min_time_before_taker_s": 30,  # let BIDs work first
    "pc_min_spread_to_taker": 0.02,    # don't take if BID near ask
    "pc_cvd_threshold": 0,             # only take if buyer pressure on lagging side
    "pc_max_taker_per_slug": 5,        # bounded
    "pc_min_s_between_taker": 5,       # rate limit
}
```

**Logic** (one-liner): when slug is imbalanced AND elapsed > 30s AND pair-cost would be < $0.97 AND CVD positive on lagging side → market-buy lagging side at ask.

**Why deploy this**: ACC-PC has lower variance than ACC-M alone (the taker rebalances inventory at risk-adjusted cost), and pair-completion is theoretically risk-free profit.

**Why this isn't the V3f composite (ACC-H)**: ACC-PC is REACTIVE (only when imbalanced), ACC-H is OPPORTUNISTIC (any cheap ask). Reactive avoids the directional exposure that crushed ACC-H in backtest.

**Expected PnL**: +$0.30/slug × 12 slugs/h × 14h = **$50/day theoretical**. Realistic: $10-25/day.

### 2.5 NEW: PAT (Pair-Arb Taker) — RESEARCH ONLY, not deployable yet

Based on `0xcfb103c3` (xuanxuan008, +$2.5k/day): 90% TAKER, 99.8% paired, single-side outcome only.

**Pattern**:
1. Detect thin-book slug at slot open (depth < threshold)
2. Market-BUY both Up and Down at current asks
3. If sum_asks < ~$0.95: profitable pair-arb
4. Hold pair, merge at $1 via NegRiskAdapter
5. Profit = $1 - (taker_buy_up + taker_buy_dn + 2×taker_fees)

**Why not deployable yet**:
- Our backtest engine doesn't simulate this pattern correctly (mid-slug merge profits aren't tracked in fills.parquet PnL formula)
- Need to build a PAT-specific simulator that tracks pair accumulation from concurrent TAKER buys
- Estimated 4-6 hours of dev work

**Action item**: build `pat_backtest.py` next. Don't deploy PAT live until simulator validates +EV.

**Pseudo-spec for when ready**:
```python
PAT_DRAFT = {
    "POST_SIZE": 0,                    # no maker side
    "TAKER_BUY_SIZE": 20,              # market-buy in 20-share chunks
    "MAX_TAKER_PAIR_COST": 0.97,       # only buy if both sides combined < $0.97
    "MIN_BOOK_DEPTH_FILTER": 100,      # only thin-book slugs (z=-17.86 selection signal)
    "MAX_PAIR_BUYS_PER_SLUG": 3,       # limit exposure per slug
    "wallet_seed_usdc": 100,
}
```

### 2.6 DEFER: Directional MAS — needs signal decode

Based on `0x89b5cdaa` (ohanism, **+$248/slug — biggest winner**): 100% maker, 100% SELL, 41% paired = single-side mint-and-sell with directional bias.

**Why undeployable**:
- Their win rate on single-side picks is 51.5% (essentially random)
- They're making money because of maker rebates + multi-asset spread + size
- We don't know which side to mint-and-sell on
- Random side selection has high variance

**Research path** (not deployment): decode their slug-selection signal. They engage 76.3% of slugs with a -2.53 z-score on depth (thin-book bias). But that doesn't tell us which SIDE to take.

**Action**: skip for now. Revisit only if ACC-M + ACC-PC + MAS together produce sustainable income.

---

## 3. Revised deployment timeline (4 weeks, conservative)

### Week 1: ACC-M REV ONLY at $100

```
Day 1-2: TV agent ports ACC-M REV (POST_SIZE=20) per existing spec
Day 3:   Shadow deploy on BTC 5m only
Day 4-5: 48h shadow validation
Day 6:   If shadow $/slug > $0 → promote to live at $100
Day 7:   Live deploy; monitor closely
```

**Halt criteria**: If live 24h PnL < -$15 or 5 consecutive losing slugs → halt and review.

### Week 2: Add MAS REV at $100 (parallel)

```
Day 8-9:  Port MAS REV; shadow on BTC 5m + 15m (2 cells, $30 pre-mint each)
Day 10:   48h shadow validation
Day 11:   Live deploy at $100 (parallel to ACC-M, different wallet)
Day 12-14: Monitor both
```

Total live capital: $200 ($100 ACC-M + $100 MAS).

### Week 3: Add ACC-PC at $100 + ACC-H shadow-only

```
Day 15-16: Port ACC-PC; shadow on BTC 5m
Day 17:    Live deploy ACC-PC at $100
Day 18:    Port ACC-H V3f; shadow-ONLY (no money)
Day 19-21: All 3 live + ACC-H shadow logging
```

Total live capital: $300 across 3 strategies. ACC-H shadow has no capital.

### Week 4: Validation + selective scale-up

```
Day 22-28: Daily PnL review per strategy
           - If ANY strategy hits +$30/day for 5 consecutive days: scale to $300
           - If ACC-H shadow consistently shows -$5/slug or worse: drop permanently
           - If PAT simulator built + +EV: spec PAT and queue for shadow
```

### Definition of DONE (revised)

After 28 days:
- ACC-M live, producing $10-50/day consistently (positive ≥ 5/7 days)
- MAS live, producing $0-10/day (break-even acceptable as data collection)
- ACC-PC live, producing $10-25/day
- ACC-H decision made (drop or refine)
- Total realistic income: **$20-85/day on $300 capital**

This replaces the old plan's $100-300/day on $200 capital projection (which was based on 50-170x inflated wallet stats).

---

## 4. Capital allocation summary

| Strategy | Wallet seed | Active capital | Expected daily |
|---|---|---|---|
| ACC-M REV | $100 | ~$40-60 working | $20-50 |
| MAS REV | $100 | $60 in pre-mints + $40 reserve | $0-10 |
| ACC-PC | $100 | ~$40-60 + occasional takes | $10-25 |
| ACC-H | $0 (shadow only) | n/a | n/a (data collection) |
| **TOTAL LIVE** | **$300** | varies | **$30-85/day expected** |

**Halt conditions per strategy**:
- 24h drawdown > $30 → halt
- 7-day rolling PnL < -$50 → halt
- 5 consecutive losing slugs → reduce POST_SIZE 50%

**Scale-up conditions per strategy**:
- 7-day rolling PnL > $200 → consider 2x capital
- 14-day rolling PnL > $500 → consider 3x capital

---

## 5. What changes in the TV agent handoff

### 5.1 README_TV_AGENT_HANDOFF.md edits needed

| Section | Current text | Replace with |
|---|---|---|
| Header "Initial capital: $200 USDC.e total" | $200 | **$300 across 3 live + shadow ACC-H** |
| "Expected day-1 PnL: $25-150/day" | $25-150/day | **$20-85/day realistic (was 50-170x inflated)** |
| ACC-M spec link | "$50 seed" | **"$100 seed, POST_SIZE=20"** |
| ACC-H spec link | "$50 seed, $50-150/day" | **"SHADOW-ONLY initially, V3f underperforms in backtest"** |
| MAS spec link | "$30 pre-mint × 6 cells" | **"$30 pre-mint × 2 cells in $100 wallet"** |
| Sprint 5 "Verify wallet funded ($50 ACC-M + $100 MAS)" | $50+$100 | **"$100 ACC-M + $100 MAS"** |
| Sprint 6 "SHADOW deploy ACC-H" | included | **keep shadow but mark NEVER promote to live until shadow PnL > $0** |
| Sprint 7 "PROMOTE ACC-H to LIVE" | included | **REPLACE with: PROMOTE ACC-PC to LIVE (the new pair-completion variant)** |
| "Definition of DONE" PnL targets | $25-50, $30-100, $50-150 = $100-300/day | **$20-50, $0-10, $10-25 = $30-85/day** |

### 5.2 New spec docs to write before TV agent starts

1. `TV_DEPLOY_SPEC_ACC_M_REV_2026_05_19.md` — same as current spec but POST_SIZE=20, seed $100, 1 cell start
2. `TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md` — same as current spec but 2 cells, $100 wallet
3. `TV_DEPLOY_SPEC_ACC_PC_2026_05_19.md` — new spec (ACC-M + pair-completion taker)
4. `TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md` — shadow-only variant with per-rule logging

### 5.3 What stays exactly the same

These are validated correct across 213 slugs and don't need changes:
- Cancel rule (3¢ displacement / 20s age)
- Merge threshold (5 pairs)
- Spread filter (5¢ max per leg)
- Stop-posting offset (270s = 30s before close for 5m, 870s for 15m)
- CLOB minimum order (5 shares)
- All infrastructure (Ireland VPS, BookMirror, PolymarketClient, etc.)
- Performance requirements P1-P10

---

## 6. Realistic projections by week

**Week 1 (ACC-M REV only at $100)**:
- Expected: $0-50/day depending on day's volatility
- 7-day target: $50-300 cumulative
- Stop loss: -$30 on any day

**Week 2 (ACC-M REV + MAS REV, $200 total)**:
- Expected: $5-65/day combined
- 7-day target: $100-450 cumulative

**Week 3 (+ ACC-PC, $300 total)**:
- Expected: $15-85/day combined
- 7-day target: $200-600 cumulative

**Week 4+ (validated scale-up)**:
- If any strategy crosses $200/week: scale 2x
- If all 3 sustainable at $300 each: $900 total capital, $90-250/day expected

**Compound math**: starting at $300, growing at $30/day average = $930 after 30 days. Reinvesting profits at $30/day = $1100 after 30 days. Don't get attached to big projections — start, validate, grow.

---

## 7. Risk caveats (read carefully)

1. **All backtest numbers are simulation, not live results.** Real fills may be lower than simulated; queue dynamics may favor faster bots; latency matters. The validation is +EV but live could be worse.

2. **Per-slug variance is HIGH**. Stddev at sz=20 is $7/slug. At sz=100 it's $21/slug. You will have -$15 slugs. Plan for them.

3. **ACC-M's reference wallet `0x04b6d7e9` does MAS in chain history** (98% SELL maker), not ACC-M (BIDs). We're capturing the same edge from the opposite book side. This works in simulation; live behavior may differ if our BID-side is more crowded than their ASK-side.

4. **MAS is barely break-even at small pre-mint.** It's a data-gathering deployment, not a profit engine. If live shows -$5/day for a week, halt it.

5. **ACC-H V3f explicitly LOSES money** in fee-accurate simulation. The pickup's claim of $50-150/day for ACC-H is unsupported by our data. Treat shadow logs as research, not pre-deployment validation.

6. **No directional alpha decoded.** All our wallets either pair-arb (50/50 outcomes) or pick directional with random results. The $248/slug winner (`0x89b5cdaa`) has 51.5% win rate — basically random. Don't expect directional edge.

7. **Slug-selection signal not implemented yet.** `0xcfb103c3` engages thin-book slugs (z=-17.86 on depth). Adding this filter to ACC-M may improve PnL but isn't in this spec yet.

8. **Multi-asset (ETH/SOL) not yet validated** at sz=20. ACC-M REV starts with BTC 5m only.

---

## 8. The honest answer to "are our 3 strategies wrong?"

**Short answer**: ACC-M is right but undersized. ACC-H is wrong (taker layer is harmful). MAS is right but undersized AND barely profitable at our scale.

**Long answer**: We had the right INSTINCTS — the pair-arb maker pattern is real and profitable, the mint-and-sell pattern is real, and hybrid maker+taker exists. But:
- The wallets we copied don't all do what we thought (`0x04b6d7e9` is MAS, not ACC-M)
- The V3f composite taker we built isn't profitable in fee-accurate simulation
- All our spec POST_SIZEs were 4-40x too small

The strategies in the handoff are 90% the right design. They need to be:
- ACC-M: resized 4x
- ACC-H: dropped from live, run shadow only
- MAS: kept small, accepted as marginal
- ACC-PC: added as the lower-variance variant we should have built from the start

That + accepting that $30-85/day on $300 is the realistic target (not $100-300/day on $200) is the honest revision.

---

## 9. Immediate next actions

For the user (you):
1. Read this document
2. Approve the revised plan (or reject specific items)
3. Decide on $300 total commitment (or smaller — could start with just ACC-M REV at $100)

For TV agent:
1. Read `TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md` (existing plan stands for infrastructure)
2. Apply spec changes per §5.1 above
3. Build per-rule shadow logging (so we can validate ACC-H without committing capital)
4. Implement ACC-PC as new strategy module

For ongoing research (parallel to deployment):
1. Build `pat_backtest.py` simulator
2. Decode `0xeebde7a0`'s actual taker behavior (V3f decode was incomplete)
3. Try to find a slug-selection signal that explains $0xcfb103c3$'s edge

---

## 10. Bottom line

**Start with $100 on ACC-M REV (POST_SIZE=20). Validate for 7 days. If profitable, add MAS REV at $100. Then ACC-PC. ACC-H stays in shadow.**

Expected income at full $300 deployment: $30-85/day.

This is a 10x downward revision from the original handoff. It's also the honest answer based on 213-slug backtest + 5-wallet chain decode.

The original plan was based on inflated wallet stats. The revised plan is based on what actually showed +EV in simulation. Start small, prove it works live, scale only when validated.

---

*See `OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md` for the full data + analysis. See `MORNING_READ_2026_05_19.md` for the executive summary.*
