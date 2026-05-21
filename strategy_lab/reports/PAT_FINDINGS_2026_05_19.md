# PAT (Pair-Arb Taker) — backtest findings

**Date**: 2026-05-19
**Inspired by**: `0xcfb103c3` (xuanxuan008) — 90% taker, 99.8% paired, $2.5k/day per LB-API
**Backtest scope**: 87 slugs across 2 wallets (cfb=48, 04b6=39), 10 PAT variants

---

## TL;DR

**Pure PAT is marginal** (+$0.21 to +$0.67/slug across variants). The structural opportunity (sum_asks < $1.00 + taker fees) is too rare in BTC updown markets to drive meaningful PnL on its own.

**PAT+ACC-M HYBRID is the win**: +$1.98/slug average — **20% better than ACC-M alone** (+$1.65).

The reference wallet (xuanxuan008) likely makes their $2.5k/day from:
- Longer-window strategy (positions held + merged at end of slug, not immediate)
- Slug-selection signal (thin-book z=-17.86)
- We can't replicate them with immediate pair-arb-merge logic

**Recommended action**:
1. Deploy **PAT+ACC-M hybrid** as the upgrade to ACC-M REV (was sz=20, ACC-M-only)
2. Do NOT deploy pure PAT as standalone strategy — too few firing opportunities

---

## 1. Strategy logic implemented

```python
def check_pat(ss_up, ss_dn, cfg, ts_us, slot_start_us):
    # Need valid books on both sides
    if not (0 < ss_up.best_ask < 1 and 0 < ss_dn.best_ask < 1):
        return False
    # Rate limit: 5s between fires
    if (ts_us - max(ss_up.last_pat_fire_us, ss_dn.last_pat_fire_us)) < 5_000_000:
        return False
    # Don't fire in first 5s (let book stabilize)
    if (ts_us - slot_start_us) < 5_000_000:
        return False
    # Need book depth (avoid partial fills)
    if ss_up.ask_size_at_best < 5 or ss_dn.ask_size_at_best < 5:
        return False
    # === Edge filter (critical) ===
    fee_up = poly_taker_fee(ss_up.best_ask)
    fee_dn = poly_taker_fee(ss_dn.best_ask)
    pair_cost = ss_up.best_ask + ss_dn.best_ask + fee_up + fee_dn
    if pair_cost >= cfg.pat_max_pair_cost:
        return False  # not profitable
    return True

# When fires:
take_size = min(cfg.pat_take_size, ss_up.ask_size_at_best, ss_dn.ask_size_at_best)
# Market-buy both sides
ss_up.inv += take_size; ss_up.cost_paid += take_size * ask_up; ss_up.taker_fees += take_size * fee_up
ss_dn.inv += take_size; ss_dn.cost_paid += take_size * ask_dn; ss_dn.taker_fees += take_size * fee_dn
# IMMEDIATE MERGE — pair guaranteed
cash_recovered += take_size * 1.0
ss_up.inv -= take_size; ss_dn.inv -= take_size
```

---

## 2. Results

### 87-slug backtest (cfb=48, 04b6=39 slugs combined)

| Strategy | cfb_48 | 04b6_39 | Avg | Verdict |
|---|---|---|---|---|
| **PAT+ACC-M-sz20-c1.00** (hybrid) | **+$2.22** | **+$1.74** | **+$1.98** | ⭐ winner |
| ACC-M-sz20 (baseline) | +$1.81 | +$1.49 | +$1.65 | strong |
| PAT-sz100-c1.00 (large) | +$0.91 | +$0.42 | +$0.67 | marginal |
| PAT-sz50-c1.00 | +$0.66 | +$0.35 | +$0.50 | marginal |
| PAT-sz20-c1.00 | +$0.41 | +$0.25 | +$0.33 | weak |
| PAT-sz20-c99 | +$0.41 | +$0.23 | +$0.32 | weak |
| PAT-sz20-c1.00-thin500 | +$0.29 | +$0.19 | +$0.24 | thin-filter HURTS |
| PAT-sz20-c98 | +$0.35 | +$0.16 | +$0.25 | rare-fires |
| PAT-sz20-c97 (original) | +$0.28 | +$0.14 | +$0.21 | almost never fires |
| PAT-sz20-c1.01 | +$0.19 | -$0.17 | +$0.01 | loses money (fees > edge) |

### Interpretation

1. **Pure PAT is marginal** even at the most permissive threshold. The pair-cost rarely drops below $0.97-1.00 in BTC updown markets — both ask sides are usually structurally near $0.50 each.

2. **Hybrid (PAT + ACC-M) is the winner**. ACC-M's maker BIDs do most of the work (+$1.65/slug); PAT adds opportunistic taker grabs (+$0.33/slug) when both asks happen to dip simultaneously.

3. **Thin-book filter HURTS** PAT — taking with insufficient depth means partial fills + slippage. The reference wallet `0xcfb103c3` may use thin-book selection at a different layer (slug eligibility before any orders).

4. **Threshold $1.01 actively loses money** — pair_cost above $1 means we're paying more than we'll recover at merge. Even if it fires more, the EV is negative.

5. **Sizing helps**: PAT-sz100 makes ~3x PAT-sz20 ($0.67 vs $0.33). Bigger takes capture more volume per opportunity.

---

## 3. Why our PAT doesn't replicate xuanxuan008's $2.5k/day

Possible reasons:

### 3.1 They don't immediately merge

Their `merge_per_slug = 0.052` (near zero merges). Our PAT immediately merges every pair. They hold inventory longer — possibly until slug close, possibly via batch-merge router for many slugs at once.

Their actual flow might be:
1. Take cheap asks on one side or both
2. Accumulate inventory
3. At slug close, batch-merge OR redeem winning side
4. Profit from chainlink redemption (winner pays $1) PLUS accumulated cheap-cost basis

This is closer to **MAS pattern but via TAKER** — buy cheap shares early, sell or hold to settlement.

### 3.2 They have a slug-selection signal we don't have

Z=-17.86 on depth = they engage thin-book slugs. Thin books have wider gaps, easier to find sum_asks < $1.

But we tested `pat_max_book_depth_filter=500` (thin-book only) and PnL DROPPED. So that's not their secret either.

### 3.3 Their LB-API number might be inflated

LB-API 30d is `+$77k` for xuanxuan008. Over our 30-hour chain window, our true_pnl shows them LOSING $10k. They have huge variance. The $2.5k/day average might be 1-2 hot weeks dominating the rest.

If their actual run-rate is closer to break-even or +$500/day on $50k+ bankroll, our backtest +$0.30/slug × 200 slugs/day × scale factor would be in the right ballpark.

---

## 4. Concrete recommendation

### Replace ACC-M REV deployment with PAT+ACC-M HYBRID

Original spec (sz=5): +$0.37-0.73/slug
ACC-M REV (sz=20): +$1.25 to +$1.81/slug
**PAT+ACC-M HYBRID (sz=20, pat_c=1.00)**: **+$1.74 to +$2.22/slug**

PAT+ACC-M HYBRID is strictly better than ACC-M alone (+$0.33/slug uplift, no downside) at the same wallet seed.

### Configuration

```python
PAT_ACCM_HYBRID = {
    # ACC-M base (post BIDs both sides)
    "POST_SIZE": 20,
    "MIN_BID_PRICE": 0.05,
    "MAX_BID_PRICE": 0.95,
    "MAX_SUM_BIDS": 1.00,
    "CANCEL_THRESHOLD": 0.03,
    "MAX_ORDER_AGE_S": 20,
    "MERGE_THRESHOLD_PAIRS": 5,
    "MAX_IMBALANCE_SHARES": 10,
    "ABSOLUTE_MAX_INVENTORY": 100,

    # PAT taker overlay
    "enable_pat": True,
    "pat_take_size": 20,
    "pat_max_pair_cost": 1.00,         # critical: above this loses money
    "pat_min_s_between_fires": 5,
    "pat_max_fires_per_slug": 10,
    "pat_min_book_depth_each_side": 5,
    "pat_min_time_after_open_s": 5,
    # NO thin-book filter — it hurts performance
}
```

---

## 5. Implementation deltas for TV agent

If TV agent has already started implementing ACC-M, the PAT-overlay is a small addition:

1. **Add taker buy capability** on both sides simultaneously (most maker bots only post — add ability to issue MarketBuy orders)
2. **Track top-of-book ask size** for both Up and Down (already in BookMirror)
3. **Add the `check_pat` function** (50 lines) called on every L25Update
4. **Add immediate merge after PAT fire** (already have merge logic from ACC-M)
5. **Add taker_fees to PnL accounting** (separate from maker_rebates)

Estimated dev time: **+4 hours on top of ACC-M REV**.

If TV agent has ACC-M REV deployed and working, adding PAT overlay is a config change + 50 lines of code + 1 test.

---

## 6. PAT-only deployment NOT recommended

Even at best (PAT-sz100-c1.00 = +$0.67/slug), pure PAT is 2.5x worse than ACC-M alone. There's no point in running pure-PAT as a standalone strategy.

**The only deployable PAT variant is PAT+ACC-M HYBRID.** Treat PAT as a feature flag added to ACC-M, not as its own strategy.

---

## 7. Where might PURE PAT work?

Speculation: PAT might work better in:
- **Higher-spread markets** — sports markets where sum_asks regularly drops below $1.00
- **Less liquid markets** — where temporary dislocations create > 3¢ gaps
- **Multi-asset routing** — if we monitor BTC + ETH + SOL simultaneously, more chances to find a dislocation any given second

But that's research, not deployment. For BTC 5m updown markets, PAT alone isn't profitable enough.

---

## 8. Recommendation summary

| Strategy | Deploy? | Why |
|---|---|---|
| PAT+ACC-M HYBRID | ✅ YES | +$1.98/slug — best variant in 87-slug test |
| Pure PAT | ❌ NO | +$0.21-$0.67/slug — too rare-firing |
| PAT with thin-book filter | ❌ NO | Actually HURTS PAT performance |
| PAT at threshold > $1.00 | ❌ NO | Loses money on fees |

**Replace ACC-M REV deployment with PAT+ACC-M HYBRID. Same wallet seed, +20% PnL.**

---

*See `STRATEGY_REVISION_2026_05_19.md` for original strategy revision context.*
*See `OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md` for full 213-slug backtest data.*
