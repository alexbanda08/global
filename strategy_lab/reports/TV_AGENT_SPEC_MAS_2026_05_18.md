# TV Agent Implementation Spec — MAS (Mint-And-Sell maker)

**Date**: 2026-05-18
**Strategy code**: `MAS`
**Source**: V3 backtest (no wallet decodes this — we are the MIRROR side of the ACC strategies)
**Deploy stage**: Shadow first → Live after 48h validation

---

## 1. Strategy summary

Mint Up+Down pairs upfront via `CTF.splitPosition`. Post limit ASKS on both Up and Down sides at `best_ask`. Wait for taker BUYS to lift our asks. Collect cash + maker rebate per fill. At slug end, redeem any leftover.

This is the OPPOSITE side of ACC-M/H. When a wallet like 0x04b6d7e9 posts a BID at $0.40 and a taker SELLS into it, the TAKER might be us-as-MAS having posted an ASK at $0.40 and being lifted (wait, no — the taker sells, hits the bid). Actually MAS posts ASKS at $0.60 and waits for ACC-style taker BUYS that lift our ask.

So: **MAS sells to taker BUYERS. ACC buys from taker SELLERS. We can run BOTH in parallel without conflict.**

**Expected edge**: 0.5-2% per pair sold + maker rebate.
**Test deploy projection**: ~$30-150/day at $30 pre-mint × 6 cells.

---

## 2. State machine

```
EVENTS                            STATE                  ACTIONS
──────────────────────────────────────────────────────────────────────
SlugStart(slug)                   INIT                  → If cell enabled:
                                                            MintPairs(PRE_MINT_USDC)
                                                            inv_up=N, inv_dn=N
                                                            mint_cost=PRE_MINT_USDC

L25Update(slug, books)            SELLING               → If filters pass:
                                                            Cancel old asks
                                                            Post Ask Up + Ask Dn
                                                          → Check inventory: if low, repost
                                                            stops

OrderFill(slug, side, sz, px)     SELLING               → inv -= sz
                                                          → cash_received += sz * px
                                                          → rebates += sz * rebate(px)

SlugEndApproaching                CLOSING               → Cancel all open asks
(slot_start + 270s)

SlugResolved(slug, outcome)       SETTLEMENT            → Redeem inv (winning side at $1)
                                                          → Compute slug PnL
                                                          → Reset SlugState
```

---

## 3. Decision rules

### 3.1 On `SlugStart`:

```python
def on_slug_start(slug, asset, tf, slot_start_us, condition_id, state):
    if not cell_enabled(asset, tf):
        return []
    if wallet.balance_usdc < PRE_MINT_USDC:
        return []  # insufficient capital
    
    # Mint pairs upfront
    return [MintPairs(
        slug=slug,
        condition_id=condition_id,
        amount_usdc=PRE_MINT_USDC,
    )]
    # On mint completion: state.inv_up = PRE_MINT_USDC, inv_dn = PRE_MINT_USDC,
    # state.mint_cost = PRE_MINT_USDC
```

### 3.2 On `L25Update`:

```python
def on_l25_update(slug, books, state):
    elapsed_s = (now_us - state.slot_start_us) / 1_000_000
    if elapsed_s > stop_post_offset_s(asset_tf):
        return []  # too late to post
    
    # Entry filter: only post when there's edge
    sum_asks = books.up.best_ask + books.dn.best_ask
    if sum_asks < MIN_SUM_ASKS:
        return []
    
    # Spread filter
    if books.up.spread > MAX_SPREAD_PER_LEG or books.dn.spread > MAX_SPREAD_PER_LEG:
        return []
    
    # Inventory check
    can_post_up = state.inv_up >= MIN_POST_INVENTORY
    can_post_dn = state.inv_dn >= MIN_POST_INVENTORY
    if not (can_post_up or can_post_dn):
        return []
    
    actions = []
    
    # Cancel + repost if book moved
    if state.open_ask_up and abs(state.open_ask_up.price - books.up.best_ask) > 0.01:
        actions.append(Cancel(state.open_ask_up.order_id))
    if state.open_ask_dn and abs(state.open_ask_dn.price - books.dn.best_ask) > 0.01:
        actions.append(Cancel(state.open_ask_dn.order_id))
    
    if can_post_up and not state.open_ask_up:
        actions.append(PostAsk(
            slug=slug, side="Up",
            price=books.up.best_ask,
            size=min(POST_SIZE, state.inv_up),
            order_type="GTC_POST_ONLY",
        ))
    if can_post_dn and not state.open_ask_dn:
        actions.append(PostAsk(
            slug=slug, side="Down",
            price=books.dn.best_ask,
            size=min(POST_SIZE, state.inv_dn),
            order_type="GTC_POST_ONLY",
        ))
    
    return actions
```

### 3.3 On `OrderFill` (taker lifted our ask):

```python
def on_order_fill(slug, side, fill_size, fill_price, state):
    if side == "Up":
        state.inv_up -= fill_size
    else:
        state.inv_dn -= fill_size
    state.cash_received += fill_size * fill_price
    state.rebates += fill_size * maker_rebate(fill_price)
    state.fill_count += 1
    
    # Note: NO merging — MAS doesn't merge mid-slug (we held the pre-minted pair
    # to sell BOTH sides; if both sold, we sold the pair for sum_asks > $1)
    # Held-side bias risk: if only one fills, we hold the loser
    
    return []
```

### 3.4 On `SlugResolved`:

```python
def on_slug_resolved(slug, outcome, state):
    leftover_up = state.inv_up
    leftover_dn = state.inv_dn
    
    redeem = 0
    if outcome == "Up":
        redeem = leftover_up * 1.00
    else:
        redeem = leftover_dn * 1.00
    state.cash_received += redeem
    
    actions = [RedeemPositions(slug=slug, condition_id=...)]
    
    slug_pnl = state.cash_received + state.rebates - state.mint_cost
    log_slug_pnl(slug, state, slug_pnl)
    
    return actions
```

---

## 4. Configuration parameters

```python
MAS_CONFIG = {
    "strategy_code": "MAS",
    "version": "1.0.0",
    
    # Cells (all 6 — small edge per cell adds up)
    "cells": ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"],
    
    # Per-slug capital
    "PRE_MINT_USDC": 30,           # test scale
    
    # Posting
    "POST_SIZE": 5,                # CLOB min
    "MIN_SUM_ASKS": 1.005,         # only post when edge exists
    "MAX_SPREAD_PER_LEG": 0.05,
    "REPOST_THRESHOLD_CENTS": 1,
    
    # Inventory
    "MIN_POST_INVENTORY": 5,
    
    # Timing
    "STOP_POST_OFFSET_S_5M": 270,
    "STOP_POST_OFFSET_S_15M": 870,
    
    # Risk
    "MAX_DAILY_DRAWDOWN_USDC": 30,
    "MAX_CONCURRENT_SLUGS": 6,     # 1 per cell
    
    "shadow_only": True,
    "log_path": "shadow_mas_<date>.csv",
}
```

---

## 5. Per-slug fire-count expectations (V3 backtest)

| Event | Expected count |
|---|---|
| Mint (1× per slug) | 1 |
| L25 updates | ~300 |
| Ask posts | 50-150 |
| **Ask fills** | **5-15** at $30 pre-mint |
| Redeem (1× per slug) | 1 |

---

## 6. Risk: held-side selection bias

If only ONE leg fills (other doesn't), we're stuck holding the leftover side at slug end:
- Winning side: redeem at $1, profit
- Losing side: $0, loss

Per V3 backtest, held-side win rate is ~38% (selection bias). At small pre-mint ($30):
- Worst case leftover: $30 × ($1 - sell_price) = ~$15 loss if held side loses
- Best case: $30 × ($1 - sell_price) = ~$15 gain if held side wins
- Expected: -$0.275/share held × ~15 shares held = -$4 expected drag per slug with leftover

Mitigation: keep `PRE_MINT_USDC` small. At $30, max naked exposure is bounded.

---

## 7. Shadow logging (similar to ACC-M)

CSV columns:
```
ts_us, slug, action, side, price, size, sim_inv_up, sim_inv_dn, sim_cash_received,
sim_rebates, sim_mint_cost, sim_pnl_so_far, sim_held_side_lottery
```

---

## 8. Promotion criteria

After 48h shadow:
- Mean realized $/slug > **$0.10** (positive expectancy, lower bar than ACC due to smaller edge)
- Median realized $/slug > **$0.00**
- Drawdown < $30 in 24h

If pass → live at $30 pre-mint × all 6 cells.

---

## 9. Implementation checklist (for TV agent)

- [ ] Implement `MintPairs` via `CTF.splitPosition`
- [ ] Subscribe to L25 + trade WS for all 6 cells
- [ ] State machine (§2)
- [ ] Decision rules (§3) with all filters
- [ ] Track `inv_up`, `inv_dn` per slug
- [ ] Implement post-ask + cancel logic
- [ ] Redemption call after slug resolution
- [ ] Shadow logging
- [ ] PnL tracking
- [ ] Kill switch
- [ ] Unit tests for each decision rule
- [ ] Integration test: replay 1 historical slug, verify PnL matches V3 simulator

---

## 10. Why run MAS alongside ACC

MAS and ACC are MIRROR strategies:
- MAS posts ASKS at $0.60
- ACC posts BIDS at $0.40

They don't compete for the same fills. They complement.

By running BOTH:
- MAS captures the `sum_asks > $1` mispricing edge
- ACC captures the `sum_bids < $1` mispricing edge
- Together: capture both sides of the spread

Risk: shared capital pool. Manage with config:
```python
SHADOW_CONFIG = {
    "wallet_total_usdc": 200,
    "allocations": {
        "MAS": 100,   # $100 across 6 cells = ~$17/cell pre-mint
        "ACC-M": 50,  # $50 for BTC bid posting
        "ACC-H": 50,  # $50 for BTC+ETH bid+taker
    },
}
```

---

## 11. Reference files

- Backtest: `strategy_lab/wallet_hunt/replicate/v3_wallet_trade_driven.py`
- Strategy catalog: `strategy_lab/reports/STRATEGY_FINAL_2026_05_18.md`
- This spec: `strategy_lab/reports/TV_AGENT_SPEC_MAS_2026_05_18.md`
