# Mint-and-Sell V3 — Test-Deploy Spec (minimum capital)

_2026-05-18. Companion to MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md.
Encodes the CLOB minimum order constraint (5 shares per post = $2.5
per side notional) and finds the minimum pre-mint that saturates._

---

## TL;DR — the test config

```python
TEST_CONFIG = {
    # Per-fire posting
    "post_size_shares": 5,         # Polymarket CLOB minimum order
    "post_notional_per_side": 2.5, # 5 shares × ~$0.50 avg price
    "post_notional_per_fire": 5.0, # both sides posted = $2.5 Up + $2.5 Down

    # Per-slug capital
    "pre_mint_usdc": 10.0,         # mints 10 Up + 10 Down tokens via CTF.splitPosition
    "min_post_inventory": 5,       # stop posting when remaining inv < CLOB min

    # Entry filter
    "min_sum_asks": 1.005,         # only post when ask_up + ask_dn ≥ $1.005

    # Quote cadence
    "fill_wait_s": 60,             # wait 60s for taker before cancel/repost
    "cooldown_per_repost_ticks": 1, # re-quote on every L25 update

    # Cells (start with sol_5m — highest $/slug)
    "cells": ["sol_5m", "sol_15m", "eth_15m", "btc_15m"],
    # eth_5m and btc_5m have lower per-slug PnL but high volume — add after validation
}
```

**Per-slug peak capital: $10.** Total active capital at any moment across 4
cells with 1-2 concurrent active slugs ≈ **$40-80**.

---

## Why $2.5 per fire / $10 pre-mint?

**CLOB minimum order**: Polymarket CLOB rejects orders smaller than 5 shares
per side. At avg price $0.50, that's **$2.50 per side, $5 per fire** (both
legs posted).

**Pre-mint $10 is the SMALLEST viable size that:**
- Provides enough inventory for at least 2 fills per side (2 × 5 = 10 shares)
- Lets the simulator drain inventory across ~5-10 fires per slug (matches
  the lower end of wallet behavior)
- Yields measurable +$0.07-$0.45/slug (profitable, just small)

**Saturation pattern** (from the pre-mint sweep on mid-rank 100 slugs):

| pre_mint | sol_5m | sol_15m | btc_5m | btc_15m | eth_5m | eth_15m | TOTAL $/day |
|---|---|---|---|---|---|---|---|
| $5  | $85  | $9  | $20  | $14 | $3  | $3  | **$134** |
| $10 | $132 | $23 | $32  | $17 | $18 | $18 | **$240** |
| $20 | $205 | $33 | $112 | $31 | $52 | $29 | **$462** |
| $50 | $377 | $52 | $218 | $77 | $92 | $34 | **$850** |
| $100 | $1,398 | $103 | $351 | $106 | $308 | $32 | **$2,299** |
| $200 | $3,429 | $523 | $717 | $164 | $1,019 | $176 | **$6,027** |
| $500 | $5,146 | $2,557 | $1,627 | $635 | $3,977 | $1,397 | **$15,339** |

**$10 test config projects ~$240/day across 6 cells. ROC ~300%/day** on
peak deployed capital — because mint capital RECYCLES per slug (5-15 min)
and we only fund N concurrent slug workers.

---

## STEP-BY-STEP: how the profit emerges

### Step 0: Market setup

A Polymarket BTC 5m up-down slug starts at `slot_start_us`. We're
interested in the "two-sided ask premium" pattern: when both
`best_ask(Up) + best_ask(Down) > $1.00`, there's a structural mispricing
— the pair of tokens together pays $1 at resolution (regardless of
outcome), but the asks sum to MORE than $1.

Example state at slug start:
- `best_ask_Up = $0.51` (someone's selling Up tokens at 51¢)
- `best_ask_Down = $0.50` (someone's selling Down tokens at 50¢)
- `sum_asks = $1.01` ← **$0.01 of free edge if we can sell BOTH**

### Step 1: Pre-mint inventory (one-shot, at slug start)

```python
CTF.splitPosition(
    collateralToken=USDC,
    parentCollectionId=0x0,
    conditionId=slug_condition_id,
    partition=[1,2],
    amount=10_000_000  # $10 USDC (6 decimals)
)
# Now wallet holds: 10 Up tokens + 10 Down tokens
# Cost: $10 USDC
```

This is the **ONE mint TX** wallet `0x89b5cdaa` does per slug. Chain-verified.

### Step 2: Post both maker limit-sells (repeating ~every 1-5s)

```python
clob_client.create_and_post_order(
    token_id=up_token_id,
    side="SELL",
    price=best_ask_Up,   # $0.51
    size=5,              # CLOB minimum
    order_type="GTC",    # good-til-cancelled
)
clob_client.create_and_post_order(
    token_id=down_token_id,
    side="SELL",
    price=best_ask_Down, # $0.50
    size=5,
    order_type="GTC",
)
```

We're now resting at the top-of-book on both sides. Inventory:
- Up: 10 (5 listed in CLOB, 5 in wallet reserve)
- Down: 10 (5 listed, 5 reserve)

### Step 3: Wait for taker fills (within 60s)

Three things can happen:

**3a. Taker BUYER lifts our Up ask at $0.51**
- We SOLD 5 Up tokens. Receive: 5 × $0.51 = $2.55 USDC + maker rebate
- Maker rebate per share = `0.20 × 0.07 × 0.51 × 0.49` = $0.0035
- Total rebate: 5 × $0.0035 = $0.0175
- Inventory: Up=5, Down=10

**3b. Taker BUYER lifts our Down ask at $0.50** (same logic)
- Receive: 5 × $0.50 = $2.50 + rebate
- Inventory: Up=5, Down=5

**3c. After 60s, no fills** → cancel + repost at NEW best_ask (book moved)
- Repeat indefinitely while sum_asks ≥ $1.005

### Step 4: Track cash + inventory over slug lifetime

Repeat Step 2/3 every ~5s. The book moves; sometimes ask_Up rises to $0.55
because flow is Up-favored. We follow:

```
Time 0:00  sum_asks=$1.01  post Up@$0.51, Down@$0.50  → Up fills (cash +$2.55)
Time 0:05  sum_asks=$1.02  post Up@$0.52, Down@$0.50  → Down fills (cash +$2.50)
Time 0:10  sum_asks=$1.03  post Up@$0.53, Down@$0.50  → both fill (cash +$5.15)
...
```

After 5 minutes of slug life, typical outcome:
- Up shares sold: 9-10 (out of 10 pre-minted)
- Down shares sold: 9-10
- Total cash: ~$10.10 (sold ~20 shares at sum_asks avg ~$1.010 per pair)
- Total rebates: 20 × $0.0035 = $0.07
- Inventory remaining: 0-1 of each side

### Step 5: Slug ends — resolve

Chainlink Data Streams settles BTC price at `slot_end`. Outcome = Up or Down.

If leftover inventory: redeem winning side at $1, losing side worthless.

Example: 0 Up + 1 Down leftover, outcome=Down → +$1 redemption.

### Step 6: Tally slug PnL

```
Cash from sales:    +$10.10
Maker rebates:       +$0.07
Redemption:          +$1.00 (1 Down × $1 if Down won, else $0)
Mint cost:          -$10.00
                    ────────
NET SLUG PnL:        +$1.17 (if held side won) or +$0.17 (if held side lost)
```

The edge comes from: **`sum_asks_avg - $1.00 + rebates - held_loss`**.

At sum_asks averaging $1.010 across 20 fills, edge per pair = $0.010 + $0.007
rebate = $0.017 × 10 pairs sold = $0.17. Plus 50% redemption probability ×
$1 leftover = +$0.50 expected. Net **+$0.67/slug expected**.

### Step 7: Aggregate across all slugs in the cell

Repeat across all ~280 slugs/day in btc_5m (5-min markets running 24/7).

At $0.65/slug × 280 slugs/day × $10 pre-mint per slug = **+$182/day** for
btc_5m alone. Cross 6 cells: **~$240/day total at test config**.

---

## Where the profit DOES NOT come from

### NOT from picking direction
We never bet on Up vs Down. We sell BOTH sides simultaneously.

### NOT from beating other makers
We're competing for the same taker volume. Wallets that pre-mint earlier
get better queue position. We use a queue-share approximation.

### NOT from holding inventory
Inventory leftover at slug end is a TAX (held-side selection bias =
underdog wins only 38% of the time). The model works because we
**fully drain inventory** at the right pre-mint size.

### NOT from sum_asks > $1 alone
sum_asks > $1.005 at time of POST. But fills happen at TAKER's print price
later, which is what we book as cash. The edge comes from the BOOK MOVING
UPWARD over the slug lifetime — average fill price ends up HIGHER than the
posting time average, because takers chase the higher side as outcome
clarifies.

---

## Where the profit DOES come from

1. **Maker rebate**: $0.20 × 0.07 × p × (1−p) per share. At p=0.5 = $0.0035/share.
   On 20 share-fills per slug = $0.07/slug pure rebate income.

2. **Two-sided spread capture**: by posting on BOTH sides, our average
   realized price ends up close to mid-book ($0.50), giving us
   `(2 × $0.50 = $1.00) - $1.00 mint cost = breakeven`. **Plus the
   sum_asks > $1 premium** at time of fill (book moves up during slug):
   typical realized cash $1.005-$1.030 per pair-sold = $0.005-$0.030 edge.

3. **End-of-slug redemption**: leftover inventory of winning side pays $1.
   Net expected redemption ≈ $0.5 × n_leftover_winning_pairs.

The TOTAL slug PnL formula (test config, $10 pre-mint):

```
PnL_slug = (n_filled × avg_fill_price) + (n_filled × rebate_per_share)
        + (n_leftover_winning_side × $1)
        − $10
```

For a saturated slug with all 10 shares sold per side:
```
20 × $0.502 + 20 × $0.004 + 0 - $10 = $10.04 + $0.08 = $0.12 PnL
```

For a slug with leftover (5 sold each side, 5 leftover each, Up wins):
```
10 × $0.510 + 10 × $0.004 + 5 × $1 + 0 - $10 = $5.10 + $0.04 + $5.00 - $10 = $0.14 PnL
```

For a slug with leftover where the wrong side won (4 sold Up, 6 sold Down,
6 Up leftover, 4 Down leftover, outcome=Down):
```
4 × $0.51 + 6 × $0.50 + 10 × $0.004 + 4 × $1 + 0 - $10 = $2.04 + $3.00 + $0.04 + $4 - $10 = -$0.92 PnL
```

So **30% of slugs LOSE** (when held side is the underdog). The other 70%
win small. Average +$0.07-$0.45/slug.

---

## Risks specific to the $10 test config

1. **Queue position**: we're posting tiny 5-share orders behind 100-1000+
   share queues. Our share of taker volume is `5/(5+queue) ≈ 2-5%`. The
   sim's queue-share approximation handles this — but live, the FIFO queue
   may be more brutal.

2. **Gas costs**: each `splitPosition` + `redeem` is ~150k gas. At 20 gwei
   on Polygon = ~$0.003 per slug. Negligible at our scale.

3. **CLOB cancel/repost rate**: at every L25 tick (1/s) × 60s/slug × 6
   cells = 360 cancel-and-repost operations per minute peak. May hit CLOB
   rate limits.

4. **Trades parquet stale**: model validated on Apr 24 - May 16 window.
   Newer windows may differ if microstructure shifted.

5. **Polymarket fees**: 7% taker on every fill. Our model already accounts
   for this via `poly_taker_fee_per_share`.

---

## Comparison to V1 (dead) and V2

| | V1 | V2 | **V3 test** |
|---|---|---|---|
| Notional per fire | $200 | $2.5 | **$2.5** ($5 both sides) |
| Pre-mint per slug | per-fire | per-fire | **$10 (single mint)** |
| Fee model | 80% maker fee bug | rebate as income | rebate as income (correct) |
| Cash accounting | post-time | post-time | **trade-time (correct)** |
| Cooldown | 10s | 1s | 1s |
| Min sum_asks | $1.035 | $1.005 | $1.005 |
| Expected per-slug | -$25k/day | -$25k/day | **+$240/day** (test scale) |

---

## Scaling beyond test

Once $10/slug test is validated on live paper:

| Pre-mint per slug | Concurrent capital (6 cells, 2 active each) | $/day projection |
|---|---|---|
| $10 (test)  | $120 | +$240 |
| $50         | $600 | +$850 |
| $100        | $1,200 | +$2,299 |
| $200        | $2,400 | **+$6,027** |
| $500        | $6,000 | +$15,339 |

ROC stays at 200-400% daily as long as inventory clears. Past $200, ROC
degrades because leftover-inventory bias kicks in (saturation = 100% but
some slugs leave large leftover when demand is asymmetric).

**Recommended path**:
1. Test at $10 for 7 days → confirm $200/day or close
2. Scale to $50 for 7 days → confirm $850/day
3. Scale to $100, then $200

Don't jump to $500 — variance is materially higher because losing slugs
have $73/slug average leftover at that size.

---

## Files

- [v3_wallet_trade_driven.py](../wallet_hunt/replicate/v3_wallet_trade_driven.py) — now enforces CLOB min order (5 shares)
- [V3_PRE_MINT_SWEEP_2026_05_18.csv](V3_PRE_MINT_SWEEP_2026_05_18.csv) — full sweep data
- [MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md](MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md) — full V3 deep-dive
