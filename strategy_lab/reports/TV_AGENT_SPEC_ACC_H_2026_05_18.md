# TV Agent Implementation Spec — ACC-H (Hybrid Maker+Taker Accumulator)

**Date**: 2026-05-18
**Strategy code**: `ACC-H`
**Source wallet**: `0xeebde7a0` ($344k/day, 50% maker + 50% taker)
**Deploy stage**: ⚠️ **NOT RECOMMENDED for first deploy** — see warning below

---

## ⚠️ CRITICAL WARNING — Read before implementing

Chain analysis of 0xeebde7a0 shows their **median per-slug imbalance is 50%** (paired% = 50%). This means **half their PnL comes from DIRECTIONAL betting** with the leftover unpaired inventory — they HAVE alpha on which side will win.

**We do NOT have that directional alpha.**

If we deploy ACC-H without a directional signal, we're effectively flipping coins on 50% of our PnL. The expected value of pure directional betting on a fair coin is $0 minus fees.

**Use ACC-H only if combined with a directional signal** (e.g., binance momentum, chainlink lead-lag, our existing momo signal). Without that, **deploy ACC-M (pure pair arb, 92% paired) instead**.

Source: `strategy_lab/reports/STRATEGY_CATALOG_2026_05_18.md` §Imbalance analysis.

---

## 1. Strategy summary

Identical to ACC-M (post BIDs + accumulate + merge) PLUS opportunistic TAKER BUYS when conditions favor it. When one side's ask drops below fair value OR our inventory becomes imbalanced, we market-BUY the lagging/cheap side to rebalance AND capture deep discount.

This is the **$344k/day pattern**. Adds ~2× the volume of pure ACC-M plus deeper edge per pair.

**Expected edge**: 1-3% per pair-rotation (higher than ACC-M because of cheap taker buys).
**Test deploy projection**: ~$50-150/day at $50 USDC.e seed.

---

## 2. State machine (extends ACC-M with TAKER mode)

```
EVENTS                            STATE                  ACTIONS
──────────────────────────────────────────────────────────────────────
(All ACC-M events same...)

L25Update(slug, books)            ACCUMULATING          → ACC-M actions
                                                          + Check TAKER trigger
                                                          + If trigger met:
                                                              MarketBuy(cheap side)

TradePrint(slug, side, px, sz)    ACCUMULATING          → Update recent_price_history
                                                          → Detect ASK COLLAPSE
                                                            (e.g., ask drops > 5¢)
                                                          → If detected:
                                                              MarketBuy(that side)

InventoryImbalanceDetected        REBALANCING           → MarketBuy(lighter side)
                                                            to restore balance
```

---

## 3. Decision rules (in addition to ACC-M)

### 3.1 Taker BUY trigger — Reason 1: Inventory pacing

```python
def check_taker_pacing(slug, state):
    """If passive bids aren't filling fast enough, take to maintain pace.
    Mimics 0xeebde7a0 inventory pacing controller (decoded by Agent 1)."""
    elapsed_frac = (now_us - state.slot_start_us) / state.slug_duration_us
    
    # Target inventory build = elapsed_frac * MAX_INVENTORY
    target_inv = elapsed_frac * TARGET_INVENTORY_PER_SLUG
    current_inv = (state.inv_up + state.inv_dn) / 2.0  # average sides
    
    deficit = target_inv - current_inv
    if deficit < PACING_DEFICIT_THRESHOLD:
        return None  # on pace
    
    # We're behind pace — take a buy
    # Pick the side with lower inventory (rebalance)
    if state.inv_up < state.inv_dn:
        target_side = "Up"
    else:
        target_side = "Down"
    
    return TakerBuy(side=target_side, max_size=TAKER_SIZE, reason="pacing")
```

### 3.2 Taker BUY trigger — Reason 2: Ask collapse

```python
def check_ask_collapse(slug, side, current_ask, recent_asks_60s):
    """Detect sharp ask drop — opportunity to buy cheap."""
    if len(recent_asks_60s) < 10:
        return False
    median_60s = np.median(recent_asks_60s)
    drop_amount = median_60s - current_ask
    if drop_amount > ASK_COLLAPSE_THRESHOLD:  # e.g., 5¢
        return True
    return False
```

### 3.3 Taker BUY trigger — Reason 3: Inventory imbalance

```python
def check_imbalance_take(state, current_books):
    """If we have lots of one side and not the other, market-buy lighter side
    to balance (otherwise we'd be 'naked' at slug end)."""
    imbalance = abs(state.inv_up - state.inv_dn)
    if imbalance < IMBALANCE_THRESHOLD:
        return None
    
    # Buy the LIGHTER side
    if state.inv_up < state.inv_dn:
        side = "Up"
        target_ask = current_books.up.best_ask
    else:
        side = "Down"
        target_ask = current_books.dn.best_ask
    
    # Don't take at silly prices
    if target_ask > TAKER_MAX_PRICE:
        return None
    
    # Size: just enough to rebalance
    size_to_buy = min(imbalance, TAKER_MAX_SIZE)
    return TakerBuy(side=side, price=target_ask, size=size_to_buy, reason="rebalance")
```

### 3.4 Unified taker decision (combine all 3 triggers)

```python
def on_l25_update_for_taker(slug, books, state):
    """Returns at most ONE TakerBuy action per L25 update."""
    # Check rebalance first (most urgent)
    rebal = check_imbalance_take(state, books)
    if rebal: return [rebal]
    
    # Check ask collapse on either side
    if check_ask_collapse(slug, "Up", books.up.best_ask, state.recent_asks_up_60s):
        if state.inv_up < ABSOLUTE_MAX_INVENTORY:
            return [TakerBuy(side="Up", price=books.up.best_ask, size=TAKER_SIZE, reason="collapse")]
    if check_ask_collapse(slug, "Down", books.dn.best_ask, state.recent_asks_dn_60s):
        if state.inv_dn < ABSOLUTE_MAX_INVENTORY:
            return [TakerBuy(side="Down", price=books.dn.best_ask, size=TAKER_SIZE, reason="collapse")]
    
    # Check pacing
    pace = check_taker_pacing(slug, state)
    if pace: return [pace]
    
    return []
```

### 3.5 On `TakerBuy` action executed:

```python
def on_taker_fill(slug, side, fill_size, fill_price, state):
    taker_fee = fill_size * taker_fee_per_share(fill_price)
    if side == "Up":
        state.inv_up += fill_size
    else:
        state.inv_dn += fill_size
    state.cash_spent += fill_size * fill_price + taker_fee  # taker pays fee
    state.taker_fill_count += 1
    # Check if can merge
    if min(state.inv_up, state.inv_dn) >= MERGE_THRESHOLD_PAIRS:
        return [TriggerMerge(slug)]
    return []
```

---

## 4. Configuration parameters (overrides ACC-M)

```python
ACC_H_CONFIG = {
    **ACC_M_CONFIG,  # Inherit all ACC-M defaults
    
    "strategy_code": "ACC-H",
    
    # Hybrid taker controls
    "TAKER_SIZE": 5,                       # Match CLOB min; conservative
    "TAKER_MAX_SIZE": 25,                  # Cap per single taker buy
    "TAKER_MAX_PRICE": 0.95,               # Don't take near $1
    "ASK_COLLAPSE_THRESHOLD": 0.05,        # 5¢ drop = collapse trigger
    "ASK_COLLAPSE_WINDOW_S": 60,           # Look at last 60s
    "TARGET_INVENTORY_PER_SLUG": 30,       # Goal at slug end (in paired pairs)
    "PACING_DEFICIT_THRESHOLD": 5,         # If 5+ pairs behind pace, take
    "IMBALANCE_THRESHOLD": 10,             # Rebalance if imbalance > 10 shares
    
    # Anti-overfire (don't market-buy too often)
    "MIN_S_BETWEEN_TAKER_BUYS": 5,         # At most 1 taker buy per 5s
    "MAX_TAKER_BUYS_PER_SLUG": 50,         # Cap total takes per slug
    
    # Cells (mimic 0xeebde7a0 — BTC + ETH)
    "cells": ["btc_5m", "btc_15m", "eth_5m", "eth_15m"],
}
```

---

## 5. Per-slug fire-count expectations

Based on 0xeebde7a0 decode:

| Event | Expected count | Range |
|---|---|---|
| L25 updates received | ~300 | 200-500 |
| Bid posts | 100-300 | varies |
| **Bid fills** | **5-15** (test) | wallet: 235 at full scale |
| **Taker BUYs** | **5-25** (test) | wallet: 448 at full scale (hybrid!) |
| Merges | 2-5 (test) | wallet: ~10 at full scale |

**Critical**: 0xeebde7a0 does ~2× more taker buys than maker fills. Hybrid mode is the volume king.

---

## 6. Risk: avoiding naked positions

Three layers of protection:

1. **Posting filter**: don't post on the heavy side if `|inv_up - inv_dn| > MAX_IMBALANCE_SHARES`
2. **Rebalance taker**: if imbalance grows despite filter, market-buy lighter side
3. **Slug-end leftover cap**: hard limit `ABSOLUTE_MAX_INVENTORY` so worst-case leftover is bounded

Worst-case naked exposure at slug end:
```
worst_case = ABSOLUTE_MAX_INVENTORY × $1 (if held side loses)
           = 100 × $1 = $100 exposure per slug
```

Mitigation: at $50 seed, even worst-case leftover is < $100 (we can't accumulate beyond what wallet supports).

---

## 7. Shadow mode logging (extends ACC-M)

In addition to ACC-M shadow CSV, log:

```
ts_us, slug, action, side, price, size, taker_or_maker, reason,
inv_up, inv_dn, imbalance, recent_ask_drop, pacing_deficit
```

Specifically for taker decisions, log the trigger reason so we can analyze
post-shadow:
- `reason="collapse"` (ask collapse)
- `reason="rebalance"` (inventory rebalance)
- `reason="pacing"` (behind pace)
- `reason="opportunistic"` (cheap fill available)

---

## 8. Promotion criteria (more stringent than ACC-M)

After 48h shadow, promote to live IF:
- Mean realized $/slug > **$0.50** (positive expectancy with margin)
- Median realized $/slug > **$0.20**
- Realized fill rate > 30% of simulated (queue position is real)
- Drawdown < $30 in any 24h window
- Taker buys actually capture average price BELOW best_bid_at_post_time (verify edge)

If all pass: enable live at $50 seed, BTC 5m only.

---

## 9. Implementation checklist (for TV agent)

In addition to ACC-M checklist:

- [ ] Implement recent-ask price history tracker per (slug, side) — rolling 60s window
- [ ] Implement 3 taker triggers (collapse, rebalance, pacing)
- [ ] Anti-overfire rate limiter (MIN_S_BETWEEN_TAKER_BUYS)
- [ ] Slug-level taker count cap (MAX_TAKER_BUYS_PER_SLUG)
- [ ] Inventory balance enforcement on BOTH post AND take decisions
- [ ] Log taker reason for post-shadow analysis
- [ ] Unit test each taker trigger independently
- [ ] Integration test: replay slug where 0xeebde7a0 was active, verify our taker decisions match in timing/direction

---

## 10. Differences from ACC-M (for code review)

| | ACC-M | ACC-H |
|---|---|---|
| Maker BIDs | ✅ | ✅ |
| Maker rebate income | ✅ | ✅ |
| Market BUYs | ❌ | **✅** |
| Inventory rebalance via taker | ❌ | **✅** |
| Taker fee paid | $0 | **paid on taker buys** |
| Expected daily PnL | $25-50 | **$50-150 (test)** |
| Volume/day | 1× | **2-3×** |
| Code complexity | Simple | Medium |
| Risk profile | Low (pure maker) | Medium (taker fees, larger volume) |

---

## 11. Same reference files / contracts as ACC-M

See ACC-M spec for:
- Reference files
- Contract addresses
- Shadow mode requirements
- Failure handling

---

## 12. Why ACC-H makes 6-10x more than ACC-M

| Mechanism | ACC-M | ACC-H |
|---|---|---|
| Maker rebate per pair | +$0.007 | +$0.007 (same) |
| Spread captured | sum_bids<$1 ≈ $0.01 | $0.01 (same) |
| Taker discounts captured | $0 | +$0.10-$0.15 (when ask drops) |
| Inventory rebalancing | passive only | active (don't get naked) |
| **Total edge per pair** | $0.02-$0.04 | $0.12-$0.20 |
| Per-slug PnL (at scale) | small consistent | larger variable |

The hybrid model captures the "deep discount" moments that pure makers miss.
