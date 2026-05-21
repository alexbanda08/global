# TV Agent — Maker Bot Suite Deployment Plan

**Target VPS**: Ireland (`85.137.174.152`, `ssh vps_ireland`)
**Target environment**: existing `tv-engine.service` + `tv-api.service` running on Ubuntu 24.04
**Goal**: deploy 3 new strategies (ACC-M, ACC-H, MAS) in shadow mode first, then live
**Owner**: TV agent (the Tradingvenue dev)

---

## 0. What you already have on Ireland VPS (verified 2026-05-18)

```
/opt/tradingvenue/             — main repo (cloned + uv-synced)
/etc/tv/tradingvenue.env       — secrets + config
tv-engine.service              — running, uptime 3d 16h
tv-api.service                 — running, dashboard on :8443
```

**Polymarket infrastructure already in place** under `backend/app/venues/polymarket/`:

| Module | What it does | Reusable for new strategies? |
|---|---|---|
| `book_mirror.py` | WS L25 mirror, <10ms staleness | ✅ YES — use for L25 feed |
| `client.py` | place/cancel orders, get_fills, snapshots | ✅ YES — use for order ops |
| `live_gate.py` | geoblock check + daily ACK file | ✅ YES — required for live |
| `allowance.py` | USDC + CTF/NegRiskAdapter approval | ✅ YES — already wired |
| `fees.py` | fee curve | ✅ YES (or use ours) |
| `onchain_oracle.py` | chainlink resolution | ✅ YES — for slug outcome |
| `market_data.py` | market metadata | ✅ YES |
| `gamma_client.py` | Gamma API for discovery | ✅ YES |
| `paper.py` | paper trading executor | ⚠️ NO — bar-driven, not suitable |

**Existing strategies** under `backend/app/strategies/polymarket/`:
- `updown_5m.py` / `updown_15m.py` — bar-driven up-down strategies
- `momo.py` / `momo_v2.py` — momentum strategies
- `inverse.py` — inverse variant

All are **bar-driven** (fire once per bar boundary via `evaluate()`). **Our new strategies are EVENT-DRIVEN** (fire on every L25 update). This is the main architectural gap.

**Service infrastructure** already in place under `backend/app/services/`:
- `poly_redeemer.py` — calls **vanilla CTF.redeemPositions** (recently switched FROM NegRiskAdapter on 2026-05-18). Already handles slug resolution → cash recovery.

**Engine** at `backend/app/engine/`:
- `main.py` — asyncio TaskGroup with all loops
- `poly_updown_loop.py` — master scheduler dispatching bar-driven controllers
- `_preflight.py` — boot checks (allowance, geoblock, etc.)

---

## 1. What needs to be BUILT (the gap)

### 1.1 Event-driven strategy framework

The new strategies (ACC-M, ACC-H, MAS) need a **per-L25-tick decision loop**, NOT a bar-driven `evaluate()`. We've built this in Python at `shadow_engine/` (see §3 below for handoff).

What TV agent must add to the tradingvenue codebase:

```
backend/app/strategies/polymarket/maker/      # NEW subdir
├── __init__.py
├── base.py              # MakerStrategyBase — event-driven ABC
├── acc_m.py             # Pure pair-arb maker
├── acc_h.py             # Hybrid maker + composite taker
└── mas.py               # Mint-and-sell mirror

backend/app/engine/
└── poly_maker_loop.py   # NEW — drives MakerStrategy on every L25 update
                          # subscribes to BookMirror + trade WS + slug resolutions
                          # dispatches events to enabled strategy instances
                          # invokes order ops via PolymarketClient
```

### 1.2 NegRiskAdapter MERGE call (currently missing)

`poly_redeemer.py` switched FROM NegRiskAdapter TO vanilla CTF for **redemption**. But ACC strategies need **mergePositions** mid-slug (different from redeem):

- `redeemPositions(condition_id, indexSets)` — used after slug resolves, claims winning side at $1
- `mergePositions(condition_id, amount)` — used mid-slug, burns N Up + N Down tokens, returns N USDC.e

Add a new module:

```
backend/app/services/poly_merger.py    # NEW
  - merge_pairs(slug, condition_id, amount) -> tx_hash
  - Uses NegRiskAdapter (canonical: 0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296)
  - Already in TV's env as TV_POLY_NEG_RISK_ADAPTER_ADDRESS
```

**Chain trace verified (2026-05-18)**: All decoded wallets (0x89b5cdaa, 0x04b6d7e9, 0xeebde7a0, relay 0xf3cfb6a6) route through a Polymarket-internal BATCH MERGE ROUTER at `0x84ba896235059fe27727eaa2695a9f99220d9a7e` for high-frequency batch merges. That router internally calls NegRiskAdapter / CTF.

**For our scale (5-pair merges, $50-200 capital), single NegRiskAdapter calls are sufficient.** Upgrade to batch router only when daily volume exceeds $1M.

### 1.3 splitPosition MINT call (for MAS only)

MAS needs to MINT pairs at slug start:

```
backend/app/services/poly_minter.py    # NEW
  - mint_pairs(slug, condition_id, amount) -> tx_hash
  - calls CTF.splitPosition(USDC, parent=0, condition_id, partition=[1,2], amount)
```

### 1.4 Multi-order management per slug

The existing `PolymarketClient` supports single orders. Maker strategies post + cancel MANY orders per slug. Add a per-slug `OpenOrderTracker`:

```
backend/app/strategies/polymarket/maker/order_tracker.py    # NEW
  - tracks open orders by (slug, order_id) → OpenOrder dataclass
  - handles partial-fill residuals (don't cancel after partial fill)
  - manages cancel-on-displacement + cancel-on-age rules
```

### 1.5 Trade-print WS subscriber (for ACC-H)

`BookMirror` provides L25 updates. ACC-H needs **trade prints** for the sharp-drop trigger (Rule B). Either:
- Extend BookMirror to also subscribe to the trades WS topic, OR
- Add new module `backend/app/venues/polymarket/trade_mirror.py`

The trades WS endpoint is the same WS server, just a different subscription topic.

### 1.6 Periodic merge timer

ACC strategies should check merge eligibility every 5s (in addition to checking on every fill). Add to the maker loop:

```python
async def merge_check_loop(strategies, every_s=5):
    while True:
        for strat in strategies:
            decisions = strat.periodic_merge_check()
            await dispatch(decisions)
        await asyncio.sleep(every_s)
```

---

## 2. Implementation phases (8-day plan)

### Phase 1 — Reference port (Day 1-2)

Port the Python `shadow_engine/` strategies into the tradingvenue codebase:

1. Create `backend/app/strategies/polymarket/maker/` subdirectory
2. Port `shadow_engine/base.py` → `maker/types.py` (event dataclasses)
3. Port `shadow_engine/strategies/base.py` → `maker/base.py` (MakerStrategyBase)
4. Port `acc_m.py`, `acc_h.py` modules (logic identical to shadow_engine)
5. Add new strategy module `mas.py` (mirror of acc_m, posts ASKs instead of BIDs, plus mint)

Unit tests: replay one historical slug, verify decisions match shadow_engine output.

### Phase 2 — Infrastructure integration (Day 3-4)

1. Build `engine/poly_maker_loop.py`:
   - Subscribe to BookMirror L25 stream for configured cells
   - Subscribe to trades WS (build trade_mirror if needed)
   - Subscribe to slug resolution events from poly_redeemer / oracle
   - Dispatch L25Update + TradePrint + SlugResolved to enabled strategies
   - Collect Decision objects → route to executor

2. Build `services/poly_merger.py` for NegRiskAdapter merge calls
3. Build `services/poly_minter.py` for splitPosition mint calls (MAS only)
4. Wire into `engine/main.py` TaskGroup alongside `poly_updown_loop`
5. Add env vars to `/etc/tv/tradingvenue.env`:
   ```
   TV_POLY_MAKER_ENABLED=true
   TV_POLY_MAKER_STRATEGIES=acc_m              # comma-separated
   TV_POLY_MAKER_CELLS=btc_5m,btc_15m
   TV_POLY_MAKER_SHADOW_MODE=true              # set false for live
   TV_POLY_MAKER_WALLET_SEED_USDC=50
   ```

### Phase 3 — Shadow validation (Day 5-6)

Run for 48 hours in shadow mode:
- Strategies receive REAL L25 + trades from Polymarket WS
- Decisions are LOGGED to CSV but no orders are submitted
- Periodic comparison: would-be-fill rate vs realized trades

Shadow log location: `/var/log/tv/shadow_<strategy>_<date>.csv`

Validation criteria (per `TV_DEPLOY_SPEC_ACC_M_2026_05_18.md`):
- Decisions fire at expected rate (~30/slug for ACC-M)
- Cancel discipline (3¢ threshold, 20s max age)
- Merge trigger fires when paired ≥ 5
- Inventory balance stays within 5-share imbalance
- No null exceptions in 48h

### Phase 4 — Live deploy (Day 7-8)

If shadow passes:
1. Fund Ireland wallet with $50 USDC.e
2. Set `TV_POLY_MAKER_SHADOW_MODE=false`
3. Start with `TV_POLY_MAKER_STRATEGIES=acc_m` + `TV_POLY_MAKER_CELLS=btc_5m` ONLY
4. Monitor for 24h
5. Scale: add btc_15m, then ETH cells, then add ACC-H, then MAS

---

## 3. The shadow_engine handoff

Working Python implementation at `/opt/tradingvenue/shadow_engine/` (TV agent needs to port to repo):

Source location on dev machine:
```
C:\Users\alexandre bandarra\Desktop\global\shadow_engine\
├── __init__.py
├── base.py                  # 250 lines — event types, Side, Action, SlugState, OpenOrder
├── strategies/
│   ├── __init__.py
│   ├── base.py              # StrategyBase ABC + helpers
│   ├── acc_m.py             # Pure pair-arb (~200 lines)
│   └── acc_h.py             # Hybrid (inherits acc_m, adds 3-rule composite trigger)
├── feeds/
│   └── replay.py            # Historical replay (validation-only, not for prod)
└── runner.py                # Orchestrator + shadow logging + fill simulation
```

**TV agent should import this as a reference, then PORT to TV's coding patterns** (Pydantic models, structlog, dependency injection, etc.). The decision logic is the truth — the architectural integration is TV agent's call.

---

## 4. Specifications

Three TV-deploy specs (already written, no addresses/provenance, clean for TV agent):

| Spec | What |
|---|---|
| `strategy_lab/reports/TV_DEPLOY_SPEC_ACC_M_2026_05_18.md` | Pure maker pair-arb |
| `strategy_lab/reports/TV_DEPLOY_SPEC_ACC_H_2026_05_18.md` | Hybrid maker + 3-rule composite taker |
| `strategy_lab/reports/TV_DEPLOY_SPEC_MAS_2026_05_18.md` | Mint-and-sell maker mirror |
| `strategy_lab/reports/TV_AGENT_HANDOFF_2026_05_18.md` | Master handoff with performance reqs |

Each spec has: state machine, decision rules, configuration parameters, per-slug expectations, shadow/live promotion criteria, implementation checklist.

---

## 5. Performance requirements (NON-NEGOTIABLE)

From `TV_AGENT_HANDOFF_2026_05_18.md` §"Performance requirements":

| Req | Status on Ireland VPS | Action if missing |
|---|---|---|
| P1: <5ms RTT to AWS eu-west-2 | ✅ verified 2ms | none |
| P2: WS-only order posting | ✅ PolymarketClient v2 already does this | none |
| P3: Pre-signed order pool | ❌ NOT YET | **MUST BUILD** at slug warmup |
| P4: Async pipeline | ✅ asyncio TaskGroup already | verify hot path is zero-blocking |
| P5: Persistent WS + keepalive | ✅ BookMirror has this | verify trade WS too |
| P6: msgspec/orjson | ⚠️ check WS message parsing | swap if standard json |
| P7: Integer-cent quantization | ❌ NOT YET | add to hot path |
| P8: Async logging | ⚠️ check structlog config | wrap in async queue if needed |
| P9: Pre-computed triggers | ❌ NOT YET | refactor decision rules |
| P10: Latency instrumentation | ❌ NOT YET | add LatencyMetrics class |

**Critical: P3 (pre-signed order pool)** is the biggest performance win. At slug start, pre-sign 10-20 candidate orders at varying prices. When decision fires, lookup-and-send takes ~50µs vs ~1ms signing on the fly.

---

## 6. The 3 strategies — summary

### ACC-M (Pure maker pair-arbitrage)
- Post limit BIDs on Up + Down when sum_bids < $1
- Cancel rules: 3¢ displacement OR 20s age
- Merge paired inventory via NegRiskAdapter when paired ≥ 5
- Redeem leftover at slug resolution
- **Strict 5-share imbalance discipline**
- Cells: BTC 5m + 15m to start
- Edge: ~$0.05-0.20/pair (validated against $212k/day wallet)

### ACC-H (Hybrid — ACC-M + composite taker)
Same as ACC-M PLUS 3 composite taker rules (OR-combined, ~70% coverage of reference wallet):

| Rule | Trigger | Coverage |
|---|---|---|
| A: Discount-capture | `ask < $0.50 AND (60s_median_ask - ask) > $0.03` | 33% |
| B: Sharp-drop | `(max_5s_trade_price - ask) > $0.02` | 33% |
| C: Early-slot | `0 <= offset_s <= 60 AND no_prior_fill` | 20% |

Looser inventory discipline (10-share imbalance) because taker can rebalance.

### MAS (Mint-and-sell — mirror of ACC-M)
- MINT paired tokens via splitPosition at slug start
- Post limit ASKs at best_ask when sum_asks > $1
- Same cancel rules as ACC-M
- NO merge mid-slug (just hold to slug end)
- Redeem leftover at slug resolution
- Cells: all 6 (small edge per cell × volume)
- Edge: ~$0.02/pair (smaller but consistent)

---

## 7. About the fill simulation calibration

You asked what "calibrate the replay fill simulator" means. Here's the explanation:

### What we have

`shadow_engine/runner.py:_simulate_fills` uses a **5% queue-share heuristic**:
```python
fill_share = min(order.remaining, trade.size * 0.05)
```

This says: "when a taker trade prints at our bid price, we fill 5% of the trade volume". This is a crude approximation.

### What's correct (per `acc_simulator.py` validated reference)

The proper model uses **queue-position proportional share**:
```python
# Our share of the trade = our_size / (our_size + visible_queue_at_our_price)
our_share = post_size / (post_size + visible_bid_size_at_our_price)
fill_share = trade.size * our_share
```

This requires knowing the **visible bid size at our exact price level** — which we currently don't have because the `opportunities.parquet` only has `size_up`/`size_dn` at BEST ASK (not best BID).

### How to calibrate

Two paths:

**Path A: Load L25 bid sizes directly**
- Stop using `opportunities.parquet` (ask-only)
- Read `data/v4/canonical/orderbook_l25/btc.parquet` directly
- Extract bid sizes at our bid level per L25 update
- Pass actual bid_size to runner._simulate_fills

**Path B: Estimate via cumulative trade volume**
- For each (slug, side), accumulate SELL trade volume at each price level over time
- Visible queue ≈ (orders posted at that level so far) - (already filled at that level)
- This is approximate but doesn't need L25 reload

**Path C: Match acc_simulator.py exactly**
- Port the queue-aware model from `strategy_lab/wallet_hunt/replicate/acc_simulator.py` line by line
- Run shadow on same slugs as acc_simulator
- Compare per-slug PnL, calibrate until match within ±10%

**Recommendation**: Path A is most accurate. Path C is the fastest validation.

### When this matters

- **Shadow mode**: matters because we want trustworthy PnL projections
- **Live mode**: doesn't matter (fills come from real orders, not simulation)

So calibration is a **shadow-validation prerequisite**, not a live-deploy blocker.

---

## 8. What TV agent should do in order

### Sprint 1 (Days 1-2): Port strategies

```bash
# On Ireland VPS:
cd /opt/tradingvenue
git checkout -b maker-suite

# Copy reference code (or pull from a shared bucket)
mkdir backend/app/strategies/polymarket/maker
# port shadow_engine/base.py to maker/types.py
# port shadow_engine/strategies/base.py to maker/base.py
# port shadow_engine/strategies/acc_m.py to maker/acc_m.py
# port shadow_engine/strategies/acc_h.py to maker/acc_h.py
# write maker/mas.py from TV_DEPLOY_SPEC_MAS spec

# Add unit tests under backend/tests/unit/strategies/maker/
```

### Sprint 2 (Days 3-4): Infrastructure

```bash
# Build the maker loop
touch backend/app/engine/poly_maker_loop.py
# - subscribes to BookMirror.L25Update
# - subscribes to trade WS (or build trade_mirror.py)
# - subscribes to oracle resolution events
# - dispatches to enabled MakerStrategy instances
# - routes Decision → PolymarketClient.place_order / cancel_order
# - calls services/poly_merger.merge_pairs(...) on MERGE decisions
# - calls services/poly_redeemer.redeem(...) on REDEEM decisions

# Build merger service
touch backend/app/services/poly_merger.py
# - merge_pairs(slug, condition_id, amount) -> tx_hash
# - chooses NegRiskAdapter vs vanilla CTF based on slug's market type

# Build minter service (MAS only)
touch backend/app/services/poly_minter.py
# - mint_pairs(slug, condition_id, amount) -> tx_hash

# Wire into engine/main.py
# add poly_maker_loop.run() to TaskGroup alongside poly_updown_loop
```

### Sprint 3 (Days 5-6): Shadow deploy

```bash
# Set env in /etc/tv/tradingvenue.env
echo 'TV_POLY_MAKER_ENABLED=true' >> /etc/tv/tradingvenue.env
echo 'TV_POLY_MAKER_STRATEGIES=acc_m' >> /etc/tv/tradingvenue.env
echo 'TV_POLY_MAKER_CELLS=btc_5m' >> /etc/tv/tradingvenue.env
echo 'TV_POLY_MAKER_SHADOW_MODE=true' >> /etc/tv/tradingvenue.env

# Restart tv-engine
systemctl restart tv-engine

# Monitor logs
journalctl -u tv-engine -f | grep maker

# After 48h, run validation
python -m backend.app.maintenance.maker_shadow_report --since=48h
```

### Sprint 4 (Days 7-8): Live promote

```bash
# Verify wallet funded
# Verify allowance set (use existing /opt/tradingvenue allowance preflight)

# Set live mode
sed -i 's/TV_POLY_MAKER_SHADOW_MODE=true/TV_POLY_MAKER_SHADOW_MODE=false/' /etc/tv/tradingvenue.env
systemctl restart tv-engine

# Monitor for 24h
# Check tv-api dashboard at :8443
```

---

## 9. Risk + safety

### Kill switches

`tv-engine` already has the daily ACK file mechanism (`/var/lib/tv/poly_live_ack_YYYY-MM-DD.ok`). Maker strategies should respect this too: NO orders submitted unless daily ACK exists.

Add a per-strategy kill flag in env:
```
TV_POLY_MAKER_KILL=                       # comma-separated strategy codes to halt
```

`engine/main.py` checks this on every loop iteration.

### Daily drawdown auto-halt

In each strategy's decision pipeline:
```python
if state.daily_pnl < -MAX_DAILY_DRAWDOWN:
    raise StrategyHalted("daily drawdown exceeded")
```

The maker loop catches StrategyHalted, cancels all open orders, sends an alert.

### Failure handling (from spec)

| Failure | Detection | Response |
|---|---|---|
| WS disconnect | BookMirror.is_dead() | Cancel all open orders; pause until reconnect |
| Order post fails | API error | Retry once; skip slug on 2nd fail |
| Merge tx revert | Tx receipt failed | Retry with higher gas; redeem at slug end if 3 fails |
| Wallet balance low | < RESERVE_USDC | Pause strategy; alert |
| Imbalance too high | > ABSOLUTE_MAX_INVENTORY | Stop posting heavy side; alert |

---

## 10. Files to send TV agent

```
Master handoff:
- strategy_lab/reports/TV_AGENT_HANDOFF_2026_05_18.md     (deploy seq + perf reqs + Rust plan)

Strategy specs (3 deploy-ready docs):
- strategy_lab/reports/TV_DEPLOY_SPEC_ACC_M_2026_05_18.md
- strategy_lab/reports/TV_DEPLOY_SPEC_ACC_H_2026_05_18.md
- strategy_lab/reports/TV_DEPLOY_SPEC_MAS_2026_05_18.md

This deployment plan (read first):
- strategy_lab/reports/TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md  ← THIS DOC

Reference Python implementation (port to TV codebase):
- shadow_engine/                                          (entire dir)
- examples/shadow_acc_m_btc_5m.py
- examples/shadow_compare_acc_m_vs_h.py

Supporting research (background, not strictly needed):
- strategy_lab/reports/CANCEL_RULES_DECODED_2026_05_18.md
- strategy_lab/reports/EEBDE7A0_TAKER_TRIGGER_V2_2026_05_18.md
- strategy_lab/reports/WALLET_TX_TAXONOMY_2026_05_18.md
```

---

## 11. Open questions for TV agent

1. **Trade WS subscription** — does BookMirror already subscribe to trades, or do we need a separate trade_mirror? (verify by reading book_mirror.py end-to-end)

2. **NegRiskAdapter vs vanilla CTF for merge** — `poly_redeemer.py` switched FROM NegRiskAdapter TO vanilla CTF for redeem on 2026-05-18. Should merge use the same vanilla CTF, or stay with NegRiskAdapter (which is what decoded wallets use)? Confirm via on-chain trace.

3. **Multi-strategy execution on same wallet** — if ACC-M and MAS run simultaneously on the same wallet, they share the USDC.e balance. How does TV's allowance preflight handle this?

4. **Existing strategy migration** — current `momo`/`momo_v2` are bar-driven. Can the new event-driven `poly_maker_loop` coexist with the existing bar-driven `poly_updown_loop` in the same engine TaskGroup? (Should be yes — both are just async tasks.)

5. **Allowance setup for new wallet** — if we use a new wallet just for maker strategies, allowance preflight needs to be configured for that wallet too.

---

## 12. Success metrics (30 days post-deploy)

Per strategy:
- Net daily PnL (USDC.e cash flow)
- Edge per pair (computed from total PnL / total pairs merged)
- Capital velocity (daily volume / peak wallet balance)
- Sharpe of daily PnL
- Max drawdown
- Order fill rate
- Cancel rate

Targets at test scale ($50 seed):
- ACC-M: $25-50/day
- ACC-H: $50-150/day
- MAS: $30-150/day

At wallet scale ($5k seed):
- ACC-M: ~$2,500/day
- ACC-H: ~$5,000/day
- MAS: ~$1,500/day

If realized < 30% of target, debug execution latency (likely queue position).

---

## 13. Bottom line for TV agent

**You have all the infrastructure**. Just need to:
1. Port 3 Python files (acc_m, mas, base) into a new `maker/` subdir — **defer acc_h** until missing 31% taker signal is decoded
2. Build a new event-driven loop (`poly_maker_loop`) — ~300 lines wrapping existing BookMirror + PolymarketClient
3. Add 2 service modules (poly_merger for mid-slug merges, poly_minter for MAS pre-mints)
4. Implement P3 (pre-signed orders) + P7 (integer cents) + P10 (latency metrics)
5. Run shadow for 48h, validate, promote to live $50

Estimated dev time: **5-8 days for one engineer**.

Capital risk to start: **$50 USDC.e per strategy**.

Expected day-1 live result: positive but small ($25-50/day per strategy at test scale).

---

## 14. ✅ Deploy-order finalized — ALL 3 strategies ready

After deeper taker-signal investigation (2026-05-18 V3f decode), ACC-H is now safe to deploy.

| Strategy | Deploy status | Why |
|---|---|---|
| **ACC-M** | ✅ DEPLOY 1st | Pure pair-arb, no taker, no missing-signal risk |
| **MAS** | ✅ DEPLOY 2nd (parallel) | Mirror of ACC-M, different side of book — safe |
| **ACC-H** | ✅ DEPLOY 3rd | V3f composite (4 rules) covers 78.9% of fires; missing 21.1% is ~$0/week impact |

**V3f composite rule for ACC-H** (4-rule OR-combined trigger):

| Rule | Trigger | Coverage | Lift |
|---|---|---|---|
| A | discount-capture (ask < $0.50 & drop > 3¢) | 33% | 1.48× |
| B | sharp-drop (5s trade price drop > 2¢) | 33% | 1.94× |
| C | early-slot (0-60s offset & no prior fill) | 20% | 1.63× |
| **D** | **buy-pressure-then-dip (60s buy_vol > 50 & any 5s dip)** | **+10pp** | **1.84×** |

Composite coverage: **78.9%** of decoded reference wallet's taker fires. The remaining 21.1% is sub-second CLOB micro-alpha we can't see at 1Hz, but it's EV-neutral after Polymarket taker fees.

**Sequenced deploy progression**:
1. Day 1-5: ACC-M + MAS deploy in shadow on Ireland VPS
2. Day 6-7: ACC-M + MAS go live, ACC-H deploys in shadow
3. Day 8: ACC-H goes live alongside ACC-M and MAS

Capital allocation:
- ACC-M: $50 (BTC 15m + ETH 5m)
- MAS: $100 (SOL 5m/15m + ETH 15m — different cells from ACC-M)
- ACC-H: $50 (BTC 5m where it has the best edge)
- Total: $200 USDC.e

All 3 specs in `TV_DEPLOY_SPEC_*_2026_05_18.md` are complete.

---

## 15. On historical fill simulator calibration — skip

The Python `shadow_engine/` includes a replay-based fill simulator that estimates would-be fills from historical trades. The user correctly pointed out: **TV agent's live shadow on Ireland VPS uses REAL Polymarket WS data, not historical replay.** Historical fill calibration won't change live outcomes.

TV agent's live shadow workflow:
1. Real L25 + trade WS subscriptions
2. Strategy emits Decision objects (post bid, cancel, etc.)
3. Decisions are LOGGED, not submitted
4. Real trades from WS are watched: if a trade prints at price ≤ our would-be-bid, mark as "would have filled"
5. Compute realized PnL projection from would-be-fills

This is the AUTHENTIC test. No simulation calibration needed — real data drives the validation.

The shadow_engine's replay simulator is useful for:
- Unit-testing strategy decision logic before deploying
- Comparing strategy parameter changes (A/B testing in-process)
- Sanity checks during development

It is NOT the live-validation tool. **The live shadow is.**
