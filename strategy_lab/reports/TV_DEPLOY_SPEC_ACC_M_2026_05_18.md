# TV Agent Deploy Spec — ACC-M (Maker Pair Arbitrage)

**Version**: 1.0
**Mode**: Shadow first → Live after 48h validation
**Type**: Pair arbitrage maker bot for Polymarket binary up-down markets

---

## 0. Performance requirements (read FIRST)

This strategy competes with 100+ other maker bots for queue position. The
performance requirements in `TV_AGENT_HANDOFF_2026_05_18.md` §"Performance
requirements (MANDATORY)" are NOT optional:

- VPS in Ireland/London (<5ms RTT to AWS eu-west-2)
- WebSocket-only order posting (NOT REST)
- Pre-signed order pool at slug start
- Async pipeline (zero blocking on hot path)
- Persistent WS connections with TCP keepalive
- msgspec/orjson for JSON parsing
- Integer-cent price quantization
- Async logging (non-blocking)
- Latency instrumentation (p50/p90/p99 per operation)

Target hot-path latency: **end-to-end < 1ms (excluding network)**.

If any of these are not met, the strategy will lose to faster bots. Verify all
performance requirements pass before deploying.

---

## 1. What you're building

A bot that:
1. Posts limit BUY (BID) orders on both Up and Down sides of binary up-down markets
2. Accumulates paired Up+Down inventory at prices summing to less than $1.00
3. Periodically merges paired inventory via the NegRiskAdapter to recover USDC.e
4. Recycles capital continuously through the slug lifecycle
5. At slug resolution, redeems any leftover single-side inventory for $1 per winning share

The strategy captures the structural mispricing where `sum_bids < $1.00`. Each merged pair returns $1 of USDC.e, so accumulating pairs at a combined cost below $1 yields arbitrage profit + maker rebate income.

---

## 2. State machine

```
EVENT                              STATE              ACTIONS
────────────────────────────────────────────────────────────────────────────
SlugActive(slug, slot_end_us)      IDLE              → state = ACCUMULATING
                                                       SlugState initialized

L25Update(slug, books)             ACCUMULATING      → For each side (Up, Down):
                                                         Run cancel-check on open order
                                                         Run post-check; post if conditions hold

OrderFill(slug, side, sz, px)      ACCUMULATING      → inv[side] += sz
                                                       cash_spent += sz * px
                                                       rebates += sz * rebate(px)
                                                       Check merge trigger

MergeTrigger                       MERGING           → Send min(inv_up, inv_dn) pairs
                                                         to NegRiskAdapter contract
                                                       cash_recovered += pairs * $1
                                                       inv_up -= pairs; inv_dn -= pairs

CloseApproaching                   CLOSING           → Stop posting new bids
(now > slot_end - 30s)                                 Leave existing bids to fill

SlugResolved(slug, outcome)        SETTLING          → Force final merge of any paired
                                                       Redeem winning leftover via CTF
                                                       Log slug PnL
                                                       state = IDLE
```

---

## 3. Decision rules

### 3.1 Post a BID

Called on every L25Update.

```python
def should_post_bid(side, book, state, wallet_balance):
    # Stop posting near close
    elapsed_s = (now_us - state.slot_start_us) / 1_000_000
    if elapsed_s > state.slug_duration_s - 30:
        return False, None

    # Skip wide books
    spread = book.best_ask - book.best_bid
    if spread > 0.05:
        return False, None

    # Edge filter: only post when sum_bids < $1
    sum_bids = book.up.best_bid + book.dn.best_bid
    if sum_bids >= 1.00:
        return False, None

    # Price band
    bid_price = book[side].best_bid
    if not (0.05 <= bid_price <= 0.95):
        return False, None

    # Inventory balance — don't accumulate too much on one side
    if side == "Up" and state.inv_up > state.inv_dn + MAX_IMBALANCE_SHARES:
        return False, None
    if side == "Down" and state.inv_dn > state.inv_up + MAX_IMBALANCE_SHARES:
        return False, None

    # Hard cap
    if state.inv[side] >= ABSOLUTE_MAX_INVENTORY:
        return False, None

    # Wallet balance check
    required = POST_SIZE * bid_price
    if wallet_balance < required + RESERVE_USDC:
        return False, None

    return True, bid_price
```

### 3.2 Cancel an existing BID

Called on every L25Update for each open order.

```python
def should_cancel_bid(order, book):
    # Rule 1: book displacement
    displacement = abs(order.price - book[order.side].best_bid)
    if displacement >= CANCEL_THRESHOLD:
        return True, "displacement"

    # Rule 2: age
    age_s = (now_us - order.posted_us) / 1_000_000
    if age_s >= MAX_ORDER_AGE_S:
        return True, "age"

    # Otherwise leave the order alone
    return False, None
```

**IMPORTANT**: Do NOT cancel on partial fill. Leave residuals on the book.
**IMPORTANT**: Do NOT cancel near slug close. Let orders fill or expire naturally.

### 3.3 Merge trigger

Called after every fill and on a 5-second periodic timer.

```python
def should_merge(state):
    pairs = int(min(state.inv_up, state.inv_dn))
    return pairs >= MERGE_THRESHOLD_PAIRS
```

### 3.4 At slug resolution

```python
def on_slug_resolved(slug, outcome, state):
    # Force final merge
    pairs = int(min(state.inv_up, state.inv_dn))
    if pairs > 0:
        merge_via_adapter(slug, pairs)

    # Redeem winning leftover
    if outcome == "Up" and state.inv_up > pairs:
        redeem_positions(slug, side="Up", shares=state.inv_up - pairs)
    elif outcome == "Down" and state.inv_dn > pairs:
        redeem_positions(slug, side="Down", shares=state.inv_dn - pairs)

    # Log PnL
    slug_pnl = state.cash_recovered + state.rebates - state.cash_spent
    log_slug_complete(slug, state, slug_pnl)
```

---

## 4. Configuration

```python
ACC_M_CONFIG = {
    # Strategy identity
    "strategy_code": "ACC-M",
    "version": "1.0.0",

    # Market scope
    "cells": ["btc_5m", "btc_15m"],   # Start small; expand after validation
    "operating_hours_utc": None,       # 24/7

    # Capital
    "wallet_seed_usdc": 50,            # Test scale
    "RESERVE_USDC": 5,                 # Keep this much liquid for gas etc.

    # Posting
    "POST_SIZE": 5,                    # Shares per post (CLOB minimum)
    "MIN_BID_PRICE": 0.05,
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,              # Only post when sum_bids < this
    "MAX_SPREAD_PER_LEG": 0.05,
    "MAX_CONCURRENT_SLUGS": 4,

    # Inventory balance
    "MAX_IMBALANCE_SHARES": 5,         # Stop posting heavy side if exceeded
    "ABSOLUTE_MAX_INVENTORY": 50,      # Hard cap on either side

    # Cancel rules
    "CANCEL_THRESHOLD": 0.03,          # Cancel if best_bid moves >= 3¢ from our price
    "MAX_ORDER_AGE_S": 20,             # Cancel orders older than 20s
    "CANCEL_ON_FILL": False,           # KEEP residuals after partial fills
    "CANCEL_ON_CLOSE": False,          # Let orders fill/expire near close

    # Merging
    "MERGE_THRESHOLD_PAIRS": 5,        # Merge when min(inv_up, inv_dn) >= 5
    "MERGE_CHECK_INTERVAL_S": 5,       # Periodic merge check timer

    # Risk
    "MAX_DAILY_DRAWDOWN_USDC": 25,
    "MAX_CONSECUTIVE_LOSING_SLUGS": 10,

    # Shadow vs Live
    "shadow_mode": True,               # Set False for live
    "log_path": "shadow_acc_m_{date}.csv",
}
```

---

## 5. Required interfaces

### Inputs (events to consume)

| Event | Schema |
|---|---|
| `SlugActive` | slug, asset, tf, slot_start_us, slot_end_us, condition_id |
| `L25Update` | slug, ts_us, books (per side: best_bid, best_ask, sizes) |
| `OrderFill` | slug, order_id, side, fill_size, fill_price |
| `SlugResolved` | slug, outcome, settlement_ts_us |
| `WalletBalance` | usdc_balance, last_updated_us |

### Outputs (actions to emit)

| Action | Schema |
|---|---|
| `PostBid` | slug, side, price, size, order_type="GTC_POST_ONLY" → order_id |
| `Cancel` | order_id → ack |
| `MergePositions` | slug, pairs → tx_hash |
| `RedeemPositions` | slug, condition_id, side, shares → tx_hash |
| `LogDecision` | strategy_code, slug, ts_us, action, payload |
| `LogSlugComplete` | strategy_code, slug, state, slug_pnl |

---

## 6. Per-slug expected behavior

At test scale ($50 seed, 5-share posts):

| Event | Count |
|---|---|
| L25 updates received | ~300 (1/sec for 5m slug) |
| Bid posts | 50-150 (after dedup/cancel) |
| Cancels | 10-30 |
| Bid fills | 3-15 |
| Merges | 1-3 |
| Settlement redeems | 0-1 |

At wallet scale ($5k+ seed, 5-share posts):

| Event | Count |
|---|---|
| Bid fills | 100-400 |
| Merges | 5-20 |

---

## 7. Shadow mode requirements

When `shadow_mode=True`:
- All actions (PostBid, Cancel, MergePositions, RedeemPositions) are LOGGED, not submitted
- Simulate fills by listening to TradePrint events:
  - If `trade.side == 'SELL'` AND `trade.price <= our_active_bid_price`:
    - Simulate fill of size `min(post_size, trade.size * queue_share)`
    - Update simulated state
- queue_share approximation: `post_size / (post_size + visible_bid_size_at_our_price)`

CSV log columns:
```
ts_us, slug, action, side, price, size, simulated_fill, sim_inv_up, sim_inv_dn,
sim_cash_spent, sim_cash_recovered, sim_pnl_so_far, slug_offset_s, trigger_reason
```

Generate end-of-day report:
- Realized $/slug per cell
- Realized vs simulated fill rate
- Realized vs simulated PnL
- Inventory balance discipline (% slugs >X% imbalance)

---

## 8. Live mode promotion criteria

After 48h shadow mode, promote to live if ALL pass:
- Mean realized $/slug > $0 (positive expectancy)
- Median realized $/slug > $0 (>50% positive slugs)
- Realized fill rate > 30% of simulated
- Max 24h drawdown < $25
- No more than 2 slugs with > 25% imbalance (discipline check)

Live deploy progression:
1. Start at $50 seed, BTC 5m only
2. Run 24h
3. If PnL matches projection: expand to BTC 15m
4. After 7 days clean: expand to ETH 5m + 15m
5. Scale seed 2x per week if PnL > $50/day per cell

Maximum recommended seed for initial deploy: $500 (above this, queue position and infrastructure speed matter much more).

---

## 9. Failure handling

| Failure | Detection | Response |
|---|---|---|
| WS feed disconnect | No L25/trade for >5s | Cancel all open orders; pause until reconnect |
| Order post fails | API error | Retry once with backoff; skip slug if 2nd fails |
| Merge tx fails | Tx revert | Retry with higher gas; if 3 fails, redeem at slug end |
| Wallet balance < reserve | balance check | Pause strategy; alert operator |
| Inventory > absolute_max | check at fill | Stop posting on heavy side; force market buy on light side at next L25 if available |
| Daily drawdown > 25 USDC | end-of-fill check | Halt strategy until manual reset |

---

## 10. Implementation checklist

- [ ] Subscribe to Polymarket CLOB WebSocket for L25 + trades on configured cells
- [ ] Subscribe to chainlink resolution events for slug close detection
- [ ] Implement SlugState dataclass and per-slug instance tracking
- [ ] Implement state machine transitions (§2)
- [ ] Implement decision rules (§3) with all filters
- [ ] Implement inventory balance enforcement
- [ ] Implement order management (post / cancel / track lifecycle)
- [ ] Implement merge call to NegRiskAdapter contract
- [ ] Implement redemption call to ConditionalTokens contract
- [ ] Shadow logging to CSV with all columns from §7
- [ ] Daily PnL summary report
- [ ] Failure handling (§9)
- [ ] Kill switch on operator command (signal-based)
- [ ] Unit tests for each decision rule using synthetic events
- [ ] Integration test: replay 1 historical slug, verify behavior matches expected pattern
- [ ] Deploy to production environment with shadow_mode=True
- [ ] Monitor for 48h
- [ ] Run promotion criteria check
- [ ] Toggle shadow_mode=False for live deploy

---

## 11. Reference files

- `strategy_lab/wallet_hunt/replicate/acc_simulator.py` — Python reference simulator
- `strategy_lab/strategies/base.py` — StrategyBase interface
- Backtest validation script: same simulator can replay shadow logs

---

## 12. Why this strategy works

The market regularly displays `sum_bids < $1.00` due to:
- Asymmetric taker flow (one side gets sold more aggressively)
- Maker risk pricing (maker bids below mid to compensate)
- Liquidity premium (makers want compensation for inventory risk)

When we accumulate Up + Down at a combined cost below $1.00, and either:
- Merge the pair for exactly $1.00 (NegRiskAdapter)
- Or redeem the winning side for $1.00 at settlement

The mechanism is risk-free as long as we maintain inventory balance. Maker rebate income is bonus profit on top of the spread capture.

Edge per pair = $1.00 - sum_bids + maker_rebate. Typical: $0.05-$0.20.
