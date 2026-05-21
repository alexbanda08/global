# ACC-PC backtest — head-to-head vs ACC-M

**Date**: 2026-05-19
**Engine**: `strategy_lab/backtests/acc_pc_backtest.py`
**Data**: 50 BTC 5m slugs from `data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet` (event-level L25, no 1Hz subsampling) + `data/v4/canonical/trades_polymarket/btc.parquet`
**Window**: 2026-04-26 → 2026-05-03 (7-day window, evenly-spaced sample)
**Fill model**: **FIFO queue** (track shares ahead of us, decrement on each taker SELL trade) — strictly more realistic than the 5% queue-share heuristic in legacy simulators

---

## TL;DR

- **Both strategies LOSE money** at $50 seed on this 50-slug sample.
  - ACC-M: **-$1.04/slug** mean, 16% profitable, sum -$52
  - ACC-PC: **-$1.12/slug** mean, 18% profitable, sum -$56
- **ACC-PC taker layer barely fires** (only 12/50 slugs see any taker activity, mean 0.34 buys/slug)
- The **binding filter is `pair_cost < $0.97`** — not CVD. Disabling CVD produced IDENTICAL results.
- **Root cause**: bid-ask spread + 7% taker fee make pair-completion via TAKER ASK economically unviable in most slug states (typical pair_cost = $1.02-1.04, above our $0.97 ceiling)
- **Leftover-burn is the dominant loss source** for ACC-M: cost paid $22.23/slug vs cash recovered $21.46/slug + rebates $0.11 = net -$0.66/slug structural, plus variance

---

## 1. Backtest configuration

```python
StratConfig (ACC-M baseline):
  post_size = 5                # CLOB minimum
  min_bid_price = 0.05
  max_bid_price = 0.95
  max_sum_bids = 1.00          # only post when sum_bids < $1
  max_spread_per_leg = 0.05
  cancel_threshold = 0.03      # 3¢ displacement
  max_order_age_s = 20
  max_imbalance = 5            # strict
  absolute_max_inv = 50
  merge_threshold_pairs = 5
  stop_posting_offset_s = 270  # 30s before close

ACCPCConfig (extends ACC-M):
  max_imbalance = 10           # looser
  enable_taker = True
  max_pair_cost = 0.97         # cushion below break-even
  min_time_before_taker_s = 30
  min_spread_to_taker = 0.02   # don't take if BID close to ask
  cvd_window_s = 30
  cvd_min_threshold = 0        # only fire if buyers dominating
  max_taker_per_slug = 20
  min_s_between_taker = 5
```

Fees: **Polymarket real curve** `fee = 0.07 × p × (1-p)` per share, maker rebate = `0.20 × fee`.

---

## 2. Results — 50 slugs

| Metric | ACC-M | ACC-PC |
|---|---|---|
| Mean PnL/slug | **-$1.04** | **-$1.12** |
| Median PnL/slug | $0.00 | $0.00 |
| Sum PnL (50 slugs) | -$51.99 | -$56.18 |
| % profitable slugs | 16% | 18% |
| Mean fills/slug | 12.1 | 13.7 |
| Mean merges/slug | 4.0 | 4.5 |
| Mean pairs merged | 20.7 | 23.4 |
| Mean cost paid | $22.23 | $24.96 |
| Mean rebates | $0.11 | $0.13 |
| Mean cash recovered | $21.08 | $23.74 |
| Mean leftover redeemed | $0.37 | $0.38 |
| Mean leftover burned | $5.88 | $7.04 |
| Mean taker buys/slug | 0 | **0.34** |
| Slugs with ≥1 taker fire | 0 | 12/50 |
| Mean taker fees | $0 | $0.026 |

### Diff distribution

- ACC-PC better than ACC-M: 28% of slugs
- ACC-PC same: 38% of slugs (no taker fire)
- ACC-PC worse: 34% of slugs

### Per-slug variance

ACC-M has many zero-PnL slugs early in window (11 of first 14 slugs = 0 fills, 0 PnL). These slugs likely have very low taker SELL activity within the 5-minute window. With a FIFO 24-share queue ahead of us, we need ≥24 shares of cumulative taker SELL volume to start filling — many slugs don't reach that threshold.

After warmup window, both strategies fire on most slugs but produce variance: typical slug PnL is in [-$10, +$5].

---

## 3. Root-cause diagnosis

### 3.1 Why ACC-M loses money

Decomposing the avg slug:
```
cost paid                  -$22.23
cash recovered (merges)    +$20.71   (20.7 pairs × $1)
leftover redeemed          +$0.37    (winning-side leftover)
rebates                    +$0.11
                          ---------
net                        -$1.04
```

The maker pair-arb edge per pair MERGED is small but positive:
```
avg_pair_cost (per merged pair)  = $22.23 - cost_of_unredeemed
                                 ≈ 20.71 / 20.7 = $1.00 (approximately)
merge value per pair             = $1.00
profit per merged pair           ≈ $0.00 + $0.005 rebate per share = $0.01/pair
```

When this profit is averaged over the ~20.7 pairs merged per slug, that's $0.21/slug of pure edge.

The **$5.88 burned leftover** per slug is what overwhelms it. Even though MOST inventory pairs, some doesn't pair before slug close — and on the losing side that cost evaporates.

### 3.2 Why ACC-PC doesn't fix the leftover problem

The ACC-PC trigger requires `pair_cost < $0.97`, where:
```
pair_cost = avg_cost_per_share_on_leading_side
          + current_ask_on_lagging_side
          + taker_fee_per_share(lagging_ask)
```

Typical book state when we're imbalanced:
- avg cost leading side: $0.48 (we got filled when sum_bids was low)
- lagging side current ask: $0.52 (spread is 2-3¢)
- taker fee: 0.07 × 0.52 × 0.48 = $0.0175
- **pair_cost ≈ $1.018** — exceeds $0.97 ceiling

This is the **structural problem**: bid-ask spread + taker fee make pair-completion via TAKER ASK uneconomical except in unusual market conditions.

Of the 50 slugs:
- 12 had at least one ACC-PC fire (taker ask momentarily dipped enough to pass `pair_cost < $0.97`)
- Average 0.34 taker buys/slug across all 50

**Verifying CVD wasn't binding**: running with `--no-cvd` produced **identical numbers**. The `pair_cost ≥ $0.97` filter rejected all cases before CVD was checked.

### 3.3 Why the FIFO queue model matters

Switching from "5% of trade size" heuristic to FIFO with `queue_ahead = bid_size_at_best (24 shares typical)`:
- Old fill rate: 88 fills/slug
- New fill rate: 12 fills/slug
- 7× drop

This is much more realistic. Real makers DO have to wait for shares ahead of them in the queue to fill first. The 88-fill number was implausibly optimistic.

12 fills/slug @ $0.50 avg = $6/slug of inventory deployment per side. With 5-share orders → 1.2 fills × 5 = 6 shares per side per slug = OK.

---

## 4. What this tells us about the spec

### 4.1 ACC-M spec is technically correct but...

The maker pair-arb edge IS real (sum_bids < $1 creates an arbitrage). But at our scale ($50 seed, 5-share posts, back of 24-share queue), the edge per slug is:
- Pure pair-arb: ~$0.01-0.02/pair × 20 pairs ≈ +$0.20-0.40/slug
- Rebates: ~+$0.10/slug
- **Leftover burn**: ~-$1.50/slug (variance: positive on winning-side leftover, negative on losing-side)

Net: **the leftover variance dominates the small per-pair edge**. With perfect inventory balance (max_imbalance = 0), the strategy would be break-even-to-slightly-positive. With imbalance = 5 it loses about $1/slug on average.

### 4.2 Reference-wallet calibration

LB-API showed `0x04b6d7e9` (ACC-M reference) makes **$2,038/day** on **$47.6M cumulative volume**. Their working capital is implied to be $10-50k.

Scaling our $50 seed at 1:1000 ratio to their $50k bankroll → expected $2/day at our scale = **+$0.16/slug if 12 BTC 5m slugs/h × 24h = 288 slugs/day**.

Our backtest shows **-$1.04/slug**. That's **-$1.20/slug worse** than the linear-scaled reference.

Possible reasons for the gap:
1. **Reference uses better queue position**: posts at best_bid (not behind the existing queue), reposts aggressively, or uses larger order sizes that get serviced earlier in the queue
2. **Reference uses tighter imbalance** discipline → less leftover burn
3. **Reference has slug-selection signal** we don't see → only fires on PROFITABLE slugs (skips the unfavorable ones)
4. **Our backtest is too pessimistic** about fills (queue model may overstate the queue ahead of us)

### 4.3 ACC-PC variant — premise is structurally limited

Pair-completion via taker ASK only works when:
```
avg_cost_leading + current_ask_lagging + taker_fee < $1.00 - safety_margin
```

With typical book: $0.48 + $0.52 + $0.018 = $1.02. **Above $1, before any safety margin.**

For ACC-PC to trigger usefully, we'd need:
- Either avg_cost_leading < $0.40 (we got filled on a deep dip)
- Or lagging-side ASK < $0.45 (its book also dipped)
- Or both

In 50 slugs we saw 12 such moments. **Not enough to materially reduce leftover risk.**

---

## 5. Better variants to investigate

### 5.1 Hedge-at-close ACC-PC variant (most promising)

Instead of pair-completion at `pair_cost < $0.97`, do **end-of-slug forced hedge**:

```python
def check_close_hedge(state, cfg, now_us, slot_end_us):
    """Hedge imbalance in last 30s of slug to lock in merge value."""
    remaining_s = (slot_end_us - now_us) / 1_000_000
    if remaining_s > 30:
        return False
    if min(state.inv_up, state.inv_dn) >= cfg.max_inv:
        return False  # already balanced

    imbalance = abs(state.inv_up - state.inv_dn)
    if imbalance < 1:
        return False
    # Always hedge in last 30s, even at pair_cost > $1 — better than leftover risk
    return True
```

EV analysis:
- 5 shares leftover at $0.50 avg cost = $2.50 cost basis
- If we don't hedge: 50% win → +$2.50, 50% lose → -$2.50, EV = $0
- BUT variance is high (each slug ±$2.50)
- Hedge cost: take 5 lagging-side at $0.55 + fee = $2.775. Merge for $5. Net cost = $5.275 - $5 = -$0.275 (locked loss)

So hedging trades **variance reduction for a small expected cost**. Over many slugs, this Sharpe-improves the strategy substantially.

Worth backtesting.

### 5.2 Tighter imbalance (max_imbalance = 1 or 2)

Currently ACC-M allows 5-share imbalance before pausing the heavy side. Tightening to 1-2 would reduce leftover but also reduce total volume.

Sweep candidate: max_imbalance ∈ {1, 2, 3, 5}.

### 5.3 Aggressive BID lift (post at best_bid + 1¢)

Instead of waiting in the queue, post at `best_bid + 0.01` to jump ahead of the 24-share queue. Costs: 1¢/share more expensive. Gains: much higher fill rate.

This is structurally different from current ACC-M but matches what observed top performers may do.

### 5.4 Skip slugs that don't pair early

Decision: if first 60s passes with no fills on either side, SKIP the slug entirely (don't post for the rest).

Reasoning: dead slugs have no taker flow → won't yield fills → no edge.

---

## 6. Honest recommendation to TV agent

Given this backtest reveals ACC-M as spec'd doesn't unambiguously profit at $50 seed:

### 6.1 Don't deploy ACC-M live yet

Run the SHADOW mode for 48-72h on Ireland VPS, but do NOT promote to live until you see:
- Mean PnL/slug > +$0.10 on the live shadow data (not historical replay)
- 60%+ profitable slugs
- Leftover burn < $2/slug consistently

If shadow shows -$1/slug like our backtest, deploying live just burns $50 seed in ~50 slugs (= 1 day at BTC 5m alone).

### 6.2 Test 4 spec variants in shadow

Run all 4 in parallel:
1. **ACC-M-A**: current spec (max_imbalance=5, BID at best_bid)
2. **ACC-M-B**: tight imbalance (max_imbalance=2)
3. **ACC-M-C**: aggressive BID lift (best_bid + 1¢)
4. **ACC-M-D**: ACC-M + close-hedge (force balance in last 30s)

Each operates independently (same data, different decisions). Compare per-slug PnL.

### 6.3 Drop ACC-PC variant for now

The pair-completion taker premise is structurally limited. Not worth dedicated capital. If we want a hybrid, **ACC-M-D (close-hedge)** is a better path.

### 6.4 Revise PnL expectation again

Backtest at $50 seed: -$1/slug (~-$300/day if deployed at BTC 5m, but capital depletes in ~50 slugs).

If we get to **break-even or +$0.10/slug** after tuning, that's $0-30/day at BTC 5m + 15m on $200 capital. **Order of magnitude smaller than the original $100-300/day projection.**

The reference wallets make their money at $50k+ bankroll where:
- Larger orders get better queue position
- Wider asset/TF mix smooths variance
- Long tail of favorable slugs compounds

At $50 seed in pure shadow, we likely can't replicate that.

---

## 7. Data fidelity confirmation

For the record: this backtest used **maximum-resolution local data** equivalent to VPS3:
- Event-level L25 (NO 1Hz subsampling) → median 29ms between snapshots
- All 25 levels per side
- FIFO queue model using `bid_size_0` as queue-ahead
- Real Polymarket trades for fill simulation
- Real fees (0.07 × p × (1-p))

The numbers are not a fidelity artifact. The strategy as designed has thin edge at our scale.

---

## 8. Files

| Path | Purpose |
|---|---|
| `strategy_lab/backtests/acc_pc_backtest.py` | Backtest engine (event-level, FIFO queue) |
| `strategy_lab/backtests/_acc_pc_results.csv` | Per-slug results (latest run) |
| `strategy_lab/backtests/_acc_pc_summary.json` | Aggregate summary |
| `strategy_lab/backtests/_run_baseline.log` | 50-slug baseline log |
| `strategy_lab/backtests/_run_nocvd.log` | 50-slug --no-cvd log (identical to baseline) |
| This document | `strategy_lab/reports/ACC_PC_BACKTEST_2026_05_19.md` |

---

## 9. Next steps

1. **Build close-hedge variant** (ACC-M-D) — most promising direction. ~30 LOC change to engine.
2. **Parameter sweep**: max_imbalance ∈ {1, 2, 3, 5} × bid_lift ∈ {0, 1¢, 2¢}. ~12 backtest runs.
3. **Expand slug sample to 200-500** to reduce variance noise (50 slugs is statistically thin)
4. **Compare to chain-decoded `0x04b6d7e9` PnL** on the EXACT same 50 slugs to identify where our model diverges
5. **Verify queue model** by comparing simulated fill rate vs reference-wallet actual fill rate per slug

If none of those produce a clear +EV variant, **the original premise (ACC-M at $50 seed) may need to be abandoned in favor of running observer-only shadow on Ireland VPS first** to learn what the live market dynamics actually look like before committing capital.
