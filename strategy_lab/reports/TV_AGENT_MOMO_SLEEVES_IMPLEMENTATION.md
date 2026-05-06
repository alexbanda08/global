# TV Agent: Implementation Guide — Momentum Sleeves (Shadow Mode)

**Recipient:** TV agent (Claude operating `/root/tv-bootstrap` and `/opt/tradingvenue` on VPS3 = `185.190.143.7`)
**Author:** Strategy lab (laptop)
**Date:** 2026-05-05 (revised after Phase 24 master-scheduler walkthrough)
**Goal:** Deploy **18 new shadow sleeves** = 3 assets × 2 tfs × 3 exit policies, exploiting the post-bar-close 2-min Binance latency window. **PAPER MODE ONLY.**
**Source backtests:**
- `EXIT_POLICY_TIER1.md` — microsecond-precise entries, 25-level depth (TIER 1 from VPS2 raw `orderbook_snapshots_v2`)
- `STRATEGY_LOGIC_AND_DATA_GAP.md` — strategy logic explainer
- `PNL_AUDIT.md` — confirmed real microstructure alpha (5 outliers ≠ artifacts)

---

## Phase scope

**Phase 1 (this doc)**: ship the 18 sleeves on the existing REST book-fetch path for shadow validation. Acceptable because exit-side book fetches are lazy (only fire on rev_bp triggers, not every tick) and `TV_POLY_PAPER_BOOK_CACHE_TTL=1s` caches per-tick re-fetches.

**Phase 2 (separate planning doc, follow-up)**: migrate Polymarket CLOB book to a WebSocket subscription with REST as fallback. Required for live trading — see `venues/hyperliquid/client.py` for the WS client pattern to mirror. Polymarket CLOB WS endpoint: `wss://ws-subscriptions-clob.polymarket.com/ws/market` with `book` + `price_change` channels. Out of scope for this implementation.

---

## 0 · Read this section first — what changed

I previously assumed the old wiring (`polymarket_updown_PROD_2026_05_05.py` style — single controller dispatched on bar close, fetches its own kline + book). Verified VPS3 today and the architecture has moved on:

| Aspect | Pre-Phase-24 | **Phase 24 (current, 2026-05-05)** |
|---|---|---|
| Dispatch | `on_bar_close(sym, tf, bars)` per controller | `on_bar_close(sym, tf, bars=[], bar_ctx=ctx)` — **BarContext shared across all registered controllers** |
| Kline fetch | each controller fetches its own | **`build_bar_context()` fetches once, all controllers read** |
| CLOB book fetch | each controller fetches its own /book | **shared `book_snapshot_yes`/`book_snapshot_no` per BarContext** |
| Sniper threshold samples | each controller computes (29s/call) | **`_SAMPLES_CACHE` keyed by `(symbol_id, tf, UTC day)` — first call/day pays cost, rest free** |
| Race fix | n/a | **eliminates V4-⊆-V3 violations** (`.planning/V4-SUBSET-BUG-VERDICT-2026-05-05.md`) |

Code refs (verified on VPS3):
- `backend/app/engine/poly_updown_loop.py:BarContext` (frozen dataclass, lines ~67-100)
- `backend/app/engine/poly_updown_loop.py:build_bar_context` (lines ~110-200)
- `backend/app/engine/poly_updown_loop.py:poly_updown_master_scheduler` (gated by `TV_POLY_USE_MASTER_SCHEDULER=true`, currently set on VPS3)
- `backend/app/controllers/polymarket_updown.py` (the controller — `_build_signal_aux` reads `self._bar_ctx_active` when present, else falls back to its own fetch)
- `backend/app/strategies/polymarket/updown_5m.py` + `updown_15m.py` — strategies are PURE: `signal(bars, config, aux) → "UP"|"DOWN"|"NONE"`. Same logic for both timeframes; the controller picks q90 (5m) vs q80 (15m).

Implications:
1. Adding a new strategy_mode = adding to `_valid_strategy_modes` tuple (controller line ~541) AND populating any new aux fields in `BarContext` and `_build_signal_aux`.
2. Adding a new exit policy = the engine already supports two: `HEDGE_HOLD` (V1) and `HYBRID` (V2 — falls through to `_try_bid_exit` = sell-at-bid when opposite-side ask book is empty). For pure HOLD, we need a new third value `HOLD_ONLY` that no-ops the on_tick exit path.
3. The current `HEDGE_POLICY` is module-level (env var, single value process-wide). For per-strategy_mode policies, we either need 3 separate envs (`TV_POLY_HEDGE_POLICY_MOMO_HOLD`, `..._HEDGE`, `..._SELL`) OR a per-controller override at construction. The latter is cleaner — see §3d.

---

## 1 · The new strategy class — `MomoStrategy`

### Why it's a new strategy, not a sniper variant

The existing `sniper` strategy_mode fires **AT bar close** on `ret_5m = log(BTC@ws / BTC@ws-300)` — i.e., the signal is the BTC return over the **5 minutes BEFORE** the market opened. This is what `aux["ret_5m"]` carries.

The momo strategy fires **AT t+120s of the new market** on `ret_2m = log(BTC@ws+120 / BTC@ws)` — i.e., the BTC return over the **first 2 minutes INSIDE** the market. Different time window, different signal.

For 5m markets, `ret_2m` consumes 40% of the market lifetime — leaves only 3 min for the bet to play out. For 15m markets it's 13% — leaves 13 min. This is why momo's hit rates differ between tfs.

### Backtest evidence (microsecond-precise entries, $25/slot, 2% fee, real book walk)

| Cell | n | hit% | HOLD total | HEDGE total | SELL total | avg vwap entry |
|---|---:|---:|---:|---:|---:|---:|
| BTC 5m  | 303 | 85.8% | $+3,748 | $+4,374 | $+4,390 | $0.696 |
| BTC 15m | 101 | 81.2% | $+1,000 | $+1,094 | $+1,115 | $0.615 |
| ETH 5m  | 270 | 90.4% | $+3,377 | $+3,571 | $+3,586 | $0.721 |
| ETH 15m |  95 | 73.7% |   $+433 |   $+780 |   $+799 | $0.655 |
| SOL 5m  | 238 | 89.5% | $+2,346 | $+2,687 | $+2,706 | $0.735 |
| SOL 15m |  70 | 84.3% |   $+673 |   $+693 |   $+705 | $0.665 |
| **TOTAL** | **1,077** | — | **$+11,577** | **$+13,200** | **$+13,300** | — |

Apply the V3 forward-walk haircut (~63% degradation from backtest to live) as a worst case → ~$4,800 over 12 days = **~$400/day** combined. Realistic mid-case (~30% haircut) → ~$9,300 over 12 days = **~$775/day**.

### Class signature (same `PolymarketBinaryStrategy` ABC)

Suggested location: `backend/app/strategies/polymarket/momo.py`.

```python
"""MomoStrategy — Binance latency-arbitrage at t+120s of each market."""
from __future__ import annotations
import math
from typing import TYPE_CHECKING, Literal

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy, SignalConfig, SignalResult,
)

if TYPE_CHECKING:
    from backend.app.data.models import Bar


class MomoStrategy(PolymarketBinaryStrategy):
    """Top-10% |ret_2m| gate; reads aux['ret_2m'] populated at t+120s.

    aux schema (NEW fields populated by extended _build_signal_aux):
      ret_2m                    -- log(close@ws+120 / close@ws)
      abs_ret_2m_threshold      -- rolling 14d q90 of |ret_2m|, daily cache
      bar_ctx_phase             -- 't_plus_120' (gate — only fire on the
                                   t+120s dispatch, NOT bar close)
    """

    name = "momo"

    def signal(self, bars, config=None, aux=None) -> SignalResult:
        if aux is None:
            return "NONE"
        # Only fire on the t+120s dispatch, never on bar-close
        if aux.get("bar_ctx_phase") != "t_plus_120":
            return "NONE"
        ret_2m = aux.get("ret_2m")
        if ret_2m is None or not math.isfinite(ret_2m):
            return "NONE"
        thr = aux.get("abs_ret_2m_threshold")
        if thr is None or abs(ret_2m) < thr:
            return "NONE"
        return "UP" if ret_2m > 0 else "DOWN"


__all__ = ["MomoStrategy"]
```

---

## 2 · The new dispatch event — `t_plus_120` boundary

### Problem

The master scheduler currently fires `on_bar_close` at every Polymarket-tf boundary (5m or 15m UTC-aligned). It does NOT fire at intermediate moments.

For momo, we need a SECOND dispatch event 120 seconds after each market opens. Options ordered by intrusiveness:

### Option A (recommended): Piggyback on the 1MIN bar dispatcher

The BarEngine already gets 1-minute Binance bars. We can register a sub-handler that fires when a 1-min bar closes at exactly `(some_market_window_start) + 120s`:

```python
# In poly_updown_loop.py — add to master scheduler

def _is_t_plus_120_for_5m(bar_close_ts_s: int) -> int | None:
    """If bar_close_ts_s == ws_s + 120 for some 5m market, return ws_s. Else None."""
    # 5m windows align to UTC 0/5/10/15/... minutes
    ws_candidate = bar_close_ts_s - 120
    if ws_candidate % 300 == 0:  # aligned to 5m boundary
        return ws_candidate
    return None

def _is_t_plus_120_for_15m(bar_close_ts_s: int) -> int | None:
    ws_candidate = bar_close_ts_s - 120
    if ws_candidate % 900 == 0:
        return ws_candidate
    return None
```

Add to the master scheduler's 1MIN bar handler:
```python
async def on_1min_bar_close(symbol: str, ts_s: int):
    for tf, checker in (("5m", _is_t_plus_120_for_5m), ("15m", _is_t_plus_120_for_15m)):
        ws_s = checker(ts_s)
        if ws_s is None:
            continue
        ctx = await build_bar_context_t_plus_120(primary, symbol, tf, ws_s)
        # Dispatch ONLY to momo controllers
        for ctrl in registered_momo_controllers:
            await ctrl.on_bar_close(symbol, tf, [], bar_ctx=ctx)
```

Note `build_bar_context_t_plus_120` is a NEW BarContext builder that:
1. Fetches `btc_at_ws` (close at ws_s) and `btc_at_t_plus_120` (close at ws_s + 120)
2. Computes `ret_2m` = log(btc_at_t_plus_120 / btc_at_ws)
3. Reads cached q90 threshold
4. Re-fetches CLOB book (it changed since bar-close!)
5. Sets `bar_ctx_phase = "t_plus_120"`

### Option B (simpler, slightly less precise): asyncio-delayed callback

In the existing `on_bar_close` handler, schedule a delayed task:
```python
async def on_bar_close(sym, tf, bars, bar_ctx):
    # ... existing handling for sniper/v3/etc.
    # If any momo controllers are registered, schedule t+120 fire:
    if any(isinstance(c, MomoController) for c in registered_controllers):
        asyncio.create_task(
            _fire_momo_at_t_plus_120(sym, tf, bar_ctx.ws_s)
        )
```

The delayed task waits 120 seconds, builds a fresh BarContext, dispatches to momo controllers.

Risk: if the engine restarts in the 120s window, the scheduled callback is lost. Tradeoff: a missed market once per restart. Acceptable for paper mode validation.

**Recommend Option B** for shadow validation (lower implementation risk). Migrate to A if going live.

---

## 3 · The 18 sleeves and their exit policies

### Sleeve definitions

| # | sleeve_id | strategy_mode | hedge_policy | symbol | tf |
|---:|---|---|---|---|---|
| 1  | `poly_updown_btc_5m_momo_HOLD`  | momo | HOLD_ONLY  | BTC | 5m  |
| 2  | `poly_updown_btc_5m_momo_HEDGE` | momo | HEDGE_HOLD | BTC | 5m  |
| 3  | `poly_updown_btc_5m_momo_SELL`  | momo | SELL_BID   | BTC | 5m  |
| 4  | `poly_updown_btc_15m_momo_HOLD`  | momo | HOLD_ONLY  | BTC | 15m |
| 5  | `poly_updown_btc_15m_momo_HEDGE` | momo | HEDGE_HOLD | BTC | 15m |
| 6  | `poly_updown_btc_15m_momo_SELL`  | momo | SELL_BID   | BTC | 15m |
| 7  | `poly_updown_eth_5m_momo_HOLD`  | momo | HOLD_ONLY  | ETH | 5m  |
| 8  | `poly_updown_eth_5m_momo_HEDGE` | momo | HEDGE_HOLD | ETH | 5m  |
| 9  | `poly_updown_eth_5m_momo_SELL`  | momo | SELL_BID   | ETH | 5m  |
| 10 | `poly_updown_eth_15m_momo_HOLD`  | momo | HOLD_ONLY  | ETH | 15m |
| 11 | `poly_updown_eth_15m_momo_HEDGE` | momo | HEDGE_HOLD | ETH | 15m |
| 12 | `poly_updown_eth_15m_momo_SELL`  | momo | SELL_BID   | ETH | 15m |
| 13 | `poly_updown_sol_5m_momo_HOLD`  | momo | HOLD_ONLY  | SOL | 5m  |
| 14 | `poly_updown_sol_5m_momo_HEDGE` | momo | HEDGE_HOLD | SOL | 5m  |
| 15 | `poly_updown_sol_5m_momo_SELL`  | momo | SELL_BID   | SOL | 5m  |
| 16 | `poly_updown_sol_15m_momo_HOLD`  | momo | HOLD_ONLY  | SOL | 15m |
| 17 | `poly_updown_sol_15m_momo_HEDGE` | momo | HEDGE_HOLD | SOL | 15m |
| 18 | `poly_updown_sol_15m_momo_SELL`  | momo | SELL_BID   | SOL | 15m |

The 18 sleeves run as **3 controllers** (one per hedge_policy variant), each managing 6 (symbol, tf) slots. Total open-slot budget: 3 × 6 = 18 slots × $25 = $450 paper notional.

### Controller-level exit-policy override (key change to existing code)

Currently `HEDGE_POLICY` is a module-level constant (line 157 of controller):
```python
HEDGE_POLICY = os.getenv("TV_POLY_HEDGE_POLICY", "HEDGE_HOLD").upper()
```

For per-controller variants, add a constructor arg:
```python
class PolymarketUpdownController:
    def __init__(self, ..., hedge_policy: Literal["HEDGE_HOLD", "HYBRID", "HOLD_ONLY", "SELL_BID"] | None = None):
        # If None, fall back to env (preserves legacy behavior)
        self.hedge_policy = hedge_policy or HEDGE_POLICY
```

Then in `on_tick` / `_maybe_hedge`:
```python
async def on_tick(self) -> None:
    for slot in self._slots.values():
        if slot.status != "open":
            continue
        if self.hedge_policy == "HOLD_ONLY":
            continue  # never exit early — hold to resolution
        elif self.hedge_policy == "HEDGE_HOLD":
            await self._maybe_hedge(slot)
        elif self.hedge_policy == "HYBRID":
            await self._maybe_hedge(slot)  # hedge first, fallback to bid-exit
        elif self.hedge_policy == "SELL_BID":
            await self._maybe_sell_at_bid(slot)
```

The new `_maybe_sell_at_bid` is a separate method that mirrors `_maybe_hedge` but the ACTION is: `executor.place_exit_order(side='SELL', token_id=slot.held_token_id, qty=slot.entry_qty)` walking own bid book at the same `rev_bp=5` trigger.

`_try_bid_exit` already exists for the HYBRID-fallback path — reuse most of it. The only new thing: `SELL_BID` triggers SELL **on the rev_bp signal** (not just when opposite-asks empty).

---

## 4 · Required changes to existing code

### 4.1 `controllers/polymarket_updown.py`

| Change | Line |
|---|---|
| Add `"momo"` to `_valid_strategy_modes` tuple | ~541 |
| Accept `hedge_policy` constructor arg with default fallback to module-level | ~530 (constructor) |
| Branch `on_tick` on `self.hedge_policy` (HOLD_ONLY no-op, SELL_BID → `_maybe_sell_at_bid`) | ~2039 |
| Add `_maybe_sell_at_bid(slot)` method (mirror `_maybe_hedge`) | new method |
| Extend `_build_signal_aux` to populate `ret_2m`, `abs_ret_2m_threshold`, `bar_ctx_phase` when bar_ctx is a t+120s context | ~705 |
| Wire t+120s book re-fetch in BarContext (the entry book is at t+120s, NOT at bar close) | new helper |

### 4.2 `engine/poly_updown_loop.py`

| Change | Line |
|---|---|
| Extend `BarContext` with optional `phase: Literal["bar_close", "t_plus_120"] = "bar_close"` field | ~67 |
| Add `build_bar_context_t_plus_120(primary, sym, tf, ws_s)` builder (fetches BTC@ws and BTC@ws+120, freshly fetches CLOB books at t+120s) | new function |
| Add Option-B asyncio.create_task scheduling in master scheduler when momo controllers are registered | ~480 |
| Add new env `TV_POLY_MOMO_ENABLED` gating the t+120s scheduler arm | new |

### 4.3 `strategies/polymarket/`

| Change | File |
|---|---|
| Add `momo.py` with `MomoStrategy` class (§1) | new |
| Update `__init__.py` to export `MomoStrategy` | existing |

### 4.4 Engine main.py

Iterates `TV_POLY_STRATEGY_MODES` env to construct controllers. Update env:
```
TV_POLY_STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v3_3,v4,momo
```
And construct momo with each of 3 hedge_policy values:
```python
if "momo" in modes_enabled:
    for hp in ("HOLD_ONLY", "HEDGE_HOLD", "SELL_BID"):
        ctrl = PolymarketUpdownController(
            ..., strategy_mode="momo", hedge_policy=hp,
        )
        master_scheduler.register(ctrl)
```

(The sleeve_id suffix `_HOLD` / `_HEDGE` / `_SELL` is derived from `hedge_policy` at audit-event write time.)

---

## 5 · New env vars

```
TV_POLY_MOMO_ENABLED=true
TV_POLY_MOMO_GATE_QUANTILE=0.90
TV_POLY_MOMO_LOOKBACK_DAYS=14
TV_POLY_MOMO_MIN_SAMPLES=50
TV_POLY_MOMO_REV_BP=5
TV_POLY_MOMO_T_PLUS_SECONDS=120
TV_POLY_MOMO_NOTIONAL_USD=25
TV_POLY_MOMO_SPREAD_BTC=0.02
TV_POLY_MOMO_SPREAD_ETH=0.02
TV_POLY_MOMO_SPREAD_SOL=0.025
```

`TV_POLY_STRATEGY_MODES` add: `,momo`.

---

## 6 · Audit-event schema

Each fire writes one row to `trading.events` with `kind='poly_updown_resolution'`:
```json
{
  "sleeve_id": "poly_updown_btc_5m_momo_SELL",
  "kind": "poly_updown_resolution",
  "at": "2026-05-06 12:34:56+00",
  "data": {
    "tf": "5m",
    "symbol": "BTC",
    "won": false,
    "mode": "paper",
    "signal": "UP",
    "outcome": "Down",
    "hedge_policy": "SELL_BID",
    "entry_phase": "t_plus_120",
    "entry_price": "0.71",
    "entry_qty": "35.21",
    "exit_reason": "sell_revert_5bp",
    "exit_bucket": 18,
    "exit_price": "0.42",
    "exit_gross": "14.79",
    "pnl_usd": "-10.21",
    "ret_2m_at_signal": 0.0034,
    "abs_ret_2m_threshold": 0.0028,
    "bar_ctx_age_ms": 217
  }
}
```

The lab side will pull these via the existing `refresh_and_analyze.sh` weekly.

---

## 7 · Validation criteria

After **7 days** (target: 2026-05-12):

| Pass | Conditional | Fail |
|---|---|---|
| ≥ 200 trades aggregated across all 18 sleeves | 100-200 | < 100 |
| Combined HOLD+HEDGE+SELL net PnL > $0 | > -$200 | < -$200 |
| At least one (asset, tf, exit) cell ≥ 70% hit | 60-70% | < 60% on every cell |
| SELL ≥ HOLD in 4 of 6 (asset, tf) cells | tied | SELL underperforms broadly |

After **14 days** (target: 2026-05-19):

| Pass | Fail |
|---|---|
| Best (cell, exit) combination ≥ +$300 cumulative | < +$100 |
| Combined PnL across 18 sleeves ≥ +$1,000 | < $0 |
| BTC_5m_momo_SELL Sharpe ≥ 5 | < 3 |

If pass-criteria met → propose **single live sleeve** at $25 notional with 50% size cap on BTC_5m_momo_SELL (the highest-Sharpe backtest cell).

---

## 8 · Kill switch

```bash
# Disable globally
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/^TV_POLY_MOMO_ENABLED=.*/TV_POLY_MOMO_ENABLED=false/' /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

Per-policy kill: remove `momo` from `TV_POLY_STRATEGY_MODES`, restart.

---

## 9 · Pre-implementation questions for TV agent

Please confirm before coding:

1. **t+120s dispatch route** — Option A (extend master scheduler 1MIN handler with `_is_t_plus_120_*` checkers) vs Option B (`asyncio.create_task` 120s delay from existing `on_bar_close`). Recommend B for speed-of-shipping.
2. **HEDGE_POLICY refactor** — module env → per-controller arg. Acceptable, or do you prefer 3 separate envs?
3. **SELL_BID semantics** — does `executor.place_exit_order(side='SELL', ...)` exist on `PolyPaperExecutor`? If not, mirror BUY logic with `walk_bids` helper. Confirm before §4.1 implementation.
4. **BarContext extension** — adding `phase` field to a `frozen=True, slots=True` dataclass: must rebuild dataclass. Any concerns about backward compat with the legacy scheduler's BarContext consumers?
5. **Slot budget** — 3 momo controllers × 6 cells = 18 paper slots. Plus 35 existing sleeves. The `_slots` map is keyed by `(symbol, tf, ws_s)` — 18 momo + 35 existing = 53 max. Any concern about the slot manager's capacity?
6. **Threshold cache invariance** — the existing `_SAMPLES_CACHE` is keyed by `(symbol_id, tf, UTC day)`. For momo we need a separate cache keyed by the same (the q90 of `|ret_2m|` is per-(symbol, tf)). Add a parallel `_RET_2M_SAMPLES_CACHE`.

---

## 10 · Quick-start checklist

- [ ] Read this doc and §0 (architecture changes since pre-Phase-24)
- [ ] Confirm answers to §9 questions
- [ ] Implement `MomoStrategy` (§1)
- [ ] Implement `_maybe_sell_at_bid` controller method (§3)
- [ ] Extend `BarContext` with `phase` (§4.2)
- [ ] Implement `build_bar_context_t_plus_120` (§4.2)
- [ ] Wire Option B delayed dispatch in master scheduler (§2)
- [ ] Add `momo` to `_valid_strategy_modes` + per-controller `hedge_policy` arg (§4.1)
- [ ] Update engine/main.py to construct 3 momo controllers (§4.4)
- [ ] Add env vars (§5)
- [ ] Restart `tv-engine` and verify first momo fires within ~10 minutes (5m markets fire every 5min; first momo fires 2min after the first market opens)
- [ ] Confirm 18 sleeves visible in `trading.events` (one row per fire)
- [ ] Pull resolutions at +24h, +7d, +14d via `refresh_and_analyze.sh`

Lab side will produce `MOMO_SLEEVES_FORWARD_WALK.md` weekly to compare shadow vs backtest.
