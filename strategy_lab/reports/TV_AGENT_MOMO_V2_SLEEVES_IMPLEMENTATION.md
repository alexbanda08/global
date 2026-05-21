# TV Agent: Implementation Guide — Momentum v2 Sleeves (18 new sleeves)

**Recipient:** TV agent (Claude operating `/root/tv-bootstrap` and `/opt/tradingvenue` on VPS3 = `185.190.143.7`)
**Author:** Strategy lab (laptop)
**Date:** 2026-05-07
**Goal:** Deploy **18 NEW shadow sleeves** = 3 assets × 2 tfs × 3 exit policies under a NEW `strategy_mode="momo_v2"`. **PAPER MODE first; live transition gated.**
**Coexists with:** existing 18 `momo` sleeves. Both run side-by-side for A/B comparison. Do NOT remove current momo.
**Source backtests:**
- `strategy_lab/reports/MOMO_FULL_BACKTEST_WS_2026_05_06.md` — strict asof + L25 WS books, 1000-perm DIRECTION_PERM, walkforward OOS
- `strategy_lab/reports/MOMO_RERUN_L25_HOLD_2026_05_06.md` — HOLD baseline (current refresh)
- `strategy_lab/results/meta_classifier/momo_realfill_validation.csv` — HOLD/HEDGE/SELL with real L25 exit books
- `strategy_lab/reports/TV_AGENT_MOMO_SLEEVES_IMPLEMENTATION.md` — original 18-sleeve spec for reference (we are NOT replacing this)

---

## 0 · Why momo_v2 (delta from current momo)

| Aspect | momo (current) | **momo_v2 (this spec)** |
|---|---|---|
| `ret_2m` anchor | `log(close@(ws+120) / close@(ws))` | **`log(close@(ws+60) / close@(ws-60))`** |
| Fire offset | `ws + 120s` (`t_plus_120` phase) | **`ws + 60s` (`t_plus_60` phase)** |
| Equivalent in market lifetime | t+180 of market (60% of 5m duration consumed) | **t+120 of market (40% of 5m duration consumed)** |
| Book source | REST CLOB `/book` w/ 1s cache | **WS direct (the recent migration)** |
| Q90 threshold cache | per-(asset, tf, day) | per-(asset, tf, day) — **separate cache** because ret values differ |
| Exit policies | HOLD / HEDGE_HOLD / SELL_BID | HOLD / HEDGE_HOLD / SELL_BID (same) |
| Sleeve count | 18 | 18 |

**Why these changes work** (backtest evidence at strict asof + L25 WS books):

| offset | n | pnl_total | pnl_mean | hit% | avg_vwap |
|---:|---:|---:|---:|---:|---:|
| ws+120 (production momo) | 966 | +$9,644 | **+$9.98** | 87.2% | 0.676 |
| ws+90 | 932 | +$11,544 | **+$12.39** | 87.4% | 0.644 |
| **ws+60 (momo_v2 fire time)** | **935** | **+$12,782** | **+$13.67** | **87.5%** | **0.612** |
| ws+30 (lookahead — invalid) | 896 | +$13,756 | +$15.35 | 87.2% | 0.568 |

Walkforward OOS (rolling 7d train / 1d test, q90 refit per train window) at offset=60: **+$14.13/trade**, n=585, **all 6 cells profitable**, every cell ≥$10.72/trade.

DIRECTION_PERM (1000 random sign permutations) at offset=60: **p=0.0000 *** every cell**, combined obs +$12,782 vs perm_mean −$1,922 ± $760.

The +$3.69/trade improvement vs production offset=120 comes from firing 60 seconds earlier — the Polymarket book has had less time to absorb the Binance move, so vwap is 0.612 vs 0.676. Hit rate is essentially identical (~87%).

---

## 1 · Pre-flight (verify before changing code)

### 1a · Confirm production already on strict asof + WS books
This spec assumes:
- `fetch_close_asof` on VPS3 is **end-time-indexed** (the recent fix). If it's still bar-open-indexed, STOP and finish that fix first — momo_v2 q90 threshold will be miscalibrated otherwise.
- `executor.get_orderbook_snapshot` (or whatever path the new WS migration introduced) returns sub-50ms-stale book snapshots from `wss://ws-subscriptions-clob.polymarket.com/ws/market`.

Quick check on VPS3:
```bash
grep -nE "time_period_end_us|searchsorted.*end_us|end_us =" /opt/tradingvenue/backend/app/data/bars.py
```
If you see `end_us` in `fetch_close_asof`, you're good. If only `time_period_start_us`, halt.

### 1b · Confirm momo (v1) sleeves still active
We coexist, not replace. Both run side-by-side.
```sql
SELECT sleeve_id, COUNT(*) FROM trading.events
WHERE kind='poly_updown_resolution' AND sleeve_id LIKE 'poly_updown_%_momo_%'
  AND at > now() - interval '24 hours'
GROUP BY 1 ORDER BY 1;
```
Should show ~18 sleeves with names `poly_updown_{btc,eth,sol}_{5m,15m}_momo_{HOLD,HEDGE,SELL}`. If not, alert before deploying v2.

---

## 2 · Strategy class — `MomoV2Strategy`

Suggested location: `backend/app/strategies/polymarket/momo_v2.py`.

The signal function is identical in shape to `MomoStrategy.signal`, but reads aux fields populated by the **new `t_plus_60` dispatch phase** (see §3a).

```python
"""MomoV2Strategy — Binance latency-arbitrage at t+60s of each market (= t+120
of market lifetime under strike-at-ws-60 convention). Fires at ws+60s, NOT
ws+120s like v1.

ret_2m is anchored at (ws-60, ws+60) instead of (ws, ws+120) — the predictive
window for the q90 |ret_2m| gate. Backtest evidence in
strategy_lab/reports/MOMO_FULL_BACKTEST_WS_2026_05_06.md.
"""
from __future__ import annotations
import math
from typing import TYPE_CHECKING

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy, SignalConfig, SignalResult,
)

if TYPE_CHECKING:
    from backend.app.data.models import Bar


class MomoV2Strategy(PolymarketBinaryStrategy):
    """Top-10% |ret_2m| gate; reads aux['ret_2m'] populated at ws+60s.

    aux schema (NEW fields populated by extended _build_signal_aux for t_plus_60 phase):
      ret_2m                    -- log(close@(ws+60) / close@(ws-60))
      abs_ret_2m_threshold      -- rolling 14d q90 of |ret_2m|, daily cache,
                                   computed against momo_v2 ret values (NOT
                                   shared with momo v1's threshold cache)
      bar_ctx_phase             -- 't_plus_60' (gate — only fire on the
                                   ws+60 dispatch, never bar-close, never
                                   ws+120)
    """

    name = "momo_v2"

    def signal(self, bars, config=None, aux=None) -> SignalResult:
        if aux is None:
            return "NONE"
        # Only fire on the t+60s dispatch
        if aux.get("bar_ctx_phase") != "t_plus_60":
            return "NONE"
        ret_2m = aux.get("ret_2m")
        if ret_2m is None or not math.isfinite(ret_2m):
            return "NONE"
        thr = aux.get("abs_ret_2m_threshold")
        if thr is None or abs(ret_2m) < thr:
            return "NONE"
        return "UP" if ret_2m > 0 else "DOWN"


__all__ = ["MomoV2Strategy"]
```

---

## 3 · Master-scheduler additions

### 3a · New `t_plus_60` dispatch phase

Edit `backend/app/engine/poly_updown_loop.py`. Add a new function `build_bar_context_t_plus_60` mirroring `build_bar_context_t_plus_120` but anchored 60 seconds earlier. Sketch:

```python
async def build_bar_context_t_plus_60(
    primary: PolymarketUpdownController,
    sym: str,
    tf: str,
    ws_s: int,
) -> BarContext:
    """Build a BarContext at ws_s+60s for momo_v2 dispatch.

    Differs from build_bar_context_t_plus_120:
      - btc_at_t_plus_60 fetched (NOT btc_at_t_plus_120)
      - btc_close_at_ws_minus_60 fetched (NEW — the strike-side anchor)
      - book_snapshot_yes/no fetched fresh at this moment
      - Sniper threshold samples reused from build_bar_context (no refetch)
    """
    # ... same shape as build_bar_context_t_plus_120 but with these two
    # close-fetches and phase="t_plus_60" set on the returned BarContext.
```

Add fields to `BarContext` dataclass:
```python
@dataclass(frozen=True)
class BarContext:
    # ... existing fields ...
    # Phase 18.5 momo_v2 — strike-anchor (ws-60) and t+60 closes.
    btc_close_at_ws_minus_60: Decimal | None = None  # BTC@(ws_s - 60)  = strike
    btc_at_t_plus_60: Decimal | None = None          # BTC@(ws_s + 60)
```

### 3b · Master scheduler dedupe + dispatch

Add a third dedupe key + dispatch loop, mirroring the existing momo (v1) `t_plus_120` block:

```python
# Existing keys (don't touch):
last_5m_t120_ws_fired = 0
last_15m_t120_ws_fired = 0

# NEW for momo_v2:
last_5m_t60_ws_fired = 0
last_15m_t60_ws_fired = 0

# Existing partition (extend):
t_plus_60_controllers = [
    c for c in all_controllers
    if c.strategy_mode == "momo_v2"
]
t_plus_120_controllers = [
    c for c in all_controllers
    if c.strategy_mode == "momo"  # v1 unchanged
]
bar_close_controllers = [
    c for c in all_controllers
    if c.strategy_mode not in ("momo", "momo_v2")
]
```

Detection window per spec Q1 of v1 doc: 10s-tick check, fire when `now ∈ [ws+60, ws+65]` (5-second tolerance, matches v1's `[ws+120, ws+125]`).

### 3c · Per-symbol sequencing on a v2 fire

```python
# When the t+60 detection fires for a (sym, tf, ws_s) boundary:
ctx = await build_bar_context_t_plus_60(primary, sym, tf, ws_s)
for ctl in t_plus_60_controllers:
    try:
        await ctl.on_bar_close(sym, tf, [], bar_ctx=ctx)
    except Exception:
        logger.exception("poly_updown_scheduler.t_plus_60.on_bar_close.error",
                         extra={"sym": sym, "tf": tf, "ws_s": ws_s,
                                "controller": ctl.strategy_mode})
```

---

## 4 · Controller additions in `polymarket_updown.py`

### 4a · Register `momo_v2` strategy mode

```python
_valid_strategy_modes = (
    "volume",
    "sniper",
    "v3", "v3_1", "v3_2", "v3_3",
    "v4",
    "momo",
    "momo_v2",                    # NEW
    "inverse_volume_night",
    "inverse_sol_sniper",
    "inverse_sniper_down",
)
```

### 4b · `_build_signal_aux` extension

When `self.strategy_mode == "momo_v2"` AND `bar_ctx.phase == "t_plus_60"`, populate aux with:
- `ret_2m` from `bar_ctx.btc_at_t_plus_60` and `bar_ctx.btc_close_at_ws_minus_60`
- `abs_ret_2m_threshold` from a NEW per-(asset, tf, day) cache (see §4c)
- `bar_ctx_phase = "t_plus_60"`
- `entry_phase = "t_plus_60"` (for the audit-event row, Sleeve §6)

```python
elif self.strategy_mode == "momo_v2":
    if bar_ctx.phase != "t_plus_60":
        return None  # don't audit on wrong phase
    c0 = bar_ctx.btc_close_at_ws_minus_60
    c2 = bar_ctx.btc_at_t_plus_60
    if c0 is None or c2 is None or c0 <= 0:
        return None
    ret_2m = float(Decimal(c2).ln() - Decimal(c0).ln())  # log(c2/c0)
    threshold = await self._get_or_compute_momo_v2_threshold(
        symbol_id=bar_ctx.binance_symbol_id, tf=bar_ctx.tf, day_utc=bar_ctx.day_utc,
    )
    return {
        "ret_2m": ret_2m,
        "abs_ret_2m_threshold": threshold,
        "bar_ctx_phase": "t_plus_60",
        "entry_phase": "t_plus_60",
        "ret_2m_at_signal": ret_2m,
        "bar_ctx_age_ms": ((time.time() * 1000) - bar_ctx.created_at_ms),
    }
```

### 4c · New q90 threshold cache

Independent from `_RET_2M_SAMPLES_CACHE` (used by v1 momo) because v2's ret_2m is anchored differently. Same daily-eviction, same lookback.

```python
_RET_2M_V2_SAMPLES_CACHE: dict[tuple[str, str, date], list[float]] = {}
_RET_2M_V2_THRESHOLD_CACHE: dict[tuple[str, str, date], float] = {}

async def _get_or_compute_momo_v2_threshold(
    self, symbol_id: str, tf: str, day_utc: date,
) -> float | None:
    """Same algorithm as _get_or_compute_momo_threshold but with v2 anchor.

    Pulls 14 days of historical kline closes, computes ret_2m = log(c@(ws+60)/c@(ws-60))
    for every prior 5m or 15m boundary, takes q90 of |ret_2m|. Cached per
    (symbol_id, tf, day_utc) for the day; evicted at UTC day rollover.
    Min sample threshold: 50 (per cell, per day).
    """
    key = (symbol_id, tf, day_utc)
    if key in _RET_2M_V2_THRESHOLD_CACHE:
        return _RET_2M_V2_THRESHOLD_CACHE[key]
    # ... fetch 14d klines, compute ret_2m using anchor (ws-60, ws+60),
    # store quantile, return.
```

### 4d · Hedge policy compatibility

Reuse the existing `hedge_policy` arg + `_HEDGE_POLICY_SUFFIX` mapping:

```python
_HEDGE_POLICY_SUFFIX = {
    "HEDGE_HOLD": "HEDGE",
    "HOLD_ONLY":  "HOLD",
    "SELL_BID":   "SELL",
    "HYBRID":     "HEDGE",  # legacy
}
```

Sleeve_id format for v2 is `poly_updown_<sym>_<tf>_momo_v2_<HEDGE|HOLD|SELL>`.

### 4e · `on_tick` for v2

Same as v1 momo. The exit-policy branches (`HEDGE_HOLD`, `HOLD_ONLY`, `SELL_BID`) are identical; only the entry decision differs.

The rev_bp anchor for `on_tick`: in production momo v1, `_maybe_hedge` and `_maybe_sell_at_bid` use `slot.btc_close_at_ws` (BTC@ws). For v2 we have a choice:
- **Recommendation**: also use `slot.btc_close_at_ws` (the bar-close anchor, NOT the strike anchor `ws-60`). Reason: the rev_bp logic is checking "asset has reverted N bp from the bar that triggered our entry decision." That bar is `ws`. The strike at `ws-60` is irrelevant to the reversion logic. v1 uses `ws` and v2 should match.
- This means `on_tick` code is identical between v1 and v2 — no copy.

---

## 5 · Sleeve registration (`backend/app/engine/sleeve_registry.py` or wherever)

Add 18 new entries, naming convention identical to v1 except `momo` → `momo_v2`:

```python
MOMO_V2_SLEEVES = [
    # (asset, tf, hedge_policy)  → sleeve_id derived as
    # poly_updown_<asset_lower>_<tf>_momo_v2_<HEDGE_POLICY_SUFFIX[hedge_policy]>
    ("btc", "5m",  "HOLD_ONLY"),
    ("btc", "5m",  "HEDGE_HOLD"),
    ("btc", "5m",  "SELL_BID"),
    ("btc", "15m", "HOLD_ONLY"),
    ("btc", "15m", "HEDGE_HOLD"),
    ("btc", "15m", "SELL_BID"),
    ("eth", "5m",  "HOLD_ONLY"),
    ("eth", "5m",  "HEDGE_HOLD"),
    ("eth", "5m",  "SELL_BID"),
    ("eth", "15m", "HOLD_ONLY"),
    ("eth", "15m", "HEDGE_HOLD"),
    ("eth", "15m", "SELL_BID"),
    ("sol", "5m",  "HOLD_ONLY"),
    ("sol", "5m",  "HEDGE_HOLD"),
    ("sol", "5m",  "SELL_BID"),
    ("sol", "15m", "HOLD_ONLY"),
    ("sol", "15m", "HEDGE_HOLD"),
    ("sol", "15m", "SELL_BID"),
]

for asset, tf, hp in MOMO_V2_SLEEVES:
    register(PolymarketUpDownController(
        sleeve_id=f"poly_updown_{asset}_{tf}_momo_v2_{_HEDGE_POLICY_SUFFIX[hp]}",
        symbol=asset.upper(),
        tf=tf,
        strategy_mode="momo_v2",
        hedge_policy=hp,
        notional_usd=Decimal("25"),    # paper $25 same as v1
        mode="paper",
    ))
```

Slot budget: 18 (v1 momo) + 18 (v2 momo) + ~35 (everything else) = **71 worst-case**. Current v1 design budgets 53; need to verify the dispatch loop handles 71. If sequential dispatch becomes a bottleneck (>2s latency), parallelize per (sym, tf).

---

## 6 · New env vars

```bash
# Existing v1 vars stay unchanged. Add v2 parallels:
TV_POLY_MOMO_V2_ENABLED=true
TV_POLY_MOMO_V2_GATE_QUANTILE=0.90
TV_POLY_MOMO_V2_LOOKBACK_DAYS=14
TV_POLY_MOMO_V2_MIN_SAMPLES=50
TV_POLY_MOMO_V2_REV_BP=5
TV_POLY_MOMO_V2_T_PLUS_SECONDS=60     # ← key delta vs v1's =120
TV_POLY_MOMO_V2_NOTIONAL_USD=25
TV_POLY_MOMO_V2_SPREAD_BTC=0.02
TV_POLY_MOMO_V2_SPREAD_ETH=0.02
TV_POLY_MOMO_V2_SPREAD_SOL=0.025
TV_POLY_MOMO_V2_BOOK_STALE_MAX_MS=5000   # entry-time WS book freshness gate

# Append to comma-list (do NOT replace existing entries):
TV_POLY_STRATEGY_MODES=...,momo,momo_v2
```

### 6a · Per-sleeve enable flags (surgical pause without redeploy)

In addition to the master `TV_POLY_MOMO_V2_ENABLED`, give each sleeve its own flag for pause-without-restart. Default `true` so they all enable when master is on:

```bash
# All 18 default to true; flip individual cells off without disabling whole strategy:
TV_POLY_MOMO_V2_BTC_5M_HOLD_ENABLED=true
TV_POLY_MOMO_V2_BTC_5M_HEDGE_ENABLED=true
TV_POLY_MOMO_V2_BTC_5M_SELL_ENABLED=true
TV_POLY_MOMO_V2_BTC_15M_HOLD_ENABLED=true
TV_POLY_MOMO_V2_BTC_15M_HEDGE_ENABLED=true
TV_POLY_MOMO_V2_BTC_15M_SELL_ENABLED=true
TV_POLY_MOMO_V2_ETH_5M_HOLD_ENABLED=true
TV_POLY_MOMO_V2_ETH_5M_HEDGE_ENABLED=true
TV_POLY_MOMO_V2_ETH_5M_SELL_ENABLED=true
TV_POLY_MOMO_V2_ETH_15M_HOLD_ENABLED=true
TV_POLY_MOMO_V2_ETH_15M_HEDGE_ENABLED=true
TV_POLY_MOMO_V2_ETH_15M_SELL_ENABLED=true
TV_POLY_MOMO_V2_SOL_5M_HOLD_ENABLED=true
TV_POLY_MOMO_V2_SOL_5M_HEDGE_ENABLED=true
TV_POLY_MOMO_V2_SOL_5M_SELL_ENABLED=true
TV_POLY_MOMO_V2_SOL_15M_HOLD_ENABLED=true
TV_POLY_MOMO_V2_SOL_15M_HEDGE_ENABLED=true
TV_POLY_MOMO_V2_SOL_15M_SELL_ENABLED=true
```

In §5 sleeve registration, gate each sleeve on its own flag:
```python
for asset, tf, hp in MOMO_V2_SLEEVES:
    suffix = _HEDGE_POLICY_SUFFIX[hp]
    env_key = f"TV_POLY_MOMO_V2_{asset.upper()}_{tf.upper()}_{suffix}_ENABLED"
    if not _env_bool(env_key, default=True):
        continue  # individually paused
    register(PolymarketUpDownController(...))
```

---

## 7 · Audit-event schema (no changes from v1, only sleeve_id pattern differs)

Each fire writes one row to `trading.events` with `kind='poly_updown_resolution'` and the standard data shape. New sleeve_id pattern:

```json
{
  "sleeve_id": "poly_updown_btc_5m_momo_v2_SELL",
  "kind": "poly_updown_resolution",
  "at": "2026-05-07 12:34:56+00",
  "data": {
    "tf": "5m",
    "symbol": "BTC",
    "strategy_mode": "momo_v2",
    "won": false,
    "mode": "paper",
    "signal": "UP",
    "outcome": "Down",
    "hedge_policy": "SELL_BID",
    "entry_phase": "t_plus_60",
    "entry_price": "0.61",
    "entry_qty": "40.98",
    "exit_reason": "sell_revert_5bp",
    "pnl_usd": "-2.50",
    "ret_2m_at_signal": 0.0034,
    "abs_ret_2m_threshold": 0.0028,
    "bar_ctx_age_ms": 14
  }
}
```

The lab side will pull these via the existing `refresh_and_analyze.sh` and a new `momo_v2_shadow_vs_backtest.py` (parallel to existing momo_shadow_vs_backtest.py).

---

## 8 · Validation criteria — 7-day shadow

After **7 days** (target: 7 days post-deploy):

| Pass | Conditional | Fail |
|---|---|---|
| ≥ 200 trades aggregated across all 18 v2 sleeves | 100-200 | < 100 |
| Combined HOLD+HEDGE+SELL net PnL > **+$300** (v1 was >$0 — v2 should beat) | $0 to +$300 | < $0 |
| Mean PnL/trade ≥ **+$8** (vs v1's break-even target) | +$3 to +$8 | < +$3 |
| At least one (asset, tf, exit) cell ≥ 80% hit | 70-80% | < 70% on every cell |
| **v2 mean PnL/trade > v1 mean PnL/trade** by **≥ $4** | $1-$4 | v2 ≤ v1 |

If v2 fails the head-to-head with v1, something in the t+60 wiring is wrong — investigate before declaring v2 a regression.

After **14 days**:

| Pass | Fail |
|---|---|
| Best (cell, exit) cumulative PnL ≥ +$500 | < +$200 |
| Combined v2 PnL ≥ +$1,500 | < +$500 |
| BTC_5m_momo_v2_SELL Sharpe ≥ 5 | < 3 |

Per backtest: walkforward OOS gave +$14.13/trade, $+8,269 total over 13 days on 585 trades. Live haircut typically ~30-60%; mid-case at offset=60s should land $4-9/trade live.

If 14-day pass criteria met → propose **single live sleeve** at $1 notional on `BTC_5m_momo_v2_SELL` (highest backtest Sharpe). Same rollout playbook as `TV_AGENT_LIVE_TRANSITION_SPEC.md` but applied to v2.

---

## 9 · Concurrency / ContextVar (already fixed for v1; verify v2 inherits)

Phase 18.5's ContextVar fix in `polymarket_updown.py` (the `_BAR_CTX_ACTIVE: ContextVar` + Token-based reset pattern) wraps `on_bar_close` execution. v2 controllers reuse the same `on_bar_close` path, so the ContextVar isolation applies automatically. **Verify** by writing one new unit test:

```python
# tests/controllers/test_polymarket_updown_momo_v2.py
def test_momo_v2_bar_ctx_isolated_across_concurrent_tasks():
    """Three momo_v2 controllers run on_bar_close concurrently; each sees its own ctx."""
    # Mirror the existing momo v1 test (same name pattern but momo_v2 strategy_mode).
```

---

## 10 · Rollout sequence

1. **PR 1** — Code only (no env enable):
   - Add `momo_v2.py` strategy class
   - Add `t_plus_60` phase + `build_bar_context_t_plus_60` to `poly_updown_loop.py`
   - Add `momo_v2` to `_valid_strategy_modes` + `_build_signal_aux`
   - Add new `_RET_2M_V2_SAMPLES_CACHE` + threshold helper
   - Add `MOMO_V2_SLEEVES` registration loop (gated on `TV_POLY_MOMO_V2_ENABLED`, default `false`)
   - Unit tests
   - CI green

2. **PR 2** — Threshold backfill verify (lab-side, 30 min):
   - Pull production's last 14 days of klines
   - Compute v2 ret_2m for every 5m/15m boundary
   - Compute q90 per (asset, tf), confirm: ~10-15bp range (matches lab backtest's threshold values)
   - Sanity check that the threshold cache populates correctly on day 1

3. **PR 3** — Enable in env:
   - Set `TV_POLY_MOMO_V2_ENABLED=true` on VPS3
   - Append `momo_v2` to `TV_POLY_STRATEGY_MODES`
   - `systemctl restart tv-engine`
   - First v2 fire should appear within 5-15 minutes (next 5m boundary)
   - Verify by `SELECT sleeve_id FROM trading.events WHERE sleeve_id LIKE '%_momo_v2_%' LIMIT 1` after 15 minutes

4. **Day 1 monitoring** (next session checkpoint):
   - `bar_ctx_age_ms` p95 should be < 50ms (matches v1)
   - `entry_phase` should be `'t_plus_60'` on every v2 fire
   - First fires should have `abs_ret_2m_threshold` populated (NOT NaN)
   - Spot-check 5 v2 fires: vwap should be lower than v1 fires on same day (~0.61 vs ~0.68)

5. **Day 7 / Day 14 checkpoints** per §8.

6. **Live transition ramp** (only if Day 14 PASS per §8):
   1. Enable single highest-conviction cell (`btc_5m_momo_v2_SELL` per §8 Sharpe target, OR `eth_5m_momo_v2_HOLD` per absolute PnL) at `live=true, notional=$1`. Observe 24h.
      - Pass: ≥ 5 live fills, hit_rate within ±10% of paper, zero execution errors.
   2. After canary passes, enable other PASS-grade cells **one per day** at `$1`.
   3. After 7d total at `$1`, ramp survivors to `$5`.
   4. After 7d at `$5`, ramp to `$25`.
   5. **Hard cap during ramp:** combined live notional across all 18 v2 sleeves ≤ `$200` in any 24h rolling window.
   6. HEDGE/SELL cells follow HOLD by 7d (HOLD validates controller end-to-end first).

---

## 11 · Kill switches

### 11a · Master kill (disable all 18 v2 sleeves, v1 keeps running)
```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/^TV_POLY_MOMO_V2_ENABLED=.*/TV_POLY_MOMO_V2_ENABLED=false/' /etc/tv/tradingvenue.env \
   && systemctl restart tv-engine"
```

### 11b · Single-sleeve kill (surgical pause, no restart of others affected)
```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/^TV_POLY_MOMO_V2_SOL_5M_HEDGE_ENABLED=.*/TV_POLY_MOMO_V2_SOL_5M_HEDGE_ENABLED=false/' /etc/tv/tradingvenue.env \
   && systemctl restart tv-engine"
```

### 11c · Auto-pause triggers (controller-side)

The controller MUST self-pause an individual sleeve when any of these conditions hold over the most recent 20 resolutions:

| Trigger | Threshold | Action |
|---|---|---|
| **Loss streak** | 5 consecutive losses (any notional > $1) | Set sleeve's runtime-disabled flag, alert |
| **Hit-rate drift** | Last-20 hit rate > 15pp below backtest expected (e.g. ETH_5m_HOLD expected 95.5%, observed < 80.5%) | Set runtime-disabled flag, alert |
| **Stale-book skip rate** | > 50% of fires skipped with `reason='stale_book'` over last 20 attempts | Set runtime-disabled flag, alert (indicates WS BookMirror issue) |
| **Hedge-feasible rate** (HEDGE sleeves only) | < 50% over last 20 hedge attempts | Alert (do not auto-disable; hedge_skip → fallback to HOLD is acceptable) |

Persist runtime-disabled state in a small Redis or DB-table keyed by `sleeve_id` so it survives restart. Operator clears via:
```sql
DELETE FROM trading.sleeve_pause WHERE sleeve_id = 'poly_updown_sol_5m_momo_v2_HEDGE';
```

To re-enable a master-killed sleeve: flip env back to `true` and restart.

---

## 12 · Files to create / modify

### New files
- `backend/app/strategies/polymarket/momo_v2.py` — `MomoV2Strategy` class (§2)
- `tests/controllers/test_polymarket_updown_momo_v2.py` — unit tests (§9 + signal correctness)
- `tests/strategies/test_momo_v2_strategy.py` — strategy `signal()` unit tests

### Modified files
- `backend/app/engine/poly_updown_loop.py` — add `build_bar_context_t_plus_60` + scheduler dispatch (§3a, §3b, §3c)
- `backend/app/controllers/polymarket_updown.py`:
  - `_valid_strategy_modes` (§4a)
  - `_build_signal_aux` (§4b)
  - `_get_or_compute_momo_v2_threshold` + new sample cache (§4c)
  - `BarContext` dataclass: add `btc_close_at_ws_minus_60`, `btc_at_t_plus_60` (§3a)
- `backend/app/engine/sleeve_registry.py` (or equivalent registration entrypoint) — register 18 v2 sleeves (§5)
- `/etc/tv/tradingvenue.env` (or env file path) — new `TV_POLY_MOMO_V2_*` vars (§6)

### No changes
- `backend/app/strategies/polymarket/momo.py` (v1 untouched)
- v1 sleeve registrations
- Production `momo` audit-event consumers

---

## 13 · Risks + mitigations

| Risk | Mitigation |
|---|---|
| Slot budget overflow at 71 sleeves | Sequential dispatch in master scheduler — measure end-to-end latency on first v2 fire; parallelize per (sym, tf) if > 2s |
| v2 q90 threshold initially unstable (low sample count) | `MIN_SAMPLES=50` per cell per day — same as v1. First 1-2 days will likely have NaN thresholds for some (asset, tf, day) cells; controller returns NONE on missing threshold (fail-safe) |
| Scheduler `t_plus_60` dedupe race | Mirror v1's `last_5m_t120_ws_fired` pattern — single integer per tf, set after dispatch, reset only on restart |
| ContextVar regression from new code paths | Run the existing test_bar_ctx_active_isolated_across_concurrent_tasks test against v2 controllers (§9) |
| v2 SELL_BID exit fires more often than v1 (because firing 60s earlier leaves more remaining holding window) | Already factored into the +$3.69/trade backtest improvement |
| Lab and prod compute different q90 due to kline source mismatch | v2's threshold cache reads `binance-spot-ws` source (matches lab `klines_full.csv`'s preference for binance over okx) — verify the source preference is wired correctly |

---

## 14 · Out of scope

- Live transition (still gated; spec for v2 live $1 trial is a future doc)
- Adjusting v1 momo's anchor or fire offset (we coexist; if v2 dominates, v1 deprecation is a separate decision after 14d data)
- WS ↔ REST fallback (assumed already handled by the recent WS migration)
- Sizing changes (still $25 paper notional; live transition spec will set $1)

---

## 15 · Reporting back to lab

After 24h of v2 fires:
1. Pull `trading.events` filtered to `sleeve_id LIKE '%_momo_v2_%'`, save to `data/v4/shadow_trades_2026_05_07/momo_v2_resolutions.csv`
2. Run lab-side analyzer (parallel to existing `momo_shadow_vs_backtest.py`) — produces `MOMO_V2_SHADOW_VS_BACKTEST_<date>.md`
3. Side-by-side table: v1 vs v2 cells, n / hit% / pnl_total / pnl_mean / vwap

---

*End of TV_AGENT_MOMO_V2_SLEEVES_IMPLEMENTATION.md.*
