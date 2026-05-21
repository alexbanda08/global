# TV Agent — Strategies to implement (shadow mode)

**Date**: 2026-05-19
**Mode**: SHADOW ONLY for all strategies. No live capital yet. Goal: engine validation + bug catching.

Apply the changes below to what you've already implemented, plus add the 2 new shadow sleeves at the end.

---

## 1. ACC-M — modify (becomes "PAT+ACC-M HYBRID")

Change these parameters:

| Param | Old | New |
|---|---|---|
| `POST_SIZE` | 5 | **20** |
| `MAX_IMBALANCE_SHARES` | 5 | **10** |
| `ABSOLUTE_MAX_INVENTORY` | 50 | **100** |
| `MAX_CONCURRENT_SLUGS` | 4 | **3** |
| `cells` | btc_5m, btc_15m | **btc_5m only** (start) |
| `MAX_DAILY_DRAWDOWN_USDC` | 25 | **30** |

**Add PAT taker overlay** (new):

```python
# Add to config
"enable_pat": True,
"pat_take_size": 20,
"pat_max_pair_cost": 1.00,
"pat_min_s_between_fires": 5,
"pat_max_fires_per_slug": 10,
"pat_min_book_depth_each_side": 5,
"pat_min_time_after_open_s": 5,
```

**Add PAT trigger function** (call on every L25Update after existing maker logic):

```python
def check_pat_trigger(ss_up, ss_dn, cfg, ts_us, slot_start_us):
    if not (0 < ss_up.best_ask < 1 and 0 < ss_dn.best_ask < 1):
        return False
    last_fire = max(ss_up.last_pat_fire_us, ss_dn.last_pat_fire_us)
    if (ts_us - last_fire) < cfg.pat_min_s_between_fires * 1_000_000:
        return False
    if ss_up.n_pat_fires >= cfg.pat_max_fires_per_slug:
        return False
    if (ts_us - slot_start_us) < cfg.pat_min_time_after_open_s * 1_000_000:
        return False
    if ss_up.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False
    if ss_dn.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False
    fee_up = poly_taker_fee_per_share(ss_up.best_ask)
    fee_dn = poly_taker_fee_per_share(ss_dn.best_ask)
    pair_cost = ss_up.best_ask + ss_dn.best_ask + fee_up + fee_dn
    if pair_cost >= cfg.pat_max_pair_cost or pair_cost <= 0:
        return False
    if ss_up.inv >= cfg.absolute_max_inv or ss_dn.inv >= cfg.absolute_max_inv:
        return False
    return True


async def execute_pat_fire(slug, ss_up, ss_dn, cfg):
    take_size = min(cfg.pat_take_size,
                     ss_up.ask_size_at_best,
                     ss_dn.ask_size_at_best)
    if take_size < 5:
        return
    # Submit BOTH market buys in parallel (critical for arb)
    up_task = asyncio.create_task(
        client.market_buy(slug, "Up", ss_up.best_ask, take_size))
    dn_task = asyncio.create_task(
        client.market_buy(slug, "Down", ss_dn.best_ask, take_size))
    up_result, dn_result = await asyncio.gather(
        up_task, dn_task, return_exceptions=True)
    up_filled = up_result.filled_size if not isinstance(up_result, Exception) else 0
    dn_filled = dn_result.filled_size if not isinstance(dn_result, Exception) else 0
    ss_up.inv += up_filled
    ss_dn.inv += dn_filled
    # Track cost, fees as you do for any taker fill
    ss_up.n_pat_fires += 1
    ss_dn.n_pat_fires += 1
    ss_up.last_pat_fire_us = ts_us
    ss_dn.last_pat_fire_us = ts_us
    # Immediate merge if BOTH legs filled
    pairs = min(up_filled, dn_filled)
    if pairs >= 1:
        await merger.merge_pairs(slug, pairs)
        ss_up.inv -= pairs
        ss_dn.inv -= pairs


# In L25Update handler, after existing maker logic:
if cfg.enable_pat:
    if check_pat_trigger(ss_up, ss_dn, cfg, ts_us, slot_start_us):
        asyncio.create_task(execute_pat_fire(slug, ss_up, ss_dn, cfg))
```

**Add to SideState**:
```python
n_pat_fires: int = 0
last_pat_fire_us: int = 0
```

**Add to client interface** (if not already there):
```python
async def market_buy(self, slug, side, price, size) -> FillResult
```

**Shadow log additions**: `pat_check_passed`, `pat_pair_cost`, `pat_fire_size`, `pat_fees_total`

---

## 2. MAS — modify

Change these parameters:

| Param | Old | New |
|---|---|---|
| `cells` | 6 (btc/eth/sol × 5m/15m) | **2 (btc_5m + btc_15m only)** |
| `MAX_CONCURRENT_SLUGS` | 6 | **2** |
| `MAX_DAILY_DRAWDOWN_USDC` | 30 | **20** |

Everything else (POST_SIZE=5, PRE_MINT_USDC=30, MIN_SUM_ASKS=1.005, cancel rules) **unchanged**.

---

## 3. ACC-H — modify (add per-rule logging)

Keep all V3f composite taker logic as-is. **Add per-rule decision logging** so we can analyze which of the 4 rules (A/B/C/D) would have produced positive PnL:

```python
# In V3f trigger check, log every decision (not just fires):
LogTakerDecision(
    ts_us, slug, side,
    rule_evaluated,     # "A" | "B" | "C" | "D" | "none"
    outcome,            # "WOULD_FIRE" | "skip_inv_cap" | "skip_rate_limit"
                        # | "skip_per_slug_cap" | "no_trigger"
    current_ask,
    median_60s_ask,
    max_5s_trade,
    buy_vol_60s,
    offset_s,
    inv_up, inv_dn,
)
```

After each slug resolves, retroactively compute the **simulated PnL** for each WOULD_FIRE event (assume fee at current ask, hold to slug close, redeem winner at $1).

Log all of this to a daily CSV.

---

## 4. NEW SHADOW SLEEVE: ACC-PC (Pair-Completion Taker)

New strategy module. Inherits ACC-M maker logic. Adds a reactive taker overlay (fires only when imbalanced).

```python
ACC_PC_CONFIG = {
    # Inherit ACC-M with these mods:
    "POST_SIZE": 20,
    "MAX_IMBALANCE_SHARES": 20,         # looser — taker rebalances
    "ABSOLUTE_MAX_INVENTORY": 100,
    "MAX_CONCURRENT_SLUGS": 2,
    "RESERVE_USDC": 15,

    # ACC-PC additions
    "enable_pc_taker": True,
    "pc_taker_size": 20,
    "pc_max_pair_cost": 0.97,
    "pc_min_time_before_taker_s": 30,
    "pc_min_spread_to_taker": 0.02,
    "pc_cvd_threshold": 0.0,
    "pc_max_taker_per_slug": 5,
    "pc_min_s_between_taker_s": 5,

    "cells": ["btc_15m"],               # different cell than PAT+ACC-M
}
```

**Trigger logic** (runs on every L25Update):

```python
def check_pc_taker(state, cfg, ts_us, slot_start_us):
    """Reactive pair-completion: fire ONLY when imbalanced AND profitable."""
    imbalance = abs(state.inv_up - state.inv_dn)
    if imbalance < 1.0:
        return None

    if state.inv_up < state.inv_dn:
        lag, lead = state.up_side, state.dn_side
    else:
        lag, lead = state.dn_side, state.up_side

    # Rate + time limits
    elapsed_s = (ts_us - slot_start_us) / 1_000_000
    if elapsed_s < cfg.pc_min_time_before_taker_s:
        return None
    if lag.n_pc_taker >= cfg.pc_max_taker_per_slug:
        return None
    if (ts_us - lag.last_pc_taker_us) < cfg.pc_min_s_between_taker_s * 1_000_000:
        return None
    if not (0 < lag.best_ask < 1):
        return None
    if lag.inv >= cfg.absolute_max_inv:
        return None

    # Edge filter: pair cost must be < 0.97
    avg_lead_cost = lead.cost_paid / lead.inv
    fee = poly_taker_fee_per_share(lag.best_ask)
    pair_cost = avg_lead_cost + lag.best_ask + fee
    if pair_cost >= cfg.pc_max_pair_cost:
        return None

    # Spread filter: don't take if our BID is close to ask
    if lag.open_bid_price is not None:
        if (lag.best_ask - lag.open_bid_price) <= cfg.pc_min_spread_to_taker:
            return None

    # CVD filter: only fire when buyer pressure on lagging side
    cvd_30s = sum(d for _, d in lag.cvd_window)
    if cvd_30s <= cfg.pc_cvd_threshold:
        return None

    return MarketBuy(slug=state.slug, side=lag.side, price=lag.best_ask,
                      size=min(cfg.pc_taker_size, imbalance))
```

**Add to SideState**:
```python
n_pc_taker: int = 0
last_pc_taker_us: int = 0
cvd_window: deque = field(default_factory=deque)  # 30s rolling (ts, signed_size)
```

**Update CVD on every TradePrint**:
```python
delta = trade.size if trade.side == "BUY" else -trade.size
side_ss.cvd_window.append((ts_us, delta))
# Evict entries older than 30s
```

**Shadow logging**: log every PC check (fires + skips) with reason.

---

## 5. NEW SHADOW SLEEVE: PAT-SHADOW (research only)

Pure PAT (no ACC-M base) with permissive thresholds. Just to see how often the trigger fires at relaxed parameters.

```python
PAT_SHADOW_CONFIG = {
    "strategy_code": "PAT-SHADOW",
    "POST_SIZE": 0,                     # NO maker BIDs
    "enable_pat": True,
    "pat_take_size": 20,
    "pat_max_pair_cost": 1.02,          # permissive (vs PAT+ACC-M's 1.00)
    "pat_min_s_between_fires": 3,
    "pat_max_fires_per_slug": 30,
    "pat_min_book_depth_each_side": 5,
    "pat_min_time_after_open_s": 5,

    "cells": ["btc_5m"],
}
```

Uses the same PAT trigger function as PAT+ACC-M HYBRID (§1), just with different parameters.

Shadow log every check + would-be fire.

---

## 6. Cell assignments (no two strategies on the same cell)

| Strategy | Cell |
|---|---|
| PAT+ACC-M HYBRID | btc_5m |
| MAS | btc_5m + btc_15m |
| ACC-H | btc_5m + btc_15m |
| ACC-PC | btc_15m |
| PAT-SHADOW | btc_5m |

All shadow — they don't actually compete on the book.

---

## 7. What stays unchanged

All infrastructure work from the 2026-05-18 deployment plan:
- Ireland VPS, BookMirror, PolymarketClient
- Performance requirements P1-P10
- Allowance preflight, live_gate (won't trigger in shadow but keep wired)
- NegRiskAdapter merger, CTF splitter (for MAS)
- Cancel rules (3¢ displacement / 20s age)
- CLOB minimum order (5 shares)

---

## 8. Summary

**3 modifications to existing strategies**:
1. ACC-M → add PAT overlay + resize POST_SIZE 5→20
2. MAS → reduce 6 cells to 2 cells
3. ACC-H → add per-rule decision logging

**2 new shadow sleeves to add**:
1. ACC-PC — pair-completion taker (inherits ACC-M)
2. PAT-SHADOW — pure PAT with permissive thresholds (research)

**All 5 run in shadow mode.** Goal for this phase: validate engine behavior, catch bugs, collect decision-data per strategy. No live capital.

Once shadow runs cleanly for 7+ days with no engine errors, we'll review the data and decide which to promote first.
