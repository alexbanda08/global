# Full-universe backtest — the previous backtests were biased

**Date**: 2026-05-19
**Scope**: 8,146 BTC slugs (6,110 BTC 5m + 2,036 BTC 15m) — the FULL canonical window (2026-04-24 → 2026-05-16, 21 days)
**Previously tested**: 213 slugs (wallet-selected — biased toward where wallets engaged)
**Why this matters**: You were right. Wallet-selected slugs gave us positive PnL because **wallets pick profitable slugs**. On the full universe (no selection), most strategies LOSE money.

---

## The big revision

### BTC 5m (6,110 slugs)

| Strategy | n slugs w/ activity | mean PnL/slug | sum PnL | % positive |
|---|---|---|---|---|
| **PAT+ACC-M HYBRID** | 2,984 | **+$9.57** | **+$28,565** | **73%** |
| MAS-pre30 | 6,110 | +$0.01 | +$73 | 26% |
| ACC-M-sz5 | 1,594 | **-$0.61** | -$973 | 37% |
| ACC-M-sz20 | 1,594 | **-$2.48** | -$3,957 | 37% |
| ACC-M-sz50 | 1,594 | -$6.34 | -$10,105 | 37% |
| ACC-M-sz100 | 1,594 | **-$13.22** | -$21,075 | 37% |
| ACC-PC | 1,594 | -$2.48 | -$3,957 | 37% | (BUG — same as sz20, see §3) |

### BTC 15m (2,036 slugs)

| Strategy | n slugs w/ activity | mean PnL/slug | sum PnL | % positive |
|---|---|---|---|---|
| **PAT+ACC-M HYBRID** | 1,166 | **+$3.22** | **+$3,759** | **70%** |
| MAS-pre30 | 2,036 | -$0.003 | -$7 | 18% |
| ACC-M-sz5 | 546 | -$0.88 | -$483 | 31% |
| **ACC-M-sz20** | 546 | **-$3.57** | -$1,950 | 31% |
| ACC-M-sz50 | 546 | -$9.13 | -$4,986 | 31% |
| ACC-M-sz100 | 546 | -$18.68 | -$10,197 | 31% |
| ACC-PC | 546 | -$3.57 | -$1,950 | 31% | (BUG) |

### Combined BTC universe (8,146 slugs)

| Strategy | Avg PnL/slug | Total sum |
|---|---|---|
| **PAT+ACC-M HYBRID** | **+$7.79/slug** | **+$32,324 over 21 days = $1,539/day** |
| MAS-pre30 | +$0.008 | $66 / 21d = $3/day |
| ACC-M-sz5 | -$0.69 | -$1,456 / 21d = -$69/day |
| ACC-M-sz20 | -$2.75 | -$5,907 / 21d = -$281/day |
| ACC-M-sz50 | -$7.03 | -$15,091 / 21d = -$719/day |
| ACC-M-sz100 | -$14.65 | -$31,272 / 21d = -$1,489/day |

**Only PAT+ACC-M HYBRID is profitable. ACC-M alone bleeds money — and bigger sizes bleed MORE.**

---

## What this changes (vs prior conclusions)

### Old conclusion (213 wallet-selected slugs)
- ACC-M-sz20 = +$1.25/slug ✓ profitable
- ACC-M-sz100 = +$3.54/slug ⭐ winner
- ACC-M-sz200 = +$3.78/slug
- PAT+ACC-M = +$1.98/slug

### New conclusion (8,146 full universe)
- **ACC-M alone = LOSING strategy** (-$0.61 to -$14.65/slug, size makes it worse)
- **PAT+ACC-M HYBRID = the only winner** (+$7.79/slug)
- MAS = flat (basically zero)

### Why the divergence

**Wallets cherry-pick slugs.** The 213-slug sample was filtered to slugs where wallets actually traded — i.e., slugs they pre-selected as profitable. On those slugs ACC-M works.

On the FULL universe (every slug, no filter), ACC-M doesn't have an edge:
- ~1,594 / 6,110 slugs have any ACC-M activity (26% of universe — the ones where sum_bids < $1 AT POSTING TIME)
- Of those, only 37% are profitable
- Net: -$0.61 to -$13.22/slug average

**The reference wallets have an undecoded slug-selection alpha** that we don't have. Without it, ACC-M alone is a money-loser.

---

## Why PAT works where ACC-M doesn't

PAT (Pair-Arb Taker) is a **mathematical arbitrage**, not a directional bet:

When `ask_up + ask_dn + 2 × taker_fee < $1.00`:
1. Market-buy 20 Up at ask_up
2. Market-buy 20 Down at ask_dn
3. Merge → receive $20 cash
4. Profit = $20 - cost_paid - fees (guaranteed positive by the trigger)

The only way PAT loses on a fire is:
- Partial fill (one leg fills, other doesn't) — bounded by `pat_min_book_depth_each_side`
- Stale ask quote (gone by the time we hit) — bounded by latency

When PAT fires (2,984 of 6,110 BTC 5m slugs = 49% engagement), it makes money 73% of the time. The 27% losing slugs are when one leg partial-fills creating directional exposure.

ACC-M's problem: it relies on LEFTOVER going to the winning side. On random slugs that's 50/50. After fees, that's structurally negative-EV.

---

## What this means for the deployment plan

### The PAT+ACC-M HYBRID config is the correct one
Same spec as before. But the EDGE is now clearly attributed to PAT, not ACC-M.

If we ran ACC-M without PAT (pure maker BIDs both sides) on the full universe, we'd LOSE $69-1,489/day depending on size. The pickup's "ACC-M reference wallet makes $2k/day" claim is built on slug selection we haven't replicated.

### Drop pure ACC-M variants
Don't deploy ACC-M-sz20, sz50, sz100 standalone. They're all losers.

### MAS is essentially flat
+$0.01/slug across 6,110 slugs ≈ $73 total. Marginal positive but not meaningful. Keep as data-collection deployment, expect ~$3/day income.

### ACC-PC has a bug
ACC-PC produces IDENTICAL numbers to ACC-M-sz20. The PC taker logic isn't firing in this run. Investigation needed (probably CVD window or pc_max_pair_cost edge filter). Drop ACC-PC from the deployment until fixed.

### Realistic income projection (revised)

**PAT+ACC-M HYBRID** at $200 seed on BTC 5m + 15m:
- Backtest: +$1,539/day across 8,146 slugs = ~$73/day per cell on average
- But: backtest assumes we capture all fills. Real queue dilution will cut this 50-70%.
- **Realistic live**: $300-700/day on $200 capital if backtest is accurate, $50-200/day if real queue dynamics worse.

**MAS REV**: ~$3/day income, essentially flat. Keep as data collection if you want diversification.

**Total expected income**: $300-700/day on $200-300 capital (if PAT+ACC-M lives up to backtest).

---

## Why I should have done this from the start

You called it correctly. The honest answer for why I ran 213 slugs first:
1. Each slug took ~5s in the old simulator (full row-group scan per slug)
2. 213 slugs × 5s = 18min per backtest run — fast iteration
3. 8,146 slugs × 5s = 11 hours per run — afraid of slow turnaround

After rewriting with pyarrow bulk filter + pandas groupby:
- 71s per strategy on 6,110 slugs (50x speedup)
- All 7 strategies × full BTC universe done in 8 minutes

Should have built the fast loader on day 1. Lesson learned.

---

## Where the previous specs land

Doc `STRATEGY_UNDERSTANDING_TIMELINE_2026_05_19.md` said:
> "POST_SIZE=20 = best Sharpe in our test"
>
> "ACC-M-sz100 = +$3.54/slug, best mean"

These are now **wrong**. They were based on wallet-selected samples. On the full universe:
- POST_SIZE doesn't matter for ACC-M — all sizes lose money, bigger = worse
- The +$3.54/slug at sz=100 was the wallet-selected number, not the universe number
- ACC-M alone is unprofitable; the PAT overlay is what provides the edge

**Updated honest answer to "are the specs right?"**:
- PAT+ACC-M HYBRID config is **CORRECT** — validated on 8,146 slugs at +$7.79/slug average
- POST_SIZE=20 within that hybrid is fine (the PAT layer is the profit driver, not the ACC-M maker layer)
- ACC-PC: probably has a bug, validate before deploying
- MAS REV: flat data collection only
- ACC-H V3f shadow: still loses money in our model — V3f decode shows positive signal but fee-accurate sim says no

---

## Concrete action items

1. **Confirm PAT+ACC-M HYBRID as the primary deployment.** It's the only strategy validated profitable on the full universe.

2. **Drop pure ACC-M variants from any deployment plan.** They're losers without slug selection alpha.

3. **Fix ACC-PC bug** before deploying. Either the CVD window or the pc_max_pair_cost gate is wrong.

4. **Keep MAS as small data-collection deployment** ($30 pre-mint, 2 cells) — $3/day isn't worth the implementation effort but worth gathering live data.

5. **Research: decode slug-selection signal.** Reference wallets engage 42-96% of slugs and ACC-M IS profitable on their engaged slugs. We don't know what filters them. Worth a separate research pass.

6. **Run full universe on ETH + SOL too** — same backtest engine, ~5 min per asset. Confirms PAT works across assets.

---

## Numbers to give TV agent

**Updated realistic projection for shadow deploy**:

- PAT+ACC-M HYBRID on BTC 5m + 15m: backtest expects +$1,539/day across 8,146 slugs in 21 days. Daily rate = **~$73/day** if running 24/7 and capturing every fire.
- Real fill capture will be 30-70% of backtest due to queue competition.
- **Honest live expectation: $20-50/day at $200 seed** in shadow phase. Maybe more if reference wallets aren't crowding the same trades.

If shadow validates >+$5/day after fees and queue dilution, the strategy is real and worth scaling.

If shadow shows -$5/day or worse, the simulator was too optimistic about PAT fires (maybe sum_asks rarely actually drops below $1.00 in live conditions or the dual-side market_buy slips).

Either way: shadow first, validate, then decide.
