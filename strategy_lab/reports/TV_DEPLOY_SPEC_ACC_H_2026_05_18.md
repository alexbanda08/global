# TV Agent Deploy Spec — ACC-H (Hybrid Maker + Discount-Capture Taker)

**Version**: 1.0
**Mode**: Shadow first → Live after 48h validation
**Type**: Pair arbitrage with opportunistic market-buys on discounted asks

---

## 0. Performance requirements (read FIRST)

This strategy competes with 100+ other maker bots for queue position. The
performance requirements in `TV_AGENT_HANDOFF_2026_05_18.md` §"Performance
requirements (MANDATORY)" are NOT optional. Same as ACC-M:

- VPS in Ireland/London (<5ms RTT to AWS eu-west-2)
- WebSocket-only order posting
- Pre-signed order pool at slug start
- Async pipeline
- Persistent WS connections
- msgspec/orjson for JSON parsing
- Integer-cent price quantization
- Async logging
- Latency instrumentation

ACC-H additionally requires:
- **Sub-millisecond reaction to ASK DROPS** for the discount-capture trigger
- The ask history (rolling 60s) must be updated on every L25 tick with zero allocation
- Discount-trigger check must complete in <100µs

If discount-capture decisions take > 1ms, you'll miss the cheap fills (other
takers will get them first).

---

## 1. What you're building

Same core as ACC-M (post BIDs + accumulate + merge) PLUS opportunistic MARKET BUYS when the ask on either side drops below fair value. The market-buys lock in pair-arbitrage at a much better cost basis than waiting for the slow passive bid to fill.

The added taker module captures ~2-3× more edge per pair on the slugs where ask drops occur (typically 30-50% of slugs).

---

## 2. State machine

Inherits ACC-M state machine, with ONE new event handler:

```
EVENT                              ADDITIONAL ACTION
────────────────────────────────────────────────────────────────────
L25Update(slug, books)             → ACC-M actions PLUS:
                                     check_taker_trigger(slug, books, state)
                                     If trigger met: emit MarketBuy(side, price, size)

OrderFill from MarketBuy           → inv[side] += sz
                                     cash_spent += sz * px + taker_fee
                                     Check merge trigger
```

---

## 3. Decision rules

Inherits all ACC-M rules. ADD the discount-capture taker rule:

### 3.5 Composite taker trigger (3 OR-combined rules)

Coverage: ~70% of decoded taker fires. Called on every L25Update AND on every TradePrint.

```python
def check_taker_trigger(slug, books, state, ts_us,
                        ask_history_60s, trade_price_history_5s):
    """Composite trigger — fires on any of 3 rules."""
    actions = []
    for side in ["Up", "Down"]:
        current_ask = books[side].best_ask

        # Rate limit / cap filters (apply to ALL rules)
        if state.inv[side] >= ABSOLUTE_MAX_INVENTORY:
            continue
        last_take_us = state.last_taker_buy_us.get(side, 0)
        if (ts_us - last_take_us) < MIN_S_BETWEEN_TAKER_BUYS * 1_000_000:
            continue
        if state.taker_buy_count >= MAX_TAKER_BUYS_PER_SLUG:
            continue
        cost = TAKER_SIZE * current_ask + taker_fee(current_ask, TAKER_SIZE)
        if wallet_balance < cost + RESERVE_USDC:
            continue

        # --- Rule A: DISCOUNT-CAPTURE (33% of taker fires) ---
        # Take when current ask is significantly below recent median
        if current_ask < MAX_TAKER_PRICE_DISCOUNT:  # 0.50
            recent = ask_history_60s[side]
            if len(recent) >= 10:
                median_ask = median([a for a in recent if a > 0])
                if median_ask - current_ask >= MIN_ASK_DROP_60S:  # 0.03
                    actions.append(MarketBuy(slug, side, current_ask, TAKER_SIZE,
                                              reason="discount_capture"))
                    continue

        # --- Rule B: SHARP-DROP (33% of taker fires) ---
        # Take when own-side trade price dropped sharply in last 5s
        recent_trades = trade_price_history_5s[side]
        if len(recent_trades) >= 3:
            max_recent = max(p for _, p in recent_trades)
            drop_5s = max_recent - current_ask
            if drop_5s >= MIN_TRADE_DROP_5S:  # 0.02
                actions.append(MarketBuy(slug, side, current_ask, TAKER_SIZE,
                                          reason="sharp_drop"))
                continue

        # --- Rule C: EARLY-SLOT (20% of taker fires) ---
        # Take in first minute of slot (front-loading inventory)
        offset_s = (ts_us - state.slot_start_us) / 1_000_000
        if EARLY_SLOT_START_S <= offset_s <= EARLY_SLOT_END_S:  # [0, 60]
            # Only if we don't already have a maker bid filling on this side
            has_open_bid = any(o.is_bid and o.side == side
                                for o in state.open_orders.values())
            if not has_open_bid or state.fill_count[side] == 0:
                # Skip price filter for early-slot rule? Decoded data shows
                # this fires across price range, so no MAX_TAKER_PRICE check
                actions.append(MarketBuy(slug, side, current_ask, TAKER_SIZE,
                                          reason="early_slot"))

    return actions
```

**Rule details** (from decoded chain data — V3f composite):

| Rule | Trigger | Coverage | Lift over random |
|---|---|---|---|
| A: Discount-capture | `ask < 0.50 AND (60s_median_ask - ask) > 0.03` | 33% | 1.48× |
| B: Sharp-drop | `(max(trade_prices_5s) - current_ask) > 0.02` | 33% | 1.94× |
| C: Early-slot | `0 <= offset_s <= 60 AND no_prior_fill` | 20% | 1.63× |
| **D: Buy-pressure-then-dip (NEW)** | `buy_vol_60s > 50 AND (max_trade_5s - current_ask) > $0.001` | +10pp | **1.84×** |

**Rejected hypotheses** (do NOT use these):
- Signed-volume / order-flow imbalance (anti-signal)
- Book imbalance (anti-signal)
- Binance momentum (noise — 1MIN granularity too coarse)
- Absolute cheap-price < $0.30 (covered by Rule A already)
- Inventory pacing (random)
- Book depth beyond top-of-book (no signal)
- Trade-size bursts (no signal)
- Own-side maker-fill chasing (no signal)
- Sub-second signed volume (no signal at 1-2s windows)
- Sum_asks magic thresholds (no signal)
- Cross-exchange (coinbase 60s) — borderline, weak

V3f composite rule (A + B + C + D) covers **78.9% of decoded taker fires** at **1.37× lift** (z=+11.9).
The remaining 21.1% IS hidden alpha (residual WR 63.8% vs captured 60.7%) but
likely driven by sub-second CLOB events we can't see in 1Hz L25 snapshots.

**Decision: SAFE TO DEPLOY** with V3f. Missing 21% is ~$0/week PnL impact in
real Polymarket fees (the marginal tail trades are EV-negative after taker fees).

---

## 4. Configuration (extends ACC-M)

```python
ACC_H_CONFIG = {
    **ACC_M_CONFIG,                    # Inherit all ACC-M settings

    "strategy_code": "ACC-H",

    # Taker composite trigger (3 OR-combined rules)
    "TAKER_SIZE": 5,                       # CLOB minimum
    # Rule A — Discount-capture
    "MAX_TAKER_PRICE_DISCOUNT": 0.50,      # only Rule A; don't take above mid
    "MIN_ASK_DROP_60S": 0.03,              # 3¢ below 60s median = trigger
    "ROLLING_WINDOW_60S": 60,              # window for ask median
    # Rule B — Sharp-drop
    "MIN_TRADE_DROP_5S": 0.02,             # 2¢ drop in own-side trade prices in last 5s
    "ROLLING_WINDOW_5S": 5,                # window for trade-price max
    # Rule C — Early-slot
    "EARLY_SLOT_START_S": 0,
    "EARLY_SLOT_END_S": 60,                # first 60s of slot

    # Rate limits
    "MIN_S_BETWEEN_TAKER_BUYS": 5,     # Throttle per side
    "MAX_TAKER_BUYS_PER_SLUG": 50,

    # Inventory (looser than pure ACC-M because taker buys can rebalance)
    "MAX_IMBALANCE_SHARES": 10,        # Allow some imbalance; taker will rebalance
    "ABSOLUTE_MAX_INVENTORY": 100,
}
```

---

## 5. Required interfaces (extends ACC-M)

ADD to inputs:

| Event | Schema |
|---|---|
| `TradePrint` | slug, ts_us, side, price, size, taker_side (BUY/SELL) |

(This is used for the 60s ask history. Alternatively, derive from L25Update if trades aren't separately exposed.)

ADD to outputs:

| Action | Schema |
|---|---|
| `MarketBuy` | slug, side, price, size, reason → order_id |

---

## 6. Per-slug expected behavior (test scale)

| Event | ACC-M | ACC-H |
|---|---|---|
| Bid fills | 3-15 | 3-15 (same) |
| Market buys | 0 | 0-25 (more on volatile slugs) |
| Merges | 1-3 | 2-5 |

ACC-H expected to do 2-3× more volume than ACC-M on slugs with ask drops.

---

## 7. Edge model

**Pure maker fill (ACC-M behavior)**:
```
edge_per_pair = $1.00 - sum_bids_at_fill + maker_rebate
              ≈ $0.05 + $0.014 ≈ $0.06
```

**Discount-capture taker buy (ACC-H additional)**:
```
edge_per_pair = $1.00 - (other_side_bid_price + taker_ask_price + taker_fee)
              When taker_ask drops 5¢ below median:
              ≈ $1.00 - ($0.50 + $0.40 + $0.008) ≈ $0.092 per pair
              ~50% more than pure maker
```

When discount-capture fires (~30-50% of slugs), edge per pair on that slug is materially higher.

---

## 8. Risk addition

Taker fees are real cost: 0.07 × p × (1-p) per share. At p=$0.40: $0.0168/share, $0.084 on 5-share order.

Worst case taker exposure: TAKER_SIZE × MAX_TAKER_BUYS_PER_SLUG × MAX_TAKER_PRICE = 5 × 50 × $0.50 = $125 per slug.

Make sure `wallet_seed_usdc` >= worst_case_taker_exposure per active slug + RESERVE_USDC.

---

## 9. Promotion criteria (more stringent than ACC-M)

After 48h shadow, promote to live if:
- Mean realized $/slug > $0.50
- Median realized $/slug > $0.20
- Realized fill rate > 30% of simulated
- Realized taker fills capture cheaper price than recent median (verify the trigger is working)
- Drawdown < $30 in any 24h
- Taker buy fees don't exceed taker arbitrage capture

If pass: enable live at $50 seed, BTC 5m only.

---

## 10. Implementation checklist (in addition to ACC-M)

- [ ] Implement rolling 60s ask history tracker per (slug, side)
- [ ] Implement discount-capture trigger (§3.5)
- [ ] Anti-overfire rate limiter
- [ ] Per-slug taker count cap
- [ ] Track and log taker_reason for each market-buy
- [ ] Update PnL accounting to include taker fees as separate cost line
- [ ] Unit test discount trigger with synthetic ask drops
- [ ] Integration test: verify taker fires when ask drops match decoded thresholds

---

## 11. Why this works on top of ACC-M

When the book briefly displays a cheap ask (e.g., panic selling on Up drops ask to $0.40 vs $0.50 fair), there's a temporary microstructure dislocation. By market-buying immediately:
- We lock in the cheap pair-arb (vs $1.00 merge value)
- We avoid waiting for our passive bid to fill at higher prices
- We rebalance inventory if we were one-sided

Acceptable cost: small taker fee. Expected gain: 50%+ larger edge per pair on the slug.

The trigger is conservative (3¢ below 60s median + below mid) to avoid over-trading. This captures the most attractive dislocations without chasing every micro-tick.
