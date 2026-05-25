# TV agent — VWAP Continuation strategy: complete shadow-mode implementation spec

_2026-05-23. Production-deploy-ready spec for the 5m strategy with WR=86.3% / +$1,090 sum/28d / Sharpe~8 / OOS test_wr=89%. Shadow-mode (paper-only) initial deploy. Designed to drop in alongside the existing 11 shadow sleeves with zero conflict._

---

## 0. Acceptance criteria

After deploy:
1. **5 new sleeves registered** in journal at boot: `n=5` in a single `poly_updown.vwap_cont_registered` log line.
2. **1s binance feed active**: tv-engine subscribes to `{btc,eth,sol}usdt@kline_1s` streams in addition to existing 1m/5m/15m. Frame counter increments at ~3 closed-bars/sec total.
3. **All 5 sleeves emit signals** within 1 hour after deploy (cells fire every 5min, so within one slot cycle).
4. **`gate_decisions` payload present** in `poly_updown_signal` audit rows for every fire decision.
5. **Top sleeve `btc_5m_vwap_off240_m1v` resolves with WR ≥ 70%** after 24h of fires (n ≥ 30). The backtest WR is 86.3% — accept ±15pp margin for shadow validation.
6. **No live capital exposure** — every sleeve has `mode='paper'` and `paper_only=True`.

If any of those fail, see §13 rollback.

---

## 1. Strategy overview

**Name**: `vwap_continuation`
**Family**: late-fire momentum-continuation on crypto up-down markets
**Markets**: BTC/ETH/SOL 5m chainlink-resolved (no 15m initially)
**Fire timing**: 30 to 270 seconds INTO each 5m slot (multiple offsets per cell)
**Mode**: `paper` only (CLAUDE.md inv #11 — no live capital in shadow)

### Signal definition (one bullet, exact math)

At time `t = slot_start + offset_s`:

```
let bucket_start_s = (t // 900) * 900             // start of current 15m UTC bucket

let cum_px_vol = Σ price_close[s] · volume[s]   for s in [bucket_start_s, t]   (1s bars)
let cum_vol    = Σ volume[s]                    for s in [bucket_start_s, t]

let vwap_15m_anchored = cum_px_vol / cum_vol     if cum_vol > 0 else NaN

let dev_bps = 10000 · ln(close_now / vwap_15m_anchored)

direction = "UP"   if dev_bps > 0 else "DOWN"

fire if  thr_min_bps < |dev_bps| ≤ thr_max_bps   AND  gate_stack passes
```

Bet UP = buy YES-UP token. Bet DOWN = buy YES-DOWN token. Hold to slot close.

---

## 2. Sleeve roster (5 sleeves to register)

All paper-only. `hedge_policy = HOLD_ONLY` (no hedging on shadow validation).

| # | sleeve_id | asset | tf | offset_s | thr_min_bps | thr_max_bps | gate_stack | Expected WR | Expected $/tr | n/28d |
|--:|---|---|---|--:|--:|--:|---|--:|--:|--:|
| 1 | `poly_updown_btc_5m_vwap_off240_m1v` | BTC | 5m | 240 | 5 | 10 | `m1v` | 86.3% | +$2.00 | 546 |
| 2 | `poly_updown_btc_5m_vwap_off60_f7_cross` | BTC | 5m | 60 | 10 | 15 | `f7, cross_full` | 73.8% | +$3.10 | 164 |
| 3 | `poly_updown_btc_5m_vwap_off90_cross` | BTC | 5m | 90 | 10 | 15 | `cross_full` | 78.7% | +$1.89 | 221 |
| 4 | `poly_updown_eth_5m_vwap_off210_f7_m1v` | ETH | 5m | 210 | 10 | 15 | `f7, m1v` | 92.6% | +$1.26 | 188 |
| 5 | `poly_updown_sol_5m_vwap_off60` | SOL | 5m | 60 | 20 | 30 | (none) | 75.0% | +$1.66 | 64 |

**Cross-fire policy**: sleeves 1-3 all target BTC 5m at different offsets — each can fire INDEPENDENTLY per slug (they observe different moments in the slot, so on a given slug all three could trigger; this is intentional for diversification).

---

## 3. Data flow

```
binance WS (1s kline)  →  BinanceMarketDataFeed (NEW 1s deque)  →  Vwap15mStore  →  BarContext  →  Strategy.signal()  →  Controller.dispatch  →  audit + paper fill
                                                                    ↓
                                                          (also: existing 1m deque for RSI / M1V)
```

### 3.1 Binance 1s WS subscription (NEW)

VPS3 storedata's `binance_spot_klines_live.py` already collects 1s into `binance_klines_v2`. For tv-engine to use 1s, we need EITHER:
- **Option A (recommended)**: tv-engine subscribes to the same 1s WS streams directly (one WS per asset already running for 1m; add `@kline_1s` interval). Avoids cross-service latency.
- **Option B**: tv-engine reads 1s rows from storedata DB on each fire decision. Slower, adds DB load.

**Use Option A.** Code change in `BinanceMarketDataFeed`:

```python
# backend/app/data/binance_market_data.py — modify subscription list
SUBSCRIPTION_INTERVALS = ("1s", "1m", "5m", "15m")  # was: ("1m", "5m", "15m")
```

Plus add a `_closes_1s` deque per symbol with `maxlen = 16 * 60 = 960` (16 min, enough for 15m VWAP + 60s buffer):

```python
self._closes_1s: dict[str, collections.deque] = {
    sym: collections.deque(maxlen=960) for sym in self.symbols
}
self._volumes_1s: dict[str, collections.deque] = {
    sym: collections.deque(maxlen=960) for sym in self.symbols
}
```

On each `kline_1s` close event:
```python
self._closes_1s[symbol].append((close_ts_us, float(close), float(vol)))
self._volumes_1s[symbol].append(float(vol))
```

Public read APIs:
```python
def get_close_1s_at(self, symbol: str, target_us: int) -> float | None:
    """At-or-before 1s close. None if not available."""
    deque = self._closes_1s[symbol]
    # Binary search by ts_us; return close
    ...

def get_vwap_15m_anchored(self, symbol: str, anchor_us: int) -> float | None:
    """Anchored VWAP since start of 15m bucket containing anchor_us.

    Iterates 1s deque from bucket_start_us to anchor_us, accumulates
    Σ(close·vol) / Σ(vol). O(900) walk, <2ms.
    """
    bucket_start_us = (anchor_us // (900 * 1_000_000)) * (900 * 1_000_000)
    cum_px_vol = 0.0
    cum_vol = 0.0
    for ts_us, close, vol in self._closes_1s[symbol]:
        if ts_us < bucket_start_us:
            continue
        if ts_us > anchor_us:
            break
        cum_px_vol += close * vol
        cum_vol += vol
    if cum_vol <= 0:
        return None
    return cum_px_vol / cum_vol
```

**Warmup**: deque needs ≥15 min of 1s data before first valid VWAP. On boot, replay historical from storedata DB (`SELECT * FROM binance_klines_v2 WHERE period_id='1SEC' AND time_period_start_us > NOW() - INTERVAL '20 minutes'`) to populate the deque. OR just skip fires for the first 16 min after boot (acceptable for shadow validation).

### 3.2 Vwap15mStore (NEW lightweight class)

```python
# backend/app/strategies/polymarket/vwap_store.py
"""Anchored 15m VWAP cache — per-asset, refreshed by every 1s close."""
from __future__ import annotations

import math
from collections import deque


class Vwap15mStore:
    """Maintains a per-asset rolling 16-min deque of 1s (ts_us, close, vol)
    and exposes anchored VWAP since the start of the current 15m UTC bucket.

    INVARIANT: anchored VWAP resets exactly at each 15m boundary
    (ts_us % 900_000_000 == 0). The deque keeps 16 min so we always have at
    least the previous 1 min for warmup straddling a boundary.
    """
    _BUCKET_US = 900 * 1_000_000

    def __init__(self, max_bars: int = 960) -> None:
        self.bars: dict[str, deque] = {}
        self.max_bars = max_bars

    def push(self, asset: str, ts_us: int, close: float, vol: float) -> None:
        if asset not in self.bars:
            self.bars[asset] = deque(maxlen=self.max_bars)
        self.bars[asset].append((int(ts_us), float(close), float(vol)))

    def vwap_at(self, asset: str, anchor_us: int) -> float | None:
        d = self.bars.get(asset)
        if not d:
            return None
        bucket_start_us = (anchor_us // self._BUCKET_US) * self._BUCKET_US
        cum_px_vol = 0.0
        cum_vol = 0.0
        for ts_us, close, vol in d:
            if ts_us < bucket_start_us:
                continue
            if ts_us > anchor_us:
                break
            cum_px_vol += close * vol
            cum_vol += vol
        if cum_vol <= 0:
            return None
        return cum_px_vol / cum_vol

    def dev_bps_at(self, asset: str, anchor_us: int) -> float | None:
        d = self.bars.get(asset)
        if not d:
            return None
        # close_now = the latest close at-or-before anchor_us
        close_now = None
        for ts_us, close, _vol in reversed(d):
            if ts_us <= anchor_us:
                close_now = close
                break
        if close_now is None or close_now <= 0:
            return None
        vwap = self.vwap_at(asset, anchor_us)
        if vwap is None or vwap <= 0:
            return None
        return 10000.0 * math.log(close_now / vwap)
```

Wire into `BinanceMarketDataFeed.__init__`:
```python
from backend.app.strategies.polymarket.vwap_store import Vwap15mStore
self.vwap_store = Vwap15mStore()
```

In the 1s kline handler:
```python
self.vwap_store.push(asset, close_ts_us, close, vol)
```

---

## 4. Files to add / modify (complete inventory)

| File | Action | Purpose |
|---|---|---|
| `backend/app/strategies/polymarket/vwap_store.py` | **NEW** | Anchored 15m VWAP cache (§3.2) |
| `backend/app/strategies/polymarket/vwap_continuation.py` | **NEW** | Strategy class (§5) |
| `backend/app/strategies/polymarket/markov.py` | **EXISTS** (per Phase 34 fixes) — reuse `label_regime_vol_adaptive` |
| `backend/app/strategies/polymarket/gates.py` | **MODIFY** — add `cross_full_passes` helper |
| `backend/app/data/binance_market_data.py` | **MODIFY** — subscribe to 1s streams, expose `vwap_store` (§3.1) |
| `backend/app/engine/poly_updown_loop.py` | **MODIFY** — add late-fire dispatch builders for t_plus_{30,60,90,120,150,180,210,240,270} (§6) |
| `backend/app/controllers/polymarket_updown.py` | **MODIFY** — add `vwap_dev_bps` gate logic + `cross_asset_devs` aux read (§7) |
| `backend/app/engine/main.py` | **MODIFY** — register 5 `_VWAP_CONT_SLEEVES_SPEC` controllers (§8) |
| `backend/tests/strategies/polymarket/test_vwap_continuation.py` | **NEW** — unit tests (§11) |
| `backend/tests/data/test_vwap_store.py` | **NEW** — unit tests (§11) |
| `backend/tests/controllers/test_polymarket_updown_vwap.py` | **NEW** — integration tests (§11) |
| `/etc/tv/tradingvenue.env` | **MODIFY** — add `TV_POLY_VWAP_CONT_ENABLED=false` (default OFF; flip to true on go-live) |

---

## 5. Strategy class (full code)

```python
# backend/app/strategies/polymarket/vwap_continuation.py
"""VWAP Continuation strategy (Phase 35).

Late-fire momentum continuation on 5m crypto up-down markets. Bets WITH
binance deviation from its 15m anchored VWAP at a fixed offset into each
slot. Filters by M1V Markov regime, F7 RSI, and cross-asset confluence
(any subset, configured per sleeve).

INVARIANTS (CLAUDE.md inv #4):
- signal() is PURE. No IO, no time.time(), no mutation.
- All inputs arrive via aux populated by build_bar_context_t_plus_N.
- Returns "NONE" on any missing/invalid input — never crashes.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy,
    SignalConfig,
    SignalResult,
)

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.data.models import Bar


class VwapContinuationStrategy(PolymarketBinaryStrategy):
    """Bets WITH the binance 15m VWAP deviation.

    aux schema (populated by build_bar_context_t_plus_<offset_s>)::

        aux = {
            "bar_ctx_phase":            "t_plus_240",     # gate; must match self.offset_s
            "vwap_dev_bps":             float,             # 10000·ln(close/vwap_15m)
            "vwap_15m_anchored":        float,             # for audit only
            "rsi_14_for_signal":        float,             # F7 input (existing aux field)
            "markov_regime_w20_1m_va":  int,               # M1V input (existing aux field)
            "cross_asset_devs":         [(asset, dev_bps), ...],   # for cross_full / cross_partial gates
        }
    """

    name = "vwap_continuation"

    def __init__(
        self,
        *,
        offset_s: int,
        thr_min_bps: float,
        thr_max_bps: float,
        require_m1v: bool = False,
        require_f7: bool = False,
        require_cross_full: bool = False,
        require_cross_partial: bool = False,
    ) -> None:
        self.offset_s = int(offset_s)
        self.thr_min = float(thr_min_bps)
        self.thr_max = float(thr_max_bps)
        self.require_m1v = bool(require_m1v)
        self.require_f7 = bool(require_f7)
        self.require_cross_full = bool(require_cross_full)
        self.require_cross_partial = bool(require_cross_partial)
        # Mode is implicit — taker-style threshold-gated entry.
        self.mode = "vwap_continuation"

    def signal(
        self,
        bars: list["Bar"],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        # Phase gate — only fire on the matching late-fire phase.
        expected_phase = f"t_plus_{self.offset_s}"
        if aux.get("bar_ctx_phase") != expected_phase:
            return "NONE"
        # 1. dev_bps in range
        dev_bps = aux.get("vwap_dev_bps")
        if dev_bps is None or not math.isfinite(dev_bps):
            return "NONE"
        abs_dev = abs(dev_bps)
        if not (self.thr_min < abs_dev <= self.thr_max):
            return "NONE"
        # 2. direction from sign
        direction: SignalResult = "UP" if dev_bps > 0 else "DOWN"
        # 3. M1V gate
        if self.require_m1v:
            regime = aux.get("markov_regime_w20_1m_va")
            if regime is None or not isinstance(regime, int):
                return "NONE"
            if direction == "UP" and regime != 2:    # 2 = Bull
                return "NONE"
            if direction == "DOWN" and regime != 0:  # 0 = Bear
                return "NONE"
        # 4. F7 RSI gate
        if self.require_f7:
            rsi = aux.get("rsi_14_for_signal")
            if rsi is None or not math.isfinite(rsi):
                return "NONE"
            if direction == "UP" and rsi <= 50:
                return "NONE"
            if direction == "DOWN" and rsi >= 50:
                return "NONE"
        # 5. cross-asset confluence
        if self.require_cross_full or self.require_cross_partial:
            cross = aux.get("cross_asset_devs") or []
            agree = 0
            valid = 0
            for _, d in cross:
                if d is None or not math.isfinite(d):
                    continue
                valid += 1
                if direction == "UP" and d > 0:
                    agree += 1
                elif direction == "DOWN" and d < 0:
                    agree += 1
            if valid == 0:
                return "NONE"
            need = valid if self.require_cross_full else 1
            if agree < need:
                return "NONE"
        return direction


__all__ = ["VwapContinuationStrategy"]
```

---

## 6. Loop builder additions

`poly_updown_loop.py` currently has `build_bar_context_t_plus_60` and
`build_bar_context_t_plus_120`. Add ONE parameterized builder:

```python
async def build_bar_context_t_plus_n(
    primary: PolymarketUpdownController,
    symbol: str,
    tf: str,
    ws_s: int,
    offset_s: int,
    cid: str | None,
) -> BarContext:
    """Generic late-fire BarContext builder for VWAP continuation.

    Phase = f"t_plus_{offset_s}". Populates:
      - vwap_dev_bps, vwap_15m_anchored  (from BinanceMarketDataFeed.vwap_store)
      - rsi_14_for_signal                 (same as existing F7 path)
      - markov_regime_w20_1m_va           (new M1V — see Phase 34 fix §4.4)
      - cross_asset_devs                  (dev_bps for the OTHER two crypto assets)

    Returns a BarContext with phase=f"t_plus_{offset_s}". If anything fails
    (no 1s data, no vwap, no cid), still returns a valid BarContext with
    aux fields as None; strategy.signal() will return NONE.
    """
    feed = primary.feed
    fire_us = (ws_s + offset_s) * 1_000_000

    # 1. VWAP + dev_bps from 1s store
    vwap = feed.vwap_store.vwap_at(symbol, fire_us)
    dev_bps = feed.vwap_store.dev_bps_at(symbol, fire_us)

    # 2. RSI (same as F7 path — existing code)
    rsi_14 = await primary._fetch_rsi_14_at_ws_s(symbol, ws_s)

    # 3. M1V regime (see Phase 34 fix §4.4 — reuse the same compute)
    m1v_regime = await primary._fetch_markov_regime_m1v(symbol, ws_s)

    # 4. Cross-asset dev_bps for the OTHER two crypto assets
    ASSETS = ("BTC", "ETH", "SOL")
    others = [a for a in ASSETS if a != symbol]
    cross_devs = [(a, feed.vwap_store.dev_bps_at(a, fire_us)) for a in others]

    # 5. Spread + book — same as t_plus_120 (use the same fetch helpers)
    # ... (preserve existing book / token_id fetch logic)

    return BarContext(
        symbol=symbol, tf=tf, ws_s=ws_s, cid=cid,
        phase=f"t_plus_{offset_s}",
        rsi_14_for_signal=rsi_14,
        # Phase 35 — VWAP continuation aux
        vwap_dev_bps=dev_bps,
        vwap_15m_anchored=vwap,
        markov_regime_w20_1m_va=m1v_regime,
        cross_asset_devs=cross_devs,
        # ... book/token fields ...
    )
```

Extend `BarContext` dataclass:
```python
# Phase 35 — VWAP continuation aux
vwap_dev_bps: float | None = None
vwap_15m_anchored: float | None = None
markov_regime_w20_1m_va: int | None = None   # may already exist from Phase 34
cross_asset_devs: list[tuple[str, float | None]] | None = None
```

Scheduler dispatch — currently `poly_updown_scheduler` fires `t_plus_60` and `t_plus_120` boundaries. Add late-fire boundaries:

```python
# poly_updown_loop.py — poly_updown_scheduler

VWAP_OFFSETS = (30, 60, 90, 120, 150, 180, 210, 240, 270)

# For each 5m slot, after the t_plus_120 dispatch, schedule VWAP late fires:
for offset_s in VWAP_OFFSETS:
    if offset_s in (60, 120):
        continue  # already covered by existing builders
    # Schedule timer for (ws_s + offset_s) → call build_bar_context_t_plus_n
    asyncio.create_task(
        _vwap_late_fire_dispatch(controller, symbol="BTC", tf="5m",
                                  ws_s=ws_s, offset_s=offset_s)
    )
    # ... same for ETH, SOL
```

**OPTIMIZATION**: don't fire all 9 offsets unless a VWAP sleeve actually needs that offset for that (symbol, tf). The 5 sleeves we ship use offsets {60, 90, 210, 240}. Track which (symbol, tf, offset) tuples have a registered VWAP controller; only dispatch those.

---

## 7. Controller modifications

`polymarket_updown.py` — the existing gate-stack block in `_dispatch_signal` already handles `hod`, `mtf2`, `m5va` (and m1va per Phase 34). For VWAP continuation strategy, the strategy itself enforces the gates (M1V, F7, cross). The controller just needs to:

1. Accept the new aux fields in the BarContext (no-op — they flow through).
2. Audit the new aux fields on signal/skip rows.

Add to the audit payload constructor:
```python
if self.strategy.name == "vwap_continuation":
    payload["vwap_dev_bps"] = _bar_ctx_active.vwap_dev_bps
    payload["vwap_15m_anchored"] = _bar_ctx_active.vwap_15m_anchored
    payload["markov_regime_w20_1m_va"] = _bar_ctx_active.markov_regime_w20_1m_va
    payload["cross_asset_devs"] = _bar_ctx_active.cross_asset_devs
    payload["fire_offset_s"] = self.strategy.offset_s
```

No new gate logic needed in the controller — strategy enforces everything.

---

## 8. Sleeve registration in engine_main.py

Append to existing wiring (next to `_SHADOW_GATED_SLEEVES_SPEC`):

```python
# Phase 35 — VWAP continuation sleeves (paper-only, shadow validation).
# Format: (sleeve_id, asset, tf, offset_s, thr_min_bps, thr_max_bps,
#          require_m1v, require_f7, require_cross_full, require_cross_partial, hedge_policy)
_VWAP_CONT_SLEEVES_SPEC: tuple[
    tuple[str, str, str, int, float, float, bool, bool, bool, bool, str], ...
] = (
    ("poly_updown_btc_5m_vwap_off240_m1v",
     "BTC", "5m", 240,  5.0, 10.0, True,  False, False, False, "HOLD_ONLY"),
    ("poly_updown_btc_5m_vwap_off60_f7_cross",
     "BTC", "5m",  60, 10.0, 15.0, False, True,  True,  False, "HOLD_ONLY"),
    ("poly_updown_btc_5m_vwap_off90_cross",
     "BTC", "5m",  90, 10.0, 15.0, False, False, True,  False, "HOLD_ONLY"),
    ("poly_updown_eth_5m_vwap_off210_f7_m1v",
     "ETH", "5m", 210, 10.0, 15.0, True,  True,  False, False, "HOLD_ONLY"),
    ("poly_updown_sol_5m_vwap_off60",
     "SOL", "5m",  60, 20.0, 30.0, False, False, False, False, "HOLD_ONLY"),
)
```

In the BarEngine boot wiring, instantiate them when env is on:

```python
_vwap_cont_enabled = os.getenv("TV_POLY_VWAP_CONT_ENABLED", "false").lower() == "true"
if _vwap_cont_enabled:
    from backend.app.strategies.polymarket.vwap_continuation import (
        VwapContinuationStrategy,
    )
    _vwap_spawned: list[str] = []
    for (
        _sid, _asset, _tf, _offset, _thr_min, _thr_max,
        _need_m1v, _need_f7, _need_cross_full, _need_cross_partial, _hp,
    ) in _VWAP_CONT_SLEEVES_SPEC:
        _strategy = VwapContinuationStrategy(
            offset_s=_offset,
            thr_min_bps=_thr_min,
            thr_max_bps=_thr_max,
            require_m1v=_need_m1v,
            require_f7=_need_f7,
            require_cross_full=_need_cross_full,
            require_cross_partial=_need_cross_partial,
        )
        _vwap_ctrl = PolymarketUpdownController(
            pool=read_pool,
            executor=executor,
            strategy=_strategy,
            symbol=_asset,
            tf=_tf,
            mode="paper",                  # SHADOW — never live
            hedge_policy=_hp,
            slot_allowlist={(_asset, _tf)},
            audit_sleeve_id=_sid,
            paper_only=True,
        )
        register_poly_updown(_vwap_ctrl)
        _all_controllers.append((_vwap_ctrl, _sid))
        _vwap_spawned.append(_sid)
    logger.info(
        "poly_updown.vwap_cont_registered",
        n=len(_vwap_spawned),
        sleeve_ids=_vwap_spawned,
    )
```

---

## 9. Audit row payload schema

For every fire decision (whether `order_placed`, `gate_*_skip`, `no_signal`), the audit row `data` jsonb MUST include:

```json
{
  "tf": "5m",
  "symbol": "BTC",
  "signal": "UP" | "DOWN" | null,
  "reason": "order_placed" | "no_signal" | "gate_skip_dev_out_of_range" | ...,
  "mode": "paper",
  "strategy_mode": "vwap_continuation",
  "fire_offset_s": 240,
  "vwap_dev_bps": 7.34,
  "vwap_15m_anchored": 75432.21,
  "markov_regime_w20_1m_va": 2,
  "cross_asset_devs": [["ETH", 5.21], ["SOL", 12.7]],
  "rsi_14_for_signal": 56.7,
  "gate_decisions": {                        // ONLY populated when applicable
    "m1v":   {"pass": true,  "regime": 2},
    "f7":    {"pass": true,  "rsi_14": 56.7},
    "cross": {"pass": true,  "agree": 2, "valid": 2}
  }
}
```

For `order_placed` / `hedge_placed` / `poly_updown_resolution` rows, additionally include:
- `condition_id`, `won`, `outcome`, `entry_qty`, `entry_price`, `pnl_usd`,
- everything the existing momo/sniper audit pipeline includes.

---

## 10. Environment variables

| Var | Default | Purpose |
|---|---|---|
| `TV_POLY_VWAP_CONT_ENABLED` | `false` | Master switch. Set to `true` after code review + tests pass. |
| `TV_POLY_VWAP_CONT_PAPER_NOTIONAL_USD` | `25.0` | Paper notional. Match existing shadow sleeves. |
| `TV_POLY_VWAP_CONT_MIN_BOOK_EVENTS` | `25` | Same as production min_book_events. Sparse books → skip. |
| `TV_POLY_VWAP_CONT_MAX_BOOK_STALENESS_S` | `60` | L25 book staleness tolerance. |

NO new secrets, NO new API keys, NO new RPC endpoints.

---

## 11. Tests

### 11.1 Unit — `test_vwap_continuation.py`

```python
import pytest
from backend.app.strategies.polymarket.vwap_continuation import VwapContinuationStrategy

S_TOP = VwapContinuationStrategy(offset_s=240, thr_min_bps=5, thr_max_bps=10, require_m1v=True)


def _aux(**overrides):
    base = dict(
        bar_ctx_phase="t_plus_240",
        vwap_dev_bps=7.5,
        vwap_15m_anchored=75432.21,
        markov_regime_w20_1m_va=2,                # Bull
        rsi_14_for_signal=60.0,
        cross_asset_devs=[("ETH", 5.0), ("SOL", 12.0)],
    )
    base.update(overrides)
    return base


def test_top_config_fires_up():
    assert S_TOP.signal([], aux=_aux()) == "UP"


def test_phase_mismatch_returns_none():
    assert S_TOP.signal([], aux=_aux(bar_ctx_phase="t_plus_60")) == "NONE"


def test_dev_below_thr_min_returns_none():
    assert S_TOP.signal([], aux=_aux(vwap_dev_bps=3.0)) == "NONE"


def test_dev_above_thr_max_returns_none():
    assert S_TOP.signal([], aux=_aux(vwap_dev_bps=15.0)) == "NONE"


def test_m1v_disagreement_returns_none():
    # UP fire (dev_bps=+7.5) but regime=Bear → NONE
    assert S_TOP.signal([], aux=_aux(markov_regime_w20_1m_va=0)) == "NONE"


def test_m1v_warmup_returns_none():
    assert S_TOP.signal([], aux=_aux(markov_regime_w20_1m_va=-1)) == "NONE"


def test_missing_aux_returns_none():
    assert S_TOP.signal([], aux=None) == "NONE"


def test_dev_nan_returns_none():
    assert S_TOP.signal([], aux=_aux(vwap_dev_bps=float("nan"))) == "NONE"


def test_down_fire_with_bear_regime():
    s = VwapContinuationStrategy(offset_s=240, thr_min_bps=5, thr_max_bps=10, require_m1v=True)
    assert s.signal([], aux=_aux(vwap_dev_bps=-7.0, markov_regime_w20_1m_va=0)) == "DOWN"


def test_cross_full_requires_both():
    s = VwapContinuationStrategy(offset_s=60, thr_min_bps=10, thr_max_bps=15,
                                 require_cross_full=True)
    # UP with one cross-asset DOWN → reject
    a = _aux(vwap_dev_bps=12.0, cross_asset_devs=[("ETH", -3.0), ("SOL", 8.0)])
    assert s.signal([], aux=a) == "NONE"
    # UP with both cross-assets UP → accept
    a2 = _aux(vwap_dev_bps=12.0, cross_asset_devs=[("ETH", 5.0), ("SOL", 8.0)])
    assert s.signal([], aux=a2) == "UP"
```

### 11.2 Unit — `test_vwap_store.py`

```python
import pytest
from backend.app.strategies.polymarket.vwap_store import Vwap15mStore

S_PER_BAR = 1_000_000  # 1 second in microseconds


def test_empty_returns_none():
    st = Vwap15mStore()
    assert st.vwap_at("BTC", 1000 * S_PER_BAR) is None


def test_anchored_vwap_resets_at_15m_boundary():
    st = Vwap15mStore()
    # Push 5 bars within bucket A (close=100, vol=1)
    for i in range(5):
        st.push("BTC", i * S_PER_BAR, 100.0, 1.0)
    # VWAP at end of bucket A should be 100.0
    assert abs(st.vwap_at("BTC", 4 * S_PER_BAR) - 100.0) < 1e-6
    # Push 5 bars in bucket B (close=200, vol=1) — bucket starts at 900s
    for i in range(5):
        st.push("BTC", (900 + i) * S_PER_BAR, 200.0, 1.0)
    # VWAP at start of bucket B should equal close of first B bar (200)
    assert abs(st.vwap_at("BTC", 904 * S_PER_BAR) - 200.0) < 1e-6
    # The bucket A bars MUST NOT contribute to bucket B's VWAP.


def test_dev_bps_calculation():
    st = Vwap15mStore()
    # 10 bars at close=100, vol=1; then close jumps to 105
    for i in range(10):
        st.push("BTC", i * S_PER_BAR, 100.0, 1.0)
    st.push("BTC", 10 * S_PER_BAR, 105.0, 1.0)
    # vwap = (10*100 + 1*105) / 11 ≈ 100.4545
    # dev_bps = 10000 * ln(105 / 100.4545) ≈ 442
    dev = st.dev_bps_at("BTC", 10 * S_PER_BAR)
    assert 430 < dev < 450


def test_zero_volume_returns_none():
    st = Vwap15mStore()
    st.push("BTC", 0, 100.0, 0.0)  # zero vol
    assert st.vwap_at("BTC", 0) is None
```

### 11.3 Integration — `test_polymarket_updown_vwap.py`

```python
@pytest.mark.asyncio
async def test_vwap_continuation_fire_end_to_end_paper():
    """Real BarContext, real strategy, fake pool — assert order_placed audit row."""
    pool = _CapturingPool()
    feed = _make_feed_with_vwap_store_prefilled()  # close=100 trending to 100.7 (dev_bps=+7)
    strategy = VwapContinuationStrategy(
        offset_s=240, thr_min_bps=5, thr_max_bps=10, require_m1v=True,
    )
    controller = PolymarketUpdownController(
        pool=pool, executor=_make_executor(), feed=feed, strategy=strategy,
        symbol="BTC", tf="5m", mode="paper", paper_only=True,
        audit_sleeve_id="poly_updown_btc_5m_vwap_off240_m1v",
    )

    # Inject BarContext at fire time
    bar_ctx = _make_bar_context(
        phase="t_plus_240", symbol="BTC", tf="5m", ws_s=1_700_000_000,
        vwap_dev_bps=+7.0, vwap_15m_anchored=100.4,
        markov_regime_w20_1m_va=2,                     # Bull, agrees with UP
        rsi_14_for_signal=60.0,
        cross_asset_devs=[("ETH", 4.0), ("SOL", 6.0)],
    )
    controller._bar_ctx_active = bar_ctx

    await controller._dispatch_signal_from_context(bar_ctx)

    # Find order_placed row
    placed = [r for r in pool.inserts if "order_placed" in r[0]]
    assert len(placed) == 1
    payload = json.loads(placed[0][1][1])
    assert payload["strategy_mode"] == "vwap_continuation"
    assert payload["signal"] == "UP"
    assert payload["fire_offset_s"] == 240
    assert payload["vwap_dev_bps"] == 7.0


@pytest.mark.asyncio
async def test_vwap_continuation_skip_when_m1v_warmup():
    """Markov regime = -1 must cause NONE / gate_markov_skip."""
    # ... similar setup with markov_regime_w20_1m_va=-1
    # Assert no order_placed; the audit should still record the no-fire decision.
```

---

## 12. Verification SQL (run at deploy + 1h, 24h, 7d)

### 12.1 At deploy +1h — sleeves alive

```sql
SELECT sleeve_id, COUNT(*) AS rows
FROM trading.events
WHERE at > NOW() - INTERVAL '1 hour'
  AND kind = 'poly_updown_signal'
  AND sleeve_id LIKE 'poly_updown_%_vwap%'
GROUP BY 1
ORDER BY 1;
-- Expect: 5 rows, each with COUNT > 0.
```

### 12.2 At deploy +4h — gates working

```sql
SELECT sleeve_id,
       COUNT(*) FILTER (WHERE data->>'reason' = 'no_signal') AS no_sig,
       COUNT(*) FILTER (WHERE data->>'reason' LIKE 'gate_%') AS gated,
       COUNT(*) FILTER (WHERE data->>'reason' = 'order_placed') AS placed
FROM trading.events
WHERE at > NOW() - INTERVAL '4 hours'
  AND sleeve_id LIKE 'poly_updown_%_vwap%'
GROUP BY 1
ORDER BY 1;
-- For each sleeve, expect: no_sig dominant (>= 60%), gated some, placed > 0.

-- M1V regime distribution for the top sleeve
SELECT data->>'markov_regime_w20_1m_va' AS regime, COUNT(*)
FROM trading.events
WHERE at > NOW() - INTERVAL '4 hours'
  AND sleeve_id = 'poly_updown_btc_5m_vwap_off240_m1v'
  AND data ? 'markov_regime_w20_1m_va'
GROUP BY 1;
-- Expect rows for regime IN ('0','1','2'). If ALL '-1', warmup not working —
-- check Vwap15mStore deque warmup logic.
```

### 12.3 At deploy +24h — first WR sample

```sql
SELECT sleeve_id,
       COUNT(*) AS n,
       AVG(CASE WHEN data->>'won' = 'true' THEN 1.0 ELSE 0.0 END) AS wr,
       SUM((data->>'pnl_usd')::numeric) AS sum_pnl
FROM trading.events
WHERE at > NOW() - INTERVAL '24 hours'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id LIKE 'poly_updown_%_vwap%'
GROUP BY 1
ORDER BY 1;
-- Expected:
--   btc_5m_vwap_off240_m1v: n ~= 20, WR >= 70%
--   btc_5m_vwap_off60_f7_cross: n ~= 6, WR >= 55%
--   btc_5m_vwap_off90_cross: n ~= 8, WR >= 65%
--   eth_5m_vwap_off210_f7_m1v: n ~= 7, WR >= 80%
--   sol_5m_vwap_off60: n ~= 2-3, WR variance high (small n)
```

### 12.4 At deploy +7d — full backtest comparison

```sql
-- Compare to backtest expected (28d / 4 = 7d ratio applied to n).
WITH live AS (
  SELECT sleeve_id,
         COUNT(*) AS live_n,
         AVG(CASE WHEN data->>'won' = 'true' THEN 1.0 ELSE 0.0 END) AS live_wr,
         AVG((data->>'pnl_usd')::numeric) AS live_avg_pnl
  FROM trading.events
  WHERE at > NOW() - INTERVAL '7 days'
    AND kind = 'poly_updown_resolution'
    AND sleeve_id LIKE 'poly_updown_%_vwap%'
  GROUP BY 1
)
SELECT * FROM live;
-- Compare against:
--   btc_5m_vwap_off240_m1v:    expect n ~ 137, WR ~ 86%, $/tr ~ +$2.00
--   btc_5m_vwap_off60_f7_cross: expect n ~ 41,  WR ~ 74%, $/tr ~ +$3.10
--   btc_5m_vwap_off90_cross:    expect n ~ 55,  WR ~ 79%, $/tr ~ +$1.89
--   eth_5m_vwap_off210_f7_m1v:  expect n ~ 47,  WR ~ 93%, $/tr ~ +$1.26
--   sol_5m_vwap_off60:          expect n ~ 16,  WR ~ 75%, $/tr ~ +$1.66
-- Acceptable shadow tolerance: WR within ±15pp, n within ±50%.
```

---

## 13. Rollback

If any failure mode at deploy +1h, +4h, or +24h:

```bash
# Option A — disable VWAP continuation only (other sleeves unaffected)
sudo sed -i 's/^TV_POLY_VWAP_CONT_ENABLED=true/TV_POLY_VWAP_CONT_ENABLED=false/' /etc/tv/tradingvenue.env
sudo systemctl restart tv-engine

# Option B — if 1s feed broke other strategies (unlikely; 1s is additive)
# Revert binance_market_data.py to subscribe only to 1m/5m/15m intervals.
# Restart.
```

All VWAP continuation sleeves are `paper_only=True` — **no live capital is exposed at any point**.

---

## 14. Performance / latency budget

| Stage | Budget | Source |
|---|---:|---|
| 1s WS frame → deque push | < 1 ms | in-process |
| `Vwap15mStore.vwap_at` (900-bar walk) | < 2 ms | O(900) linear scan |
| `Vwap15mStore.dev_bps_at` | < 2 ms | same |
| RSI(14) fetch — existing 1m feed | < 5 ms | existing |
| M1V regime compute (15 closes + 14d returns) | < 5 ms | per Phase 34 spec |
| Cross-asset dev_bps (× 2 assets) | < 4 ms | 2× vwap_store calls |
| L25 book fetch (WS mirror) | < 10 ms | existing WS path |
| Total BarContext build | **< 30 ms** | well under 50 ms p95 target |
| Strategy.signal() | < 1 ms | pure |
| Audit insert | < 5 ms | async pool |
| End-to-end fire decision | **< 50 ms** | leaves >120s buffer to slot close |

---

## 15. Open questions for the operator

1. **1s feed re-warmup on engine restart**: do we replay from `binance_klines_v2` (storedata DB) or accept a 16-min warmup window with no fires? Replay needs DB read at boot; warmup is simpler. **Recommendation**: warmup. tv-engine restarts are rare; losing 16 min of shadow signals is acceptable.

2. **Should sleeves 1, 2, 3 fire on the same slug?** They observe different offsets (240s vs 60s vs 90s), so in principle yes — but a single slug could have all three trigger if binance keeps drifting in the same direction across the slot. Per Phase 34's "11 independent sleeves" precedent, this is fine — log it and let it ride; PnL is genuinely diversified across fire times.

3. **15m markets — try later?** Backtest didn't focus on 15m yet (we built `vwap_continuation_15m.py` but didn't run it overnight). If 5m sleeves prove stable in shadow, extend to 15m as Phase 35.1.

4. **Notional sizing — Kelly later?** Spec uses flat $25. The Bayesian-Kelly proposal (yesterday's NEW_STRATEGIES_PROPOSAL.md §S4) is on the roadmap. For now, flat $25 keeps audit simple.

---

## 16. Checklist for TV agent

- [ ] Add 1s WS subscription in `BinanceMarketDataFeed` (`@kline_1s` for BTC/ETH/SOL).
- [ ] Add per-asset `_closes_1s` deque + push handler.
- [ ] Create `vwap_store.py` (full code in §3.2).
- [ ] Wire `vwap_store` into `BinanceMarketDataFeed.__init__`.
- [ ] Extend `BarContext` dataclass with 4 new fields (§6).
- [ ] Create `build_bar_context_t_plus_n` parameterized builder (§6).
- [ ] Extend `poly_updown_scheduler` to dispatch on offsets {30, 60, 90, 120, 150, 180, 210, 240, 270} when a VWAP controller exists for that (symbol, tf).
- [ ] Create `vwap_continuation.py` strategy class (full code in §5).
- [ ] Extend `_dispatch_signal` audit payload to include VWAP aux fields (§7).
- [ ] Add `_VWAP_CONT_SLEEVES_SPEC` and boot wiring in `engine_main.py` (§8).
- [ ] Add 4 env vars to `/etc/tv/tradingvenue.env` (§10).
- [ ] Write unit tests `test_vwap_continuation.py`, `test_vwap_store.py` (§11.1, §11.2).
- [ ] Write integration test `test_polymarket_updown_vwap.py` (§11.3).
- [ ] Run `pytest backend/tests/` — all green.
- [ ] Deploy: `sudo systemctl restart tv-engine`.
- [ ] Set `TV_POLY_VWAP_CONT_ENABLED=true` in env file, restart again.
- [ ] Verify 5 sleeves registered: `journalctl -u tv-engine --since 1m | grep vwap_cont_registered`.
- [ ] Run §12.1 SQL at +1h.
- [ ] Run §12.2 SQL at +4h.
- [ ] Run §12.3 SQL at +24h.
- [ ] Run §12.4 SQL at +7d, compare to backtest expectations.

---

## 17. References

- Backtest reports: `VWAP_CONTINUATION_5M_2026_05_23.md`, `VWAP_CONT_V2_GATED_2026_05_23.md`, `VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md`
- Synthesis: `OVERNIGHT_STRATEGY_RUN_2026_05_23.md`, `DISCOVERIES_TABLE_2026_05_23.md`
- Prior Phase 34 fix spec (for M1V reuse): `TV_AGENT_PHASE34_FIXES_2026_05_22.md`
- Polymarket-bot port basis (`mlmodelpoly/src/collector/fair_model.py`): used in the underlying backtest signal verification, not in production strategy itself.

## End of spec
