# TV Agent Deploy Spec — MAS (Mint And Sell)

**Version**: 1.0
**Mode**: Shadow first → Live after 48h validation
**Type**: Maker selling of pre-minted pair inventory on Polymarket binary up-down markets

---

## 0. Performance requirements (read FIRST)

Same mandatory performance requirements as ACC-M. See `TV_AGENT_HANDOFF_2026_05_18.md`
§"Performance requirements (MANDATORY)":

- VPS in Ireland/London
- WebSocket-only order posting
- Pre-signed order pool
- Async pipeline
- Persistent WS connections
- msgspec/orjson for JSON parsing
- Integer-cent price quantization
- Async logging
- Latency instrumentation

MAS-specific: the MintPairs transaction happens ONCE at slug start (off the
critical path), so signing speed for mints is less important than for orders.
Post-fill order management still needs sub-ms hot path.

---

## 1. What you're building

A bot that:
1. Mints Up+Down pair inventory upfront at slug start via the ConditionalTokens contract
2. Posts limit SELL (ASK) orders on both Up and Down sides at the current best_ask
3. Captures the structural mispricing where `sum_asks > $1.00` (the inverse of ACC)
4. At slug resolution, redeems any leftover inventory for $1 per winning share

This is the mirror image of ACC-M: ACC posts BIDs (buys low), MAS posts ASKs (sells high). They do not compete on the same side of the book.

---

## 2. State machine

```
EVENT                              STATE              ACTIONS
────────────────────────────────────────────────────────────────────────────
SlugActive(slug, slot_end_us)      IDLE              → If cell enabled AND wallet has funds:
                                                         MintPairs(PRE_MINT_USDC)
                                                       inv_up = inv_dn = PRE_MINT_USDC
                                                       mint_cost = PRE_MINT_USDC
                                                       state = SELLING

L25Update(slug, books)             SELLING           → For each side (Up, Down):
                                                         Run cancel-check on open ask
                                                         Run post-check; post if conditions hold

OrderFill(slug, side, sz, px)      SELLING           → inv[side] -= sz
                                                       cash_received += sz * px
                                                       rebates += sz * rebate(px)

CloseApproaching                   CLOSING           → Stop posting new asks
(now > slot_end - 30s)                                 Leave existing asks to fill

SlugResolved(slug, outcome)        SETTLING          → Redeem winning leftover
                                                       Compute slug PnL
                                                       state = IDLE
```

---

## 3. Decision rules

### 3.1 On `SlugActive`

```python
def on_slug_active(slug, asset, tf, condition_id, state, wallet_balance):
    if not cell_enabled(asset, tf):
        return []
    if wallet_balance < PRE_MINT_USDC + RESERVE_USDC:
        return []  # insufficient capital

    return [MintPairs(
        slug=slug,
        condition_id=condition_id,
        amount_usdc=PRE_MINT_USDC,
    )]
    # On mint success: state.inv_up = PRE_MINT_USDC,
    #                  state.inv_dn = PRE_MINT_USDC,
    #                  state.mint_cost = PRE_MINT_USDC
```

### 3.2 Post an ASK

```python
def should_post_ask(side, book, state):
    elapsed_s = (now_us - state.slot_start_us) / 1_000_000
    if elapsed_s > state.slug_duration_s - 30:
        return False, None

    # Edge filter: only post when sum_asks > $1 (positive spread to capture)
    sum_asks = book.up.best_ask + book.dn.best_ask
    if sum_asks < MIN_SUM_ASKS:
        return False, None

    # Spread filter
    spread = book.best_ask - book.best_bid
    if spread > MAX_SPREAD_PER_LEG:
        return False, None

    # Inventory check
    if state.inv[side] < MIN_POST_INVENTORY:
        return False, None

    return True, book[side].best_ask
```

### 3.3 Cancel an existing ASK

Same rule shape as ACC-M cancel logic:

```python
def should_cancel_ask(order, book):
    displacement = abs(order.price - book[order.side].best_ask)
    if displacement >= CANCEL_THRESHOLD:
        return True, "displacement"
    age_s = (now_us - order.posted_us) / 1_000_000
    if age_s >= MAX_ORDER_AGE_S:
        return True, "age"
    return False, None
```

**IMPORTANT**: Do NOT cancel on partial fill (same as ACC-M).
**IMPORTANT**: Do NOT cancel near slug close.

### 3.4 On `SlugResolved`

```python
def on_slug_resolved(slug, outcome, state):
    leftover_up = state.inv_up
    leftover_dn = state.inv_dn

    if outcome == "Up" and leftover_up > 0:
        redeem_positions(slug, side="Up", shares=leftover_up)
        state.cash_received += leftover_up * 1.00
    elif outcome == "Down" and leftover_dn > 0:
        redeem_positions(slug, side="Down", shares=leftover_dn)
        state.cash_received += leftover_dn * 1.00

    slug_pnl = state.cash_received + state.rebates - state.mint_cost
    log_slug_complete(slug, state, slug_pnl)
```

---

## 4. Configuration

```python
MAS_CONFIG = {
    "strategy_code": "MAS",
    "version": "1.0.0",

    # Market scope (run on all 6 cells — small edge per cell adds up)
    "cells": ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"],
    "operating_hours_utc": None,       # 24/7

    # Capital
    "PRE_MINT_USDC": 30,               # Per slug, per cell
    "RESERVE_USDC": 5,

    # Posting
    "POST_SIZE": 5,                    # CLOB minimum
    "MIN_SUM_ASKS": 1.005,             # Only post when edge exists
    "MAX_SPREAD_PER_LEG": 0.05,
    "MIN_POST_INVENTORY": 5,

    # Cancel rules
    "CANCEL_THRESHOLD": 0.03,          # Cancel if best_ask moves >= 3¢
    "MAX_ORDER_AGE_S": 20,
    "CANCEL_ON_FILL": False,
    "CANCEL_ON_CLOSE": False,

    # Risk
    "MAX_DAILY_DRAWDOWN_USDC": 30,
    "MAX_CONCURRENT_SLUGS": 6,         # 1 per cell

    # Shadow vs Live
    "shadow_mode": True,
    "log_path": "shadow_mas_{date}.csv",
}
```

---

## 5. Required interfaces

Same input/output as ACC-M, EXCEPT:
- ADD: `MintPairs(slug, condition_id, amount_usdc)` action
- REMOVE: `MergePositions` (MAS doesn't merge mid-slug)

---

## 6. Per-slug expected behavior

| Event | Test scale | Wallet scale |
|---|---|---|
| Mint (1× per slug) | 1 | 1 |
| L25 updates | ~300 | ~300 |
| Ask posts | 50-150 | 100-400 |
| Ask fills | 5-15 | 50-200 |
| Redeem (1× per slug) | 1 | 1 |

---

## 7. Edge model

```
mint_cost = N_pairs * $1.00
cash_received = (filled_up * ask_up_price) + (filled_down * ask_dn_price)
              + maker_rebates
redemption_at_close = leftover_winning_side * $1.00

slug_pnl = cash_received + redemption_at_close - mint_cost

Per pair sold via both legs:
edge = sum_asks - $1.00 + maker_rebate
     ≈ $0.01 + $0.014 = $0.024
```

The edge per pair is smaller than ACC strategies but bounded and consistent.

---

## 8. Risk: held-side selection bias

If only one leg fills (other doesn't), we hold the leftover at slug end:
- Winning side: redeem at $1 → profit
- Losing side: $0 → loss

Empirically, held-side wins ~38% of the time (selection bias — the side that doesn't fill is often the side that's losing).

Mitigation: keep `PRE_MINT_USDC` small ($30-100). Worst-case naked exposure bounded by pre-mint size.

At PRE_MINT_USDC=$30:
- Max leftover: 30 shares × $1 = $30 if held side wins (gain) or 0 if loses (we already paid in mint)
- Worst-case net loss per slug (held side loses fully): $30 - small_partial_fills ≈ -$15 to -$25

---

## 9. Promotion criteria

After 48h shadow:
- Mean realized $/slug > $0.10
- Median realized $/slug > $0
- No more than 3 consecutive losing slugs per cell
- Max 24h drawdown < $30

If pass: enable live at $30 pre-mint × all 6 cells.

---

## 10. Implementation checklist

- [ ] Implement `MintPairs` call to ConditionalTokens contract
- [ ] Subscribe to L25 + trade WS for all 6 cells
- [ ] State machine (§2)
- [ ] Decision rules (§3) with all filters
- [ ] Track inv_up, inv_dn per slug
- [ ] Post-ask + cancel logic (same rule shape as ACC-M but for asks)
- [ ] Redemption call after slug resolution
- [ ] Shadow logging to CSV
- [ ] PnL tracking + daily summary
- [ ] Kill switch
- [ ] Unit tests for each decision rule
- [ ] Integration test: replay 1 historical slug, verify PnL matches expectation
- [ ] Deploy with shadow_mode=True
- [ ] Promote to live after 48h validation

---

## 11. Compatibility with ACC strategies

MAS posts ASKs. ACC strategies post BIDs. They operate on different sides of the book and DO NOT compete for queue position or fills.

If running BOTH (e.g., MAS + ACC-H on the same operator):
- Share wallet balance pool
- Allocate via config (e.g., $50 to MAS across 6 cells = $8/cell, $50 to ACC-H for BTC)
- Track per-strategy PnL separately

The two strategies capture opposite sides of the same spread mispricing.

---

## 12. Why this strategy works

The market regularly displays `sum_asks > $1.00` due to:
- Asymmetric taker flow on the buy side
- Maker risk pricing (asks priced above mid to compensate)
- Liquidity premium

When we mint a pair for $1.00 and sell BOTH sides at prices summing above $1.00, the difference is our edge plus maker rebate income. The leftover-bias risk is bounded by the small pre-mint size.

Edge per pair ≈ $0.01-$0.04. Smaller per-trade than ACC strategies, but volume × edge yields consistent positive PnL.
