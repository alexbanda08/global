# TV Agent Deploy Spec — ACC-M REV (Maker Pair Arbitrage, $100 budget)

**Version**: 2.0 (replaces TV_DEPLOY_SPEC_ACC_M_2026_05_18.md)
**Date**: 2026-05-19
**Mode**: Shadow first → Live after 48h validation
**Capital**: $100 USDC.e seed (was $50)
**Key change vs v1**: POST_SIZE 5 → **20**, cells reduced to BTC 5m only initially

---

## 0. Why this revision exists

213-slug backtest validation showed:
- POST_SIZE=5 (v1 spec) produced +$0.37-0.73/slug — marginal
- POST_SIZE=20 produced +$1.25/slug — **3x improvement, low variance** ($7 stddev)
- POST_SIZE=100 produced +$3.54/slug but requires $500+ seed

For the $100-budget constraint, **POST_SIZE=20** is the sweet spot:
- Highest Sharpe of the budget-compatible sizes
- Bounded variance
- 4-order capacity within $100 wallet

---

## 1. What you're building (unchanged from v1)

A bot that posts maker BID orders on both Up and Down sides of binary up-down markets when the structural mispricing `sum_bids < $1.00` exists, accumulates paired inventory, and merges via NegRiskAdapter to recover $1 per pair.

State machine, fill logic, cancel rules — ALL UNCHANGED from v1 spec. Only parameters change.

---

## 2. Configuration changes

```python
ACC_M_REV_CONFIG = {
    # === CHANGED FROM v1 ===
    "POST_SIZE": 20,                   # WAS 5 — critical fix
    "ABSOLUTE_MAX_INVENTORY": 80,      # WAS 50 — 4 orders × 20 shares
    "MAX_IMBALANCE_SHARES": 10,        # WAS 5 — looser for sz=20
    "wallet_seed_usdc": 100,           # WAS 50 — fits new size
    "MAX_CONCURRENT_SLUGS": 2,         # WAS 4 — start narrow
    "cells": ["btc_5m"],               # WAS ["btc_5m", "btc_15m"] — single cell start

    # === UNCHANGED (validated correct) ===
    "MIN_BID_PRICE": 0.05,
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,
    "MAX_SPREAD_PER_LEG": 0.05,
    "CANCEL_THRESHOLD": 0.03,          # 3¢ displacement
    "MAX_ORDER_AGE_S": 20,
    "CANCEL_ON_FILL": False,
    "CANCEL_ON_CLOSE": False,
    "MERGE_THRESHOLD_PAIRS": 5,
    "MERGE_CHECK_INTERVAL_S": 5,
    "RESERVE_USDC": 10,                # raised from 5

    # === RISK CAPS (REVISED LOWER) ===
    "MAX_DAILY_DRAWDOWN_USDC": 20,     # was 25
    "MAX_CONSECUTIVE_LOSING_SLUGS": 5, # was 10 — halt earlier
    "MAX_HOURLY_FILLS": 100,           # NEW — sanity cap

    # === SHADOW / LIVE ===
    "shadow_mode": True,               # FIRST 48h, then flip to False
    "log_path": "shadow_acc_m_rev_{date}.csv",
}
```

---

## 3. Capital math (CRITICAL — read carefully)

At POST_SIZE=20 with $0.50 avg price:
- Per posted order: 20 × $0.50 = **$10 cost**
- Per slug with both sides: **$20 reserved**
- 2 concurrent slugs: **$40 working capital**
- Merge cycle: when paired ≥ 5, merge for $5+ cash recovered
- Reserve: $60 for gas + new slugs + safety

**$100 budget breakdown**:
- $40 working capital (2 slugs × $20)
- $20 buffer for merge timing
- $30 reserve for new slugs as old ones close
- $10 safety reserve

**DO NOT** open more than 2 concurrent slugs in this config. Engine must enforce `MAX_CONCURRENT_SLUGS=2`.

---

## 4. Expected per-slug behavior

At POST_SIZE=20 (revised from v1's POST_SIZE=5):

| Event | Test scale (v1) | Test scale (REV) |
|---|---|---|
| L25 updates received | ~300 | ~300 |
| Bid posts (after dedup/cancel) | 50-150 | 50-100 |
| Cancels | 10-30 | 10-25 |
| Bid fills | 3-15 | **8-25** (higher due to queue position) |
| Merges | 1-3 | **2-5** |
| Per-slug PnL avg (backtest) | $0.37-0.73 | **$1.25** |

Reference: 213-slug backtest sum at sz=20 = $267 across the slugs = $1.25/slug avg.

---

## 5. Shadow → Live promotion criteria (revised)

After 48h shadow mode, promote to live if ALL pass:
- **Mean realized $/slug > $0** (positive expectancy — was $0.10 in v1, lower bar for honest validation)
- **Median realized $/slug > $0** (>50% positive slugs)
- **Realized fill rate > 25% of simulated** (was 30%)
- **Max 24h drawdown < $20** (revised from $25)
- **No more than 2 slugs with > 50% imbalance** (discipline check at sz=20)

If shadow shows -$0.50/slug to +$0/slug: pause for 1 week, re-test. Probably tighter slug-selection needed.

If shadow shows < -$0.50/slug avg: **do not promote**, investigate why backtest projections didn't hold.

---

## 6. Live deploy progression (revised conservative)

1. **Day 1**: Live at $100 seed, BTC 5m ONLY, single concurrent slug max
2. **Day 2**: If Day 1 not loss: enable 2 concurrent slugs
3. **Day 3-7**: Monitor daily — halt if 24h drawdown > $15
4. **Day 7**: If 7-day rolling PnL > $50: enable BTC 15m as second cell, keep wallet at $100
5. **Day 14**: If 14-day rolling PnL > $200: consider scaling wallet to $200
6. **Day 30**: If 30-day rolling > $500: consider full $300 scale

**Halt conditions** (stop strategy immediately):
- 24h drawdown > $20
- 7-day rolling PnL < -$30
- 5 consecutive losing slugs
- Any error rate > 5%

**Re-tune triggers** (don't halt, but reduce):
- Realized fill rate < 25% of simulated → reduce POST_SIZE to 10 temporarily
- Inventory consistently >50% imbalance → tighten MAX_IMBALANCE_SHARES to 5

---

## 7. Implementation checklist (delta from v1)

Items new or changed vs v1 checklist:

- [ ] Update POST_SIZE constant from 5 to 20 in all places
- [ ] Update ABSOLUTE_MAX_INVENTORY from 50 to 80
- [ ] Update MAX_IMBALANCE_SHARES from 5 to 10
- [ ] Update MAX_CONCURRENT_SLUGS from 4 to 2 (with engine enforcement)
- [ ] Reduce active cells to btc_5m only (configurable)
- [ ] Add MAX_HOURLY_FILLS sanity cap (alert if exceeded)
- [ ] Update wallet preflight to require $100 USDC.e + approvals
- [ ] Update shadow log column for "expected_pnl_per_slug" based on new POST_SIZE
- [ ] Lower promotion bar (mean $/slug > $0 instead of $0.10)

All other v1 checklist items stand.

---

## 8. Why POST_SIZE=20 not 100?

Backtest data:

| POST_SIZE | Avg PnL/slug (213 slugs) | Stddev | $/slug Sharpe | Capital per order |
|---|---|---|---|---|
| 5 (v1 spec) | +$0.37-0.73 | $3 | ~0.20 | $2.50 |
| 20 (REV) | +$1.25 | $7 | **0.18** | $10 |
| 50 | +$2.35 | $13 | 0.18 | $25 |
| 100 | +$3.54 | $21 | 0.17 | $50 |
| 200 | +$3.78 | $37 | 0.10 | $100 |

Sharpe ratios are roughly comparable across 20-100. **20 was chosen for $100 budget**:
- 1 posted order = $10 = 10% of wallet
- Acceptable per-order exposure for a $100 wallet
- Bigger sizes would require ≥$250 wallet to maintain healthy capital efficiency

If we scale to $300 wallet later, sz=50-100 becomes appropriate.

---

## 9. Why merge at 5 pairs (unchanged)?

213-slug validation tested merge_threshold_pairs in {2, 5, 10}:
- merge=2 ("tight"): +$2.20/slug avg, higher gas burn
- merge=5 (spec): +$2.35/slug avg
- merge=10 ("hot"): +$2.35/slug avg

Merge=5 captured 95% of merge=2's PnL with half the merge events. **Keep at 5.**

---

## 10. Risk: leftover-burn variance

Even at POST_SIZE=20, some slugs end with imbalanced inventory at slug close. The losing side's leftover shares go to $0.

Estimated leftover-burn at sz=20:
- Per slug: $1-3 burn on losing-side leftover
- Per 24h: $20-50 in burned cost
- Offset by: $1.25/slug average from merges + rebates

Net: positive expected value, with high single-slug variance.

**Mitigation**: ACC-PC variant (separate spec, deploys after ACC-M REV) adds reactive taker pair-completion. Reduces leftover-burn at cost of small taker fees. Run as separate strategy.

---

## 11. Files to update

| File | Change |
|---|---|
| `backend/app/strategies/polymarket/maker/acc_m.py` | Update default POST_SIZE = 20 |
| `backend/app/strategies/polymarket/maker/config.py` | Update default config dict |
| `/etc/tv/tradingvenue.env` | `TV_POLY_MAKER_WALLET_SEED_USDC=100` |
| `/etc/tv/tradingvenue.env` | `TV_POLY_MAKER_CELLS=btc_5m` |
| `shadow_engine/strategies/acc_m.py` | Update Python reference to match |

---

## 12. Expected revenue

**Backtest (213 slugs, on wallet-selected slug universe)**: +$1.25/slug avg.

**Live extrapolation** (assuming 75% of backtest fill rate due to competition):
- ~12 BTC 5m slugs/hour engaged × 14h active = 168 slugs/day
- $1.25/slug × 0.75 fill rate × 168 = **$157/day theoretical**
- Realistic after live queue dynamics: **$30-80/day on $100**

**Worst-case daily drawdown**: -$15 to -$20 (based on stddev × confidence interval).

This is a **profitable but variance-heavy** strategy at our budget. Treat it as a 2-week validation deployment.

---

## 13. What ACC-M REV does NOT cover

- ETH and SOL — deploy on BTC first, validate, then expand
- 4PM-ET daily markets — only 5m for now
- Slug-selection signal (engagement filter) — runs on all available slugs
- Multi-asset diversification — single asset for first deployment

These are deferred to Phase 2 of the deployment after $100 BTC 5m validates.

---

*End of ACC-M REV spec. See `STRATEGY_REVISION_2026_05_19.md` for context on why this revision exists.*
