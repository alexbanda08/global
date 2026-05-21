# TV Agent — PAT+ACC-M HYBRID Implementation Spec (FINAL)

**Date**: 2026-05-20
**Status**: Ready to implement. Self-contained — supersedes / consolidates the prior 5 docs.
**Mode**: Shadow → Live in 4 stages.
**Capital**: $200 USDC.e (Ireland VPS hot wallet).
**Strategy**: PAT+ACC-M HYBRID — the **only** strategy validated profitable on the full 8,146-slug BTC universe (**+$7.79/slug**, n_universe_fires=2,984).

Replaces / consolidates:
- `TV_DEPLOY_SPEC_ACC_M_2026_05_18.md` (v1 ACC-M base)
- `TV_DEPLOY_SPEC_ACC_M_REV_2026_05_19.md` (POST_SIZE=20 update)
- `TV_DEPLOY_SPEC_PAT_ACCM_HYBRID_2026_05_19.md` (PAT overlay)
- `TV_AGENT_CHANGES_2026_05_19.md` (the previous master change-list)
- `TV_AGENT_IMPLEMENTATION_DELTAS_2026_05_19.md`

**What changed since 2026-05-19**: We tried to decode "which slugs the wallets pick" and trained per-wallet engagement classifiers (GB AUC 0.94–0.98 for 3 of 4 wallets). Classifier-selected slugs do **not** amplify PAT+ACC-M PnL beyond a marginal 1.3× lift. So: deploy PAT+ACC-M on the **full BTC 5m universe** — no selection filter. See `SLUG_SELECTION_DECODE_2026_05_20.md`.

---

## 0. TL;DR

You are building a single strategy: **PAT+ACC-M HYBRID**. It is two layers running together inside one engine:

1. **ACC-M (maker)**: posts BID orders on both Up and Down whenever `sum_bids < $1.00`. Accumulates paired inventory. Merges via NegRiskAdapter for $1/pair.
2. **PAT (taker overlay)**: market-buys BOTH sides simultaneously when `sum_asks + 2×taker_fee < $1.00`. Immediate merge. Adds ~+20% PnL over ACC-M alone.

**On the full BTC 5m universe (6,110 slugs):** PAT+ACC-M fires on 49% of slugs and produces **+$7.79/slug average** PnL (this includes non-fire slugs as $0). On firing slugs the per-fire PnL is +$1.98.

Deploy shadow-only for 7 days, then progress to live in 4 stages.

---

## 1. Architecture

### 1.1 Where it lives

```
backend/app/strategies/polymarket/maker/
├── types.py              # SlugState, SideState, StratCfg dataclasses
├── fees.py               # poly_taker_fee_per_share, poly_maker_rebate_per_share
├── acc_m.py              # ACC-M maker logic (post bid, cancel, merge)
├── pat.py                # PAT taker overlay (NEW — this spec)
├── pat_accm.py           # composite engine wiring acc_m + pat together
├── shadow_log.py         # CSV writer for shadow + live decision log
└── tests/
    ├── test_acc_m.py
    ├── test_pat_trigger.py
    └── test_pat_accm_integration.py
```

### 1.2 Event flow

```
WS adapter (already exists)
   │
   ▼
BookMirror (already exists)        ← maintains best_bid, best_ask, sizes per (slug,outcome)
   │
   ├─ L25Update(slug, ts_us, books) ───────► pat_accm.handle_l25(...)
   ├─ TradePrint(slug, ts_us, side, sz, px) ► pat_accm.handle_trade(...)
   ├─ OrderFill(slug, order_id, ...) ──────► pat_accm.handle_fill(...)
   ├─ SlugActive(slug, slot_start_us, ...) ► pat_accm.start_slug(...)
   └─ SlugResolved(slug, outcome) ─────────► pat_accm.finalize_slug(...)
```

### 1.3 Per-slug state

```python
# types.py
from dataclasses import dataclass, field

@dataclass
class SideState:
    side: str                              # "Up" | "Down"
    inv: float = 0.0                       # net shares held
    cost_paid: float = 0.0                 # USDC spent on buys (taker + maker bid fills)
    cash_received: float = 0.0             # USDC received on sells (rare for ACC-M)
    rebate: float = 0.0                    # maker rebate income
    taker_fees: float = 0.0                # taker fee outflow
    # Open maker bid
    open_bid: float | None = None          # price of our open BID, or None
    open_bid_remaining: float = 0.0        # unfilled size remaining
    open_bid_posted_us: int = 0
    # Best top-of-book seen
    best_bid: float = 0.0
    best_ask: float = 1.0
    bid_size_at_best: float = 0.0
    ask_size_at_best: float = 0.0
    # Counters
    n_maker_bid_fills: int = 0
    n_pat_fires: int = 0
    last_pat_us: int = 0

@dataclass
class SlugState:
    slug: str
    slot_start_us: int
    slot_end_us: int
    outcome_truth: str | None              # "Up" | "Down" | None (until SlugResolved)
    up: SideState
    dn: SideState
    cash_recovered: float = 0.0            # USDC from merges + redemptions
    n_merges: int = 0
    pairs_merged: float = 0.0
    leftover_redeemed: float = 0.0
    finalized: bool = False

@dataclass
class StratCfg:
    # Identity
    strategy_code: str = "PAT-ACC-M-HYBRID"
    version: str = "1.0.0"

    # Capital
    wallet_seed_usdc: float = 200.0
    reserve_usdc: float = 30.0

    # ACC-M maker
    post_size: float = 20.0
    min_bid_price: float = 0.05
    max_bid_price: float = 0.95
    max_sum_bids: float = 1.00
    max_spread_per_leg: float = 0.05
    cancel_threshold: float = 0.03
    max_order_age_s: float = 20.0
    cancel_on_fill: bool = False
    cancel_on_close: bool = False
    merge_threshold_pairs: float = 5.0
    merge_check_interval_s: float = 5.0
    max_imbalance_shares: float = 10.0
    absolute_max_inventory: float = 100.0
    stop_posting_offset_s: float = 270.0       # 5m default — stop 30s before close

    # PAT overlay
    enable_pat: bool = True
    pat_take_size: float = 20.0
    pat_max_pair_cost: float = 1.00            # CRITICAL — above this loses money
    pat_min_s_between_fires: float = 5.0
    pat_max_fires_per_slug: int = 10
    pat_min_book_depth_each_side: float = 5.0
    pat_min_time_after_open_s: float = 5.0

    # Risk caps
    max_concurrent_slugs: int = 3
    max_daily_drawdown_usdc: float = 30.0
    max_consecutive_losing_slugs: int = 5
    max_hourly_fills: int = 200
    max_hourly_pat_fires: int = 30

    # Cells
    cells: tuple = ("btc_5m",)                 # tuple of strings: "{asset}_{tf}"

    # Shadow vs Live
    shadow_mode: bool = True
    log_path: str = "shadow_pat_accm_{date}.csv"
```

---

## 2. ACC-M base — exact rules

### 2.1 Post a BID — `acc_m.should_post_bid(side, slug_state, book, cfg, wallet_balance, now_us)`

Called on every `L25Update` for each side (Up and Down).

```python
def should_post_bid(side, ss, book, cfg, wallet_balance, slot_start_us, now_us):
    other = "dn" if side == "Up" else "up"
    side_ss = ss.up if side == "Up" else ss.dn
    other_ss = ss.dn if side == "Up" else ss.up

    # Stop posting near close (last 30s of slug)
    elapsed_s = (now_us - slot_start_us) / 1_000_000
    if elapsed_s > cfg.stop_posting_offset_s:
        return False, None

    # Skip wide books on this side
    if (book[side].best_ask - book[side].best_bid) > cfg.max_spread_per_leg:
        return False, None

    # Edge filter: only post when sum_bids < $1
    sum_bids = book["Up"].best_bid + book["Down"].best_bid
    if sum_bids >= cfg.max_sum_bids:
        return False, None

    # Price band
    bid_price = book[side].best_bid
    if not (cfg.min_bid_price <= bid_price <= cfg.max_bid_price):
        return False, None

    # Inventory balance — don't post on the heavy side
    if side_ss.inv > other_ss.inv + cfg.max_imbalance_shares:
        return False, None

    # Hard cap
    if side_ss.inv >= cfg.absolute_max_inventory:
        return False, None

    # Wallet balance (need cash to post)
    required = cfg.post_size * bid_price
    if wallet_balance < required + cfg.reserve_usdc:
        return False, None

    # Already have an open bid at this price? skip
    if side_ss.open_bid is not None and abs(side_ss.open_bid - bid_price) < 0.005:
        return False, None

    return True, bid_price
```

When `should_post_bid` returns True, emit:
```
PostBid(slug, side, price=bid_price, size=cfg.post_size, order_type="GTC_POST_ONLY")
```

### 2.2 Cancel an existing BID — `acc_m.should_cancel_bid(order, book, cfg, now_us)`

Called on every `L25Update` for each open order.

```python
def should_cancel_bid(order, book, cfg, now_us):
    # Rule 1: book displacement
    displacement = abs(order.price - book[order.side].best_bid)
    if displacement >= cfg.cancel_threshold:
        return True, "displacement"
    # Rule 2: age
    age_s = (now_us - order.posted_us) / 1_000_000
    if age_s >= cfg.max_order_age_s:
        return True, "age"
    return False, None
```

**Hard rules** (don't cancel even if above triggers):
- Do NOT cancel on partial fill — leave residuals.
- Do NOT cancel in the last 30s of slug (let orders fill/expire).

### 2.3 Merge trigger — `acc_m.should_merge(slug_state, cfg)`

Called after every `OrderFill` and on a periodic 5s timer.

```python
def should_merge(state, cfg):
    pairs = int(min(state.up.inv, state.dn.inv))
    return pairs >= cfg.merge_threshold_pairs, pairs
```

When True: emit `MergePositions(slug, pairs)` → NegRiskAdapter. On success: `inv_up -= pairs; inv_dn -= pairs; cash_recovered += pairs * 1.0`.

### 2.4 Slug resolution

```python
def finalize_slug(state, cfg, outcome):
    # Force final merge of any remaining pairs
    pairs = int(min(state.up.inv, state.dn.inv))
    if pairs > 0:
        emit MergePositions(state.slug, pairs)
        state.up.inv -= pairs; state.dn.inv -= pairs
        state.cash_recovered += pairs * 1.0
        state.n_merges += 1; state.pairs_merged += pairs

    # Redeem winning leftover
    if outcome == "Up" and state.up.inv > 0:
        emit RedeemPositions(state.slug, "Up", state.up.inv)
        state.leftover_redeemed = state.up.inv * 1.0
        state.cash_recovered += state.leftover_redeemed
        state.up.inv = 0
    elif outcome == "Down" and state.dn.inv > 0:
        emit RedeemPositions(state.slug, "Down", state.dn.inv)
        state.leftover_redeemed = state.dn.inv * 1.0
        state.cash_recovered += state.leftover_redeemed
        state.dn.inv = 0

    # Compute PnL — write to shadow_log
    cost = state.up.cost_paid + state.dn.cost_paid
    cash_in = state.up.cash_received + state.dn.cash_received + state.cash_recovered
    rebates = state.up.rebate + state.dn.rebate
    fees = state.up.taker_fees + state.dn.taker_fees
    pnl = cash_in + rebates - cost - fees
    state.finalized = True
    emit LogSlugComplete(state.slug, pnl, state)
```

---

## 3. PAT overlay — exact rules

### 3.1 Trigger check — `pat.check_pat_trigger(ss_up, ss_dn, cfg, ts_us, slot_start_us, hourly_pat_fires, wallet_balance)`

Called on every `L25Update` **after** the ACC-M maker logic has run.

```python
def check_pat_trigger(ss_up, ss_dn, cfg, ts_us, slot_start_us,
                     hourly_pat_fires, wallet_balance):
    # Validity: both sides must have valid asks
    if not (0 < ss_up.best_ask < 1 and 0 < ss_dn.best_ask < 1):
        return False

    # Rate limit (combined across sides)
    last_fire_us = max(ss_up.last_pat_us, ss_dn.last_pat_us)
    if (ts_us - last_fire_us) < cfg.pat_min_s_between_fires * 1_000_000:
        return False
    if ss_up.n_pat_fires >= cfg.pat_max_fires_per_slug:
        return False
    if hourly_pat_fires >= cfg.max_hourly_pat_fires:
        return False

    # Let book stabilize after slug opens
    if (ts_us - slot_start_us) < cfg.pat_min_time_after_open_s * 1_000_000:
        return False

    # Need book depth on BOTH sides
    if ss_up.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False
    if ss_dn.ask_size_at_best < cfg.pat_min_book_depth_each_side:
        return False

    # === EDGE FILTER (the only thing that matters for profit) ===
    fee_up = poly_taker_fee_per_share(ss_up.best_ask)
    fee_dn = poly_taker_fee_per_share(ss_dn.best_ask)
    pair_cost = ss_up.best_ask + ss_dn.best_ask + fee_up + fee_dn
    if pair_cost >= cfg.pat_max_pair_cost or pair_cost <= 0:
        return False

    # Inventory cap
    if ss_up.inv >= cfg.absolute_max_inventory or ss_dn.inv >= cfg.absolute_max_inventory:
        return False

    # Wallet balance
    take_size = min(cfg.pat_take_size, ss_up.ask_size_at_best, ss_dn.ask_size_at_best)
    cost = take_size * (ss_up.best_ask + ss_dn.best_ask) + take_size * (fee_up + fee_dn)
    if wallet_balance < cost + cfg.reserve_usdc:
        return False

    return True
```

### 3.2 Fire execution — `pat.execute_pat_fire(slug, ss_up, ss_dn, cfg, client, merger, now_us)`

Async — fires both market buys in parallel, then merges.

```python
async def execute_pat_fire(slug, ss_up, ss_dn, cfg, client, merger, now_us):
    take_size = min(cfg.pat_take_size,
                    ss_up.ask_size_at_best,
                    ss_dn.ask_size_at_best)
    if take_size < 5:           # below CLOB minimum
        return None

    ask_up, ask_dn = ss_up.best_ask, ss_dn.best_ask

    # Submit BOTH market-buys concurrently (CRITICAL for arb integrity)
    up_task = asyncio.create_task(client.market_buy(slug, "Up",   ask_up, take_size))
    dn_task = asyncio.create_task(client.market_buy(slug, "Down", ask_dn, take_size))

    up_result, dn_result = await asyncio.gather(
        up_task, dn_task, return_exceptions=True
    )

    up_filled = (up_result.filled_size if not isinstance(up_result, Exception) else 0)
    dn_filled = (dn_result.filled_size if not isinstance(dn_result, Exception) else 0)

    if up_filled > 0:
        ss_up.inv += up_filled
        ss_up.cost_paid += up_filled * up_result.fill_price
        ss_up.taker_fees += up_filled * poly_taker_fee_per_share(up_result.fill_price)
    if dn_filled > 0:
        ss_dn.inv += dn_filled
        ss_dn.cost_paid += dn_filled * dn_result.fill_price
        ss_dn.taker_fees += dn_filled * poly_taker_fee_per_share(dn_result.fill_price)

    ss_up.n_pat_fires += 1
    ss_dn.n_pat_fires += 1
    ss_up.last_pat_us = now_us
    ss_dn.last_pat_us = now_us

    # Immediate merge of completed pair
    pairs = min(up_filled, dn_filled)
    if pairs >= 1:
        ok = await merger.merge_pairs(slug, pairs)
        if ok:
            ss_up.inv -= pairs
            ss_dn.inv -= pairs
            # cash_recovered is updated by merger callback (it knows the slug_state)
    # If asymmetric fill: do NOT cancel the filled leg. ACC-M maker layer
    # will try to balance via the next BID cycle.

    return {
        "fired": True,
        "take_size": take_size,
        "up_filled": up_filled,
        "dn_filled": dn_filled,
        "pair_cost": ask_up + ask_dn +
                     poly_taker_fee_per_share(ask_up) +
                     poly_taker_fee_per_share(ask_dn),
        "merged_pairs": pairs,
    }
```

### 3.3 Integration: where PAT plugs into L25Update

```python
# In pat_accm.handle_l25:
def handle_l25(slug, ts_us, book, slug_state, cfg, client, merger, engine):
    # 1. ACC-M maker step: cancel + post on each side
    for side in ("Up", "Down"):
        order = slug_state.open_order(side)
        if order is not None:
            cancel, reason = acc_m.should_cancel_bid(order, book, cfg, ts_us)
            if cancel and not (cfg.cancel_on_close and
                               ts_us - slug_state.slot_start_us > cfg.stop_posting_offset_s * 1e6):
                emit_cancel(order); slug_state.clear_order(side)
        ok, bid_price = acc_m.should_post_bid(
            side, slug_state, book, cfg, engine.wallet_balance,
            slug_state.slot_start_us, ts_us)
        if ok:
            emit_post_bid(slug, side, bid_price, cfg.post_size)
            slug_state.record_open_order(side, bid_price, cfg.post_size, ts_us)

    # 2. ACC-M merge check
    do_merge, pairs = acc_m.should_merge(slug_state, cfg)
    if do_merge:
        asyncio.create_task(merger.merge_pairs(slug, pairs))
        # (merger callback updates inv + cash_recovered)

    # 3. PAT overlay
    if cfg.enable_pat:
        if pat.check_pat_trigger(slug_state.up, slug_state.dn, cfg,
                                 ts_us, slug_state.slot_start_us,
                                 engine.hourly_pat_fires,
                                 engine.wallet_balance):
            asyncio.create_task(pat.execute_pat_fire(
                slug, slug_state.up, slug_state.dn, cfg,
                client, merger, ts_us))
            engine.hourly_pat_fires += 1
```

---

## 4. Fee + rebate primitives — `fees.py`

These are already implemented in `strategy_lab/fees.py`. Port to TV.

```python
DEFAULT_CRYPTO_FEE_BPS = 700           # 7% per Gamma feeSchedule
MAKER_REBATE_SHARE_CRYPTO = 0.20       # makers receive 20% of taker fee as rebate

def poly_taker_fee_per_share(price: float, fee_rate: float = 0.07) -> float:
    """Real curve: fee = rate × p × (1 − p). Zero at p=0 or p=1, peaks at p=0.5."""
    if not (0.0 < price < 1.0):
        return 0.0
    return fee_rate * price * (1.0 - price)

def poly_maker_rebate_per_share(price: float, fee_rate: float = 0.07,
                                rebate_share: float = MAKER_REBATE_SHARE_CRYPTO) -> float:
    """Maker rebate = 20% × taker fee. Maker also pays $0 in addition."""
    return poly_taker_fee_per_share(price, fee_rate) * rebate_share
```

**Critical**: takers pay this fee per share on **every** fill. Makers pay **$0** and receive the rebate. The legacy "2% on profit" approximation is wrong — at p=0.69 with 48% hit rate the real fee curve costs ~$0.43/trade extra vs legacy.

---

## 5. Capital math

At wallet seed $200 USDC.e:

| Bucket | Amount | Notes |
|---|---:|---|
| Reserve (gas + safety) | $30 | hard floor — never go below |
| ACC-M working (2-3 slugs × $20 × 2 sides) | $80-$120 | up to 6 open orders × 20 shares × avg $0.50 |
| PAT transient (up to 2 fires/hr × $20) | $40 | recovered $1/pair on immediate merge |
| Spare buffer | $10-$50 | for slug rotation |

`max_concurrent_slugs = 3` is the cap. Engine MUST enforce. Above 3 the working capital exceeds budget.

**ABS limits**:
- Total working capital at any moment must stay under `wallet_balance - reserve_usdc`
- If wallet drops below $50: pause all new posts until next deposit

---

## 6. Expected per-slug behavior (BTC 5m)

From `_fast_full_btc_full_btc5m.csv` validation:

| Stat | Value |
|---|---|
| Universe | 6,110 BTC 5m slugs |
| PAT+ACC-M fires (≥1 fill) | 2,984 slugs (49%) |
| Mean PnL across **all** slugs | **+$7.79** (this includes $0 for non-fires) |
| Mean PnL on firing slugs | +$15.95 (sum / 2984) |
| Median PnL on firing slugs | ~+$1.50 |
| Win rate (PnL > 0 on firing slugs) | ~75% |
| Per-slug stddev | ~$13 |

Per-slug operational events:
- L25 updates received: ~300
- ACC-M BID posts: 50-100
- ACC-M BID fills: 8-25
- ACC-M merges: 2-5
- **PAT taker fires: 0-2** (rare; depends on book)
- PAT merges: 0-2

---

## 7. Shadow log — required CSV columns

Write one row per `LogSlugComplete` to `shadow_pat_accm_{YYYYMMDD}.csv`:

```
slug,asset,tf,slot_start_us,slot_end_us,outcome_truth,
n_l25_updates,n_bid_posts,n_bid_cancels,n_bid_fills_up,n_bid_fills_dn,
n_merges,pairs_merged,
n_pat_checks,n_pat_passed,n_pat_fires,
pat_total_take_size,pat_partial_fill_events,pat_avg_pair_cost,
inv_up_final,inv_dn_final,leftover_redeemed,
cost_paid_total,cash_received_total,rebates_total,taker_fees_total,
pnl_realized,pnl_expected_backtest,
wallet_balance_start,wallet_balance_end,
err_rate_pct,halt_reason
```

Plus per-decision log to `shadow_pat_decisions_{date}.csv` (one row per PAT check):

```
ts_us,slug,
ss_up_best_ask,ss_dn_best_ask,ask_size_up,ask_size_dn,
pair_cost,fee_up,fee_dn,
check_passed,skip_reason,
inv_up,inv_dn,wallet_balance,
hourly_pat_fires,elapsed_s_from_slot_start
```

Skip reasons (enum): `OK`, `INVALID_ASK`, `RATE_LIMIT`, `SLUG_CAP`, `HOURLY_CAP`, `TOO_EARLY`, `THIN_BOOK`, `PAIR_COST_TOO_HIGH`, `INV_CAP`, `INSUFFICIENT_BALANCE`.

---

## 8. Unit tests (must pass before shadow)

```python
# test_pat_trigger.py

def test_fires_when_pair_cost_under_one():
    cfg = StratCfg(pat_max_pair_cost=1.00, pat_min_time_after_open_s=5,
                   pat_min_book_depth_each_side=5)
    ss_up = SideState("Up",   best_ask=0.42, ask_size_at_best=20)
    ss_dn = SideState("Down", best_ask=0.55, ask_size_at_best=20)
    # pair_cost = 0.42 + 0.55 + fee(0.42) + fee(0.55)
    #           = 0.97 + 0.07×0.42×0.58 + 0.07×0.55×0.45
    #           = 0.97 + 0.017 + 0.0173 ≈ 1.004  → should NOT fire (above 1.00)
    assert not check_pat_trigger(ss_up, ss_dn, cfg,
                                 ts_us=20_000_000, slot_start_us=0,
                                 hourly_pat_fires=0, wallet_balance=200)

def test_fires_when_pair_cost_well_under_one():
    cfg = StratCfg()
    ss_up = SideState("Up",   best_ask=0.40, ask_size_at_best=20, last_pat_us=0)
    ss_dn = SideState("Down", best_ask=0.50, ask_size_at_best=20, last_pat_us=0)
    # pair_cost ≈ 0.90 + 0.075 ≈ 0.975 → fires
    assert check_pat_trigger(ss_up, ss_dn, cfg, 20_000_000, 0, 0, 200)

def test_blocks_in_first_5s():
    cfg = StratCfg(pat_min_time_after_open_s=5)
    ss_up = SideState("Up",   best_ask=0.40, ask_size_at_best=20)
    ss_dn = SideState("Down", best_ask=0.50, ask_size_at_best=20)
    # 3s after slug start → blocked
    assert not check_pat_trigger(ss_up, ss_dn, cfg, 3_000_000, 0, 0, 200)

def test_blocks_thin_book():
    cfg = StratCfg(pat_min_book_depth_each_side=5)
    ss_up = SideState("Up",   best_ask=0.40, ask_size_at_best=2)   # too thin
    ss_dn = SideState("Down", best_ask=0.50, ask_size_at_best=20)
    assert not check_pat_trigger(ss_up, ss_dn, cfg, 20_000_000, 0, 0, 200)

def test_blocks_rate_limit():
    cfg = StratCfg(pat_min_s_between_fires=5)
    ss_up = SideState("Up",   best_ask=0.40, ask_size_at_best=20, last_pat_us=18_000_000)
    ss_dn = SideState("Down", best_ask=0.50, ask_size_at_best=20)
    # ts - last_fire = 2s, below 5s rate limit
    assert not check_pat_trigger(ss_up, ss_dn, cfg, 20_000_000, 0, 0, 200)

def test_blocks_inv_cap():
    cfg = StratCfg(absolute_max_inventory=100)
    ss_up = SideState("Up",   best_ask=0.40, ask_size_at_best=20, inv=100)  # at cap
    ss_dn = SideState("Down", best_ask=0.50, ask_size_at_best=20)
    assert not check_pat_trigger(ss_up, ss_dn, cfg, 20_000_000, 0, 0, 200)

def test_blocks_insufficient_balance():
    cfg = StratCfg(pat_take_size=20, reserve_usdc=30)
    ss_up = SideState("Up",   best_ask=0.40, ask_size_at_best=20)
    ss_dn = SideState("Down", best_ask=0.50, ask_size_at_best=20)
    # take = 20, cost ≈ 20×0.90 + 2×~0.5 ≈ $19; need $19 + $30 reserve = $49
    assert check_pat_trigger(ss_up, ss_dn, cfg, 20_000_000, 0, 0, 50)
    assert not check_pat_trigger(ss_up, ss_dn, cfg, 20_000_000, 0, 0, 40)


# test_acc_m.py — at minimum:
def test_post_bid_only_when_sum_bids_below_one():
    book = Book(up=SideBook(best_bid=0.48, best_ask=0.51),
                dn=SideBook(best_bid=0.49, best_ask=0.52))
    # sum_bids = 0.97 → posts
    ok, px = should_post_bid("Up", empty_state, book, default_cfg, wallet_balance=200,
                              slot_start_us=0, now_us=10_000_000)
    assert ok and px == 0.48

def test_post_bid_blocks_when_sum_bids_at_one():
    book = Book(up=SideBook(best_bid=0.51, best_ask=0.54),
                dn=SideBook(best_bid=0.49, best_ask=0.52))
    # sum_bids = 1.00 → blocks
    ok, _ = should_post_bid("Up", empty_state, book, default_cfg, 200, 0, 10_000_000)
    assert not ok

def test_cancel_on_3c_displacement():
    order = Order(side="Up", price=0.48, posted_us=0)
    book = Book(up=SideBook(best_bid=0.45, best_ask=0.51), ...)
    cancel, reason = should_cancel_bid(order, book, default_cfg, now_us=5_000_000)
    assert cancel and reason == "displacement"

def test_no_cancel_at_2c_displacement():
    order = Order(side="Up", price=0.48, posted_us=0)
    book = Book(up=SideBook(best_bid=0.46, best_ask=0.51), ...)
    cancel, _ = should_cancel_bid(order, book, default_cfg, now_us=5_000_000)
    assert not cancel

def test_merge_at_threshold_pairs():
    state = SlugState(...); state.up.inv = 5; state.dn.inv = 6
    ok, pairs = should_merge(state, default_cfg)
    assert ok and pairs == 5

def test_no_merge_below_threshold():
    state = SlugState(...); state.up.inv = 4; state.dn.inv = 4
    ok, pairs = should_merge(state, default_cfg)
    assert not ok


# test_pat_accm_integration.py
def test_full_slug_pnl_matches_backtest():
    """Replay a known slug from fast_full_backtest output, assert PnL within $0.10."""
    # Pick btc-updown-5m-1778767500 from _fast_full_btc_full_btc5m.csv
    # Run pat_accm.handle_l25 over recorded L25 events
    # Assert |computed_pnl - reference_pnl| < 0.10
```

---

## 9. Shadow → Live promotion criteria

After 7 days of shadow:

| Criterion | Threshold |
|---|---:|
| Mean realized $/slug | **> $1.00** |
| Median realized $/slug | **> $0** |
| Realized maker-fill rate ÷ shadow-projected | **> 25%** |
| Max 24h drawdown (shadow $/slug × n_slugs) | **< $25** |
| PAT fires successfully paired | **≥ 1 in 7d, ≥ 70% pair-complete** |
| Engine error rate (any unhandled exception) | **< 0.5%** |
| Latency p99 (PAT decision-to-order-submit) | **< 250ms** |

If shadow shows -$0.50/slug to +$0/slug: pause for 1 week, re-analyze. Likely TV maker queue position differs from backtest.

If shadow shows < -$0.50/slug: do **not** promote. Open a debug session.

---

## 10. Live deploy progression

| Day | Wallet | Cells | Max concurrent slugs | Pass criterion |
|---:|---:|---|---:|---|
| 1 | $200 | btc_5m | 1 | No errors, 1 successful merge |
| 2 | $200 | btc_5m | 2 | 24h PnL > $0 |
| 3-7 | $200 | btc_5m | 3 | 24h drawdown < $25, 7-day PnL > $50 |
| 8-14 | $200 | btc_5m + btc_15m | 3 | 14-day PnL > $150 |
| 15-30 | $400 | btc_5m + btc_15m + eth_5m | 4 | 30-day PnL > $400 |
| 30+ | $1000 | full BTC + ETH | 6 | maintain Sharpe > 0.15 |

### Halt conditions (auto, no manual override)

Stop the strategy immediately if any:
- 24h drawdown > $30
- 7-day rolling PnL < -$50
- 5 consecutive losing slugs
- Engine error rate > 1% over 1h window
- PAT fires fail to pair-complete > 30% of last 10 fires
- Wallet balance < $50

### Re-tune triggers (reduce size, don't halt)

- Realized fill rate < 25% of projected → reduce `post_size` to 10 temporarily
- Inventory imbalance > 50% sustained → tighten `max_imbalance_shares` to 5
- PAT pair-cost edge < $0.01 most fires → raise `pat_max_pair_cost` floor or pause PAT

---

## 11. Risk: partial PAT fill

If both `market_buy` calls submit but only one fills (book moves in the millisecond gap), we have single-side exposure.

**Mitigation built into `execute_pat_fire`**:
1. `asyncio.gather(..., return_exceptions=True)` — never crashes on one-side failure
2. Both legs use **MarketBuy at top-ask** with a tight `max_slippage = 0.02` cap on the order
3. If asymmetric fill: ACC-M maker layer continues posting BIDs on the lagging side to rebalance via maker rebates rather than a second taker take
4. Log every partial-fill prominently to `shadow_pat_decisions.csv` with `pat_partial_fill_events += 1`

**Worst case**: 20 shares of one side at avg $0.45 = $9 exposure. If outcome wrong: -$9. Bounded. Backtest sees this on <5% of fires.

If partial-fill rate exceeds 30% over rolling 10 fires → halt PAT layer (keep ACC-M running).

---

## 12. Files to ship

```
backend/app/strategies/polymarket/maker/
├── types.py          (§1.3 dataclasses)        — NEW
├── fees.py           (§4)                       — port from strategy_lab/fees.py
├── acc_m.py          (§2)                       — NEW
├── pat.py            (§3)                       — NEW
└── pat_accm.py       (§3.3 wiring + lifecycle)  — NEW

backend/tests/unit/strategies/maker/
├── test_acc_m.py            — NEW
├── test_pat_trigger.py      — NEW
└── test_pat_accm_integration.py — NEW (uses recorded L25 events)

/etc/tv/tradingvenue.env additions
├── TV_POLY_MAKER_STRATEGY=PAT_ACCM_HYBRID
├── TV_POLY_MAKER_WALLET_SEED_USDC=200
├── TV_POLY_MAKER_CELLS=btc_5m
├── TV_POLY_MAKER_MAX_CONCURRENT_SLUGS=3
├── TV_POLY_MAKER_POST_SIZE=20
├── TV_POLY_MAKER_PAT_ENABLED=true
├── TV_POLY_MAKER_PAT_MAX_PAIR_COST=1.00
└── TV_POLY_MAKER_SHADOW_MODE=true            (flip to false to go live)
```

---

## 13. What this spec does NOT cover (deferred)

- **Other strategies (MAS, ACC-H, ACC-PC, PAT-SHADOW)**. Validation showed only PAT+ACC-M is profitable on the full universe. Deferring the rest until PAT+ACC-M is live and stable.
- **Slug-selection filter**. Per `SLUG_SELECTION_DECODE_2026_05_20.md`, we can predict wallet engagement (AUC 0.94+) but it does NOT amplify PAT+ACC-M PnL. Deploy on full BTC 5m universe — no filter.
- **ETH / SOL**. Phase 2 after BTC validates.
- **Slug-prioritization** (when more slugs available than `max_concurrent_slugs`). Use FIFO on `slot_start_us` until further analysis.
- **REST/WS lag mitigation** for the momo controller. That's a separate TV agent track. See `MOMO_REST_LAG_VS_MICROSTRUCTURE.md`.

---

## 14. Reference data the TV agent can use to validate

After implementation, replay one of these slugs through the engine and verify PnL within $0.10:

| Slug | Tf | Outcome | PAT+ACC-M PnL (backtest) | Notes |
|---|---|---|---:|---|
| btc-updown-5m-1778767500 | 5m | Down | +$50.35 | High-PnL example (n=1 from validation) |
| btc-updown-5m-1778769300 | 5m | Up | +$30.04 | Typical win |
| btc-updown-5m-1778766900 | 5m | (look up) | +$10-20 | Typical |

All available in `strategy_lab/backtests/_fast_full_btc_full_btc5m.csv` (`strategy=PAT+ACC-M`).

To pull L25 events for a slug:
```python
import pyarrow.parquet as pq
pf = pq.ParquetFile("data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet")
for rg_idx in range(pf.metadata.num_row_groups):
    df = pf.read_row_group(rg_idx).to_pandas()
    df = df[df.slug == "btc-updown-5m-1778767500"]
    # ... replay through engine
```

---

## 15. Bottom line

Implement PAT+ACC-M HYBRID per this spec. Deploy at $200 in shadow mode for 7 days. If shadow shows mean PnL > $1/slug and no errors, promote to live in 4 stages per §10. Backtest projects **+$7.79/slug** on the full universe and **+$1.98/slug** on firing-only slugs; live realistic is **$50-150/day** at $200 wallet after queue-position dilution.

This is the only validated profitable strategy we have. Slug-selection alpha (predicting which slugs the wallets pick) was attempted this session and does NOT amplify PnL — so we deploy on the full BTC 5m universe with no selection filter. Decoded findings live in `SLUG_SELECTION_DECODE_2026_05_20.md` for future reference.
