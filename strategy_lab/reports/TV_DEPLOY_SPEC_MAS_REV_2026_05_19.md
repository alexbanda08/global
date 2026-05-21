# TV Agent Deploy Spec — MAS REV (Mint and Sell, $100 budget)

**Version**: 2.0 (replaces TV_DEPLOY_SPEC_MAS_2026_05_18.md)
**Date**: 2026-05-19
**Mode**: Shadow first → Live after 48h validation
**Capital**: $100 USDC.e wallet (active capital: $60 in pre-mints + $40 reserve)
**Key changes vs v1**: Reduced from 6 cells to 2 cells, treat as data-gathering not profit engine

---

## 0. Why this revision exists

213-slug backtest validation showed:
- MAS-pre30 (v1 spec): +$0.09/slug avg — essentially flat
- MAS-pre50: +$0.04 to +$0.14/slug — also flat
- MAS-pre200-tight: -$0.12 to +$1.35/slug — high variance
- MAS-pre500: **-$3.02/slug** — actively LOSES money

MAS is **break-even at small scale and harmful at large scale**. It's not a money-loser at $30 pre-mint (which is good), but it's also not generating meaningful PnL.

We deploy it for two reasons:
1. **Live data collection** — see if real fill rates differ from simulated
2. **Strategy diversification** — MAS posts ASKs while ACC-M REV posts BIDs; they operate on different sides of the book and don't compete

---

## 1. What changes vs v1

| Param | v1 | REV | Reason |
|---|---|---|---|
| Active cells | 6 (btc/eth/sol × 5m/15m) | **2 (btc 5m + btc 15m)** | $100 budget can't fund 6 active mints simultaneously |
| Wallet seed | $100 (but planned $180 active) | **$100** (with $60 active) | Honest sizing |
| Pre-mint per slug | $30 | $30 (unchanged) | Don't scale up — sweep shows >pre100 underperforms |
| MAX_CONCURRENT_SLUGS | 6 | **2** | Match cell count |
| Promotion criteria mean $/slug | >$0.10 | **>$0** | Lower bar; break-even is acceptable |

---

## 2. Configuration

```python
MAS_REV_CONFIG = {
    # === CHANGED FROM v1 ===
    "wallet_seed_usdc": 100,           # WAS planned $180 active
    "cells": ["btc_5m", "btc_15m"],    # WAS all 6 cells
    "MAX_CONCURRENT_SLUGS": 2,         # WAS 6
    "MAX_DAILY_DRAWDOWN_USDC": 20,     # WAS 30 — tighter

    # === UNCHANGED (validated correct) ===
    "PRE_MINT_USDC": 30,
    "POST_SIZE": 5,                    # CLOB minimum for asks
    "MIN_SUM_ASKS": 1.005,             # only post when edge exists
    "MAX_SPREAD_PER_LEG": 0.05,
    "MIN_POST_INVENTORY": 5,
    "CANCEL_THRESHOLD": 0.03,
    "MAX_ORDER_AGE_S": 30,             # asks live longer than bids
    "CANCEL_ON_FILL": False,
    "CANCEL_ON_CLOSE": False,

    # === SHADOW / LIVE ===
    "shadow_mode": True,
    "log_path": "shadow_mas_rev_{date}.csv",
}
```

---

## 3. Capital math

At $30 pre-mint × 2 active cells:
- Active capital: $60 in mints simultaneously
- Reserve: $40 for new mints as old slugs close + gas + safety

**Mint cycle**:
- Slug opens → check wallet has $30+$RESERVE → mint 30 pairs ($30 cost)
- Slug closes → redeem winning leftover → recover $X
- New slug opens → mint again

If 2 cells × 12 slugs/h = 24 mints/hour. At $30 each = $720/h in gross mint-and-recover cycle. Net $60 active at any time.

**DO NOT** mint a new slug if wallet balance < $35 (the $30 mint + $5 reserve). Engine must enforce.

---

## 4. State machine (unchanged from v1)

Inherits v1 spec. Key flow:

```
SlugActive(slug, condition_id) 
  → if wallet_balance >= $35:
      MintPairs($30) — gas + 30 pairs of Up + Down tokens
      state.inv_up = 30, state.inv_dn = 30

L25Update
  → for each side: cancel-on-displacement, repost ASK if conditions hold

OrderFill (taker BUY hits our ASK)
  → state.inv[side] -= sz
  → state.cash_received += sz * fill_price
  → state.rebates += sz * maker_rebate(fill_price)

SlugResolved(outcome)
  → if outcome="Up": redeem state.inv_up at $1
  → if outcome="Down": redeem state.inv_dn at $1
  → slug_pnl = cash_received + rebates + redemption - mint_cost
```

---

## 5. Per-slug expected behavior

At $30 pre-mint:

| Event | Expected count |
|---|---|
| Mint (1× per slug) | 1 |
| L25 updates | ~300 |
| Ask posts | 40-100 |
| Ask fills | 5-15 |
| Redeem (1× per slug) | 1 |
| Per-slug PnL avg (backtest) | +$0.09 |

Per-slug PnL breakdown:
- Mint cost: -$30
- Trading cash from fills: +$15-25 (sells at $0.50-0.70 avg)
- Maker rebates: +$0.10
- Leftover redemption (winning side): +$5-30
- **Net: -$5 to +$10 typical, ~+$0 average**

---

## 6. Shadow → Live promotion criteria (relaxed)

After 48h shadow:
- **Mean realized $/slug ≥ -$0.50** (essentially break-even — was $0.10 in v1)
- **At least 70% of mints fully recovered** (mint cost recovered by close)
- **No more than 3 consecutive losing slugs per cell**
- **Max 24h drawdown < $20**

Why looser bar? MAS is a data-collection deployment. We're learning whether live behavior matches sim before scaling. Break-even is acceptable.

---

## 7. Live deploy progression

1. **Day 1**: Live at $100 wallet, BTC 5m ONLY initially (1 concurrent slug)
2. **Day 2**: If Day 1 PnL > -$10: enable BTC 15m as second cell
3. **Day 3-7**: Monitor — halt if 7-day rolling PnL < -$30
4. **Day 7**: Decision point:
   - PnL > +$30/week: keep running, gather more data
   - PnL -$30 to +$30: keep running but flag for re-tune
   - PnL < -$30: HALT and re-evaluate
5. **Day 14**: If consistently > +$50/week, consider adding ETH 5m as third cell (still in $100 budget if pre-mint=$25 × 3 cells = $75)

**DO NOT** scale pre-mint above $30 without separate validation backtest. Sweep showed pre-mint=$500 LOSES $3/slug.

---

## 8. Why MAS is barely profitable in backtest

Hypothesis from sweep data:

1. **At low pre-mint ($30)**: not enough inventory to fill many ASKs → revenue capped low → near break-even
2. **At medium pre-mint ($100-200)**: more inventory → more sells → but more leftover risk too → net flat
3. **At high pre-mint ($500)**: too much leftover-on-losing-side → burned cost overwhelms profit

There's no clear scaling path. MAS works at small scale or not at all.

If we want to make significant money from MAS, we need:
- Directional signal to bias mint toward winning side (don't have it)
- Multi-asset spread to reduce variance (could try BTC+ETH+SOL)
- Better slug selection (don't engage every slug)

---

## 9. Implementation checklist (delta from v1)

- [ ] Reduce active cells from 6 to 2 (btc_5m + btc_15m)
- [ ] Reduce MAX_CONCURRENT_SLUGS from 6 to 2
- [ ] Lower MAX_DAILY_DRAWDOWN from $30 to $20
- [ ] Lower promotion bar (mean $/slug > -$0.50)
- [ ] Update wallet preflight: need $100 USDC.e + approvals for CTF.splitPosition

All other v1 checklist items stand.

---

## 10. Expected revenue (honest)

**Backtest (213 slugs)**: +$0.09/slug avg.

**Live extrapolation**:
- ~8 BTC slugs/h (5m + 15m mix) × 14h = 112 slugs/day
- $0.09 × 112 = **$10/day theoretical**
- Realistic after live competition: **$0-5/day**
- Worst case 24h drawdown: -$15

This is **a learning deployment**, not a revenue engine. Set expectations accordingly.

---

## 11. What MAS REV does NOT cover

- ETH and SOL — start BTC only
- 4PM-ET daily markets — only 5m/15m
- Directional bias toward winning outcome (no signal decoded)
- Pre-mint scaling above $30 (validated harmful at $500)

These are research items, not deployment items.

---

## 12. Compatibility with ACC-M REV

MAS posts ASKs. ACC-M REV posts BIDs. They operate on opposite sides of the book and **DO NOT** compete for queue position or fills.

**Running both simultaneously**:
- ACC-M REV on BTC 5m wallet ($100)
- MAS REV on BTC 5m + BTC 15m, different wallet ($100)
- They each fund themselves independently

If using a single shared wallet:
- Net $200 capital with $40+ in pre-mints + $20 in BIDs + $140 reserve
- Engine enforces per-strategy capital allocation

---

## 13. Bottom line

**MAS REV is a small-scale data-gathering deployment.** Not a profit engine at our current scale.

Run it for 30 days at $100 capital. If consistently breaks even → keep running for the diversification value (independent edge from ACC-M REV). If consistently loses → halt.

Don't expect MAS to make us rich. The wallet `0x04b6d7e9` (98% SELL maker) makes $2k/day at $50M+ cumulative volume — implying ~$10k-50k working capital. At our $100 we're 100-500x smaller and revenue scales sub-linearly.

If after 60 days both ACC-M REV and ACC-PC are working AND we have a $1k+ bankroll to commit, revisit MAS at larger scale.

---

*See `STRATEGY_REVISION_2026_05_19.md` for the full strategy revision context.*
