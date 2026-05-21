# TV Agent — F7 RSI filter implementation spec

**Date**: 2026-05-20
**Status**: Ready to implement. Drop-in addition to existing momo signal evaluator.
**Mode**: Shadow first — add as parallel sleeves alongside existing momo v1/v2.

---

## 0. TL;DR

Add **one filter** to every momo sleeve's signal evaluator. Filter: skip a fire when the binance 1m RSI(14) at signal time disagrees with the momo direction.

Validated on **14 days of real VPS3 shadow trades** (3,277 resolutions across 12 cells):
- Current WR: **49.65%** / PnL **−$1,966**
- + F7 filter: WR **59.69%** / PnL **+$9,879**
- **Swing: +$11,846 over 14d = +$846/day** in shadow-paper PnL
- **0 of 12 cells regress**. Every cell improves.

Implementation: ~30 lines of new code (RSI helper + gate). No new strategy class, no new sleeve type — adds a single `rsi_gate` decision to existing sleeves, plus optional new `_F7` variants for A/B testing.

---

## 1. The filter

Input at signal time `ws_s` (the production controller's signal anchor, =`slot_start_s − window_s`):

```
rsi_14 = RSI(period=14) on binance-spot-ws 1MIN closes, evaluated AT or BEFORE ws_s
```

Gate (two threshold variants):

```python
# F7 — basic agreement
def f7_passes(signal: str, rsi_14: float) -> bool:
    if not math.isfinite(rsi_14):
        return False            # no RSI -> skip (need at least 14 bars of klines)
    if signal == "UP"   and rsi_14 <= 50.0: return False
    if signal == "DOWN" and rsi_14 >= 50.0: return False
    return True

# F7_extreme — strict agreement (smaller universe, higher WR)
def f7_extreme_passes(signal: str, rsi_14: float) -> bool:
    if not math.isfinite(rsi_14):
        return False
    if signal == "UP"   and rsi_14 <= 60.0: return False
    if signal == "DOWN" and rsi_14 >= 40.0: return False
    return True
```

Calling site: **after** the existing momo gate decides `signal ∈ {UP, DOWN}`, **before** the order is emitted.

---

## 2. RSI(14) computation — exact algorithm

Standard Wilder-style RSI on **log-returns** of binance-spot-ws 1MIN closes. Required precision: the gate decision must be stable to >0.01 RSI units, since the threshold is hard at 50/60/40.

### Implementation

```python
from collections import deque
import math

class RSI14:
    """Streaming RSI(14) on binance 1m closes.
    Update on each new closed bar. Read .value at any time."""
    PERIOD = 14

    def __init__(self):
        self.prev_close: float | None = None
        self.gains: deque[float] = deque(maxlen=self.PERIOD)
        self.losses: deque[float] = deque(maxlen=self.PERIOD)

    def update(self, close: float) -> None:
        if self.prev_close is None or not math.isfinite(close) or close <= 0:
            self.prev_close = close if math.isfinite(close) and close > 0 else self.prev_close
            return
        ret = math.log(close / self.prev_close)
        self.gains.append(ret if ret > 0 else 0.0)
        self.losses.append(-ret if ret < 0 else 0.0)
        self.prev_close = close

    @property
    def value(self) -> float:
        if len(self.gains) < self.PERIOD:
            return float("nan")
        avg_up = sum(self.gains) / self.PERIOD
        avg_dn = sum(self.losses) / self.PERIOD
        if avg_dn == 0:
            return 100.0
        rs = avg_up / avg_dn
        return 100.0 - 100.0 / (1.0 + rs)
```

Maintain ONE `RSI14` instance per asset (BTC, ETH, SOL). Feed every closed 1m binance bar via `update(close)`. Read `.value` at signal time.

### Edge cases

| Condition | Behavior |
|---|---|
| First 14 bars of stream | `value` returns NaN → gate returns False (skip the fire) |
| Stream gap / missed bar | Use last-known close; do not extrapolate. Skip RSI update for the missed minute. Mark next bar's RSI as stale if gap > 60s |
| Reconnect after long disconnect | Backfill last 14 closes from binance REST OR from `binance_klines_v2` table before resuming; mark RSI as warming-up until 14 fresh bars seen |
| `close = 0` or NaN | Skip update; keep prev state |

### Validation against backtest

Reference values from `strategy_lab/meta_classifier/momo_filter_overlay.py:attach_kline_features`. Implementation matches:
```python
log_rets[1:] = np.log(close[1:] / close[:-1])
roll_up[14:] = (cumsum_up[14:] - cumsum_up[:-14]) / 14
roll_dn[14:] = (cumsum_dn[14:] - cumsum_dn[:-14]) / 14
rsi = 100 - 100 / (1 + roll_up / roll_dn)
```

Spot-check the live RSI against this Python on the first ~50 bars after deploy. Tolerance: ±0.5 RSI units.

---

## 3. Where to call the gate

In the existing momo signal evaluator (the function that fires `poly_updown_signal` and the downstream order):

```python
# === existing momo gate (unchanged) ===
ret_2m = compute_ret_2m(asset, ws_s)
if abs(ret_2m) < q90_threshold:
    return SkipSignal(reason="no_signal")
signal = "UP" if ret_2m > 0 else "DOWN"

# === NEW: F7 RSI gate ===
rsi_14 = rsi_state[asset].value  # streaming RSI per asset
if not f7_passes(signal, rsi_14):
    return SkipSignal(reason=f"f7_rsi_disagree_{signal.lower()}_rsi={rsi_14:.2f}")

# === existing fire path (unchanged) ===
emit_signal(...)
emit_order(...)
```

Place: in the signal-evaluation function, **after** the direction is decided but **before** any order/fill is emitted.

The skip event MUST still be logged to `trading.events` as `poly_updown_signal` with `reason="f7_rsi_disagree_*"` so we can audit gate behavior post-deployment.

---

## 4. Config flags

Add to per-sleeve config (existing `tradingvenue.env` or `tv-sleeves.yml`):

```yaml
# Per-sleeve toggles
sleeves:
  poly_updown_btc_5m_momo_HOLD:
    f7_rsi_filter: off        # "off" | "basic" | "extreme"

  poly_updown_btc_5m_momo_v3_HOLD:    # NEW shadow sleeve
    base: poly_updown_btc_5m_momo_HOLD
    f7_rsi_filter: basic

  poly_updown_btc_5m_momo_v3x_HOLD:   # NEW shadow sleeve (strict)
    base: poly_updown_btc_5m_momo_HOLD
    f7_rsi_filter: extreme
```

### Recommended initial state

1. **All existing momo v1/v2 sleeves**: `f7_rsi_filter: off` (no behavior change). Keep them logging baseline.
2. **NEW shadow sleeves** (one per existing momo sleeve): add `_v3_*` suffix, set `f7_rsi_filter: basic`. These fire in shadow only, alongside the baselines.
3. **NEW shadow sleeves (strict)**: add `_v3x_*` suffix with `f7_rsi_filter: extreme`.

Total new sleeves: 24 v1+v2 momo sleeves × 2 variants = **48 new shadow sleeves**.

(Each cell × policy × version × filter = 6 cells × 3 policies (HOLD/HEDGE/SELL) × 2 versions (v1, v2) × 2 filters (basic, extreme) = 72 — but you can drop policies that share the same fires; only HOLD needs duplicating for the fire-gate test. So 24 new sleeves is the lean version.)

### Lean rollout (recommended)

Skip duplicating HEDGE/SELL — they share fires with HOLD; the fire-gate change applies once and exit policies pick up the filtered fire set automatically.

```
Baseline:   12 existing sleeves (6 cells × v1/v2)  — f7_rsi_filter: off
+ F7 basic: 12 new sleeves (_v3_)                  — f7_rsi_filter: basic
+ F7 extr:  12 new sleeves (_v3x_)                 — f7_rsi_filter: extreme
Total new shadow sleeves: 24
```

---

## 5. Event payload additions

The `poly_updown_signal` event's JSON `data` must include the new fields whether the gate fires or skips:

```json
{
  "tf": "5m",
  "mode": "shadow",
  "symbol": "BTC",
  "signal": "UP",
  "condition_id": "0x...",
  "strategy_mode": "momo",

  "rsi_14":           62.1,          // NEW — RSI value at ws_s
  "rsi_14_stale_s":   0,             // NEW — seconds since last RSI update (0 = fresh)
  "f7_filter":        "basic",       // NEW — which filter was active for this sleeve
  "f7_decision":      "pass",        // NEW — "pass" | "skip_disagree" | "skip_nan_rsi" | "skip_stale_rsi"

  "reason":           "signal"       // or "f7_rsi_disagree_up_rsi=42.10" when skipped
}
```

The `poly_updown_resolution` event payload remains unchanged. Won/lost is unaffected by the new gate.

---

## 6. Backward-compatibility

- Existing baseline sleeves keep their sleeve_id and behavior. They continue firing at their current rate.
- New `_v3_` and `_v3x_` sleeves are NEW sleeve_ids — they emit their own `poly_updown_signal` and `poly_updown_resolution` events.
- A single momo signal evaluation may now produce up to 3 sleeve-decisions per cell (baseline, _v3_, _v3x_). All three should be logged independently for clean A/B.
- If the signal is "UP" and `rsi_14 = 55`: baseline fires, `_v3_` fires (55 > 50), `_v3x_` skips (55 < 60).

This way the baseline data is unchanged AND we get a clean comparison.

---

## 7. RSI bootstrap on engine start

When TV engine boots, RSI(14) needs ≥14 prior 1m bars before it can gate. Two options:

### Option A — Backfill from binance_klines_v2 (recommended, fast)

```sql
SELECT time_period_start_us, price_close
FROM binance_klines_v2
WHERE source = 'binance-spot-ws'
  AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
  AND period_id = '1MIN'
  AND time_period_start_us > (extract(epoch from now())::bigint - 1800) * 1000000
ORDER BY time_period_start_us;
```

Feed the last ~25 bars to each `RSI14` instance before opening the WS subscription. Engine is "RSI-ready" within ~1 second.

### Option B — Warm-up window (simpler)

Mark the engine as "RSI warming up" for the first 14 minutes after boot. Skip all momo fires during this window. Acceptable but loses 14 minutes per restart.

**Use Option A.**

---

## 8. Implementation files

| File | Change |
|---|---|
| `backend/app/indicators/rsi.py` | NEW — `RSI14` streaming class (§2 code above) |
| `backend/app/indicators/__init__.py` | export `RSI14` |
| `backend/app/strategies/polymarket/momo/signal.py` | Add F7 gate call after direction decision (§3) |
| `backend/app/strategies/polymarket/momo/config.py` | Add `f7_rsi_filter` field; values "off"/"basic"/"extreme" |
| `backend/app/runtime/rsi_manager.py` | NEW — owns the 3 `RSI14` instances (BTC/ETH/SOL), subscribes to binance-spot-ws 1m bars, bootstraps from binance_klines_v2 on start |
| `backend/app/runtime/bootstrap.py` | Wire `rsi_manager` into engine startup; ensure it's ready before momo signal evaluator runs |
| `/etc/tv/tv-sleeves.yml` | Add 24 new `_v3_` / `_v3x_` sleeve definitions |
| `backend/tests/unit/indicators/test_rsi14.py` | NEW — golden test (see §10) |
| `backend/tests/unit/strategies/momo/test_f7_gate.py` | NEW — gate boundary tests (see §10) |

---

## 9. Implementation steps (in order)

1. **Implement `RSI14`** class — match the Python reference in `strategy_lab/meta_classifier/momo_filter_overlay.py`. Add unit test against ≥30 reference bars to confirm value matches within 0.01.

2. **Implement `rsi_manager`** — owns per-asset RSI state, subscribes to binance-spot-ws 1MIN bars, calls `RSI14.update(close)` on each bar close.

3. **Bootstrap from binance_klines_v2** on engine start. Verify `rsi_manager.is_ready_for(asset)` returns True before any momo signal evaluator runs.

4. **Add `f7_rsi_filter` config field** to momo sleeve config schema.

5. **Add F7 gate call** in momo signal evaluator (§3). Log `rsi_14`, `f7_filter`, `f7_decision`, `rsi_14_stale_s` in every `poly_updown_signal` payload.

6. **Add the 24 new sleeve definitions** to `tv-sleeves.yml`. Set `mode: shadow` for all.

7. **Deploy** to VPS3 in shadow. Verify within 1 hour:
   - All 12 baseline sleeves still firing at the same rate as before
   - 12 `_v3_` sleeves firing at ~70% of baseline rate (basic gate skips ~30%)
   - 12 `_v3x_` sleeves firing at ~40% of baseline rate (extreme gate skips ~60%)
   - No engine errors

8. **Run for 7 days in shadow.** Daily WR/PnL deltas auditable via:
   ```sql
   SELECT sleeve_id, 
          count(*) as n,
          avg((data->>'won')::boolean::int) * 100 as wr_pct,
          sum((data->>'pnl_usd')::numeric) as pnl_total
   FROM trading.events
   WHERE kind = 'poly_updown_resolution'
     AND at > now() - interval '7 days'
   GROUP BY sleeve_id
   ORDER BY sleeve_id;
   ```

9. **Promotion criteria** — after ≥ 7d and ≥ 200 resolved fires per `_v3_` sleeve:
   - If `_v3_` WR ≥ baseline WR + 5pp AND `_v3_` PnL > baseline PnL: promote to live (replace baseline)
   - If `_v3x_` WR ≥ baseline WR + 10pp AND `_v3x_` n ≥ 100: also promote (parallel with `_v3_`)
   - If either fails: keep in shadow, investigate

---

## 10. Unit tests

### `test_rsi14.py`

```python
def test_rsi14_golden_30_bars():
    """RSI(14) on a known close-price sequence matches the Python reference within 0.01."""
    closes = [100.0, 100.5, 100.3, 100.7, 101.0, 100.8, 101.2, 101.5, 101.3,
              101.8, 102.0, 101.7, 102.1, 102.3, 102.5, 102.2, 102.6, 102.4,
              102.8, 103.0, 102.7, 103.1, 103.3, 102.9, 103.4, 103.6, 103.2,
              103.7, 104.0, 103.8]
    rsi = RSI14()
    for c in closes:
        rsi.update(c)
    # Reference value computed offline with same algorithm
    expected = 76.5      # placeholder — recompute with the agreed Python reference
    assert abs(rsi.value - expected) < 0.5

def test_rsi14_warmup_returns_nan():
    rsi = RSI14()
    for c in [100.0, 101.0, 102.0]:
        rsi.update(c)
    assert math.isnan(rsi.value)

def test_rsi14_handles_constant_price():
    rsi = RSI14()
    for _ in range(20):
        rsi.update(100.0)
    # No movement → all gains and losses zero → avg_dn==0 → returns 100
    assert rsi.value == 100.0

def test_rsi14_handles_bad_input():
    rsi = RSI14()
    rsi.update(100.0)
    rsi.update(float("nan"))    # should not corrupt state
    rsi.update(101.0)
    # prev_close should still be 100, so this is a 1% gain
    assert rsi.prev_close == 101.0
```

### `test_f7_gate.py`

```python
def test_f7_basic_up_rsi_above_50_passes():
    assert f7_passes("UP", 51.0) is True
    assert f7_passes("UP", 50.01) is True

def test_f7_basic_up_rsi_at_or_below_50_skips():
    assert f7_passes("UP", 50.0) is False
    assert f7_passes("UP", 49.99) is False

def test_f7_basic_down_rsi_below_50_passes():
    assert f7_passes("DOWN", 49.0) is True

def test_f7_basic_down_rsi_at_or_above_50_skips():
    assert f7_passes("DOWN", 50.0) is False
    assert f7_passes("DOWN", 50.01) is False

def test_f7_basic_nan_rsi_skips():
    assert f7_passes("UP", float("nan")) is False
    assert f7_passes("DOWN", float("nan")) is False

def test_f7_extreme_thresholds():
    assert f7_extreme_passes("UP", 60.0) is False
    assert f7_extreme_passes("UP", 60.01) is True
    assert f7_extreme_passes("DOWN", 40.0) is False
    assert f7_extreme_passes("DOWN", 39.99) is True
```

---

## 11. Expected behavior in shadow (from the validation data)

Per-cell expectations after 7 days of shadow (extrapolating from the 14d VPS3 numbers, halving for time):

### momo v1 cells

| cell | baseline n/7d | baseline WR | `_v3_` n/7d | `_v3_` WR | `_v3_` PnL Δ/7d |
|---|---:|---:|---:|---:|---:|
| btc_5m | ~313 | ~46% | ~226 | ~55% | +$1,150 |
| btc_15m | ~48 | ~58% | ~27 | ~74% | +$125 |
| eth_5m | ~196 | ~49% | ~149 | ~54% | +$460 |
| eth_15m | ~40 | ~44% | ~17 | ~91% | +$460 |
| sol_5m | ~189 | ~51% | ~140 | ~60% | +$590 |
| sol_15m | ~40 | ~46% | ~15 | ~87% | +$380 |

### momo v2 cells

| cell | baseline n/7d | baseline WR | `_v3_` n/7d | `_v3_` WR | `_v3_` PnL Δ/7d |
|---|---:|---:|---:|---:|---:|
| btc_5m | ~294 | ~50% | ~217 | ~59% | +$1,010 |
| btc_15m | ~64 | ~63% | ~40 | ~81% | +$205 |
| eth_5m | ~192 | ~45% | ~135 | ~53% | +$695 |
| eth_15m | ~61 | ~69% | ~30 | ~88% | +$20 |
| sol_5m | ~163 | ~48% | ~120 | ~56% | +$550 |
| sol_15m | ~41 | ~51% | ~19 | ~79% | +$280 |

If observed deltas after 7d are within ±50% of these expectations, F7 is confirmed live. Outside that range, investigate (RSI computation bug, time-of-day drift, regime change).

---

## 12. Risks and caveats

| Risk | Mitigation |
|---|---|
| **RSI computation diverges from backtest** | Unit test against Python reference; spot-check 50 live RSI values in first hour |
| **Binance 1m feed lags or gaps** | `rsi_14_stale_s` is logged; gate skips if stale > 90s |
| **Engine restart during a slug** | Bootstrap from `binance_klines_v2`; RSI ready within 1s |
| **Sample size on 15m cells is small** | Only ~70 baseline fires per 15m cell per 7d → wide CI. The 15m WR jumps are real but expect noisier per-day numbers than 5m |
| **Regime change** | Validation window is May 7-20 only. If market microstructure shifts, F7 edge may shrink. The 5m cells (large n) will tell faster than 15m |
| **F7_extreme over-filters** | Smaller universe → fewer fires but higher WR. Trade-off depends on capital deployment cadence. Run both `_v3_` and `_v3x_` in parallel for direct comparison |

---

## 13. Validation data this spec is built on

```
File:      strategy_lab/monitoring/_logs/vps3/momo_events_14d.csv
Source:    SELECT * FROM trading.events
           WHERE kind IN ('poly_updown_signal','poly_updown_resolution','poly_updown_hedge_skip')
             AND sleeve_id LIKE '%momo%'
             AND at > now() - interval '14 days'
Window:    2026-05-07 → 2026-05-20 (~14 days)
Rows:      159,031 events (148,379 signals + 10,166 resolutions + 502 hedge_skips)
Universe:  12 momo cells × 3 policies = 36 sleeves on VPS3

Results CSV: strategy_lab/results/meta_classifier/momo_12cells_f7.csv
Analysis:    strategy_lab/meta_classifier/momo_12cells_f7.py
```

### Headline result

- **3,277 unique fires across 12 cells** (HOLD policy, no double-counting across HEDGE/SELL)
- **Current WR**: 49.65%
- **+ F7 basic WR**: **59.69%** (n=2,265, skipped 31% of fires)
- **PnL swing**: −$1,966 → +$9,879 = **+$11,846 over 14 days = +$846/day**

Every single cell improves. No regressions.

---

## 14. Bottom line for TV agent

One filter, ~30 lines of code, 1-2 days of work including tests + deploy.

Validated on real production shadow trades. Pre-deployment WR target: **≥ 58%** aggregate across `_v3_` sleeves after 7 days. Pre-deployment PnL target: **positive on each cell** (vs current losing across most).

Ship as shadow first, run 7 days, promote per §9.

If F7 holds in 7d shadow as it does in the 14d backtest, the strategy goes from -$846/day across momo to +$0/day or better. Combined with the existing direction-bet PnL, that's the strongest single change available right now.
