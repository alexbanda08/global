# TV Agent Implementation Spec — ACC-M (Maker-only Accumulator)

**Date**: 2026-05-18
**Strategy code**: `ACC-M`
**Source wallet**: `0x04b6d7e9` ($212k/day, 94.6% pure maker-bid)
**Deploy stage**: Shadow first → Live after 48h validation

---

## 1. Strategy summary

Post limit BIDS on both Up and Down sides at `best_bid`. When taker SELLs hit our bids, we accumulate paired Up+Down inventory at prices < $1 per pair. Periodically merge paired inventory via NegRiskAdapter to recover USDC.e. Recycle indefinitely through slug. **Never post asks. Never market-sell.**

**Expected edge**: 0.5-1.6% per pair-rotation (verified by wallet decode).
**Test deploy projection**: ~$25-50/day at $50 USDC.e seed.

---

## 2. State machine

```
EVENTS                            STATE                  ACTIONS
──────────────────────────────────────────────────────────────────────
SlugStart(slug, slot_start_us)    INIT                  → Initialize SlugState
                                                          (inv_up=0, inv_dn=0,
                                                           cash_spent=0, ...)

L25Update(slug, books)            ACCUMULATING          → If filters pass:
                                                          • Cancel old bids
                                                          • Post Bid Up + Bid Dn
                                                          • Check inventory balance

OrderFill(slug, side, sz, px)     ACCUMULATING          → Update inv += sz
                                                          → cash_spent += sz*px
                                                          → rebates += sz*rebate(px)
                                                          → Check merge trigger

MergeTrigger                      MERGING               → Send min(inv_up, inv_dn)
                                                            pairs to NegRiskAdapter
                                                          → cash_recovered += pairs*$1
                                                          → inv_up,dn -= pairs

SlugEndApproaching                CLOSING               → Cancel all open orders
(slot_start + 270s)                                       (stop posting)

SlugResolved(slug, outcome)       SETTLEMENT            → Force final merge
                                                          → Redeem leftover single-side
                                                          → Log slug PnL
                                                          → Reset SlugState
```

---

## 3. Decision rules (in priority order)

### 3.1 On every `L25Update`:

```python
def on_l25_update(slug, books, state):
    # Filter 1: Don't post in last 30s before slug close
    elapsed_s = (now_us - state.slot_start_us) / 1_000_000
    if elapsed_s > 270:  # for 5m slugs (300s); 870 for 15m (900s)
        return []  # NO POST
    
    # Filter 2: Skip wide-book conditions
    if books.up.spread > 0.05 or books.dn.spread > 0.05:
        return []  # too risky
    
    # Filter 3: Edge filter — only post when sum_bids < $1
    sum_bids = books.up.best_bid + books.dn.best_bid
    if sum_bids >= 1.00:
        return []  # no edge to capture
    
    # Filter 4: Price band
    if not (0.05 <= books.up.best_bid <= 0.95): return []
    if not (0.05 <= books.dn.best_bid <= 0.95): return []
    
    # Filter 5: INVENTORY BALANCE (critical — prevents "naked" position)
    imbalance = abs(state.inv_up - state.inv_dn)
    post_up = state.inv_up <= state.inv_dn + MAX_IMBALANCE_SHARES
    post_dn = state.inv_dn <= state.inv_up + MAX_IMBALANCE_SHARES
    
    # Filter 6: Wallet balance check
    if wallet.balance_usdc < POST_SIZE * (books.up.best_bid + books.dn.best_bid):
        # Insufficient pUSD to back both bids — only post one side
        if state.inv_up > state.inv_dn: post_up = False  # we need Dn more
        elif state.inv_dn > state.inv_up: post_dn = False
        else: return []  # can't afford either
    
    actions = []
    
    # Cancel old bids if book moved
    if state.open_bid_up and abs(state.open_bid_up.price - books.up.best_bid) > 0.01:
        actions.append(Cancel(state.open_bid_up.order_id))
    if state.open_bid_dn and abs(state.open_bid_dn.price - books.dn.best_bid) > 0.01:
        actions.append(Cancel(state.open_bid_dn.order_id))
    
    # Post new bids
    if post_up and (not state.open_bid_up or state.open_bid_up_cancelled):
        actions.append(PostBid(
            slug=slug, side="Up",
            price=books.up.best_bid,
            size=POST_SIZE,
            order_type="GTC_POST_ONLY",  # no taking; pure maker
        ))
    if post_dn and (not state.open_bid_dn or state.open_bid_dn_cancelled):
        actions.append(PostBid(
            slug=slug, side="Down",
            price=books.dn.best_bid,
            size=POST_SIZE,
            order_type="GTC_POST_ONLY",
        ))
    
    return actions
```

### 3.2 On every `OrderFill` (our bid was hit):

```python
def on_order_fill(slug, side, fill_size, fill_price, state):
    # Update inventory and cash tracking
    if side == "Up":
        state.inv_up += fill_size
    else:
        state.inv_dn += fill_size
    state.cash_spent += fill_size * fill_price
    state.rebates += fill_size * maker_rebate(fill_price)
    state.fill_count += 1
    
    # Check merge trigger
    pairs_now = min(state.inv_up, state.inv_dn)
    if pairs_now >= MERGE_THRESHOLD_PAIRS:
        return [TriggerMerge(slug)]
    
    return []
```

### 3.3 On `MergeTrigger`:

```python
def on_merge_trigger(slug, state):
    pairs = int(min(state.inv_up, state.inv_dn))
    if pairs < MERGE_THRESHOLD_PAIRS:
        return []
    
    # Call NegRiskAdapter — transfer paired Up+Down tokens
    # to 0xf3cfb6a6 — it auto-merges and returns USDC.e in same tx
    actions = [MergePositions(
        slug=slug,
        pairs=pairs,
        method="negrisk_adapter",  # or "ctf_direct" (more gas)
    )]
    
    state.inv_up -= pairs
    state.inv_dn -= pairs
    state.cash_recovered += pairs * 1.00
    state.merge_count += 1
    
    return actions
```

### 3.4 On `SlugResolved`:

```python
def on_slug_resolved(slug, outcome, state):
    # Force one last merge for any remaining pairs
    pairs = int(min(state.inv_up, state.inv_dn))
    if pairs > 0:
        # ... do merge ...
        state.inv_up -= pairs
        state.inv_dn -= pairs
        state.cash_recovered += pairs
    
    # Redeem leftover single-side
    leftover_up = state.inv_up
    leftover_dn = state.inv_dn
    redeem = 0
    if outcome == "Up" and leftover_up > 0:
        redeem = leftover_up * 1.00
    elif outcome == "Down" and leftover_dn > 0:
        redeem = leftover_dn * 1.00
    state.cash_recovered += redeem
    
    actions = [RedeemPositions(slug=slug, condition_id=...)]
    
    # Compute and log slug PnL
    slug_pnl = state.cash_recovered + state.rebates - state.cash_spent
    log_slug_pnl(slug, state, slug_pnl)
    
    return actions
```

---

## 4. Configuration parameters

```python
ACC_M_CONFIG = {
    # === Strategy identifier ===
    "strategy_code": "ACC-M",
    "version": "1.0.0",
    
    # === Cell selection ===
    "cells": ["btc_5m", "btc_15m"],  # Start BTC-only like 0x04b6d7e9
    # Later: extend to ["eth_5m", "eth_15m", "sol_5m", "sol_15m"]
    
    # === Capital ===
    "wallet_seed_usdc": 50,        # Test: $50; production: scale up
    "max_committed_per_slug": 50,  # Cap to prevent over-commitment
    
    # === Posting ===
    "POST_SIZE": 5,                # CLOB minimum, in shares
    "MIN_BID_PRICE": 0.05,         # Skip extreme outcomes
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,          # Only post when edge exists
    "MAX_SPREAD_PER_LEG": 0.05,    # Skip illiquid books

    # === Cancel rules (DECODED FROM CHAIN, HYBRID-PERSISTENT) ===
    # Source: 0x04b6d7e9 (90% orders fill without cancel) + 0xb27bc932 (5× scale)
    # Cancels are OFF-CHAIN (Polymarket API only, no on-chain event).
    # Whichever rule fires first → cancel.
    "CANCEL_THRESHOLD_CENTS": 3.0, # cancel if best_bid moves ≥ 3¢ from our price
    "MAX_ORDER_AGE_S": 20.0,       # cancel if order older than 20s
    "CANCEL_ON_FILL": False,       # KEEP residuals on book after partial fills (DO NOT cancel)
    "CANCEL_ON_CLOSE": False,      # No special end-of-slug cancel (let orders fill or expire naturally)
    "REPOST_ON_CANCEL": True,      # After cancel, immediately post at new best_bid
    
    # === Inventory balance (CRITICAL — prevents naked position) ===
    # Calibrated from 0x04b6d7e9 chain decode: they maintain 92% paired,
    # median imbalance only 8%. Mimic this discipline tightly.
    "MAX_IMBALANCE_SHARES": 5,     # If |inv_up - inv_dn| > 5 shares, stop posting heavy side
    "MAX_IMBALANCE_PCT": 0.10,     # OR hard cap at 10% of total inventory
    "ABSOLUTE_MAX_INVENTORY": 50,  # Hard cap on either side (small for safety)
    
    # === Merging ===
    "MERGE_THRESHOLD_PAIRS": 5,    # Merge when paired >= 5
    "MERGE_METHOD": "negrisk_adapter",  # or "ctf_direct"
    "MERGE_GAS_PRICE_GWEI": 30,    # Polygon gas price ceiling
    
    # === Timing ===
    "STOP_POST_OFFSET_S_5M": 270,  # Stop posting 30s before 5m slug close
    "STOP_POST_OFFSET_S_15M": 870, # Stop posting 30s before 15m slug close
    
    # === Risk controls ===
    "MAX_DAILY_DRAWDOWN_USDC": 25, # Halt strategy if daily loss exceeds this
    "MAX_CONSECUTIVE_LOSING_SLUGS": 10,  # Halt if 10 losing slugs in a row
    "MAX_CONCURRENT_SLUGS": 4,     # Total active slugs across cells
    
    # === Shadow vs Live ===
    "shadow_only": True,           # Set False for live; logs decisions only
    "log_path": "shadow_acc_m_<date>.csv",
}
```

---

## 5. Per-slug fire-count expectations

Based on the wallet 0x04b6d7e9 decode, expect per slug:

| Event | Expected count | Range |
|---|---|---|
| L25 updates received | ~300 (1/sec for 300s) | 200-500 |
| Bid posts (both sides, after dedup/cancel) | 100-200 | varies with book volatility |
| Cancels (book moved) | 50-150 | varies |
| Bid fills (taker SELLs hit our bid) | **3-10** (test scale, 5-share orders) | wallet: 200-400 at full scale |
| Merges (NegRiskAdapter calls) | **1-3** (test scale) | wallet: 20+ at full scale |
| Redeems (settlement) | 0-1 (if leftover) | rare |

**Key calibration**: at $50 seed posting 5-share bids, we expect **3-10 fills per slug** (we're at the back of a 100-1000 share queue). Wallet at $47k seed posts 8-20 share orders and gets 200-400 fills/slug.

---

## 6. Input/Output interfaces

### Inputs (events to consume)

```python
SlugStart(slug, asset, tf, slot_start_us, slot_end_us, condition_id)
L25Update(slug, ts_us, books={up: L25Snapshot, dn: L25Snapshot})
TradePrint(slug, ts_us, side, price, size)  # for verification only
OrderUpdate(slug, order_id, status, filled_size, fill_price)
SlugResolved(slug, outcome, settlement_ts_us)
WalletBalance(usdc_balance, last_updated_us)
```

### Outputs (actions to emit)

```python
PostBid(slug, side, price, size, order_type="GTC_POST_ONLY") → order_id
Cancel(order_id) → ack
MergePositions(slug, pairs, method) → tx_hash
RedeemPositions(slug, condition_id) → tx_hash
LogDecision(strategy_code, slug, ts_us, action, payload, projected_pnl)
LogSlugComplete(strategy_code, slug, state, slug_pnl)
```

---

## 7. Shadow mode requirements

In shadow mode (`shadow_only=True`):
- All `PostBid` / `Cancel` / `MergePositions` / `RedeemPositions` actions are LOGGED, not submitted
- Simulate fills by checking incoming `TradePrint` events:
  - If `trade.side == 'SELL' AND trade.price <= our_active_bid_price`:
    - Simulate fill (subject to queue-position approximation)
    - Update simulated state
- Output CSV: `shadow_acc_m_<date>.csv` with columns:
  ```
  ts_us, slug, action, side, price, size, simulated_fill, sim_inv_up, sim_inv_dn,
  sim_cash_spent, sim_cash_recovered, sim_pnl_so_far, slug_offset_s, condition_met
  ```

After 48h shadow:
- Compute realized $/slug per cell
- Compute simulated fill rate vs ideal (queue-aware)
- Compare to acc_simulator backtest projection

**Promotion criteria**:
- Mean realized $/slug > $0 (positive expectancy)
- Median realized $/slug > $0 (>50% positive slugs)
- No drawdown > $25 in 24h
- IF YES → set `shadow_only=False` and start live at $50 seed

---

## 8. Failure modes + handling

| Failure | Symptom | Handling |
|---|---|---|
| WS disconnect | No L25/trade updates | Cancel all open orders within 5s, wait for reconnect |
| Order post fails | Polymarket API error | Retry once, then skip slug |
| Merge fails (gas) | Tx revert | Retry with higher gas; if 3 fails, redeem at slug end |
| Wallet drains to $0 | balance==0 | Halt strategy, alert operator |
| Inventory imbalance > 50 | |inv_up - inv_dn| huge | Force market-buy lighter side, then stop slug |
| Cell-wide losses | Daily PnL on cell < -$50 | Pause cell for 24h |

---

## 9. Implementation checklist (for TV agent)

- [ ] Subscribe to Polymarket CLOB WS feed for L25 + trades on configured cells
- [ ] Subscribe to chainlink RTDS / slug resolution events
- [ ] Implement state machine (see §2)
- [ ] Implement decision rules (see §3) with all filters
- [ ] Implement inventory balance enforcement (CRITICAL — naked position guard)
- [ ] Implement NegRiskAdapter merge call (or CTF.mergePositions fallback)
- [ ] Implement redemption call after slug resolution
- [ ] Shadow logging (CSV with all columns in §7)
- [ ] PnL tracking + daily summary
- [ ] Failure handling (see §8)
- [ ] Kill switch on operator command
- [ ] Unit tests: each decision rule with synthetic events
- [ ] Integration test: replay 1 historical slug, verify output matches acc_simulator

---

## 10. Reference files

- Backtest validation: `strategy_lab/wallet_hunt/replicate/acc_simulator.py`
- Strategy base: `strategy_lab/strategies/base.py`
- Wallet decode (source): `strategy_lab/wallet_hunt/cache/0x04b6d7e9/`
- TX taxonomy: `strategy_lab/reports/WALLET_TX_TAXONOMY_2026_05_18.md`
- Strategy spec (this doc): `strategy_lab/reports/TV_AGENT_SPEC_ACC_M_2026_05_18.md`

---

## 11. Contract addresses (Polygon mainnet)

```
USDC.e         = 0x2791bca1f2de4661ed88a30c99a7a9449aa84174
PUSD wrapper   = 0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb
CTF            = 0x4d97dcd97ec945f40cf65f87097ace5ea0476045
CLOB Matcher   = 0xe111180000d2663c0091e4f400237545b87b996b
NegRiskAdapter = 0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0
```

Use `NegRiskAdapter` for merge route (matches all decoded wallet behavior).
