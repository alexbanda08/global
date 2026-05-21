# TV Agent Deploy Spec — PAT+ACC-M HYBRID

**Version**: 1.0 (NEW — replaces ACC-M REV as primary deployment)
**Date**: 2026-05-19
**Mode**: Shadow first → Live after 48h validation
**Capital**: $200 USDC.e seed (higher than $100 cap because Sharpe is best in this variant)
**Inherits**: ACC-M REV (BID-side maker) + PAT (pair-arb taker overlay)

---

## 0. TL;DR

This strategy is **ACC-M REV with a PAT (Pair-Arb Taker) overlay**. ACC-M does the heavy lifting (post BIDs both sides, accumulate paired inventory, merge for $1). PAT adds opportunistic market-buys on BOTH sides when sum_asks + fees < $1.00.

In 87-slug backtest:
- ACC-M-sz20 alone: +$1.65/slug
- **PAT+ACC-M-sz20 HYBRID: +$1.98/slug (+20% uplift, no downside)**

Same wallet seed as ACC-M REV, +20% PnL. Strictly better.

---

## 1. Strategy logic

### 1.1 ACC-M base (maker BIDs both sides)

Standard ACC-M behavior. On every L25Update:
- Post BID on Up + BID on Down when sum_bids < $1.00
- Cancel on 3¢ displacement or 20s age
- Don't cancel on partial fill
- Merge paired inventory when ≥5

This produces +$1.25-$1.65/slug per the 213-slug validation.

### 1.2 PAT overlay (taker pair-arb when cheap)

On every L25Update, ADDITIONALLY check:

```
if sum_asks + total_taker_fees < $1.00
   AND book has ≥5 shares at top-of-book on BOTH sides
   AND 5+ seconds since last PAT fire
   AND elapsed_s ≥ 5 (let book stabilize)
   AND inv on both sides < cap:
     → market-BUY 20 shares Up
     → market-BUY 20 shares Down (concurrent)
     → immediately merge the pair via NegRiskAdapter
     → realize $20 cash recovered, pay 2 × taker fees
```

This fires 0-2 times per slug typically. Each fire adds ~$0.10-0.30 to slug PnL.

---

## 2. State machine extension

Inherits ACC-M REV state machine. ADD one event handler:

```
EVENT                              ADDITIONAL ACTION
────────────────────────────────────────────────────────────────
L25Update(slug, books)             → (ACC-M actions PLUS)
                                     check_pat(ss_up, ss_dn, cfg, ts, slot_start)
                                     If trigger met:
                                       size = min(pat_take_size, ask_size_up, ask_size_dn)
                                       emit MarketBuy(slug, "Up",   ask_up, size)
                                       emit MarketBuy(slug, "Down", ask_dn, size)
                                       (after both fill) emit MergePositions(slug, size)
```

---

## 3. Configuration

```python
PAT_ACCM_HYBRID_CONFIG = {
    # === IDENTITY ===
    "strategy_code": "PAT-ACC-M-HYBRID",
    "version": "1.0.0",
    "wallet_seed_usdc": 200,          # $50 reserve + $150 working
    "RESERVE_USDC": 30,

    # === ACC-M BASE (validated from REV spec) ===
    "POST_SIZE": 20,
    "MIN_BID_PRICE": 0.05,
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,
    "MAX_SPREAD_PER_LEG": 0.05,
    "CANCEL_THRESHOLD": 0.03,
    "MAX_ORDER_AGE_S": 20,
    "CANCEL_ON_FILL": False,
    "CANCEL_ON_CLOSE": False,
    "MERGE_THRESHOLD_PAIRS": 5,
    "MERGE_CHECK_INTERVAL_S": 5,
    "stop_posting_offset_s": 270,
    "MAX_IMBALANCE_SHARES": 10,
    "ABSOLUTE_MAX_INVENTORY": 100,
    "MAX_CONCURRENT_SLUGS": 3,

    # === PAT OVERLAY (the new bit) ===
    "enable_pat": True,
    "pat_take_size": 20,              # match POST_SIZE
    "pat_max_pair_cost": 1.00,        # CRITICAL: above this loses money
    "pat_min_s_between_fires": 5,
    "pat_max_fires_per_slug": 10,
    "pat_min_book_depth_each_side": 5,
    "pat_min_time_after_open_s": 5,
    # NOTE: NO thin-book filter — backtest shows it hurts

    # === RISK ===
    "MAX_DAILY_DRAWDOWN_USDC": 30,
    "MAX_CONSECUTIVE_LOSING_SLUGS": 5,
    "MAX_HOURLY_FILLS": 200,
    "MAX_HOURLY_PAT_FIRES": 30,       # PAT-specific cap

    # === CELLS ===
    "cells": ["btc_5m"],              # Start with single cell

    # === SHADOW / LIVE ===
    "shadow_mode": True,
    "log_path": "shadow_pat_accm_{date}.csv",
}
```

---

## 4. PAT trigger pseudocode

```python
def check_pat_trigger(ss_up, ss_dn, state, cfg, ts_us, slot_start_us):
    """Check if PAT (pair-arb taker) should fire."""
    # Validity
    if not (0 < ss_up.best_ask < 1 and 0 < ss_dn.best_ask < 1):
        return False

    # Rate limit (combined across sides)
    last_fire_us = max(ss_up.last_pat_fire_us, ss_dn.last_pat_fire_us)
    if (ts_us - last_fire_us) < cfg.pat_min_s_between_fires * 1_000_000:
        return False
    if ss_up.n_pat_fires >= cfg.pat_max_fires_per_slug:
        return False

    # Hourly cap (across slugs)
    if state.hourly_pat_fires >= cfg.MAX_HOURLY_PAT_FIRES:
        return False

    # Timing: let book stabilize after slug opens
    elapsed_s = (ts_us - slot_start_us) / 1_000_000
    if elapsed_s < cfg.pat_min_time_after_open_s:
        return False

    # Book depth: need fills available at top-of-book
    if ss_up.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False
    if ss_dn.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False

    # === EDGE FILTER (the core) ===
    fee_up = poly_taker_fee_per_share(ss_up.best_ask)
    fee_dn = poly_taker_fee_per_share(ss_dn.best_ask)
    pair_cost = ss_up.best_ask + ss_dn.best_ask + fee_up + fee_dn
    if pair_cost >= cfg.pat_max_pair_cost or pair_cost <= 0:
        return False

    # Inventory cap (don't over-accumulate)
    if ss_up.inv >= cfg.absolute_max_inv or ss_dn.inv >= cfg.absolute_max_inv:
        return False

    # Wallet balance (need cash for the take)
    take_size = min(cfg.pat_take_size, ss_up.ask_size_at_best, ss_dn.ask_size_at_best)
    cost = take_size * (ss_up.best_ask + ss_dn.best_ask) + take_size * (fee_up + fee_dn)
    if state.wallet_balance < cost + cfg.RESERVE_USDC:
        return False

    return True


async def execute_pat_fire(slug, ss_up, ss_dn, state, cfg):
    """Execute the PAT fire — two simultaneous MarketBuy + immediate merge."""
    take_size = min(cfg.pat_take_size, ss_up.ask_size_at_best, ss_dn.ask_size_at_best)
    ask_up = ss_up.best_ask
    ask_dn = ss_dn.best_ask

    # Submit both MarketBuy orders in parallel (CRITICAL for arb)
    up_task = asyncio.create_task(
        client.market_buy(slug, "Up", ask_up, take_size)
    )
    dn_task = asyncio.create_task(
        client.market_buy(slug, "Down", ask_dn, take_size)
    )
    up_result, dn_result = await asyncio.gather(
        up_task, dn_task, return_exceptions=True
    )

    # Handle results
    if isinstance(up_result, Exception) or isinstance(dn_result, Exception):
        log.warning("PAT fire partial failure", up=up_result, dn=dn_result)
        # Best effort: track whatever filled
        if not isinstance(up_result, Exception):
            ss_up.inv += up_result.filled_size
            ss_up.cost_paid += up_result.filled_size * up_result.fill_price
        if not isinstance(dn_result, Exception):
            ss_dn.inv += dn_result.filled_size
            ss_dn.cost_paid += dn_result.filled_size * dn_result.fill_price
        # Don't immediate-merge if asymmetric fill — let ACC-M maker layer rebalance
        return

    # Both legs filled
    up_filled = up_result.filled_size
    dn_filled = dn_result.filled_size
    ss_up.inv += up_filled
    ss_up.cost_paid += up_filled * up_result.fill_price
    ss_up.taker_fees += up_filled * poly_taker_fee_per_share(up_result.fill_price)
    ss_dn.inv += dn_filled
    ss_dn.cost_paid += dn_filled * dn_result.fill_price
    ss_dn.taker_fees += dn_filled * poly_taker_fee_per_share(dn_result.fill_price)
    ss_up.n_pat_fires += 1
    ss_dn.n_pat_fires += 1
    ss_up.last_pat_fire_us = now_us()
    ss_dn.last_pat_fire_us = now_us()
    state.hourly_pat_fires += 1

    # Immediate merge — paired by construction
    pairs = min(up_filled, dn_filled)
    if pairs >= 1:
        await merger.merge_pairs(slug, pairs)
        ss_up.inv -= pairs
        ss_dn.inv -= pairs
        # cash_recovered tracked by merger callback


# On every L25Update:
if cfg.enable_pat:
    if check_pat_trigger(ss_up, ss_dn, state, cfg, ts_us, slot_start_us):
        asyncio.create_task(execute_pat_fire(slug, ss_up, ss_dn, state, cfg))
```

---

## 5. Capital math

At wallet seed $200:
- Reserve: $30
- ACC-M working: 2-3 slugs × $20 × 2 sides = $80-120
- PAT working: up to 2 fires/hour × 20 shares × ~$0.50 × 2 sides = $40 transient
- Total working: $120-160
- Buffer for new slugs: $40

PAT fires consume capital briefly (between MarketBuy and merge → $1/pair recovered). Net capital usage at any moment: small.

---

## 6. Expected per-slug behavior

| Event | Per slug |
|---|---|
| L25 updates | ~300 |
| ACC-M BID posts | 50-100 |
| ACC-M BID fills | 8-25 |
| **PAT taker fires** | **0-2** (rare, depends on book) |
| ACC-M merges | 2-5 |
| PAT merges | 0-2 |
| Avg PnL (87-slug backtest) | **+$1.98/slug** |
| Stddev | $13 |

---

## 7. Shadow → Live promotion criteria

After 48h shadow:
- Mean realized $/slug > $1.00 (was $0 for ACC-M REV — higher bar because we expect PAT uplift)
- Median realized $/slug > $0.50
- PAT fire rate sane (0-2 per slug on average)
- At least 1 PAT fire successfully paired in 48h
- Max 24h drawdown < $25

---

## 8. Live deploy progression

1. **Day 1**: Live at $200 wallet, BTC 5m ONLY, 2 max concurrent slugs
2. **Day 2-3**: Monitor — halt if 24h drawdown > $25
3. **Day 4**: If 3-day PnL > $50: enable 3 concurrent slugs
4. **Day 7**: If 7-day PnL > $150: enable BTC 15m as second cell, wallet at $200
5. **Day 14**: If 14-day PnL > $400: scale wallet to $400, enable ETH 5m
6. **Day 30**: If 30-day PnL > $1000: full scale-up to $1000 wallet across BTC + ETH

**Halt conditions**:
- 24h drawdown > $30
- 7-day rolling PnL < -$50
- 5 consecutive losing slugs
- Any error rate > 5%
- PAT fires fail to merge consistently (> 30% PAT fires don't pair-complete)

---

## 9. Implementation checklist

### Already have (from ACC-M REV)
- [ ] ACC-M REV strategy module (POST_SIZE=20, etc.)
- [ ] poly_merger.py (NegRiskAdapter merge call)
- [ ] BookMirror with bid/ask + sizes
- [ ] Order tracker per slug

### NEW for PAT+ACC-M HYBRID
- [ ] Implement `check_pat_trigger` function (~30 lines)
- [ ] Implement `execute_pat_fire` async function with dual-side MarketBuy
- [ ] Implement `client.market_buy` if not already there
- [ ] Add `n_pat_fires`, `last_pat_fire_us` to SideState
- [ ] Add `hourly_pat_fires` counter at engine level (reset hourly)
- [ ] Add PAT fire logging (separate from ACC-M maker fills)
- [ ] Wire PAT check after ACC-M maker logic in L25Update handler
- [ ] Unit test PAT trigger logic with synthetic books
- [ ] Integration test: ensure dual-side MarketBuy is atomic-ish
- [ ] Shadow logging includes PAT-specific columns: `pat_check_passed`, `pat_pair_cost`, `pat_fire_size`, `pat_total_fees`

---

## 10. Risk: partial-fill of one PAT leg

If we submit MarketBuy on Up and Down simultaneously but only one fills (book moves before second hits), we have single-side exposure.

**Mitigation logic**:
1. Use asyncio.gather with bounded timeout (e.g., 500ms)
2. If one side fails or times out: don't auto-cancel the filled side — let ACC-M maker logic try to rebalance via BID
3. Log the partial-fill event prominently

**Worst case**: we hold N shares of one side at avg cost $X. If we paid $0.45 × 20 = $9 and outcome is wrong, lose $9. Bounded.

**Frequency expected**: <5% of PAT fires partial-fill in normal conditions. Both sides usually have stable books for the few milliseconds we need.

---

## 11. Difference vs ACC-PC (the variant we previously planned)

| Aspect | ACC-PC (deferred) | PAT+ACC-M HYBRID (new) |
|---|---|---|
| Trigger | Only when imbalanced (one BID filled) | Whenever sum_asks + fees < $1.00 |
| Direction | Buy the LAGGING side only | Buy BOTH sides simultaneously |
| Profit mechanism | Complete a pair we partially have | Lock in arb on a cheap pair |
| Backtest PnL/slug | +$0.30-0.50 | **+$1.98** |
| Variance | Low | Medium |

PAT+ACC-M HYBRID is **strictly better** in backtest. ACC-PC remains in spec as optional 3rd strategy (deferred).

---

## 12. What this strategy does NOT cover

- Pure PAT without ACC-M base — fires too rarely to be useful alone (+$0.21-0.67/slug)
- Multi-asset (ETH, SOL) — Phase 2, after BTC validates
- Slug-selection signal (thin-book filtering) — backtest shows this HURTS, not helps
- Multi-leg taker (3+ assets simultaneously) — not validated

---

## 13. Bottom line

**Deploy PAT+ACC-M HYBRID at $200 seed as the primary strategy.** It's strictly better than ACC-M REV (+20% PnL) for the same operational complexity.

Expected:
- Backtest: +$1.98/slug × ~12 slugs/h × 14h = **$330/day theoretical**
- Realistic after live queue dynamics: **$50-150/day**
- Worst case daily drawdown: -$25
- Required validation: 48h shadow + 7d live monitor

---

## 14. Migration path from current ACC-M v1 spec

If TV agent has already started ACC-M v1 (POST_SIZE=5):

1. Stop work on v1 spec
2. Apply ACC-M REV changes (POST_SIZE=20, max_imbalance=10, wallet $200)
3. Add PAT overlay (this spec §4)
4. Proceed to shadow validation as PAT+ACC-M HYBRID

Total additional dev time: **4-6 hours** beyond ACC-M REV.

---

*See `PAT_FINDINGS_2026_05_19.md` for the data behind the PAT decision.*
*See `TV_AGENT_IMPLEMENTATION_DELTAS_2026_05_19.md` for the consolidated change list.*
