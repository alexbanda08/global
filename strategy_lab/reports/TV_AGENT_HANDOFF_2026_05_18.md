# TV Agent Handoff — Polymarket Maker Bot Suite

**Date**: 2026-05-18
**Version**: 1.0
**Scope**: Build, shadow, and deploy 3 maker bots for Polymarket binary up-down markets

---

## Overview

You are building 3 strategy modules that share infrastructure but operate independently:

| Code | Type | Side of book | Deploy priority |
|---|---|---|---|
| **ACC-M** | Maker pair arbitrage (BID-only) | BUY side | **1st** (simplest, lowest risk) |
| **ACC-H** | ACC-M + discount-capture taker | BUY side + opportunistic taker | 2nd (after ACC-M validated) |
| **MAS** | Mint-and-sell maker (ASK-only) | SELL side | 3rd (different side, doesn't compete) |

Each module is independently configurable, runs in parallel, and can be enabled/disabled per cell. Full per-strategy specs:

- `strategy_lab/reports/TV_DEPLOY_SPEC_ACC_M_2026_05_18.md`
- `strategy_lab/reports/TV_DEPLOY_SPEC_ACC_H_2026_05_18.md`
- `strategy_lab/reports/TV_DEPLOY_SPEC_MAS_2026_05_18.md`

---

## ⚡ Performance requirements (MANDATORY)

You are competing with 100+ other maker bots for queue position. Every millisecond
matters. The strategy works only if our orders reach the book BEFORE competitors.
These optimizations are NOT optional.

### P1. VPS location — Ireland/London (MUST HAVE)

Polymarket CLOB infrastructure is on AWS eu-west-2 (London). Deploy the bot to a
VPS in Ireland or London with verified < 5ms round-trip to AWS eu-west-2.

- US East: 130ms round-trip — **unusable for this strategy**
- US West: 200ms — **unusable**
- Ireland: 1-2ms — **target**
- London: 0.5-1ms — **ideal**

Verify with `ping` to `clob.polymarket.com` and confirm RTT < 5ms before deploying.

Recommended providers: Hetzner FSN1/HEL1, OVH London, AWS eu-west-2 (same region as Polymarket).

### P2. WebSocket-only order posting (MUST HAVE)

Polymarket exposes BOTH REST and WebSocket order APIs. WS is materially faster.

- REST `POST /order`: 10-50ms per call (HTTP overhead, TLS handshake amortized)
- WS persistent connection: 1-2ms per order (just frame send)

Use ONLY WebSocket order posting. Maintain a persistent WS connection 24/7
with TCP keepalive at 15s intervals.

### P3. Pre-signed order pool (MUST HAVE)

EIP-712 order signing is ~1ms per order in Python. At 1-3 orders per second peak,
this is significant on-decision latency.

**Solution**: at slug start, pre-sign 10-20 candidate orders at varying prices
(e.g., $0.40, $0.42, $0.44, ..., $0.60 for both sides). When the decision engine
triggers a post, look up the pre-signed order matching the current best_bid and
send it immediately.

Pre-signing happens off the critical path (during slug warmup, before fills can occur).
Decision-to-send latency drops from ~1.5ms to ~50µs.

```python
# Slug warmup (T-30s before slug start)
for side in ["Up", "Down"]:
    for price in price_grid(0.30, 0.65, step=0.01):
        order = build_order(slug, side, price, POST_SIZE)
        signed = sign_eip712(order, wallet_key)
        pre_signed_pool[(slug, side, price)] = signed

# Decision time (hot path)
def post_bid(slug, side, price):
    signed = pre_signed_pool.get((slug, side, round_to_cent(price)))
    if signed:
        ws.send(signed)  # ~50µs
    else:
        # Fallback: sign on the fly (rare)
        ...
```

### P4. Async pipeline (MUST HAVE)

Decision logic, order sending, fill processing, and merge transactions must
all run on separate async tasks. NEVER block the decision loop on:
- HTTP requests
- TX confirmations
- Disk I/O
- Logging (use async log queue)

Python: use `asyncio` + `aiohttp` + `aio_pika` (if using msg queue).
Decision loop should be ZERO-IO on the hot path.

### P5. Connection pooling + persistent WS (MUST HAVE)

- ONE persistent WS connection per Polymarket endpoint (CLOB + user)
- Never reconnect mid-slug (cancel all orders if reconnect needed)
- TCP keepalive enabled (15-30s interval)
- Detect dead connections within 3 seconds (heartbeat ping)

### P6. Fast JSON parsing (RECOMMENDED)

Standard Python `json` library is slow (~50µs per L25 message).

Use `msgspec` or `orjson` for 5-10x faster parsing:
- `msgspec`: schema-typed, fastest, validates on parse
- `orjson`: schema-less, very fast, lenient

For hot-path WS messages, define typed schemas and use `msgspec.json.Decoder`.

### P7. Local price grid quantization

CLOB prices are in 1-cent increments. Round all incoming prices to the nearest
cent BEFORE any logic. This:
- Eliminates float-comparison bugs
- Enables pre-signed order lookup by exact price key
- Reduces decision branches

```python
def quantize(price):
    return round(price * 100) / 100
```

### P8. Async logging (don't block on disk)

Shadow mode generates ~50-200 log lines per slug. Synchronous disk writes can
add 0.5-2ms per decision.

Use an async log queue:
```python
log_queue = asyncio.Queue(maxsize=10000)

async def log_writer():
    while True:
        batch = []
        try:
            for _ in range(100):
                batch.append(await asyncio.wait_for(log_queue.get(), timeout=0.1))
        except asyncio.TimeoutError:
            pass
        if batch:
            await write_batch_to_disk(batch)

# Hot path
log_queue.put_nowait(decision)  # zero-blocking
```

### P9. Pre-compute decision triggers

For each L25 update, the decision rules are mostly deterministic conditionals.
Pre-compute thresholds and use them as fast comparisons:

```python
# At config load time (once)
CANCEL_THRESHOLD_CENTS = int(0.03 * 100)  # 3
MAX_BID_CENTS = int(0.95 * 100)  # 95
MIN_BID_CENTS = int(0.05 * 100)  # 5

# Hot path (per L25 update)
bid_cents = int(book.best_bid * 100)
if not (MIN_BID_CENTS <= bid_cents <= MAX_BID_CENTS):
    return None
displacement_cents = abs(bid_cents - order.price_cents)
if displacement_cents >= CANCEL_THRESHOLD_CENTS:
    cancel_order(order)
```

Integer comparisons are faster than float and eliminate FP precision issues.

### P10. Measure latency in shadow mode

Instrument every hot-path operation:

```python
@dataclass
class LatencyMetrics:
    ws_receive_to_parse: float       # WS frame in → parsed event
    parse_to_decision: float         # parsed → decision computed
    decision_to_send: float          # decision → WS frame out
    end_to_end: float                # WS in → WS out
```

Track p50/p90/p99 percentiles per metric. Log distribution daily.

**Target latency budgets**:
- ws_receive_to_parse: p99 < 200µs
- parse_to_decision: p99 < 500µs
- decision_to_send: p99 < 200µs (using pre-signed orders)
- end_to_end: p99 < 1ms (excluding network)

If any metric is significantly above budget, identify the bottleneck before
deploying live.

---

## Phase 3: Rust transition plan (after Python deploy validated)

Python with all the above optimizations achieves ~1ms compute latency end-to-end.
For elite queue position (top 5% of bots), Rust can shave another 0.5-0.8ms on
the hot path.

### When to transition

Rewrite ONLY when ALL of these are true:
- Python implementation deployed live and profitable
- Shadow data shows our fill rate is < 50% of simulated optimistic (queue starvation)
- We have 4-8 weeks of engineering budget
- Latency profiling shows compute (not network or CLOB-side) is the bottleneck

### What to rewrite first (hybrid approach)

Don't rewrite everything in Rust. Use FFI/PyO3 for the critical hot path:

| Module | Stay Python | Rewrite in Rust |
|---|---|---|
| Strategy decision logic | ✅ | |
| State management | ✅ | |
| Logging / monitoring | ✅ | |
| Order management | ✅ | |
| WS message parsing | | ✅ (highest gain) |
| EIP-712 order signing | | ✅ (largest single cost) |
| L25 book delta merging | | ✅ |
| Decision-rule conditionals | | ✅ (only after profile shows benefit) |

The strategy logic itself stays in Python — easier to iterate, debug, A/B test.
The hot path (parse → sign → send) goes to Rust.

### Rust target latency

| Operation | Python | Rust |
|---|---|---|
| WS frame parse | 50µs | 5µs |
| EIP-712 sign | 1000µs | 50µs |
| End-to-end hot path | 1500µs | 300µs |

A 1.2ms improvement on the critical path. For 300 competing bots fighting for
queue position, this can mean the difference between front of queue and back.

### Infrastructure for Rust transition

- Use `pyo3` for Python-to-Rust FFI
- Use `ethers-rs` for EIP-712 signing
- Use `tungstenite` for WS
- Maintain backward compat — Python should still work if Rust extension fails to load

---

## Shared infrastructure required

### 1. Market data feed (WS)

Subscribe to Polymarket CLOB WebSocket for:
- **L25 book updates** per active (slug, outcome) — produces `L25Update` events
- **Trade prints** per active (slug, outcome) — produces `TradePrint` events

Required quality:
- Sub-second latency from CLOB to bot
- Auto-reconnect on disconnect
- Backpressure handling (drop oldest if bot is slow)

### 2. Slug lifecycle feed

Per cell (BTC/ETH/SOL × 5m/15m), track:
- Active slug ID
- Slot start timestamp (microseconds UTC)
- Slot end timestamp
- Condition ID (for CTF/redeem calls)
- Resolution status + outcome (from chainlink)

Emit events:
- `SlugActive(slug, asset, tf, slot_start_us, slot_end_us, condition_id)`
- `SlugResolved(slug, outcome, settlement_ts_us)`

### 3. Wallet manager

Track:
- USDC.e balance (live, updated after every tx)
- Outstanding order commitments (sum of price × size for open orders)
- Free balance available for new commitments

Emit:
- `WalletBalance(usdc_balance, last_updated_us)` on every change

### 4. Order management

For each strategy module:
- Track open orders by `order_id`
- Update on `OrderFill` events from CLOB WS
- Handle partial fills (residuals remain on book)
- Track cancel state (sent vs confirmed)

### 5. On-chain transaction manager

Build, sign, and submit transactions for:
- **MintPairs**: `ConditionalTokens.splitPosition(collateral=USDC, parent=0, condition_id, partition=[1,2], amount)`
- **MergePositions**: via NegRiskAdapter contract (send paired Up+Down tokens; returns USDC.e in same tx)
- **RedeemPositions**: `ConditionalTokens.redeemPositions(collateral=USDC, parent=0, condition_id, indexSets=[winning_set])`

Requirements:
- Gas price oracle (Polygon — typically 30 gwei base)
- Retry logic on revert (up to 3 attempts with increasing gas)
- Tx confirmation tracking
- Nonce management for parallel txs

### 6. Decision dispatch

For each strategy module instance:
- On every `L25Update`: call `strategy.on_l25_update(slug, books, state)`
- On every `OrderFill`: call `strategy.on_order_fill(slug, order_id, fill_size, fill_price)`
- On `SlugResolved`: call `strategy.on_slug_resolved(slug, outcome)`
- On periodic 5s timer: call `strategy.on_merge_check(slug, state)` (ACC strategies only)

Each strategy returns a list of `Decision` objects (PostBid, PostAsk, Cancel, MergePositions, MarketBuy, RedeemPositions). Dispatch them through order management + tx manager.

### 7. Logging + telemetry

Per strategy module:
- Shadow CSV log of every decision (see per-spec format)
- Per-slug summary at slug end (PnL, fills, merges, leftover)
- Daily report (total PnL, slug count, avg edge per slug)
- Real-time metrics: open orders, inventory per slug, wallet balance

### 8. Kill switches

- Per-strategy enable/disable flag (toggle without restart)
- Per-cell enable/disable
- Global emergency halt (cancel all open orders, no new posts)
- Daily drawdown auto-halt per strategy

---

## Deployment sequence

### Phase 1: ACC-M shadow (Day 1)

Implement ACC-M only. Deploy on VPS with `shadow_mode=True`.

- Subscribe to BTC 5m + BTC 15m feeds
- Log all decisions to CSV
- Simulate fills based on incoming TradePrint events
- No on-chain txs

**Success criterion**: bot runs 24h without crashing, generates well-formed log files.

### Phase 2: ACC-M shadow validation (Day 2-3)

Continue shadow for 48 total hours, then:

- Compute realized $/slug (using simulated fills)
- Compare to expected: ~$0.50-$2 per slug at small scale
- Validate inventory balance discipline (% slugs with imbalance >25%)
- Validate cancel discipline (avg order age before cancel)

**Promotion criteria**:
- Mean $/slug > $0 in last 24h
- Median $/slug > $0
- Max 24h drawdown < $25
- No more than 2 slugs with >25% imbalance

### Phase 3: ACC-M live (Day 4)

If shadow passes:
- Toggle `shadow_mode=False`
- Fund wallet with $50 USDC.e
- Start with BTC 5m ONLY (single cell to limit risk)
- Monitor for 24h

**Live success criterion**: realized $/day matches shadow projection within ±30%.

### Phase 4: ACC-H implementation (Day 5-7)

While ACC-M runs live, build ACC-H:
- Inherits all ACC-M code
- ADDS discount-capture taker module
- New trigger: market-buy when ask drops > 3¢ below 60s median AND ask < $0.50

Deploy in shadow alongside live ACC-M.

### Phase 5: ACC-H shadow validation (Day 8-9)

48h shadow. Promotion criteria stricter:
- Mean $/slug > $0.50
- Median $/slug > $0.20
- Taker fills capture cheaper than median (verify trigger works)
- Drawdown < $30

### Phase 6: ACC-H live (Day 10)

If shadow passes:
- Run ACC-M (existing) + ACC-H (new) in parallel
- Allocate wallet: $50 to ACC-M, $50 to ACC-H
- Different cells if desired (e.g., ACC-M on BTC 15m, ACC-H on BTC 5m)

### Phase 7: MAS implementation (Day 11+)

Implement MAS as separate module:
- Reuses shared infrastructure
- Adds MintPairs flow before posting asks
- Posts ASKs at best_ask (NOT BIDs)

Deploy in shadow on all 6 cells. Promote per its own criteria.

### Phase 8: Scale

After all 3 strategies validated live:
- Increase per-strategy wallet allocations gradually
- Expand cell coverage (ETH, SOL)
- Monitor combined inventory exposure (across all 3 modules)

---

## Capital allocation (initial)

```python
WALLET_TOTAL = 200  # USDC.e

ALLOCATIONS = {
    "ACC-M": 50,    # BTC 5m + 15m
    "ACC-H": 50,    # BTC 5m + ETH 5m
    "MAS":   100,   # All 6 cells × $17 pre-mint each
}

# Reserve: $0 (each module enforces its own reserve internally)
```

Each module operates within its allocation. If a module hits its allocation cap (all funds in open orders + inventory), it stops posting new orders.

---

## Concurrent execution rules

When running multiple strategies on the same cell:

1. **ACC-M and MAS on same cell**: different sides of book, no conflict. OK to run.
2. **ACC-M and ACC-H on same cell**: BOTH post BIDs — they compete. AVOID. Run on different cells.
3. **ACC-M and ACC-H on different cells**: fully independent. OK.
4. **MAS on same cell as ACC-M**: OK (different sides).

Recommended initial assignment:
- ACC-M: BTC 15m + ETH 5m
- ACC-H: BTC 5m
- MAS: SOL 5m + SOL 15m + ETH 15m (cells where ACC isn't active)

---

## Shared configuration template

Each strategy reads from a shared config file:

```yaml
# config/strategies.yml

global:
  wallet_address: "0x..."
  rpc_endpoints:
    - "https://polygon-rpc.com"
    - "https://polygon-rpc.com/alt"
  ws_endpoints:
    polymarket_clob: "wss://ws-subscriptions-clob.polymarket.com/ws"
    polymarket_user: "wss://ws-subscriptions-clob.polymarket.com/ws/user"

  contracts:
    ctf: "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
    clob_matcher: "0xe111180000d2663c0091e4f400237545b87b996b"
    neg_risk_adapter: "0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0"
    usdc: "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"

  fees:
    taker_fee_rate: 0.07          # 7% per share
    maker_rebate_share: 0.20      # 20% of taker fee

strategies:
  acc_m:
    enabled: true
    shadow_mode: true
    cells: ["btc_15m", "eth_5m"]
    wallet_allocation_usdc: 50
    # ... rest from TV_DEPLOY_SPEC_ACC_M

  acc_h:
    enabled: false                # enable after ACC-M validated
    shadow_mode: true
    cells: ["btc_5m"]
    wallet_allocation_usdc: 50
    # ... rest from TV_DEPLOY_SPEC_ACC_H

  mas:
    enabled: false
    shadow_mode: true
    cells: ["sol_5m", "sol_15m", "eth_15m"]
    wallet_allocation_usdc: 100
    # ... rest from TV_DEPLOY_SPEC_MAS
```

---

## Logging format (unified across strategies)

```
shadow_<strategy>_<YYYYMMDD>.csv

Columns:
ts_us              # decision timestamp (microseconds UTC)
strategy           # ACC-M / ACC-H / MAS
slug               # market identifier
asset              # btc / eth / sol
tf                 # 5m / 15m
action             # post_bid / post_ask / cancel / market_buy / mint / merge / redeem
side               # Up / Down
price              # decimal price
size               # shares
order_id           # tracking ID (empty for non-order actions)
fill_simulated     # True/False (shadow mode only)
inv_up             # current Up inventory at decision time
inv_dn             # current Down inventory at decision time
cash_spent         # cumulative cash spent on this slug
cash_received      # cumulative cash received (for MAS)
cash_recovered     # cumulative recovered via merge
rebates            # cumulative maker rebates earned
slug_pnl_so_far    # estimated PnL up to this point
slug_offset_s      # seconds since slot_start
trigger_reason     # which filter/rule caused this decision
```

Per-slug summary written on `SlugResolved`:

```
slug_summary_<strategy>_<YYYYMMDD>.csv

Columns: slug, asset, tf, outcome, n_posts, n_cancels, n_fills, n_market_buys,
         n_merges, n_redeems, total_cash_spent, total_cash_received,
         total_cash_recovered, total_rebates, mint_cost, leftover_up, leftover_dn,
         redeem_value, slug_pnl
```

---

## Critical implementation details

### Cancel discipline (applies to ALL strategies)

```python
def should_cancel(order, book):
    displacement = abs(order.price - book[order.side].best_price)
    if displacement >= 0.03:  # 3¢ rule
        return True
    age_s = (now_us - order.posted_us) / 1_000_000
    if age_s >= 20:  # 20s rule
        return True
    return False  # otherwise leave it
```

**Do NOT cancel on partial fill** — leave residuals on the book.
**Do NOT cancel near slug close** — let orders fill or expire naturally.

### Inventory balance (ACC strategies)

```python
def can_post(side, state):
    if side == "Up" and state.inv_up > state.inv_dn + MAX_IMBALANCE_SHARES:
        return False  # too much Up already
    if side == "Down" and state.inv_dn > state.inv_up + MAX_IMBALANCE_SHARES:
        return False
    if state.inv[side] >= ABSOLUTE_MAX_INVENTORY:
        return False
    return True
```

ACC-M: `MAX_IMBALANCE_SHARES = 5`, `ABSOLUTE_MAX_INVENTORY = 50`
ACC-H: `MAX_IMBALANCE_SHARES = 10`, `ABSOLUTE_MAX_INVENTORY = 100` (looser because taker can rebalance)

### Merge trigger (ACC strategies)

```python
def should_merge(state):
    pairs = int(min(state.inv_up, state.inv_dn))
    return pairs >= 5
```

Merge via NegRiskAdapter: send `pairs` Up tokens + `pairs` Down tokens in single tx. Adapter returns `pairs` USDC.e in the same tx.

Periodic check every 5 seconds. Also check immediately after each fill.

### Discount-capture trigger (ACC-H only)

```python
def should_market_buy(side, book, ask_history_60s):
    current_ask = book[side].best_ask
    if current_ask >= 0.50:
        return False  # only take below mid
    if len(ask_history_60s) < 10:
        return False  # insufficient history
    median_ask = median([a for a in ask_history_60s if a > 0])
    if (median_ask - current_ask) < 0.03:
        return False  # not cheap enough
    return True
```

Rate limit: max 1 take per 5 seconds per side, max 50 takes per slug.

---

## Pre-deployment validation tests

Before going live, validate:

1. **Round-trip on testnet** (if available): mint → post → fill → merge → redeem one full slug
2. **Unit tests**: each decision rule with synthetic inputs
3. **Integration test**: replay historical L25 data, verify decisions match expected pattern
4. **Stress test**: simulate 100 slugs/day, verify no crashes, no memory leaks
5. **Failure simulation**: kill WS feed mid-slug, verify clean cancel + recovery
6. **Latency test**: measure WS-to-decision latency, target < 50ms

---

## Success metrics (after 30 days live)

For each strategy:
- Net daily PnL (USDC.e)
- Edge per pair (USDC.e per merged pair)
- Capital velocity (daily volume / peak balance)
- Sharpe ratio of daily PnL
- Max drawdown
- Order fill rate (fills / posts)
- Cancel rate (cancels / posts)

Compare to expected:

| Strategy | Test scale daily PnL | Production scale daily PnL |
|---|---|---|
| ACC-M | $25-50 | $200-500 |
| ACC-H | $50-150 | $500-2000 |
| MAS | $30-150 | $300-1500 |

If realized PnL is materially below expected after 30 days, root-cause analysis needed (likely queue position, execution latency, or signal degradation).

---

## Questions for TV agent before starting

Before implementing, confirm:

1. **WS infrastructure**: do we have stable Polymarket CLOB WS access? If not, REST polling is fallback (5s interval) but degrades fill rate.

2. **On-chain signer**: do we have an EIP-712 signer for Polymarket order signing? Required for posting orders.

3. **Wallet hot-storage policy**: how much USDC.e is the operator comfortable holding in the trading wallet?

4. **Operator timezone / monitoring schedule**: 24/7 unattended? Or scheduled hours?

5. **Cell preferences**: any cells off-limits for now (e.g., SOL too volatile)?

6. **Kill switch**: how is the operator alerted to issues (Telegram, email, dashboard)?

---

## Reference files

- Strategy specs (one per strategy):
  - `strategy_lab/reports/TV_DEPLOY_SPEC_ACC_M_2026_05_18.md`
  - `strategy_lab/reports/TV_DEPLOY_SPEC_ACC_H_2026_05_18.md`
  - `strategy_lab/reports/TV_DEPLOY_SPEC_MAS_2026_05_18.md`
- This handoff: `strategy_lab/reports/TV_AGENT_HANDOFF_2026_05_18.md`
- Backtest simulators for reference:
  - `strategy_lab/wallet_hunt/replicate/acc_simulator.py`
  - `strategy_lab/wallet_hunt/replicate/v3_wallet_trade_driven.py`

---

## Final word

This is a maker bot suite. The strategies are validated by chain analysis showing multiple operators making $10k-$250k/day with similar templates. Our test deploy targets $25-150/day at $50-200 capital.

Build ACC-M first (simplest). Validate in shadow. Promote to live. Then layer ACC-H and MAS on top.

The decoded operational rules (cancel thresholds, merge triggers, discount-capture parameters) are NOT guesses — they're chain-verified patterns. Trust them.

Run safely. Start small. Scale on data.
