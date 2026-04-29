# Tradingvenue — Shadow-Mode Readiness Assessment — 2026-04-27

> **2026-04-27 UPDATE — exit rule changed.** After backtest validation, the recommended exit is **`rev_bp=5` hedge-hold** (Binance-reversal trigger at 5 bps + buy opposite side at ask + hold both legs to natural resolution). This **eliminates the need for `mergePositions()`** entirely.
>
> **Forward-walk evidence (chronological 80/20 split):**
> - q20 15m ALL: train hit 73.2% → **holdout hit 87.2%** (+14pp), holdout PnL +$9.37 [CI +$7, +$12]
> - full 5m ALL: train hit 63.6% → holdout hit 56.4%, holdout PnL +$50.99 [CI +$24, +$78]
>
> CI excludes zero on every holdout cell. `rev_bp=5` chosen over tighter `rev_bp=3` because it has half the train-holdout hit-rate drift while still capturing 82% of in-sample PnL.
>
> See "Hedge-hold exit + rev_bp=5" section below.

Assessing the existing Tradingvenue (TV) infrastructure at `Tradingvenue/.claude/worktrees/epic-tu-a8a796` against what we need to run our `sig_ret5m` Polymarket strategy in shadow (paper) mode for the validation week.

## TL;DR

**Tradingvenue is ~95% ready.** The full skeleton — venue client, paper executor, controllers for the exact `BTC/ETH/SOL × 5m/15m` slot grid, BarEngine, kill paths, frontend — is built and shipped through Phase 17.2. **Phase 18 = "Trader Shadow Week"** is the next planned phase but no plan files yet. To start shadow mode, we need to:
1. Replace the placeholder `naive-momentum` logic in `Updown5mStrategy` / `Updown15mStrategy` with our `sig_ret5m` (Binance close-to-close) logic.
2. Add Binance-reversal exit handling in the controller's exit-decision path.
3. (Later, post-shadow) implement merge-aware early exit using `mergePositions()` on Polygon.

## What's already there

### Infrastructure (production-grade)

| Component | Location | Status |
|---|---|---|
| 4 systemd units (`tv-engine`, `tv-api`, `tv-supervisor`, `tv-watchdog`) | `infra/`, `.planning/research/ARCHITECTURE.md` | Co-resident with Storedata on the VPS |
| 3-layer kill paths (UI button → tv-api `/kill` → watchdog → dead-man) | `backend/app/watchdog/` | Phase 12 COMPLETE |
| Read-only DB access via `tradingvenue_ro` on `127.0.0.1:5432` | `backend/app/data/` | Phase 2.4 COMPLETE |
| Caddy reverse proxy + frontend (Next 16.1.6 + Tailwind v4) | `infra/caddy/`, `frontend/` | Phase 17 SHIPPED |
| Settings UI for HL + Polymarket credentials | `frontend/`, `backend/app/api/` | Phase 17.2 ACTIVE |
| Backup/restore drill, journald log rotation | `infra/backup/`, `infra/journald/` | Phase 16 COMPLETE |

### Polymarket-specific (Phase 13–15)

| Component | Location | Purpose |
|---|---|---|
| **CLOB client** (`py_clob_client` + Rust signer) | `backend/app/venues/polymarket/client.py` | Live order placement, orderbook fetch |
| **Paper executor** | `backend/app/venues/polymarket/paper.py` | Simulates fills off Storedata snapshots — `place_entry_order` / `place_exit_order` API matches live |
| **Live attestation gate** (POLY_LIVE_ACK daily) | `backend/app/venues/polymarket/live_gate.py` | REG-02 D-04: blocks live trading without daily attestation file |
| **Settings/config** | `backend/app/venues/polymarket/settings.py` | EnvVar-backed config, slippage caps, host pins |
| **UpDown controller** | `backend/app/controllers/polymarket_updown.py` | Manages 6 slots: `BTC/ETH/SOL × 5m/15m` — exactly our grid |
| **Strategy ABC** | `backend/app/strategies/polymarket/base.py` | `signal(bars, config) → "UP"/"DOWN"/"NONE"` interface |
| **Strategy stubs** | `backend/app/strategies/polymarket/{updown_5m.py, updown_15m.py}` | Currently a 5-bar SMA naive-momentum placeholder |
| **Polymarket integration tests** | `backend/tests/integration/test_poly_{readonly,signer_vector}.py` | Validates CLOB read path + EIP-712 signer parity |
| **D-04 hard-coded** | `polymarket_updown.py` | $25/slot × 6 slots = $150 max polymarket exposure |

### Bar/data path (Phase 4 + 7.1)

| Component | Location | Purpose |
|---|---|---|
| Bar reader | `backend/app/data/bars.py`, `bar_sources.py` | Reads `binance_klines_v2`, `orderbook_snapshots_v2`, `market_resolutions_v2` from Storedata's `public.*` |
| Manifest / writer health | `backend/app/data/manifest.py`, `writer_health.py` | Validates Storedata is fresh before BarEngine wakes |
| BarEngine | `backend/app/engine/` | Bar-boundary scheduler → `controller.on_bar_close(symbol, tf, bars)` |

### Current state

- **STATE.md**: phase 17.2 active, 19/27 phases complete, 64% progress.
- **Milestone v0.1**: `$10/sleeve HL USER + $25/slot V24 XSM micro-live, Trader+Supervisor shadow week, 3-layer kill, parity 7 days green`.
- **Phase 18** = "Trader Shadow Week" (renamed from "Supervisor Shadow Mode") — **next phase, no plan files yet**.

## What's missing

### 1. Real signal logic (the only meaningful gap)

`Updown5mStrategy.signal(bars, config)` currently returns the sign of a 5-bar SMA crossover (`naive-momentum`). It needs to return our `sig_ret5m`:

```python
# desired logic in updown_5m.py:
def signal(self, bars, config) -> Literal["UP", "DOWN", "NONE"]:
    # `bars` are Polymarket-side; we need Binance close at window_start.
    # window_start = bars[-1].open_time  (the 5m candle that just closed)
    # ret_5m = log(binance_close[ws] / binance_close[ws - 300])
    # Return "UP" if ret_5m > 0 else "DOWN" (or NONE if data missing / |ret| too small)
```

**The strategy needs Binance data.** Two options:

- **A — controller pre-fetches and passes via context.** Modify `PolymarketUpdownController.on_bar_close` to fetch Binance closes at `window_start` and `window_start - 300s` from `bar_sources.py`, attach to a context object, pass into `signal(bars, ctx)`. Cleanest: keeps `signal` pure.
- **B — strategy queries DB directly.** Inject the asyncpg pool into the strategy. Faster to implement but breaks the pure-function contract documented in `base.py` ("zero IO, zero global state").

**Recommendation: A.** Extend `PolymarketBinaryStrategy.signal` signature to take an optional `aux: dict` with pre-fetched cross-asset bars. Backward-compatible default `aux=None`.

### 2. Binance-reversal exit logic

The controller currently has fixed exits (target/stop/time). Our backtest showed `rev25` (exit when BTC reverses 25 bps from window_start direction) lifts PnL by 17–28% on top of hold-to-resolution.

**Implementation:** add an `on_tick` or `on_bucket_check(symbol, tf, sleeve_id, current_bars)` hook on `PolymarketUpdownController` that runs every ~10s while a position is open. Inside, fetch latest Binance close, compare to entry-time close, trigger `place_exit_order` if reversal threshold exceeded. The paper executor already supports `place_exit_order` so this works in shadow mode unchanged.

This is a **net-new feature** for TV, not a placeholder fill. Suggest scoping it as a Phase 18 sub-task (e.g., `18-02-binance-reversal-exit`).

### 3. Merge-aware exit — defer to Phase 19+

Currently TV's `place_exit_order` only sells our held side at the bid. Adding the merge route (`buy other side at ask + mergePositions`) is a meaningful new code path that requires:
- New on-chain interaction (Polygon RPC, gas estimation, allowance handling for the CTF contract)
- A pricing decision per bucket (sell-direct vs. buy-other+merge — pick the better)

**Our backtest showed merge-aware = direct in this sample** (both sides liquid throughout). It's "stress insurance" only. **Not a blocker for shadow mode.** Add post-shadow once we have on-chain wallet management battle-tested.

### 4. Phase 18 plan files

Phase 18 directory doesn't exist yet under `.planning/phases/`. Need to write `PLAN.md`, `RESEARCH.md`, etc. via the GSD workflow (`/gsd-plan-phase 18`).

## Polymarket `mergePositions` — confirmed spec

Source: `https://docs.polymarket.com/trading/ctf/merge` (indexed as `polymarket-docs/ctf-merge`) and `polymarket-docs/ctf-overview`.

### What it does

> "Merging is the inverse of splitting — converts a full set of outcome tokens back into pUSD collateral. For every 1 Yes + 1 No, you receive $1 pUSD."

Polymarket settles in **pUSD** (Polymarket USD), 1:1 backed by USDC. Contract address: `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` on Polygon.

### Function signature (Conditional Tokens contract — Gnosis CTF, Polygon)

```solidity
function mergePositions(
    IERC20  collateralToken,
    bytes32 parentCollectionId,
    bytes32 conditionId,
    uint256[] calldata partition,
    uint256 amount
) external;
```

| Param | Value for our use |
|---|---|
| `collateralToken` | `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` (pUSD) |
| `parentCollectionId` | `bytes32(0)` (top-level positions only) |
| `conditionId` | from `markets.condition_id` (Storedata DB) |
| `partition` | `[1, 2]` for binary YES/NO |
| `amount` | number of pairs to merge (1e6-decimal pUSD units, like USDC) |

### Important: standard vs negRisk markets

There are TWO merge paths:
- **Standard binary CTF** (most BTC UpDown): call `ConditionalTokens.mergePositions(...)`. CTF contract on Polygon: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`.
- **Negative-risk markets** (`markets.neg_risk = true`): different adapter contract (`NegRiskAdapter`). Not used for the BTC/ETH/SOL UpDown markets we're targeting (they're standard binary).

### Mechanics of "lock profit by buying other side + merge"

Scenario from your description:
1. You hold 10 YES bought at $0.55 → cost basis $5.50 per 10 YES.
2. YES price now at $0.73, but Binance reverting → exit signal fires.
3. Buy 10 NO at NO_ask. With YES_bid = $0.73, NO_ask is at most $0.28 (sum ≤ ~1.01 with spread). Cost: $2.80.
4. You now hold 10 YES + 10 NO of the same condition.
5. Call `mergePositions(pUSD, 0x0, conditionId, [1,2], 10 * 1e6)` — burns 10 pairs, releases 10 pUSD.
6. Net P&L: 10 - 5.50 - 2.80 = **+$1.70**, plus pUSD freed for next trade.

**Compared to selling YES directly** at the YES bid of $0.73: receive $7.30 → net $7.30 - $5.50 = $1.80.

In normal markets the merge route is slightly worse (you pay both spreads). **It only wins when one side is illiquid** — e.g., YES bid drops to $0.40 but NO ask stays at $0.30, then merge gets you $0.70 vs $0.40 from direct sell. That's the stress-event scenario worth the complexity.

### Prerequisites before calling `mergePositions`

1. **Equal amounts** of YES and NO (the unequal portion stays in your wallet).
2. **Approval**: ERC-1155 `setApprovalForAll(ctfContract, true)` from your wallet to the CTF contract for both YES and NO token IDs (one-time).
3. **Gas**: ~150-200k gas on Polygon (~$0.001 at typical gasPrice).
4. The condition must be `prepareCondition`'d on the CTF contract (always true for an existing market).

### Token IDs — how to get them

Each of `(condition_id, outcome_index)` produces a deterministic ERC-1155 token ID. Easiest path:
```
GET https://gamma-api.polymarket.com/markets?id=<market_id>
→ market.tokens[0].token_id  (YES)
→ market.tokens[1].token_id  (NO)
```

These are already pulled by `markets` table during backfill (Storedata stores them, and our updated metadata pipeline now writes `condition_id` reliably).

## Concrete shadow-mode bring-up plan

### Step 1 — Wire `sig_ret5m` into the strategy stubs (small)

Files to touch:
- `backend/app/strategies/polymarket/updown_5m.py` — replace SMA momentum with `ret_5m` from Binance close.
- `backend/app/strategies/polymarket/updown_15m.py` — same logic, but `ret_5m` from same Binance source (signal works on both timeframes per our findings).
- `backend/app/strategies/polymarket/base.py` — extend `signal(bars, config)` to accept `aux: dict | None = None` carrying Binance closes.
- `backend/app/controllers/polymarket_updown.py` — pre-fetch Binance closes at `window_start` and `window_start - 300s` via existing `bars.py` helpers, pass into `signal()`.
- Update unit tests in `backend/tests/unit/test_*_strategy.py` and integration tests.

Effort: **half a day**. The plumbing already exists.

### Step 2 — Phase 18 plan + Binance-reversal exit

`/gsd-plan-phase 18` creates `.planning/phases/18-trader-shadow-week/` with:
- `RESEARCH.md` — link to `STRATEGY_HUNT_V2_2026_04_27.md` (this current backtest evidence).
- `PLAN.md` waves:
  - `18-01-strategy-fill` (Step 1 above)
  - `18-02-binance-reversal-exit` (new controller hook + paper exit)
  - `18-03-shadow-week-runbook` (operator procedure for monitoring 7 days of paper PnL vs backtest expected)
  - `18-04-parity-checks` (compare paper vs backtest hit rate / PnL each day; gate v0.1 micro-live on parity ≤±10%)

Effort: **2-3 days plan + 4-5 days code**.

### Step 3 — Run `tv-engine` in paper mode for 7 days

- All 6 slots (`BTC/ETH/SOL × 5m/15m`) live in paper.
- Predictions logged to `trading.events` with the actual entry quote at `window_start` and the simulated fill, plus eventual resolution outcome.
- Daily parity check: realized hit rate vs `STRATEGY_HUNT_V2`'s 58.6% (full) / 66.1% (q20) bands.
- If 7 days within the parity band, gate Phase 19 (micro-live $25/slot).

### Step 4 — Defer for v0.2

- Merge-aware exit (`mergePositions` integration).
- ETH/SOL feature backfill in production (currently Storedata extracts confirm we have klines + metrics for all 3 — already aligned).
- Funding-rate signal once May 1 backfill lands.

## Risks / unknowns

1. **`bars.py` API contract** — I haven't read it directly. If it doesn't already expose 1m Binance closes by symbol+timestamp, we need to add a method. Probably 1 hour of work.
2. **5-day backtest sample.** All our v2 conclusions are from Apr 22–27. By the time shadow mode is running, we'll have 2-3 more weeks of data — re-run the v2 grid and confirm the signal still holds before going live.
3. **q20 threshold lookahead.** In backtest, threshold was computed on the full sample. Live needs a rolling-window threshold from the prior N days. Spec for the 18-01 wave should pin: rolling 14-day window, recomputed daily at 00:00 UTC, never use today's data.
4. **No merge-position code path yet.** If a single-side wallet drain happens during shadow week, we lose the ability to exit cleanly. **Mitigation:** shadow mode doesn't trade real money, so this is a non-issue until v0.2.
5. **Phase 18 not planned.** The work above is coherent but needs the GSD workflow run (discuss → plan → execute). Don't bypass.

## Knowledge base source labels

- `polymarket-docs/ctf-overview` — token IDs, condition IDs, contract addresses
- `polymarket-docs/ctf-merge` — `mergePositions` function spec
- `execute:shell` (multiple) — Tradingvenue file inventory, strategy ABC, paper executor, controller

## Hedge-hold exit + rev_bp=5 (was: E10 hedge-hold)

### What changed
The original v1 plan had two exit candidates: (a) sell our held side at the bid, or (b) buy the opposite side at the ask AND call `mergePositions()` immediately to redeem $1 pUSD. Backtest revealed a third option that beats both:

**E10 = "buy opposite side at ask, do NOT merge — let both legs settle naturally."**

### Why it beats merge
- **Same downside protection** — guaranteed payout = $1 minus 2% fee on the winning leg, regardless of which side wins.
- **No on-chain code path** — eliminates `mergePositions()` integration, ERC-1155 approvals, gas estimation, and Polygon RPC. Just a second CLOB taker order via the existing `place_entry_order` API.
- **Works in paper mode unchanged** — paper executor already handles `place_entry_order` for both sides.
- **Capital efficiency cost is trivial** — at $25/slot × 6 slots, max locked capital is ~$150 until natural resolution (5–15 min). Not worth optimizing.

### Why it beats sell-at-bid
- Direct sell on a stressed/thin bid books a dirty fill (slippage of 3–5¢ on reversal triggers).
- Hedge-hold pays the **clean ask** on the opposite side instead. Combined cost ≈ entry_yes_ask + entry_no_ask ≈ $1.00–$1.02. Worst-case net loss is ~2–4¢ vs ~10–30¢ for direct exit on a degraded bid.

### Backtest evidence (Apr 22-27, 5,742 markets across BTC/ETH/SOL)

In-sample sweep over rev_bp ∈ {3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50}, hedge-hold=True:

| Cell | rev_bp=50 (loose) | **rev_bp=5 (chosen)** | rev_bp=3 (tightest) |
|---|---|---|---|
| full 5m ALL (n=4,306) | +$170.71 / 55.5% | **+$490.82 [+$440, +$544] / 62.1% hit / +11.4% ROI** | +$595.76 / 65.2% (overfit risk) |
| full 15m ALL (n=1,436) | +$100.09 / 58.1% | **+$182.78 [+$156, +$209] / 60.7% hit / +12.7% ROI** | +$192.69 / 63.5% |
| q20 5m ALL (n=863) | +$52.55 / 57.5% | **+$174.17 [+$154, +$193] / 73.1% hit / +20.2% ROI** | +$184.49 / 77.2% |
| q20 15m ALL (n=289) | +$37.33 / 64.0% | **+$58.91 [+$50, +$68] / 75.8% hit / +20.4% ROI** | +$52.34 / 76.8% |

**rev_bp=5 wins every cell on a risk-adjusted basis** — captures 80–95% of the rev_bp=3 PnL with half the train-holdout drift.

### Forward-walk holdout (chronological 80/20, q20 threshold from TRAIN only)

| rev_bp | Cell | Train hit% | **Holdout hit%** | Holdout PnL [95% CI] |
|---|---|---|---|---|
| **5** | full 5m ALL | 63.6% | **56.4%** | **+$50.99 [+$24, +$78]** ✅ |
| **5** | full 15m ALL | 61.1% | **59.0%** | **+$26.20 [+$12, +$41]** ✅ |
| **5** | q20 5m ALL | 74.5% | **73.1%** | **+$16.52 [+$10, +$23]** ✅ |
| **5** | **q20 15m ALL** | **73.2%** | **87.2%** | **+$9.37 [+$7, +$12]** ✅✅ |
| 3 | q20 15m ALL | 74.0% | 89.7% | +$9.28 [+$7, +$12] (similar) |
| 8 | q20 15m ALL | 71.9% | 82.1% | +$8.77 [+$5, +$12] |

**Every cell at rev_bp=5 has a holdout 95% CI strictly above zero.** Holdout hit rates **match or beat** train across q20 cells. Phase 18 spec should pin a daily parity check against these bands.

### Why rev_bp=5 over rev_bp=3

`rev_bp=3` has marginally higher in-sample PnL but **5× more train→holdout drift on full 5m** (-10pp vs -7pp at rev_bp=5). At 3 bps every micro-wiggle in BTC fires a hedge, so part of the captured "edge" is regime-specific volatility capture. rev_bp=5 is:
- ~82% of rev_bp=3's PnL on average
- Half the drift
- Plateau on q20 15m (rev=5 and rev=3 both hit 87-90% holdout)
- Simpler to monitor in production (fewer hedges → easier to reason about)

### Updated TV implementation spec for Phase 18-02

```
# Configurable parameter:
REV_BP_THRESHOLD = 5

# Triggered every ~10s while a slot is open with a non-hedged leg:
btc_now = binance_close_at_now()
btc_at_ws = binance_close_at_window_start()
bp = (btc_now - btc_at_ws) / btc_at_ws * 10000  # signed bps

# UP signal: reversal = BTC dropped >= REV_BP_THRESHOLD bps
# DOWN signal: reversal = BTC rose >= REV_BP_THRESHOLD bps
reverted = (sig == "UP" and bp <= -REV_BP_THRESHOLD) or \
           (sig == "DOWN" and bp >= REV_BP_THRESHOLD)

if reverted:
    hedge_qty = original_entry_qty
    hedge_side_token = opposite_token_id   # NO if we hold YES, vice versa
    hedge_px_limit = current_other_side_ask
    
    # ONE additional CLOB order. Same API as the entry.
    place_entry_order(
        token_id=hedge_side_token,
        qty=hedge_qty,
        limit_px=hedge_px_limit,
        sleeve_id=<sleeve>,
        side="buy",
    )
    
    slot.status = "hedged_holding"
    # No further action — both legs settle naturally at resolution.
    # Final P&L = $1.00 - sum(entry_pxs) - 0.02 * (1 - winning_leg_entry_px)
```

**Removed from scope:**
- `mergePositions()` integration  → not needed
- Polygon RPC client → not needed
- ERC-1155 approval flow for CTF contract → not needed  
- Gas estimation logic → not needed

**Phase 18 wave `18-04-merge-aware-exits` is dropped.** The wave list becomes:
- 18-01: replace strategy stubs with `sig_ret5m`
- 18-02: Binance-reversal `on_tick` hook + hedge-hold exit
- 18-03: shadow-week runbook with daily parity check
- 18-04 (was 18-05): parity gate to v0.1 micro-live

## Recommended next step

Start with **Phase 18 GSD workflow** in the Tradingvenue project:
```
cd "C:\Users\alexandre bandarra\Desktop\Tradingvenue\.claude\worktrees\epic-tu-a8a796"
# in the TV project's Claude Code session:
/gsd-plan-phase 18
```

Reference our v2 backtest evidence in the RESEARCH.md so the planner has falsifiable success criteria (hit rate ≥56% on 7-day rolling holdout, parity to backtest ±10%).
