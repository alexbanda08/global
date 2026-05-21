# TV Agent Deploy Spec — ACC-PC (Pair-Completion Taker)

**Version**: 1.0 (NEW STRATEGY)
**Date**: 2026-05-19
**Mode**: Shadow first → Live after 48h validation
**Capital**: $100 USDC.e seed
**Inherits**: ACC-M REV (all maker logic identical)

---

## 0. What is ACC-PC?

ACC-PC = **ACC-M plus a reactive taker layer**.

Pure ACC-M can end a slug with **imbalanced inventory** (one BID filled, other side didn't) — that leftover loses to $0 on the losing-resolution side. ACC-PC adds a smart taker that **only fires when imbalance exists** and the lagging side's ask is cheap enough to pair-complete profitably.

This is fundamentally different from ACC-H (V3f composite):
- ACC-H taker = opportunistic (any cheap ask, fire) → backtest -$6.84/slug
- ACC-PC taker = reactive (only on imbalance + sub-$0.97 pair-cost) → backtest +$0.27-0.49/slug

ACC-PC's premise: a pair-completion taker buy is **risk-free arbitrage** if executed at total pair cost < $1.00. The taker fee shrinks the edge but doesn't reverse the sign.

---

## 1. State machine extension

Inherits ACC-M REV state machine. Adds ONE new event handler:

```
EVENT                              ADDITIONAL ACTION
────────────────────────────────────────────────────────────────
L25Update(slug, books)             → (ACC-M actions PLUS)
                                     check_pair_completion(state, books)
                                     If trigger met: emit MarketBuy(lagging_side, ask, size)

OrderFill from MarketBuy           → state.inv[side] += sz
                                     state.taker_fees += sz * taker_fee(price)
                                     [rebalances toward pair, triggers merge if paired ≥ 5]
```

---

## 2. The trigger rule (ONLY rule, simple)

```python
def check_pair_completion_taker(state, books, ts_us, slot_start_us, cfg):
    """Fires ONLY when imbalanced AND pair-completion is profitable."""

    # Identify imbalance
    imbalance = abs(state.inv_up - state.inv_dn)
    if imbalance < 1.0:
        return None  # already balanced — let ACC-M maker do its thing

    # Identify lagging side (less inventory) and leading side
    if state.inv_up < state.inv_dn:
        lag_side = "Up"
        lead_inv = state.inv_dn
        lead_cost = state.cost_paid_dn
    else:
        lag_side = "Down"
        lead_inv = state.inv_up
        lead_cost = state.cost_paid_up
    lag_book = books[lag_side]

    # Rate limit checks
    elapsed_s = (ts_us - slot_start_us) / 1_000_000
    if elapsed_s < cfg.pc_min_time_before_taker_s:  # 30s default
        return None  # let BIDs work first
    if state.n_pc_taker[lag_side] >= cfg.pc_max_taker_per_slug:  # 5
        return None
    if (ts_us - state.last_pc_taker_us[lag_side]) < cfg.pc_min_s_between_taker * 1_000_000:
        return None

    # Inventory cap
    if state.inv[lag_side] >= cfg.absolute_max_inv:
        return None

    # Wallet balance
    take_size = cfg.pc_taker_size  # default 20 shares
    ask = lag_book.best_ask
    fee_per_share = poly_taker_fee(ask)
    take_cost = take_size * ask + take_size * fee_per_share
    if wallet_balance < take_cost + cfg.reserve:
        return None

    # === EDGE FILTER ===
    avg_lead_cost = lead_cost / lead_inv  # avg fill price on leading side
    pair_cost_per_share = avg_lead_cost + ask + fee_per_share
    if pair_cost_per_share >= cfg.pc_max_pair_cost:  # 0.97
        return None  # taking wouldn't be profitable

    # === SAFETY: don't take if our own BID is close to ask ===
    # (because our BID will fill anyway, saving us the taker fee)
    our_bid = state.open_bid_price.get(lag_side)
    if our_bid and (ask - our_bid) <= cfg.pc_min_spread_to_taker:  # 0.02
        return None

    # === SAFETY: only fire if CVD says BUYERS dominate the lagging side ===
    # (positive CVD → sellers won't drop to our BID → take now)
    cvd_30s = sum(d for _, d in state.cvd_window[lag_side])
    if cvd_30s <= cfg.pc_cvd_threshold:  # 0
        return None

    # ALL CHECKS PASSED — fire taker buy
    return MarketBuy(
        side=lag_side,
        price=ask,
        size=min(take_size, imbalance),  # cap at imbalance amount
        reason="pair_completion",
    )
```

---

## 3. Configuration

```python
ACC_PC_CONFIG = {
    # === INHERIT FROM ACC-M REV ===
    "strategy_code": "ACC-PC",
    "POST_SIZE": 20,
    "MIN_BID_PRICE": 0.05,
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,
    "MAX_SPREAD_PER_LEG": 0.05,
    "CANCEL_THRESHOLD": 0.03,
    "MAX_ORDER_AGE_S": 20,
    "MERGE_THRESHOLD_PAIRS": 5,
    "stop_posting_offset_s": 270,

    # === ACC-PC ADDITIONS ===
    "enable_pc_taker": True,
    "pc_taker_size": 20,                 # shares per pair-completion buy
    "pc_max_pair_cost": 0.97,            # edge threshold
    "pc_min_time_before_taker_s": 30,    # don't fire in first 30s
    "pc_min_spread_to_taker": 0.02,      # skip if BID near ask
    "pc_cvd_threshold": 0.0,             # require positive buyer pressure
    "pc_cvd_window_s": 30,
    "pc_max_taker_per_slug": 5,          # bounded
    "pc_min_s_between_taker_s": 5,       # rate limit per side

    # === INVENTORY (LOOSER THAN PURE ACC-M) ===
    "MAX_IMBALANCE_SHARES": 20,          # taker can rebalance, so allow more imbalance
    "ABSOLUTE_MAX_INVENTORY": 100,
    "MAX_CONCURRENT_SLUGS": 2,

    # === CAPITAL ===
    "wallet_seed_usdc": 100,
    "RESERVE_USDC": 15,                  # higher reserve due to taker buys
    "MAX_DAILY_DRAWDOWN_USDC": 20,
    "MAX_CONSECUTIVE_LOSING_SLUGS": 5,

    # === CELLS + MODE ===
    "cells": ["btc_5m"],
    "shadow_mode": True,
    "log_path": "shadow_acc_pc_{date}.csv",
}
```

---

## 4. Capital math

At POST_SIZE=20 + pc_taker_size=20:
- Maker side: $20/slug working capital (same as ACC-M REV)
- Taker buys: up to 5/slug × 20 shares × $0.50 = $50 additional per slug
- Worst-case per slug: $70 deployed
- 2 concurrent slugs: $140 — exceeds $100 wallet

**SOLUTION**: limit `pc_max_taker_per_slug` to **3** if running both maker and taker on a $100 wallet. Or run ACC-PC SOLO without ACC-M on the same cell.

**Recommended**: deploy ACC-PC on a DIFFERENT cell than ACC-M to avoid book competition.
- ACC-M REV on BTC 5m
- ACC-PC on BTC 15m

This way they don't compete on the same book, and each has its own $100 capital.

---

## 5. Expected behavior per slug

| Event | Per slug |
|---|---|
| L25 updates | ~300 |
| Maker BID posts | 50-100 |
| Maker BID fills | 8-25 |
| **Pair-completion taker fires** | **0-3** (only when imbalanced) |
| Merges | 2-5 |
| Avg PnL (backtest) | **+$0.30-0.50/slug** |

The taker fires INFREQUENTLY (12 out of 50 slugs in our backtest had any taker activity). It's a backup risk-reducer, not a primary edge driver.

---

## 6. Why the CVD filter?

`pc_cvd_threshold = 0` means we only take if cumulative volume delta on lagging side > 0 (more aggressive BUYS than SELLS in last 30s on that outcome).

Logic: if CVD is positive (buyers dominating), our BID is LESS likely to fill (sellers won't drop to us). So taking the ask now is the right move.

If CVD is negative (sellers dominating), our BID WILL fill naturally. Don't pay the taker fee.

This filter caused ACC-PC to fire only 12/50 slugs in backtest. Could relax to `cvd_threshold = -10` to fire more often.

---

## 7. Why the spread filter (`pc_min_spread_to_taker`)?

If our BID is at $0.49 and ask is at $0.50 (1¢ spread), our BID will almost certainly fill from the natural seller flow. No need to take.

If our BID is at $0.49 and ask is at $0.55 (6¢ spread), our BID is far from the ask and may never fill. Take.

Threshold: 2¢. Above 2¢ spread → take is worth it. Below → wait.

---

## 8. Shadow mode requirements

Same as ACC-M REV plus:
- Log each pair-completion check with WHICH filter rejected (cvd, spread, edge, time, rate)
- Log avg pair cost when fired
- Track post-fire PnL: did the pair merge profitably?

Specifically log to CSV:
```
ts_us, slug, side, ask, our_bid, spread, cvd_30s, avg_lead_cost, pair_cost,
edge_passed, spread_passed, cvd_passed, time_passed,
fired, fill_qty, fill_price, taker_fee, post_fire_inv_up, post_fire_inv_dn
```

---

## 9. Live promotion criteria

After 48h shadow:
- **Mean realized $/slug > $0** (must be positive)
- **Taker fires per slug averaged 0.2-1.0** (sanity check on filters)
- **At least one taker fire profitable when merged** (mechanism works)
- **Max 24h drawdown < $20**

---

## 10. Comparison: ACC-PC vs other variants

| Strategy | Taker logic | Backtest PnL | Risk |
|---|---|---|---|
| ACC-M REV | None | +$1.25/slug | Leftover-burn variance |
| **ACC-PC** | **Reactive (imbalance only)** | **+$0.30-0.50/slug** | Low (only takes when profitable) |
| ACC-H V3f | Opportunistic (4 rules) | -$6.84/slug | High (directional exposure) |

ACC-PC has **smaller mean than ACC-M REV** in our backtest because the taker filters rarely fire. But the THEORETICAL benefit is variance reduction — when ACC-PC does fire, it locks in a pair (no leftover risk). 

**Reality check**: ACC-PC might just be a marginal improvement over ACC-M REV. Treat it as data-collection deployment to see if the live taker fires are profitable AND reduce leftover-burn.

---

## 11. Implementation checklist (additions to ACC-M REV)

- [ ] Implement `check_pair_completion_taker` function
- [ ] Track per-side CVD rolling window (30s)
- [ ] Track avg_lead_cost per side (cost_paid / inv)
- [ ] Wire taker decisions to MarketBuy action
- [ ] Update taker_fee accounting
- [ ] Add pc-specific shadow log columns
- [ ] Unit test trigger logic with synthetic imbalance scenarios
- [ ] Verify rate limits work (min_s_between_taker, max_per_slug)

---

## 12. Bottom line

**ACC-PC is the safer ACC-M.** Same maker base, plus a reactive taker that ONLY fires when imbalance creates a clear pair-completion opportunity at total cost < $0.97.

Deploy after ACC-M REV is validated. Use $100 wallet on a separate cell (BTC 15m if ACC-M is on BTC 5m).

Expected PnL: +$0.30-0.50/slug × 8 slugs/h × 14h = $35-55/day theoretical. Realistic: $10-25/day.

Not the highest-PnL strategy but the lowest-risk variant we have.

---

*See `STRATEGY_REVISION_2026_05_19.md` for the full strategy revision context.*
