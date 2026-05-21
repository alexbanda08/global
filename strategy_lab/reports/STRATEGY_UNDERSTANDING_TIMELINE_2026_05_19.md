# How our understanding of the wallets evolved (and whether the current specs are right)

**Date**: 2026-05-19
**Question being answered**: We re-analyzed these wallets multiple times and arrived at different specs each time. Are the LATEST specs (the ones TV agent is about to implement) actually right?

---

## TL;DR

The current specs are our **best guess to date**, built on the largest dataset (213 slugs) using fee-accurate simulation. Three things they get RIGHT with high confidence:

1. **POST_SIZE 5 is wrong** — bigger is better (validated 5-200 sweep)
2. **ACC-H V3f composite taker LOSES money in simulation** (-$6.84/slug consistent across 4 wallets)
3. **Pair-arb maker mechanism works** — the maths of sum_bids < $1 → merge for $1 is solid

Two things they may still be WRONG about:

1. **Our reference wallets don't do what we think they do.** The wallet ACC-M was built on (0x04b6d7e9) actually does the MAS pattern (98% SELL maker) in chain history. Our ACC-M (post BIDs) captures the opposite side of the same edge.
2. **ACC-H may actually work live.** The V3f decode was rigorous (78.9% taker-fire coverage at 1.37× lift). Our backtest says it loses; one of those is wrong.

**Shadow validation is essential.** The current specs are hypotheses, not facts.

---

## Timeline — six analyses, six different conclusions

### Day 1 (2026-05-16) — three contradictory readings

**Session A** (`WALLET_HUNT_eebde7a0_2026_05_16.md`)
- Data: 6 hours of /activity from data-api (3,474 trades)
- Conclusion: 0xeebde7a0 is a **CONTRARIAN MOMO FADER**. 64.3% WR on legs that contradict binance pre-window momentum.
- Recommendation: build `momo_INV_15m` — exact opposite of our momo strategy.
- The wallet was **losing money** (-$190 on resolved legs, -$3,077 unrealized).

**Session B** (`STRATEGY_DECODED_2026_05_16.md`)
- Data: 5,500 fires across 3 wallets cross-referenced with L25 books
- Conclusion: ALL 3 wallets do the **same MAS strategy** (`sum_asks > $1` → splitPosition → post limit SELLs both sides). 100% of fires match.
- No directional signal. Pure microstructure arbitrage.
- Daily PnL claims: 0x04b6d7e9=$212k, 0xeebde7a0=$344k, 0x89b5cdaa=$10k.

**Session C** (`WALLET_HUNT_MULTIWALLET_2026_05_16.md`)
- Data: 6 wallets via /trades aggregation
- Conclusion: **4 different strategy types**. 0xce25e214 = pyramid_taker (contrarian, winner). 0x04b6d7e9 = single_fire_taker. 0x89b5cdaa = maker_both_sides. 0xeebde7a0 = pyramid_taker (loser).
- Two profitable: 0xce25e214, 0x04b6d7e9. Both win on BTC 15m, lose on 5m.

**Session D** (`MINT_AND_SELL_REPLICATION_2026_05_16.md`)
- Data: backtest of the MAS strategy from Session B
- Conclusion: $25 mint × 5M+ opportunities = $1,206/day. Scaled 8× = $9,646/day, matching 0x89b5cdaa's observed $9,765/day.

**Where they diverged**:
- A focused on **directional bias** (binance match)
- B focused on **book microstructure** (sum_asks)
- C focused on **trade-volume fingerprint** (frequency, side ratio)
- Each saw the same wallet through a different lens.

### Day 2 (2026-05-17) — 9 wallets, refined types

`WALLET_STRATEGIES_DECODED_2026_05_17.md`

- 0xb27bc932 emerges as kingpin: **$254k/day, 2-sided CLOB scalper** with relay-wallet exit.
- 0x0fe40e88 ($19k/day) = non-up-down (sports markets).
- F2 cluster (0x9dae874a, 0xa0a50783) = pure binance-directional HOLD.
- 0xcfb103c3 = **failed scalper** copy of 0xb27bc932.

Different framing again. Now PnL is the lens, and the kingpin shifts.

### Day 3 (2026-05-18) — convergence to 3 strategies

`MULTI_WALLET_ALPHA_DECODE_2026_05_18.md` + `STRATEGY_FINAL_REVISED_2026_05_18.md`

Introduced **paired_pct** (Up vs Down inventory balance) + **leftover_on_winner_pct** (directional alpha):

| Wallet | Paired% | Imbalance% | Verdict |
|---|---|---|---|
| 0x04b6d7e9 | 92% | 8% | **PURE PAIR ARB** → ACC-M |
| 0xeebde7a0 | 50% | 50% | **HYBRID arb + directional** → ACC-H |
| 0x89b5cdaa | 0% | 100% | **PURE DIRECTIONAL** → skip (no signal) |

Written specs:
- **ACC-M**: "MIMICS the 3 winning Polymarket wallets" — post BIDs both sides, accumulate paired inventory, merge for $1.
- **MAS**: "**None of our decoded wallets actually do this.**" Self-described as "**our V3 invention**" — be the OTHER side of the accumulator wallets.
- **ACC-H**: ACC-M + V3f composite taker (4 rules: Discount-capture + Sharp-drop + Early-slot + Buy-pressure-then-dip). 78.9% coverage at 1.37× lift on Bonereaper's taker fires.

This is what was handed to TV agent on 2026-05-18.

### Day 4 (2026-05-19) — audit + revisions

**Three audits in one day**:

1. `STRATEGY_AUDIT_REFS_ONLY_2026_05_19.md`
   - Re-ran v3 on the 16 reference wallets using LB-API data
   - **NEITHER MAS reference (0xf7f0b0b1, 0xd44e2993) currently practices mint-and-sell.** They show pair-arb pattern in /activity.
   - 0x04b6d7e9 (ACC-M ref) shows 100% BUY in last 1 hour of /activity — but 98% SELL maker in chain history. **Contradiction.**
   - Recommendation: postpone MAS, keep ACC-M.

2. `OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md`
   - Ran multi-strategy backtest on 213 slugs across 5 wallets
   - **ACC-M-sz5 (current spec)**: +$0.37/slug (marginal)
   - **ACC-M-sz100**: +$3.54/slug (5x better, just from bigger size)
   - **ACC-H V3f**: **-$6.84/slug** (LOSES money across all 5 wallets, opposite of pickup claim)
   - **MAS pre30**: +$0.09/slug (essentially flat)
   - **MAS pre500**: -$3.02/slug (actively harmful)

3. `PAT_FINDINGS_2026_05_19.md`
   - Built PAT (Pair-Arb Taker) simulator
   - Pure PAT: +$0.21-0.67/slug (marginal — fires too rarely)
   - **PAT+ACC-M HYBRID: +$1.98/slug** — best variant, 20% better than ACC-M alone

Final specs (the ones TV agent will implement):
- PAT+ACC-M HYBRID (modified ACC-M with PAT overlay)
- MAS REV (2 cells only, $30 pre-mint)
- ACC-H (SHADOW ONLY, never live)
- ACC-PC (new — pair-completion taker, shadow)
- PAT-shadow (research)

---

## Why sessions diverged — 5 root causes

### 1. Different data sources gave different stories

| Source | Window | What it shows | What it misses |
|---|---|---|---|
| `/activity` data-api | last 1-6 hours | recent behavior snapshot | Misses long-term pattern |
| `/trades` chain decode | 1-30 days | full historical behavior | No book context |
| `L25 book scan` | 21 days | structural opportunities (sum_asks > $1) | No PnL truth |
| `fills.parquet` enriched | full | per-fill maker/taker + offset_s | Joined data is hard |
| LB-API `/profit` | 1d/7d/30d/all | true daily PnL | Black-box, no behavior |
| Backtest simulation | replays full data | fee-accurate per-slug PnL | Sim != live |

A wallet looks like one strategy in /activity and a different strategy in chain history because they're **different time windows of the same wallet doing different things**.

### 2. Same wallet does different things at different times

`0x04b6d7e9` is the clearest example:
- Chain decode (30 hours, 54k fills): **98% SELL maker** (MAS pattern)
- Recent /activity (1 hour): **100% BUY** (ACC-M pattern)
- Both are true. They run multiple modes.

Our specs were written from chain analysis but recent behavior is different.

### 3. Different analytical frames

| Day | Frame |
|---|---|
| 1A | Directional bias (binance match WR) |
| 1B | Book microstructure (sum_asks > $1) |
| 1C | Trade fingerprint (taker/maker ratio + frequency) |
| 3 | Paired-pct + leftover analysis |
| 4 | Fee-accurate simulated PnL |

Each frame highlights different patterns. None is wrong; they're complementary. But each session committed to ONE frame and concluded confidently.

### 4. Sample-size variance was huge

| Session | Sample |
|---|---|
| Day 1A | 87 resolved legs, 1 wallet |
| Day 1B | 5,500 fires, 3 wallets |
| Day 1C | 6 wallets, ~3,500 trades each |
| Day 3 | 5 wallets full chain, ~50k fills each |
| Day 4 | 213 slug backtests, 5 wallets, 1.5d window |

Small samples gave high-confidence wrong answers. Large samples gave more conservative (but possibly more correct) answers.

### 5. Pickup numbers were inflated

LB-API audit revealed pickup numbers (`$254k/day`, `$344k/day`) were **50-170x overstated**. Actual LB-API run-rates per wallet:

| Wallet | Pickup claim | LB actual 30d/day |
|---|---|---|
| 0xeebde7a0 | $344k/day | **$6.0k/day** |
| 0xb27bc932 | $254k/day | **$1.7k/day** |
| 0x04b6d7e9 | $212k/day | **$2.0k/day** |

This affected sizing (we thought wallets used $50k+ working capital; actually unknown but likely $10-50k).

---

## What changed in the SPECS over time

### ACC-M (the most-revised strategy)

| Day | What | POST_SIZE | wallet seed |
|---|---|---|---|
| 5-16 | Initial decode | n/a | n/a |
| 5-18 | First spec | 5 | $50 |
| 5-19 audit | "Resize" | 50-200 | $500-2000 |
| 5-19 refs-only | "Keep at 5" | 5 | $50 |
| 5-19 today | PAT+ACC-M HYBRID | **20** | **$200** |

Each step refined the size based on new data:
- Day 3 spec used CLOB minimum (5) without size optimization
- Day 4 audit found size 100-200 best in 30-slug sweep
- Day 4 refs-only walked back to 5 (didn't want to extrapolate)
- Day 4 today: 213-slug validation showed size 20 = best Sharpe; size 100-200 = highest mean but high variance. PAT overlay added +20% PnL.

### MAS (existence questioned then restored)

| Day | What | Status |
|---|---|---|
| 5-16 Session B | "All 3 wallets do MAS" | Believed |
| 5-18 STRATEGY_SPEC_MAS | "None of our wallets do this. MAS is our invention" | Hypothesis |
| 5-18 V3 backtest | "+$5-10k/day projected" | Profitable in sim |
| 5-19 audit refs-only | "Both MAS refs DON'T currently mint" | Doubt |
| 5-19 213-slug backtest | "+$0.09/slug at pre30, harmful at pre500" | Marginal |
| 5-19 today | "Keep small for data collection" | Hold |

MAS oscillated between "the universal strategy" and "our invention nobody actually does". The current spec is a small data-collection deployment.

### ACC-H (V3f composite taker)

| Day | What | Status |
|---|---|---|
| 5-18 V1 decode | Rule A (Discount-capture), 33% coverage | Confidence: moderate |
| 5-18 V2 decode | A+B+C, 68.9% coverage | Confidence: high |
| 5-18 V3 decode | A+B+C+D (V3f), 78.9% coverage at 1.37× lift | "**RECOMMEND DEPLOY**" |
| 5-18 ACC-H spec | "Edge $0.10-$0.30 per pair" + "$50-150/day target" | Pickup numbers |
| 5-19 backtest (213 slugs) | **-$6.84/slug**, loses across all 5 wallets | Hard contradiction |
| 5-19 today | SHADOW ONLY, never live | Defer |

The V3f decode was rigorous (chain-feature regression on 1349 fires + 1401 controls). But fee-accurate simulation shows it bleeds money. One of these is wrong.

---

## Are the current specs right?

### What we're confident in (HIGH confidence)

1. **POST_SIZE 5 was wrong.** Bigger orders get more fills (validated 5 → 200 sweep, 213 slugs).

2. **ACC-H V3f loses money in simulation.** -$6.84/slug across 5 different wallets is a robust signal, not noise.

3. **Pair-arb maker mechanism is sound.** Buying paired Up+Down at sum < $1 and merging for $1 is mathematically guaranteed positive when fills happen at the bid.

4. **MAS at $500 pre-mint is harmful** (-$3.02/slug). Don't over-mint.

5. **BID lift +1¢ is harmful** (-$3.61/slug). Don't try to skip the queue.

### What we're uncertain about (MEDIUM confidence)

1. **PAT+ACC-M HYBRID = +$1.98/slug.** Backtest said so on 87 slugs. Could be sample noise. Live shadow will tell.

2. **Recent reference-wallet behavior is bid-side.** Chain decode says they do BOTH (BIDs and ASKs at different times). Our spec captures BIDs. Live data will reveal current edge direction.

3. **ACC-PC is marginally positive** (+$0.30-0.50/slug). Could be noise.

4. **Sweet-spot POST_SIZE between 20-100.** 20 has best Sharpe in our test; 100 has highest mean. Could be different live.

### What we may still be wrong about (LOW confidence)

1. **The wallets we copied might not be doing what we think.** 0x04b6d7e9 is the ACC-M reference, but their chain history shows 98% SELL maker (MAS pattern). Our ACC-M (BID side) works in simulation but doesn't match the wallet behavior we claimed to copy.

2. **ACC-H V3f might actually work live.** The V3f decode was rigorous and the reference wallet (Bonereaper) does make $6k/day per LB. Our simulator says V3f loses — but the simulator might be wrong about fee impact on taker timing.

3. **PAT alone fires too rarely to matter** (+$0.21-0.67/slug). The actual edge that 0xcfb103c3 (+$2.5k/day claimed) captures must be more sophisticated than our PAT — possibly hold-to-redemption with slug-selection signal.

4. **Slug selection layer not implemented.** Wallets engage 42-96% of slugs (huge variance). Our strategies engage every slug. Adding a selection filter could change everything.

5. **Live queue dynamics may differ from FIFO model.** Our simulator assumes we sit at the back of a 24-share queue and wait. Real makers have multiple concurrent orders, repost aggressively, and may achieve much better queue position than we model.

---

## Verdict: are the LATEST specs right?

They're the **most data-driven specs we've had**. Each prior session got something wrong because:
- Sample was too small (Day 1)
- Data source was a narrow window (Day 2)
- We confidently committed to one analytical frame (Day 3)

The current specs come from:
- Largest backtest sample (213 slugs)
- Fee-accurate simulation
- All 5 reference wallets included
- Multiple analytical frames combined

But they're STILL HYPOTHESES because:
- 213 slugs is meaningful but not huge
- Simulator may have inaccuracies
- Live behavior may differ
- Our reference wallets may have shifted what they do

**The right move**: deploy in shadow as planned. Validate the specific assumptions that could be wrong:
- Does PAT+ACC-M HYBRID actually fill at backtest rates?
- Does ACC-H V3f actually lose money live, or does our sim mismodel something?
- Does MAS at $30 break even or lose?
- What's the real fill rate vs FIFO model?

After 14 days of shadow data, we'll have the answer.

---

## What I'd watch in the shadow data

Specific signals to check in the first 7 days of shadow logs:

| Metric | Backtest expects | If different, what it means |
|---|---|---|
| ACC-M fill rate (per slug, per side) | 8-25 fills | <8 → queue model too optimistic, raise POST_SIZE; >25 → maybe we have better queue position than expected |
| PAT fire rate (per slug) | 0-2 | 0 always → threshold too tight; >2 → markets dislocate more than we thought |
| ACC-H V3f rule fire counts | A=33%, B=33%, C=20%, D=10% of fires | If far off, decoded thresholds may be stale |
| ACC-H simulated post-fire PnL per rule | All 4 should lose | If any rule is +EV, that subset might be deployable |
| MAS fill rate at pre30 | 5-15 ASK fills/slug | <5 = nobody buying our asks; MAS unviable at small scale |
| ACC-PC fire rate | <1/slug | Too rare = filters too tight; if >2/slug, CVD filter may not be working |

After 14d, decide:
- If ACC-M-sz20 hits >$1/slug → scale to sz=100, then $200 wallet
- If ACC-H V3f shows any rule with positive PnL → revive that rule only
- If MAS stays flat → drop or pivot
- If PAT+ACC-M HYBRID shows the +20% uplift → it's real
- If nothing works → re-decode wallets with fresh data

---

## Bottom line

The current specs are right enough to deploy in shadow. They're not necessarily right in absolute terms — they're our **best guess pending live validation**.

The KEY change from prior sessions is that THIS time we're being **honest about uncertainty**:
- Shadow first, no live capital until validation
- Per-rule logging for ACC-H so we can attribute
- Multiple shadow sleeves so we can compare in parallel
- Halt conditions defined upfront

Previous handoffs claimed $100-300/day with certainty. This one says "shadow it and see, expect $20-85/day if it works at all."

That's the right framing. Ship the shadow deploy, let the data speak, adjust based on what we learn.
